"""执行层：握住一条工作从取记忆到产出结果的生命周期。"""

import asyncio
import time

from agents import Agent, RawResponsesStreamEvent, Runner
from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

from .capabilities import tools_for
from .capabilities.mcp import mcp_servers
from .config import ASSISTANT_NAME
from .memory import prompt_context, record_turn
from .models import active_backend
from .state.session import get_session
from .stream_log import close_burst, finish_reasoning, note_stream
from .work import Work

_agent_lock = asyncio.Lock()


async def run_work(work: Work, gateway) -> str:
    """跑完一条工作。日常对话带会话并归档，定时任务两者都不做。"""
    waited = time.monotonic()
    async with _agent_lock:
        delay = time.monotonic() - waited
        if delay >= 0.05:
            work.trace.log(f"等上一轮执行结束，空等 {delay:.2f}s")
        text = await _run_locked(work, gateway)
    if work.event.kind == "message":
        record_turn(work.event.text, text)
        work.trace.log("本轮对话已归档")
    return text


async def _run_locked(work: Work, gateway) -> str:
    instructions = prompt_context(work)
    tools = tools_for(work, gateway)
    servers = mcp_servers()
    backend = active_backend()
    model = backend.model_name()
    settings = backend.model_settings()
    tool_names = "、".join(getattr(tool, "name", type(tool).__name__) for tool in tools) or "无"
    server_names = "、".join(getattr(server, "name", "mcp") for server in servers) or "无"
    session = "开" if work.event.use_session else "关"
    budget = _thinking_note(settings.extra_body)
    work.trace.log(
        f"准备提示 {len(instructions)} 字，工具 {len(tools)} 个（{tool_names}），"
        f"MCP {server_names}，会话{session}，模型 {model}{budget}"
    )
    agent = Agent(
        name=ASSISTANT_NAME,
        instructions=instructions,
        tools=tools,
        mcp_servers=servers,
        model=model,
        model_settings=settings,
    )
    streamed: list[str] = []
    state = {
        "first": False,
        "text": False,
        "turns": 0,
        "tools": {},
        "reasoning": [],
        "reasoning_events": 0,
        "reasoning_written": False,
        "burst_kind": "",
        "burst_count": 0,
    }
    try:
        result = Runner.run_streamed(
            agent,
            work.event.text,
            session=get_session() if work.event.use_session else None,
            max_turns=10,
        )
        work.trace.log("已发起流式请求。接下来的空档是在读会话并等待模型")
        async for event in result.stream_events():
            note_stream(work, event, state)
            thought = reasoning_delta(event)
            if thought:
                await gateway.stream_reasoning(work, thought)
                continue
            if reasoning_finished(event):
                await gateway.finish_reasoning_stream(work)
            delta = text_delta(event)
            if not delta:
                continue
            if not state["text"]:
                state["text"] = True
                await gateway.finish_reasoning_stream(work)
                close_burst(work, state)
                finish_reasoning(work, state, "")
                if state["reasoning_written"]:
                    work.trace.log("事件 response.output_text.delta，开始输出正文")
                else:
                    work.trace.log("事件 response.output_text.delta，开始输出正文。此前没有收到思考内容")
            streamed.append(delta)
            await gateway.stream_delta(work, delta)
        failure = result.run_loop_exception
        if failure is not None:
            raise failure
    except Exception as exc:
        work.trace.log(f"执行失败：{exc}")
        await gateway.stream_finish(work)
        work.notified["streamed"] = False
        return f"出错了：{exc}"
    await gateway.stream_finish(work)
    work.trace.log(f"流式输出结束，共 {len(''.join(streamed))} 字")
    text = reply_text(result.final_output, "".join(streamed))
    if work.notified.get("streamed") and not streamed_covers(text, "".join(streamed)):
        work.notified["streamed"] = False
        work.trace.log("流式正文和最终结果不一致，改为整段再发一次")
    return text


def _thinking_note(extra_body: object) -> str:
    if not isinstance(extra_body, dict):
        return ""
    budget = extra_body.get("thinking_token_budget")
    if not isinstance(budget, int) or budget <= 0:
        return ""
    return f"，思考上限 {budget} token"


_REASONING_DELTA = {
    "response.reasoning_text.delta",
    "response.reasoning_summary_text.delta",
}
_REASONING_DONE = {
    "response.reasoning_text.done",
    "response.reasoning_summary_text.done",
}


def reasoning_delta(event: object) -> str:
    """取出思考正文的增量。"""
    if not isinstance(event, RawResponsesStreamEvent):
        return ""
    if getattr(event.data, "type", None) not in _REASONING_DELTA:
        return ""
    delta = getattr(event.data, "delta", "")
    return delta if isinstance(delta, str) else ""


def reasoning_finished(event: object) -> bool:
    """这一段思考是否已经结束。"""
    if not isinstance(event, RawResponsesStreamEvent):
        return False
    return getattr(event.data, "type", None) in _REASONING_DONE


def text_delta(event: object) -> str:
    """取出模型正文的增量。工具参数和思考过程不往外推。"""
    if not isinstance(event, RawResponsesStreamEvent):
        return ""
    data = event.data
    if isinstance(data, ResponseTextDeltaEvent):
        return data.delta or ""
    if getattr(data, "type", None) == "response.output_text.delta":
        delta = getattr(data, "delta", "")
        return delta if isinstance(delta, str) else ""
    return ""


def reply_text(output: object, streamed: str) -> str:
    """优先用模型的最终正文。没有时退回流式拼出来的文字。"""
    if isinstance(output, str) and output.strip():
        return output
    if output:
        return str(output)
    stripped = streamed.strip()
    return stripped or "完成。"


def streamed_covers(final: str, streamed: str) -> bool:
    """最终正文已经出现在流式输出里时，通道不必再发一遍。"""
    body = final.strip()
    return not body or body in streamed
