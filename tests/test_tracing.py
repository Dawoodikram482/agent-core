"""Tests for configure_tracing. No network calls: the Langfuse client is replaced by a fake."""

import sys
from typing import ClassVar

import langfuse
import pytest

from agent_core.observability.tracing import Tracing, TracingUnavailableError, configure_tracing
from agent_core.settings import load_settings


class FakeLangfuse:
    """Records how it was created and whether it was flushed or shut down."""

    instances: ClassVar[list["FakeLangfuse"]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.flushed = 0
        self.shut_down = False
        FakeLangfuse.instances.append(self)

    def flush(self) -> None:
        self.flushed += 1

    def shutdown(self) -> None:
        self.shut_down = True


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> type[FakeLangfuse]:
    FakeLangfuse.instances = []
    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    return FakeLangfuse


@pytest.fixture
def langfuse_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")


def test_disabled_without_keys(fake_langfuse: type[FakeLangfuse]) -> None:
    tracing = configure_tracing(load_settings())

    assert tracing == Tracing(enabled=False)
    assert fake_langfuse.instances == []


def test_disabled_handle_methods_do_nothing() -> None:
    tracing = Tracing(enabled=False)

    tracing.flush()
    tracing.shutdown()


@pytest.mark.usefixtures("langfuse_keys")
def test_enabled_with_keys(fake_langfuse: type[FakeLangfuse], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("ENVIRONMENT", "test")

    tracing = configure_tracing(load_settings())

    assert tracing.enabled is True
    (client,) = fake_langfuse.instances
    assert id(tracing.client) == id(client)
    assert client.kwargs == {
        "public_key": "pk-lf-test",
        "secret_key": "sk-lf-test",
        "base_url": "http://localhost:3000/",
        "environment": "test",
    }


@pytest.mark.usefixtures("langfuse_keys")
def test_flush_and_shutdown_reach_the_client(fake_langfuse: type[FakeLangfuse]) -> None:
    tracing = configure_tracing(load_settings())

    tracing.flush()
    tracing.shutdown()

    (client,) = fake_langfuse.instances
    assert client.flushed == 1
    assert client.shut_down is True


@pytest.mark.usefixtures("langfuse_keys")
def test_keys_without_the_package_fail_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langfuse", None)

    with pytest.raises(TracingUnavailableError, match=r"agent-core\[langfuse\]"):
        configure_tracing(load_settings())


def test_loads_settings_when_none_given(fake_langfuse: type[FakeLangfuse]) -> None:
    assert configure_tracing().enabled is False
