"""定时任务的 SQLite 操作。对话记录在 conversations/，不进数据库。"""

import uuid
from datetime import datetime, timezone

import aiosqlite

from ..config import DB_PATH

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run TEXT,
    last_run TEXT,
    last_result TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram'
);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON scheduled_tasks(next_run);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
"""


async def init_db() -> None:
    """初始化数据库。已有的库补上 channel 列，旧任务仍回到 Telegram。"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_TABLES)
        cursor = await db.execute("PRAGMA table_info(scheduled_tasks)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "channel" not in columns:
            await db.execute(
                "ALTER TABLE scheduled_tasks ADD COLUMN channel TEXT NOT NULL DEFAULT 'telegram'"
            )
        await db.commit()


async def create_task(
    chat_id: int,
    prompt: str,
    stype: str,
    svalue: str,
    next_run: str,
    channel: str,
) -> str:
    """创建定时任务。channel 是到期后回复要投回的通道。"""
    task_id = uuid.uuid4().hex[:8]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO scheduled_tasks (id, chat_id, prompt, schedule_type, schedule_value, next_run, created_at, channel) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, chat_id, prompt, stype, svalue, next_run, datetime.now(timezone.utc).isoformat(), channel),
        )
        await db.commit()
    return task_id


async def get_all_tasks() -> list[dict]:
    """获取所有任务。"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM scheduled_tasks")
        return [dict(row) for row in await cursor.fetchall()]


async def get_due_tasks() -> list[dict]:
    """获取到期的任务。"""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' AND next_run <= ?",
            (now,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def update_task_status(task_id: str, status: str) -> bool:
    """更新任务状态。"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE scheduled_tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_task(task_id: str) -> bool:
    """删除任务。"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_task_after_run(task_id: str, result: str, next_run: str | None, status: str) -> None:
    """执行后更新任务。"""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scheduled_tasks SET last_run = ?, last_result = ?, next_run = ?, status = ? WHERE id = ?",
            (now, result, next_run, status, task_id),
        )
        await db.commit()
