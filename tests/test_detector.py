from datetime import datetime

from src.energy.simulator import PowerySimulator
from src.energy.detector import rule_detect, detect, vision_detect
from src.energy.forecast import forecast_peak


def test_simulator_generates_data():
    sim = PowerySimulator(room_count=3, seed=1)
    day = datetime(2024, 5, 22)
    records = sim.generate_day(day)
    assert len(records) == 3 * 24
    assert all(r["power_w"] > 0 for r in records)


def test_rule_detect_finds_high_power():
    sim = PowerySimulator(room_count=20, seed=99)
    records = sim.generate_day(datetime(2024, 5, 22))
    alarms = rule_detect(records)
    # 模拟数据包含 30% 违规房间，20 个房间应至少命中若干
    assert len(alarms) > 0


def test_detect_returns_summary():
    sim = PowerySimulator(room_count=5, seed=5)
    records = sim.generate_day(datetime(2024, 5, 22))
    result = detect(records, use_vision=False)
    assert "rule_alarms" in result
    assert "summary" in result
    assert result["vision_used"] is False
    # 纯规则通道应为 medium 置信（无视觉复核）
    if result["rule_alarms"]:
        assert result["rule_alarms"][0]["confidence"] == "medium"


def test_detect_dual_channel_vision():
    """IoT功率规则 + 智算视觉 双通道：命中房间应升级为 high 置信并返回视觉证据。"""
    sim = PowerySimulator(room_count=20, seed=99)
    records = sim.generate_day(datetime(2024, 5, 22))
    result = detect(records, use_vision=True)
    assert result["vision_used"] is True
    assert result["vision"] is not None
    # 规则命中房间应全部被视觉复核为高置信
    if result["rule_alarms"]:
        assert result["vision"]["detected"] is True
        assert len(result["vision"]["objects"]) == len(result["rule_alarms"])
        assert all(a["confidence"] == "high" for a in result["rule_alarms"])


def test_vision_detect_without_candidates_is_noop():
    v = vision_detect(candidate_rooms=[])
    assert v["detected"] is False
    assert v["objects"] == []


def test_forecast_peak_returns_suggestion():
    sim = PowerySimulator(room_count=3, seed=3)
    history = sim.generate_day(datetime(2024, 5, 22))
    pred = forecast_peak(history[:72], forecast_hours=24, peak_threshold_w=3000)
    assert len(pred["predicted"]) == 24
    assert pred["suggestion"]
    assert pred["peak_count"] >= 0
