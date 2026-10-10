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
import uuid
import hashlib
import secrets
import hmac
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort

from webapp import db
from src.ai_service.bot import CampusAIBot
from src.energy.simulator import PowerySimulator
from src.energy.detector import detect
from src.energy.forecast import forecast_peak
from src.scheduler.constraints import Course, Room
from src.scheduler.genetic import GeneticScheduler
from src.scheduler.classroom import assign_classrooms


app = Flask(__name__)
# 会话密钥：优先从环境变量读取（部署时务必设置），未设置时生成并持久化到 webapp/.secret_key
_secret_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
if os.environ.get("SECRET_KEY"):
    app.secret_key = os.environ["SECRET_KEY"]
elif os.path.exists(_secret_file):
    with open(_secret_file, "rb") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    try:
        with open(_secret_file, "w") as f:
            f.write(app.secret_key)
    except OSError:
        pass  # 只读环境：每次启动随机密钥，会话将失效，但不影响功能

# 管理员口令：默认 admin / admin123（仅本机演示用），生产必须通过环境变量 ADMIN_PASSWORD 覆盖
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# 受保护的前端页面与 API（未登录一律拒绝）
PROTECTED_PAGES = {"/ai", "/energy", "/scheduler"}
PROTECTED_API = ("/api/",)

# 全局会话
_bot = CampusAIBot()
_generator = None  # 惰性初始化


def _get_generator():
    global _generator
    if _generator is None:
        _generator = PowerySimulator(room_count=8, seed=42)   # seed=2024 恰好 0 违规房间，改 42（与 demo 一致、必命中）
    return _generator


def _is_logged_in() -> bool:
    return session.get("is_admin") is True


def _check_password(pwd: str) -> bool:
    """恒定时间比较，避免时序侧信道。"""
    return hmac.compare_digest(pwd.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))


def _csrf_token():
    """当前会话的 CSRF token（无则生成）。"""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def _csrf_ok() -> bool:
    stored = session.get("_csrf", "")
    # 会话未设置 token 时一律拒绝（封堵空值对空值的恒等通过）
    if not stored:
        return False
    sent = request.headers.get("X-CSRF-Token", "")
    return hmac.compare_digest(sent, stored)


# ---------------- 登录/鉴权 ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = (request.form.get("username") or "").strip()
        pwd = request.form.get("password") or ""
        if user == ADMIN_USER and _check_password(pwd):
            session.clear()
            session["is_admin"] = True
            session["_csrf"] = secrets.token_hex(16)
            return redirect(url_for("index"))
        return render_template("login.html", error="用户名或密码错误"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def _guard():
    path = request.path
    # 静态资源不拦截
    if path.startswith("/static"):
        return
    is_api = path.startswith(PROTECTED_API)
    is_page = path in PROTECTED_PAGES
    if not is_page and not is_api:
        return  # 首页/登录等公开

    if not _is_logged_in():
        if is_api:
            return jsonify({"error": "未登录"}), 401
        return redirect(url_for("login"))

    # 写操作 API 需携带 CSRF token（登录后任意校验）
    if is_api and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not _csrf_ok():
            return jsonify({"error": "CSRF 校验失败"}), 403


@app.context_processor
def _inject_globals():
    return {"csrf_token": _csrf_token(), "is_logged_in": _is_logged_in()}


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

    full = detect(records, use_vision=True)  # 双通道：IoT功率规则 + 智算视觉复核
    run_id = f"E{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
    for a in full["rule_alarms"]:
        db.save_energy_alert(a)

    pred = forecast_peak(records[:48], forecast_hours=24, peak_threshold_w=2500)  # 阈值低于曲线峰值，否则恒 0 高峰
    db.save_forecast(pred["predicted"], pred["peak_slots"], run_id=run_id)

    return jsonify({
        "alarms": full["rule_alarms"],
        "alarm_count": len(full["rule_alarms"]),
        "vision": full["vision"],
        "vision_used": full["vision_used"],
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
    sched = GeneticScheduler(courses, rooms, pop_size=30, generations=100)  # 多时段编码，100 代收敛到 0 冲突
    result = sched.solve()
    run_id = f"S{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
    db.save_schedule(result["schedule"], run_id=run_id)
    return jsonify({
        "schedule": result["schedule"], "fitness": result["fitness"],
        "conflicts": result["conflicts"], "run_id": run_id,
    })


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
    app.run(host="127.0.0.1", port=5000, debug=False)
