"""Tests for AgentSettings and load_settings."""

from pathlib import Path

import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from agent_core.settings import AgentSettings, SettingsError, load_settings


class IngestSettings(AgentSettings):
    """A service's settings, as a service would declare them."""

    database_url: SecretStr
    batch_size: int = 500


class PrefixedSettings(AgentSettings):
    model_config = SettingsConfigDict(env_prefix="INGEST_")

    database_url: SecretStr


def test_defaults_without_any_configuration() -> None:
    settings = load_settings()

    assert settings.service_name == "agent"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_format == "auto"
    assert settings.tracing_configured is False


def test_reads_environment_variables_case_insensitively(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "pitwall-ingest")
    monkeypatch.setenv("ENVIRONMENT", "Production")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FORMAT", "JSON")

    settings = load_settings()

    assert settings.service_name == "pitwall-ingest"
    assert settings.environment == "production"
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"


def test_reads_dotenv_file_and_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("SERVICE_NAME=from-dotenv\nLOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    settings = load_settings()

    assert settings.service_name == "from-dotenv"
    assert settings.log_level == "ERROR"


def test_subclass_adds_typed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost/pitwall")
    monkeypatch.setenv("BATCH_SIZE", "250")

    settings = load_settings(IngestSettings)

    assert isinstance(settings, IngestSettings)
    assert settings.database_url.get_secret_value() == "postgresql://user:pw@localhost/pitwall"
    assert settings.batch_size == 250


def test_missing_required_value_fails_fast_with_clear_message() -> None:
    with pytest.raises(SettingsError) as excinfo:
        load_settings(IngestSettings)

    message = str(excinfo.value)
    assert "Invalid settings for IngestSettings" in message
    assert "DATABASE_URL: missing; set it in the environment or in .env" in message


def test_error_names_the_prefixed_variable() -> None:
    with pytest.raises(SettingsError, match="INGEST_DATABASE_URL: missing"):
        load_settings(PrefixedSettings)


def test_invalid_values_are_reported_without_echoing_them(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@db/x")
    monkeypatch.setenv("BATCH_SIZE", "lots-and-lots-of-rows")
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(SettingsError) as excinfo:
        load_settings(IngestSettings)

    message = str(excinfo.value)
    assert "BATCH_SIZE:" in message
    assert "LOG_LEVEL:" in message
    assert "lots-and-lots-of-rows" not in message


def test_overrides_take_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "from-env")

    assert load_settings(service_name="from-test").service_name == "from-test"


def test_secrets_never_appear_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@db/pitwall")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-very-secret")

    settings = load_settings(IngestSettings)

    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert "hunter2" not in text
        assert "sk-lf-very-secret" not in text


@pytest.mark.parametrize(
    ("public", "secret", "expected"),
    [
        ("pk-lf-1", "sk-lf-1", True),
        ("pk-lf-1", None, False),
        (None, "sk-lf-1", False),
        ("", "sk-lf-1", False),
    ],
)
def test_tracing_configured_needs_both_keys(
    monkeypatch: pytest.MonkeyPatch, public: str | None, secret: str | None, expected: bool
) -> None:
    if public is not None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", public)
    if secret is not None:
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", secret)

    assert load_settings().tracing_configured is expected


def test_settings_are_immutable() -> None:
    settings = load_settings()

    with pytest.raises(ValueError, match="frozen"):
        settings.service_name = "changed"  # type: ignore[misc]


def test_non_text_values_are_validated_not_normalised() -> None:
    with pytest.raises(SettingsError, match="LOG_LEVEL:"):
        load_settings(log_level=5)
