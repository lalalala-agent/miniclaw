"""OpenAI 兼容客户端。能走 Responses 或 Chat Completions 的供应商共用这里。"""

from typing import Literal


def configure_compatible_client(
    *,
    api_key: str,
    base_url: str | None,
    api: Literal["responses", "chat_completions"],
) -> None:
    """关闭 trace，并设成全局默认客户端。base_url 以 /v1 结尾时，SDK 会自己拼上接口路径。"""
    from agents import set_default_openai_api, set_default_openai_client, set_tracing_disabled
    from openai import AsyncOpenAI

    set_tracing_disabled(True)
    client_kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    set_default_openai_client(AsyncOpenAI(**client_kwargs), use_for_tracing=False)
    set_default_openai_api(api)
