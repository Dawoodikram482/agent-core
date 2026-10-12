"""Settings for the LLM gateway: which providers, in which order, with which models.

Every provider speaks the OpenAI-compatible chat completions API. A provider is used
only when its API key is set, so a service with just a Groq key simply runs on Groq.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import NoDecode

from agent_core.settings import AgentSettings

KNOWN_PROVIDERS = ("groq", "gemini", "openrouter")


class ProviderConfig(BaseModel):
    """Connection details for one OpenAI-compatible provider."""

    model_config = ConfigDict(frozen=True)

    name: str
    base_url: HttpUrl
    api_key: SecretStr
    model: str
    max_concurrency: int = Field(default=4, ge=1)

    @property
    def chat_completions_url(self) -> str:
        """Full URL of the chat completions endpoint."""
        return f"{str(self.base_url).rstrip('/')}/chat/completions"


class LLMSettings(AgentSettings):
    """Agent settings plus the LLM gateway's providers and retry policy.

    Providers are tried in the order of ``LLM_PROVIDERS`` (comma-separated). Each one
    reads ``<NAME>_API_KEY``, ``<NAME>_MODEL``, ``<NAME>_BASE_URL`` and
    ``<NAME>_MAX_CONCURRENCY``; model names come from configuration, never from code.
    """

    llm_providers: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["groq", "gemini"])
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_attempts: int = Field(default=3, ge=1, le=10)
    llm_backoff_base_seconds: float = Field(default=0.5, ge=0)
    llm_backoff_max_seconds: float = Field(default=8.0, ge=0)

    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: HttpUrl = HttpUrl("https://api.groq.com/openai/v1")
    groq_max_concurrency: int = Field(default=4, ge=1)

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-flash-latest"
    gemini_base_url: HttpUrl = HttpUrl("https://generativelanguage.googleapis.com/v1beta/openai")
    gemini_max_concurrency: int = Field(default=4, ge=1)

    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: HttpUrl = HttpUrl("https://openrouter.ai/api/v1")
    openrouter_max_concurrency: int = Field(default=2, ge=1)

    @field_validator("llm_providers", mode="before")
    @classmethod
    def _split_providers(cls, value: object) -> object:
        if isinstance(value, str):
            value = [part for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            names = [str(part).strip().lower() for part in value]
            unknown = sorted(set(names) - set(KNOWN_PROVIDERS))
            if unknown:
                msg = f"unknown provider(s) {', '.join(unknown)}; choose from {', '.join(KNOWN_PROVIDERS)}"
                raise ValueError(msg)
            if len(set(names)) != len(names):
                msg = "each provider may appear only once"
                raise ValueError(msg)
            return names
        return value

    def provider_configs(self) -> list[ProviderConfig]:
        """Providers in fallback order, skipping any whose API key is not set."""
        configs = []
        for name in self.llm_providers:
            api_key: SecretStr | None = getattr(self, f"{name}_api_key")
            if api_key is None or not api_key.get_secret_value():
                continue
            configs.append(
                ProviderConfig(
                    name=name,
                    base_url=getattr(self, f"{name}_base_url"),
                    api_key=api_key,
                    model=getattr(self, f"{name}_model"),
                    max_concurrency=getattr(self, f"{name}_max_concurrency"),
                )
            )
        return configs
