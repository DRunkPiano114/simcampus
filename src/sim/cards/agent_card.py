"""Agent archive card — 累计成长模式.

Day N's agent card shows the agent as they are at the end of Day N: cumulative
emotion, top relationships, recent memories, active concerns, and a featured
inner thought from the day. Reuses `build_context_at_timepoint` so all the
snapshot-loading, today-so-far, and qualitative-label logic is shared with
the chat/role-play endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw

from ..agent.storage import WorldStorage
from ..api.context import build_context_at_timepoint
from .aggregations import load_day_scenes
from .assets import get_agent_visual
from .base import (
    CANVAS_H,
    CANVAS_W,
    INK_BLACK,
    INK_GRAY,
    font_serif,
    font_wen,
    paper_background,
)
from .elements.balloon import render_balloon
from .elements.banner import draw_divider
from .elements.portrait import scaled_portrait
from .elements.seal import render_seal

# Agent cards are rendered using the 22:00 end-of-day snapshot.
AGENT_TIME_PERIOD = "22:00"

# Chinese labels for emotion enum values — backend ships raw English from the
# Emotion enum, but a share card is end-user-facing so it gets the display text
# here. Keep in sync with web/src/lib/constants.ts::EMOTION_LABELS.
EMOTION_LABELS_CN: dict[str, str] = {
    "happy": "开心",
    "sad": "难过",
    "anxious": "焦虑",
    "angry": "生气",
    "excited": "兴奋",
    "calm": "平静",
    "embarrassed": "尴尬",
    "bored": "无聊",
    "neutral": "平常",
    "jealous": "嫉妒",
    "proud": "自豪",
    "guilty": "愧疚",
    "frustrated": "挫败",
    "touched": "感动",
    "curious": "好奇",
}


def _emotion_cn(raw: str) -> str:
    return EMOTION_LABELS_CN.get(raw, raw)


# --- Data types ------------------------------------------------------------


@dataclass(frozen=True)
class RelationshipPreview:
    target_name: str
    favorability: int
    trust: int
    label_text: str


@dataclass(frozen=True)
class MemoryPreview:
    date: str
    text: str
    importance: int


@dataclass(frozen=True)
class ConcernPreview:
    text: str
    intensity_label: str
    positive: bool


@dataclass(frozen=True)
class AgentLayoutSpec:
    """Render-ready snapshot of one agent on one day."""

    agent_id: str
    name_cn: str
    day: int
    is_teacher: bool
    motif_emoji: str
    motif_tag: str
    main_color: str
    emotion_label: str
    energy_label: str
    pressure_label: str
    featured_quote: str | None
    featured_scene: str | None
    relationships: list[RelationshipPreview] = field(default_factory=list)
    memories: list[MemoryPreview] = field(default_factory=list)
    top_concern: ConcernPreview | None = None
    self_narrative: str = ""


# --- Pure projection -------------------------------------------------------


def _featured_quote_for(agent_id: str, day: int) -> tuple[str | None, str | None]:
    """Walk the day's scenes, pick the agent's strongest inner thought."""
    try:
        scenes = load_day_scenes(day)
    except FileNotFoundError:
        return None, None

    best: tuple[int, str, str] | None = None  # (score, thought, scene_label)
    for scene in scenes:
        sinfo = scene.get("scene", {})
        label = f"{sinfo.get('time', '')} · {sinfo.get('name', '')}"
        for g in scene.get("groups", []):
            if g.get("is_solo"):
                refl = g.get("solo_reflection", {}) or {}
                thought = refl.get("inner_thought", "")
                if agent_id in g.get("participants", []) and thought:
                    score = len(thought) + 4  # solo thoughts lack urgency; weight them lightly
                    if not best or score > best[0]:
                        best = (score, thought, label)
                continue
            for tick in g.get("ticks", []) or []:
                mind = (tick.get("minds") or {}).get(agent_id)
                if not mind:
                    continue
                thought = mind.get("inner_thought", "")
                if len(thought) < 10:
                    continue
                urgency = int(mind.get("urgency") or 0)
                score = urgency * 5 + len(thought)
                if not best or score > best[0]:
                    best = (score, thought, label)
    if not best:
        return None, None
    _, thought, label = best
    return thought, label


def context_to_agent_spec(
    agent_id: str,
    day: int,
    ctx: dict[str, Any],
    featured_quote: str | None,
    featured_scene: str | None,
) -> AgentLayoutSpec:
    """Project chat-context dict → render-ready dataclass."""
    visual = get_agent_visual(agent_id)
    is_teacher = bool(visual.get("is_teacher"))

    # Top 3 relationships by favorability, only for students (teacher card
    # omits CP/relationship section).
    rels: list[RelationshipPreview] = []
    if not is_teacher:
        raw = sorted(
            ctx.get("relationships", []),
            key=lambda r: int(r.get("favorability") or 0),
            reverse=True,
        )[:3]
        for r in raw:
            rels.append(
                RelationshipPreview(
                    target_name=r.get("target_name", ""),
                    favorability=int(r.get("favorability") or 0),
                    trust=int(r.get("trust") or 0),
                    label_text=r.get("label_text", ""),
                )
            )

    # Top 2 key memories by importance (already sorted by build_context…).
    mems: list[MemoryPreview] = []
    for m in ctx.get("key_memories", [])[:2]:
        if hasattr(m, "model_dump"):
            m = m.model_dump()
        mems.append(
            MemoryPreview(
                date=str(m.get("date", "")),
                text=str(m.get("text", "")),
                importance=int(m.get("importance") or 0),
            )
        )

    # Top active concern (intensity already labeled in context).
    concerns_raw = ctx.get("active_concerns", [])
    top_concern: ConcernPreview | None = None
    if concerns_raw:
        def intensity_sort_key(c):
            return int(c.get("intensity") or 0)
        strongest = max(concerns_raw, key=intensity_sort_key)
        top_concern = ConcernPreview(
            text=str(strongest.get("text", "")),
            intensity_label=str(strongest.get("intensity_label", "")),
            positive=bool(strongest.get("positive")),
        )

    return AgentLayoutSpec(
        agent_id=agent_id,
        name_cn=visual.get("name_cn", agent_id),
        day=day,
        is_teacher=is_teacher,
        motif_emoji=visual.get("motif_emoji", ""),
        motif_tag=visual.get("motif_tag", ""),
        main_color=visual.get("main_color", "#888888"),
        emotion_label=_emotion_cn(str(ctx.get("emotion_label", ""))),
        energy_label=str(ctx.get("energy_label", "")),
        pressure_label=str(ctx.get("pressure_label", "")),
        featured_quote=featured_quote,
        featured_scene=featured_scene,
        relationships=rels,
        memories=mems,
        top_concern=top_concern,
        self_narrative=str(ctx.get("self_narrative", "")),
    )


def build_agent_spec(
    agent_id: str,
    day: int,
    world: WorldStorage,
) -> AgentLayoutSpec:
    """Public entry: world + agent + day → render-ready dataclass."""
    ctx = build_context_at_timepoint(agent_id, day, AGENT_TIME_PERIOD, world)
    quote, scene_label = _featured_quote_for(agent_id, day)
    return context_to_agent_spec(agent_id, day, ctx, quote, scene_label)


# --- Rendering -------------------------------------------------------------


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _render_card(spec: AgentLayoutSpec) -> Image.Image:
    img = paper_background(CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img, "RGBA")

    # --- Header strip with main color + day seal -----------------------
    color = _hex_to_rgba(spec.main_color, 180)
    draw.rectangle([(0, 0), (CANVAS_W, 36)], fill=color)

    seal = render_seal(f"第{spec.day:03d}天", size=118, font_size=30)
    img.paste(seal, (72, 56), seal)

    title_fnt = font_serif(60, bold=True)
    sub_fnt = font_wen(30)
    draw.text((232, 56), spec.name_cn, font=title_fnt, fill=INK_BLACK)
    # Teacher motif_tag (e.g. '班主任') already names the role — avoid
    # rendering "班主任 · 班主任 · 语文".
    subtitle = (
        f"{spec.motif_emoji} {spec.motif_tag} · 语文"
        if spec.is_teacher
        else f"{spec.motif_emoji} {spec.motif_tag} · 学生"
    )
    draw.text((232, 130), subtitle.strip(), font=sub_fnt, fill=INK_GRAY)

    draw_divider(img, y=210, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)

    # --- Big portrait ---------------------------------------------------
    portrait_size = 360
    portrait = scaled_portrait(spec.agent_id, portrait_size)
    img.paste(portrait, (72, 240), portrait)

    # --- Current-state panel (right of portrait) -----------------------
    panel_x = 72 + portrait_size + 40
    panel_y = 252
    label_fnt = font_serif(22, bold=True)
    value_fnt = font_wen(28)

    def _row(label: str, value: str, dy: int) -> None:
        draw.text((panel_x, panel_y + dy), label, font=label_fnt, fill=INK_GRAY)
        draw.text((panel_x + 110, panel_y + dy - 4), value, font=value_fnt, fill=INK_BLACK)

    _row("情绪", spec.emotion_label or "—", 0)
    _row("精力", spec.energy_label or "—", 56)
    _row("压力", spec.pressure_label or "—", 112)

    if spec.top_concern and not spec.is_teacher:
        tag = "期待" if spec.top_concern.positive else "挂怀"
        _row(tag, f"{spec.top_concern.intensity_label} · {spec.top_concern.text[:18]}", 168)

    # --- Featured inner thought (the card's heart) ----------------------
    y_quote = 240 + portrait_size + 40
    if spec.featured_quote:
        quote_label_fnt = font_serif(24, bold=True)
        draw.text((72, y_quote), "今日金句", font=quote_label_fnt, fill=INK_BLACK)
        bal = render_balloon(
            f"（{spec.name_cn} 心想）{spec.featured_quote}",
            max_width=CANVAS_W - 2 * 72,
            kind="thought",
            font_size=28,
        )
        img.paste(bal, (72, y_quote + 36), bal)
        y_quote += 36 + bal.height + 14
        if spec.featured_scene:
            meta_fnt = font_wen(20)
            draw.text(
                (72, y_quote),
                f"— {spec.featured_scene}",
                font=meta_fnt,
                fill=INK_GRAY,
            )
            y_quote += 32

    # --- Relationships (students only) ---------------------------------
    y_rels = y_quote + 20
    if spec.relationships:
        draw.text(
            (72, y_rels),
            "此刻关系 TOP 3",
            font=font_serif(24, bold=True),
            fill=INK_BLACK,
        )
        y_rels += 36
        rel_fnt = font_wen(24)
        label_small = font_wen(18)
        for r in spec.relationships:
            name_text = f"{r.target_name}"
            draw.text((86, y_rels), name_text, font=rel_fnt, fill=INK_BLACK)
            meta_text = f"{r.label_text} · 好感 {r.favorability:+d}  信任 {r.trust:+d}"
            draw.text((300, y_rels + 4), meta_text, font=label_small, fill=INK_GRAY)
            y_rels += 36

    # --- Footer -------------------------------------------------------------
    draw_divider(img, y=CANVAS_H - 150, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)
    brand = render_seal("班", size=120, font_size=80)
    img.paste(brand, (CANVAS_W - 72 - 120, CANVAS_H - 72 - 120), brand)
    draw.text(
        (90, CANVAS_H - 120),
        "SimCampus · AI 校园模拟器",
        font=font_serif(32, bold=True),
        fill=INK_BLACK,
    )
    draw.text(
        (90, CANVAS_H - 80),
        "每天都在上演",
        font=font_wen(26),
        fill=INK_GRAY,
    )
    return img


def render(agent_id: str, day: int, world: WorldStorage) -> Image.Image:
    spec = build_agent_spec(agent_id, day, world)
    return _render_card(spec)


# --- JSON serialization for API -------------------------------------------


def spec_to_dict(spec: AgentLayoutSpec) -> dict[str, Any]:
    return {
        "agent_id": spec.agent_id,
        "name_cn": spec.name_cn,
        "day": spec.day,
        "is_teacher": spec.is_teacher,
        "motif_emoji": spec.motif_emoji,
        "motif_tag": spec.motif_tag,
        "main_color": spec.main_color,
        "emotion_label": spec.emotion_label,
        "energy_label": spec.energy_label,
        "pressure_label": spec.pressure_label,
        "featured_quote": spec.featured_quote,
        "featured_scene": spec.featured_scene,
        "relationships": [
            {
                "target_name": r.target_name,
                "favorability": r.favorability,
                "trust": r.trust,
                "label_text": r.label_text,
            }
            for r in spec.relationships
        ],
        "memories": [
            {"date": m.date, "text": m.text, "importance": m.importance}
            for m in spec.memories
        ],
        "top_concern": None if spec.top_concern is None else {
            "text": spec.top_concern.text,
            "intensity_label": spec.top_concern.intensity_label,
            "positive": spec.top_concern.positive,
        },
        "self_narrative": spec.self_narrative,
    }
