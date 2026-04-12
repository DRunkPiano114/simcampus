"""Catalyst event checker — fires conditional events based on agent state."""

from __future__ import annotations

import json
import random
from pathlib import Path

from loguru import logger

from ..config import settings
from ..models.agent import AgentProfile, AgentState, Role
from ..models.relationship import RelationshipFile
from .event_queue import EventQueueManager


class CatalystChecker:
    """Check triggers once per day and inject matching events into EventQueue."""

    def __init__(self, catalyst_file: Path, rng: random.Random):
        self.catalysts = json.loads(catalyst_file.read_text("utf-8"))["catalyst_events"]
        self.rng = rng
        self.cooldown_state: dict[str, int] = self._load_cooldown_state()

    def check_and_inject(
        self,
        day: int,
        agents: dict[str, tuple[AgentProfile, AgentState]],
        relationships: dict[str, RelationshipFile],
        event_manager: EventQueueManager,
    ) -> list[str]:
        """Check triggers and inject matching events. Returns fired event texts."""
        fired: list[str] = []
        for catalyst in self.catalysts:
            matched = self._check_trigger(catalyst, day, agents, relationships)
            if not matched:
                continue
            cooldown_key = self._cooldown_key(catalyst, matched)
            if self._on_cooldown(cooldown_key, catalyst["cooldown_days"], day):
                continue
            event_text = self._fill_template(catalyst, matched)
            event_manager.add_event(
                text=event_text,
                category="catalyst",
                source_scene="catalyst",
                source_day=day,
                witnesses=matched.get("witnesses", []),
                spread_probability=0.7,
            )
            self.cooldown_state[cooldown_key] = day
            fired.append(event_text)
        self._save_cooldown_state()
        return fired

    # -- Cooldown management --

    def _cooldown_key(self, catalyst: dict, matched: dict) -> str:
        base = f"{catalyst['trigger_type']}:{json.dumps(catalyst['trigger_params'], sort_keys=True, ensure_ascii=False)}"
        if catalyst.get("cooldown_scope") == "per_pair":
            pair = ":".join(sorted(matched.get("witnesses", [])))
            return f"{base}:{pair}"
        return base

    def _on_cooldown(self, key: str, cooldown_days: int, today: int) -> bool:
        last_fired = self.cooldown_state.get(key, -999)
        return (today - last_fired) < cooldown_days

    def _load_cooldown_state(self) -> dict[str, int]:
        path = settings.world_dir / "catalyst_cooldowns.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
        return {}

    def _save_cooldown_state(self) -> None:
        path = settings.world_dir / "catalyst_cooldowns.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.cooldown_state, ensure_ascii=False, indent=2), "utf-8",
        )

    # -- Trigger checking --

    def _check_trigger(
        self,
        catalyst: dict,
        day: int,
        agents: dict[str, tuple[AgentProfile, AgentState]],
        relationships: dict[str, RelationshipFile],
    ) -> dict | None:
        trigger_type = catalyst["trigger_type"]
        params = catalyst["trigger_params"]

        if trigger_type == "concern_stalled":
            for aid, (profile, state) in agents.items():
                if profile.role != Role.STUDENT:
                    continue
                needs_related = any("{related_person}" in t for t in catalyst["templates"])
                for c in state.active_concerns:
                    if c.topic == params["topic"]:
                        if needs_related and not c.related_people:
                            continue
                        stale_days = day - c.last_reinforced_day
                        if stale_days >= params["min_stale_days"]:
                            result = {
                                "agent": profile.name,
                                "agent_id": aid,
                                "witnesses": [aid],
                            }
                            if c.related_people:
                                result["related_person"] = c.related_people[0]
                            return result

        elif trigger_type == "isolation":
            for aid, (profile, state) in agents.items():
                if profile.role != Role.STUDENT:
                    continue
                rels = relationships.get(aid)
                if not rels:
                    continue
                active_rels = sum(
                    1 for rel in rels.relationships.values()
                    if rel.days_since_interaction <= 3
                )
                if active_rels <= params["max_active_relationships"]:
                    return {
                        "agent": profile.name,
                        "agent_id": aid,
                        "witnesses": [aid],
                    }

        elif trigger_type == "relationship_threshold":
            for aid, (profile_a, _) in agents.items():
                if profile_a.role != Role.STUDENT:
                    continue
                rels = relationships.get(aid)
                if not rels:
                    continue
                for rel in rels.relationships.values():
                    if rel.favorability >= params["favorability_gte"]:
                        other_id = rel.target_id
                        other = agents.get(other_id)
                        if other and other[0].role == Role.STUDENT:
                            return {
                                "agent_a": profile_a.name,
                                "agent_b": other[0].name,
                                "witnesses": [aid, other_id],
                            }

        elif trigger_type == "intention_stalled":
            for aid, (profile, state) in agents.items():
                if profile.role != Role.STUDENT:
                    continue
                for intent in state.daily_plan.intentions:
                    if not intent.fulfilled and not intent.abandoned:
                        if intent.pursued_days >= params["min_pursued_days"]:
                            return {
                                "agent": profile.name,
                                "agent_id": aid,
                                "witnesses": [aid],
                            }

        return None

    def _fill_template(self, catalyst: dict, matched: dict) -> str:
        template = self.rng.choice(catalyst["templates"])
        return template.format(**{
            k: v for k, v in matched.items()
            if k not in ("witnesses", "agent_id")
        })
