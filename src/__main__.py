"""启动个人 Agent。

准备：
1. 在仓库根目录安装依赖：uv sync
2. 复制 .env.example 为 .env 并填入凭据
3. 在 CHANNELS 里写上要启用的通道，然后 uv run python -m src
"""

import asyncio

from .capabilities.mcp import cleanup_mcp, connect_mcp
from .channels.base import Channel
from .channels.registry import build, enabled_names, missing_settings
from .config import (
    ASSISTANT_NAME,
    DATA_DIR,
    DB_PATH,
    LOG_DIR,
    STORE_DIR,
    TRACE_LOG,
    WORKSPACE_DIR,
    require_env,
)
from .gateway import Gateway
from .memory import ensure_workspace
from .models import active_backend
from .state.db import init_db


async def _prepare() -> None:
    for directory in (WORKSPACE_DIR, STORE_DIR, DATA_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    await init_db()
    ensure_workspace()


async def _boot(names: list[str]) -> None:
    """目录和通道在同一个事件循环里准备。"""
    await _prepare()
    channels = build(names)
    gateway = Gateway()
    for channel in channels:
        gateway.register(channel)
    print(f"{ASSISTANT_NAME} 已启动！通道：{', '.join(channel.name for channel in channels)}")
    print(f"模型：{active_backend().name} / {active_backend().model_name()}")
    print(f"工作目录：{WORKSPACE_DIR}")
    print(f"数据库：{DB_PATH}")
    print(f"过程日志：{TRACE_LOG}")
    await _serve(channels, gateway)


async def _serve(channels: list[Channel], gateway: Gateway) -> None:
    """MCP 和通道跑在同一个事件循环里。有终端通道时，终端退出就停掉其余通道。"""
    for notice in await connect_mcp():
        print(notice)
    tasks = [asyncio.create_task(channel.start(gateway), name=channel.name) for channel in channels]
    try:
        await _wait_ready(channels, tasks)
        gateway.on_running()
        for channel in channels:
            allow = getattr(channel, "allow_input", None)
            if allow is not None:
                allow()
        if any(channel.name == "cli" for channel in channels):
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    raise exc
        else:
            await asyncio.gather(*tasks)
    finally:
        for channel in channels:
            stop = getattr(channel, "request_stop", None)
            if stop is not None:
                stop()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        gateway.shutdown()
        await cleanup_mcp()


async def _wait_ready(channels: list[Channel], tasks: list[asyncio.Task]) -> None:
    """等每个通道声明就绪。启动失败时把异常抛出来，不拉起调度器。"""
    for channel, task in zip(channels, tasks):
        wait = getattr(channel, "wait_until_ready", None)
        if wait is None:
            if task.done():
                task.result()
            continue
        ready = asyncio.create_task(wait())
        done, _pending = await asyncio.wait({ready, task}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            if not ready.done():
                ready.cancel()
            task.result()


def main() -> None:
    """主函数。"""
    names = enabled_names()
    backend = active_backend()
    missing = list(backend.missing_settings()) + missing_settings(names)
    require_env(missing)
    backend.configure()
    asyncio.run(_boot(names))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n正在关闭...")
