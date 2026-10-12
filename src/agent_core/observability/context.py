"""Correlation IDs: one ID per request or run, added to every log line it produces.

The ID lives in a context variable, so it follows async tasks and threads started with
``contextvars.copy_context`` without being passed around by hand.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import structlog

CORRELATION_ID_KEY = "correlation_id"


def new_correlation_id() -> str:
    """Return a new random correlation ID (32 hex characters)."""
    return uuid.uuid4().hex


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Set the correlation ID for the current context and return it.

    Args:
        correlation_id: An ID received from a caller (for example an ``X-Correlation-ID``
            header). A new one is generated when omitted.
    """
    value = correlation_id or new_correlation_id()
    structlog.contextvars.bind_contextvars(**{CORRELATION_ID_KEY: value})
    return value


def get_correlation_id() -> str | None:
    """Return the correlation ID of the current context, if one is set."""
    value = structlog.contextvars.get_contextvars().get(CORRELATION_ID_KEY)
    return value if isinstance(value, str) else None


@contextmanager
def correlation_scope(correlation_id: str | None = None) -> Iterator[str]:
    """Use a correlation ID inside a ``with`` block, then restore the previous one.

    Example:
        >>> with correlation_scope() as cid:
        ...     log.info("run started")  # carries correlation_id=cid
    """
    value = correlation_id or new_correlation_id()
    tokens = structlog.contextvars.bind_contextvars(**{CORRELATION_ID_KEY: value})
    try:
        yield value
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
