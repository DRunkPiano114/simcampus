"""Claude Code headless mode backend for structured LLM calls.

Spawns `claude -p` as a subprocess with --tools "" (no tool access),
--json-schema for structured output, and --output-format json.
"""

import asyncio
import json
import os

from loguru import logger
from pydantic import BaseModel

from ..config import settings


def _subprocess_env() -> dict[str, str]:
    """Build env for the subprocess, stripping invalid API keys.

    load_dotenv() may inject a placeholder ANTHROPIC_API_KEY (e.g. 'sk-ant-xxx')
    from .env. If --bare is off, we need to remove it so Claude uses OAuth instead.
    """
    env = os.environ.copy()
    if not settings.claude_code_bare:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def _build_cmd(schema_str: str) -> list[str]:
    """Build the claude CLI command with appropriate flags."""
    cmd = [
        "claude",
        "-p",                           # headless / non-interactive
        "--output-format", "json",      # structured JSON output
        "--json-schema", schema_str,    # enforce response schema
        "--tools", "",                  # disable ALL tools
        "--model", settings.claude_code_model,
        "--no-session-persistence",     # don't save session to disk
    ]

    # --bare gives faster startup (no hooks/LSP/plugins) but requires
    # a real ANTHROPIC_API_KEY env var (skips OAuth keychain).
    # Enable via SIM_CLAUDE_CODE_BARE=true in .env.
    if settings.claude_code_bare:
        cmd.append("--bare")

    return cmd


def _extract_result(events: list[dict]) -> dict:
    """Extract the result event from the JSON event array."""
    for event in reversed(events):
        if event.get("type") == "result":
            if event.get("is_error"):
                error_text = event.get("result", "unknown error")
                raise RuntimeError(f"claude-code returned error: {error_text}")
            return event
    raise RuntimeError("claude-code returned no result event")


async def structured_call_claude(
    response_model: type[BaseModel],
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseModel:
    """Call Claude Code headless mode and return a validated Pydantic model."""
    # Combine messages into a single prompt (all callers use a single user msg)
    prompt = "\n\n".join(m["content"] for m in messages)

    # Generate JSON Schema from Pydantic model
    schema = response_model.model_json_schema()
    schema_str = json.dumps(schema, ensure_ascii=False)

    cmd = _build_cmd(schema_str)

    logger.debug(
        f"claude-code call: model={settings.claude_code_model} "
        f"schema={response_model.__name__} bare={'--bare' in cmd}"
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(),
    )

    stdout_bytes, stderr_bytes = await proc.communicate(input=prompt.encode("utf-8"))
    stdout_text = stdout_bytes.decode("utf-8")

    # Non-zero exit: check if stdout has error info before falling back to stderr
    if proc.returncode != 0:
        # Try to parse stdout for structured error
        try:
            events = json.loads(stdout_text)
            result_event = _extract_result(events)  # will raise with error msg
        except (json.JSONDecodeError, RuntimeError):
            pass
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"claude-code exited with code {proc.returncode}: {stderr_text[:500]}"
        )

    # Output is a JSON array of events; find the result event
    try:
        events = json.loads(stdout_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"claude-code returned invalid JSON: {e}\n"
            f"raw output: {stdout_text[:500]}"
        )

    result_event = _extract_result(events)

    # Log usage info
    usage = result_event.get("usage", {})
    cost = result_event.get("total_cost_usd", 0)
    duration = result_event.get("duration_api_ms", 0)
    logger.debug(
        f"claude-code done: cost=${cost:.4f} "
        f"tokens_in={usage.get('input_tokens', 0)}+cache_read={usage.get('cache_read_input_tokens', 0)} "
        f"tokens_out={usage.get('output_tokens', 0)} "
        f"api_ms={duration}"
    )

    # --json-schema puts validated data in "structured_output"
    structured = result_event.get("structured_output")
    if structured is None:
        # Fall back: try to parse the text result as JSON
        result_text = result_event.get("result", "")
        try:
            structured = json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(
                f"claude-code did not return structured output. "
                f"result text: {str(result_text)[:500]}"
            )

    return response_model.model_validate(structured)
