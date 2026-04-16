"""Daily card — 1080×1440 班级日报 summary for a single day.

Layered like scene_card:
  - Data is gathered by `aggregations.build_daily_summary(day)` (pure).
  - Rendering reads the dataclasses and draws Pillow primitives.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .aggregations import DailySummary, build_daily_summary
from .assets import load_visual_bible
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


def _draw_section_title(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> None:
    fnt = font_serif(28, bold=True)
    draw.text((x, y), label, font=fnt, fill=INK_BLACK)


def _render_mood_strip(
    img: Image.Image,
    y: int,
    summary: DailySummary,
    *,
    margin: int = 88,
) -> None:
    """Tiny color-chip strip: one dot per agent tinted by their main color."""
    if not summary.mood_map:
        return
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_section_title(draw, margin, y, "心情地图")
    bible = load_visual_bible()
    chip_y = y + 38
    chip_r = 26
    gap = 16
    n = len(summary.mood_map)
    total_w = n * (chip_r * 2) + (n - 1) * gap
    start_x = max(margin, (CANVAS_W - total_w) // 2)
    name_fnt = font_wen(18)
    for i, entry in enumerate(summary.mood_map):
        cx = start_x + chip_r + i * (chip_r * 2 + gap)
        cy = chip_y + chip_r
        hex_ = bible.get(entry.agent_id, {}).get("main_color", "#888888")
        color = _hex_to_rgba(hex_, alpha=240)
        draw.ellipse(
            [(cx - chip_r, cy - chip_r), (cx + chip_r, cy + chip_r)],
            fill=color,
            outline=INK_BLACK,
            width=2,
        )
        draw.text(
            (cx, cy + chip_r + 8),
            entry.agent_name,
            font=name_fnt,
            fill=INK_GRAY,
            anchor="mt",
        )


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b, alpha)


def _render_cp_block(img: Image.Image, y: int, summary: DailySummary, *, margin: int = 88) -> int:
    if summary.cp is None:
        return y
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_section_title(draw, margin, y, "今日 CP")
    cp = summary.cp
    # Two small portraits side by side with a red heart between.
    portrait_size = 140
    a = scaled_portrait(cp.a_id, portrait_size)
    b = scaled_portrait(cp.b_id, portrait_size)
    row_y = y + 50
    img.paste(a, (margin, row_y), a)
    img.paste(b, (margin + portrait_size + 90, row_y), b)
    heart_fnt = font_serif(60, bold=True)
    draw.text(
        (margin + portrait_size + 45, row_y + portrait_size // 2),
        "♥",
        font=heart_fnt,
        fill=(176, 40, 28, 255),
        anchor="mm",
    )
    name_fnt = font_serif(24, bold=True)
    draw.text(
        (margin + portrait_size // 2, row_y + portrait_size + 8),
        cp.a_name,
        font=name_fnt,
        fill=INK_BLACK,
        anchor="mt",
    )
    draw.text(
        (margin + portrait_size + 90 + portrait_size // 2, row_y + portrait_size + 8),
        cp.b_name,
        font=name_fnt,
        fill=INK_BLACK,
        anchor="mt",
    )
    delta_fnt = font_wen(20)
    draw.text(
        (margin, row_y + portrait_size + 50),
        f"好感 +{cp.favorability_delta}  信任 +{cp.trust_delta}  理解 +{cp.understanding_delta}",
        font=delta_fnt,
        fill=INK_GRAY,
    )
    return row_y + portrait_size + 90


def _render_quote_block(
    img: Image.Image,
    y: int,
    summary: DailySummary,
    *,
    margin: int = 88,
) -> int:
    if summary.golden_quote is None:
        return y
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_section_title(draw, margin, y, "今日金句")
    quote = summary.golden_quote
    bal = render_balloon(
        f"（{quote.agent_name}）{quote.text}",
        max_width=CANVAS_W - 2 * margin,
        kind="thought",
        font_size=30,
    )
    img.paste(bal, (margin, y + 40), bal)
    return y + 40 + bal.height + 12


def _render_headline_block(
    img: Image.Image,
    y: int,
    summary: DailySummary,
    *,
    margin: int = 88,
) -> int:
    h = summary.headline
    if h is None:
        return y
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_section_title(draw, margin, y, "今日头条")

    meta_fnt = font_wen(22)
    draw.text(
        (margin, y + 34),
        f"{h.scene_time}  ·  {h.scene_name}  ·  {h.scene_location}",
        font=meta_fnt,
        fill=INK_GRAY,
    )

    body_fnt = font_serif(28, bold=True)
    body_start_y = y + 66
    # Speech line (if any)
    if h.speech:
        bal = render_balloon(
            f"{h.speaker_name}：{h.speech}",
            max_width=CANVAS_W - 2 * margin,
            kind="speech",
            font_size=28,
        )
        img.paste(bal, (margin, body_start_y), bal)
        body_start_y += bal.height + 12
    if h.thought:
        bal = render_balloon(
            f"（{h.thought_name or h.speaker_name} 心想）{h.thought}",
            max_width=CANVAS_W - 2 * margin,
            kind="thought",
            font_size=26,
        )
        img.paste(bal, (margin, body_start_y), bal)
        body_start_y += bal.height + 12
    _ = body_fnt  # font retained for downstream callers if needed
    return body_start_y


def _render_card(summary: DailySummary) -> Image.Image:
    img = paper_background(CANVAS_W, CANVAS_H)
    draw = ImageDraw.Draw(img, "RGBA")

    # Header: big date seal + title
    seal = render_seal(f"第{summary.day:03d}天", size=138, font_size=34)
    img.paste(seal, (72, 60), seal)

    title_fnt = font_serif(60, bold=True)
    sub_fnt = font_wen(30)
    draw.text((232, 72), "班级日报", font=title_fnt, fill=INK_BLACK)
    draw.text((232, 150), "一天里的教室、宿舍、操场与心事", font=sub_fnt, fill=INK_GRAY)

    draw_divider(img, y=218, x_start=72, x_end=CANVAS_W - 72, color=INK_GRAY, dash=10)

    y = 240
    y = _render_headline_block(img, y, summary)
    y += 16
    y = _render_quote_block(img, y, summary)
    y += 10
    # Mood strip sits near bottom-half
    _render_mood_strip(img, y + 10, summary)
    y += 130
    y = _render_cp_block(img, y, summary)

    # Footer: brand
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


def render(day: int) -> Image.Image:
    summary = build_daily_summary(day)
    return _render_card(summary)
