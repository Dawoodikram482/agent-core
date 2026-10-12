"""One call to set up a service: settings, logging and tracing."""

from agent_core.observability.logging import configure_logging, get_logger
from agent_core.observability.tracing import Tracing, configure_tracing
from agent_core.settings import AgentSettings, load_settings


def bootstrap[S: AgentSettings](settings_cls: type[S]) -> tuple[S, Tracing]:
    """Load settings, configure logging, then tracing. Call once at startup.

    Example:
        >>> settings, tracing = bootstrap(IngestSettings)  # doctest: +SKIP

    Raises:
        SettingsError: If settings are missing or invalid.
        TracingUnavailableError: If Langfuse keys are set but langfuse is not installed.
    """
    settings = load_settings(settings_cls)
    configure_logging(settings)
    tracing = configure_tracing(settings)
    get_logger(__name__).info("service configured", tracing=tracing.enabled, log_level=settings.log_level)
    return settings, tracing
