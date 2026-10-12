"""Errors raised by the LLM gateway."""

from dataclasses import dataclass


class LLMError(Exception):
    """Base class for every LLM gateway error."""


class NoProvidersConfiguredError(LLMError):
    """No provider in ``LLM_PROVIDERS`` has an API key, so the gateway cannot make calls."""


class LLMRequestError(LLMError):
    """The provider rejected the request itself (bad request, bad key, unknown model).

    These are not retried and do not fall back to another provider: the same request
    would fail again, and hiding a configuration mistake behind a fallback makes it
    harder to notice.
    """

    def __init__(self, provider: str, status_code: int, detail: str) -> None:
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{provider} rejected the request (HTTP {status_code}): {detail}")


class OutputTruncatedError(LLMError):
    """The model hit ``max_tokens`` before writing any answer.

    Reasoning models (e.g. ``openai/gpt-oss-120b`` on Groq, recent Gemini Flash models)
    spend part of ``max_tokens`` thinking before they reply. With a small limit they can
    use all of it and return an empty answer. Retrying with the same limit gives the same
    result, so this is raised straight away: raise ``max_tokens`` or leave it unset.
    """

    def __init__(self, provider: str, model: str, max_tokens: int | None) -> None:
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        limit = f"max_tokens={max_tokens}" if max_tokens is not None else "the token limit"
        super().__init__(
            f"{provider} ({model}) used up {limit} before answering; reasoning models need a higher limit"
        )


@dataclass(frozen=True)
class ProviderFailure:
    """Why one provider could not answer, for :class:`AllProvidersFailedError`."""

    provider: str
    reason: str
    attempts: int

    def __str__(self) -> str:
        plural = "attempt" if self.attempts == 1 else "attempts"
        return f"{self.provider}: {self.reason} ({self.attempts} {plural})"


class AllProvidersFailedError(LLMError):
    """Every provider was rate limited or kept failing. Lists what happened at each."""

    def __init__(self, failures: list[ProviderFailure]) -> None:
        self.failures = failures
        details = "\n".join(f"  - {failure}" for failure in failures)
        super().__init__(f"All LLM providers failed:\n{details}")


class InvalidJSONResponseError(LLMError):
    """``chat_json`` got a reply that did not match the schema, even after one retry."""

    def __init__(self, schema_name: str, detail: str) -> None:
        self.schema_name = schema_name
        self.detail = detail
        super().__init__(f"Reply did not match {schema_name} after a retry: {detail}")
