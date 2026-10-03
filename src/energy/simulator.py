"""
IoT 数据模拟器。

在没有真实物联网设备的环境下，用它生成接近真实的学生宿舍 / 教学楼用电数据，
供能耗预警与用电高峰预测模块使用。接入真实 IoT 网关后，只需把数据源替换为
真实上报序列即可，接口保持一致。
"""

import math
import random
from datetime import datetime, timedelta


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

    def generate_day(self, day: datetime) -> list[dict]:
        """生成某一天所有房间的逐小时用电序列。"""
        records = []
        for r in range(self.room_count):
            illegal = random.random() < 0.3  # 30% 房间存在违规电器（模拟）
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
                        "room": f"room-{r:02d}",
                        "ts": day + timedelta(hours=hour),
                        "power_w": round(watt, 1),
                    }
                )
        return records
