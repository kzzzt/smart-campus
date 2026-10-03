"""
AI 教务智能客服主逻辑（bot）。

处理一条学生消息的完整链路：
    1. 意图 + 槽位理解（understand）
    2. 若可自动应答 -> 生成知识库回答
    3. 若需人工 -> 自动生成工单并流转给对应辅导员
    4. 返回给学生结构化回复
"""

from .intent import understand
from .ticket import TicketSystem

# 知识库：意图 -> 常见问题答案（初稿为内置固定答案，可扩展为向量检索）
KNOWLEDGE_BASE = {
    "leave": (
        "同学你好，关于请假（病假/事假）的流程：一般需提前在教务系统提交申请，"
        "上传相关证明（病假条/事假事由），由辅导员审批后生效。"
        "单次请假超过X天或涉及期末考试的，需提交学院审核。"
    ),
    "scholarship": (
        "同学你好，奖学金评定通常在每学年秋季学期开展。评定依据为综合素质测评成绩"
        "（学业成绩 + 德育 + 文体），具体名额与标准以学院当年通知为准。"
        "参评基本条件：无挂科、无违纪处分。"
    ),
    "status_change": (
        "同学你好，学籍异动（转专业/休学/复学/退学）需先由本人提出书面申请，"
        "经学院、教务处逐级审批。转专业一般在大一/大二结束后开放申请窗口，"
        "需满足目标专业接收条件并通过考核。具体材料清单可咨询学籍业务辅导员。"
    ),
    "other": (
        "抱歉，这个问题我暂时无法直接回答。已为你生成工单并转给相关辅导员，"
        "请留意处理结果。"
    ),
}


class CampusAIBot:
    """教务智能客服机器人（7×24h）。"""

    def __init__(self):
        self.tickets = TicketSystem()

    def handle(self, student_desc: str, student_id: str = "") -> dict:
        """
        处理一条学生消息，返回结构化结果：
        {
            "student_id": str,
            "input": str,
            "intent": str,
            "confidence": float,
            "answer": str | None,
            "needs_human": bool,
            "ticket": dict | None,
        }
        """
        u = understand(student_desc)
        answer = None

        if u["needs_human"]:
            # 需要人工：自动生成工单并流转
            slots = u["slots"]
            if student_id:
                slots["student_id"] = student_id
            ticket = self.tickets.create(
                intent=u["intent"], student_desc=student_desc, slots=slots
            )
            self.tickets.flow(ticket.ticket_id)
            return {
                "student_id": student_id,
                "input": student_desc,
                "intent": u["intent"],
                "confidence": u["confidence"],
                "answer": KNOWLEDGE_BASE["other"],
                "needs_human": True,
                "ticket": {
                    "id": ticket.ticket_id,
                    "handler": ticket.handler,
                    "status": ticket.status,
                    "slots": slots,
                },
            }

        # 可自动应答：返回知识库答案
        answer = KNOWLEDGE_BASE.get(u["intent"], KNOWLEDGE_BASE["other"])
        return {
            "student_id": student_id,
            "input": student_desc,
            "intent": u["intent"],
            "confidence": u["confidence"],
            "answer": answer,
            "needs_human": False,
            "ticket": None,
        }
