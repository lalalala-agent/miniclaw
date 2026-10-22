"""把模型流式事件写成过程日志。执行层只负责一轮的顺序。"""

import time

from agents import RawResponsesStreamEvent, RunItemStreamEvent

from .trace import clip
from .work import Work

_REASONING_LIMIT = 400


def note_stream(work: Work, event: object, state: dict) -> None:
    """记下模型往返、事件类型和思考正文。回复增量本身不逐条写入。"""
    if isinstance(event, RunItemStreamEvent):
        close_burst(work, state)
        _note_item(work, event, state)
        return
    if not isinstance(event, RawResponsesStreamEvent):
        close_burst(work, state)
        work.trace.log(f"事件 {type(event).__name__}")
        return
    kind = getattr(event.data, "type", type(event.data).__name__)
    if kind in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}:
        _append_reasoning(work, state, getattr(event.data, "delta", "") or "", kind)
        return
    if kind in {"response.reasoning_text.done", "response.reasoning_summary_text.done"}:
        close_burst(work, state)
        finish_reasoning(work, state, getattr(event.data, "text", "") or "")
        work.trace.log(f"事件 {kind}")
        return
    if kind == "response.output_text.delta":
        return
    if kind.endswith(".delta"):
        _note_burst(work, state, kind)
        return
    close_burst(work, state)
    opened = not state["first"]
    if opened:
        state["first"] = True
    if kind == "response.created":
        state["turns"] += 1
        if opened:
            work.trace.log("事件 response.created，模型开始生成")
        else:
            work.trace.log(f"事件 response.created，模型第 {state['turns']} 次开始生成")
        return
    if kind == "response.queued":
        work.trace.log("事件 response.queued，请求在模型服务里排队")
        return
    if kind == "response.completed":
        finish_reasoning(work, state, "")
        gap = _gap_note(state)
        work.trace.log(f"事件 response.completed，模型这一次生成结束。{_usage(event.data)}{gap}")
        return
    if kind == "response.incomplete":
        finish_reasoning(work, state, "")
        work.trace.log(f"事件 response.incomplete，模型这一次没有生成完。{_usage(event.data)}")
        return
    if kind == "response.failed":
        work.trace.log(f"事件 response.failed，模型这一次失败：{_failure(event.data)}")
        return
    work.trace.log(f"事件 {_event_label(event.data, kind)}")


def finish_reasoning(work: Work, state: dict, full_text: str) -> None:
    """把已经攒下的思考正文写入日志。同一轮只写一次，超长只留开头。"""
    streamed = "".join(state["reasoning"])
    state["reasoning"] = []
    text = full_text.strip() or streamed.strip()
    count = state["reasoning_events"]
    state["reasoning_events"] = 0
    if not text or state["reasoning_written"]:
        return
    state["reasoning_written"] = True
    parts = ["思考内容"]
    if count:
        parts.append(f"{count} 个增量")
    if len(text) > _REASONING_LIMIT:
        parts.append(f"原文 {len(text)} 字，只保留 {_REASONING_LIMIT} 字")
        text = text[: _REASONING_LIMIT - 1].rstrip() + "…"
    title = parts[0] if len(parts) == 1 else f"{parts[0]}（{'，'.join(parts[1:])}）"
    work.trace.write_block(title, text)


def close_burst(work: Work, state: dict) -> None:
    """同类增量告一段落时记一次总数。"""
    kind = state["burst_kind"]
    count = state["burst_count"]
    state["burst_kind"] = ""
    state["burst_count"] = 0
    if kind and count > 1:
        work.trace.log(f"事件 {kind} 结束，共 {count} 次")


def _append_reasoning(work: Work, state: dict, delta: str, kind: str) -> None:
    if state["burst_kind"] != kind:
        close_burst(work, state)
        state["burst_kind"] = kind
        state["burst_count"] = 0
        work.trace.log(f"事件 {kind}，开始记录思考")
    state["burst_count"] += 1
    state["reasoning_events"] += 1
    if delta:
        state["reasoning"].append(delta)


def _gap_note(state: dict) -> str:
    if state["text"] or state["reasoning_events"] or state["reasoning_written"]:
        return ""
    return "。输出正文前没有收到思考事件，这段时间是模型在服务端生成"


def _note_burst(work: Work, state: dict, kind: str) -> None:
    if state["burst_kind"] == kind:
        state["burst_count"] += 1
        return
    close_burst(work, state)
    state["burst_kind"] = kind
    state["burst_count"] = 1
    work.trace.log(f"事件 {kind}")


def _event_label(data: object, kind: str) -> str:
    item = getattr(data, "item", None)
    if item is None:
        return kind
    item_type = getattr(item, "type", "") or ""
    name = getattr(item, "name", "") or ""
    extra = " ".join(part for part in (item_type, name) if part)
    return f"{kind} {extra}".strip()


def _note_item(work: Work, event: RunItemStreamEvent, state: dict) -> None:
    item = event.item
    if event.name == "tool_called":
        name = getattr(item, "tool_name", None) or "未知工具"
        call_id = getattr(item, "call_id", None) or name
        state["tools"][call_id] = (name, time.monotonic())
        work.trace.log(f"调用工具 {name} {_arguments(item)}")
        return
    if event.name == "tool_output":
        call_id = getattr(item, "call_id", None)
        name, started = state["tools"].pop(call_id, ("工具", None))
        spent = "" if started is None else f"，耗时 {time.monotonic() - started:.2f}s"
        output = clip(str(getattr(item, "output", "")), 180)
        work.trace.log(f"{name} 返回{spent}：{output or '（空）'}")
        return
    if event.name == "reasoning_item_created":
        finish_reasoning(work, state, _reasoning_from_item(item))
        work.trace.log("事件 reasoning_item_created")
        return
    if event.name == "mcp_list_tools":
        work.trace.log("查询 MCP 工具列表")
        return
    work.trace.log(f"过程事件 {event.name}")


def _reasoning_from_item(item: object) -> str:
    raw = getattr(item, "raw_item", None)
    blocks = list(getattr(raw, "content", None) or []) + list(getattr(raw, "summary", None) or [])
    parts = [getattr(block, "text", "") for block in blocks]
    return "\n".join(part for part in parts if part)


def _arguments(item: object) -> str:
    raw = getattr(item, "raw_item", None)
    if isinstance(raw, dict):
        arguments = raw.get("arguments", "")
    else:
        arguments = getattr(raw, "arguments", "")
    text = arguments if isinstance(arguments, str) else str(arguments or "")
    return clip(text, 180)


def _usage(data: object) -> str:
    response = getattr(data, "response", None)
    usage = getattr(response, "usage", None)
    if usage is None:
        return "没有用量数据"
    parts = [f"输入 {usage.input_tokens}，输出 {usage.output_tokens}"]
    reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0)
    if reasoning:
        parts.append(f"其中思考 {reasoning}")
    if cached:
        parts.append(f"命中缓存 {cached}")
    return "，".join(parts)


def _failure(data: object) -> str:
    response = getattr(data, "response", None)
    error = getattr(response, "error", None)
    if error is None:
        return "未知原因"
    message = getattr(error, "message", None) or str(error)
    return clip(str(message), 180)
