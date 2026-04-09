from collections.abc import AsyncGenerator
from dataclasses import dataclass

import instructor
import litellm

from ..config import settings

# Suppress litellm debug logs
litellm.suppress_debug_info = True
# Drop params unsupported by some providers (e.g. volcengine + response_format)
litellm.drop_params = True


@dataclass
class LLMResult:
    data: object
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost_usd: float = 0.0


def get_instructor_client() -> instructor.AsyncInstructor:
    return instructor.from_litellm(
        litellm.acompletion,
        mode=instructor.Mode.MD_JSON,
    )


async def _do_structured_call(
    model: str,
    response_model: type,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    max_retries: int,
) -> LLMResult:
    client = get_instructor_client()
    result, completion = await client.chat.completions.create_with_completion(
        model=model,
        messages=messages,
        response_model=response_model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
    )

    usage = getattr(completion, "usage", None)
    tokens_prompt = getattr(usage, "prompt_tokens", 0) or 0
    tokens_completion = getattr(usage, "completion_tokens", 0) or 0

    try:
        cost = litellm.completion_cost(
            completion_response=completion,
            model=model,
        )
    except Exception:
        cost = 0.0

    return LLMResult(
        data=result,
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        cost_usd=cost,
    )


async def structured_call(
    response_model: type,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    temp = temperature if temperature is not None else settings.creative_temperature
    tokens = max_tokens if max_tokens is not None else settings.max_tokens_per_turn

    try:
        return await _do_structured_call(
            settings.llm_model, response_model, messages,
            temp, tokens, settings.max_retries,
        )
    except Exception as exc:
        if not settings.llm_fallback_model or settings.llm_fallback_model == settings.llm_model:
            raise
        from loguru import logger
        logger.warning(
            f"structured_call failed with {settings.llm_model}, "
            f"falling back to {settings.llm_fallback_model}: {exc!r}"
        )
        return await _do_structured_call(
            settings.llm_fallback_model, response_model, messages,
            temp, tokens, settings.max_retries,
        )


async def streaming_text_call(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    """Stream raw text tokens (no structured output). For God Mode chat."""
    response = await litellm.acompletion(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature if temperature is not None else settings.creative_temperature,
        max_tokens=max_tokens if max_tokens is not None else 1024,
        stream=True,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
