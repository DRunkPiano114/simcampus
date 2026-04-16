"""Scene card — Phase 1 template.

Three layers, deliberately separated for testability:

  1. Pure selection (`select_featured_group`) — no Pillow, works on raw JSON.
  2. LayoutSpec (`scene_to_layout_spec`) — dataclass capturing exactly what
     the renderer needs. Trivially unit-testable.
  3. Render (`render`) — Pillow-side, smoke-tested only (pixel output is
     non-deterministic across libfreetype versions).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .assets import PROJECT_ROOT, load_visual_bible
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

DAYS_DIR = PROJECT_ROOT / "web" / "public" / "data" / "days"

# Maximum number of participants we portrait. Beyond this, the card gets
# unreadable — we pick the three most involved (speaker, target, top witness).
MAX_PORTRAITS = 3


# --- Data loading ----------------------------------------------------------


def day_dir(day: int) -> Path:
    return DAYS_DIR / f"day_{day:03d}"


def load_scenes_index(day: int) -> list[dict[str, Any]]:
    path = day_dir(day) / "scenes.json"
    if not path.exists():
        raise FileNotFoundError(f"scenes.json not found for day {day}: {path}")
    return json.loads(path.read_text("utf-8"))


def load_scene_by_array_index(day: int, scene_idx: int) -> dict[str, Any]:
    """Load a scene by its position in scenes.json (0-based).

    The frontend navigates by array position (scenes.json entries can carry
    non-sequential `scene_index` fields); the API mirrors that contract.
    """
    index = load_scenes_index(day)
    if scene_idx < 0 or scene_idx >= len(index):
        raise IndexError(
            f"scene_idx {scene_idx} out of range for day {day} "
            f"(have {len(index)} scenes)"
        )
    entry = index[scene_idx]
    path = day_dir(day) / entry["file"]
    if not path.exists():
        raise FileNotFoundError(f"scene file not found: {path}")
    return json.loads(path.read_text("utf-8"))


# --- Selection (pure) ------------------------------------------------------


def select_featured_group(scene_data: dict[str, Any]) -> int | None:
    """Pick the most dramatically loaded multi-agent group in the scene.

    Rules (matching the plan):
      1. Filter to multi-agent groups (is_solo=False or no is_solo field +
         multiple participants).
      2. Rank by sum(tick.urgency) + sum(len(inner_thought)) across all ticks.
      3. If no multi-agent group exists, return None (caller should emit 404:
         solo reflections belong on the agent card, not the scene card).
    """
    candidates: list[tuple[int, int]] = []  # (score, group_index)
    for idx, group in enumerate(scene_data.get("groups", [])):
        if group.get("is_solo"):
            continue
        if len(group.get("participants", [])) < 2:
            continue
        ticks = group.get("ticks") or []
        if not ticks:
            continue
        score = 0
        for tick in ticks:
            minds = tick.get("minds") or {}
            for mind in minds.values():
                score += int(mind.get("urgency") or 0)
                score += len(mind.get("inner_thought") or "")
        candidates.append((score, idx))

    if not candidates:
        return None
    # Highest score; ties broken by earliest group_index for determinism.
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return candidates[0][1]


def _pick_featured_tick(group: dict[str, Any]) -> dict[str, Any] | None:
    """Choose the tick inside the group with the strongest beat.

    Prefers: tick that has public speech AND at least one rich inner thought
    (≥ 12 chars). Falls back to highest aggregate urgency.
    """
    ticks = group.get("ticks") or []
    if not ticks:
        return None

    def score(tick: dict[str, Any]) -> tuple[int, int, int]:
        has_speech = bool((tick.get("public") or {}).get("speech"))
        minds = tick.get("minds") or {}
        rich_thoughts = sum(
            1 for m in minds.values() if len(m.get("inner_thought") or "") >= 12
        )
        urgency_sum = sum(int(m.get("urgency") or 0) for m in minds.values())
        return (int(has_speech), rich_thoughts, urgency_sum)

    return max(ticks, key=score)


# --- LayoutSpec ------------------------------------------------------------


@dataclass(frozen=True)
class BubbleSpec:
    agent_id: str
    display_name: str
    kind: str  # "speech" | "thought"
    text: str


@dataclass(frozen=True)
class LayoutSpec:
    """Everything the renderer needs, derived purely from scene data."""

    day: int
    time: str
    scene_name: str
    location: str
    # Ordered portraits: speaker first, target second, witness third.
    portraits: list[tuple[str, str]] = field(default_factory=list)  # (agent_id, name_cn)
    bubbles: list[BubbleSpec] = field(default_factory=list)
    featured_quote: str | None = None  # strongest inner thought, for caption
    featured_speaker_name: str | None = None


def _group_display_name(
    agent_id: str,
    participant_names: dict[str, str],
    bible: dict[str, Any],
) -> str:
    if agent_id in participant_names:
        return participant_names[agent_id]
    visual = bible.get(agent_id, {})
    return visual.get("name_cn", agent_id)


def scene_to_layout_spec(
    scene_data: dict[str, Any],
    group_index: int,
) -> LayoutSpec:
    """Project a scene + group selection into a render-ready dataclass."""
    bible = load_visual_bible()
    scene = scene_data["scene"]
    participant_names = scene_data.get("participant_names", {})
    group = scene_data["groups"][group_index]

    portraits: list[tuple[str, str]] = []
    bubbles: list[BubbleSpec] = []
    featured_quote: str | None = None
    featured_speaker_name: str | None = None

    tick = _pick_featured_tick(group)
    if tick is None:
        # No ticks — unusual but possible. Card still renders header + empty.
        return LayoutSpec(
            day=scene["day"],
            time=scene["time"],
            scene_name=scene["name"],
            location=scene["location"],
        )

    speech = (tick.get("public") or {}).get("speech") or {}
    speaker_id = speech.get("agent")
    target_id = speech.get("target")
    speech_text = speech.get("content") or ""

    minds = tick.get("minds") or {}

    # Ordered portraits: speaker, target, top witness (not speaker/target).
    used: set[str] = set()
    ordered: list[str] = []
    if speaker_id and speaker_id in group.get("participants", []):
        ordered.append(speaker_id)
        used.add(speaker_id)
    if target_id and target_id in group.get("participants", []) and target_id not in used:
        ordered.append(target_id)
        used.add(target_id)

    witness_candidates = [
        (aid, m)
        for aid, m in minds.items()
        if aid not in used and m.get("inner_thought")
    ]
    witness_candidates.sort(
        key=lambda item: int(item[1].get("urgency") or 0),
        reverse=True,
    )
    for aid, _ in witness_candidates:
        if len(ordered) >= MAX_PORTRAITS:
            break
        ordered.append(aid)
        used.add(aid)

    # Fill remaining slots from other participants (keeps the card populated
    # even when there's no rich inner monologue).
    for aid in group.get("participants", []):
        if len(ordered) >= MAX_PORTRAITS:
            break
        if aid not in used:
            ordered.append(aid)
            used.add(aid)

    portraits = [
        (aid, _group_display_name(aid, participant_names, bible))
        for aid in ordered[:MAX_PORTRAITS]
    ]

    # Bubbles: speech from speaker, thought from target (if present), thought
    # from witness (if present).
    if speaker_id and speech_text:
        bubbles.append(
            BubbleSpec(
                agent_id=speaker_id,
                display_name=_group_display_name(speaker_id, participant_names, bible),
                kind="speech",
                text=speech_text,
            )
        )

    if target_id and target_id in minds:
        t_thought = minds[target_id].get("inner_thought")
        if t_thought:
            bubbles.append(
                BubbleSpec(
                    agent_id=target_id,
                    display_name=_group_display_name(target_id, participant_names, bible),
                    kind="thought",
                    text=t_thought,
                )
            )

    for aid, _ in witness_candidates[:1]:
        w_thought = minds[aid].get("inner_thought")
        if w_thought:
            bubbles.append(
                BubbleSpec(
                    agent_id=aid,
                    display_name=_group_display_name(aid, participant_names, bible),
                    kind="thought",
                    text=w_thought,
                )
            )

    # Featured quote = strongest inner_thought by (urgency, length).
    thought_ranking = sorted(
        ((aid, m) for aid, m in minds.items() if m.get("inner_thought")),
        key=lambda item: (
            int(item[1].get("urgency") or 0),
            len(item[1].get("inner_thought") or ""),
        ),
        reverse=True,
    )
    if thought_ranking:
        aid, m = thought_ranking[0]
        featured_quote = m.get("inner_thought")
        featured_speaker_name = _group_display_name(aid, participant_names, bible)

    return LayoutSpec(
        day=scene["day"],
        time=scene["time"],
        scene_name=scene["name"],
        location=scene["location"],
        portraits=portraits,
        bubbles=bubbles,
        featured_quote=featured_quote,
        featured_speaker_name=featured_speaker_name,
    )


# --- Rendering -------------------------------------------------------------


def _render_card(spec: LayoutSpec) -> Image.Image:
    """Draw a 1080×1440 scene card from a LayoutSpec. Pillow side only."""
    bible = load_visual_bible()
    img = paper_background(CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img, "RGBA")

    # --- Header: date seal + scene title ----------------------------------
    date_seal = render_seal(f"第{spec.day:03d}天", size=118, font_size=30)
    img.paste(date_seal, (72, 64), date_seal)

    title_fnt = font_serif(52, bold=True)
    sub_fnt = font_wen(32)
    draw.text(
        (210, 70),
        f"{spec.time}  ·  {spec.scene_name}",
        font=title_fnt,
        fill=INK_BLACK,
    )
    draw.text((210, 138), spec.location, font=sub_fnt, fill=INK_GRAY)

    draw_divider(img, y=210, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)

    # --- Portraits row ----------------------------------------------------
    n = len(spec.portraits)
    portrait_size = 320 if n <= 2 else 260
    y_portraits = 260
    gutter = 40

    if n == 0:
        pass  # header-only card (rare; empty body)
    else:
        total_w = n * portrait_size + (n - 1) * gutter
        start_x = (CANVAS_W - total_w) // 2
        name_fnt = font_serif(36, bold=True)
        motif_fnt = font_wen(22)
        for i, (aid, name_cn) in enumerate(spec.portraits):
            x = start_x + i * (portrait_size + gutter)
            p = scaled_portrait(aid, portrait_size)
            img.paste(p, (x, y_portraits), p)
            cx = x + portrait_size / 2
            draw.text(
                (cx, y_portraits + portrait_size + 12),
                name_cn,
                font=name_fnt,
                fill=INK_BLACK,
                anchor="mt",
            )
            motif = bible.get(aid, {})
            tag = f"{motif.get('motif_emoji', '')} {motif.get('motif_tag', '')}".strip()
            if tag:
                draw.text(
                    (cx, y_portraits + portrait_size + 58),
                    tag,
                    font=motif_fnt,
                    fill=INK_GRAY,
                    anchor="mt",
                )

    # --- Bubbles ----------------------------------------------------------
    bubble_y = y_portraits + portrait_size + 120
    max_bubble_y = CANVAS_H - 200
    for i, bubble in enumerate(spec.bubbles):
        if bubble_y >= max_bubble_y:
            break
        # Alternate sides: speech left, thought right.
        align_right = bubble.kind == "thought" and i > 0
        prefix = ""
        if bubble.kind == "thought":
            prefix = f"（{bubble.display_name} 心想）"
        else:
            prefix = f"{bubble.display_name}："
        bal = render_balloon(
            prefix + bubble.text,
            max_width=840,
            kind=bubble.kind,
            font_size=34 if bubble.kind == "thought" else 36,
            tail="br" if align_right else "bl",
        )
        x = CANVAS_W - 90 - bal.width if align_right else 90
        img.paste(bal, (x, bubble_y), bal)
        bubble_y += bal.height + 28

    # --- Footer: divider + brand seal + tagline ---------------------------
    draw_divider(
        img,
        y=CANVAS_H - 150,
        x_start=72,
        x_end=CANVAS_W - 72,
        color=INK_GRAY,
        dash=10,
    )

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


def render(day: int, scene_idx: int) -> Image.Image | None:
    """Public entry point: load scene, pick group, render, or None if all-solo."""
    scene_data = load_scene_by_array_index(day, scene_idx)
    group_index = select_featured_group(scene_data)
    if group_index is None:
        return None
    spec = scene_to_layout_spec(scene_data, group_index)
    return _render_card(spec)
