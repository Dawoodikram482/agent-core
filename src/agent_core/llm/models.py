"""Request and response types for the LLM gateway."""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """One message in a conversation."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


MessagesInput = Sequence[ChatMessage | Mapping[str, str]]


def to_messages(messages: MessagesInput) -> list[ChatMessage]:
    """Accept :class:`ChatMessage` objects or plain ``{"role": ..., "content": ...}`` dicts."""
    return [m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m) for m in messages]


class TokenUsage(BaseModel):
    """Tokens used by one call, as reported by the provider (zero when not reported)."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ChatResult(BaseModel):
    """The answer to one chat call.

    Attributes:
        text: The reply text.
        provider: Which provider answered, e.g. ``groq``.
        model: The model that answered, as reported by the provider.
        usage: Token counts.
        latency_ms: Time for the successful request, in milliseconds.
        attempts: Requests made across all providers before this answer, including it.
        finish_reason: Why generation stopped (``stop``, ``length``...), if reported.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    provider: str
    model: str
    usage: TokenUsage
    latency_ms: float = Field(ge=0)
    attempts: int = Field(ge=1)
    finish_reason: str | None = None


class JsonChatResult[T: BaseModel](BaseModel):
    """The answer to a ``chat_json`` call: the validated object plus the raw call details."""

    model_config = ConfigDict(frozen=True)

    data: T
    result: ChatResult
