"""
SQLite 数据库访问层。

为三大子系统提供持久化存储：
    - conversations / tickets   : AI 客服对话与工单流转
    - energy_alerts             : 能耗安全告警记录
    - schedules                 : 排课方案结果

使用 Python 内置 sqlite3，无需额外依赖，便于部署与演示。
"""

import os
import sqlite3
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(__file__), "campus.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    input TEXT,
    intent TEXT,
    confidence REAL,
    answer TEXT,
    needs_human INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    intent TEXT,
    student_desc TEXT,
    slots TEXT,
    handler TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    resolution TEXT
);

CREATE TABLE IF NOT EXISTS energy_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room TEXT,
    ts TEXT,
    power_w REAL,
    reason TEXT,
    confidence TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS energy_forecast (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    slot_ts TEXT,
    power_w REAL,
    is_peak INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    time_slot TEXT,
    course TEXT,
    teacher TEXT,
    room TEXT,
    room_type TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def save_conversation(row: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO conversations
           (student_id, input, intent, confidence, answer, needs_human)
           VALUES (?,?,?,?,?,?)""",
        (row.get("student_id"), row.get("input"), row.get("intent"),
         row.get("confidence"), row.get("answer"),
         1 if row.get("needs_human") else 0),
    )
    conn.commit()
    conn.close()


def save_ticket(ticket) -> None:
    import json
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO tickets
           (id, intent, student_desc, slots, handler, status, resolution)
           VALUES (?,?,?,?,?,?,?)""",
        (ticket.ticket_id, ticket.intent, ticket.student_desc,
         json.dumps(ticket.slots, ensure_ascii=False),
         ticket.handler, ticket.status, ticket.resolution),
    )
    conn.commit()
    conn.close()


def save_energy_alert(a: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO energy_alerts (room, ts, power_w, reason, confidence)
           VALUES (?,?,?,?,?)""",
        (a["room"], a["ts"].strftime("%Y-%m-%d %H:%M:%S"),
         a["power_w"], a["reason"], a.get("confidence", "medium")),
    )
    conn.commit()
    conn.close()


def save_forecast(predicted: list, peaks: list, run_id: str | None = None) -> None:
    conn = get_conn()
    peak_ids = {p["ts"].strftime("%Y-%m-%d %H:%M:%S") for p in peaks}
    for p in predicted:
        ts = p["ts"].strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO energy_forecast (run_id, slot_ts, power_w, is_peak)
               VALUES (?,?,?,?)""",
            (run_id, ts, p["power_w"], 1 if ts in peak_ids else 0),
        )
    conn.commit()
    conn.close()


def save_schedule(rows: list, run_id: str | None = None) -> None:
    conn = get_conn()
    for r in rows:
        conn.execute(
            """INSERT INTO schedules (run_id, time_slot, course, teacher, room, room_type)
               VALUES (?,?,?,?,?,?)""",
            (run_id, r.get("time_slot"), r.get("course"), r.get("teacher"),
             r.get("room"), r.get("room_type")),
        )
    conn.commit()
    conn.close()


# ---------------- 查询 ----------------

def recent_conversations(limit: int = 50) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_tickets(status: str | None = None) -> list:
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_energy_alerts(limit: int = 50) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM energy_alerts ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_forecast(limit: int = 48) -> list:
    conn = get_conn()
    # 只返回最新一次 run 的预测，避免多次运行的 24h 序列互相污染展示
    rows = conn.execute(
        """SELECT * FROM energy_forecast
           WHERE run_id = (SELECT run_id FROM energy_forecast ORDER BY id DESC LIMIT 1)
           ORDER BY id ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_schedules(limit: int = 100) -> list:
    conn = get_conn()
    # 只返回最新一次 run 的排课结果
    rows = conn.execute(
        """SELECT * FROM schedules
           WHERE run_id = (SELECT run_id FROM schedules ORDER BY id DESC LIMIT 1)
           ORDER BY id ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
