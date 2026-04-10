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
