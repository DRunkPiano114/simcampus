"""Phase 0 self-test — renders two visual-sanity images for sign-off:

  1. test_portraits.png      — 2×5 grid of all 10 agent portraits
  2. prototype_scene_card.png — real 1080×1440 scene card rendered from
                                simulation/days/day_001/2200_宿舍夜聊.json tick 3

Output is written to .cache/self_test/ (gitignored).

Run: `uv run python -m sim.cards.self_test`
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .assets import PROJECT_ROOT, load_visual_bible
from .base import (
    CANVAS_H,
    CANVAS_W,
    CINNABAR_RED,
    INK_BLACK,
    INK_GRAY,
    PAPER_CREAM,
    font_serif,
    font_wen,
    paper_background,
    save_png,
)
from .elements.banner import draw_divider
from .elements.balloon import render_balloon
from .elements.portrait import load_portrait, scaled_portrait
from .elements.seal import render_seal

OUT_DIR = PROJECT_ROOT / ".cache" / "self_test"

# --- test_portraits grid ---------------------------------------------------


def render_portrait_grid() -> Image.Image:
    """Render a 2×5 grid of all agent portraits onto a cream background.

    Ordering: students in bible order, teacher last with an outline to flag the
    visual distinction.
    """
    bible = load_visual_bible()
    ordered = [aid for aid, cfg in bible.items() if not cfg.get("is_teacher")] + [
        aid for aid, cfg in bible.items() if cfg.get("is_teacher")
    ]

    cols, rows = 5, 2
    cell = 340
    pad = 40
    label_h = 56
    W = pad + cols * cell + (cols - 1) * 20 + pad
    H = pad + rows * (cell + label_h) + (rows - 1) * 32 + pad

    canvas = Image.new("RGBA", (W, H), PAPER_CREAM)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas, "RGBA")

    title_fnt = font_serif(40, bold=True)
    draw.text((pad, 10), "SimCampus · Portraits Sheet", font=title_fnt, fill=INK_BLACK)

    fnt = font_wen(30)
    for i, agent_id in enumerate(ordered):
        row, col = divmod(i, cols)
        x = pad + col * (cell + 20)
        y = pad + 40 + row * (cell + label_h + 32)
        p = load_portrait(agent_id)
        # Pre-generated portrait is 320×320; resize up slightly to 300 to fit
        p = p.resize((cell - 40, cell - 40), Image.Resampling.NEAREST)
        canvas.paste(p, (x + 20, y + 10), p)
        name_cn = bible[agent_id]["name_cn"]
        tag = bible[agent_id].get("motif_tag", "")
        label = f"{name_cn} · {tag}"
        draw.text(
            (x + cell / 2, y + cell + 6),
            label,
            font=fnt,
            fill=INK_GRAY,
            anchor="mt",
        )
    return canvas


# --- prototype scene card --------------------------------------------------

SCENE_FIXTURE_PATH = (
    PROJECT_ROOT / "web" / "public" / "data" / "days" / "day_001" / "2200_宿舍夜聊.json"
)
# Fallback if web/public/data is not yet exported: try the raw sim output.
SCENE_FIXTURE_FALLBACK = (
    PROJECT_ROOT / "simulation" / "days" / "day_001" / "2200_宿舍夜聊.json"
)


def _load_fixture() -> dict:
    for candidate in (SCENE_FIXTURE_PATH, SCENE_FIXTURE_FALLBACK):
        if candidate.exists():
            return json.loads(candidate.read_text("utf-8"))
    raise FileNotFoundError(
        "no day_001 dorm-night fixture found at either\n"
        f"  {SCENE_FIXTURE_PATH}\n  {SCENE_FIXTURE_FALLBACK}\n"
        "run `scripts/export_frontend_data.py` or adjust SCENE_FIXTURE_PATH."
    )


def render_prototype_scene_card() -> Image.Image:
    """Render the anchoring scene card: day_001 宿舍夜聊, tick 3 (girls' group).

    This is the Phase-0 sign-off visual — it must represent the final look of
    every scene card we will ever render. Layout intentionally simple: the
    point is to lock paper tone + font + portrait + bubble + seal.
    """
    data = _load_fixture()
    scene = data["scene"]
    group = data["groups"][1]  # girls' dorm: 唐诗涵 / 程雨桐 / 苏念瑶 / 方语晨
    tick = group["ticks"][3]
    bible = load_visual_bible()

    # Extract beat
    speech = tick["public"]["speech"]
    speaker_id = speech["agent"]                   # fang_yuchen
    speech_text = speech["content"]
    target_id = speech["target"]                   # cheng_yutong
    # Strongest contrasting thought = target's (urgency 8)
    target_mind = tick["minds"].get(target_id, {})
    target_thought = target_mind.get("inner_thought", "")
    # Witness: the other group member with a thought in this tick
    witness_id = next(
        (aid for aid, m in tick["minds"].items()
         if aid not in (speaker_id, target_id) and m.get("inner_thought")),
        None,
    )
    witness_thought = (
        tick["minds"][witness_id]["inner_thought"] if witness_id else ""
    )

    # Canvas
    img = paper_background(CANVAS_W, CANVAS_H)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img, "RGBA")

    # --- Header: date seal + scene title ----------------------------------
    date_seal = render_seal(f"第{scene['day']:03d}天", size=118, font_size=30)
    img.paste(date_seal, (72, 64), date_seal)

    title_fnt = font_serif(52, bold=True)
    sub_fnt = font_wen(32)
    title = f"{scene['time']}  ·  {scene['name']}"
    sub = f"{scene['location']}"
    draw.text((210, 70), title, font=title_fnt, fill=INK_BLACK)
    draw.text((210, 138), sub, font=sub_fnt, fill=INK_GRAY)

    draw_divider(img, y=210, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)

    # --- Main: 2 portraits + bubbles + witness ----------------------------
    # Portraits at 320×320 each, positioned at upper-left and upper-right
    portrait_size = 320
    p_left = scaled_portrait(speaker_id, portrait_size)
    p_right = scaled_portrait(target_id, portrait_size)
    y_portraits = 260
    img.paste(p_left, (80, y_portraits), p_left)
    img.paste(p_right, (CANVAS_W - 80 - portrait_size, y_portraits), p_right)

    # Name labels under portraits
    name_fnt = font_serif(38, bold=True)
    motif_fnt = font_wen(24)
    for x, aid in ((80, speaker_id), (CANVAS_W - 80 - portrait_size, target_id)):
        info = bible[aid]
        name_x = x + portrait_size / 2
        draw.text(
            (name_x, y_portraits + portrait_size + 12),
            info["name_cn"],
            font=name_fnt,
            fill=INK_BLACK,
            anchor="mt",
        )
        draw.text(
            (name_x, y_portraits + portrait_size + 62),
            f"{info.get('motif_emoji', '')} {info.get('motif_tag', '')}",
            font=motif_fnt,
            fill=INK_GRAY,
            anchor="mt",
        )

    # --- Bubbles ----------------------------------------------------------
    # Speech bubble from speaker, placed below the 2-portrait row, left-aligned
    bubble_y = y_portraits + portrait_size + 120
    speech_bal = render_balloon(
        speech_text,
        max_width=840,
        kind="speech",
        font_size=36,
        tail="bl",
    )
    img.paste(speech_bal, (90, bubble_y), speech_bal)

    # Target's inner thought — right-aligned, below speech bubble
    thought_y = bubble_y + speech_bal.height + 32
    thought_bal = render_balloon(
        f"（内心）{target_thought}",
        max_width=840,
        kind="thought",
        font_size=34,
        tail="br",
    )
    thought_x = CANVAS_W - 90 - thought_bal.width
    img.paste(thought_bal, (thought_x, thought_y), thought_bal)

    # --- Witness strip (optional) ----------------------------------------
    if witness_id and witness_thought:
        witness_y = thought_y + thought_bal.height + 28
        # Small portrait
        wp = scaled_portrait(witness_id, 160)
        img.paste(wp, (90, witness_y), wp)
        # Micro-label
        w_info = bible[witness_id]
        draw.text(
            (90 + 160 + 24, witness_y + 12),
            f"{w_info['name_cn']} 心想",
            font=font_serif(28, bold=True),
            fill=INK_GRAY,
        )
        # Small thought bubble
        wbal = render_balloon(
            witness_thought,
            max_width=640,
            kind="thought",
            font_size=28,
        )
        img.paste(wbal, (90 + 160 + 24, witness_y + 54), wbal)

    # --- Footer: divider + brand seal + tagline ---------------------------
    draw_divider(img, y=CANVAS_H - 150, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)

    brand = render_seal("班", size=120, font_size=80)
    img.paste(brand, (CANVAS_W - 72 - 120, CANVAS_H - 72 - 120), brand)

    tagline = "SimCampus · AI 校园模拟器"
    sub_tag = "每天都在上演"
    draw.text((90, CANVAS_H - 120), tagline, font=font_serif(32, bold=True), fill=INK_BLACK)
    draw.text((90, CANVAS_H - 80), sub_tag, font=font_wen(26), fill=INK_GRAY)

    return img


# --- CLI entry -------------------------------------------------------------


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("rendering test_portraits.png...")
    grid = render_portrait_grid()
    save_png(grid, OUT_DIR / "test_portraits.png")
    print(f"  → {OUT_DIR / 'test_portraits.png'}")

    print("rendering prototype_scene_card.png...")
    card = render_prototype_scene_card()
    save_png(card, OUT_DIR / "prototype_scene_card.png")
    print(f"  → {OUT_DIR / 'prototype_scene_card.png'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
