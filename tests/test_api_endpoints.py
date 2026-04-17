"""Tests for API request/response models and endpoint shapes."""

import pytest
from pydantic import ValidationError

from sim.api.models import AgentReaction, AgentReactionLLM, ChatMessage, ChatRequest, RolePlayRequest


class TestChatModels:
    """Test Pydantic models for chat API."""

    def test_chat_request_valid(self):
        req = ChatRequest(
            agent_id="lin_zhaoyu",
            day=1,
            time_period="08:45",
            message="你在想什么？",
        )
        assert req.agent_id == "lin_zhaoyu"
        assert req.history == []

    def test_chat_request_with_history(self):
        req = ChatRequest(
            agent_id="lin_zhaoyu",
            day=1,
            time_period="08:45",
            message="继续说",
            history=[
                ChatMessage(role="user", content="你好"),
                ChatMessage(role="assistant", content="嗯"),
            ],
        )
        assert len(req.history) == 2

    def test_role_play_request_valid(self):
        req = RolePlayRequest(
            user_agent_id="lin_zhaoyu",
            target_agent_ids=["lu_siyuan", "fang_yuchen"],
            day=1,
            time_period="12:00",
            message="午饭吃什么？",
        )
        assert len(req.target_agent_ids) == 2

    def test_role_play_request_min_targets(self):
        """Must have at least 1 target."""
        with pytest.raises(ValidationError):
            RolePlayRequest(
                user_agent_id="lin_zhaoyu",
                target_agent_ids=[],
                day=1,
                time_period="12:00",
                message="test",
            )

    def test_role_play_request_max_targets(self):
        """Cannot have more than 4 targets."""
        with pytest.raises(ValidationError):
            RolePlayRequest(
                user_agent_id="lin_zhaoyu",
                target_agent_ids=["a", "b", "c", "d", "e"],
                day=1,
                time_period="12:00",
                message="test",
            )

    def test_agent_reaction_model(self):
        reaction = AgentReaction(
            agent_id="lu_siyuan",
            agent_name="陆思远",
            action="speak",
            content="好啊，去食堂",
            inner_thought="今天想吃点好的",
            emotion="happy",
        )
        assert reaction.action == "speak"
        assert reaction.target is None

    def test_agent_reaction_with_target(self):
        reaction = AgentReaction(
            agent_id="tang_shihan",
            agent_name="唐诗涵",
            action="speak",
            target="su_nianyao",
            content="你看到了吗",
            inner_thought="她应该知道",
            emotion="curious",
        )
        assert reaction.target == "su_nianyao"

    def test_agent_reaction_silence(self):
        reaction = AgentReaction(
            agent_id="he_jiajun",
            agent_name="何家骏",
            action="silence",
            content="",
            inner_thought="跟我没关系",
            emotion="neutral",
        )
        assert reaction.action == "silence"

    def test_agent_reaction_rejects_invalid_action(self):
        """Literal type rejects hallucinated action values."""
        with pytest.raises(ValidationError):
            AgentReaction(
                agent_id="test",
                agent_name="测试",
                action="talk",  # invalid — not in Literal
                content="hello",
                inner_thought="thinking",
                emotion="neutral",
            )

    def test_agent_reaction_llm_model(self):
        """AgentReactionLLM excludes agent_id/agent_name."""
        llm_out = AgentReactionLLM(
            action="speak",
            content="好啊",
            inner_thought="可以",
            emotion="happy",
        )
        assert llm_out.action == "speak"
        assert "agent_id" not in AgentReactionLLM.model_fields

    def test_agent_reaction_llm_rejects_invalid_action(self):
        """AgentReactionLLM also enforces Literal action."""
        with pytest.raises(ValidationError):
            AgentReactionLLM(
                action="respond",
                content="test",
                inner_thought="test",
                emotion="neutral",
            )

    def test_agent_reaction_from_llm_output(self):
        """Construct AgentReaction from AgentReactionLLM + known data."""
        llm_out = AgentReactionLLM(
            action="speak",
            target="someone",
            content="你看",
            inner_thought="有意思",
            emotion="curious",
        )
        reaction = AgentReaction(
            agent_id="lu_siyuan",
            agent_name="陆思远",
            **llm_out.model_dump(),
        )
        assert reaction.agent_id == "lu_siyuan"
        assert reaction.action == "speak"
        assert reaction.content == "你看"


class TestOrchestratorSnapshots:
    """Test that orchestrator snapshot methods work correctly."""

    def test_daily_snapshot_files_constant(self):
        """Verify the snapshot files list is correct."""
        from sim.interaction.orchestrator import Orchestrator
        assert "state.json" in Orchestrator.DAILY_SNAPSHOT_FILES
        assert "relationships.json" in Orchestrator.DAILY_SNAPSHOT_FILES
        assert "self_narrative.json" in Orchestrator.DAILY_SNAPSHOT_FILES


class TestResolveSceneGroupIndex:
    """Scene card should share the viewer's current group, not always the
    server's featured pick."""

    @staticmethod
    def _scene(groups: list[dict]) -> dict:
        return {
            "scene": {"day": 1, "time": "07:00", "name": "早读", "location": "教室"},
            "groups": groups,
        }

    @staticmethod
    def _mind(urgency: int = 0, thought: str = "") -> dict:
        return {
            "observation": "",
            "inner_thought": thought,
            "emotion": "neutral",
            "action_type": "observe",
            "action_content": None,
            "action_target": None,
            "urgency": urgency,
            "is_disruptive": False,
        }

    def _multi_group(self, participants: list[str], urgency: int = 2) -> dict:
        return {
            "is_solo": False,
            "participants": participants,
            "ticks": [
                {
                    "tick": 0,
                    "public": {
                        "speech": {
                            "agent": participants[0],
                            "target": participants[1],
                            "content": "嗨",
                        },
                        "actions": [],
                        "environmental_event": None,
                        "exits": [],
                    },
                    "minds": {aid: self._mind(urgency, "想点事") for aid in participants},
                }
            ],
        }

    def _solo_group(self, aid: str) -> dict:
        return {
            "is_solo": True,
            "participants": [aid],
            "solo_reflection": {
                "inner_thought": "一个人",
                "emotion": "neutral",
                "activity": None,
            },
            "ticks": [],
        }

    def test_caller_group_is_honored(self):
        from sim.api.server import _resolve_scene_group_index

        # Group 0 has the higher drama score, but caller pinned group 1 —
        # returning the caller's choice is the whole point.
        scene = self._scene([
            self._multi_group(["a", "b"], urgency=9),
            self._multi_group(["c", "d"], urgency=1),
        ])
        assert _resolve_scene_group_index(scene, 1) == 1

    def test_no_caller_falls_back_to_featured(self):
        from sim.api.server import _resolve_scene_group_index

        scene = self._scene([
            self._multi_group(["a", "b"], urgency=1),
            self._multi_group(["c", "d"], urgency=9),
        ])
        assert _resolve_scene_group_index(scene, None) == 1

    def test_out_of_range_raises_404(self):
        from fastapi import HTTPException
        from sim.api.server import _resolve_scene_group_index

        scene = self._scene([self._multi_group(["a", "b"])])
        with pytest.raises(HTTPException) as exc:
            _resolve_scene_group_index(scene, 5)
        assert exc.value.status_code == 404

    def test_solo_group_raises_404(self):
        from fastapi import HTTPException
        from sim.api.server import _resolve_scene_group_index

        scene = self._scene([self._solo_group("a"), self._multi_group(["b", "c"])])
        with pytest.raises(HTTPException) as exc:
            _resolve_scene_group_index(scene, 0)
        assert exc.value.status_code == 404

    def test_no_multi_agent_group_and_no_caller_raises_404(self):
        from fastapi import HTTPException
        from sim.api.server import _resolve_scene_group_index

        scene = self._scene([self._solo_group("a")])
        with pytest.raises(HTTPException) as exc:
            _resolve_scene_group_index(scene, None)
        assert exc.value.status_code == 404
