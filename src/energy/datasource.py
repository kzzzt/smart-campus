"""
真实数据源接入 —— 让能耗模块读取"真实"数据而不只是模拟。

提供两类数据源，输出与 simulator.generate_day() 兼容的记录结构：
    {"room", "ts", "power_w", "building", "handler"}

1. read_csv(path)：读取 `ts,power_w` 两列（或带 building/handler 列）的公开负荷数据(如 UK-DALE)，
   规整为一个房间的时序序列；
2. read_mqtt(broker, topic)：订阅 MQTT 主题，收一条 JSON 测量（{"room","ts","power_w"}），
   需安装 paho-mqtt。

自动降级：缺依赖/连接失败会抛出异常，调用方（web/demo）可捕获并按需回退到模拟器。
接入点：把返回值交给 src/energy/detector.detect() / forecast_peak() 即可复用全部告警与预测。

用法示例：
    python -m src.energy.datasource sample.csv
"""
from __future__ import annotations

import csv
import os.path
import sys
from datetime import datetime, timedelta


def read_csv(
    path: str,
    room: str = "1号宿舍楼-101",
    building: str = "1号宿舍楼",
    handler: str = "1号楼生活辅导员",
    hours: int = 24,
) -> list[dict]:
    """读取 CSV 时序数据（至少含 ts,power_w 两列），规整为 24 小时记录。

    CSV 支持：`ts,power_w[,building,handler]`；ts 可为 ISO 时间或留空（自动补时间轴）。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据文件不存在：{path}")
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in csv.DictReader(f):
            rows.append({
                "ts": (line.get("ts") or "").strip(),
                "power_w": float(line.get("power_w") or 0),
                "building": (line.get("building") or building).strip(),
                "handler": (line.get("handler") or handler).strip(),
            })

    records = []
    base = datetime.now().replace(second=0, microsecond=0)
    n = min(len(rows), max(hours, 1))
    for i, r in enumerate(rows[:n]):
        ts = r["ts"]
        try:
            ts = datetime.fromisoformat(ts) if ts else base - timedelta(hours=n - i)
        except ValueError:
            ts = base - timedelta(hours=n - i)
        records.append({
            "room": room,
            "ts": ts,
            "power_w": round(r["power_w"], 1),
            "building": r["building"],
            "handler": r["handler"],
        })
    return records


def read_mqtt(broker: str, topic: str, timeout: float = 5.0) -> list[dict]:
    """订阅 MQTT 主题，等待并返回一条测量（JSON: {"room","ts","power_w"}）。需 paho-mqtt。"""
    import json
    import time

    import paho.mqtt.client as mqtt

    got: list[dict] = []

    def _on_message(client, _userdata, msg):
        try:
            d = json.loads(msg.payload.decode())
            got.append({
                "room": d.get("room", "未知房间"),
                "ts": datetime.now(),
                "power_w": float(d.get("power_w", 0)),
            })
        except Exception:
            pass
        client.disconnect()

    client = mqtt.Client()
    client.on_message = _on_message
    client.connect(broker, 1883, 60)
    client.subscribe(topic)
    client.loop_start()
    deadline = time.time() + timeout
    while not got and time.time() < deadline:
        time.sleep(0.1)
    client.loop_stop()
    return got


def _demo(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    records = read_csv(argv[0])
    print(f"读取 {len(records)} 条记录，示例：{records[0]}")
    print("可直接交给 detect() / forecast_peak() 使用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
