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
    return client.post("/login", data={"username": "admin", "password": "admin123"})


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


def test_counselor_only_ai_and_scheduler(client):
    """辅导员：AI 客服 + 排课；能耗页/能耗运行被拒。"""
    _login_as(client, "counselor", "cou123")
    assert client.get("/ai").status_code == 200
    assert client.get("/scheduler").status_code == 200
    assert client.get("/energy").status_code == 403
    assert client.post("/api/energy/run").status_code == 403
    tok = _csrf_from_session(client)
    assert client.post("/api/schedule/run", headers={"X-CSRF-Token": tok}).status_code == 200


def test_counselor_sees_only_own_tickets(client):
    """辅导员只见流转到自己职责的工单（数据范围隔离）。"""
    _login_as(client, "admin", "admin123")
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
    """工单结案仅管理员；辅导员/学生被拒。"""
    _login_as(client, "admin", "admin123")
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


def test_student_cannot_resolve(client):
    _login_as(client, "admin", "admin123")
    tok = _csrf_from_session(client)
    client.post(
        "/api/chat",
        json={"message": "我寝室插座坏了找谁？", "student_id": "20230001"},
        headers={"X-CSRF-Token": tok},
    )
    all_tickets = db.list_tickets(role="", who="")
    assert all_tickets
    tid = all_tickets[0]["id"]
    client.post("/logout")
    _login_as(client, "student", "stu123")
    tok2 = _csrf_from_session(client)
    assert client.post(f"/api/tickets/{tid}/resolve", json={"resolution": "x"},
                       headers={"X-CSRF-Token": tok2}).status_code == 403


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
