"""
entrance.py - V4 入口(接口与 V3 一致)
======================================
一个入口: 输入消息, 输出标签(及路由决策)。
内部走两阶段渐进式注入(kernel.classify), 返回结构与 V3 entrance 同构。

用法:
    from v4.entrance import entrance
    result = entrance(messages, debug=True)

用户须提供自己的 DeepSeek API key(环境变量 DEEPSEEK_API_KEY 或 api_key= 参数)。
"""

import os
from .prompt_parser import parse_prompt_file
from .llm import LLMClient, DEFAULT_FLASH
from .kernel import classify

_DEFAULT_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompt.txt")
_parsed_cache: dict = {}


def _load_parsed(prompt_file: str | None = None) -> dict:
    path = prompt_file or _DEFAULT_PROMPT_FILE
    if path not in _parsed_cache:
        _parsed_cache[path] = parse_prompt_file(path)
    return _parsed_cache[path]


def _format_messages(messages: list[dict]) -> str:
    """OpenAI 格式消息 -> 可读对话文本(与 V3 一致)。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            continue
        elif role == "user":
            lines.append(f"[用户] {content}")
        elif role == "assistant":
            lines.append(f"[客服] {content}")
    return "\n".join(lines)


def entrance(
    messages: list[dict],
    debug: bool = False,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    prompt_file: str | None = None,
    model: str | None = None,
    k: int = 5,
    thinking: str = "disabled",
) -> dict:
    """V4 入口 - 两阶段渐进式注入意图路由。

    Args:
        messages:    OpenAI 格式对话历史 [{"role":"user","content":"..."}, ...]
        debug:       打印各层中间结果
        api_key:     用户的 DeepSeek API key(不传则读环境变量 DEEPSEEK_API_KEY)
        base_url:    API 地址(默认 https://api.deepseek.com)
        prompt_file: prompt.txt 路径(默认包内 prompt.txt, 即 V3 prompter 产物)
        model:       模型名(默认 deepseek-v4-flash)
        k:           Layer_1 召回的 top-k(默认 5)
        thinking:    thinking 模式(默认 disabled, 分类任务够用且省时延)

    Returns:
        与 V3 entrance 同构:
        {
            "case": 1, "risk_level": None, "response_mode": "v4",
            "tag_dispositions": {}, "decision_trail": [],
            "data": {
                "primary_intent": {"l1": str, "l2": str, "confidence": float},
                "top_candidates": [{"l1": str, "l2": str, "probability": float}],
                "needs_clarification": bool,
                "user_output": str,
                "reason": str,
            }
        }
    """
    if debug:
        print(f"[V4 entrance] {len(messages)} messages")

    parsed = _load_parsed(prompt_file)
    conversation = _format_messages(messages)
    client = LLMClient(api_key=api_key, base_url=base_url)

    try:
        data = classify(
            parsed,
            conversation,
            client,
            model=model or DEFAULT_FLASH,
            k=k,
            thinking=thinking,
            debug=debug,
        )
    except Exception as e:
        if debug:
            print(f"[V4 entrance] kernel exception: {e}")
        data = {
            "primary_intent": {"l1": "", "l2": "", "confidence": 0.0},
            "top_candidates": [],
            "needs_clarification": True,
            "user_output": "系统处理异常，请稍后重试或拨打95500客服热线。",
            "reason": f"kernel exception: {e}",
        }

    result = {
        "case": 1,
        "risk_level": None,
        "response_mode": "v4",
        "tag_dispositions": {},
        "decision_trail": [],
        "data": data,
    }

    if debug:
        pi = data.get("primary_intent", {})
        print(
            f"[V4 entrance] done: intent={pi.get('l1', '?')}/{pi.get('l2', '?')}, "
            f"clarify={data.get('needs_clarification')}"
        )
    return result


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("V4 entrance 测试")
    print("=" * 60)
    test_msgs = [{"role": "user", "content": "我想查一下我的保单"}]
    result = entrance(test_msgs, debug=True)
    print("\n>>> V4 entrance 返回:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
