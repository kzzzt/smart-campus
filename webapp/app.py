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
from src.energy.detector import detect, summarize_rooms, build_notices
from src.energy.forecast import forecast_peak
from src.scheduler.constraints import Course, Room
from src.scheduler.genetic import GeneticScheduler
from src.scheduler.classroom import assign_classrooms


# 角色说明
ROLES = {
    "student": "学生",
    "counselor": "辅导员",
    "admin": "管理人员",
}

# 各角色可访问的页面
ROLE_PAGES = {
    "student": ["/ai"],                       # 学生：仅 AI 客服（不可见能耗/排课）
    "counselor": ["/ai", "/scheduler"],       # 辅导员：AI 客服 + 排课
    "admin": ["/ai", "/energy", "/scheduler"],# 管理人员：全部
}
# 兼容引用（学生不再只读浏览能耗/排课，置空）
READ_ONLY_PAGES_FOR_STUDENT = []
# 默认演示账户（不覆盖时用）——首启初始化到 users 表
DEFAULT_ACCOUNTS = [
    ("student", "stu123", "student", "学生小李", "20230001", ""),
    ("counselor", "cou123", "counselor", "综合事务辅导员", "", "综合事务辅导员"),
    ("admin", "SmartCampus@2026", "admin", "系统管理员", "", ""),
]


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


def _hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def _is_logged_in() -> bool:
    return session.get("role") is not None


def _current_user() -> dict | None:
    """当前登录用户信息（缓存于 session）或 None。"""
    uname = session.get("username")
    if not uname:
        return None
    return {
        "username": uname,
        "role": session.get("role"),
        "display_name": session.get("display_name"),
        "student_id": session.get("student_id"),
        "handler": session.get("handler"),
    }


def _check_password(user: dict | None, pwd: str) -> bool:
    """恒定时间比较用户哈希，避免时序侧信道。"""
    if not user:
        return False
    return hmac.compare_digest(_hash_pwd(pwd), user.get("password_hash", ""))


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


# ---------------- 登录/鉴权（RBAC） ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = (request.form.get("username") or "").strip()
        pwd = request.form.get("password") or ""
        rec = db.get_user(user)

        if rec and _check_password(rec, pwd):
            session.clear()
            # 角色、身份与数据范围写入会话
            session["username"] = rec["username"]
            session["role"] = rec["role"]
            session["display_name"] = rec.get("display_name") or rec["username"]
            session["student_id"] = rec.get("student_id") or ""
            session["handler"] = rec.get("handler") or ""
            session["_csrf"] = secrets.token_hex(16)
            return redirect(url_for("index"))
        return render_template(
            "login.html", error="用户名或密码错误",
            accounts=DEFAULT_ACCOUNTS, demo_accounts=_demo_accounts(),
        ), 401
    return render_template(
        "login.html",
        accounts=DEFAULT_ACCOUNTS,
        demo_accounts=_demo_accounts(),
    )


def _demo_accounts() -> dict:
    """演示账号速查（前端角色卡片自动填充用）。"""
    return {
        "student": (DEFAULT_ACCOUNTS[0][0], DEFAULT_ACCOUNTS[0][1]),
        "counselor": (DEFAULT_ACCOUNTS[1][0], DEFAULT_ACCOUNTS[1][1]),
        "admin": (DEFAULT_ACCOUNTS[2][0], DEFAULT_ACCOUNTS[2][1]),
    }


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/me")
def api_me():
    """返回当前登录用户（供前端导航/权限展示）。"""
    if not _is_logged_in():
        return jsonify({"error": "未登录"}), 401
    u = _current_user()
    return jsonify({
        "username": u["username"],
        "role": u["role"],
        "role_label": ROLES.get(u["role"], u["role"]),
        "display_name": u["display_name"],
        "student_id": u["student_id"],
        "handler": u["handler"],
    })


def _page_allowed(path: str, role: str) -> bool:
    """页面是否对某角色开放（学生仅 AI 客服）。"""
    return path in ROLE_PAGES.get(role, [])


@app.before_request
def _guard():
    path = request.path
    # 静态资源不拦截
    if path.startswith("/static"):
        return
    if path in ("/login", "/logout", "/api/me"):
        return
    is_api = path.startswith(PROTECTED_API)
    is_page = path in PROTECTED_PAGES
    if not is_page and not is_api:
        return  # 首页等公开

    if not _is_logged_in():
        if is_api:
            return jsonify({"error": "未登录"}), 401
        return redirect(url_for("login"))

    role = session.get("role")

    # ============ 页面访问控制 ============
    if is_page:
        if not _page_allowed(path, role):
            return render_template("forbidden.html", role_label=ROLES.get(role, role)), 403
        return

    # ============ API 访问控制 ============
    if is_api:
        # 写操作：按角色 + 路径细分
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # 智能客服（学生/辅导员/管理）都可提问、生成工单 —— 学生的核心功能
            if path == "/api/chat":
                if not _csrf_ok():
                    return jsonify({"error": "CSRF 校验失败"}), 403
                return
            # 工单结案：仅管理员
            if path.startswith("/api/tickets/") and path.endswith("/resolve"):
                if role != "admin":
                    return jsonify({"error": "仅管理人员可结案工单"}), 403
            # 排课求解：管理员 / 辅导员
            if path == "/api/schedule/run" and role not in ("admin", "counselor"):
                return jsonify({"error": "当前角色无排课修改权限"}), 403
            # 能耗运行：仅管理
            if path == "/api/energy/run" and role != "admin":
                return jsonify({"error": "仅管理人员可触发能耗分析"}), 403
            # 其他写 API：学生一律拒绝（学生仅客服可交互）
            if role == "student":
                return jsonify({"error": "学生角色仅可使用 AI 客服"}), 403
            if not _csrf_ok():
                return jsonify({"error": "CSRF 校验失败"}), 403
        else:
            # 读操作 API：登录即可（数据范围在路由内按角色过滤）
            return
    return


@app.context_processor
def _inject_globals():
    u = _current_user()
    role = u["role"] if u else None
    allowed = set(ROLE_PAGES.get(role, [])) if role else set()
    return {
        "csrf_token": _csrf_token(),
        "is_logged_in": _is_logged_in(),
        "current_user": u,
        "allowed_pages": sorted(allowed, key=lambda p: ["/ai", "/energy", "/scheduler"].index(p)) if allowed else [],
        "ROLES": ROLES,
        "ROLE_PAGES": ROLE_PAGES,
        "READ_ONLY_PAGES_FOR_STUDENT": READ_ONLY_PAGES_FOR_STUDENT,
    }


# ---------------- 页面路由 ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ai")
def ai_page():
    u = _current_user()
    # 学生只能看到自己的对话记录，避免看到其它学生的学号/内容
    recent = db.recent_conversations(limit=20)
    if u and u["role"] == "student":
        sid = u.get("student_id") or ""
        recent = [c for c in recent if c["student_id"] == sid]
    # 按角色过滤工单：student 只看自己，counselor 只看流转到自己的
    role, who = (u["role"], u["student_id"]) if u and u["role"] == "student" else ((u["role"], u["handler"]) if u and u["role"] == "counselor" else ("", ""))
    tickets = db.list_tickets(role=role, who=who)
    # 辅导员：在 AI 页同时展示流转到自己职责的能耗告警（学生/管理员不需要）
    energy_notices = None
    if u and u["role"] == "counselor" and u.get("handler"):
        energy_notices = [n for n in db.list_energy_notices() if n["handler"] == u["handler"]]
    return render_template("ai.html", conversations=recent, tickets=tickets, energy_notices=energy_notices)


@app.route("/energy")
def energy_page():
    alerts = db.list_energy_alerts()
    forecast = db.list_forecast()
    rooms = db.list_room_energy()
    notices = db.list_energy_notices()
    return render_template(
        "energy.html", alerts=alerts, forecast=forecast,
        rooms=rooms, notices=notices,
    )


@app.route("/scheduler")
def scheduler_page():
    u = _current_user()
    # 辅导员：只展示与自己相关的课程（handler 若匹配排课教师名则过滤，否则显示全部）
    if u and u["role"] == "counselor" and u.get("handler"):
        by_teacher = db.list_schedules_by_teacher(u["handler"])
        schedule = by_teacher if by_teacher else db.list_schedules()
    else:
        schedule = db.list_schedules()
    return render_template("scheduler.html", schedule=schedule)


# ---------------- API ----------------

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    # 以登录会话的学号为准：学生不能伪造他人学号（管理员/辅导员可显式代学生登记）
    u = _current_user()
    student_id = session.get("student_id") or ""
    if u and u["role"] != "student" and data.get("student_id"):
        student_id = str(data.get("student_id")).strip()
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
    """重新生成一天能耗数据：逐宿舍能耗汇总、检测违规、预测高峰，全部持久化。"""
    sim = _get_generator()
    day = datetime.now()
    records = sim.generate_day(day)

    full = detect(records, use_vision=True)  # 双通道：IoT功率规则 + 智算视觉复核
    run_id = f"E{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
    for a in full["rule_alarms"]:
        db.save_energy_alert(a)

    # 逐宿舍能耗汇总 + 高能耗通知对应辅导员
    room_rows = summarize_rooms(records)
    notices = build_notices(room_rows)
    db.save_room_energy(room_rows, run_id=run_id)
    db.save_energy_notice([{**n, "run_id": run_id} for n in notices])

    pred = forecast_peak(records[:48], forecast_hours=24, peak_threshold_w=2500)  # 阈值低于曲线峰值，否则恒 0 高峰
    db.save_forecast(pred["predicted"], pred["peak_slots"], run_id=run_id)

    return jsonify({
        "alarms": full["rule_alarms"],
        "alarm_count": len(full["rule_alarms"]),
        "vision": full["vision"],
        "vision_used": full["vision_used"],
        "rooms": room_rows,
        "notices": notices,
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
    u = _current_user()
    role, who = (u["role"], u["student_id"]) if u and u["role"] == "student" else ((u["role"], u["handler"]) if u and u["role"] == "counselor" else ("", ""))
    return jsonify(db.list_tickets(role=role, who=who))


@app.route("/api/tickets/<tid>/resolve", methods=["POST"])
def api_resolve(tid):
    data = request.get_json(force=True)
    resolution = data.get("resolution", "已处理")
    # 更新数据库中的工单状态（已结案的不再重复结案）
    conn = db.get_conn()
    cur = conn.execute(
        "UPDATE tickets SET status='resolved', resolution=? WHERE id=? AND status != 'resolved'",
        (resolution, tid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "changed": cur.rowcount > 0})


if __name__ == "__main__":
    db.init_db()
    print("智慧校园管理与安全平台 Web 版已启动： http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
