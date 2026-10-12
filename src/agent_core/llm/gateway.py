"""The LLM gateway: one async client for every OpenAI-compatible provider, with fallback.

How a call is routed:

1. Providers are tried in order (default Groq, then Gemini).
2. HTTP 429 (rate limited) moves on to the next provider immediately.
3. Timeouts, connection errors, 5xx responses and malformed replies are retried with
   exponential backoff and full jitter, up to ``max_attempts`` per provider, then the
   gateway falls back to the next provider.
4. Any other 4xx (bad request, bad key, unknown model) raises :class:`LLMRequestError`
   straight away: retrying or falling back would only hide the mistake.
5. An empty answer cut off by ``max_tokens`` (a reasoning model that spent the whole
   limit thinking) raises :class:`OutputTruncatedError` straight away, for the same reason.
6. If no provider answers, :class:`AllProvidersFailedError` lists what happened at each.

Each provider has its own concurrency cap, so a burst of calls cannot exceed what its
free tier tolerates.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, ValidationError

from agent_core.llm.errors import (
    AllProvidersFailedError,
    InvalidJSONResponseError,
    LLMRequestError,
    NoProvidersConfiguredError,
    OutputTruncatedError,
    ProviderFailure,
)
from agent_core.llm.models import (
    ChatMessage,
    ChatResult,
    JsonChatResult,
    MessagesInput,
    TokenUsage,
    to_messages,
)
from agent_core.llm.settings import LLMSettings, ProviderConfig
from agent_core.observability.logging import get_logger

log = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]

_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class RetryPolicy:
    """How often and how patiently to retry one provider.

    Attributes:
        max_attempts: Requests per provider before falling back (1 = no retries).
        backoff_base_seconds: Upper bound of the first wait; doubles each retry.
        backoff_max_seconds: Cap on any single wait.
    """

    max_attempts: int = 3
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 8.0

    def delay(self, attempt: int, rand: float) -> float:
        """Wait before retry number ``attempt`` (1-based), with full jitter.

        ``rand`` is a number in [0, 1); the wait is a random fraction of the exponential cap,
        which spreads retries out when many calls fail at once.
        """
        cap: float = min(self.backoff_max_seconds, self.backoff_base_seconds * 2.0 ** (attempt - 1))
        return rand * cap


class _RetryableError(Exception):
    """An attempt failed in a way worth retrying (internal)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _RateLimitedError(Exception):
    """The provider answered 429 (internal)."""


class LLMGateway:
    """Async chat client over several OpenAI-compatible providers, with fallback.

    Create it from settings and use it as an async context manager so the HTTP
    connections are closed::

        async with LLMGateway.from_settings(load_settings(LLMSettings)) as llm:
            result = await llm.chat([{"role": "user", "content": "Who won Monza 2026?"}])
    """

    def __init__(
        self,
        providers: list[ProviderConfig],
        *,
        retry: RetryPolicy | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        """Create a gateway.

        Args:
            providers: Providers in fallback order; usually ``settings.provider_configs()``.
            retry: Retry policy per provider.
            timeout_seconds: Timeout for each HTTP request.
            client: HTTP client to use (tests pass one); the gateway creates and owns one otherwise.
            sleep: Awaitable used to wait between retries (tests pass a fake).
            rand: Source of random numbers in [0, 1) for jitter.

        Raises:
            NoProvidersConfiguredError: If ``providers`` is empty.
        """
        if not providers:
            msg = "No LLM provider has an API key. Set GROQ_API_KEY or GEMINI_API_KEY (see LLM_PROVIDERS)."
            raise NoProvidersConfiguredError(msg)
        self._providers = providers
        self._retry = retry or RetryPolicy()
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._sleep = sleep
        self._rand = rand
        self._limits = {p.name: asyncio.Semaphore(p.max_concurrency) for p in providers}

    @classmethod
    def from_settings(cls, settings: LLMSettings, *, client: httpx.AsyncClient | None = None) -> Self:
        """Build a gateway from :class:`LLMSettings`."""
        retry = RetryPolicy(
            max_attempts=settings.llm_max_attempts,
            backoff_base_seconds=settings.llm_backoff_base_seconds,
            backoff_max_seconds=settings.llm_backoff_max_seconds,
        )
        return cls(
            settings.provider_configs(),
            retry=retry,
            timeout_seconds=settings.llm_timeout_seconds,
            client=client,
        )

    @property
    def providers(self) -> list[str]:
        """Provider names in fallback order."""
        return [p.name for p in self._providers]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client if the gateway created it."""
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        messages: MessagesInput,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **options: Any,  # noqa: ANN401 - passed through to the provider unchanged
    ) -> ChatResult:
        """Send a chat request, falling back across providers.

        Args:
            messages: The conversation, as :class:`ChatMessage` objects or role/content dicts.
            temperature: Sampling temperature; provider default when omitted.
            max_tokens: Maximum tokens to generate; provider default when omitted.
            **options: Extra OpenAI-compatible fields (e.g. ``response_format``, ``stop``).

        Raises:
            LLMRequestError: A provider rejected the request itself (not retried).
            OutputTruncatedError: The model used up ``max_tokens`` before answering.
            AllProvidersFailedError: No provider produced an answer.
        """
        payload_base: dict[str, Any] = {"messages": [m.model_dump() for m in to_messages(messages)]}
        if temperature is not None:
            payload_base["temperature"] = temperature
        if max_tokens is not None:
            payload_base["max_tokens"] = max_tokens
        payload_base.update(options)

        failures: list[ProviderFailure] = []
        total_attempts = 0
        for provider in self._providers:
            attempts = 0
            reason = "no attempt made"
            while attempts < self._retry.max_attempts:
                attempts += 1
                total_attempts += 1
                try:
                    result = await self._attempt(provider, payload_base, total_attempts)
                except _RateLimitedError:
                    reason = "rate limited (HTTP 429)"
                    log.warning("llm provider rate limited", provider=provider.name, attempt=attempts)
                    break
                except _RetryableError as exc:
                    reason = exc.reason
                    log.warning("llm attempt failed", provider=provider.name, attempt=attempts, reason=reason)
                    if attempts < self._retry.max_attempts:
                        await self._sleep(self._retry.delay(attempts, self._rand()))
                    continue
                log.info(
                    "llm call succeeded",
                    provider=result.provider,
                    model=result.model,
                    prompt_tokens=result.usage.prompt_tokens,
                    completion_tokens=result.usage.completion_tokens,
                    latency_ms=round(result.latency_ms, 1),
                    attempts=result.attempts,
                )
                return result
            failures.append(ProviderFailure(provider.name, reason, attempts))
            log.warning("llm falling back", provider=provider.name, reason=reason)

        raise AllProvidersFailedError(failures)

    async def chat_json[T: BaseModel](
        self,
        messages: MessagesInput,
        schema: type[T],
        *,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        **options: Any,  # noqa: ANN401 - passed through to the provider unchanged
    ) -> JsonChatResult[T]:
        """Ask for a JSON reply and validate it against a Pydantic model.

        The schema is added to the conversation as a system message and JSON mode is
        requested. If the reply is not valid JSON for the schema, the model is shown the
        error and asked once more.

        Raises:
            InvalidJSONResponseError: The second reply was still invalid.
            LLMRequestError, AllProvidersFailedError: As for :meth:`chat`.
        """
        conversation = [_schema_instruction(schema), *to_messages(messages)]
        options.setdefault("response_format", {"type": "json_object"})

        result = await self.chat(conversation, temperature=temperature, max_tokens=max_tokens, **options)
        try:
            return JsonChatResult(data=_parse_json(result.text, schema), result=result)
        except ValidationError as first_error:
            log.warning("llm reply did not match schema; retrying once", schema=schema.__name__)
            retry_conversation = [
                *conversation,
                ChatMessage(role="assistant", content=result.text),
                ChatMessage(
                    role="user",
                    content=(
                        "That reply was not valid JSON for the schema. Errors:\n"
                        f"{_summarise(first_error)}\n"
                        "Reply again with only the corrected JSON object."
                    ),
                ),
            ]

        result = await self.chat(
            retry_conversation, temperature=temperature, max_tokens=max_tokens, **options
        )
        try:
            return JsonChatResult(data=_parse_json(result.text, schema), result=result)
        except ValidationError as second_error:
            raise InvalidJSONResponseError(schema.__name__, _summarise(second_error)) from None

    async def _attempt(
        self, provider: ProviderConfig, payload_base: dict[str, Any], attempt_no: int
    ) -> ChatResult:
        payload = {"model": provider.model, **payload_base}
        headers = {"Authorization": f"Bearer {provider.api_key.get_secret_value()}"}
        async with self._limits[provider.name]:
            started = time.perf_counter()
            try:
                response = await self._client.post(
                    provider.chat_completions_url, json=payload, headers=headers
                )
            except httpx.TimeoutException as exc:
                raise _RetryableError("timed out") from exc
            except httpx.TransportError as exc:
                raise _RetryableError(f"connection error ({type(exc).__name__})") from exc
            latency_ms = (time.perf_counter() - started) * 1000

        status = response.status_code
        if status == 429:
            raise _RateLimitedError
        if status >= 500:
            raise _RetryableError(f"server error (HTTP {status})")
        if status >= 400:
            error = LLMRequestError(provider.name, status, _error_detail(response))
            log.error("llm request rejected", provider=provider.name, status=status, detail=error.detail)
            raise error

        try:
            body = response.json()
            choice = body["choices"][0]
            text = choice["message"].get("content")
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length" and not text:
                truncated = OutputTruncatedError(
                    provider.name, provider.model, payload_base.get("max_tokens")
                )
                log.error("llm output truncated", provider=provider.name, model=provider.model)
                raise truncated
            if not isinstance(text, str):
                raise TypeError("content is not text")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise _RetryableError("malformed response") from exc

        return ChatResult(
            text=text,
            provider=provider.name,
            model=str(body.get("model") or provider.model),
            usage=TokenUsage.model_validate(body.get("usage") or {}),
            latency_ms=latency_ms,
            attempts=attempt_no,
            finish_reason=finish_reason,
        )


def _schema_instruction(schema: type[BaseModel]) -> ChatMessage:
    schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
    return ChatMessage(
        role="system",
        content=(
            "Reply with only a JSON object, no prose and no code fences. "
            f"It must match this JSON Schema: {schema_json}"
        ),
    )


def _parse_json[T: BaseModel](text: str, schema: type[T]) -> T:
    fenced = _JSON_FENCE.match(text)
    return schema.model_validate_json(fenced.group(1) if fenced else text.strip())


def _summarise(error: ValidationError, limit: int = 5) -> str:
    lines = []
    for item in error.errors(include_input=False, include_url=False)[:limit]:
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"- {location}: {item['msg']}")
    return "\n".join(lines)


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and "message" in error:
            return str(error["message"])[:200]
        if isinstance(error, list) and error and isinstance(error[0], dict):
            return str(error[0].get("error", {}).get("message", error[0]))[:200]
    return str(body)[:200]
