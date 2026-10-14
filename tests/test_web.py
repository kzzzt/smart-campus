"""Web API 集成测试：鉴权 / CSRF / 三大子系统 API 端到端（Flask test client）。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from webapp import db
from webapp.app import app


@pytest.fixture()
def client(tmp_path):
    # 使用临时数据库，避免污染真实 campus.db
    old_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    db.init_db()
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as c:
        yield c
    db.DB_PATH = old_path


def _login(client):
    return client.post("/login", data={"username": "admin", "password": "SmartCampus@2026"})


def _login_as(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def _csrf_from_session(client):
    with client.session_transaction() as s:
        return s.get("_csrf")


def _csrf_from(client, page="/ai"):
    r = client.get(page)
    html = r.get_data(as_text=True)
    import re
    m = re.search(r"X-CSRF-Token':'([0-9a-f]{32})'", html)
    return m.group(1) if m else None


def test_pages_redirect_when_not_logged_in(client):
    for p in ("/ai", "/energy", "/scheduler"):
        r = client.get(p)
        assert r.status_code == 302  # 重定向到登录


def test_api_rejects_when_not_logged_in(client):
    r = client.post("/api/energy/run")
    assert r.status_code == 401


def test_wrong_password_rejected(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_login_grants_access(client):
    assert _login(client).status_code == 302
    for p in ("/ai", "/energy", "/scheduler"):
        assert client.get(p).status_code == 200


# ---------------- RBAC 角色隔离 ----------------

def test_student_only_ai_page(client):
    """学生仅能访问 AI 客服页，能耗/排课页一律 403（不可见其他接口）。"""
    _login_as(client, "student", "stu123")
    assert client.get("/ai").status_code == 200
    assert client.get("/energy").status_code == 403
    assert client.get("/scheduler").status_code == 403


def test_student_can_chat_and_create_ticket(client):
    """学生可提问并生成工单（AI 客服是其核心功能），但不可运行能耗/排课。"""
    _login_as(client, "student", "stu123")
    tok = _csrf_from_session(client)
    assert tok
    r = client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 200
    assert r.get_json()["needs_human"] is True
    # 学生不可触发能耗/排课写操作
    assert client.post("/api/energy/run", headers={"X-CSRF-Token": tok}).status_code == 403
    assert client.post("/api/schedule/run", headers={"X-CSRF-Token": tok}).status_code == 403


def test_counselor_only_ai_and_reply(client):
    """辅导员：AI 客服 + 工单回复；可只读查看能耗/排课页，但运行（写操作）被拒。"""
    _login_as(client, "counselor", "cou123")
    assert client.get("/ai").status_code == 200
    assert client.get("/scheduler").status_code == 200
    assert client.get("/energy").status_code == 200
    assert client.post("/api/schedule/run").status_code == 403
    assert client.post("/api/energy/run").status_code == 403


def test_counselor_sees_only_own_energy_and_schedule(client):
    """辅导员能耗/排课页面：只看到本人负责的宿舍楼栋与本人相关课程（数据范围隔离）。"""
    # 先用 admin 生成一份能耗 + 排课数据
    _login_as(client, "admin", "SmartCampus@2026")
    etok = _csrf_from(client, "/energy")
    client.post("/api/energy/run", headers={"X-CSRF-Token": etok})
    stok = _csrf_from(client, "/scheduler")
    client.post("/api/schedule/run", headers={"X-CSRF-Token": stok})
    client.post("/logout")

    # 1号楼生活辅导员：只看 1号宿舍楼 的宿舍；排课页无权限（仅教师视角可见）
    _login_as(client, "f1", "cou123")
    html = client.get("/energy").get_data(as_text=True)
    assert "1号宿舍楼-" in html
    assert "2号宿舍楼-" not in html
    assert client.get("/scheduler").status_code == 403
    # 排课页只显示本人课程（张老师 -> 数据结构）；能耗页无权限（仅告警/业务视角可见）
    _login_as(client, "t_zhang", "cou123")
    sh = client.get("/scheduler").get_data(as_text=True)
    assert "数据结构" in sh
    assert "大学英语" not in sh
    assert client.get("/energy").status_code == 403


def test_counselor_can_reply_own_ticket(client):
    """流转到辅导员职责（综合事务辅导员）的工单，该辅导员可回复；
    其他职责辅导员（学籍与请假业务辅导员）回复被拒 403。"""
    _login_as(client, "admin", "SmartCampus@2026")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )  # other -> 综合事务辅导员
    tid = db.list_tickets(role="", who="")[0]["id"]
    assert tid

    # 综合事务辅导员（counselor 账号）可回复自己职责的工单
    client.post("/logout")
    _login_as(client, "counselor", "cou123")
    tok2 = _csrf_from_session(client)
    r = client.post(f"/api/tickets/{tid}/reply", json={"reply": "已联系后勤维修，今晚上门处理"},
                    headers={"X-CSRF-Token": tok2})
    assert r.status_code == 200
    got = r.get_json()["ticket"]
    assert got["reply"] == "已联系后勤维修，今晚上门处理"
    assert got["status"] == "processing"

    # 其他职责辅导员（学籍与请假业务辅导员）回复被拒
    client.post("/logout")
    _login_as(client, "c_leave", "cou123")
    tok3 = _csrf_from_session(client)
    r = client.post(f"/api/tickets/{tid}/reply", json={"reply": "x"},
                    headers={"X-CSRF-Token": tok3})
    assert r.status_code == 403


def test_schedule_run_admin_only(client):
    """排课求解仅管理员：辅导员/学生 403。"""
    _login_as(client, "counselor", "cou123")
    tok = _csrf_from_session(client)
    assert client.post("/api/schedule/run", headers={"X-CSRF-Token": tok}).status_code == 403
    client.post("/logout")
    _login_as(client, "admin", "SmartCampus@2026")
    tok2 = _csrf_from_session(client)
    assert client.post("/api/schedule/run", headers={"X-CSRF-Token": tok2}).status_code == 200


def test_counselor_sees_only_own_tickets(client):
    """辅导员只见流转到自己职责的工单（数据范围隔离）。"""
    _login_as(client, "admin", "SmartCampus@2026")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    # 辅导员登录后工单列表不包含综合事务辅导员以外的工单
    client.post("/logout")
    _login_as(client, "c_leave", "cou123")  # 学籍与请假业务辅导员
    tickets = client.get("/api/tickets").get_json()
    assert all(t["handler"] == "学籍与请假业务辅导员" for t in tickets) or len(tickets) == 0


def test_admin_resolves_ticket_only(client):
    """管理人员可结案任意工单；辅导员不能结案他人工单（403）。"""
    _login_as(client, "admin", "SmartCampus@2026")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    all_tickets = db.list_tickets(role="", who="")
    assert all_tickets, "应生成工单"
    tid = all_tickets[0]["id"]
    assert client.post(f"/api/tickets/{tid}/resolve", json={"resolution": "已核实处理"},
                       headers={"X-CSRF-Token": tok}).status_code == 200

    client.post("/logout")
    _login_as(client, "counselor", "cou123")
    tok2 = _csrf_from_session(client)
    assert client.post(f"/api/tickets/{tid}/resolve", json={"resolution": "x"},
                       headers={"X-CSRF-Token": tok2}).status_code == 403


def test_student_can_resolve_own_ticket(client):
    """学生可结单自己发起的工单；不能结单他人（不同学号）的工单。"""
    # 学生发起工单（学号 20230001）
    _login_as(client, "student", "stu123")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    mine = db.list_tickets(role="student", who="20230001")
    assert mine, "学生应能通过学号看到自己的工单"
    tid = mine[0]["id"]
    # 学生可结单自己工单
    assert client.post(f"/api/tickets/{tid}/resolve", json={"resolution": "已解决"},
                       headers={"X-CSRF-Token": tok}).status_code == 200
    got = db.get_ticket(tid)
    assert got["status"] == "resolved"


def test_student_cannot_resolve_others_ticket(client):
    """学生不能结单他人学号的工单（越权 403）。"""
    # 管理员以 20230002 发起他人工单
    _login_as(client, "admin", "SmartCampus@2026")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230002"},
        headers={"X-CSRF-Token": tok},
    )
    all_tickets = db.list_tickets(role="", who="")
    assert all_tickets
    tid = all_tickets[0]["id"]
    client.post("/logout")

    # 学生 20230001 尝试结单 20230002 的工单 -> 403
    _login_as(client, "student", "stu123")
    tok2 = _csrf_from_session(client)
    assert client.post(f"/api/tickets/{tid}/resolve", json={"resolution": "x"},
                       headers={"X-CSRF-Token": tok2}).status_code == 403


def test_student_sees_own_ticket_and_reply(client):
    """学生端：能看到辅导员回复（闭环）——发起工单后辅导员回复，学生工单含 reply。"""
    # 管理员（或辅导员）发起工单，辅导员回复
    _login_as(client, "admin", "SmartCampus@2026")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    tid = db.list_tickets(role="", who="")[0]["id"]
    client.post("/logout")
    _login_as(client, "counselor", "cou123")
    tok2 = _csrf_from_session(client)
    client.post(f"/api/tickets/{tid}/reply", json={"reply": "已派后勤维修，今晚处理"},
                headers={"X-CSRF-Token": tok2})
    client.post("/logout")

    # 学生登录：能通过 /api/tickets 看到自己工单，且包含辅导员回复
    _login_as(client, "student", "stu123")
    mine = client.get("/api/tickets").get_json()
    mine = [t for t in mine if t["id"] == tid]
    assert mine, "学生应能看到自己发起的工单"
    assert mine[0]["reply"] == "已派后勤维修，今晚处理"
    assert mine[0]["status"] == "processing"


def test_csrf_blocks_post_without_token(client):
    _login(client)
    r = client.post("/api/energy/run")
    assert r.status_code == 403


def test_energy_run_end_to_end(client):
    _login(client)
    tok = _csrf_from(client, "/energy")
    assert tok
    r = client.post("/api/energy/run", headers={"X-CSRF-Token": tok})
    assert r.status_code == 200
    data = r.get_json()
    assert data["vision_used"] is True
    assert data["peak_count"] > 0
    assert isinstance(data["alarm_count"], int)


def test_schedule_run_end_to_end(client):
    _login(client)
    tok = _csrf_from(client, "/scheduler")
    assert tok
    r = client.post("/api/schedule/run", headers={"X-CSRF-Token": tok})
    assert r.status_code == 200
    data = r.get_json()
    assert data["fitness"] > 0
    assert data["conflicts"] == 0
    assert data["run_id"]


def test_chat_and_ticket_flow(client):
    _login(client)
    tok = _csrf_from(client, "/ai")
    assert tok
    r = client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["needs_human"] is True
    assert data["ticket"]["id"].startswith("TK-")


# ---------------- 角色化界面与辅导员数据范围（总览兜底） ----------------

def test_counselor_overview_sees_all_energy_and_schedule(client):
    """综合事务辅导员（无专属楼栋/课程）：能耗与排课页展示全校总览，而非空数据。"""
    _login_as(client, "admin", "SmartCampus@2026")
    etok = _csrf_from(client, "/energy")
    client.post("/api/energy/run", headers={"X-CSRF-Token": etok})
    stok = _csrf_from(client, "/scheduler")
    client.post("/api/schedule/run", headers={"X-CSRF-Token": stok})
    client.post("/logout")

    _login_as(client, "counselor", "cou123")
    ehtml = client.get("/energy").get_data(as_text=True)
    assert "宿舍能耗总览" in ehtml                                   # 总览态标题
    assert "1号宿舍楼-101" in ehtml and "2号宿舍楼-201" in ehtml       # 能看到两个楼栋
    assert 'id="runBtn"' not in ehtml                                # 仍无采集按钮（只读）
    shtml = client.get("/scheduler").get_data(as_text=True)
    assert "课程总览" in shtml
    assert "数据结构" in shtml and "大学英语" in shtml                 # 全校课程可见
    assert 'id="runBtn"' not in shtml                                # 无求解按钮


def test_building_counselor_keeps_own_scope(client):
    """楼栋辅导员仍只看本人楼栋（隔离不被总览兜底破坏），标题为『所管宿舍能耗』。"""
    _login_as(client, "admin", "SmartCampus@2026")
    etok = _csrf_from(client, "/energy")
    client.post("/api/energy/run", headers={"X-CSRF-Token": etok})
    client.post("/logout")

    _login_as(client, "f1", "cou123")
    html = client.get("/energy").get_data(as_text=True)
    assert "所管宿舍能耗" in html
    assert "1号宿舍楼-" in html
    assert "2号宿舍楼-" not in html


def test_role_based_nav_labels(client):
    """导航标签按角色定制：学生=在线咨询 / 辅导员=辅导员工作台 / 管理=能耗监控。"""
    _login_as(client, "student", "stu123")
    assert "在线咨询" in client.get("/ai").get_data(as_text=True)
    client.post("/logout")
    _login_as(client, "counselor", "cou123")
    html = client.get("/ai").get_data(as_text=True)
    assert "辅导员工作台" in html and "宿舍能耗" in html
    client.post("/logout")
    _login_as(client, "admin", "SmartCampus@2026")
    html = client.get("/ai").get_data(as_text=True)
    assert "能耗监控" in html and "排课管理" in html


def test_student_ai_page_shows_own_tickets_and_auto_refresh(client):
    """学生视角：工单区称『我的工单』且带自动刷新（辅导员回复自动可见）；管理员页无学生轮询。"""
    _login_as(client, "student", "stu123")
    html = client.get("/ai").get_data(as_text=True)
    assert "我的工单" in html
    assert "refreshSidebar" in html and "setInterval" in html
    client.post("/logout")
    _login_as(client, "admin", "SmartCampus@2026")
    assert "}, 12000)" not in client.get("/ai").get_data(as_text=True)


# ---------------- 辅导员细分视角（教师 / 楼栋 / 业务，互不越界） ----------------

def test_counselor_view_segmentation(client):
    """教师只见课表；楼栋辅导员只见告警通知 + 所管宿舍能耗；业务辅导员不回归。"""
    # 教师视角（张老师）：/scheduler 200，/ai 与 /energy 403；首页为"教师工作台"
    _login_as(client, "t_zhang", "cou123")
    assert client.get("/scheduler").status_code == 200
    assert client.get("/ai").status_code == 403
    assert client.get("/energy").status_code == 403
    home = client.get("/").get_data(as_text=True)
    assert "教师工作台" in home and "我的课表" in home
    assert "宿舍能耗" not in home and "辅导员工作台" not in home
    client.post("/logout")

    # 楼栋辅导员（f1）：/ai(告警通知) + /energy 200，/scheduler 403；工作台仅告警通知
    _login_as(client, "f1", "cou123")
    assert client.get("/energy").status_code == 200
    h_ai = client.get("/ai").get_data(as_text=True)
    assert "宿舍告警通知" in h_ai and "告警通知中心" in h_ai
    assert "工单处理中心" not in h_ai
    assert "最近咨询记录</div>" not in h_ai
    assert client.get("/scheduler").status_code == 403
    client.post("/logout")

    # 业务辅导员（counselor）：三页正常 + 完整工作台（不回归）
    _login_as(client, "counselor", "cou123")
    for p in ("/ai", "/energy", "/scheduler"):
        assert client.get(p).status_code == 200
    assert "工单处理中心" in client.get("/ai").get_data(as_text=True)


def test_student_resolve_button_interaction_ready(client):
    """学生结单按钮：带 id 且页面无原生 confirm/alert（沙箱预览环境同样可交互）。"""
    _login_as(client, "student", "stu123")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    html = client.get("/ai").get_data(as_text=True)
    assert "resolve-btn-" in html          # 两段确认所需按钮 id
    assert "再次点击确认结单" in html      # 页内二次确认文案
    assert "confirm(" not in html          # 不依赖原生弹窗
    assert "alert(" not in html
