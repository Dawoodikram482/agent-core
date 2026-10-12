"""Shared test fixtures."""

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from agent_core.observability.logging import HANDLER_NAME

# Environment variables that AgentSettings reads; cleared so the developer's shell
# or a stray .env never leaks into a test.
SETTINGS_ENV_VARS = (
    "SERVICE_NAME",
    "ENVIRONMENT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "DATABASE_URL",
    "INGEST_DATABASE_URL",
    "INGEST_BATCH_SIZE",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Run every test in an empty folder with no settings variables, and reset logging after."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    yield
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


class LogCapture:
    """A text stream that also parses the JSON log lines written to it."""

    def __init__(self) -> None:
        self.stream = io.StringIO()

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.text.splitlines() if line.strip()]

    def last(self) -> dict[str, object]:
        return self.records()[-1]


@pytest.fixture
def capture() -> LogCapture:
    return LogCapture()
