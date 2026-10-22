"""长期记忆和每日对话归档。正文留在工作区，只把少量内容放进提示。"""

from datetime import datetime, timezone

from ..capabilities.skills import skill_instructions
from ..config import ASSISTANT_NAME, CONVERSATIONS_DIR, MEMORY_FILE, TIMEZONE_NAME, WORKSPACE_DIR
from ..work import Work

MEMORY_TEMPLATE = f"""# {ASSISTANT_NAME} - 个人 AI 助手

你是 {ASSISTANT_NAME}，一个运行在 Telegram 上的个人 AI 助手。

## 能力
- 用 read_file、write_file、edit_file、glob_files、grep_files 管理本工作区文件
- 用 run_command 在工作区执行命令
- 用 fetch_url 抓取网页文本
- 用 send_message 给用户发消息
- 用 schedule_task 创建定时任务，并用 list_tasks、pause_task、resume_task、cancel_task 管理它们
- 技能目录里只有名称和描述。请求与某条描述相符时，用 read_skill 读取正文再执行

## 定时任务
- schedule_type "cron"：Cron 表达式，按 {TIMEZONE_NAME} 解释
- schedule_type "interval"：毫秒数（如 "3600000" = 1 小时）
- schedule_type "once"：ISO 时间戳；没有时区时按 {TIMEZONE_NAME} 解释

## 记忆
- 这个 MEMORY.md 是长期记忆，了解用户偏好后写回本文件
- conversations/ 包含每日对话归档，可用 glob_files 和 grep_files 搜索

## 用户偏好
（在了解用户时添加）
"""


def ensure_workspace() -> None:
    """确保工作目录和 MEMORY.md 存在。"""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(MEMORY_TEMPLATE, encoding="utf-8")


def prompt_context(work: Work) -> str:
    """取出要放进本轮提示的少量记忆。对话归档不在这里整段读入。"""
    _ = work
    memory = MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.exists() else MEMORY_TEMPLATE
    parts = [
        f"你是 {ASSISTANT_NAME}，一个运行在 Telegram 上的个人 AI 助手。",
        f"当前时区是 {TIMEZONE_NAME}。文件工具和命令都限制在工作区内。",
        "定时任务要让用户看到结果时，调用 send_message。",
        "",
    ]
    skills = skill_instructions()
    if skills:
        parts.extend([skills, ""])
    parts.append(memory)
    return "\n".join(parts)


def record_turn(user_msg: str, assistant_msg: str) -> None:
    """把一轮对话归档到当天的 Markdown。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = CONVERSATIONS_DIR / f"{today}.md"
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    entry = f"## {timestamp}\n\n**用户**: {user_msg}\n\n**{ASSISTANT_NAME}**: {assistant_msg}\n\n---\n\n"
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8") + entry
    else:
        content = f"# 对话记录 - {today}\n\n" + entry
    filepath.write_text(content, encoding="utf-8")
