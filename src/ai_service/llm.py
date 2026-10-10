"""
AI 教务智能客服 —— 大模型统调用统一入口。

分层设计（README/作品说明书所述"大模型语义理解"落地点）：
    - 大模型负责"理解"：意图识别、槽位抽取、复杂问题摘要；
    - 本地规则负责"兜底"：无 key / 断网 / 欠费 / 超时 / 异常时自动降级，
      保证 7×24 客服在离线环境演示永不崩、永远秒回。
接口保持一致，业务代码无需改动即可切换。

配置（环境变量，切勿写进仓库）：
    LLM_API_KEY    必填，否则走本地规则
    LLM_BASE_URL   可选，默认 https://api.openai.com/v1（国内兼容网关可换）
    LLM_MODEL      可选，默认 gpt-4o-mini
"""

import os

# 懒加载 OpenAI 客户端；未安装 openai 时完全不影响离线回退
_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI  # 延迟导入，未安装不报错

        _client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        )
    return _client


def chat(messages: list, system: str | None = None, timeout: int = 20) -> str:
    """
    与大模型对话的统一入口。

    参数
    ----
    messages : list[dict]
        [{"role": "user", "content": "..."}, ...]
    system : str | None
        系统提示词（可选）
    timeout : int
        网络超时秒数，防止页面转圈

    返回
    ----
    str : 模型回复文本；未配置/失败时自动降级为本地规则回复
    """
    if not messages:
        return ""
    # 未配置 key：直接本地规则回复（离线可跑）
    if not os.environ.get("LLM_API_KEY"):
        return _local_fallback(messages)
    try:
        conv = ([{"role": "system", "content": system}] if system else []) + list(messages)
        resp = _get_client().chat.completions.create(
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            messages=conv,
            timeout=timeout,
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content or _local_fallback(messages)
    except Exception:
        # 断网 / 超时 / 欠费 / key 失效 都不崩，降级到本地规则
        return _local_fallback(messages)


def _local_fallback(messages: list) -> str:
    last = messages[-1]["content"] if messages else ""
    return f"[本地规则回复] 已收到你的问题：「{last}」。如需更精准处理，请转人工/生成工单。"
