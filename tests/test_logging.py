"""Tests for configure_logging, redaction and stdlib integration."""

import logging
from datetime import datetime

import pytest
from pydantic import SecretStr

from agent_core.observability.logging import REDACTED, configure_logging, get_logger, redact_secrets
from agent_core.settings import load_settings
from tests.conftest import LogCapture


def json_logging(capture: LogCapture, **overrides: object) -> None:
    configure_logging(load_settings(log_format="json", **overrides), stream=capture.stream)


def test_json_line_has_standard_fields(capture: LogCapture) -> None:
    json_logging(capture, service_name="pitwall-ingest", environment="test")

    get_logger("pitwall.loader").info("session loaded", session_key=9161, rows=1234)

    record = capture.last()
    assert record["event"] == "session loaded"
    assert record["level"] == "info"
    assert record["logger"] == "pitwall.loader"
    assert record["service"] == "pitwall-ingest"
    assert record["env"] == "test"
    assert record["session_key"] == 9161
    assert record["rows"] == 1234
    timestamp = datetime.fromisoformat(str(record["timestamp"]))
    assert timestamp.utcoffset() is not None
    assert timestamp.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_auto_format_is_console_in_development(capture: LogCapture) -> None:
    configure_logging(load_settings(environment="development"), stream=capture.stream)

    get_logger().info("hello", lap=12)

    assert "hello" in capture.text
    assert "lap=12" in capture.text
    assert not capture.text.lstrip().startswith("{")


def test_auto_format_is_json_outside_development(capture: LogCapture) -> None:
    configure_logging(load_settings(environment="production"), stream=capture.stream)

    get_logger().info("hello")

    assert capture.last()["event"] == "hello"


def test_level_filters_lower_levels(capture: LogCapture) -> None:
    json_logging(capture, log_level="WARNING")

    log = get_logger()
    log.info("not shown")
    log.warning("shown")

    assert [r["event"] for r in capture.records()] == ["shown"]


def test_secret_values_and_secret_keys_are_masked(capture: LogCapture) -> None:
    json_logging(capture)

    get_logger().info(
        "calling provider",
        api_key="gsk_live_123",
        authorization="Bearer abc",
        database_password="hunter2",  # noqa: S106 - test value
        client=SecretStr("sk-xyz"),
        headers={"Authorization": "Bearer abc", "Accept": "json"},
        attempts=[{"token": "t-1"}, {"status": 429}],
    )

    record = capture.last()
    assert record["api_key"] == REDACTED
    assert record["authorization"] == REDACTED
    assert record["database_password"] == REDACTED
    assert record["client"] == REDACTED
    assert record["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert record["attempts"] == [{"token": REDACTED}, {"status": 429}]
    for secret in ("gsk_live_123", "Bearer abc", "hunter2", "sk-xyz", "t-1"):
        assert secret not in capture.text


def test_token_counts_are_not_mistaken_for_secrets(capture: LogCapture) -> None:
    json_logging(capture)

    get_logger().info("llm call", prompt_tokens=120, completion_tokens=40, max_tokens=512)

    record = capture.last()
    assert (record["prompt_tokens"], record["completion_tokens"], record["max_tokens"]) == (120, 40, 512)


def test_redact_processor_leaves_event_and_none_alone() -> None:
    event = {"event": "token refreshed", "token": None, "lap": 3}

    assert redact_secrets(None, "info", event) == {"event": "token refreshed", "token": None, "lap": 3}


def test_stdlib_logs_use_the_same_format(capture: LogCapture) -> None:
    json_logging(capture, service_name="pitwall-mcp")

    logging.getLogger("uvicorn.error").warning("port %s in use", 8000)

    record = capture.last()
    assert record["event"] == "port 8000 in use"
    assert record["logger"] == "uvicorn.error"
    assert record["level"] == "warning"
    assert record["service"] == "pitwall-mcp"


def test_exceptions_are_structured_in_json(capture: LogCapture) -> None:
    json_logging(capture)

    try:
        _ = 1 / 0
    except ZeroDivisionError:
        get_logger().exception("calculation failed")

    record = capture.last()
    assert record["event"] == "calculation failed"
    assert "ZeroDivisionError" in str(record["exception"])


def test_configuring_twice_does_not_duplicate_output(capture: LogCapture) -> None:
    json_logging(capture)
    json_logging(capture)

    get_logger().info("once")

    assert len(capture.records()) == 1


def test_bound_values_appear_on_every_line(capture: LogCapture) -> None:
    json_logging(capture)

    log = get_logger(run="r-1")
    log.info("start")
    log.info("end")

    assert [r["run"] for r in capture.records()] == ["r-1", "r-1"]


def test_defaults_to_stderr_and_loaded_settings(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()

    get_logger().warning("to stderr")

    assert '"event": "to stderr"' in capsys.readouterr().err
