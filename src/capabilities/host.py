"""发消息和定时任务。发消息走网关，不绑定某一个通道实现。"""

from agents import function_tool

from ..scheduler import calculate_next_run
from ..state import db
from ..work import OutboundMessage, Work


def host_tools(work: Work, gateway) -> list:
    """创建这一轮工作可用的宿主工具。"""

    async def send_message(text: str) -> str:
        """发送一条消息给当前用户。"""
        if not text:
            return "消息为空，未发送。"
        await gateway.deliver(
            OutboundMessage(channel=work.event.channel, chat_id=work.event.chat_id, text=text)
        )
        work.notified["sent"] = True
        return "消息已发送。"

    async def schedule_task(prompt: str, schedule_type: str, schedule_value: str) -> str:
        """创建定时任务。schedule_type 为 cron、interval 或 once。schedule_value 为 cron 表达式、正毫秒数或 ISO 时间戳。cron 和无时区的 once 按配置时区解释。"""
        try:
            next_run = calculate_next_run(schedule_type, schedule_value)
        except (TypeError, ValueError) as exc:
            return f"调度参数无效：{exc}"
        task_id = await db.create_task(
            work.event.chat_id,
            prompt,
            schedule_type,
            schedule_value,
            next_run,
            work.event.channel,
        )
        return f"任务 {task_id} 已创建。下次执行：{next_run}"

    async def list_tasks() -> str:
        """列出所有定时任务。"""
        tasks = await db.get_all_tasks()
        if not tasks:
            return "没有定时任务。"
        lines = [
            f"- [{task['id']}] {task['status']} | {task['schedule_type']}({task['schedule_value']}) | {task['prompt'][:50]}"
            for task in tasks
        ]
        return "\n".join(lines)

    async def pause_task(task_id: str) -> str:
        """暂停一个定时任务。"""
        ok = await db.update_task_status(task_id, "paused")
        return "任务已暂停。" if ok else "任务未找到。"

    async def resume_task(task_id: str) -> str:
        """恢复一个已暂停的定时任务。"""
        ok = await db.update_task_status(task_id, "active")
        return "任务已恢复。" if ok else "任务未找到。"

    async def cancel_task(task_id: str) -> str:
        """取消并删除一个定时任务。"""
        ok = await db.delete_task(task_id)
        return "任务已取消。" if ok else "任务未找到。"

    return [
        function_tool(send_message),
        function_tool(schedule_task),
        function_tool(list_tasks),
        function_tool(pause_task),
        function_tool(resume_task),
        function_tool(cancel_task),
    ]
