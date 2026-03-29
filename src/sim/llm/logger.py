import json
import time
from pathlib import Path

from loguru import logger

from ..config import settings


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def log_llm_call(
    day: int,
    scene_name: str,
    group_id: int | str,
    call_type: str,
    input_messages: list[dict],
    output: object,
    tokens_prompt: int = 0,
    tokens_completion: int = 0,
    cost_usd: float = 0.0,
    latency_ms: float = 0.0,
    model: str = "",
    temperature: float = 0.0,
) -> None:
    log_dir = settings.logs_dir / f"day_{day:03d}" / scene_name / str(group_id)
    _ensure_dir(log_dir)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{call_type}_{timestamp}.json"

    output_data = output.model_dump() if hasattr(output, "model_dump") else output

    record = {
        "call_type": call_type,
        "model": model or settings.llm_model,
        "temperature": temperature,
        "tokens": {"prompt": tokens_prompt, "completion": tokens_completion},
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "input_messages": input_messages,
        "output": output_data,
    }

    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Append to cost tracker
    cost_line = {
        "day": day,
        "scene": scene_name,
        "call_type": call_type,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "cost_usd": cost_usd,
    }
    costs_file = settings.logs_dir / "costs.jsonl"
    _ensure_dir(costs_file.parent)
    with open(costs_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(cost_line, ensure_ascii=False) + "\n")

    logger.debug(
        f"LLM call: {call_type} | day={day} scene={scene_name} group={group_id} | "
        f"tokens={tokens_prompt}+{tokens_completion} cost=${cost_usd:.4f} latency={latency_ms:.0f}ms"
    )
