"""工作生命周期上的插件钩子。默认不注册任何钩子。"""

from collections.abc import Awaitable, Callable
from typing import Any

from .work import Work

Hook = Callable[..., Any]

_before: list[Hook] = []
_after: list[Hook] = []


def register_before(hook: Hook) -> None:
    """在网关把工作交给执行层之前调用。hook 接收 Work。"""
    _before.append(hook)


def register_after(hook: Hook) -> None:
    """在网关投递回复之后调用。hook 接收 Work 和结果文本。"""
    _after.append(hook)


async def before_work(work: Work) -> None:
    """依次调用已注册的前置钩子。"""
    for hook in list(_before):
        result = hook(work)
        if isinstance(result, Awaitable):
            await result


async def after_work(work: Work, result: str) -> None:
    """依次调用已注册的后置钩子。"""
    for hook in list(_after):
        outcome = hook(work, result)
        if isinstance(outcome, Awaitable):
            await outcome
