"""
v3/entrance.py — V3 路由层入口
===============================

V3 单阶段管道: L1 意图路由, 无 L0 标签检测, 无风险评估, 无回复分派。

返回格式遵循 GUI 约定优于配置协议:
  - *_level → 风险 badge (V3 固定 null)
  - *_mode  → 模式 badge (V3 固定 "v3")
  - data.*  → 业务数据自动发现

用法:
    from v3.entrance import entrance
    result = entrance(messages, debug=True)
"""

import json
from .L1_router import route as l1_route


def entrance(
    messages: list[dict],
    debug: bool = False,
) -> dict:
    """
    V3 入口 — 单阶段 L1 意图路由。

    Args:
        messages: OpenAI 格式对话历史
        debug:    打印调试信息

    Returns:
        {
            "case": 1,
            "risk_level": None,
            "response_mode": "v3",
            "tag_dispositions": {},
            "decision_trail": [],
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
        print(f"[V3 entrance] {len(messages)} messages")

    # 调用 L1
    try:
        l1_result = l1_route(messages, debug=debug)
    except Exception as e:
        if debug:
            print(f"[V3 entrance] L1 exception: {e}")
        l1_result = {
            "primary_intent": {"l1": "", "l2": "", "confidence": 0.0},
            "top_candidates": [],
            "needs_clarification": True,
            "user_output": "系统处理异常，请稍后重试或拨打95500客服热线。",
            "reason": f"L1 exception: {e}",
        }

    # 构建返回 — 遵循 GUI 约定优于配置协议
    result = {
        "case": 1,                    # V3 单 case: 正常路由
        "risk_level": None,           # V3 无风险评估
        "response_mode": "v3",        # GUI *_mode suffix → mode badge
        "tag_dispositions": {},       # 空, GUI 不展示
        "decision_trail": [],         # 空, GUI 不展示
        "data": {
            "primary_intent": l1_result.get("primary_intent", {}),
            "top_candidates": l1_result.get("top_candidates", []),
            "needs_clarification": l1_result.get("needs_clarification", False),
            "user_output": l1_result.get("user_output", ""),
            "reason": l1_result.get("reason", ""),
        },
    }

    if debug:
        pi = l1_result.get("primary_intent", {})
        print(
            f"[V3 entrance] done: "
            f"intent={pi.get('l1', '?')}/{pi.get('l2','?')}, "
            f"clarify={l1_result.get('needs_clarification')}"
        )

    return result


# ═══════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("V3 entrance 测试")
    print("=" * 60)

    test_msgs = [
        {"role": "user", "content": "我想查一下我的保单"},
    ]

    result = entrance(test_msgs, debug=True)
    print("\n>>> V3 entrance 返回:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
