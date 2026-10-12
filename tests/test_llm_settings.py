"""Tests for LLMSettings and provider configuration."""

import pytest

from agent_core.llm import LLMSettings
from agent_core.settings import SettingsError, load_settings


def test_defaults_try_groq_then_gemini() -> None:
    settings = load_settings(LLMSettings)

    assert settings.llm_providers == ["groq", "gemini"]
    assert settings.groq_model == "openai/gpt-oss-120b"
    assert settings.gemini_model == "gemini-flash-latest"
    assert settings.llm_max_attempts == 3


def test_providers_without_keys_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")

    configs = load_settings(LLMSettings).provider_configs()

    assert [c.name for c in configs] == ["gemini"]


def test_order_models_and_urls_come_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDERS", "Gemini, groq")
    monkeypatch.setenv("GROQ_API_KEY", "gq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GROQ_MAX_CONCURRENCY", "1")

    configs = load_settings(LLMSettings).provider_configs()

    assert [c.name for c in configs] == ["gemini", "groq"]
    assert configs[0].model == "gemini-test-model"
    assert configs[0].chat_completions_url == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert configs[1].chat_completions_url == "https://api.groq.com/openai/v1/chat/completions"
    assert configs[1].max_concurrency == 1


def test_empty_api_key_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")

    assert load_settings(LLMSettings).provider_configs() == []


@pytest.mark.parametrize(
    ("value", "message"),
    [("groq,chatgpt", "unknown provider"), ("groq,groq", "only once")],
)
def test_invalid_provider_lists_fail_fast(monkeypatch: pytest.MonkeyPatch, value: str, message: str) -> None:
    monkeypatch.setenv("LLM_PROVIDERS", value)

    with pytest.raises(SettingsError, match=message):
        load_settings(LLMSettings)


def test_provider_list_can_be_given_as_a_list() -> None:
    assert load_settings(LLMSettings, llm_providers=["openrouter"]).llm_providers == ["openrouter"]


def test_api_keys_stay_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_super_secret")

    settings = load_settings(LLMSettings)

    assert "gsk_super_secret" not in repr(settings)
    assert "gsk_super_secret" not in repr(settings.provider_configs())


def test_provider_list_of_wrong_type_is_rejected() -> None:
    with pytest.raises(SettingsError, match="LLM_PROVIDERS"):
        load_settings(LLMSettings, llm_providers=42)
