"""Tests for bootstrap and the public API."""

import pytest
from pydantic import SecretStr

import agent_core
from agent_core import AgentSettings, SettingsError, bootstrap


class DemoSettings(AgentSettings):
    database_url: SecretStr


def test_bootstrap_loads_settings_and_configures_logging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@db/x")
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("SERVICE_NAME", "demo")

    settings, tracing = bootstrap(DemoSettings)

    assert isinstance(settings, DemoSettings)
    assert tracing.enabled is False
    err = capsys.readouterr().err
    assert '"event": "service configured"' in err
    assert '"service": "demo"' in err
    assert "pw@db" not in err


def test_bootstrap_fails_fast_on_missing_settings() -> None:
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        bootstrap(DemoSettings)


def test_public_api_is_importable_from_the_package() -> None:
    for name in agent_core.__all__:
        assert hasattr(agent_core, name), name
