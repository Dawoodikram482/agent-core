"""Structured logging for every agent and service.

``configure_logging`` sets up structlog and routes the standard library's ``logging``
through the same pipeline, so logs from our code, uvicorn, httpx and others share one
format: JSON in production, readable console output in development.

Every line carries a UTC timestamp, the level, the service name, the environment and,
when set, the correlation ID. Secrets are masked before anything is written.
"""

import logging
import sys
from typing import IO, Any

import structlog
from pydantic import SecretBytes, SecretStr
from structlog.typing import EventDict, Processor, WrappedLogger

from agent_core.settings import AgentSettings, load_settings

REDACTED = "**********"
HANDLER_NAME = "agent-core"

# Key parts that mark a value as secret. Matched against the parts of a key split on "_"
# and "-", so "access_token" is masked while "prompt_tokens" and "max_tokens" are not.
_SECRET_KEY_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "cookie",
    }
)
_SECRET_KEY_PHRASES = ("api_key", "private_key", "secret_key")


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalised = key.lower().replace("-", "_")
    if any(phrase in normalised for phrase in _SECRET_KEY_PHRASES):
        return True
    return any(part in _SECRET_KEY_PARTS for part in normalised.split("_"))


def _redact(key: object, value: object) -> object:
    if isinstance(value, SecretStr | SecretBytes):
        return REDACTED
    if value is not None and _is_secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: _redact(k, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact(None, v) for v in value)
    return value


def redact_secrets(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Structlog processor that masks secret values, including inside nested dicts and lists."""
    for key, value in list(event_dict.items()):
        if key != "event":
            event_dict[key] = _redact(key, value)
    return event_dict


def _add_service_fields(service_name: str, environment: str) -> Processor:
    def add_service(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        event_dict.setdefault("env", environment)
        return event_dict

    return add_service


def _use_json(settings: AgentSettings) -> bool:
    if settings.log_format == "auto":
        return settings.environment != "development"
    return settings.log_format == "json"


def configure_logging(settings: AgentSettings | None = None, *, stream: IO[str] | None = None) -> None:
    """Configure structlog and the standard library's logging for the whole process.

    Safe to call more than once: the previous handler is replaced, never duplicated.

    Args:
        settings: Log level, format, service name and environment. Loaded from the
            environment when omitted.
        stream: Where log lines go. Defaults to standard error.
    """
    settings = settings or load_settings()
    output = stream or sys.stderr
    as_json = _use_json(settings)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_fields(settings.service_name, settings.environment),
        redact_secrets,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Processor
    final: list[Processor]
    if as_json:
        renderer = structlog.processors.JSONRenderer()
        final = [structlog.processors.dict_tracebacks, renderer]
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=_is_terminal(output))
        final = [renderer]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final],
    )
    handler = logging.StreamHandler(output)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:  # noqa: ANN401
    """Return a structured logger, optionally with values bound to every line it writes."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger.bind(**initial_values) if initial_values else logger


def _is_terminal(stream: IO[str]) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


__all__ = ["REDACTED", "configure_logging", "get_logger", "redact_secrets"]
