"""本机或内网的 vLLM。走 OpenAI Responses API。"""

import os

from agents import ModelSettings

from .client import configure_compatible_client

_DEFAULT_MODEL = "Qwen3.6"
_DEFAULT_API_KEY = "empty"
_DEFAULT_THINKING_BUDGET = 1024


class VllmBackend:
    """端点必填。密钥和模型名可以不填。"""

    name = "vllm"

    def missing_settings(self) -> list[str]:
        if not os.getenv("VLLM_BASE_URL", "").strip():
            return ["VLLM_BASE_URL"]
        return []

    def model_name(self) -> str:
        return os.getenv("VLLM_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

    def model_settings(self) -> ModelSettings:
        """思考保持开启，并用 token 预算限制长度。"""
        return ModelSettings(
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "thinking_token_budget": _thinking_budget(),
            }
        )

    def configure(self) -> None:
        configure_compatible_client(
            api_key=os.getenv("VLLM_API_KEY", _DEFAULT_API_KEY).strip() or _DEFAULT_API_KEY,
            base_url=os.getenv("VLLM_BASE_URL", "").strip(),
            api="responses",
        )


def _thinking_budget() -> int:
    raw = os.getenv("THINKING_TOKEN_BUDGET", "").strip()
    if not raw:
        return _DEFAULT_THINKING_BUDGET
    try:
        budget = int(raw)
    except ValueError:
        return _DEFAULT_THINKING_BUDGET
    return budget if budget > 0 else _DEFAULT_THINKING_BUDGET
