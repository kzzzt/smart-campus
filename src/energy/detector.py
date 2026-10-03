"""
违规电器 / 安全隐患检测模块。

结合 IoT 数据（功率特征）与智算视觉模型（图像识别违规电器）双重判定：
  - 规则判定：功率异常持续（超过阈值且持续多时点） -> 判为疑似违规；
  - 视觉判定：调用视觉模型对摄像头画面/照片识别违规电器（初稿为接口占位）。

双重判定可有效降低单通道误报。
"""

# 违规电器典型功率阈值（W）
ILLEGAL_POWER_THRESHOLD_W = 1000.0
# 持续时长阈值（小时），超过才算"疑似违规"而非瞬时杂波
SUSTAIN_HOURS = 2


def rule_detect(records: list[dict]) -> list[dict]:
    """
    基于 IoT 功率序列的规则判定。
    records: simulator.generate_day() 产生的某一房间序列（带 hour 信息）。

    返回可疑记录列表 [{"room","ts","power_w","reason"}, ...]
    """
    alarms = []
    # 按房间分组
    by_room: dict[str, list[dict]] = {}
    for rec in records:
        by_room.setdefault(rec["room"], []).append(rec)

    for room, seq in by_room.items():
        # 统计连续超过阈值的小时数
        over_hours = []
        for rec in sorted(seq, key=lambda x: x["ts"]):
            if rec["power_w"] > ILLEGAL_POWER_THRESHOLD_W:
                over_hours.append(rec)
        if len(over_hours) >= SUSTAIN_HOURS:
            alarms.append(
                {
                    "room": room,
                    "ts": over_hours[-1]["ts"],
                    "power_w": round(max(r["power_w"] for r in over_hours), 1),
                    "reason": f"持续超过 {ILLEGAL_POWER_THRESHOLD_W}W 达 {len(over_hours)} 小时，疑似违规电器（电热毯/电煮锅等高功率设备）",
                }
            )
    return alarms


def vision_detect(image: bytes | None = None) -> dict:
    """
    智算视觉模型检测入口（接口占位）。
    真实实现：调用目标检测模型（如 YOLO 系列部署在智算节点），识别画面中的
    电热毯、电煮锅、违规接线等。初稿返回固定结构示意。

    返回 {"detected": bool, "objects": [...], "confidence": float}
    """
    # 示意：无真实图像时返回未检测
    return {"detected": False, "objects": [], "confidence": 0.0}


def detect(records: list[dict], use_vision: bool = False) -> dict:
    """综合检测入口：规则判定 + 可选视觉校验。"""
    rule_alarms = rule_detect(records)
    vision = vision_detect() if use_vision else None

    # 双重判定：规则命中且视觉也命中 -> 高置信；规则命中 -> 中置信（提示复核）
    for a in rule_alarms:
        a["confidence"] = "high" if (vision and vision["detected"]) else "medium"

    return {
        "rule_alarms": rule_alarms,
        "vision": vision,
        "summary": (
            f"检测到 {len(rule_alarms)} 个疑似违规电器房间"
            + (f"，{vision['objects']}" if vision and vision["detected"] else "")
        ),
    }
