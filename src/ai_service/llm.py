"""
AI 教务智能客服 —— 大模型调用统一入口。

初稿中默认使用「本地规则 + 提示词模板」的可运行实现，
接入真实大模型时只需替换本模块的 chat() 函数（例如调用 OpenAI / 国内大模型 API）。
这样保证在没有外部 API 密钥的情况下 Demo 依然可以完整运行。
"""


def chat(messages: list, system: str | None = None) -> str:
    """
    与大模型对话的统一入口。

    参数
    ----
    messages : list[dict]
        [{"role": "user", "content": "..."}, ...]
    system : str | None
        系统提示词（可选）

    返回
    ----
    str : 模型回复文本

    说明
    ----
    默认实现是一个「简单规则式本地回复器」，用于让 Demo 离线可跑。
    接入真实大模型示例（需开启 requirements 中的 openai 依赖）：

        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conv,
        )
        return resp.choices[0].message.content
    """
    if not messages:
        return ""
    last = messages[-1]["content"]
    # 规则式回退：如果本地无法理解，则建议生成工单
    return f"[本地规则回复] 已收到你的问题：「{last}」。如需更精准处理，请转人工/生成工单。"
