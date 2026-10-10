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
    resolution TEXT,
    student_id TEXT
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

CREATE TABLE IF NOT EXISTS room_energy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    room TEXT,
    building TEXT,
    handler TEXT,              -- 本宿舍对应辅导员（用于高能耗告警）
    current_w REAL,            -- 当前/最新功率
    max_w REAL,                -- 当日最高功率
    avg_w REAL,
    is_high INTEGER DEFAULT 0, -- 是否高能耗（需告警）
    notified INTEGER DEFAULT 0,-- 是否已向辅导员发警告
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS energy_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    room TEXT,
    handler TEXT,              -- 收到警告的辅导员职责名
    power_w REAL,
    level TEXT,                -- high / warning
    message TEXT,
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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,            -- student / counselor / admin
    display_name TEXT,
    student_id TEXT,               -- 学生学号（角色=student 时）
    handler TEXT                   -- 辅导员职责名（角色=counselor 时）
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
    # 幂等写入默认 RBAC 账户：逐条 INSERT OR IGNORE，新增账号(如楼栋辅导员)
    # 会自动补进已有的旧库（不再要求 users 表为空）
    from .seed_users import SEED_USERS
    for u in SEED_USERS:
        conn.execute(
            """INSERT OR IGNORE INTO users
               (username, password_hash, role, display_name, student_id, handler)
               VALUES (?,?,?,?,?,?)""",
            (u["username"], u["password_hash"], u["role"], u["display_name"],
             u.get("student_id"), u.get("handler")),
        )
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
           (id, intent, student_desc, slots, handler, status, resolution, student_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ticket.ticket_id, ticket.intent, ticket.student_desc,
         json.dumps(ticket.slots, ensure_ascii=False),
         ticket.handler, ticket.status, ticket.resolution,
         getattr(ticket, "student_id", None)),
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


def list_tickets(status: str | None = None, role: str = "", who: str = "") -> list:
    conn = get_conn()
    sql = "SELECT * FROM tickets WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    # 数据范围：student 只看自己，counselor 只看 callback 到自己职责的工单
    if role == "student" and who:
        sql += " AND student_id=?"
        args.append(who)
    elif role == "counselor" and who:
        sql += " AND handler=?"
        args.append(who)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, args).fetchall()
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


def list_schedules_by_teacher(teacher: str, limit: int = 200) -> list:
    """返回最新一次排课结果中，某位教师相关的课程行。未匹配则返回空列表。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM schedules
           WHERE run_id=(SELECT run_id FROM schedules ORDER BY id DESC LIMIT 1)
             AND teacher=?
           ORDER BY id ASC LIMIT ?""",
        (teacher, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- 账户（RBAC） ----------------

def get_user(username: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_teachers() -> list[str]:
    """排课数据中实际出现的全部教师名（用于辅导员筛选与自己相关课程）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT teacher FROM schedules ORDER BY teacher"
    ).fetchall()
    conn.close()
    return [r["teacher"] for r in rows if r["teacher"]]


# ---------------- 宿舍能耗（每宿舍当前/最高 + 辅导员通知） ----------------

def save_room_energy(rows: list, run_id: str | None = None) -> None:
    conn = get_conn()
    for r in rows:
        conn.execute(
            """INSERT INTO room_energy
               (run_id, room, building, handler, current_w, max_w, avg_w, is_high, notified)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, r.get("room"), r.get("building"), r.get("handler"),
             r.get("current_w"), r.get("max_w"), r.get("avg_w"),
             1 if r.get("is_high") else 0,
             1 if r.get("notified") else 0),
        )
    conn.commit()
    conn.close()


def save_energy_notice(notices: list) -> None:
    conn = get_conn()
    for n in notices:
        conn.execute(
            """INSERT INTO energy_notices (run_id, room, handler, power_w, level, message)
               VALUES (?,?,?,?,?,?)""",
            (n.get("run_id"), n.get("room"), n.get("handler"),
             n.get("power_w"), n.get("level"), n.get("message")),
        )
    conn.commit()
    conn.close()


def list_room_energy(limit: int = 100) -> list:
    """最新一次运行的全部宿舍能耗明细（按建筑-房间排序）。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM room_energy
           WHERE run_id=(SELECT run_id FROM room_energy ORDER BY id DESC LIMIT 1)
           ORDER BY id ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_energy_notices(limit: int = 30) -> list:
    """最新一次运行的辅导员告警通知。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM energy_notices
           WHERE run_id=(SELECT run_id FROM energy_notices ORDER BY id DESC LIMIT 1)
           ORDER BY id ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
