from datetime import datetime

from src.energy.simulator import PowerySimulator
from src.energy.detector import rule_detect, detect
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


def test_forecast_peak_returns_suggestion():
    sim = PowerySimulator(room_count=3, seed=3)
    history = sim.generate_day(datetime(2024, 5, 22))
    pred = forecast_peak(history[:72], forecast_hours=24, peak_threshold_w=3000)
    assert len(pred["predicted"]) == 24
    assert pred["suggestion"]
    assert pred["peak_count"] >= 0
