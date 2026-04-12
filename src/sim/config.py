from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = {"env_prefix": "SIM_"}

    # Paths
    project_root: Path = Path(".")
    data_dir: Path = Path("data")
    agents_dir: Path = Path("agents")
    world_dir: Path = Path("world")
    logs_dir: Path = Path("logs")

    # LLM
    llm_model: str = "deepseek/deepseek-chat"
    llm_fallback_model: str = "openrouter/google/gemini-3-flash-preview"
    creative_temperature: float = 0.9
    analytical_temperature: float = 0.3
    plan_temperature: float = 0.7
    compression_temperature: float = 0.5
    max_tokens_per_turn: int = 32000
    max_tokens_scene_end: int = 32000
    max_tokens_daily_plan: int = 32000
    max_tokens_compression: int = 32000
    max_tokens_solo: int = 32000
    max_retries: int = 3

    # PDA tick loop
    min_ticks_before_termination: int = 3
    consecutive_quiet_to_end: int = 4
    perception_temperature: float = 0.9
    max_tokens_perception: int = 32000

    # Simulation
    exam_interval_days: int = 30
    event_expire_days: int = 3
    recent_md_max_weeks: int = 4
    max_key_memories: int = 10
    solo_energy_threshold: int = 20  # Fix 18: lowered from 25

    # key_memories write controls
    key_memory_write_threshold: int = 3       # min importance to write
    per_day_memory_cap: int = 2               # post-pass cap on today's memories

    # Self-narrative
    self_narrative_interval_days: int = 3
    self_narrative_temperature: float = 0.7
    max_tokens_self_narrative: int = 32000

    # Re-planning
    replan_temperature: float = 0.7
    max_tokens_replan: int = 32000

    # Self-reflection (post-scene per-agent)
    reflection_temperature: float = 0.7
    max_tokens_reflection: int = 32000
    max_tokens_narrative: int = 32000

    # Concerns
    max_active_concerns: int = 4
    concern_decay_per_day: int = 2            # intensity drop per end-of-day
    concern_stale_days: int = 5               # days without reinforcement → evict
    concern_autogen_max_intensity: int = 6    # cap for reflection-generated concerns

    # Ambient events (Fix 12)
    ambient_event_probability: float = 0.3
    ambient_events_file: Path = Path("data/scene_ambient_events.json")

    # Consolidation (Fix 15)
    consolidation_interval_days: int = 3
    consolidation_lookback_days: int = 7
    consolidation_temperature: float = 0.3
    max_tokens_consolidation: int = 4000

    # Relationships
    max_recent_interactions: int = 10         # per-relationship recent interaction log cap

    # Concurrency
    max_concurrent_llm_calls: int = 5


settings = Settings()
