"""通道协议：接入由各通道自己完成，投递由网关调用。"""

from typing import Protocol

from ..work import OutboundMessage


class Channel(Protocol):
    """新通道实现 name 和 deliver，再注册到网关。

    要边生成边显示，再实现 write_stream 和 finish_stream。
    要边想边显示，再实现 write_reasoning 和 finish_reasoning。
    没有这些方法时，网关仍在回合结束后一次性 deliver。
    """

    name: str

    async def deliver(self, message: OutboundMessage) -> None:
        """把一条完整回复发回这个通道。"""
