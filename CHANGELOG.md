# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-10-12

### Fixed

- Default `GROQ_MODEL` is now `openai/gpt-oss-120b`; Groq retired `llama-3.3-70b-versatile`
  on 16 August 2026.
- An empty reply cut off by `max_tokens` (a reasoning model that spent the whole limit
  thinking) now raises `OutputTruncatedError` straight away instead of being retried as a
  malformed reply.
- `examples/smoke.py` allows 512 tokens, enough for reasoning models.

## [0.2.0] - 2026-10-12

### Added

- `LLMGateway`: async chat over OpenAI-compatible providers with ordered fallback
  (default Groq, then Gemini), returning a typed `ChatResult` with text, provider, model,
  token usage, latency and attempt count (PW-3).
- Retry policy: 429 falls back immediately; timeouts, connection errors, 5xx and malformed
  replies retry with exponential backoff and full jitter; other 4xx raise `LLMRequestError` (PW-3).
- `AllProvidersFailedError` listing each provider's failure (PW-3).
- `chat_json`: replies validated against a Pydantic model, with one retry on invalid JSON (PW-3).
- `LLMSettings`: provider order, models, URLs, concurrency caps and retry policy from the environment (PW-3).
- `examples/smoke.py`: manual check against the real providers (PW-3).
- Release workflow: merging a new version to main tags it and publishes release notes from this file.

### Changed

- CI runs on Linux for pull requests and on Linux and Windows for pushes to main.

## [0.1.0] - 2026-10-12

### Added

- `AgentSettings` and `load_settings`: typed settings from environment variables and `.env`,
  secrets as `SecretStr`, and a `SettingsError` that names every missing or invalid variable (PW-2).
- `configure_logging` and `get_logger`: structlog with JSON or console output, standard-library
  logs in the same format, and masking of secret values and secret-looking keys (PW-2).
- Correlation IDs: `correlation_scope`, `bind_correlation_id`, `get_correlation_id` (PW-2).
- `configure_tracing` and `Tracing`: optional Langfuse tracing via the `langfuse` extra (PW-2).
- `bootstrap`: settings, logging and tracing in one call (PW-2).
- Project created from python-service-template and trimmed to a library (ADR 3).
