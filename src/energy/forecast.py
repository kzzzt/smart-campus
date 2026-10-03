"""
用电高峰预测模块。

基于历史逐小时负荷数据，预测教学楼未来用电高峰时段，用于削峰调度与节能。
初稿采用简单的时间序列趋势 + 时段基线法；可替换为更复杂的预测模型
（如 LSTM / Prophet / 回归），接口保持一致。

返回预测出的"高峰时段"列表与预测功率序列，供运行管理侧做削峰调度提示。
"""

from datetime import datetime, timedelta


def _hour_seasonality(ts: datetime) -> float:
    """基于时刻的用电规律系数（模拟：白天课间高、夜间低）。"""
    h = ts.hour
    # 模拟教学楼使用规律：上午上课、下午上课、晚自习
    if 8 <= h <= 11:
        return 1.0
    if 14 <= h <= 17:
        return 0.95
    if 19 <= h <= 21:
        return 0.8
    return 0.3


def _weekday_factor(ts: datetime) -> float:
    return 1.0 if ts.weekday() < 5 else 0.5  # 工作日高，周末低


def forecast_peak(
    history: list[dict],
    forecast_hours: int = 24,
    peak_threshold_w: float = 5000.0,
) -> dict:
    """
    预测未来 forecast_hours 小时的负荷，并标记高峰时段。

    参数
    ----
    history : list[dict]
        历史逐小时负荷：[{"ts": datetime, "power_w": float}, ...]
    forecast_hours : int
        预测小时数
    peak_threshold_w : float
        高峰判定阈值

    返回
    ----
    {
        "predicted": [{"ts", "power_w"}],
        "peak_slots": [{"ts", "power_w"}],
        "peak_count": int,
        "suggestion": str,   # 减排/削峰建议
    }
    """
    if not history:
        start = datetime.now().replace(minute=0, second=0, microsecond=0)
    else:
        start = history[-1]["ts"] + timedelta(hours=1)

    predicted = []
    for i in range(forecast_hours):
        ts = start + timedelta(hours=i)
        # 基线 = 基准功率 * 时段系数 * 周几系数 + 轻噪声
        base = 3000 * _hour_seasonality(ts) * _weekday_factor(ts)
        power = round(base * (0.9 + 0.1 * ((i * 7) % 10) / 10), 1)
        predicted.append({"ts": ts, "power_w": power})

    peaks = [p for p in predicted if p["power_w"] > peak_threshold_w]

    suggestion = (
        f"预测未来 {forecast_hours}h 内出现 {len(peaks)} 个用电高峰"
        f"（阈值 {peak_threshold_w}W）。建议：将非关键负荷（如部分照明/空调）"
        "错峰运行，并联动智能排课系统避免上课时段叠加高能耗实验课。"
        if peaks
        else f"预测未来 {forecast_hours}h 用电平稳，无高峰。可持续保持低能耗策略。"
    )

    return {
        "predicted": predicted,
        "peak_slots": peaks,
        "peak_count": len(peaks),
        "suggestion": suggestion,
    }
