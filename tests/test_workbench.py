"""辅导员工作台：工单状态桶筛选 + 告警通知闭环测试。

不依赖 pytest tmpdir（沙箱环境下 tmp 目录 ACL 会报错），改用工作区内可写临时库。
"""
import os
import re

import pytest

from webapp import db
from webapp.app import app

db.DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_wb_test.db")

app.config.update(TESTING=True, SECRET_KEY="test-secret")


class _T:
    """最小 Ticket 替身，满足 db.save_ticket 所需属性。"""

    def __init__(self, tid, handler="综合事务辅导员", student_id="20230001"):
        self.ticket_id = tid
        self.intent = "other"
        self.student_desc = f"测试问题 {tid}"
        self.slots = {"student_id": student_id}
        self.handler = handler
        self.status = "processing"
        self.resolution = ""
        self.student_id = student_id


def _db_paths():
    return [db.DB_PATH, db.DB_PATH + "-wal", db.DB_PATH + "-shm"]


@pytest.fixture(autouse=True)
def _clean_db():
    for p in _db_paths():
        if os.path.exists(p):
            os.remove(p)
    db.init_db()
    yield
    for p in _db_paths():
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _csrf(c, path="/ai"):
    m = re.search(r"X-CSRF-Token':'([0-9a-f]{32})'", c.get(path).get_data(as_text=True))
    assert m, "页面中未找到 CSRF token"
    return m.group(1)


def test_list_tickets_buckets():
    db.save_ticket(_T("TK-A"))  # 待处理（无回复）
    db.save_ticket(_T("TK-B"))  # 回复后 -> 已答复
    db.reply_ticket("TK-B", "已安排处理")
    db.save_ticket(_T("TK-C"))  # 结案
    conn = db.get_conn()
    conn.execute("UPDATE tickets SET status='resolved', resolution='ok' WHERE id='TK-C'")
    conn.commit()
    conn.close()

    open_ids = {t["id"] for t in db.list_tickets(bucket="open")}
    replied = {t["id"] for t in db.list_tickets(bucket="replied")}
    resolved = {t["id"] for t in db.list_tickets(bucket="resolved")}
    assert open_ids == {"TK-A"}
    assert replied == {"TK-B"}
    assert resolved == {"TK-C"}


def test_counselor_workbench_flow():
    db.save_ticket(_T("TK-1"))
    c = app.test_client()
    assert c.post("/login", data={"username": "counselor", "password": "cou123"}).status_code == 302

    html = c.get("/ai").get_data(as_text=True)
    assert "辅导员工作台" in html
    assert "TK-1" in html

    # 回复工单 -> 200
    r = c.post("/api/tickets/TK-1/reply", json={"reply": "已安排处理"},
               headers={"X-CSRF-Token": _csrf(c)})
    assert r.status_code == 200
    assert "TK-1" in c.get("/ai?tbucket=replied").get_data(as_text=True)

    # 告警通知闭环：待处理出现 -> 标记已处理 -> acknowledged=1
    db.save_energy_notice([{
        "run_id": "T2", "room": "1号宿舍楼-101", "handler": "综合事务辅导员",
        "power_w": 2326, "level": "high", "message": "高能耗告警",
    }])
    assert "高能耗告警" in c.get("/ai?nbucket=pending").get_data(as_text=True)
    nid = db.list_energy_notices()[0]["id"]
    assert c.post(f"/api/notices/{nid}/handle",
                  headers={"X-CSRF-Token": _csrf(c)}).status_code == 200
    rows = db.list_energy_notices(limit=50)
    assert [n["acknowledged"] for n in rows if n["id"] == nid] == [1]


def test_counselor_cannot_handle_others_notice():
    db.save_energy_notice([{
        "run_id": "T3", "room": "2号宿舍楼-201", "handler": "1号楼生活辅导员",
        "power_w": 1900, "level": "warning", "message": "他人职责告警",
    }])
    c = app.test_client()
    c.post("/login", data={"username": "counselor", "password": "cou123"})  # 综合事务辅导员
    nid = db.list_energy_notices()[0]["id"]
    assert c.post(f"/api/notices/{nid}/handle",
                  headers={"X-CSRF-Token": _csrf(c)}).status_code == 404


def test_admin_can_handle_any_notice():
    db.save_energy_notice([{
        "run_id": "T4", "room": "2号宿舍楼-201", "handler": "1号楼生活辅导员",
        "power_w": 1900, "level": "warning", "message": "任意告警",
    }])
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "SmartCampus@2026"})
    nid = db.list_energy_notices()[0]["id"]
    assert c.post(f"/api/notices/{nid}/handle",
                  headers={"X-CSRF-Token": _csrf(c)}).status_code == 200
