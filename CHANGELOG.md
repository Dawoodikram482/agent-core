# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

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
