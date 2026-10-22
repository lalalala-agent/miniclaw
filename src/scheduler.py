"""按固定间隔扫描到期任务，并把任务交给网关。"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import SCHEDULER_INTERVAL, SCHEDULE_TIMEZONE
from .state import db
from .work import InboundEvent


def calculate_next_run(
    schedule_type: str,
    schedule_value: str,
    *,
    now: datetime | None = None,
    schedule_timezone: ZoneInfo | None = None,
) -> str:
    """校验调度参数，并将 next_run 统一保存为 UTC ISO 时间。"""
    from croniter import croniter

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include timezone information")

    current_utc = current.astimezone(timezone.utc)
    local_timezone = schedule_timezone or SCHEDULE_TIMEZONE

    if schedule_type == "cron":
        local_now = current_utc.astimezone(local_timezone)
        next_run = croniter(schedule_value, local_now).get_next(datetime)
    elif schedule_type == "interval":
        try:
            interval_ms = int(schedule_value)
        except ValueError as exc:
            raise ValueError("interval must be a positive integer in milliseconds") from exc
        if interval_ms <= 0:
            raise ValueError("interval must be positive")
        next_run = current_utc + timedelta(milliseconds=interval_ms)
    elif schedule_type == "once":
        try:
            next_run = datetime.fromisoformat(schedule_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("once must be a valid ISO timestamp") from exc
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=local_timezone)
        if next_run.astimezone(timezone.utc) <= current_utc:
            raise ValueError("once timestamp must be in the future")
    else:
        raise ValueError(f"unknown schedule_type: {schedule_type}")

    return next_run.astimezone(timezone.utc).isoformat()


async def check_due_tasks(gateway) -> None:
    """检查到期任务。"""
    try:
        tasks = await db.get_due_tasks()
    except Exception:
        return

    for task in tasks:
        try:
            await execute_task(task, gateway)
        except Exception:
            pass


async def execute_task(task: dict, gateway) -> None:
    """执行单个任务。模型没发消息时，由网关把结果投回原通道。"""
    task_id, chat_id = task["id"], task["chat_id"]
    prompt, stype, svalue = task["prompt"], task["schedule_type"], task["schedule_value"]
    channel = task.get("channel") or "telegram"
    event = InboundEvent(
        channel=channel,
        chat_id=chat_id,
        text=f"执行任务需要使用 send_message 通知用户。任务：{prompt}",
        kind="task",
        use_session=False,
    )
    result = await gateway.submit(event)

    now = datetime.now(timezone.utc)
    if stype in {"cron", "interval"}:
        next_run = calculate_next_run(stype, svalue, now=now)
        await db.update_task_after_run(task_id, result, next_run, "active")
    elif stype == "once":
        await db.update_task_after_run(task_id, result, None, "completed")


def setup_scheduler(gateway) -> AsyncIOScheduler:
    """设置调度器。"""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_due_tasks, "interval", seconds=SCHEDULER_INTERVAL, args=[gateway])
    return scheduler
