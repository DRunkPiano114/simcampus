import json
import os
import tempfile
from pathlib import Path

from ..config import settings
from ..models.agent import AgentProfile, AgentState
from ..models.event import EventQueue
from ..models.memory import KeyMemory, KeyMemoryFile
from ..models.progress import Progress
from ..models.relationship import RelationshipFile


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class AgentStorage:
    def __init__(self, agent_id: str, base_dir: Path | None = None):
        self.agent_id = agent_id
        self.dir = (base_dir or settings.agents_dir) / agent_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def _json_path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def _md_path(self, name: str) -> Path:
        return self.dir / f"{name}.md"

    # Profile
    def load_profile(self) -> AgentProfile:
        return AgentProfile.model_validate_json(self._json_path("profile").read_text("utf-8"))

    def save_profile(self, profile: AgentProfile) -> None:
        atomic_write_json(self._json_path("profile"), profile.model_dump())

    # State
    def load_state(self) -> AgentState:
        return AgentState.model_validate_json(self._json_path("state").read_text("utf-8"))

    def save_state(self, state: AgentState) -> None:
        atomic_write_json(self._json_path("state"), state.model_dump())

    # Relationships
    def load_relationships(self) -> RelationshipFile:
        path = self._json_path("relationships")
        if not path.exists():
            return RelationshipFile()
        return RelationshipFile.model_validate_json(path.read_text("utf-8"))

    def save_relationships(self, rels: RelationshipFile) -> None:
        atomic_write_json(self._json_path("relationships"), rels.model_dump())

    # Key Memories
    def load_key_memories(self) -> KeyMemoryFile:
        path = self._json_path("key_memories")
        if not path.exists():
            return KeyMemoryFile()
        return KeyMemoryFile.model_validate_json(path.read_text("utf-8"))

    def append_key_memory(self, memory: KeyMemory) -> None:
        km = self.load_key_memories()
        km.memories.append(memory)
        atomic_write_json(self._json_path("key_memories"), km.model_dump())

    # Today markdown
    def read_today_md(self) -> str:
        path = self._md_path("today")
        return path.read_text("utf-8") if path.exists() else ""

    def append_today_md(self, content: str) -> None:
        path = self._md_path("today")
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    def clear_today_md(self) -> None:
        path = self._md_path("today")
        path.write_text("", encoding="utf-8")

    # Recent markdown
    def read_recent_md(self) -> str:
        path = self._md_path("recent")
        return path.read_text("utf-8") if path.exists() else ""

    def write_recent_md(self, content: str) -> None:
        path = self._md_path("recent")
        path.write_text(content, encoding="utf-8")

    def read_recent_md_last_n_days(self, n: int) -> str:
        content = self.read_recent_md()
        if not content:
            return ""
        sections = content.split("\n# Day ")
        recent = sections[-n:] if len(sections) > n else sections
        if recent and not recent[0].startswith("# Day "):
            recent[0] = recent[0]
        else:
            recent = ["# Day " + s for s in recent]
        return "\n".join(recent)


class WorldStorage:
    def __init__(self, agents_dir: Path | None = None, world_dir: Path | None = None):
        self.agents_dir = agents_dir or settings.agents_dir
        self.world_dir = world_dir or settings.world_dir
        self.world_dir.mkdir(parents=True, exist_ok=True)
        self.agents: dict[str, AgentStorage] = {}

    def load_all_agents(self) -> None:
        self.agents = {}
        if not self.agents_dir.exists():
            return
        for d in sorted(self.agents_dir.iterdir()):
            if d.is_dir() and (d / "profile.json").exists():
                self.agents[d.name] = AgentStorage(d.name, self.agents_dir)

    def get_agent(self, agent_id: str) -> AgentStorage:
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentStorage(agent_id, self.agents_dir)
        return self.agents[agent_id]

    def load_progress(self) -> Progress:
        path = self.world_dir / "progress.json"
        if not path.exists():
            return Progress()
        return Progress.model_validate_json(path.read_text("utf-8"))

    def save_progress(self, progress: Progress) -> None:
        atomic_write_json(self.world_dir / "progress.json", progress.model_dump())

    def load_event_queue(self) -> EventQueue:
        path = self.world_dir / "event_queue.json"
        if not path.exists():
            return EventQueue()
        return EventQueue.model_validate_json(path.read_text("utf-8"))

    def save_event_queue(self, eq: EventQueue) -> None:
        atomic_write_json(self.world_dir / "event_queue.json", eq.model_dump())
