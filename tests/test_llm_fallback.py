"""Test: structured_call falls back to llm_fallback_model on primary model failure."""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field

from sim.llm.client import structured_call, LLMResult, _do_structured_call


class DummyOutput(BaseModel):
    value: int = Field(ge=1, le=10)


def _fake_llm_result():
    return LLMResult(
        data=DummyOutput(value=5),
        tokens_prompt=10,
        tokens_completion=5,
        cost_usd=0.001,
    )


def test_fallback_triggered_on_primary_failure():
    """When primary model raises, fallback model is called."""
    primary_called = False
    fallback_called = False

    async def mock_do_call(model, response_model, messages, temp, tokens, retries):
        nonlocal primary_called, fallback_called
        if model == "deepseek/deepseek-chat":
            primary_called = True
            raise Exception("structured output validation failed")
        elif model == "openrouter/google/gemini-3-flash-preview":
            fallback_called = True
            return _fake_llm_result()
        raise AssertionError(f"unexpected model: {model}")

    with patch("sim.llm.client._do_structured_call", side_effect=mock_do_call):
        with patch("sim.llm.client.settings") as mock_settings:
            mock_settings.llm_model = "deepseek/deepseek-chat"
            mock_settings.llm_fallback_model = "openrouter/google/gemini-3-flash-preview"
            mock_settings.creative_temperature = 0.9
            mock_settings.max_tokens_per_turn = 32000
            mock_settings.max_retries = 3

            result = asyncio.run(structured_call(DummyOutput, [{"role": "user", "content": "test"}]))

    assert primary_called
    assert fallback_called
    assert result.data.value == 5


def test_no_fallback_when_primary_succeeds():
    """When primary model succeeds, fallback is never called."""
    models_called = []

    async def mock_do_call(model, response_model, messages, temp, tokens, retries):
        models_called.append(model)
        return _fake_llm_result()

    with patch("sim.llm.client._do_structured_call", side_effect=mock_do_call):
        with patch("sim.llm.client.settings") as mock_settings:
            mock_settings.llm_model = "deepseek/deepseek-chat"
            mock_settings.llm_fallback_model = "openrouter/google/gemini-3-flash-preview"
            mock_settings.creative_temperature = 0.9
            mock_settings.max_tokens_per_turn = 32000
            mock_settings.max_retries = 3

            result = asyncio.run(structured_call(DummyOutput, [{"role": "user", "content": "test"}]))

    assert models_called == ["deepseek/deepseek-chat"]
    assert result.data.value == 5


def test_no_fallback_when_same_model():
    """When fallback model is the same as primary, exception propagates."""
    async def mock_do_call(model, response_model, messages, temp, tokens, retries):
        raise Exception("validation failed")

    with patch("sim.llm.client._do_structured_call", side_effect=mock_do_call):
        with patch("sim.llm.client.settings") as mock_settings:
            mock_settings.llm_model = "deepseek/deepseek-chat"
            mock_settings.llm_fallback_model = "deepseek/deepseek-chat"
            mock_settings.creative_temperature = 0.9
            mock_settings.max_tokens_per_turn = 32000
            mock_settings.max_retries = 3

            with pytest.raises(Exception, match="validation failed"):
                asyncio.run(structured_call(DummyOutput, [{"role": "user", "content": "test"}]))


def test_no_fallback_when_fallback_empty():
    """When fallback model is empty string, exception propagates."""
    async def mock_do_call(model, response_model, messages, temp, tokens, retries):
        raise Exception("validation failed")

    with patch("sim.llm.client._do_structured_call", side_effect=mock_do_call):
        with patch("sim.llm.client.settings") as mock_settings:
            mock_settings.llm_model = "deepseek/deepseek-chat"
            mock_settings.llm_fallback_model = ""
            mock_settings.creative_temperature = 0.9
            mock_settings.max_tokens_per_turn = 32000
            mock_settings.max_retries = 3

            with pytest.raises(Exception, match="validation failed"):
                asyncio.run(structured_call(DummyOutput, [{"role": "user", "content": "test"}]))
