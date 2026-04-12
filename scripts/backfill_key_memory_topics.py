"""Backfill empty topics field on existing KeyMemory records using cheap
keyword classification. Idempotent — only writes records where topics is
empty. NOT an LLM call — bucket coarseness is fine for clustering.

Usage:
    uv run python scripts/backfill_key_memory_topics.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sim.config import settings  # noqa: E402

KEYWORD_RULES = {
    "学业": ["英语", "物理", "数学", "化学", "生物", "作业", "考试",
             "卷子", "复习", "成绩", "排名", "刷题", "笔记", "月考",
             "分数", "学习", "功课"],
    "关系": ["喜欢", "暗恋", "讨厌", "吵架", "约", "告白", "暧昧",
             "陪", "撑", "靠近", "远离", "朋友", "室友"],
    "家庭": ["妈妈", "爸爸", "家里", "家人", "电话", "回家", "父母"],
    "情绪": ["哭", "崩溃", "笑", "兴奋", "孤独", "焦虑", "难过"],
}


def classify_topic(text: str) -> str:
    for topic, keywords in KEYWORD_RULES.items():
        if any(kw in text for kw in keywords):
            return topic
    return "其他"


def main() -> None:
    agents_dir = settings.agents_dir
    if not agents_dir.exists():
        print(f"agents/ directory not found at {agents_dir}")
        return

    total_backfilled = 0
    for agent_dir in sorted(agents_dir.iterdir()):
        km_path = agent_dir / "key_memories.json"
        if not km_path.exists():
            continue

        data = json.loads(km_path.read_text("utf-8"))
        memories = data.get("memories", [])
        changed = 0
        for mem in memories:
            if not mem.get("topics"):
                topic = classify_topic(mem.get("text", ""))
                mem["topics"] = [topic]
                changed += 1

        if changed:
            km_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  {agent_dir.name}: backfilled {changed} memories")
            total_backfilled += changed

    print(f"\nDone. Backfilled {total_backfilled} total memories.")


if __name__ == "__main__":
    main()
