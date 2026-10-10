"""
工单生成与流转模块。

核心闭环：AI 无法处理的复杂情况 -> 自动生成工单 -> 按类型流转给对应辅导员。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 辅导员职责映射：意图 -> 对应处理人
INTENT_TO_HANDLER = {
    "leave":        "学籍与请假业务辅导员",
    "scholarship":  "奖助学金评审辅导员",
    "status_change": "学籍异动业务辅导员",
    "other":        "综合事务辅导员",
}


@dataclass
class Ticket:
    """一张流转工单。"""
    ticket_id: str
    intent: str
    student_desc: str
    slots: dict = field(default_factory=dict)
    handler: str = ""
    status: str = "pending"          # pending / processing / resolved
    created_at: str = ""
    resolution: Optional[str] = None

    def __post_init__(self):
        if not self.handler:
            self.handler = INTENT_TO_HANDLER.get(self.intent, "综合事务辅导员")
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TicketSystem:
    """工单系统：负责创建、流转与结案。"""

    def __init__(self):
        self.tickets: list[Ticket] = []

    def create(self, intent: str, student_desc: str, slots: dict) -> Ticket:
        # 唯一工单 ID：日期 + 短 UUID，避免跨重启/同进程重复被 INSERT OR REPLACE 静默覆盖
        ticket_id = f"TK-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8]}"
        t = Ticket(
            ticket_id=ticket_id,
            intent=intent,
            student_desc=student_desc,
            slots=slots,
        )
        self.tickets.append(t)
        return t

    def flow(self, ticket_id: str) -> Optional[Ticket]:
        """流转（发送提醒给对应辅导员）。示意：直接更新状态。"""
        t = self.find(ticket_id)
        if t:
            t.status = "processing"
        return t

    def resolve(self, ticket_id: str, resolution: str) -> Optional[Ticket]:
        t = self.find(ticket_id)
        if t:
            t.status = "resolved"
            t.resolution = resolution
        return t

    def find(self, ticket_id: str) -> Optional[Ticket]:
        for t in self.tickets:
            if t.ticket_id == ticket_id:
                return t
        return None
