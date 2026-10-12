"""Manual smoke test: call each configured provider for real, using your .env.

Run from the repo root:

    uv run python examples/smoke.py

It checks every provider in LLM_PROVIDERS that has an API key on its own (so a wrong
key or model name shows up per provider), then runs one chat_json call through the
normal fallback chain. It uses a few hundred tokens of free-tier quota. CI never runs it.
"""

import asyncio
import sys

from pydantic import BaseModel

from agent_core import configure_logging, load_settings
from agent_core.llm import LLMError, LLMGateway, LLMSettings


class Answer(BaseModel):
    """Expected shape of the structured reply."""

    country: str
    capital: str


async def check_provider(settings: LLMSettings, name: str) -> bool:
    configs = [c for c in settings.provider_configs() if c.name == name]
    async with LLMGateway(configs, timeout_seconds=settings.llm_timeout_seconds) as llm:
        try:
            result = await llm.chat(
                [{"role": "user", "content": "Reply with exactly: pit wall online"}],
                max_tokens=20,
                temperature=0,
            )
        except LLMError as exc:
            print(f"  FAIL {name}: {exc}")
            return False
    print(
        f"  OK   {name}: model={result.model} tokens={result.usage.total_tokens} "
        f"latency={result.latency_ms:.0f} ms reply={result.text.strip()!r}"
    )
    return True


async def main() -> int:
    settings = load_settings(LLMSettings, log_format="console", log_level="WARNING")
    configure_logging(settings)
    names = [c.name for c in settings.provider_configs()]
    if not names:
        print("No provider has an API key. Set GROQ_API_KEY and/or GEMINI_API_KEY in .env.")
        return 1

    print(f"Providers with keys, in fallback order: {', '.join(names)}")
    results = [await check_provider(settings, name) for name in names]

    print("Structured reply through the fallback chain:")
    async with LLMGateway.from_settings(settings) as llm:
        try:
            reply = await llm.chat_json(
                [{"role": "user", "content": "The capital of the Netherlands?"}], Answer
            )
        except LLMError as exc:
            print(f"  FAIL chat_json: {exc}")
            return 1
    print(f"  OK   {reply.result.provider}: {reply.data.model_dump()}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
