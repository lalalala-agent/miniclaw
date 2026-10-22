"""按 CHANNELS 取出要启动的通道。实现登记在各通道模块里。"""

import os
from collections.abc import Callable

from ..config import APP_HOME
from .base import Channel

Factory = Callable[[], Channel]
Missing = Callable[[], list[str]]
_factories: dict[str, Factory] = {}
_missing: dict[str, Missing] = {}
_loaded = False


def register(name: str, factory: Factory, missing: Missing | None = None) -> None:
    """登记一种通道。同名会覆盖旧的。missing 返回这个通道还缺的环境变量。"""
    _factories[name] = factory
    if missing is None:
        _missing.pop(name, None)
    else:
        _missing[name] = missing


def load() -> None:
    """导入各通道模块，完成登记。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import cli, telegram  # noqa: F401


def enabled_names() -> list[str]:
    """CHANNELS 里点名的通道。空着或有未知名字时退出。"""
    load()
    names: list[str] = []
    seen: set[str] = set()
    for part in os.getenv("CHANNELS", "").split(","):
        name = part.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    known = ", ".join(sorted(_factories)) or "（无）"
    if not names:
        raise SystemExit(f"缺少环境变量：CHANNELS。可选：{known}。请填写 {APP_HOME / '.env'}")
    unknown = [name for name in names if name not in _factories]
    if unknown:
        raise SystemExit(f"未知通道：{', '.join(unknown)}。可选：{known}。请填写 {APP_HOME / '.env'}")
    return names


def missing_settings(names: list[str]) -> list[str]:
    """已启用通道还缺的环境变量。没有申报的通道不增加缺项。"""
    load()
    found: list[str] = []
    seen: set[str] = set()
    for name in names:
        report = _missing.get(name)
        if report is None:
            continue
        for item in report():
            if item in seen:
                continue
            seen.add(item)
            found.append(item)
    return found


def build(names: list[str]) -> list[Channel]:
    """按名字造出通道实例。调用前应先确认所需环境变量已经填好。"""
    load()
    return [_factories[name]() for name in names]
