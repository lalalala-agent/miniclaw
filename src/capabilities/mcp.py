"""已连接的 MCP。各项在自己的模块里登记，入口不点名。"""

from collections.abc import Awaitable, Callable

Connector = Callable[[], Awaitable[tuple[object | None, str | None]]]
_connectors: dict[str, Connector] = {}
_servers: list = []
_started = False
_loaded = False


def register(name: str, connect: Connector) -> None:
    """登记一项 MCP。同名会覆盖旧的。connect 返回服务；连不上时返回说明。"""
    _connectors[name] = connect


def load() -> None:
    """导入各 MCP 模块，完成登记。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import presenter, web_search  # noqa: F401


async def connect_mcp() -> list[str]:
    """连上已登记的 MCP。每条说明交给启动日志，失败不阻止启动。"""
    global _started
    load()
    if _started:
        return []
    _started = True
    notices: list[str] = []
    for connect in _connectors.values():
        server, notice = await connect()
        if server is not None:
            _servers.append(server)
            name = getattr(server, "name", "mcp")
            notices.append(f"MCP {name} 已连接。")
        elif notice:
            notices.append(notice)
    return notices


def mcp_servers() -> list:
    """返回已连接的 MCP。还没连上时是空列表。"""
    return list(_servers)


async def cleanup_mcp() -> None:
    """关闭已连接的 MCP。"""
    servers = list(reversed(_servers))
    _servers.clear()
    for server in servers:
        name = getattr(server, "name", "mcp")
        try:
            await server.cleanup()
        except Exception as exc:
            print(f"关闭 MCP {name} 时出错：{exc}")
