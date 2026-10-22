"""官方 OpenAI，或任何沿用 OPENAI_* 环境变量的兼容端点。"""

import os

from agents import ModelSettings

from .client import configure_compatible_client


class OpenAIBackend:
    """缺省供应商。密钥必填，端点和模型名可以不填。"""

    name = "openai"

    def missing_settings(self) -> list[str]:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            return ["OPENAI_API_KEY"]
        return []

    def model_name(self) -> str:
        return os.getenv("OPENAI_MODEL", "gpt-4.1").strip() or "gpt-4.1"

    def model_settings(self) -> ModelSettings:
        return ModelSettings()

    def configure(self) -> None:
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        configure_compatible_client(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            base_url=base_url,
            api="responses",
        )
