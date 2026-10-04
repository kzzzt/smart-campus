"""
意图识别与槽位提取模块。

将学生的一句自然语言问题映射到：
    1. 意图（intent）：leave / scholarship / status_change / other
    2. 槽位（slots）：{ 学生学号, 请假类型, 奖学金类别, 学籍异动类型, ... }

初稿采用「关键词规则 + 可替换的 LLM 提示词」双通道：
    - 规则通道：离线、快速、稳定，Demo 默认开启；
    - LLM 通道：当规则通道置信度不足时调用大模型做语义理解，
      体现「大模型 + 规则」结合的工程设计。
"""

from .llm import chat

# 意图 -> 关键词
INTENT_KEYWORDS = {
    "leave":       ["请假", "病假", "事假", "休学", "请假流程"],
    "scholarship": ["奖学金", "评奖", "助学金", "奖学金评定"],
    "status_change": ["学籍", "转专业", "休学", "退学", "复学", "学籍异动", "学籍变更"],
    "other":       [],
}

# 槽位 -> 关键词（用于抽取实体）
SLOT_KEYWORDS = {
    "student_id":     ["学号", "我的学号"],
    "leave_type":     ["病假", "事假", "病假申请"],
    "scholarship_type": ["国家奖学金", "励志奖学金", "学业奖学金"],
    "duration":       ["一天", "两天", "一周", "三天"],
}


def extract_intent(text: str) -> tuple[str, float]:
    """
    基于关键词的意图识别。返回 (intent, score)。
    LLM 通道（示意）：可调用 chat() 让模型返回 JSON 意图标签，
    当规则置信度低于阈值时启用。
    """
    best_intent, best_score = "other", 0.0
    for intent, kws in INTENT_KEYWORDS.items():
        hit = sum(1 for kw in kws if kw in text)
        if hit and hit > best_score:
            best_intent, best_score = intent, float(hit) / max(len(kws), 1)
    return best_intent, best_score


def extract_slots(text: str) -> dict:
    """抽取槽位实体（初稿为关键词匹配，真实可接 LAC / LLM 抽取）。"""
    slots: dict = {}
    for name, kws in SLOT_KEYWORDS.items():
        for kw in kws:
            # 简单前后缀抽取：实际工程应使用正则/实体识别
            if kw in text:
                slots[name] = kw
    return slots


def understand(text: str) -> dict:
    """
    综合理解入口。返回：
    {
        "intent": str,
        "slots": dict,
        "confidence": float,
        "needs_human": bool,   # 是否需转人工/生成工单
        "llm_used": bool,
    }
    """
    intent, score = extract_intent(text)
    slots = extract_slots(text)

    # 规则置信度过低 -> 尝试 LLM 语义理解（示意）
    llm_used = False
    if score < 0.25:
        llm_used = True
        # 示意：调用大模型返回 JSON（初稿回退到规则结果，避免外部依赖）
        # resp = chat([{"role": "user", "content": text}], system=INTENT_LLM_PROMPT)
        # 解析 resp 中的意图...
        if "奖学金" in text:
            intent, score = "scholarship", 0.9
        elif "请假" in text:
            intent, score = "leave", 0.9
        elif "学籍" in text or "转专业" in text:
            intent, score = "status_change", 0.9

    # 人工兜底：仅当无法识别意图（other）时转人工/生成工单。
    # 之前用 "or not slots" 会导致明确的意图问题（如"请假的流程"）
    # 因未抽到具体槽位而被误判为需人工 —— 已修正为仅 other 兜底。
    needs_human = intent == "other"

    return {
        "intent": intent,
        "slots": slots,
        "confidence": round(score, 2),
        "needs_human": needs_human,
        "llm_used": llm_used,
    }


INTENT_LLM_PROMPT = (
    "你是教务智能客服的意图识别模块。请判断用户问题的意图，"
    "从 [leave, scholarship, status_change, other] 中选择并返回。"
)
