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
| **LLM gateway** | One async client for Groq, Gemini and OpenRouter with automatic fallback, retries and validated JSON replies |

## Install

agent-core is released as Git tags. In a service's repo:

```bash
uv add "agent-core @ git+https://github.com/Dawoodikram482/agent-core@v0.2.0"

# with Langfuse tracing support
uv add "agent-core[langfuse] @ git+https://github.com/Dawoodikram482/agent-core@v0.2.0"
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

## LLM gateway

`LLMGateway` sends OpenAI-compatible chat requests to the providers in `LLM_PROVIDERS`,
in order, and returns the same `ChatResult` whichever one answered.

```python
from pydantic import BaseModel

from agent_core import LLMGateway, LLMSettings, bootstrap


class Winner(BaseModel):
    driver: str
    team: str


settings, tracing = bootstrap(LLMSettings)  # or your own subclass of LLMSettings

async with LLMGateway.from_settings(settings) as llm:
    result = await llm.chat([{"role": "user", "content": "Who won the 2026 Singapore GP?"}])
    print(result.text, result.provider, result.usage.total_tokens, result.latency_ms)

    reply = await llm.chat_json([{"role": "user", "content": "Who won? Answer as JSON."}], Winner)
    print(reply.data.driver)  # validated Winner instance
```

How failures are handled:

| What happens | What the gateway does |
| --- | --- |
| HTTP 429 (rate limited) | Tries the next provider straight away |
| Timeout, connection error, HTTP 5xx, malformed reply | Retries with exponential backoff and jitter (`LLM_MAX_ATTEMPTS`), then the next provider |
| Other HTTP 4xx (bad request, bad key, unknown model) | Raises `LLMRequestError`: no retry, no fallback |
| Every provider failed | Raises `AllProvidersFailedError`, listing what happened at each |
| `chat_json` reply does not match the schema | Shows the model the errors and asks once more, then raises `InvalidJSONResponseError` |

Each provider has a concurrency cap (`GROQ_MAX_CONCURRENCY` and so on), so a burst of calls
stays within its free tier. Check your keys and model names against the real providers with
`uv run python examples/smoke.py` (uses a few hundred tokens).

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

LLM gateway settings (`LLMSettings`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDERS` | `groq,gemini` | Providers in fallback order: `groq`, `gemini`, `openrouter` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | (none) | A provider is used only when its key is set |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model per provider; check the provider's console for current names |
| `GEMINI_MODEL` | `gemini-flash-latest` | |
| `OPENROUTER_MODEL` | `meta-llama/llama-3.3-70b-instruct:free` | |
| `<NAME>_BASE_URL` | provider's OpenAI-compatible URL | Override for proxies or tests |
| `<NAME>_MAX_CONCURRENCY` | 4 (OpenRouter 2) | Simultaneous requests per provider |
| `LLM_TIMEOUT_SECONDS` | `30` | Timeout per request |
| `LLM_MAX_ATTEMPTS` | `3` | Requests per provider before falling back |
| `LLM_BACKOFF_BASE_SECONDS` / `LLM_BACKOFF_MAX_SECONDS` | `0.5` / `8` | Backoff range between retries |

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
| `LLMSettings` | Agent settings plus LLM providers and retry policy |
| `LLMGateway.from_settings(settings)` | Gateway over the configured providers (use with `async with`) |
| `LLMGateway.chat(messages, ...)` | One chat call with fallback; returns `ChatResult` |
| `LLMGateway.chat_json(messages, Model, ...)` | Validated structured reply; returns `JsonChatResult` |

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync              # install everything, including Langfuse for the tests
uv run poe hooks     # install the git pre-commit hooks
uv run poe check     # lint, mypy --strict and tests (fails below 80% coverage)
```

Releases are automatic: bump `version` in `pyproject.toml` and add a matching section to
`CHANGELOG.md` in the same pull request. Merging it tags `v<version>` and publishes the
release notes.

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
└── llm/
    ├── gateway.py           LLMGateway, RetryPolicy: fallback, retries, chat_json
    ├── settings.py          LLMSettings, ProviderConfig
    ├── models.py            ChatMessage, ChatResult, TokenUsage, JsonChatResult
    └── errors.py            LLMRequestError, AllProvidersFailedError, ...
examples/smoke.py            manual check against the real providers
tests/                       one test module per source module
docs/adr/                    architecture decision records
```

## Design decisions

- [ADR 1: Record architecture decisions](docs/adr/0001-record-architecture-decisions.md)
- [ADR 2: Use poethepoet as the task runner](docs/adr/0002-poethepoet-task-runner.md)
- [ADR 3: agent-core is a library, not a service](docs/adr/0003-agent-core-is-a-library.md)
- [ADR 4: Settings, logging and tracing stack](docs/adr/0004-settings-logging-and-tracing.md)
- [ADR 5: LLM gateway with provider fallback](docs/adr/0005-llm-gateway.md)

## License

[MIT](LICENSE)
