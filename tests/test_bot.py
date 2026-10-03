from src.ai_service.bot import CampusAIBot
from src.ai_service.intent import understand
from src.ai_service.ticket import TicketSystem


def test_understand_leave():
    r = understand("我想请一天病假，需要什么材料？")
    assert r["intent"] == "leave"
    assert r["confidence"] > 0


def test_understand_scholarship():
    r = understand("国家奖学金评定标准是什么？")
    assert r["intent"] == "scholarship"


def test_understand_status_change():
    r = understand("请问转专业的手续怎么办？")
    assert r["intent"] == "status_change"


def test_auto_answer_leave():
    bot = CampusAIBot()
    r = bot.handle("请三天病假的流程？", student_id="20230001")
    assert r["needs_human"] is False
    assert r["answer"] and "请假" in r["answer"]


def test_ticket_flow_for_complex():
    """涉及 key 信息缺失/无法自动处理的 -> 应生成工单并流转。"""
    bot = CampusAIBot()
    r = bot.handle("帮我查一下三食堂门口的失物招领", student_id="20230002")
    assert r["needs_human"] is True
    assert r["ticket"] is not None
    assert r["ticket"]["handler"]  # 已流转给某辅导员
    assert r["ticket"]["status"] == "processing"


def test_ticket_system_resolve():
    ts = TicketSystem()
    t = ts.create("leave", "请病假", {"leave_type": "病假"})
    ts.flow(t.ticket_id)
    ts.resolve(t.ticket_id, "已处理")
    assert ts.find(t.ticket_id).status == "resolved"
