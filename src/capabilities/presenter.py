"""放映 MCP。连接必须发生在执行模型的那条事件循环上。"""

import os

from ..config import PRESENTATIONS_DIR, PRESENTER_DIR, PRESENTER_PYTHON
from .mcp import register


async def _connect() -> tuple[object | None, str | None]:
    """连上放映 MCP。成功返回服务，失败返回给启动日志的原因。"""
    PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    server_py = PRESENTER_DIR / "server.py"
    if not PRESENTER_PYTHON.is_file() or not server_py.is_file():
        return None, f"放映引擎未就绪，缺少 {PRESENTER_PYTHON}"
    from agents.mcp import MCPServerStdio

    env = os.environ.copy()
    env["PRESENTATION_INCOMING_DIR"] = str(PRESENTATIONS_DIR)
    env["PPT_SPEECH_BACKEND"] = "local"
    server = MCPServerStdio(
        params={
            "command": str(PRESENTER_PYTHON),
            "args": [str(server_py)],
            "cwd": str(PRESENTER_DIR),
            "env": env,
        },
        name="ppt-presenter",
        cache_tools_list=True,
        client_session_timeout_seconds=30,
    )
    try:
        await server.connect()
    except Exception as exc:
        await _close(server)
        return None, f"放映 MCP 连接失败：{exc}"
    return server, None


async def _close(server: object) -> None:
    cleanup = getattr(server, "cleanup", None)
    if cleanup is None:
        return
    try:
        await cleanup()
    except Exception:
        pass


register("ppt-presenter", _connect)
