"""Initialize the simulation world: create agent folders and world state files."""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS_DIR = ROOT / "data" / "characters"
AGENTS_DIR = ROOT / "agents"
WORLD_DIR = ROOT / "world"
LOGS_DIR = ROOT / "logs"

# Preset relationships (Day 1)
# Format: (agent_a, agent_b, label, a_fav, b_fav, a_trust, b_trust)
PRESET_RELATIONSHIPS = [
    ("lin_zhaoyu", "tang_shihan", "同桌", 10, 5, 5, 5),
    ("lin_zhaoyu", "jiang_haotian", "前后桌", 5, 10, 0, 5),
    ("lin_zhaoyu", "lu_siyuan", "室友", 15, 15, 10, 10),
    ("lin_zhaoyu", "shen_yifan", "室友", 10, 10, 5, 5),
    ("jiang_haotian", "lu_siyuan", "室友", 5, 5, 5, 5),
    ("jiang_haotian", "shen_yifan", "室友", -5, 0, 0, 0),
    ("cheng_yutong", "su_nianyao", "同桌", 5, 10, 5, 5),
    ("su_nianyao", "fang_yuchen", "前后桌", 20, 20, 15, 15),
    ("tang_shihan", "fang_yuchen", "室友", 15, 15, 10, 10),
    ("tang_shihan", "cheng_yutong", "室友", 5, 5, 5, 5),
    ("tang_shihan", "su_nianyao", "室友", 10, 10, 5, 5),
]


def load_character_names() -> dict[str, str]:
    """Load agent_id -> name mapping from character files."""
    names = {}
    for f in CHARACTERS_DIR.glob("*.json"):
        data = json.loads(f.read_text("utf-8"))
        names[data["agent_id"]] = data["name"]
    return names


def build_relationships(names: dict[str, str]) -> dict[str, dict]:
    """Build relationship files for all agents from presets."""
    rels: dict[str, dict] = {aid: {} for aid in names}

    for a, b, label, a_fav, b_fav, a_trust, b_trust in PRESET_RELATIONSHIPS:
        rels[a][b] = {
            "target_name": names[b],
            "target_id": b,
            "favorability": a_fav,
            "trust": a_trust,
            "understanding": 10,
            "label": label,
            "recent_interactions": [],
        }
        rels[b][a] = {
            "target_name": names[a],
            "target_id": a,
            "favorability": b_fav,
            "trust": b_trust,
            "understanding": 10,
            "label": label,
            "recent_interactions": [],
        }

    return rels


def init_agent(char_file: Path, rels: dict[str, dict]) -> None:
    """Initialize one agent's folder with profile, state, relationships, memories."""
    data = json.loads(char_file.read_text("utf-8"))
    agent_id = data["agent_id"]
    agent_dir = AGENTS_DIR / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Profile (immutable during simulation)
    (agent_dir / "profile.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Initial state
    pressure = {"高": 60, "中": 35, "低": 15}.get(
        data["family_background"]["pressure_level"], 30
    )
    state = {
        "emotion": "neutral",
        "energy": 85,
        "academic_pressure": pressure,
        "location": "教室",
        "daily_plan": {"intentions": [], "mood_forecast": "neutral"},
        "day": 1,
        "active_concerns": [],
    }
    (agent_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Empty self-narrative
    (agent_dir / "self_narrative.md").write_text("", encoding="utf-8")

    # Relationships
    rel_data = {"relationships": rels.get(agent_id, {})}
    (agent_dir / "relationships.json").write_text(
        json.dumps(rel_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Empty memories and today/recent
    (agent_dir / "key_memories.json").write_text(
        json.dumps({"memories": []}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (agent_dir / "today.md").write_text("", encoding="utf-8")
    (agent_dir / "recent.md").write_text("", encoding="utf-8")


def init_world() -> None:
    """Initialize world state files."""
    WORLD_DIR.mkdir(parents=True, exist_ok=True)
    (WORLD_DIR / "exam_results").mkdir(parents=True, exist_ok=True)

    progress = {
        "current_day": 1,
        "current_date": "2025-09-01",
        "day_phase": "daily_plan",
        "current_scene_index": 0,
        "scenes": [],
        "next_exam_in_days": 30,
        "total_days_simulated": 0,
        "last_updated": "",
    }
    (WORLD_DIR / "progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    event_queue = {"events": [], "next_id": 1}
    (WORLD_DIR / "event_queue.json").write_text(
        json.dumps(event_queue, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    # Clean previous state
    if AGENTS_DIR.exists():
        shutil.rmtree(AGENTS_DIR)
    if WORLD_DIR.exists():
        shutil.rmtree(WORLD_DIR)
    if LOGS_DIR.exists():
        shutil.rmtree(LOGS_DIR)

    names = load_character_names()
    rels = build_relationships(names)

    for char_file in sorted(CHARACTERS_DIR.glob("*.json")):
        init_agent(char_file, rels)
        agent_id = json.loads(char_file.read_text("utf-8"))["agent_id"]
        print(f"  Initialized agent: {agent_id}")

    init_world()
    print(f"\nDone! {len(names)} agents initialized, world state created.")


if __name__ == "__main__":
    main()
