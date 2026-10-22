"""通道层。Telegram 和本地 CLI 是当前实现，新通道放在这个包里并注册到网关。"""

from .base import Channel

__all__ = ["Channel"]
