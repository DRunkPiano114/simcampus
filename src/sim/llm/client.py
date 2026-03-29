import instructor
import litellm

from ..config import settings

# Suppress litellm debug logs
litellm.suppress_debug_info = True


def get_instructor_client() -> instructor.AsyncInstructor:
    return instructor.from_litellm(
        litellm.acompletion,
        mode=instructor.Mode.JSON,
    )


async def structured_call(
    response_model: type,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> object:
    client = get_instructor_client()
    return await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        response_model=response_model,
        temperature=temperature or settings.creative_temperature,
        max_tokens=max_tokens or settings.max_tokens_per_turn,
        max_retries=settings.max_retries,
    )
