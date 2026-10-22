"""手写的 agent loop。停止条件都在 run_loop 里，不经过 Runner。

每一圈都请求当前 .env 里的模型。模型决定调用哪个工具；循环只负责执行，并判断该停还是再转一圈。
工具只允许碰同目录下的 workspace/。问题由你在终端里输入，下面 main 里的注释是可以照着问的例子。
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent / "workspace"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
MAX_FILE_CHARS = 100_000


class MaxTurnsExceeded(Exception):
    """圈数用尽。对应 SDK 里的 MaxTurnsExceeded。调用方得到异常，没有最终正文。"""

    def __init__(self, message: str, finished: list[str]) -> None:
        super().__init__(message)
        self.finished = finished


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: str


@dataclass
class ModelReply:
    """一圈模型回复。没有 tool_calls 时，text 就是可以结束的正文。"""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    output_items: list[dict] = field(default_factory=list)


@dataclass
class Scene:
    """一场真实对话。user 交给模型，behavior 和 max_turns 由循环解释。"""

    title: str
    behavior: str
    max_turns: int
    user: str


@dataclass
class Pause:
    """人工审批。循环已经退出，待批准的工具还没执行，也没有最终正文。"""

    scene: Scene
    items: list[dict]
    turn: int
    pending: list[ToolCall]
    finished: list[str]


def load_env(path: Path) -> None:
    """读仓库根目录的 .env。已经存在的环境变量不覆盖。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def client_and_model() -> tuple[OpenAI, str]:
    """按 MODEL_PROVIDER 连接，和主程序用同一家供应商。"""
    load_env(ENV_PATH)
    provider = os.getenv("MODEL_PROVIDER", "openai").strip().lower() or "openai"
    if provider == "vllm":
        base_url = os.getenv("VLLM_BASE_URL", "").strip()
        if not base_url:
            raise SystemExit("缺少 VLLM_BASE_URL")
        client = OpenAI(
            api_key=os.getenv("VLLM_API_KEY", "empty").strip() or "empty",
            base_url=base_url,
        )
        model = os.getenv("VLLM_MODEL", "Qwen3.6").strip() or "Qwen3.6"
        return client, model
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("缺少 OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    client = OpenAI(api_key=api_key, base_url=base_url)
    model = os.getenv("OPENAI_MODEL", "gpt-4.1").strip() or "gpt-4.1"
    return client, model


def resolve_workspace_path(raw: str) -> Path:
    """把路径解析到沙盒工作区内，拒绝逃出该目录的路径。"""
    if not raw or not raw.strip():
        raise ValueError("path is empty")
    root = ROOT.resolve()
    candidate = Path(raw)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path escapes workspace")
    return path


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[输出已截断]"


def _reject_glob(pattern: str) -> str | None:
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        return "模式无效。"
    return None


def read_file(path: str) -> str:
    """读取沙盒工作区内的文本文件。path 是相对工作区的路径。"""
    try:
        file = resolve_workspace_path(path)
    except ValueError as exc:
        return str(exc)
    if not file.is_file():
        return "文件不存在。"
    return _trim(file.read_text(encoding="utf-8"), MAX_FILE_CHARS)


def write_file(path: str, content: str) -> str:
    """把文本写入沙盒工作区内的文件。父目录不存在时会创建。"""
    try:
        file = resolve_workspace_path(path)
    except ValueError as exc:
        return str(exc)
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.parent.resolve().is_relative_to(ROOT.resolve()):
        return "path escapes workspace"
    file.write_text(content, encoding="utf-8")
    return "已写入。"


def glob_files(pattern: str) -> str:
    """按 glob 列出沙盒工作区内的文件。例如 *.txt。"""
    rejected = _reject_glob(pattern)
    if rejected:
        return rejected
    root = ROOT.resolve()
    matches: list[str] = []
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        matches.append(str(resolved.relative_to(root)).replace("\\", "/"))
        if len(matches) >= 200:
            break
    if not matches:
        return "没有匹配的文件。"
    return "\n".join(sorted(matches))


def grep_files(pattern: str, glob_pattern: str = "**/*") -> str:
    """在沙盒工作区文件中搜索正则。glob_pattern 用来缩小文件范围。"""
    rejected = _reject_glob(glob_pattern)
    if rejected:
        return rejected
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"正则无效：{exc}"
    root = ROOT.resolve()
    lines: list[str] = []
    for path in root.glob(glob_pattern):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or resolved.stat().st_size > 1_000_000:
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = str(resolved.relative_to(root)).replace("\\", "/")
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                lines.append(f"{relative}:{number}:{line[:300]}")
                if len(lines) >= 50:
                    return "\n".join(lines) + "\n...[结果已截断]"
    return "\n".join(lines) if lines else "没有匹配。"


TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "glob_files": glob_files,
    "grep_files": grep_files,
}
# 写文件会改动沙盒，模型点名后先退出循环，等调用方批准。其余工具直接执行。
NEEDS_APPROVAL = {"write_file"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "读取沙盒工作区内的文本文件。path 是相对工作区的路径。",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对工作区的路径"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "把文本写入沙盒工作区内的文件。父目录不存在时会创建。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对工作区的路径"},
                "content": {"type": "string", "description": "要写入的全文"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "glob_files",
        "description": "按 glob 列出沙盒工作区内的文件。例如 *.txt。",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "glob 模式"}},
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "grep_files",
        "description": "在沙盒工作区文件中搜索正则。glob_pattern 用来缩小文件范围。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则"},
                "glob_pattern": {"type": "string", "description": "文件范围，默认 **/*"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
]


def log_json(title: str, payload: object) -> None:
    """打印一份发给模型或模型返回的工具消息。"""
    print(title)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def tool_messages(items: list[dict]) -> list[dict]:
    """取出对话里和工具有关的消息。"""
    return [
        item
        for item in items
        if item.get("type") in {"function_call", "function_call_output"}
    ]


def remember_tool_result(items: list[dict], call: ToolCall, result: str) -> None:
    """把工具结果按 call_id 写回对话，下一次请求会带上它。"""
    payload = {"type": "function_call_output", "call_id": call.call_id, "output": result}
    log_json("写回下一轮的工具结果：", payload)
    items.append(payload)


def run_tool(call: ToolCall) -> str:
    tool = TOOLS.get(call.name)
    if tool is None:
        return f"未知工具：{call.name}"
    try:
        return tool(**call.arguments)
    except TypeError as exc:
        return f"参数无效：{exc}"


def call_model(client: OpenAI, model: str, items: list[dict]) -> ModelReply:
    """请求一次模型，把工具调用和正文拆开。"""
    sent = tool_messages(items)
    if sent:
        log_json("本次发给模型的工具消息：", sent)
    response = client.responses.create(
        model=model,
        input=items,
        tools=TOOL_SCHEMAS,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    calls: list[ToolCall] = []
    for item in response.output:
        if getattr(item, "type", None) != "function_call":
            continue
        raw = getattr(item, "arguments", "") or "{}"
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(
            ToolCall(
                name=getattr(item, "name", ""),
                arguments=arguments,
                call_id=getattr(item, "call_id", "") or "",
            )
        )
    output_items = [item.model_dump(exclude_none=True) for item in response.output]
    returned = [item for item in output_items if item.get("type") == "function_call"]
    if returned:
        log_json("模型返回的工具调用：", returned)
    return ModelReply(
        text=(response.output_text or "").strip(),
        tool_calls=calls,
        output_items=output_items,
    )


def run_loop(
    scene: Scene,
    client: OpenAI,
    model: str,
    *,
    items: list[dict] | None = None,
    turn: int = 0,
    finished: list[str] | None = None,
) -> str | Pause:
    """一圈等于一次模型调用。停在最终正文、工具提前收尾、人工审批，或圈数用尽。"""
    if items is None:
        items = [
            {
                "role": "system",
                "content": (
                    "你只能通过工具了解沙盒工作区，不要编造文件内容。"
                    "路径都相对工作区。需要查文件时必须调用工具。"
                ),
            },
            {"role": "user", "content": scene.user},
        ]
    if finished is None:
        finished = []
    while True:
        turn += 1
        # 和 SDK 一样：进入下一圈、调用模型之前先查圈数。
        if turn > scene.max_turns:
            reason = f"Max turns ({scene.max_turns}) exceeded"
            print(f"第 {turn} 圈还没调用模型就停止：{reason}")
            raise MaxTurnsExceeded(reason, list(finished))

        reply = call_model(client, model, items)
        if reply.tool_calls:
            detail = "；".join(f"{call.name}{call.arguments}" for call in reply.tool_calls)
            print(f"第 {turn} 圈：模型要调用 {detail}")
        else:
            print(f"第 {turn} 圈：模型只回了正文：{reply.text}")

        # 没有工具调用：这条正文就是最终输出，循环结束。
        if not reply.tool_calls:
            print("停止：FinalOutput。这次回复没有工具调用，正文就是最终结果。")
            print(f"模型被调用了 {turn} 次。")
            return reply.text

        pending = [call for call in reply.tool_calls if call.name in NEEDS_APPROVAL]
        ready = [call for call in reply.tool_calls if call.name not in NEEDS_APPROVAL]
        ready_results = [run_tool(call) for call in ready]
        for call, result in zip(ready, ready_results):
            preview = result.replace("\n", " / ")
            print(f"  {call.name} → {preview}")
            finished.append(f"{call.name} → {preview}")

        # 要批准的工具先不执行。循环把控制权交还给调用方，这一轮没有最终正文。
        if pending:
            items.extend(reply.output_items)
            for call, result in zip(ready, ready_results):
                remember_tool_result(items, call, result)
            print("停止：Interruption。工具要人工批准，循环退出，没有最终回复。")
            for call in pending:
                print(f"  待批准 {call.name}{call.arguments}")
            print(f"模型被调用了 {turn} 次。")
            return Pause(scene, items, turn, pending, finished)

        # 工具结果不再送回模型，第一个工具的输出直接当最终结果。
        if scene.behavior == "stop_on_first_tool":
            print("停止：stop_on_first_tool。第一个工具的输出就是最终结果，不再调用模型。")
            print(f"模型被调用了 {turn} 次。")
            return ready_results[0]

        if scene.behavior != "run_llm_again":
            raise ValueError(f"未知的 tool_use_behavior：{scene.behavior}")

        # 默认行为：模型刚才的回复和工具结果都写回，再转一圈。
        items.extend(reply.output_items)
        for call, result in zip(ready, ready_results):
            remember_tool_result(items, call, result)
        print("继续：run_llm_again。工具结果写回消息，再转一圈。")


def resume(pause: Pause, client: OpenAI, model: str, approved: bool) -> str | Pause:
    """调用方作完决定后，从退出的地方把循环接回去。"""
    for call in pause.pending:
        if approved:
            result = run_tool(call)
            label = "已批准"
        else:
            result = "用户拒绝执行该工具。文件没有改动。请告诉用户写入被拒绝，不要声称已经写好。"
            label = "已拒绝"
        preview = result.replace("\n", " / ")
        print(f"  {label} {call.name} → {preview}")
        pause.finished.append(f"{label} {call.name} → {preview}")
        remember_tool_result(pause.items, call, result)
    print("调用方已作决定，从退出的地方恢复循环。")
    return run_loop(
        pause.scene,
        client,
        model,
        items=pause.items,
        turn=pause.turn,
        finished=pause.finished,
    )


def seed_notes() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "notes.txt").write_text(
        "喝水提醒写在这里。\nagent loop 在没有工具调用时停止。\n",
        encoding="utf-8",
    )


def main() -> None:
    # 问之前可以改这两项，也可以在终端里输入 behavior=... 或 max_turns=...。
    # 正文结束：behavior=run_llm_again，max_turns=6
    #   用 grep_files 搜索 pattern 为 loop、glob_pattern 为 *.txt。看到工具结果后，用一句中文说出笔记里关于停止的那句话，不要再调用工具。
    # 工具提前结束：behavior=stop_on_first_tool，max_turns=6
    #   调用 read_file，path 为 notes.txt。这一步只调用工具，不要自己编写文件内容。
    # 圈数用尽：behavior=run_llm_again，max_turns=2
    #   先调用 glob_files，pattern 为 *.txt。看到结果后不要写最终回答，必须再调用一次 glob_files，pattern 仍为 *.txt。两次工具调用都完成之前，禁止只用文字结束。
    #   循环抛出 Max turns exceeded，没有最终回复。
    # 人工审批：behavior=run_llm_again，max_turns=6。write_file 会让循环先退出。
    #   调用 write_file，把「明天下午三点开会」写入 reminder.txt。写完后用一句话确认。
    #   看到待批准后输入 y 才会真的写并恢复循环；其他键是拒绝。
    behavior = "run_llm_again"
    max_turns = 6
    seed_notes()
    client, model = client_and_model()
    print(f"模型 {model}")
    print("输入问题后回车。behavior=stop_on_first_tool 或 max_turns=2 用来改停止方式。空行退出。")
    print("write_file 需要批准，循环会先退出；圈数用尽时没有最终回复。")
    while True:
        try:
            line = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            return
        if line.startswith("behavior="):
            behavior = line.split("=", 1)[1].strip() or behavior
            print(f"停止方式改为 {behavior}")
            continue
        if line.startswith("max_turns="):
            raw = line.split("=", 1)[1].strip()
            try:
                max_turns = int(raw)
            except ValueError:
                print("圈数要是整数。")
                continue
            print(f"圈数上限改为 {max_turns}")
            continue
        print(f"behavior={behavior} | max_turns={max_turns}")
        scene = Scene("手动询问", behavior, max_turns, line)
        try:
            outcome = run_loop(scene, client, model)
            while isinstance(outcome, Pause):
                try:
                    answer = input("批准执行？y 恢复循环，其他键拒绝：").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    print("没有作决定。循环不再恢复，仍然没有最终回复。")
                    outcome = None
                    break
                outcome = resume(outcome, client, model, approved=answer == "y")
        except MaxTurnsExceeded as exc:
            print(f"停止：{exc}")
            print("没有最终回复。圈数用尽时循环把异常抛给调用方，不会把半成品当成正文。")
            if exc.finished:
                print("半路已经执行过：")
                for done in exc.finished:
                    print(f"  {done}")
            else:
                print("还没有工具结果。")
        else:
            if outcome is not None:
                print(f"最终结果：{outcome}")


if __name__ == "__main__":
    main()
