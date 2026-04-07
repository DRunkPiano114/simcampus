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


# --- relationship_label ---

def test_relationship_close():
    assert relationship_label(30, 30) == "亲近"
    assert relationship_label(40, 20) == "亲近"


def test_relationship_okay():
    assert relationship_label(10, 10) == "还行"
    assert relationship_label(20, 8) == "还行"


def test_relationship_normal():
    assert relationship_label(0, 0) == "一般"
    assert relationship_label(-5, -5) == "一般"


def test_relationship_distant():
    assert relationship_label(-10, -10) == "有点疏远"
    assert relationship_label(-20, -20) == "有点疏远"


def test_relationship_hostile():
    assert relationship_label(-30, -30) == "不对付"
    assert relationship_label(-50, -10) == "不对付"


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
