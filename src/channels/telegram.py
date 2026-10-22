"""Telegram 通道：只响应主人，把文本变成事件，并把回复发回去。"""

import asyncio
import os
import time

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from ..config import ASSISTANT_NAME, TELEGRAM_BOT_TOKEN, owner_id
from ..gateway import Gateway
from ..work import InboundEvent, OutboundMessage
from .registry import register

_MESSAGE_LIMIT = 4096
_EDIT_INTERVAL = 0.4


class TelegramChannel:
    """Telegram 通道。新通道照这个名字和 deliver 来实现。"""

    name = "telegram"

    def __init__(self, owner: int) -> None:
        self.owner_id = owner
        self._bot = None
        self._stream: dict | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()

    async def wait_until_ready(self) -> None:
        """轮询开始之后才视为就绪。"""
        await self._ready.wait()

    def request_stop(self) -> None:
        """让轮询在当前事件循环里停下来。"""
        self._stop.set()

    async def start(self, gateway: Gateway) -> None:
        """在当前事件循环里轮询。不独占进程。"""

        async def post_init(app: Application) -> None:
            self._bot = app.bot

        app = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .post_init(post_init)
            .build()
        )
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("clear", self._on_clear(gateway)))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message(gateway)))
        initialized = False
        started = False
        polling = False
        try:
            await app.initialize()
            initialized = True
            if app.post_init:
                await app.post_init(app)
            if app.updater is None:
                raise RuntimeError("Telegram 通道缺少 updater")
            await app.updater.start_polling()
            polling = True
            await app.start()
            started = True
            self._ready.set()
            await self._stop.wait()
        finally:
            self._ready.set()
            if polling:
                await app.updater.stop()
            if started:
                await app.stop()
            if initialized:
                await app.shutdown()

    async def deliver(self, message: OutboundMessage) -> None:
        """按 4096 字分段发出。带了原消息 ID 时，作为回复发送。"""
        if self._bot is None:
            raise RuntimeError("Telegram 通道尚未启动")
        for start in range(0, len(message.text), _MESSAGE_LIMIT):
            kwargs = {"chat_id": message.chat_id, "text": message.text[start : start + _MESSAGE_LIMIT]}
            if message.reply_to_message_id is not None:
                kwargs["reply_to_message_id"] = message.reply_to_message_id
            await self._bot.send_message(**kwargs)

    async def write_stream(self, message: OutboundMessage) -> None:
        """把增量写进同一条消息，并按间隔编辑，避免触发频率限制。"""
        if self._bot is None or not message.text:
            return
        if self._stream is None:
            self._stream = {
                "chat_id": message.chat_id,
                "reply_to": message.reply_to_message_id,
                "message_id": None,
                "text": "",
                "pushed": "",
                "last_edit": 0.0,
            }
        self._stream["text"] += message.text
        await self._flush_stream(force=False)

    async def finish_stream(self, message: OutboundMessage) -> None:
        """把缓冲区里剩下的正文编辑进消息。"""
        if self._stream is None:
            return
        try:
            await self._flush_stream(force=True)
        finally:
            self._stream = None

    async def _flush_stream(self, force: bool) -> None:
        state = self._stream
        if state is None or not state["text"]:
            return
        now = time.monotonic()
        if state["message_id"] is not None and not force and now - state["last_edit"] < _EDIT_INTERVAL:
            return
        while len(state["text"]) > _MESSAGE_LIMIT:
            head = state["text"][:_MESSAGE_LIMIT]
            state["text"] = state["text"][_MESSAGE_LIMIT:]
            await self._upsert_stream(state, head)
            state["message_id"] = None
            state["reply_to"] = None
        if not state["text"]:
            return
        if state["message_id"] is not None and state["pushed"] == state["text"]:
            return
        if state["message_id"] is not None and not force and now - state["last_edit"] < _EDIT_INTERVAL:
            return
        await self._upsert_stream(state, state["text"])

    async def _upsert_stream(self, state: dict, text: str) -> None:
        if state["message_id"] is None:
            kwargs = {"chat_id": state["chat_id"], "text": text}
            if state["reply_to"] is not None:
                kwargs["reply_to_message_id"] = state["reply_to"]
            sent = await self._bot.send_message(**kwargs)
            state["message_id"] = sent.message_id
            state["pushed"] = text
            state["last_edit"] = time.monotonic()
            return
        try:
            await self._bot.edit_message_text(
                chat_id=state["chat_id"],
                message_id=state["message_id"],
                text=text,
            )
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        state["pushed"] = text
        state["last_edit"] = time.monotonic()

    def _is_owner(self, update: Update) -> bool:
        return update.effective_user is not None and update.effective_user.id == self.owner_id

    async def _on_start(self, update: Update, context) -> None:
        if not self._is_owner(update) or not update.message:
            return
        await update.message.reply_text(
            f"你好！我是 {ASSISTANT_NAME}，你的个人 AI 助手。\n\n"
            "我可以：\n"
            "• 读写文件、执行命令\n"
            "• 抓取网页\n"
            "• 创建定时任务和提醒\n"
            "• 记住你的偏好\n\n"
            "试试：'1 分钟后提醒我喝水'\n\n"
            "命令：\n"
            "/clear - 重置对话"
        )

    def _on_clear(self, gateway: Gateway):
        async def clear(update: Update, context) -> None:
            if not self._is_owner(update) or not update.message or not update.effective_chat:
                return
            await gateway.submit(
                InboundEvent(
                    channel=self.name,
                    chat_id=update.effective_chat.id,
                    text="/clear",
                    kind="clear",
                    use_session=False,
                    meta={"reply_to_message_id": update.message.message_id},
                )
            )

        return clear

    def _on_message(self, gateway: Gateway):
        async def handle_message(update: Update, context) -> None:
            if not self._is_owner(update) or not update.message or not update.message.text or not update.effective_chat:
                return
            chat_id = update.effective_chat.id
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await gateway.submit(
                InboundEvent(
                    channel=self.name,
                    chat_id=chat_id,
                    text=update.message.text,
                    kind="message",
                    use_session=True,
                    meta={"reply_to_message_id": update.message.message_id},
                )
            )

        return handle_message


def _factory() -> TelegramChannel:
    return TelegramChannel(owner_id())


def _missing() -> list[str]:
    """这个通道还缺的环境变量。"""
    return [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("OWNER_ID", os.getenv("OWNER_ID", "")),
        )
        if not value
    ]


register("telegram", _factory, _missing)
