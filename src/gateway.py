"""网关：把通道事件变成一条工作，并把回复投回通道。"""

from . import hooks
from .channels.base import Channel
from .state.session import clear_session
from .trace import clip
from .work import InboundEvent, OutboundMessage, Work


class Gateway:
    """不调用模型，也不认识某个通道自己的消息对象。"""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._scheduler = None

    def register(self, channel: Channel) -> None:
        """登记一个通道。同名通道会覆盖旧的。"""
        self._channels[channel.name] = channel

    def on_running(self) -> None:
        """事件循环就绪后启动调度器。调度器是另一个入口，不是通道。"""
        from .scheduler import setup_scheduler

        if self._scheduler is not None:
            return
        self._scheduler = setup_scheduler(self)
        self._scheduler.start()
        print("调度器已启动")

    def shutdown(self) -> None:
        """停掉调度器。通道退出时调用。"""
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is None:
            return
        scheduler.shutdown(wait=False)

    async def submit(self, event: InboundEvent) -> str:
        """把一件事收成工作，跑完后把回复投回原通道。"""
        work = Work(event=event)
        work.trace.log(f"收到 {event.channel}/{event.kind}：{_preview(event.text)}")
        await hooks.before_work(work)
        work.trace.log("前置钩子结束")
        if event.kind == "clear":
            await clear_session()
            result = "会话已清除！长期记忆已保留。"
            work.trace.log("会话已清空")
        else:
            from .runtime import run_work

            result = await run_work(work, self)
            work.trace.log(f"执行结束，回复 {len(result)} 字")
        await self._deliver_result(work, result)
        await hooks.after_work(work, result)
        work.trace.log("本轮结束")
        return result

    async def deliver(self, message: OutboundMessage) -> None:
        """把一条回复交给它所属的通道。"""
        channel = self._channels.get(message.channel)
        if channel is None:
            raise RuntimeError(f"通道未注册：{message.channel}")
        await channel.deliver(message)

    async def stream_reasoning(self, work: Work, delta: str) -> None:
        """把模型刚生成的一小段思考推给通道。通道没有这个方法时什么都不做。"""
        if not delta:
            return
        channel = self._channels.get(work.event.channel)
        write = getattr(channel, "write_reasoning", None)
        if write is None:
            return
        await write(self._outbound(work, delta))

    async def finish_reasoning_stream(self, work: Work) -> None:
        """通知通道这一段思考结束。"""
        channel = self._channels.get(work.event.channel)
        finish = getattr(channel, "finish_reasoning", None)
        if finish is None:
            return
        await finish(self._outbound(work, ""))

    async def stream_delta(self, work: Work, delta: str) -> None:
        """把模型刚生成的一小段正文推给通道。通道没有流式方法时什么都不做。"""
        if not delta:
            return
        channel = self._channels.get(work.event.channel)
        write = getattr(channel, "write_stream", None)
        if write is None:
            return
        await write(self._outbound(work, delta))
        work.notified["streamed"] = True

    async def stream_finish(self, work: Work) -> None:
        """通知通道这一轮的流式正文结束。收尾失败时改回整段投递。"""
        channel = self._channels.get(work.event.channel)
        finish = getattr(channel, "finish_stream", None)
        if finish is None:
            return
        try:
            await finish(self._outbound(work, ""))
        except Exception as exc:
            print(f"结束流式输出时出错：{exc}")
            work.trace.log(f"结束流式输出失败，改为整段发送：{exc}")
            work.notified["streamed"] = False

    def _outbound(self, work: Work, text: str) -> OutboundMessage:
        reply_to = work.event.meta.get("reply_to_message_id")
        return OutboundMessage(
            channel=work.event.channel,
            chat_id=work.event.chat_id,
            text=text,
            reply_to_message_id=reply_to if isinstance(reply_to, int) else None,
        )

    async def _deliver_result(self, work: Work, result: str) -> None:
        if work.notified.get("streamed"):
            work.trace.log("回复已经随着流式输出写到窗口，不再整段发送")
            return
        if work.event.kind == "task" and work.notified["sent"]:
            work.trace.log("定时任务已用 send_message 发过，不再补发")
            return
        if not result:
            work.trace.log("没有可发送的回复")
            return
        work.trace.log(f"整段发送回复，{len(result)} 字")
        reply_to = work.event.meta.get("reply_to_message_id")
        await self.deliver(
            OutboundMessage(
                channel=work.event.channel,
                chat_id=work.event.chat_id,
                text=result,
                reply_to_message_id=reply_to if isinstance(reply_to, int) else None,
            )
        )


def _preview(text: str) -> str:
    return clip(text, 80) or "（空）"
