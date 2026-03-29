from pathlib import Path

from pydantic_settings import BaseSettings


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
    creative_temperature: float = 0.9
    analytical_temperature: float = 0.3
    plan_temperature: float = 0.7
    compression_temperature: float = 0.5
    max_tokens_per_turn: int = 800
    max_tokens_scene_end: int = 1500
    max_tokens_daily_plan: int = 500
    max_tokens_compression: int = 800
    max_tokens_solo: int = 300
    max_retries: int = 3

    # Simulation
    exam_interval_days: int = 30
    event_expire_days: int = 3
    recent_md_max_weeks: int = 4
    max_key_memories: int = 10
    solo_energy_threshold: int = 25

    # Concurrency
    max_concurrent_llm_calls: int = 5


settings = Settings()
