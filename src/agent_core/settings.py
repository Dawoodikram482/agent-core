"""Settings shared by every agent and service.

Values are read from environment variables first, then from a ``.env`` file in the
working directory. Services subclass :class:`AgentSettings` to add their own fields
and load them with :func:`load_settings`, which fails fast with a readable message.

Example:
    >>> class IngestSettings(AgentSettings):
    ...     database_url: SecretStr  # required: DATABASE_URL must be set
    >>> settings = load_settings(IngestSettings)  # doctest: +SKIP
"""

from typing import Any, Literal, overload

from pydantic import HttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["auto", "json", "console"]

_LEVEL_NAMES = frozenset({"debug", "info", "warning", "error", "critical"})


class SettingsError(RuntimeError):
    """Raised when settings are missing or invalid. The message names every problem."""


class AgentSettings(BaseSettings):
    """Base settings for every agent and service.

    Attributes:
        service_name: Name added to every log line and trace (``SERVICE_NAME``).
        environment: ``development``, ``test`` or ``production`` (``ENVIRONMENT``).
        log_level: Minimum level that is logged (``LOG_LEVEL``, case-insensitive).
        log_format: ``json``, ``console``, or ``auto``: console output in development,
            JSON everywhere else (``LOG_FORMAT``).
        langfuse_public_key: Langfuse public key; tracing is on only when both keys are set.
        langfuse_secret_key: Langfuse secret key.
        langfuse_base_url: Langfuse server, cloud or self-hosted (``LANGFUSE_BASE_URL``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    service_name: str = "agent"
    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "auto"

    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: HttpUrl = HttpUrl("https://cloud.langfuse.com")

    @field_validator("log_level", "log_format", "environment", mode="before")
    @classmethod
    def _normalise_case(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.upper() if value.lower() in _LEVEL_NAMES else value.lower()

    @property
    def tracing_configured(self) -> bool:
        """True when both Langfuse keys are set and non-empty."""
        keys = (self.langfuse_public_key, self.langfuse_secret_key)
        return all(key is not None and key.get_secret_value() for key in keys)


@overload
def load_settings(**overrides: Any) -> AgentSettings: ...  # noqa: ANN401
@overload
def load_settings[S: AgentSettings](settings_cls: type[S], /, **overrides: Any) -> S: ...  # noqa: ANN401
def load_settings(settings_cls: type[AgentSettings] = AgentSettings, /, **overrides: Any) -> AgentSettings:
    """Load settings from the environment and ``.env``, failing fast on any problem.

    Args:
        settings_cls: The settings class to load, usually a subclass of :class:`AgentSettings`.
        **overrides: Values that take precedence over the environment (handy in tests).

    Raises:
        SettingsError: If a required value is missing or a value is invalid. The message
            lists each environment variable and what is wrong, never the values themselves.
    """
    try:
        return settings_cls(**overrides)
    except ValidationError as exc:
        raise SettingsError(_describe(exc, settings_cls)) from None


def _describe(exc: ValidationError, settings_cls: type[BaseSettings]) -> str:
    prefix = str(settings_cls.model_config.get("env_prefix", ""))
    lines = [f"Invalid settings for {settings_cls.__name__}:"]
    for error in exc.errors(include_input=False, include_url=False):
        field = str(error["loc"][0]) if error["loc"] else "?"
        env_var = f"{prefix}{field}".upper()
        if error["type"] == "missing":
            lines.append(f"  - {env_var}: missing; set it in the environment or in .env")
        else:
            lines.append(f"  - {env_var}: {error['msg']}")
    return "\n".join(lines)
