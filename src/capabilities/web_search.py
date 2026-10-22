"""千帆网页搜索 MCP。未配置密钥时跳过，不阻止启动。"""

import os

from .mcp import register

_URL = "https://qianfan.baidubce.com/v2/tools/web-search/mcp"
_TIMEOUT = 300
_CONNECT_TIMEOUT = 60


def _http_client(headers=None, timeout=None, auth=None):
    """连接超时 60 秒，读写沿用调用方给的超时。"""
    import httpx2

    if timeout is None:
        built = httpx2.Timeout(_TIMEOUT, connect=_CONNECT_TIMEOUT)
    else:
        built = httpx2.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=timeout.read,
            write=timeout.write,
            pool=timeout.pool,
        )
    return httpx2.AsyncClient(
        follow_redirects=False,
        headers=headers,
        timeout=built,
        auth=auth,
    )


async def _connect() -> tuple[object | None, str | None]:
    """连上千帆网页搜索。成功返回服务，失败或未配置时返回说明。"""
    key = os.getenv("QIANFAN_API_KEY", "").strip()
    if not key:
        return None, "网络搜索未配置 QIANFAN_API_KEY，已跳过。"
    from agents.mcp import MCPServerStreamableHttp

    server = MCPServerStreamableHttp(
        params={
            "url": _URL,
            "headers": {"Authorization": f"Bearer {key}"},
            "timeout": _TIMEOUT,
            "sse_read_timeout": _TIMEOUT,
            "httpx_client_factory": _http_client,
        },
        name="baidu-search",
        cache_tools_list=True,
        client_session_timeout_seconds=_TIMEOUT,
    )
    try:
        await server.connect()
    except Exception as exc:
        await _close(server)
        return None, f"网络搜索连接失败：{exc}"
    return server, None


async def _close(server: object) -> None:
    cleanup = getattr(server, "cleanup", None)
    if cleanup is None:
        return
    try:
        await cleanup()
    except Exception:
        pass


register("baidu-search", _connect)
