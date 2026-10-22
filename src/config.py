"""环境变量和路径。模型客户端由 src/models 里的供应商配置。"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# 代码在 src/，运行时数据放在仓库根目录。
REPO_ROOT = Path(__file__).resolve().parent.parent
APP_HOME = REPO_ROOT
load_dotenv(APP_HOME / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Ape")
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "60"))
TIMEZONE_NAME = os.getenv("TIMEZONE", "UTC")
SCHEDULE_TIMEZONE = ZoneInfo(TIMEZONE_NAME)

WORKSPACE_DIR = APP_HOME / "workspace"
STORE_DIR = APP_HOME / "store"
DATA_DIR = APP_HOME / "data"
LOG_DIR = APP_HOME / "logs"
TRACE_LOG = LOG_DIR / "agent.log"
DB_PATH = STORE_DIR / "self-agent.db"
CONVERSATIONS_DIR = WORKSPACE_DIR / "conversations"
MEMORY_FILE = WORKSPACE_DIR / "MEMORY.md"
SESSION_PATH = DATA_DIR / "sessions.db"
SKILLS_DIR = REPO_ROOT / "skills"
PRESENTATIONS_DIR = WORKSPACE_DIR / "presentations"
POWERPOINT_SCRIPTS = SKILLS_DIR / "powerpoint" / "scripts"
PRESENTER_DIR = SKILLS_DIR / "ppt-presenter" / "ppt_mcp"
PRESENTER_PYTHON = PRESENTER_DIR / ".venv" / "bin" / "python"


def wiki_dir() -> Path:
    """知识库目录。WIKI_PATH 必须落在工作区内，否则用 workspace/wiki。"""
    default = (WORKSPACE_DIR / "wiki").resolve()
    raw = os.getenv("WIKI_PATH", "").strip()
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (WORKSPACE_DIR / candidate).resolve()
    root = WORKSPACE_DIR.resolve()
    if path != root and path.is_relative_to(root):
        return path
    return default


def wiki_relative() -> str:
    """知识库相对工作区的路径，供文件工具使用。"""
    relative = wiki_dir().resolve().relative_to(WORKSPACE_DIR.resolve())
    return relative.as_posix() or "wiki"


def require_env(names: list[str]) -> None:
    """缺了列出的环境变量就退出。"""
    if names:
        raise SystemExit(f"缺少环境变量：{', '.join(names)}。请填写 {APP_HOME / '.env'}")


def owner_id() -> int:
    """主人的 Telegram 用户 ID。调用前应先确认 OWNER_ID 已填写。"""
    try:
        return int(os.environ["OWNER_ID"])
    except (KeyError, ValueError) as exc:
        raise SystemExit("OWNER_ID 必须是整数") from exc
