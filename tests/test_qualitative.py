"""Tests for numeric → qualitative label mappings."""

from sim.agent.qualitative import (
    energy_label,
    intensity_label,
    next_exam_label,
    pressure_label,
    relationship_label,
)


# --- energy_label ---

def test_energy_exhausted():
    assert energy_label(0) == "精疲力尽"
    assert energy_label(20) == "精疲力尽"


def test_energy_tired():
    assert energy_label(21) == "有点累"
    assert energy_label(40) == "有点累"


def test_energy_normal():
    assert energy_label(41) == "一般"
    assert energy_label(65) == "一般"


def test_energy_okay():
    assert energy_label(66) == "精神还行"
    assert energy_label(85) == "精神还行"


def test_energy_energetic():
    assert energy_label(86) == "精神充沛"
    assert energy_label(100) == "精神充沛"


# --- pressure_label ---

def test_pressure_relaxed():
    assert pressure_label(0) == "轻松"
    assert pressure_label(25) == "轻松"


def test_pressure_slight():
    assert pressure_label(26) == "稍有压力"
    assert pressure_label(45) == "稍有压力"


def test_pressure_moderate():
    assert pressure_label(46) == "压力不小"
    assert pressure_label(65) == "压力不小"


def test_pressure_high():
    assert pressure_label(66) == "压力很大"
    assert pressure_label(85) == "压力很大"


def test_pressure_extreme():
    assert pressure_label(86) == "几乎扛不住"
    assert pressure_label(100) == "几乎扛不住"


# --- intensity_label ---

def test_intensity_mild():
    assert intensity_label(1) == "轻微"
    assert intensity_label(3) == "轻微"


def test_intensity_moderate():
    assert intensity_label(4) == "中等"
    assert intensity_label(6) == "中等"


def test_intensity_strong():
    assert intensity_label(7) == "较强"
    assert intensity_label(8) == "较强"


def test_intensity_intense():
    assert intensity_label(9) == "强烈"
    assert intensity_label(10) == "强烈"


# --- relationship_label (7-tier, favorability-driven) ---

def test_relationship_very_close():
    assert relationship_label(20, 10) == "很亲近的朋友"
    assert relationship_label(30, 30) == "很亲近的朋友"


def test_relationship_good():
    assert relationship_label(15, 5) == "关系不错"
    assert relationship_label(19, 3) == "关系不错"


def test_relationship_some_favor():
    assert relationship_label(8, 0) == "还行，有些好感"
    assert relationship_label(14, 0) == "还行，有些好感"


def test_relationship_normal():
    assert relationship_label(0, 0) == "普通同学"
    assert relationship_label(7, 0) == "普通同学"


def test_relationship_distant():
    assert relationship_label(-5, 0) == "有点疏远"
    assert relationship_label(-3, -5) == "有点疏远"


def test_relationship_tense():
    assert relationship_label(-10, 0) == "关系紧张"
    assert relationship_label(-8, -10) == "关系紧张"


def test_relationship_hostile():
    assert relationship_label(-11, 0) == "互相看不顺眼"
    assert relationship_label(-30, -30) == "互相看不顺眼"


# --- next_exam_label ---

def test_exam_imminent():
    assert next_exam_label(1) == "月考近在眼前"
    assert next_exam_label(3) == "月考近在眼前"


def test_exam_soon():
    assert next_exam_label(4) == "月考快到了"
    assert next_exam_label(7) == "月考快到了"


def test_exam_two_weeks():
    assert next_exam_label(8) == "月考还有两周"
    assert next_exam_label(14) == "月考还有两周"


def test_exam_far():
    assert next_exam_label(15) == "月考还远"
    assert next_exam_label(30) == "月考还远"


# --- Edge cases: out-of-range inputs ---

def test_energy_label_negative():
    """Negative energy should still map to the lowest tier."""
    assert energy_label(-10) == "精疲力尽"


def test_energy_label_above_100():
    """Energy above 100 should map to the highest tier."""
    assert energy_label(120) == "精神充沛"


def test_pressure_label_negative():
    assert pressure_label(-5) == "轻松"


def test_pressure_label_above_100():
    assert pressure_label(110) == "几乎扛不住"


def test_intensity_label_zero():
    """Intensity of 0 (below normal range) should map to the lowest tier."""
    assert intensity_label(0) == "轻微"


def test_relationship_label_extreme_positive():
    """Very high favorability + trust → 很亲近的朋友."""
    assert relationship_label(100, 100) == "很亲近的朋友"


def test_relationship_label_extreme_negative():
    """Very low favorability + trust → 互相看不顺眼."""
    assert relationship_label(-100, -100) == "互相看不顺眼"
