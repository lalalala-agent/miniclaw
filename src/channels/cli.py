"""本地命令行通道：从标准输入读文本，把回复打到标准输出。"""

import asyncio

from ..config import ASSISTANT_NAME
from ..gateway import Gateway
from ..work import InboundEvent, OutboundMessage
from .registry import register

CLI_CHAT_ID = 0
_EXIT = {"exit", "quit", "/exit", "/quit"}


class CliChannel:
    """本机终端通道。不校验 Telegram 身份，回复直接打印。"""

    name = "cli"

    def __init__(self) -> None:
        self._reasoning_open = False
        self._stream_open = False
        self._ready = asyncio.Event()
        self._go = asyncio.Event()

    async def wait_until_ready(self) -> None:
        """说明文字打印完即视为就绪。输入提示要等调度器起来。"""
        await self._ready.wait()

    def allow_input(self) -> None:
        """调度器启动后再开始读入。"""
        self._go.set()

    async def deliver(self, message: OutboundMessage) -> None:
        """把一条完整回复打到标准输出。"""
        text = message.text.strip()
        if not text:
            return
        self._close_reasoning()
        self._close_stream()
        print(f"\n{ASSISTANT_NAME}> {text}\n", flush=True)

    async def write_reasoning(self, message: OutboundMessage) -> None:
        """把刚生成的一小段思考接在当前思考后面。"""
        text = message.text
        if not text:
            return
        if not self._reasoning_open:
            print("\n思考> ", end="", flush=True)
            self._reasoning_open = True
        print(text, end="", flush=True)

    async def finish_reasoning(self, message: OutboundMessage) -> None:
        """这一段思考结束，补上换行。"""
        self._close_reasoning()

    async def write_stream(self, message: OutboundMessage) -> None:
        """把刚生成的一小段正文接在当前回复后面。"""
        text = message.text
        if not text:
            return
        self._close_reasoning()
        if not self._stream_open:
            text = text.lstrip("\r\n")
            if not text:
                return
            print(f"\n{ASSISTANT_NAME}> ", end="", flush=True)
            self._stream_open = True
        print(text, end="", flush=True)

    async def finish_stream(self, message: OutboundMessage) -> None:
        """这一轮正文结束，补上换行。"""
        self._close_reasoning()
        self._close_stream()

    def _close_reasoning(self) -> None:
        if not self._reasoning_open:
            return
        print(flush=True)
        self._reasoning_open = False

    def _close_stream(self) -> None:
        if not self._stream_open:
            return
        print(flush=True)
        self._stream_open = False

    async def start(self, gateway: Gateway) -> None:
        """读入一行就提交一轮。输入等待不占住事件循环，定时任务仍能把回复打出来。"""
        print(_welcome())
        print("输入消息后回车。/clear 清空会话，exit 或 Ctrl-D 退出。")
        print("定时任务的回复会在这个终端里出现；关掉进程后就不会再投递。")
        self._ready.set()
        await self._go.wait()
        while True:
            line = await asyncio.to_thread(_read_line)
            if line is None:
                print()
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() in _EXIT:
                break
            if text == "/start":
                print(_welcome())
                continue
            kind = "clear" if text == "/clear" else "message"
            if kind == "message":
                print("思考中…", flush=True)
            await gateway.submit(
                InboundEvent(
                    channel=self.name,
                    chat_id=CLI_CHAT_ID,
                    text=text,
                    kind=kind,
                    use_session=kind == "message",
                )
            )


def _factory() -> CliChannel:
    return CliChannel()


register("cli", _factory)


def _read_line() -> str | None:
    """读一行。到达文件末尾时返回 None。"""
    try:
        return input("你> ")
    except EOFError:
        return None


def _welcome() -> str:
    return (
        f"你好！我是 {ASSISTANT_NAME}，你的个人 AI 助手。\n\n"
        "我可以：\n"
        "• 读写文件、执行命令\n"
        "• 抓取网页\n"
        "• 创建定时任务和提醒\n"
        "• 记住你的偏好\n\n"
        "试试：'1 分钟后提醒我喝水'\n\n"
        "命令：\n"
        "/clear - 重置对话\n"
        "exit - 退出"
    )
