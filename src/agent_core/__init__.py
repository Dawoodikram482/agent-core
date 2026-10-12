"""Agent core: the shared foundation for every agent in the Agent Avenger Project."""

from importlib.metadata import PackageNotFoundError, version

from agent_core.bootstrap import bootstrap
from agent_core.observability import (
    Tracing,
    TracingUnavailableError,
    bind_correlation_id,
    configure_logging,
    configure_tracing,
    correlation_scope,
    get_correlation_id,
    get_logger,
)
from agent_core.settings import AgentSettings, SettingsError, load_settings

try:
    __version__ = version("agent-core")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled checkout
    __version__ = "0.0.0"

__all__ = [
    "AgentSettings",
    "SettingsError",
    "Tracing",
    "TracingUnavailableError",
    "__version__",
    "bind_correlation_id",
    "bootstrap",
    "configure_logging",
    "configure_tracing",
    "correlation_scope",
    "get_correlation_id",
    "get_logger",
    "load_settings",
]
