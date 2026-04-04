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
    llm_backend: str = "litellm"  # "litellm" or "claude_code"
    llm_model: str = "deepseek/deepseek-chat"
    claude_code_model: str = "claude-sonnet-4-6"  # model for claude-code backend
    claude_code_bare: bool = False  # --bare mode (needs real ANTHROPIC_API_KEY)
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
    max_ticks_per_scene: int = 30
    min_ticks_before_termination: int = 3
    consecutive_observe_to_end: int = 3
    perception_temperature: float = 0.9
    max_tokens_perception: int = 32000

    # Simulation
    exam_interval_days: int = 30
    event_expire_days: int = 3
    recent_md_max_weeks: int = 4
    max_key_memories: int = 10
    solo_energy_threshold: int = 25

    # Concurrency
    max_concurrent_llm_calls: int = 5


settings = Settings()
