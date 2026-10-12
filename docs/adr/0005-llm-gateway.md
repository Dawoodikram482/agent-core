# 5. LLM gateway with provider fallback

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Every Pit Wall agent calls LLMs, and the project runs only on free tiers (Groq, Gemini).
Free tiers rate-limit hard and change their limits and model names often. We need one
client that:

- survives rate limits and transient errors without crashing a run,
- lets providers and models change through configuration, not code,
- returns the same typed result whichever provider answered,
- produces validated structured output (JSON matching a schema) for tools and evals.

## Decision

`agent_core.llm.LLMGateway`, an async client over OpenAI-compatible chat completions:

- **One protocol.** Groq, Gemini and OpenRouter all expose `/chat/completions` in the
  OpenAI format, so one code path serves every provider. The gateway calls it with
  `httpx` directly.
- **Ordered fallback.** Providers are tried in `LLM_PROVIDERS` order; any without an API
  key are skipped.
- **Error policy:**

  | Response | Action |
  | --- | --- |
  | 429 rate limited | next provider immediately (retrying a rate-limited free tier only wastes time) |
  | timeout, connection error, 5xx, malformed reply | retry with exponential backoff and full jitter, then next provider |
  | other 4xx (bad request, bad key, unknown model) | raise `LLMRequestError`: retrying cannot help, and a fallback would hide the mistake |
  | empty answer with `finish_reason=length` | raise `OutputTruncatedError`: the same limit would cut it off again (added in 0.2.1) |
  | every provider failed | raise `AllProvidersFailedError` listing each provider's failure |

- **Concurrency cap per provider**, so bursts stay within each free tier.
- **`chat_json`** asks for JSON mode, gives the model the JSON Schema, validates the reply
  with Pydantic and retries once with the validation errors.

## Update, 0.2.1: reasoning models

The first run against the real providers (the PW-3 smoke test) showed two things:

- Groq retired `llama-3.3-70b-versatile` on 16 August 2026. The default is now
  `openai/gpt-oss-120b`, Groq's recommended replacement.
- `gpt-oss-120b` and recent Gemini Flash models reason before answering, and those
  reasoning tokens count toward `max_tokens`. With a small limit the model can return an
  empty answer with `finish_reason=length`. The gateway used to treat that as a malformed
  reply and retry it, which could never succeed. It now raises `OutputTruncatedError`
  at once. A partial answer cut off by the limit is still returned, with
  `finish_reason="length"` on the result.

Callers should leave `max_tokens` unset, or set it with room for reasoning (hundreds of
tokens, not tens).

## Alternatives considered

- **OpenAI Python SDK:** handles the protocol, but has its own retry behaviour that would
  have to be disabled and re-implemented for cross-provider fallback, and it is a large
  dependency for one endpoint.
- **LiteLLM:** broad provider support and routing, but heavy, fast-moving, and it hides the
  retry and fallback policy we want to show and test explicitly.
- **Provider-native SDKs (google-genai, groq):** different APIs and result types per
  provider, which is exactly what the gateway removes.

## Consequences

- Swapping a model or adding OpenRouter is a `.env` change.
- Provider-specific features outside the OpenAI-compatible surface are not available.
- Token counts and timing come back on every result; caching and cost logging build on this (PW-8).
