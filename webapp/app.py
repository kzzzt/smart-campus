"""
Web 应用 —— 智慧校园管理与安全平台（可交互版）。

提供 Web 界面，将三大子系统整合为可操作应用：
    - 主页 / 三大功能页
    - AI 客服问答（规则引擎，可后续替换为真实大模型）
    - 能耗安全监控与告警
    - 智能排课与教室调度

启动：python webapp/app.py   ->   http://127.0.0.1:5000
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify, redirect, url_for

from webapp import db
from src.ai_service.bot import CampusAIBot
from src.energy.simulator import PowerySimulator
from src.energy.detector import detect
from src.energy.forecast import forecast_peak
from src.scheduler.constraints import Course, Room
from src.scheduler.genetic import GeneticScheduler
from src.scheduler.classroom import assign_classrooms


app = Flask(__name__)

# 全局会话
_bot = CampusAIBot()
_generator = None  # 惰性初始化


def _get_generator():
    global _generator
    if _generator is None:
        _generator = PowerySimulator(room_count=8, seed=2024)
    return _generator


# ---------------- 页面路由 ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ai")
def ai_page():
    recent = db.recent_conversations(limit=20)
    tickets = db.list_tickets()
    return render_template("ai.html", conversations=recent, tickets=tickets)


@app.route("/energy")
def energy_page():
    alerts = db.list_energy_alerts()
    forecast = db.list_forecast()
    return render_template("energy.html", alerts=alerts, forecast=forecast)


@app.route("/scheduler")
def scheduler_page():
    schedule = db.list_schedules()
    return render_template("scheduler.html", schedule=schedule)


# ---------------- API ----------------

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    student_id = data.get("student_id", "")
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"error": "消息不能为空"}), 400

    result = _bot.handle(msg, student_id=student_id)
    # 持久化
    db.save_conversation({
        "student_id": student_id,
        "input": msg,
        "intent": result["intent"],
        "confidence": result["confidence"],
        "answer": result["answer"],
        "needs_human": result["needs_human"],
    })
    if result["ticket"]:
        # 重新构造 Ticket 对象以保存（简化：从结果字典重建）
        from src.ai_service.ticket import Ticket
        t = Ticket(
            ticket_id=result["ticket"]["id"],
            intent=result["intent"],
            student_desc=result["input"],
            slots=result["ticket"]["slots"],
            handler=result["ticket"]["handler"],
            status="processing",
        )
        db.save_ticket(t)
        result["ticket"]["status"] = "processing"
    return jsonify(result)


@app.route("/api/energy/run", methods=["POST"])
def api_energy_run():
    """重新生成一天能耗数据，检测违规并预测高峰，全部持久化。"""
    sim = _get_generator()
    day = datetime.now()
    records = sim.generate_day(day)

    full = detect(records, use_vision=False)
    for a in full["rule_alarms"]:
        db.save_energy_alert(a)

    pred = forecast_peak(records[:48], forecast_hours=24, peak_threshold_w=5000)
    db.save_forecast(pred["predicted"], pred["peak_slots"])

    return jsonify({
        "alarms": full["rule_alarms"],
        "alarm_count": len(full["rule_alarms"]),
        "peak_count": pred["peak_count"],
        "suggestion": pred["suggestion"],
    })


@app.route("/api/schedule/run", methods=["POST"])
def api_schedule_run():
    """运行遗传算法排课并保存结果。"""
    courses = [
        Course("C1", "数据结构", "张老师", 60, 4, requires_computer=True),
        Course("C2", "大学英语", "李老师", 80, 4),
        Course("C3", "高等数学", "王老师", 90, 4),
        Course("C4", "计算机实验", "赵老师", 40, 2, requires_computer=True),
        Course("C5", "物理实验", "孙老师", 45, 2),
        Course("C6", "线性代数", "周老师", 70, 4),
    ]
    rooms = [
        Room("R1", "机房A", 60, has_computer=True, room_type="computer"),
        Room("R2", "机房B", 50, has_computer=True, room_type="computer"),
        Room("R3", "实验室1", 45, has_computer=False, room_type="lab"),
        Room("R4", "大教室1", 100, has_computer=False, room_type="normal"),
        Room("R5", "大教室2", 120, has_computer=False, room_type="normal"),
        Room("R6", "普通教室1", 60, has_computer=False, room_type="normal"),
    ]
    sched = GeneticScheduler(courses, rooms, pop_size=30, generations=40)
    result = sched.solve()
    db.save_schedule(result["schedule"])
    return jsonify({"schedule": result["schedule"], "fitness": result["fitness"]})


@app.route("/api/tickets", methods=["GET"])
def api_tickets():
    return jsonify(db.list_tickets())


@app.route("/api/tickets/<tid>/resolve", methods=["POST"])
def api_resolve(tid):
    data = request.get_json(force=True)
    resolution = data.get("resolution", "已处理")
    # 更新数据库中的工单状态
    conn = db.get_conn()
    conn.execute(
        "UPDATE tickets SET status='resolved', resolution=? WHERE id=?",
        (resolution, tid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    db.init_db()
    print("智慧校园管理与安全平台 Web 版已启动： http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
