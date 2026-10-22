"""按 MODEL_PROVIDER 取出当前供应商。"""

import os

from ..config import APP_HOME
from .base import ModelBackend

_backends: dict[str, ModelBackend] = {}


def register(backend: ModelBackend) -> None:
    """登记一家供应商。同名会覆盖旧的。"""
    _backends[backend.name] = backend


def active_backend() -> ModelBackend:
    """当前要用的那一家。MODEL_PROVIDER 缺省是 openai。"""
    name = os.getenv("MODEL_PROVIDER", "openai").strip().lower() or "openai"
    backend = _backends.get(name)
    if backend is None:
        known = ", ".join(sorted(_backends)) or "（无）"
        raise SystemExit(f"未知模型供应商：{name}。可选：{known}。请填写 {APP_HOME / '.env'}")
    return backend
