"""通道事件、回复，以及网关交给执行层的一条工作。"""

from dataclasses import dataclass, field
from typing import Any

from .trace import Trace


@dataclass
class InboundEvent:
    """通道或调度器交上来的一件事。"""

    channel: str
    chat_id: int
    text: str
    kind: str
    use_session: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """要投回某个通道的一条回复。"""

    channel: str
    chat_id: int
    text: str
    reply_to_message_id: int | None = None


@dataclass
class Work:
    """一轮工作。执行层握住它的生命周期，网关负责投递。"""

    event: InboundEvent
    notified: dict[str, bool] = field(default_factory=lambda: {"sent": False})
    trace: Trace = field(default_factory=Trace)
