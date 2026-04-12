"""One-shot LLM generation of behavioral_anchors for each character.

Reads each data/characters/*.json, builds a prompt from personality +
speaking_style + backstory + inner_conflicts, calls the LLM, writes back
the behavioral_anchors field. Idempotent: re-running overwrites.

Usage:
    uv run python scripts/generate_behavioral_anchors.py [--dry-run]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sim.config import settings  # noqa: E402
from sim.llm.client import structured_call  # noqa: E402
from sim.models.agent import BehavioralAnchors  # noqa: E402

PROMPT_TEMPLATE = """\
你是一个高中生活模拟器的角色设计师。根据以下角色信息，提炼出这个角色的行为锚点。

## 角色信息
姓名：{name}
性格：{personality}
说话风格：{speaking_style}
背景：{backstory}
内心矛盾：{inner_conflicts}

## 要求

请输出三组锚点：

1. **must_do**（3-5条）：这个角色在任何场景下都会自然做的事。
   - 必须是具体行为，不是性格形容词。
   - 例："上自习时即使有人聊天也会戴耳塞"，不要写"他很内向"

2. **never_do**（3-5条）：这个角色绝不会做的事，即使被激怒也不会。
   - 必须是具体行为。
   - 例："绝不主动告状"、"绝不让别人看到自己哭"

3. **speech_patterns**（1-3条）：标志性话风，可复用的具体片段。
   - 必须是可直接引用的表达片段，不是描述。
   - 例："句尾常加'呗'"、"被夸时会反讽自己"，不要写"说话很文艺"

**重要**：每条锚点必须能追溯到上面的背景/性格/内心矛盾，不要凭空编造。
"""


async def generate_for_character(char_path: Path, dry_run: bool) -> None:
    data = json.loads(char_path.read_text(encoding="utf-8"))
    name = data["name"]

    prompt = PROMPT_TEMPLATE.format(
        name=name,
        personality="、".join(data.get("personality", [])),
        speaking_style=data.get("speaking_style", ""),
        backstory=data.get("backstory", ""),
        inner_conflicts="；".join(data.get("inner_conflicts", [])),
    )

    messages = [{"role": "user", "content": prompt}]
    llm_result = await structured_call(
        BehavioralAnchors,
        messages,
        temperature=settings.analytical_temperature,
        max_tokens=2000,
    )
    anchors = llm_result.data

    print(f"\n{'='*60}")
    print(f"  {name} ({char_path.name})")
    print(f"{'='*60}")
    print(f"  must_do:  {anchors.must_do}")
    print(f"  never_do: {anchors.never_do}")
    print(f"  speech:   {anchors.speech_patterns}")

    if not dry_run:
        data["behavioral_anchors"] = anchors.model_dump()
        char_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  -> Written to {char_path.name}")
    else:
        print("  -> (dry-run, not written)")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate behavioral anchors")
    parser.add_argument("--dry-run", action="store_true", help="Print only, don't write")
    args = parser.parse_args()

    char_dir = settings.data_dir / "characters"
    char_files = sorted(char_dir.glob("*.json"))
    if not char_files:
        print(f"No character files found in {char_dir}")
        return

    print(f"Found {len(char_files)} characters. Generating anchors...")
    for cf in char_files:
        await generate_for_character(cf, args.dry_run)

    print("\nDone. Please review all character files before proceeding.")


if __name__ == "__main__":
    asyncio.run(main())
