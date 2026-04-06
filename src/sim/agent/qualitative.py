"""Numeric → qualitative label mappings for LLM prompts.

These thresholds are internal and never exposed to LLM prompts.
"""


def energy_label(v: int) -> str:
    if v <= 20:
        return "精疲力尽"
    if v <= 40:
        return "有点累"
    if v <= 65:
        return "一般"
    if v <= 85:
        return "精神还行"
    return "精神充沛"


def pressure_label(v: int) -> str:
    if v <= 25:
        return "轻松"
    if v <= 45:
        return "稍有压力"
    if v <= 65:
        return "压力不小"
    if v <= 85:
        return "压力很大"
    return "几乎扛不住"


def intensity_label(v: int) -> str:
    if v <= 3:
        return "轻微"
    if v <= 6:
        return "中等"
    if v <= 8:
        return "较强"
    return "强烈"


def relationship_label(favorability: int, trust: int) -> str:
    avg = (favorability + trust) / 2
    if avg >= 30:
        return "亲近"
    if avg >= 10:
        return "还行"
    if avg >= -5:
        return "一般"
    if avg >= -20:
        return "有点疏远"
    return "不对付"


def next_exam_label(days: int) -> str:
    if days <= 3:
        return "月考近在眼前"
    if days <= 7:
        return "月考快到了"
    if days <= 14:
        return "月考还有两周"
    return "月考还远"
