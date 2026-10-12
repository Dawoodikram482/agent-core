"""Tests for LLMGateway. All HTTP is mocked with respx: no real provider is ever called."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr

from agent_core.llm import (
    AllProvidersFailedError,
    ChatMessage,
    InvalidJSONResponseError,
    LLMGateway,
    LLMRequestError,
    LLMSettings,
    NoProvidersConfiguredError,
    OutputTruncatedError,
    ProviderConfig,
    RetryPolicy,
)
from agent_core.settings import load_settings

GROQ_URL = "https://api.groq.test/v1/chat/completions"
GEMINI_URL = "https://gemini.test/v1/chat/completions"
QUESTION = [{"role": "user", "content": "Who won the 2026 Singapore GP?"}]


def provider(name: str, base: str, *, max_concurrency: int = 4) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url=base,
        api_key=SecretStr(f"{name}-key"),
        model=f"{name}-model",
        max_concurrency=max_concurrency,
    )


GROQ = provider("groq", "https://api.groq.test/v1")
GEMINI = provider("gemini", "https://gemini.test/v1")


def completion(
    text: str, *, model: str = "served-model", usage: dict[str, int] | None = None
) -> httpx.Response:
    body: dict[str, Any] = {
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


class Sleeps:
    """Fake asyncio.sleep that records the delays it was asked to wait."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
async def make_gateway(sleeps: Sleeps) -> AsyncIterator[Callable[..., LLMGateway]]:
    clients: list[httpx.AsyncClient] = []

    def factory(*providers: ProviderConfig, max_attempts: int = 3) -> LLMGateway:
        client = httpx.AsyncClient()
        clients.append(client)
        return LLMGateway(
            list(providers or (GROQ, GEMINI)),
            retry=RetryPolicy(max_attempts=max_attempts, backoff_base_seconds=0.5, backoff_max_seconds=4),
            client=client,
            sleep=sleeps,
            rand=lambda: 1.0,
        )

    yield factory
    for client in clients:
        await client.aclose()


# --- happy path ---------------------------------------------------------------


@respx.mock
async def test_first_provider_answers(make_gateway: Callable[..., LLMGateway]) -> None:
    route = respx.post(GROQ_URL).mock(
        return_value=completion(
            "Norris won.", usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
        )
    )

    result = await make_gateway().chat(QUESTION, temperature=0.2, max_tokens=50)

    assert result.text == "Norris won."
    assert result.provider == "groq"
    assert result.model == "served-model"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens, result.usage.total_tokens) == (
        12,
        3,
        15,
    )
    assert result.attempts == 1
    assert result.finish_reason == "stop"
    assert result.latency_ms >= 0

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer groq-key"
    assert json.loads(request.content) == {
        "model": "groq-model",
        "messages": QUESTION,
        "temperature": 0.2,
        "max_tokens": 50,
    }


@respx.mock
async def test_accepts_chat_message_objects_and_extra_options(
    make_gateway: Callable[..., LLMGateway],
) -> None:
    route = respx.post(GROQ_URL).mock(return_value=completion("ok"))

    await make_gateway().chat([ChatMessage(role="system", content="Be brief.")], stop=["\n"])

    sent = json.loads(route.calls.last.request.content)
    assert sent["messages"] == [{"role": "system", "content": "Be brief."}]
    assert sent["stop"] == ["\n"]
    assert "temperature" not in sent


@respx.mock
async def test_missing_usage_and_model_fall_back_to_defaults(make_gateway: Callable[..., LLMGateway]) -> None:
    body = {"choices": [{"message": {"content": "ok"}}]}
    respx.post(GROQ_URL).mock(return_value=httpx.Response(200, json=body))

    result = await make_gateway().chat(QUESTION)

    assert result.usage.total_tokens == 0
    assert result.model == "groq-model"
    assert result.finish_reason is None


# --- fallback and retries -----------------------------------------------------


@respx.mock
async def test_rate_limit_falls_back_immediately(
    make_gateway: Callable[..., LLMGateway], sleeps: Sleeps
) -> None:
    groq = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    respx.post(GEMINI_URL).mock(return_value=completion("from gemini"))

    result = await make_gateway().chat(QUESTION)

    assert result.provider == "gemini"
    assert result.attempts == 2
    assert groq.call_count == 1
    assert sleeps.delays == []


@respx.mock
async def test_server_errors_are_retried_with_backoff(
    make_gateway: Callable[..., LLMGateway], sleeps: Sleeps
) -> None:
    groq = respx.post(GROQ_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(502), completion("third time lucky")]
    )

    result = await make_gateway().chat(QUESTION)

    assert result.text == "third time lucky"
    assert result.attempts == 3
    assert groq.call_count == 3
    assert sleeps.delays == [0.5, 1.0]


@respx.mock
async def test_timeouts_and_connection_errors_are_retried(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), completion("ok")]
    )

    assert (await make_gateway().chat(QUESTION)).text == "ok"


@respx.mock
async def test_malformed_replies_are_retried(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(200, text="<html>oops</html>"),
            httpx.Response(200, json={"choices": []}),
            httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        ]
    )
    respx.post(GEMINI_URL).mock(
        side_effect=[httpx.Response(200, json={"choices": [{"message": "not an object"}]}), completion("ok")]
    )

    result = await make_gateway().chat(QUESTION)

    assert result.provider == "gemini"
    assert result.attempts == 5


def truncated(content: str | None) -> httpx.Response:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    choice = {"index": 0, "message": message, "finish_reason": "length"}
    return httpx.Response(200, json={"model": "served-model", "choices": [choice]})


@respx.mock
@pytest.mark.parametrize("content", [None, ""])
async def test_empty_answer_cut_off_by_max_tokens_raises_at_once(
    make_gateway: Callable[..., LLMGateway], content: str | None
) -> None:
    groq = respx.post(GROQ_URL).mock(return_value=truncated(content))
    gemini = respx.post(GEMINI_URL).mock(return_value=completion("unused"))

    with pytest.raises(OutputTruncatedError) as caught:
        await make_gateway().chat(QUESTION, max_tokens=20)

    assert caught.value.provider == "groq"
    assert caught.value.model == "groq-model"
    assert caught.value.max_tokens == 20
    assert "max_tokens=20" in str(caught.value)
    assert groq.call_count == 1
    assert not gemini.called


@respx.mock
async def test_truncation_without_a_limit_names_the_token_limit(
    make_gateway: Callable[..., LLMGateway],
) -> None:
    respx.post(GROQ_URL).mock(return_value=truncated(None))

    with pytest.raises(OutputTruncatedError, match="the token limit") as caught:
        await make_gateway().chat(QUESTION)

    assert caught.value.max_tokens is None


@respx.mock
async def test_partial_answer_cut_off_by_max_tokens_is_returned(
    make_gateway: Callable[..., LLMGateway],
) -> None:
    respx.post(GROQ_URL).mock(return_value=truncated("Pit wall onl"))

    result = await make_gateway().chat(QUESTION, max_tokens=5)

    assert result.text == "Pit wall onl"
    assert result.finish_reason == "length"


@respx.mock
async def test_falls_back_after_exhausting_retries(
    make_gateway: Callable[..., LLMGateway], sleeps: Sleeps
) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(500))
    respx.post(GEMINI_URL).mock(return_value=completion("gemini to the rescue"))

    result = await make_gateway().chat(QUESTION)

    assert result.provider == "gemini"
    assert result.attempts == 4
    assert sleeps.delays == [0.5, 1.0]


@respx.mock
async def test_all_providers_failing_lists_each_failure(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(429))
    respx.post(GEMINI_URL).mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await make_gateway().chat(QUESTION)

    failures = excinfo.value.failures
    assert [(f.provider, f.reason, f.attempts) for f in failures] == [
        ("groq", "rate limited (HTTP 429)", 1),
        ("gemini", "timed out", 3),
    ]
    assert "groq: rate limited (HTTP 429) (1 attempt)" in str(excinfo.value)
    assert "gemini: timed out (3 attempts)" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "body", "detail"),
    [
        (400, {"error": {"message": "model does not exist"}}, "model does not exist"),
        (401, {"error": {"message": "Invalid API Key"}}, "Invalid API Key"),
        (403, [{"error": {"code": 403, "message": "API key not valid"}}], "API key not valid"),
        (404, None, "Not Found"),
    ],
)
@respx.mock
async def test_client_errors_raise_without_retry_or_fallback(
    make_gateway: Callable[..., LLMGateway], status: int, body: object, detail: str
) -> None:
    groq = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    )
    gemini = respx.post(GEMINI_URL).mock(return_value=completion("should not be used"))

    with pytest.raises(LLMRequestError) as excinfo:
        await make_gateway().chat(QUESTION)

    assert excinfo.value.provider == "groq"
    assert excinfo.value.status_code == status
    assert detail in excinfo.value.detail
    assert groq.call_count == 1
    assert gemini.call_count == 0


@respx.mock
async def test_plain_text_error_bodies_are_reported(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(422, text="bad things"))

    with pytest.raises(LLMRequestError, match="bad things"):
        await make_gateway().chat(QUESTION)


# --- concurrency --------------------------------------------------------------


@respx.mock
async def test_concurrency_cap_per_provider(make_gateway: Callable[..., LLMGateway]) -> None:
    in_flight = 0
    peak = 0

    async def slow_reply(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return completion("ok")

    respx.post(GROQ_URL).mock(side_effect=slow_reply)
    gateway = make_gateway(provider("groq", "https://api.groq.test/v1", max_concurrency=2))

    await asyncio.gather(*(gateway.chat(QUESTION) for _ in range(6)))

    assert peak == 2


# --- chat_json ----------------------------------------------------------------


class Winner(BaseModel):
    driver: str
    team: str
    position: int


@respx.mock
async def test_chat_json_validates_the_reply(make_gateway: Callable[..., LLMGateway]) -> None:
    route = respx.post(GROQ_URL).mock(
        return_value=completion('{"driver": "Norris", "team": "McLaren", "position": 1}')
    )

    reply = await make_gateway().chat_json(QUESTION, Winner)

    assert reply.data == Winner(driver="Norris", team="McLaren", position=1)
    assert reply.result.provider == "groq"
    sent = json.loads(route.calls.last.request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0.0
    assert sent["messages"][0]["role"] == "system"
    assert '"driver"' in sent["messages"][0]["content"]


@respx.mock
async def test_chat_json_strips_code_fences(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(
        return_value=completion('```json\n{"driver": "Piastri", "team": "McLaren", "position": 2}\n```')
    )

    assert (await make_gateway().chat_json(QUESTION, Winner)).data.driver == "Piastri"


@respx.mock
async def test_chat_json_retries_once_with_the_error(make_gateway: Callable[..., LLMGateway]) -> None:
    route = respx.post(GROQ_URL).mock(
        side_effect=[
            completion('{"driver": "Norris"}'),
            completion('{"driver": "Norris", "team": "McLaren", "position": 1}'),
        ]
    )

    reply = await make_gateway().chat_json(QUESTION, Winner)

    assert reply.data.team == "McLaren"
    retry_messages = json.loads(route.calls.last.request.content)["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": '{"driver": "Norris"}'}
    assert "team: Field required" in retry_messages[-1]["content"]


@respx.mock
async def test_chat_json_gives_up_after_the_retry(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(side_effect=[completion("not json at all"), completion('{"driver": 7}')])

    with pytest.raises(InvalidJSONResponseError) as excinfo:
        await make_gateway().chat_json(QUESTION, Winner)

    assert excinfo.value.schema_name == "Winner"
    assert "driver" in excinfo.value.detail


# --- construction and lifecycle -----------------------------------------------


def test_no_providers_is_a_clear_error() -> None:
    with pytest.raises(NoProvidersConfiguredError, match="GROQ_API_KEY"):
        LLMGateway([])


def test_backoff_doubles_and_is_capped() -> None:
    policy = RetryPolicy(backoff_base_seconds=0.5, backoff_max_seconds=3)

    assert [policy.delay(n, 1.0) for n in (1, 2, 3, 4)] == [0.5, 1.0, 2.0, 3.0]
    assert policy.delay(3, 0.25) == 0.5


async def test_from_settings_uses_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "5")

    async with LLMGateway.from_settings(load_settings(LLMSettings)) as gateway:
        assert gateway.providers == ["gemini"]
        assert gateway._retry.max_attempts == 5


async def test_gateway_closes_only_its_own_client() -> None:
    own = LLMGateway([GROQ])
    await own.aclose()
    assert own._client.is_closed

    shared = httpx.AsyncClient()
    borrowed = LLMGateway([GROQ], client=shared)
    await borrowed.aclose()
    assert not shared.is_closed
    await shared.aclose()


@respx.mock
async def test_unusual_error_bodies_are_still_reported(make_gateway: Callable[..., LLMGateway]) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(400, json={"detail": "context too long"}))

    with pytest.raises(LLMRequestError, match="context too long"):
        await make_gateway().chat(QUESTION)
