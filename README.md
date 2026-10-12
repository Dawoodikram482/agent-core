# agent-core

[![CI](https://github.com/Dawoodikram482/agent-core/actions/workflows/ci.yml/badge.svg)](https://github.com/Dawoodikram482/agent-core/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![mypy strict](https://img.shields.io/badge/mypy-strict-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

The shared foundation for every agent in the [Agent Avenger Project](https://github.com/Dawoodikram482/agent-avenger),
starting with Pit Wall, an AI race strategist for Formula 1. Every service installs it so
they are configured, logged and traced the same way.

| Feature | What you get |
| --- | --- |
| **Settings** | Typed settings from environment variables and `.env`, secrets as `SecretStr`, a clear error listing every missing or invalid value |
| **Logging** | structlog: JSON in production, readable console output in development, standard-library logs in the same format |
| **Correlation IDs** | One ID per request or run on every log line, safe across async tasks |
| **Secret masking** | API keys, tokens, passwords and `SecretStr` values masked before anything is written |
| **Tracing** | Langfuse when its keys are set; a no-op otherwise, so every service runs without it |

Coming next: the LLM gateway with Groq → Gemini fallback (PW-3).

## Install

agent-core is released as Git tags. In a service's repo:

```bash
uv add "agent-core @ git+https://github.com/Dawoodikram482/agent-core@v0.1.0"

# with Langfuse tracing support
uv add "agent-core[langfuse] @ git+https://github.com/Dawoodikram482/agent-core@v0.1.0"
```

## Use it

Declare the service's settings by extending `AgentSettings`, then call `bootstrap` once at startup:

```python
from pydantic import SecretStr

from agent_core import AgentSettings, bootstrap, correlation_scope, get_logger


class IngestSettings(AgentSettings):
    database_url: SecretStr  # required: startup fails clearly if DATABASE_URL is missing
    batch_size: int = 500  # optional, from BATCH_SIZE


settings, tracing = bootstrap(IngestSettings)  # settings + logging + tracing
log = get_logger(__name__)

with correlation_scope():  # new ID for this run
    log.info("session loaded", session_key=9161, rows=1234, api_key="gsk_...")
```

Console output in development (secrets masked, correlation ID added):

```text
2026-10-12T11:51:02Z [info] session loaded [pitwall.loader] api_key=********** correlation_id=3f2a... rows=1234 service=pitwall-ingest session_key=9161
```

The same line in production, as JSON:

```json
{"event": "session loaded", "level": "info", "logger": "pitwall.loader", "timestamp": "2026-10-12T11:51:02Z",
 "service": "pitwall-ingest", "env": "production", "correlation_id": "3f2a...", "session_key": 9161,
 "rows": 1234, "api_key": "**********"}
```

A missing value stops the service before it does anything, naming the variable but never the values:

```text
agent_core.settings.SettingsError: Invalid settings for IngestSettings:
  - DATABASE_URL: missing; set it in the environment or in .env
```

Call `tracing.shutdown()` when the process exits so buffered traces are sent.

## Configuration

Every service built on agent-core reads these. Copy `.env.example` to `.env` for local runs.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SERVICE_NAME` | `agent` | Name on every log line and trace |
| `ENVIRONMENT` | `development` | `development`, `test` or `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `LOG_FORMAT` | `auto` | `json`, `console`, or `auto` (console in development, JSON elsewhere) |
| `LANGFUSE_PUBLIC_KEY` | (none) | Langfuse public key; tracing is on only when both keys are set |
| `LANGFUSE_SECRET_KEY` | (none) | Langfuse secret key |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | Langfuse server, cloud or self-hosted |

Environment variables win over `.env`. Names are case-insensitive.

## API

| Name | Purpose |
| --- | --- |
| `AgentSettings` | Base class for a service's settings |
| `load_settings(cls, **overrides)` | Load settings; raises `SettingsError` listing every problem |
| `bootstrap(cls)` | Load settings, configure logging and tracing; returns `(settings, tracing)` |
| `configure_logging(settings, stream=None)` | Set up structlog and standard logging (safe to call twice) |
| `get_logger(name=None, **values)` | A structured logger, optionally with bound values |
| `correlation_scope(id=None)` | Context manager: use an ID inside a block, then restore the previous one |
| `bind_correlation_id(id=None)` / `get_correlation_id()` | Set or read the current ID |
| `configure_tracing(settings)` | Start Langfuse if configured; returns a `Tracing` handle |
| `Tracing.flush()` / `Tracing.shutdown()` | Send buffered traces / stop tracing at exit |

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync              # install everything, including Langfuse for the tests
uv run poe hooks     # install the git pre-commit hooks
uv run poe check     # lint, mypy --strict and tests (fails below 80% coverage)
```

Run `uv run poe` for all tasks.

## Project layout

```text
src/agent_core/
├── settings.py              AgentSettings, load_settings, SettingsError
├── bootstrap.py             bootstrap(): settings + logging + tracing in one call
└── observability/
    ├── logging.py           configure_logging, get_logger, secret masking
    ├── context.py           correlation IDs
    └── tracing.py           configure_tracing, Tracing
tests/                       one test module per source module
docs/adr/                    architecture decision records
```

## Design decisions

- [ADR 1: Record architecture decisions](docs/adr/0001-record-architecture-decisions.md)
- [ADR 2: Use poethepoet as the task runner](docs/adr/0002-poethepoet-task-runner.md)
- [ADR 3: agent-core is a library, not a service](docs/adr/0003-agent-core-is-a-library.md)
- [ADR 4: Settings, logging and tracing stack](docs/adr/0004-settings-logging-and-tracing.md)

## License

[MIT](LICENSE)
