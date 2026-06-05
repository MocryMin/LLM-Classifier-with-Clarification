"""
┌─────────────────────────────────────────────────────────────────────────────┐
│                    entrance.py — 智能管家路由层统一入口 (V2)                  │
│                    项目唯一对外接口 · 四阶段管道编排                            │
└─────────────────────────────────────────────────────────────────────────────┘

=== V2 管道 ==================================================================

  messages
      │
      ▼
  ┌──────────────┐  ┌──────────────┐
  │ Stage 0: L0   │  │ Stage 1: L1   │  ← 并行
  │ tag_judge_v2  │  │ purpose_route │
  └──────┬───────┘  └──────┬───────┘
         └────────┬────────┘
                  ▼
         ┌───────────────┐
         │ Stage 2: Risk  │  ← 规则引擎
         │ assess_risk    │
         └──────┬────────┘
                ▼
         ┌───────────────┐
         │ Stage 3:       │  ← 三级回复分派
         │ dispatch       │
         └──────┬────────┘
                ▼
         PipelineResult

=== 调用方式 =================================================================

      from entrance import entrance

      result = entrance(messages)
      result = entrance(messages, l0_threshold=0.5)
      result = entrance(messages, debug=True)

=== 返回 =====================================================================

  统一格式: {"case": 0|1|2, "risk_level": ..., "response_mode": ..., "data": {...}}
  与V1向后兼容 — case字段保留，data字段扩展。
"""

import os
import sys
import json
import re
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI
from L0_tag_judge import tag_judge_v2, _format_messages, build_l0_output
from L1_purpose import purpose_route, build_l1_output
from L2_risk_assess import assess_risk
from L3_response_dispatch import dispatch_by_risk, get_region
from pipeline_types import (
    L0Output, L1Output, RiskOutput, DispatchResult, PipelineResult,
    make_safe_l0, make_safe_risk, make_safe_dispatch,
)

client = OpenAI(
    api_key="sk-6172dca8aeb0461a8b84cc8bcac0f9e8",
    base_url="https://api.deepseek.com",
)

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'prompt')
_ESCALATION_PROMPT_FILE = os.path.join(_PROMPT_DIR, 'escalation.txt')

_escalation_prompt = None

# ============================================================
# 标签中文描述
# ============================================================

_TAG_CN = {
    'manual':  '人工标记（用户多次要求转人工）',
    'angry':   '愤怒/不满情绪',
    'sad':     '悲伤情绪',
    'urgent':  '紧急语境',
    'non_biz': '非业务闲聊',
}


# ============================================================
# 基础 LLM 调用
# ============================================================

def _ask(messages, thinking='enabled', max_retries=5):
    """调用 DeepSeek API，带重试机制"""
    sign = 1
    retries = 0
    while sign and retries < max_retries:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            stream=False,
            max_tokens=100000,
            extra_body={"thinking": {"type": thinking}},
        )
        if response.choices[0].message.content:
            sign = 0
        else:
            retries += 1
            print(f'[escalation] no answer, retrying... ({retries}/{max_retries})')
    return response.choices[0].message.content


# ============================================================
# Prompt 管理
# ============================================================

def _load_escalation_prompt():
    """加载升级处置 prompt 模板（惰性加载 + 缓存）"""
    global _escalation_prompt
    if _escalation_prompt is None:
        with open(_ESCALATION_PROMPT_FILE, 'r', encoding='utf-8') as f:
            _escalation_prompt = f.read()
    return _escalation_prompt


# ============================================================
# JSON 解析
# ============================================================

def _parse_escalation_json(text):
    """
    解析升级处置智能体的 JSON 输出。
    容错处理：去掉 markdown 标记，解析失败时构造兜底结果。
    """
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    try:
        data = json.loads(text)
        return {
            'call_body': data.get('call_body', '###tool_call(human_intervention_api)'),
            'situation_brief': data.get('situation_brief', '（解析失败）'),
            'user_comfort': data.get('user_comfort', '小保已收到您的消息，正在为您优先处理。'),
        }, True
    except json.JSONDecodeError:
        return _make_fallback_escalation(text), False


def _make_fallback_escalation(raw_text=''):
    """升级处置解析失败时的兜底结果"""
    brief = raw_text[:300].replace('\n', ' ') if raw_text else '系统检测到需要人工介入，但自动生成情形简述失败。'
    return {
        'call_body': '###tool_call(human_intervention_api)',
        'situation_brief': brief,
        'user_comfort': '小保已收到您的消息，正在为您优先处理，请稍候。',
    }


# ============================================================
# L0 拦截判定（V2：仅 manual 触发升级处置）
# ============================================================

def _check_l0_intercept(l0: L0Output):
    """
    检查是否触发人工升级处置。

    V2变更：只有 manual 触发立即拦截升级。
    angry/urgent/sad/non_biz 不再走升级处置流程，
    而是由 Stage 2 风险评估和 Stage 3 分派处理。

    Returns:
        tuple: (should_intercept: bool, triggered_tags: list[str])
    """
    triggered = []
    for tag_type, tag in l0.tags.items():
        if tag.triggered:
            triggered.append(tag_type)
    should_intercept = l0.should_escalate  # manual触发
    return should_intercept, triggered


# ============================================================
# 升级处置智能体（L0 manual 拦截后调用）
# ============================================================

def _escalate_to_human(messages, l0, triggered_tags, debug=False):
    """
    升级处置智能体：接收被 L0 拦截的对话和标签结果，
    调用 LLM 生成人工介入请求体和情景快速披露。

    V2适配：传入tag类型信息，prompt根据tag类型选择安抚策略。
    """
    # 构建触发标签的描述文本（含tag类型信息）
    triggered_lines = []
    for tag_type in triggered_tags:
        tag = l0.tags.get(tag_type)
        if tag:
            desc = _TAG_CN.get(tag_type, tag_type)
            triggered_lines.append(
                f"  - [{tag_type}] {desc}：置信度 {tag.probability:.2f}"
            )

    triggered_summary = '\n'.join(triggered_lines)
    l0_full = json.dumps(l0.raw_probabilities, ensure_ascii=False)

    # 对话文本
    conversation = _format_messages(messages)

    # 填充 prompt
    prompt_template = _load_escalation_prompt()
    full_prompt = prompt_template.format(
        triggered_summary=triggered_summary,
        l0_full_result=l0_full,
        conversation=conversation,
    )

    if debug:
        print(f'[escalation] 触发标签:\n{triggered_summary}')

    # 调用 LLM
    raw = _ask([{"role": "user", "content": full_prompt}], thinking='enabled')

    if debug:
        print(f'[escalation] LLM 原始输出:\n{raw}')

    result, ok = _parse_escalation_json(raw)

    if not ok:
        print('[escalation] JSON 解析失败，使用兜底结果')

    return result


# ============================================================
# 结果构建辅助
# ============================================================

def _build_tag_dispositions(l0: L0Output) -> dict:
    """构建 tag_dispositions 序列化字典"""
    return {
        tag_type: {
            "action": tag.action,
            "probability": tag.probability,
            "triggered": tag.triggered,
        }
        for tag_type, tag in l0.tags.items()
    }


def _build_decision_trail(risk: RiskOutput) -> list[dict]:
    """构建 decision_trail 序列化列表"""
    return [
        {
            "step": d.step,
            "input_value": d.input_value,
            "result": d.result,
            "reason": d.reason,
        }
        for d in risk.decision_trail
    ]


# ============================================================
# 主入口
# ============================================================

def entrance(messages, l0_threshold=0.7, debug=False, region=None):
    """
    智能管家路由层统一入口 (V2 Pipeline)。

    流程：
      Stage 0 ∥ Stage 1 → Stage 2 → Stage 3 → PipelineResult

    Args:
        messages:     list[dict], OpenAI 格式完整对话历史
        l0_threshold: float, L0 拦截阈值（默认 0.7）
        debug:        bool, 是否打印调试信息
        region:       str | None, "pilot" 或 "non_pilot"。
                      None时自动从上下文判定（当前默认non_pilot）

    Returns:
        dict: {
            "case": 0 | 1 | 2,
            "risk_level": str | None,
            "response_mode": str,
            "tag_dispositions": dict,
            "decision_trail": list[dict],
            "data": {...}
        }
    """
    if debug:
        print(f'[entrance] V2 Pipeline: {len(messages)} 条消息')

    effective_region = region or get_region()

    # ---- Stage 0 ∥ Stage 1 并行发射 ----
    if debug:
        print('[entrance] Stage 0 (L0) ∥ Stage 1 (L1) 并行发射 ...')

    l0: L0Output = make_safe_l0()
    l1: L1Output = None
    risk: RiskOutput = make_safe_risk()
    dispatch: DispatchResult = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_l0 = executor.submit(tag_judge_v2, messages)
        future_l1 = executor.submit(purpose_route, messages, debug)

        # ---- 等待 Stage 0 (L0) 先返回 ----
        try:
            raw_l0 = future_l0.result(timeout=30)
            l0 = build_l0_output(raw_l0, l0_threshold)
        except Exception as e:
            if debug:
                print(f'[entrance] Stage 0 异常: {e}，使用安全默认值')
            l0 = make_safe_l0()

        if debug:
            triggered = [t for t, tag in l0.tags.items() if tag.triggered]
            print(f'[entrance] L0 完成: 触发标签={triggered or "无"}')
            for t, tag in l0.tags.items():
                if tag.probability > 0.1:
                    print(f'  {t}: {tag.probability:.2f} (action={tag.action})')

        # ---- 检查 manual 拦截 (case=0) ----
        should_intercept, triggered_tags = _check_l0_intercept(l0)

        if should_intercept:
            if debug:
                print(f'[entrance] L0 manual拦截! → case=0')

            # 升级处置
            escalation_data = _escalate_to_human(
                messages, l0, triggered_tags, debug=debug
            )
            escalation_data["l0_tags"] = {
                t: tag.probability for t, tag in l0.tags.items()
            }

            return {
                "case": 0,
                "risk_level": "high",
                "response_mode": "faq_only_human",
                "tag_dispositions": _build_tag_dispositions(l0),
                "decision_trail": [],
                "data": escalation_data,
            }

        # ---- 检查 urgent 直通 (case=2) ----
        if l0.should_skip_risk:
            if debug:
                print('[entrance] L0 urgent触发! → case=2，跳过风险评估')

            # 等待 L1
            try:
                raw_l1 = future_l1.result(timeout=60)
                l1 = build_l1_output(raw_l1)
            except Exception as e:
                if debug:
                    print(f'[entrance] Stage 1 异常: {e}，使用兜底')
                l1 = build_l1_output({})

            # 紧急：跳过风险评估，直接操作指引
            dispatch = dispatch_by_risk(l0, l1, make_safe_risk(),
                                        effective_region, debug)

            return {
                "case": 2,
                "risk_level": None,
                "response_mode": dispatch.response_mode,
                "tag_dispositions": _build_tag_dispositions(l0),
                "decision_trail": [],
                "data": {
                    "user_output": dispatch.user_output,
                    "escalate_to_human": dispatch.escalate_to_human,
                    "primary_intent": l1.primary_intent,
                    "tool_calls": dispatch.tool_calls,
                    "reason": "紧急标记触发，跳过澄清和风险评估，直接推送操作指引",
                },
            }

        # ---- 等待 Stage 1 (L1) ----
        if debug:
            print('[entrance] L0 通过，等待 L1 ...')

        try:
            raw_l1 = future_l1.result(timeout=60)
            l1 = build_l1_output(raw_l1)
        except Exception as e:
            if debug:
                print(f'[entrance] Stage 1 异常: {e}，使用兜底')
            l1 = build_l1_output({})

    # ---- Stage 2: 风险评估 ----
    if debug:
        print('[entrance] Stage 2: 风险评估 ...')

    try:
        risk = assess_risk(l0, l1, messages, debug=debug)
    except Exception as e:
        if debug:
            print(f'[entrance] Stage 2 异常: {e}，使用安全默认值')
        risk = make_safe_risk()

    # ---- Stage 3: 回复分派 ----
    if debug:
        print(f'[entrance] Stage 3: 回复分派 (risk={risk.risk_level}, '
              f'mode={risk.response_mode}, region={effective_region}) ...')

    try:
        dispatch = dispatch_by_risk(l0, l1, risk, effective_region, debug)
    except Exception as e:
        if debug:
            print(f'[entrance] Stage 3 异常: {e}，使用安全默认值')
        dispatch = make_safe_dispatch(l1)

    # ---- 构建返回 ----
    if debug:
        pi = l1.primary_intent or {}
        print(f'[entrance] 完成: case=1, '
              f'scene={pi.get("l2", "?")}, '
              f'risk={risk.risk_level}, '
              f'mode={dispatch.response_mode}, '
              f'audit={dispatch.audit_required}')

    return {
        "case": 1,
        "risk_level": risk.risk_level,
        "response_mode": dispatch.response_mode,
        "tag_dispositions": _build_tag_dispositions(l0),
        "decision_trail": _build_decision_trail(risk),
        "data": {
            "primary_intent": l1.primary_intent,
            "top_candidates": l1.top_candidates,
            "needs_clarification": l1.needs_clarification,
            "slots": {
                "all_slots": [
                    {"name": s.name, "description": s.description, "options": s.options}
                    for s in (l1.slots.all_slots if l1.slots else [])
                ],
                "filled_slots": l1.slots.filled_slots if l1.slots else {},
                "missing_slots": l1.slots.missing_slots if l1.slots else [],
            },
            "operation": l1.operation,
            "user_output": dispatch.user_output,
            "reason": l1.reason,
            "faq_matched": dispatch.faq_matched,
            "audit_required": dispatch.audit_required,
            "recommendation": dispatch.recommendation,
            "tool_calls": dispatch.tool_calls,
        },
    }


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("entrance V2 Pipeline 测试")
    print("=" * 70)

    # ----------------------------------------------------------
    # 测试1: 正常业务对话 → 预期 case=1
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试1: 正常业务对话（预期 case=1）")
    print("=" * 70)

    test_msgs_1 = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好，我是智能管家小保，很高兴为您服务！"},
        {"role": "user", "content": "我想买车险，帮我报个价"},
    ]

    result1 = entrance(test_msgs_1, debug=True)
    print("\n>>> entrance 返回 (测试1):")
    print(json.dumps(result1, ensure_ascii=False, indent=2))

    # ----------------------------------------------------------
    # 测试2: 转人工场景 → 预期 case=0
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试2: 转人工场景（预期 case=0）")
    print("=" * 70)

    test_msgs_2 = [
        {"role": "user", "content": "转人工"},
        {"role": "assistant", "content": "请问有什么可以帮您的吗？"},
        {"role": "user", "content": "我说了转人工！听不懂人话吗？"},
    ]

    result2 = entrance(test_msgs_2, debug=True)
    print("\n>>> entrance 返回 (测试2):")
    print(json.dumps(result2, ensure_ascii=False, indent=2))

    # ----------------------------------------------------------
    # 测试3: 紧急救援 → 可能 case=2 (urgent触发) 或 case=1
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试3: 紧急救援请求")
    print("=" * 70)

    test_msgs_3 = [
        {"role": "user", "content": "我的车在高速上抛锚了，快帮我叫救援！！！"},
    ]

    result3 = entrance(test_msgs_3, debug=True)
    print("\n>>> entrance 返回 (测试3):")
    print(json.dumps(result3, ensure_ascii=False, indent=2))

    # ----------------------------------------------------------
    # 测试4: V2 核保场景
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试4: V2 核保场景（预期 scene=核保, risk=high）")
    print("=" * 70)

    test_msgs_4 = [
        {"role": "user", "content": "我有糖尿病，能买重疾险吗"},
    ]

    result4 = entrance(test_msgs_4, debug=True)
    print("\n>>> entrance 返回 (测试4):")
    pi = result4.get("data", {}).get("primary_intent", {})
    print(f"  case={result4['case']}, risk={result4['risk_level']}, "
          f"scene={pi.get('l2')}, mode={result4['response_mode']}")
    print(f"  user_output: {result4['data'].get('user_output', '')[:150]}")

    # ----------------------------------------------------------
    # 测试5: 本人推论（不应问"给谁买"）
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试5: 本人推论（预期 filled_slots.被保人关系=本人）")
    print("=" * 70)

    test_msgs_5 = [
        {"role": "user", "content": "我35岁，身体有点高血压，想买个医疗险"},
    ]

    result5 = entrance(test_msgs_5, debug=False)
    print("\n>>> entrance 返回 (测试5):")
    slots = result5.get("data", {}).get("slots", {})
    print(f"  filled_slots: {slots.get('filled_slots', {})}")
    print(f"  missing_slots: {slots.get('missing_slots', [])}")
    print(f"  user_output: {result5['data'].get('user_output', '')[:200]}")

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
