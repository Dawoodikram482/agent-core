# 4. Settings, logging and tracing stack

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Every Pit Wall service needs configuration, logs and traces, and they must behave the
same everywhere so a problem can be followed across services. Requirements:

- Typed configuration from environment variables and `.env`, failing fast with a clear
  message, and secrets that never leak into logs.
- Structured logs: machine-readable in production, readable in development, with a
  correlation ID that follows a request through async code.
- LLM tracing that is optional, so services and CI run without a tracing account.

## Decision

- **Settings: pydantic-settings.** `AgentSettings` is a `BaseSettings` subclass; services
  extend it. Secrets are `SecretStr`. `load_settings` turns validation errors into one
  `SettingsError` naming each environment variable, never echoing values.
- **Logging: structlog**, with the standard library's `logging` routed through the same
  processors (`ProcessorFormatter`), so third-party logs share the format. JSON in
  production, console in development (`LOG_FORMAT=auto`). A processor masks `SecretStr`
  values and keys that look secret (token, api_key, password, authorization...) at any depth.
- **Correlation IDs: context variables** via `structlog.contextvars`, so each async task
  keeps its own ID without passing it around.
- **Tracing: Langfuse as an optional extra** (`agent-core[langfuse]`). Enabled only when
  both keys are set; otherwise a disabled `Tracing` handle is returned. Keys set without the
  package installed is a configuration error and fails at startup.

## Alternatives considered

- **Plain `os.environ` or `python-dotenv`:** no types, no validation, error messages left to each service.
- **Standard `logging` with a JSON formatter:** works, but binding context (correlation
  IDs, run IDs) and processing pipelines are far simpler in structlog.
- **loguru:** pleasant API, but weaker standard-library integration and no context-variable binding pattern.
- **OpenTelemetry directly:** more general, but Langfuse adds LLM-specific views (prompts,
  tokens, cost) for free and already exports via OpenTelemetry underneath.
- **Langfuse as a required dependency:** simpler imports, but pulls OpenTelemetry into
  every service, including ones that never trace.

## Consequences

- One `bootstrap()` call gives any service validated settings, consistent logs and tracing.
- Secret masking matches on key names, so an unusual name holding a secret could still be
  logged; secrets should always be typed as `SecretStr`, which is masked regardless of name.
- Services that trace must depend on `agent-core[langfuse]`.
