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
    solo_energy_threshold: int = 25

    # Location agency
    free_period_locations: list[str] = ["教室", "走廊", "操场", "小卖部", "图书馆", "天台"]
    lunch_locations: list[str] = ["食堂", "教室", "操场", "小卖部"]

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

    # Concurrency
    max_concurrent_llm_calls: int = 5


settings = Settings()
