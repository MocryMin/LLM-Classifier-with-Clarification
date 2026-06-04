"""
┌─────────────────────────────────────────────────────────────────────────────┐
│                    entrance.py — 智能管家路由层统一入口                       │
│                    项目唯一对外接口 · Agent 协同规范                           │
└─────────────────────────────────────────────────────────────────────────────┘

=== 概述 =====================================================================

  本模块是"智能管家"项目的顶层路由入口 — 所有外部调用者只需调用一个函数：
  `entrance(messages)`，即可完成 L0 → L1 全链路处理。

  调用者无需了解 L0 / L1 的内部实现，只需传入标准 messages 列表，根据返回
  的 case 值分流处理即可。

=== 调用方式 =================================================================

      from entrance import entrance

      result = entrance(messages)               # 最简调用（阈值 0.7）
      result = entrance(messages, l0_threshold=0.5)  # 放宽拦截阈值
      result = entrance(messages, debug=True)   # 打印全链路调试日志

=== 输入 =====================================================================

  messages : list[dict]    （必填）OpenAI 格式完整对话历史

    每条消息格式：
      {"role": "user",       "content": "我要转人工"}
      {"role": "assistant",  "content": "您好，请问有什么可以帮您？"}

    约束：
      - role 为 "user" 或 "assistant"；"system" 会被内部跳过
      - 按时间顺序排列，最后一条为最新消息
      - 长度无限制，但建议截取最近 20 轮以控制 LLM 上下文

  l0_threshold : float = 0.7  （可选）L0 拦截灵敏度

    阈值越低越敏感 —— 更多对话被判定为"需升级人工"而提前拦截：
      0.7  推荐值：高置信拦截，兼顾精确率和召回率
      0.5  宽松值：宁可多拦不漏，适用于安全优先场景
      0.3  仅供参考：几乎全部拦截

  debug : bool = False        （可选）是否打印全链路调试日志

=== 流水线 ===================================================================

  调用 entrance() 后，内部自动完成以下两步：

    ┌─────────────────────┐
    │  ① L0 跨场景标记检测  │  tag_judge_v2(messages)
    │     ~22 次 API 调用   │  并行检测 5 个标签（manual / angry / sad / urgent / non_biz）
    └──────┬──────────────┘
           │
     ┌─────▼─────┐
     │ 任一标签   │   标签值 ∈ [0, 1]，以 0.7 为拦截阈值
     │ ≥ 阈值 ?   │
     └──┬─────┬──┘
        │ YES │ NO
        ▼     ▼
    ┌───────────────┐   ┌──────────────────────────────┐
    │ ②a 升级处置    │   │ ②b L1 意图路由               │
    │   ~1 次调用    │   │   ~2 次调用（含 JSON 重试）    │
    │ escalation LLM │   │   purpose_route(messages)   │
    └───────┬───────┘   └──────────────┬───────────────┘
            ▼                          ▼
     return {case: 0, ...}       return {case: 1, ...}

=== 返回 =====================================================================

  统一返回格式：{"case": 0|1, "data": {...}}

  ── case = 0 ── L0 拦截 → 升级人工处置 ─────────────────────────────────────

      {
        "case": 0,
        "data": {
          "call_body":       "###tool_call(human_intervention_api)",
          "situation_brief": "<向人工坐席的情景快速披露，2-4 句中文>",
          "user_comfort":    "<面向用户的安抚话语，2-4 句中文，客服口吻>",
          "l0_tags":         {"manual": 1.0, "angry": 0.93, "sad": 0.04,
                              "urgent": 0.04, "non_biz": 0.0}
        }
      }

      字段说明：
        call_body       : str   固定值，标记调用人工介入接口（demo 简化）
        situation_brief : str   向接手的人工坐席简述：用户是谁/发生了什么/
                                系统检测到什么异常/建议关注点
        user_comfort    : str   以客服"小保"口吻安抚用户，体现共情，同时告知
                                已安排人工处理。根据触发标签和情绪程度自适应
        l0_tags         : dict  5 个 L0 标签的原始 01 概率值，供上层调试/日志

      触发该分支的 L0 标签（任一 ≥ 阈值即触发）：
        manual  ≥ threshold  → 用户 ≥2 次表达转人工意图
        angry   ≥ threshold  → 愤怒/不满情绪
        sad     ≥ threshold  → 悲伤情绪
        urgent  ≥ threshold  → 紧急语境
        non_biz ≥ threshold  → 非业务闲聊

  ── case = 1 ── L0 通过 → L1 意图路由 ───────────────────────────────────────

      {
        "case": 1,
        "data": {
          "primary_intent": {
            "l1": "售前服务",          // 一级意图  (6 大类之一)
            "l2": "车险投保",          // 二级意图  (30 个子场景之一)
            "confidence": 0.95        // 置信度 [0, 1]
          },
          "top_candidates": [          // 概率 >0.1 的候选意图，按降序
            {"l1": "售前服务", "l2": "车险投保", "probability": 0.95}
          ],
          "needs_clarification": true, // 是否需要向用户发起澄清
          "slots": {                   // needs_clarification=true 时有意义
            "all_slots": [             // 当前场景全部待填槽位
              {"name": "车牌号",
               "description": "车辆牌照号码",
               "options": []}          // options 为空表示自由文本
            ],
            "filled_slots": {          // 对话中已提取的值
              "保障需求": "交强险+商业险"
            },
            "missing_slots": ["车牌号", "车型年份", "使用性质"]
          },
          "operation": {
            "type": "clarify_slots"    // 操作类型：
                  // clarify_L1      — 一级大类不明确，需展示 5 大选项
                  // clarify_slots   — 意图已定，缺槽位需收集
                  // direct_reply    — 集团直接答复（文本）
                  // route_to_subsidiary — 路由子公司（含 ###tool_call）
                  // fallback        — 未覆盖兜底
            "detail": "意图已确认为车险投保，收集全部槽位后调用报价接口"
          },
          "user_output": "好的，小保帮您准备车险报价..."  // 面向用户的输出文本
                                                          // 可能内含 ###tool_call(xxx)
          "reason": "用户明确说要买车险并请求报价"
        }
      }

      注意：L1.data 结构与 L1_purpose.purpose_route() 原始返回值完全一致，
      详见 src/L1_purpose.py 的入口文档。

=== 协同 agent 快速指南 =======================================================

  本文件是项目的唯一对外接口。其他模块 / agent 调用时只需：

      # 1. 导入
      from entrance import entrance

      # 2. 调用
      result = entrance(messages)

      # 3. 按 case 分流
      if result["case"] == 0:
          # L0 拦截 → 升级人工
          handle_escalation(result["data"]["call_body"],
                            result["data"]["situation_brief"],
                            result["data"]["user_comfort"])
      else:
          # L0 通过 → 走 L1 意图路由
          dispatch(result["data"]["operation"]["type"],
                   result["data"]["user_output"])

=== 依赖链 ===================================================================

  entrance.py
   ├── src/L0_tag_judge.py  ── tag_judge_v2(messages) → dict[5 个 float]
   │    └── prompt/tag_*.txt  (5 个判别性标签 prompt)
   ├── src/L1_purpose.py    ── purpose_route(messages) → dict[L1 完整结果]
   │    └── prompt/L1_intent_router.txt
   └── prompt/escalation.txt ── 升级处置 LLM prompt（本模块内用）

  LLM:
    L0 判别性标签:  deepseek-v4-flash (×~20)
    L1 意图路由:    deepseek-v4-pro   (×~2)
    升级处置:       deepseek-v4-flash (×1)

=== 配置 =====================================================================

  API key / base_url 修改处：本文件顶部 client = OpenAI(...) 行。
  拦截阈值默认值修改处：entrance() 函数签名的 l0_threshold 参数。

=== 测试 =====================================================================

      python src/entrance.py

  运行 3 组内置测试用例（正常业务 / 转人工 / 紧急救援），直接输出入口原始返回。
"""

import os
import sys
import json
import re

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI
from L0_tag_judge import tag_judge_v2, _format_messages
from L1_purpose import purpose_route

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
# L0 拦截判定
# ============================================================

def _check_l0_intercept(l0_result, threshold=0.5):
    """
    检查 L0 结果是否触发拦截。

    拦截条件（任一标签概率 ≥ threshold 即触发）：
      - manual  ≥ threshold  → 用户多次表达转人工意图
      - angry   ≥ threshold  → 愤怒/不满情绪
      - sad     ≥ threshold  → 悲伤情绪
      - urgent  ≥ threshold  → 紧急语境
      - non_biz ≥ threshold  → 非业务闲聊

    Args:
        l0_result: dict, tag_judge_v2 的返回值
        threshold: float, 拦截阈值，默认 0.7

    Returns:
        tuple: (should_intercept: bool, triggered_tags: list[str])
    """
    triggered = []
    for tag in ['manual', 'angry', 'sad', 'urgent', 'non_biz']:
        if l0_result.get(tag, 0.0) >= threshold:
            triggered.append(tag)
    return len(triggered) > 0, triggered


# ============================================================
# 升级处置智能体（L0 拦截后调用）
# ============================================================

def _escalate_to_human(messages, l0_result, triggered_tags, debug=False):
    """
    升级处置智能体：接收被 L0 拦截的对话和标签结果，
    调用 LLM 生成人工介入请求体和情景快速披露。

    智能体职责：
      1. 生成 call_body — 调用接入人工接口的请求体
      2. 生成 situation_brief — 向人工坐席提供情景快速披露

    Args:
        messages:       list[dict], 原始对话消息
        l0_result:      dict, L0 完整检测结果
        triggered_tags: list[str], 触发的标签列表
        debug:          bool, 是否输出调试信息

    Returns:
        dict: {"call_body": {...}, "situation_brief": "..."}
    """
    # 构建触发标签的描述文本
    triggered_lines = []
    for tag in triggered_tags:
        prob = l0_result.get(tag, 0.0)
        desc = _TAG_CN.get(tag, tag)
        triggered_lines.append(f"  - {desc}：置信度 {prob:.2f}")

    triggered_summary = '\n'.join(triggered_lines)
    l0_full = json.dumps(l0_result, ensure_ascii=False)

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
# 主入口
# ============================================================

def entrance(messages, l0_threshold=0.7, debug=False):
    """
    智能管家路由层统一入口。

    流程：
      1. L0 跨场景标记检测 (tag_judge_v2)
      2. 任一标签 ≥ threshold → 拦截，升级处置 → case=0
      3. 全部标签 < threshold → 通过，意图路由 → case=1

    Args:
        messages:     list[dict], OpenAI 格式完整对话历史
        l0_threshold: float, L0 拦截阈值（默认 0.7）
        debug:        bool, 是否打印调试信息

    Returns:
        dict: {
            "case": 0 | 1,
            "data": {
                # case=0: {"call_body": {...}, "situation_brief": "..."}
                # case=1: { L1 purpose_route 完整返回 }
            }
        }

    Example:
        >>> result = entrance([{"role": "user", "content": "我要买车险"}])
        >>> print(result["case"])  # 1
        >>> print(result["data"]["primary_intent"]["l2"])  # "车险投保"
    """
    if debug:
        print(f'[entrance] 收到 {len(messages)} 条消息')

    # ---- Step 1: L0 跨场景标记检测 ----
    if debug:
        print('[entrance] Step 1: 调用 L0 tag_judge_v2 ...')

    l0_result = tag_judge_v2(messages)

    if debug:
        print(f'[entrance] L0 结果: {json.dumps(l0_result, ensure_ascii=False)}')

    # ---- Step 2: 检查是否触发 L0 拦截 ----
    should_intercept, triggered_tags = _check_l0_intercept(l0_result, l0_threshold)

    if should_intercept:
        if debug:
            print(f'[entrance] L0 拦截触发! 触发标签: {triggered_tags}')
            print('[entrance] Step 2a: 路由至升级处置智能体 ...')

        # ---- 拦截路径：升级处置 ----
        escalation_data = _escalate_to_human(messages, l0_result, triggered_tags, debug=debug)
        escalation_data["l0_tags"] = l0_result

        return {
            "case": 0,
            "data": escalation_data,
        }

    # ---- Step 3: L0 通过，调用 L1 ----
    if debug:
        print('[entrance] L0 通过 (无标签触发)')
        print('[entrance] Step 2b: 调用 L1 purpose_route ...')

    l1_result = purpose_route(messages, debug=debug)

    if debug:
        pi = l1_result.get('primary_intent', {})
        op = l1_result.get('operation', {})
        print(f'[entrance] L1 完成: {pi.get("l1", "?")} > {pi.get("l2", "?")} '
              f'(confidence={pi.get("confidence", 0):.2f}), '
              f'operation={op.get("type", "?")}')

    return {
        "case": 1,
        "data": l1_result,
    }


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("entrance 函数测试")
    print("=" * 70)

    # ----------------------------------------------------------
    # 测试1: 正常业务对话 → 预期 case=1
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试1: 正常业务对话（预期 case=1，走 L1 意图路由）")
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
    print("测试2: 转人工场景（预期 case=0，L0 拦截 → 升级处置）")
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
    # 测试3: 紧急道路救援 → 预期 case=1（走 L1），但如果 angry/urgent
    #         被触发则可能 case=0，属于正常的分流行为
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试3: 紧急救援请求（预期由 L0 判定是否拦截）")
    print("=" * 70)

    test_msgs_3 = [
        {"role": "user", "content": "我的车在高速上抛锚了，快帮我叫救援！！！"},
    ]

    result3 = entrance(test_msgs_3, debug=True)
    print("\n>>> entrance 返回 (测试3):")
    print(json.dumps(result3, ensure_ascii=False, indent=2))

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
