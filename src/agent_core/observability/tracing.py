"""Optional tracing with Langfuse.

Tracing switches on only when both Langfuse keys are set. Without them,
:func:`configure_tracing` returns a disabled :class:`Tracing` and everything else keeps
working, so every service runs with or without Langfuse.

Langfuse is an optional extra: install ``agent-core[langfuse]`` where tracing is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_core.observability.logging import get_logger
from agent_core.settings import AgentSettings, load_settings

if TYPE_CHECKING:
    from langfuse import Langfuse

log = get_logger(__name__)


class TracingUnavailableError(RuntimeError):
    """Raised when Langfuse keys are set but the ``langfuse`` package is not installed."""


@dataclass(frozen=True)
class Tracing:
    """Handle to the tracing backend.

    Attributes:
        enabled: True when traces are sent to Langfuse.
        client: The Langfuse client when enabled, otherwise None.
    """

    enabled: bool
    client: Langfuse | None = None

    def flush(self) -> None:
        """Send any buffered traces now. Does nothing when tracing is disabled."""
        if self.client is not None:
            self.client.flush()

    def shutdown(self) -> None:
        """Flush and stop the tracing client; call once when the process exits."""
        if self.client is not None:
            self.client.shutdown()


def configure_tracing(settings: AgentSettings | None = None) -> Tracing:
    """Start Langfuse tracing when its keys are set; otherwise return a disabled handle.

    Args:
        settings: Langfuse keys, server URL, environment and service name. Loaded from
            the environment when omitted.

    Raises:
        TracingUnavailableError: If the keys are set but ``langfuse`` is not installed.
    """
    settings = settings or load_settings()
    if not settings.tracing_configured:
        log.info("tracing disabled", reason="Langfuse keys not set")
        return Tracing(enabled=False)

    try:
        from langfuse import Langfuse  # optional dependency, imported only when tracing is on
    except ImportError as exc:
        msg = (
            "Langfuse keys are set but the 'langfuse' package is not installed. "
            "Install agent-core with the langfuse extra: agent-core[langfuse]"
        )
        raise TracingUnavailableError(msg) from exc

    public_key = settings.langfuse_public_key
    secret_key = settings.langfuse_secret_key
    if public_key is None or secret_key is None:  # pragma: no cover - ruled out by tracing_configured
        return Tracing(enabled=False)

    client = Langfuse(
        public_key=public_key.get_secret_value(),
        secret_key=secret_key.get_secret_value(),
        base_url=str(settings.langfuse_base_url),
        environment=settings.environment,
    )
    log.info("tracing enabled", backend="langfuse", base_url=str(settings.langfuse_base_url))
    return Tracing(enabled=True, client=client)
