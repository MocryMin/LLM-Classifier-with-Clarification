"""
v3/L1_router.py — V3 L1 意图路由
=================================

单次 LLM 调用完成意图分类 + 路由决策。
无槽位收集, 无风险评估, 调用格式为 ###call(L1-L2)。

用法:
    from v3.L1_router import route
    result = route(messages, debug=False)
"""

import os
import json
import re
from openai import OpenAI

client = OpenAI(
    api_key="sk-6172dca8aeb0461a8b84cc8bcac0f9e8",
    base_url="https://api.deepseek.com",
)

_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "L1_router_v3.txt")
_prompt_template: str | None = None


def _load_prompt() -> str:
    """惰性加载 V3 prompt 模板。"""
    global _prompt_template
    if _prompt_template is None:
        with open(_PROMPT_FILE, "r", encoding="utf-8") as f:
            _prompt_template = f.read()
    return _prompt_template


# ═══════════════════════════════════════════════════════════
# LLM 调用
# ═══════════════════════════════════════════════════════════

def _ask(messages: list[dict], thinking: str = "enabled", max_retries: int = 5) -> str:
    """调用 DeepSeek API, 带重试。"""
    for retry in range(max_retries):
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream=False,
            max_tokens=100000,
            extra_body={"thinking": {"type": thinking}},
        )
        if response.choices[0].message.content:
            return response.choices[0].message.content
    return ""  # all retries exhausted


# ═══════════════════════════════════════════════════════════
# 消息格式化
# ═══════════════════════════════════════════════════════════

def _format_messages(messages: list[dict]) -> str:
    """将 OpenAI 格式消息列表转换为可读对话文本。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "system":
            continue
        elif role == "user":
            lines.append(f"[用户] {content}")
        elif role == "assistant":
            lines.append(f"[客服] {content}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# JSON 解析
# ═══════════════════════════════════════════════════════════

def _sanitize_json_control_chars(text: str) -> str:
    """将 JSON 字符串值内的字面控制字符替换为转义序列。"""
    result = []
    in_string = False
    escape_next = False
    for c in text:
        if escape_next:
            result.append(c)
            escape_next = False
            continue
        if c == "\\":
            result.append(c)
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            elif ord(c) < 32:
                result.append(f"\\u{ord(c):04x}")
            else:
                result.append(c)
        else:
            result.append(c)
    return "".join(result)


def _extract_json(text: str) -> dict | None:
    """三策略级联提取 JSON 对象。"""
    t = text.strip()

    # 策略1: ```json ... ```
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", t, re.DOTALL)
    if m:
        try:
            return json.loads(_sanitize_json_control_chars(m.group(1).strip()))
        except json.JSONDecodeError:
            pass

    # 策略2: 花括号边界
    first = t.find("{")
    last = t.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(_sanitize_json_control_chars(t[first : last + 1]))
        except json.JSONDecodeError:
            pass

    # 策略3: 整段
    try:
        return json.loads(_sanitize_json_control_chars(t))
    except json.JSONDecodeError:
        return None


def _make_fallback() -> dict:
    """构造兜底结果。"""
    return {
        "primary_intent": {"l1": "", "l2": "", "confidence": 0.0},
        "top_candidates": [],
        "needs_clarification": True,
        "user_output": (
            "小保没有完全理解您的需求，请换个方式描述一下您想咨询或办理的业务，好吗？"
        ),
        "reason": "JSON parse error, fallback",
    }


def _parse_result(raw: str) -> tuple[dict, bool]:
    """解析 LLM 输出, 返回 (result, ok)。"""
    data = _extract_json(raw)
    if data is None:
        return _make_fallback(), False

    # 确保必要字段存在
    data.setdefault("primary_intent", {"l1": "", "l2": "", "confidence": 0.0})
    data.setdefault("top_candidates", [])
    data.setdefault("needs_clarification", False)
    data.setdefault("user_output", "")
    data.setdefault("reason", "")
    return data, True


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def route(
    messages: list[dict],
    debug: bool = False,
    max_retries: int = 2,
) -> dict:
    """
    V3 L1 意图路由 — 单次 LLM 调用。

    Args:
        messages:    OpenAI 格式对话历史
        debug:       打印原始 LLM 输出
        max_retries: JSON 解析失败重试次数

    Returns:
        {
            "primary_intent": {"l1": str, "l2": str, "confidence": float},
            "top_candidates": [{"l1": str, "l2": str, "probability": float}],
            "needs_clarification": bool,
            "user_output": str,     # 可能含 ###call(L1-L2)
            "reason": str,
        }
    """
    conversation = _format_messages(messages)
    template = _load_prompt()
    full_prompt = template.replace("{conversation}", conversation)
    user_msg = [{"role": "user", "content": full_prompt}]

    for attempt in range(1 + max_retries):
        raw = _ask(user_msg, thinking="enabled")

        if debug:
            print(f"\n[V3 L1 RAW attempt {attempt + 1}]:")
            print(raw)

        result, ok = _parse_result(raw)

        if ok:
            return result

        if attempt < max_retries:
            print(
                f"[V3 L1] JSON parse failed, retrying... "
                f"({attempt + 1}/{max_retries})"
            )

    print("[V3 L1] JSON parse failed after all retries, using fallback.")
    return result


# ═══════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_cases = [
        [{"role": "user", "content": "你好"}],
        [{"role": "user", "content": "我想查一下我的保单"}],
        [{"role": "user", "content": "我想买个医疗险"}],
        [{"role": "user", "content": "我有糖尿病，能买重疾险吗"}],
        [{"role": "user", "content": "我35岁，想买个医疗险"}],
    ]

    for i, msgs in enumerate(test_cases):
        print(f"\n{'=' * 60}")
        print(f"Test {i + 1}: {msgs[0]['content']}")
        result = route(msgs, debug=(i == 0))  # only debug first
        pi = result["primary_intent"]
        print(f"  意图: {pi.get('l1', '?')} > {pi.get('l2', '?')} "
              f"(confidence={pi.get('confidence', 0):.2f})")
        print(f"  需澄清: {result['needs_clarification']}")
        print(f"  user_output: {result['user_output'][:120]}")
        print(f"  reason: {result['reason']}")
