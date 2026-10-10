"""
IoT 数据模拟器。

在没有真实物联网设备的环境下，用它生成接近真实的学生宿舍 / 教学楼用电数据，
供能耗预警与用电高峰预测模块使用。接入真实 IoT 网关后，只需把数据源替换为
真实上报序列即可，接口保持一致。

宿舍维度：精确到每一间宿舍（楼栋-楼层-房间号），并关联负责该宿舍的辅导员，
用于"高能耗先通知对应辅导员"的告警闭环。
"""

import math
import random
from datetime import datetime, timedelta

# 楼栋名 -> 楼内房间数（模拟两栋宿舍楼，共 12 间宿舍）
BUILDINGS = {
    "1号宿舍楼": 6,   # 101~106
    "2号宿舍楼": 6,   # 201~206
}

# 宿舍楼辅导员映射：每栋楼由一名辅导员负责（演示数据）
HANDLER_BY_BUILDING = {
    "1号宿舍楼": "1号楼生活辅导员",
    "2号宿舍楼": "2号楼生活辅导员",
}


class PowerySimulator:
    """
    宿舍 / 教学楼用电数据模拟器。

    每个房间在一段时间内生成：
      - 电力功率时间序列（随一天作息波动，可叠加"违规电器"特征）
      - 是否违规（大功率电器如电热毯/电煮锅）
      - 实验室安全隐患标记（可选）
    """

    def __init__(self, room_count: int = 5, seed: int = 42, base_power: float = 500.0):
        self.room_count = room_count
        self.base_power = base_power
        random.seed(seed)
        # 预生成房间列表（真实宿舍编号 + 负责辅导员）
        self._rooms = self._build_rooms()

    def _build_rooms(self) -> list[dict]:
        rooms = []
        idx = 0
        for building, n in BUILDINGS.items():
            base = int(building[0]) * 100  # 1号->100, 2号->200
            for i in range(1, n + 1):
                rooms.append({
                    "room": f"{building}-{base + i}",
                    "building": building,
                    "handler": HANDLER_BY_BUILDING[building],
                })
                idx += 1
        return rooms[: max(self.room_count, 1)]

    def room_list(self) -> list[dict]:
        """返回宿舍元信息（编号 + 楼栋 + 负责辅导员）。"""
        return list(self._rooms)

    def generate_day(self, day: datetime) -> list[dict]:
        """生成某一天所有房间的逐小时用电序列。"""
        records = []
        for meta in self._rooms:
            illegal = random.random() < 0.3  # 30% 房间存在违规电器（模拟）
            room = meta["room"]
            for hour in range(24):
                # 基础负荷：随作息（上课时段低、晚上高）
                diurnal = 0.6 + 0.6 * math.exp(-((hour - 21) ** 2) / 12)
                base = self.base_power * diurnal * random.uniform(0.85, 1.15)
                watt = base
                # 叠加违规电器特征：恒定大功率（如电热毯 ~1500W）长时间开启
                if illegal and 18 <= hour <= 23:
                    watt += 1500 + random.uniform(0, 200)
                records.append(
                    {
                        "room": room,
                        "building": meta["building"],
                        "handler": meta["handler"],
                        "ts": day + timedelta(hours=hour),
                        "power_w": round(watt, 1),
                    }
                )
        return records
