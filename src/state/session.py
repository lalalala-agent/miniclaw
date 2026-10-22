"""主人会话。对话连续性放在模型外面。"""

from agents import SQLiteSession

from ..config import DATA_DIR, SESSION_PATH

_session: SQLiteSession | None = None


def get_session() -> SQLiteSession:
    """返回日常对话使用的本地会话。"""
    global _session
    if _session is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _session = SQLiteSession("owner", str(SESSION_PATH))
    return _session


async def clear_session() -> None:
    """清空当前会话。长期记忆不受影响。"""
    await get_session().clear_session()
