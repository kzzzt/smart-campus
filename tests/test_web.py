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
