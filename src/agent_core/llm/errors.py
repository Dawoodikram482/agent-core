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
