"""模型供应商。新的一家在这个包里实现协议，并在下面 register。"""

from .base import ModelBackend
from .openai import OpenAIBackend
from .registry import active_backend, register
from .vllm import VllmBackend

register(OpenAIBackend())
register(VllmBackend())

__all__ = ["ModelBackend", "active_backend", "register"]
