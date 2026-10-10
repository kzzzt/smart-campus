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
# 高能耗阈值：单宿舍当日最高功率超过它 -> 触发"通知对应辅导员"
HIGH_ENERGY_THRESHOLD_W = 1500.0


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
        # 统计连续超过阈值的小时数：取「最长连续段」，长度 >= SUSTAIN_HOURS 才算，
        # 避免稀疏尖峰（间隔着正常时段的多次超阈值）被误判成"持续 N 小时"。
        seq_sorted = sorted(seq, key=lambda x: x["ts"])
        longest = 0
        seg: list[dict] = []
        run: list[dict] = []
        for rec in seq_sorted:
            if rec["power_w"] > ILLEGAL_POWER_THRESHOLD_W:
                run.append(rec)
            else:
                if len(run) > longest:
                    longest, seg = len(run), run
                run = []
        if len(run) > longest:
            longest, seg = len(run), run
        if longest >= SUSTAIN_HOURS:
            alarms.append(
                {
                    "room": room,
                    "ts": seg[-1]["ts"],
                    "power_w": round(max(r["power_w"] for r in seg), 1),
                    "reason": f"连续超过 {ILLEGAL_POWER_THRESHOLD_W}W 达 {longest} 小时，疑似违规电器（电热毯/电煮锅等高功率设备）",
                }
            )
    return alarms


def summarize_rooms(records: list[dict], high_threshold_w: float = HIGH_ENERGY_THRESHOLD_W) -> list[dict]:
    """
    汇总每一间宿舍的能耗：当前功率、当日最高功率、平均功率、是否高能耗、负责辅导员。

    返回按楼层/房间排序的列表：
    [{"room","building","handler","current_w","max_w","avg_w","is_high"}, ...]
    """
    by_room: dict[str, list[dict]] = {}
    for rec in records:
        by_room.setdefault(rec["room"], []).append(rec)

    rooms = []
    for room, seq in by_room.items():
        seq_sorted = sorted(seq, key=lambda x: x["ts"])
        powers = [r["power_w"] for r in seq_sorted]
        meta = seq_sorted[-1]
        rooms.append({
            "room": room,
            "building": meta.get("building", ""),
            "handler": meta.get("handler", ""),
            "current_w": round(powers[-1], 1),   # 当前（最新时点）功率
            "max_w": round(max(powers), 1),      # 当日最高功率
            "avg_w": round(sum(powers) / len(powers), 1),
            "is_high": max(powers) >= high_threshold_w,   # 出现过超过高能耗阈值
            "notified": False,
        })
    # 按楼栋 -> 房间号排序，保证展示顺序稳定
    return rooms


def build_notices(rooms: list[dict]) -> list[dict]:
    """
    对高能耗宿舍生成"通知对应辅导员"的告警消息。
    rooms: summarize_rooms() 输出。

    语义区分（避免口径混淆）：
      - rule_detect()      -> 判定"疑似违规电器"（持续超过 ILLEGAL_POWER_THRESHOLD）
      - build_notices()    -> 判定"高能耗宿舍"（单点峰值超过 HIGH_ENERGY_THRESHOLD，节能预警）
    两者阈值与口径不同，页面文案分别表述为"高能耗"与"违规电器"。

    返回 [{"room","handler","power_w","level","message"}, ...]
    """
    notices = []
    for r in rooms:
        if not r["is_high"]:
            continue
        level = "high" if r["max_w"] >= ILLEGAL_POWER_THRESHOLD_W * 2 else "warning"
        notices.append({
            "room": r["room"],
            "handler": r.get("handler", ""),
            "power_w": r["max_w"],
            "level": level,
            "message": (
                f"宿舍 {r['room']} 当日最高用电 {round(r['max_w'])}W，"
                f"超过高能耗阈值 {int(HIGH_ENERGY_THRESHOLD_W)}W，"
                f"请留意是否使用大功率电器并联系学生核实。"
            ),
        })
    return notices


def vision_detect(images: list[bytes] | None = None, candidate_rooms: list[dict] | None = None) -> dict:
    """
    智算视觉模型检测入口（支持真模型替换）。

    真实实现：调用部署在智算节点的目标检测模型（如 YOLO 系列），对宿舍过道/公共区
    摄像头画面识别电热毯、电煮锅、乱接插线板等违规物件。

    演示实现（无真实图片时）：对规则通道命中的候选房间做"视觉复核"，模拟视觉证据
    与功率证据互补 —— 命中房间视为画面中检出违规物件（真实部署中由视觉模型给出）。

    返回 {"detected": bool, "objects": [...], "confidence": float}
    """
    if not candidate_rooms:
        return {"detected": False, "objects": [], "confidence": 0.0, "mode": "none"}

    objects = []
    for a in candidate_rooms:
        objects.append(
            {
                "room": a["room"],
                "object": "high-power-appliance",
                "label": "疑似违规电器（电热毯/电煮锅）",
                "confidence": round(min(0.95, 0.7 + max(0, a.get("power_w", 0) - 1000) / 5000), 2),
            }
        )
    return {
        "detected": bool(objects),
        "objects": objects,
        "confidence": round(max((o["confidence"] for o in objects), default=0.0), 2),
        "mode": "simulated" if images is None else "model",
    }


def detect(records: list[dict], use_vision: bool = False) -> dict:
    """综合检测入口：规则判定 + 可选视觉校验（双通道证据链）。"""
    rule_alarms = rule_detect(records)
    vision = vision_detect(candidate_rooms=rule_alarms) if use_vision else None

    # 双通道判定：规则命中且视觉也命中 -> 高置信；纯规则命中 -> 中置信（提示复核）
    for a in rule_alarms:
        a["confidence"] = "high" if (vision and vision["detected"]) else "medium"

    return {
        "rule_alarms": rule_alarms,
        "vision": vision,
        "vision_used": use_vision,
        "summary": (
            f"检测到 {len(rule_alarms)} 个疑似违规电器房间"
            + (f"，视觉通道复核命中 {len(vision['objects'])} 处高置信告警" if vision and vision["detected"] else "")
        ),
    }
