"""Tests for correlation IDs."""

import asyncio

from agent_core.observability.context import (
    bind_correlation_id,
    correlation_scope,
    get_correlation_id,
    new_correlation_id,
)
from agent_core.observability.logging import configure_logging, get_logger
from agent_core.settings import load_settings
from tests.conftest import LogCapture


def test_new_ids_are_unique_hex() -> None:
    first, second = new_correlation_id(), new_correlation_id()

    assert first != second
    assert len(first) == 32
    int(first, 16)


def test_bind_uses_given_id_or_generates_one() -> None:
    assert bind_correlation_id("req-42") == "req-42"
    assert get_correlation_id() == "req-42"

    generated = bind_correlation_id()

    assert generated != "req-42"
    assert get_correlation_id() == generated


def test_no_id_by_default() -> None:
    assert get_correlation_id() is None


def test_scope_restores_the_previous_id() -> None:
    bind_correlation_id("outer")

    with correlation_scope("inner") as cid:
        assert cid == "inner"
        assert get_correlation_id() == "inner"

    assert get_correlation_id() == "outer"


def test_id_is_added_to_log_lines(capture: LogCapture) -> None:
    configure_logging(load_settings(log_format="json"), stream=capture.stream)

    with correlation_scope("run-7"):
        get_logger().info("inside")
    get_logger().info("outside")

    inside, outside = capture.records()
    assert inside["correlation_id"] == "run-7"
    assert "correlation_id" not in outside


def test_concurrent_tasks_keep_their_own_ids() -> None:
    async def task(name: str) -> tuple[str, str | None]:
        with correlation_scope(name):
            await asyncio.sleep(0.01)
            return name, get_correlation_id()

    async def main() -> list[tuple[str, str | None]]:
        return list(await asyncio.gather(task("a"), task("b"), task("c")))

    for name, seen in asyncio.run(main()):
        assert seen == name
