"""模型供应商协议。新的一家实现这五项，再登记到注册表。"""

from typing import Protocol

from agents import ModelSettings


class ModelBackend(Protocol):
    """启动时按名字取出一家。执行层只使用模型名和调用参数。"""

    name: str

    def missing_settings(self) -> list[str]:
        """返回还缺的环境变量名。没有缺项时是空列表。"""

    def model_name(self) -> str:
        """交给 Agent 的模型名。"""

    def model_settings(self) -> ModelSettings:
        """交给 Agent 的调用参数。没有额外参数时返回空设置。"""

    def configure(self) -> None:
        """启动时调用一次，把 SDK 指到这家。"""
