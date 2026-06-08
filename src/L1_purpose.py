"""
L1 意图路由层 (Purpose Router)
================================

单次 LLM 调用，完成：
  意图分类 → 意图澄清（仅当竞争激烈时）→ 路由输出。

V2.1 架构变更：L1 只负责意图路由，不收集槽位。
槽位收集（被保人年龄/车牌号/健康信息等）由下层agent负责。

----
入口函数
----

    from L1_purpose import purpose_route
    result = purpose_route(messages, debug=False, max_json_retries=2)

参数:
    messages          : list[dict]   — OpenAI 格式完整对话历史
    debug             : bool         — True 时打印原始 LLM JSON (调试用)
    max_json_retries  : int          — JSON 解析失败时重试次数 (默认 2)

返回:
    dict {
        "primary_intent": {
            "l1": str,              # 一级意图  例: "售前服务"
            "l2": str,              # 二级意图  例: "车险投保"
            "confidence": float     # 置信度 [0,1]
        },
        "top_candidates": [         # 概率 >0.1 的候选意图
            {"l1": str, "l2": str, "probability": float}, ...
        ],
        "needs_clarification": bool, # 仅指意图竞争（非槽位澄清）
        "operation": {
            "type": str,            # direct_reply        — 集团直接答复
                                    # route_to_subsidiary — 路由子公司 (含 ###tool_call)
                                    # fallback            — 未覆盖兜底
            "detail": str           # 操作说明
        },
        "user_output": str,         # 面向用户的输出文本
                                    # 可能包含 ###tool_call(api_name) 标记
        "reason": str               # 判断依据 (1-2句)
    }

调用示例:
    result = purpose_route([
        {"role": "user", "content": "我要买车险，帮我报个价"}
    ])
    # result["operation"]["type"]   → "route_to_subsidiary"
    # result["user_output"]         → "...\n###tool_call(auto_insure_api)"

    result = purpose_route([
        {"role": "user", "content": "我的车被撞了，要报案"}
    ])
    # result["operation"]["type"]   → "route_to_subsidiary"
    # result["user_output"]         → "...\n###tool_call(claim_report_api)"

依赖:
    pip install openai
    prompt/L1_intent_router.txt  (prompt 模板，相对路径 ../prompt/)
"""
import os
import json
import re
import threading
from openai import OpenAI

# ── 外部可读的 parse 事件日志（供测试 runner 使用）──
# 使用 thread-local 保证多线程并发安全
_parse_state = threading.local()

def _parse_event_push(event: dict):
    if not hasattr(_parse_state, 'events'):
        _parse_state.events = []
    _parse_state.events.append(event)

def get_and_clear_parse_events() -> list[dict]:
    """返回并清空当前线程自上次调用以来记录的 parse 事件列表。"""
    events = getattr(_parse_state, 'events', None)
    if events is None:
        return []
    _parse_state.events = []
    return events

client = OpenAI(
    api_key="sk-6172dca8aeb0461a8b84cc8bcac0f9e8",
    base_url="https://api.deepseek.com",
)

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'prompt')
_PROMPT_FILE = os.path.join(_PROMPT_DIR, 'L1_intent_router.txt')

_prompt_template = None


def _load_prompt():
    """加载 prompt 模板（惰性加载 + 缓存）"""
    global _prompt_template
    if _prompt_template is None:
        with open(_PROMPT_FILE, 'r', encoding='utf-8') as f:
            _prompt_template = f.read()
    return _prompt_template


# ============================================================
# 基础 LLM 调用
# ============================================================

def _ask(messages, thinking='enabled', max_retries=5):
    """调用 DeepSeek API，带重试机制"""
    sign = 1
    retries = 0
    while sign and retries < max_retries:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream=False,
            max_tokens=100000,
            extra_body={"thinking": {"type": thinking}},
        )
        if response.choices[0].message.content:
            sign = 0
        else:
            retries += 1
            print(f'[L1] no answer, retrying... ({retries}/{max_retries})')
    return response.choices[0].message.content


# ============================================================
# 消息格式化
# ============================================================

def _format_messages(messages):
    """将 OpenAI 格式消息列表转换为可读对话文本"""
    lines = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        if role == 'system':
            continue
        elif role == 'user':
            lines.append(f"[用户] {content}")
        elif role == 'assistant':
            lines.append(f"[客服] {content}")
    return '\n'.join(lines)


# ============================================================
# 解析 LLM 输出的 JSON
# ============================================================

_FALLBACK_SIGNATURE = 'JSON parse error'


def _make_fallback_result(reason='JSON parse error, fallback'):
    """构造容错兜底结果"""
    return {
        'primary_intent': {'l1': '', 'l2': '', 'confidence': 0.0},
        'top_candidates': [],
        'needs_clarification': True,
        'operation': {
            'type': 'direct_reply',
            'detail': '解析失败，兜底回复',
        },
        'user_output': '小保没有完全理解您的需求，请换个方式描述一下您想咨询或办理的业务，好吗？',
        'reason': reason,
    }


def _is_fallback(result):
    """检查是否为兜底结果"""
    return _FALLBACK_SIGNATURE in result.get('reason', '')


def _sanitize_json_control_chars(text: str) -> str:
    """将 JSON 字符串值内的字面控制字符替换为转义序列。

    LLM 有时在 user_output 字段中输出真实换行符 U+000A（应为 \\n），
    这会导致 json.loads() 抛出 JSONDecodeError: Invalid control character。
    本函数模拟 JSON 解析器状态机，仅转换字符串内的控制字符。
    """
    result = []
    in_string = False
    escape_next = False
    for c in text:
        if escape_next:
            result.append(c)
            escape_next = False
            continue
        if c == '\\':
            result.append(c)
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == '\n':
                result.append('\\n')
            elif c == '\r':
                result.append('\\r')
            elif c == '\t':
                result.append('\\t')
            elif ord(c) < 32:
                result.append(f'\\u{ord(c):04x}')
            else:
                result.append(c)
        else:
            result.append(c)
    return ''.join(result)


def _extract_json_from_text(text):
    """从 LLM 输出中鲁棒提取 JSON 对象。
    三策略级联：fence 块提取 → 花括号边界 → 整段解析。
    每次 json.loads 前先做控制字符转义。"""
    t = text.strip()

    # 策略1：提取 ```json ... ``` 或 ``` ... ```（任意位置，不要求开头）
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', t, re.DOTALL)
    if m:
        try:
            return json.loads(_sanitize_json_control_chars(m.group(1).strip()))
        except json.JSONDecodeError:
            pass

    # 策略2：提取第一个 { 到最后一个 }
    first = t.find('{')
    last = t.rfind('}')
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(_sanitize_json_control_chars(t[first:last + 1]))
        except json.JSONDecodeError:
            pass

    # 策略3：整段解析
    try:
        return json.loads(_sanitize_json_control_chars(t))
    except json.JSONDecodeError:
        return None


def _try_parse_json(text):
    """尝试解析 LLM 输出为 JSON。返回 (result, success)。"""
    result = _extract_json_from_text(text)
    if result is None:
        return _make_fallback_result(), False

    result.setdefault('primary_intent', {'l1': '', 'l2': '', 'confidence': 0.0})
    result.setdefault('top_candidates', [])
    result.setdefault('needs_clarification', False)
    result.setdefault('operation', {'type': 'direct_reply', 'detail': ''})
    result.setdefault('user_output', '')
    result.setdefault('reason', '')
    return result, True


# ============================================================
# 主入口：一次调用，全部搞定
# ============================================================

def purpose_route(messages, debug=False, max_json_retries=2):
    """
    L1 意图路由 —— 单次 LLM 调用完成：
      意图分类 + 槽位提取 + 澄清判断 + 操作决策 + 用户输出生成。

    JSON 解析失败时会自动重试（最多 max_json_retries 次），
    全部失败后才使用兜底结果。

    Args:
        messages: list[dict], OpenAI 格式的完整对话历史
            例: [{"role": "user", "content": "我要买车险"}]
        debug: bool, 若为 True 则打印原始 LLM 返回（用于调试）
        max_json_retries: int, JSON 解析失败时的最大重试次数

    Returns:
        dict: 见函数内注释
    """
    conversation = _format_messages(messages)
    template = _load_prompt()
    full_prompt = template.replace('{conversation}', conversation)
    user_msg = [{"role": "user", "content": full_prompt}]

    for attempt in range(1 + max_json_retries):
        raw = _ask(user_msg, thinking='enabled')

        if debug:
            print(f'\n[L1 RAW JSON attempt {attempt+1}]:')
            print(raw)

        result, ok = _try_parse_json(raw)

        if ok:
            if attempt > 0:
                _parse_event_push({
                    'attempts': attempt + 1,
                    'status': 'retry_recovered',
                    'fallback': False,
                    'detail': f'first {attempt} failed, attempt {attempt+1} ok',
                })
            return result

        if attempt < max_json_retries:
            print(f'[L1] JSON parse failed, retrying... ({attempt+1}/{max_json_retries})')

    # 全部重试耗尽
    _parse_event_push({
        'attempts': 1 + max_json_retries,
        'status': 'full_failure',
        'fallback': True,
        'detail': 'all retries exhausted',
    })
    # 返回最后一次的兜底结果
    print('[L1] JSON parse failed after all retries, using fallback.')
    return result


# ============================================================
# V2 新增: L1Output 包装
# ============================================================

# 32场景→风险等级映射（与L2_risk_assess共享，此处独立维护以避免循环导入）
_SCENE_RISK_MAP = {
    "欢迎引导": "low", "意图澄清": "low", "未覆盖兜底": "low",
    "产品咨询": "low", "服务介绍": "low", "行权使用": "low",
    "高频权益": "low", "客服热线": "low",
    "健康险投保": "medium", "车险投保": "medium", "寿险/年金投保": "medium",
    "意外险投保": "medium", "其他险种投保": "medium", "明确产品": "medium",
    "承保/保单获取": "medium", "保单查询": "medium", "续期缴费": "medium",
    "保单变更": "medium", "理赔报案": "medium", "理赔进度查询": "medium",
    "权益查询": "medium", "业务员联系": "medium", "网点查询": "medium",
    "核保": "high", "核赔": "high", "退保/减保": "high",
    "保单贷款/还款": "high", "分红/年金/领取": "high", "保单复效": "high",
    "理赔材料/条件": "high", "撤销报案": "high", "投诉建议": "high",
}


def build_l1_output(raw_result: dict):
    """
    将 purpose_route 的原始 dict 返回包装为 L1Output。

    V2.1: L1不再负责槽位收集。即使LLM偶尔输出slots字段，也忽略。

    Args:
        raw_result: dict, purpose_route 的返回值

    Returns:
        L1Output
    """
    from pipeline_types import L1Output, SlotsInfo

    # 提取场景名
    scene = raw_result.get("primary_intent", {}).get("l2", "")

    # V2.1: L1 不收集槽位，始终返回空 SlotsInfo
    slots = SlotsInfo(all_slots=[], filled_slots={}, missing_slots=[])

    return L1Output(
        primary_intent=raw_result.get("primary_intent", {}),
        top_candidates=raw_result.get("top_candidates", []),
        needs_clarification=raw_result.get("needs_clarification", False),
        slots=slots,
        operation=raw_result.get("operation", {}),
        user_output=raw_result.get("user_output", ""),
        reason=raw_result.get("reason", ""),
        scene_risk_base=_SCENE_RISK_MAP.get(scene, "medium"),
    )


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    DEBUG = True  # 测试时输出原始 LLM JSON

    test_cases = [
        [{"role": "user", "content": "你好"},
         {"role": "assistant","content":"您好，我是智能管家小保，很高兴为您服务！请问有什么可以帮您？"},
         {"role":"user","content":"当然！"},
         {"role":"assistant","content":"小保可以帮您办理各类保险业务，您想咨询或办理哪一项呢？\n1. 售前咨询（了解/购买保险）\n2. 保单服务（查询/变更/续期/退保等）\n3. 理赔服务（报案/进度/材料等）\n4. 增值服务（道路救援/代驾/年检等）\n5. 客户服务（投诉/业务员/网点等）\n请告诉小保您需要的服务类型～"},
         {"role":"user","content":"我想办保险"},
         {"role":"assistant","content":"好的，小保可以帮您办理保险！您想了解哪方面的保险呢？比如人身寿险、医疗健康、意外保障，还是车险财产险？您可以告诉我，我为您详细介绍～"},
         {"role":"user","content":"我想买车险"},
         {"role":"assistant","content":"好的，小保帮您办理车险。为了给您精准的报价，请提供以下信息：\n1. 您的车牌号是多少？\n2. 车辆的品牌型号和购买年份？\n3. 车辆使用性质是私家车还是营运车？\n（其余信息稍后我会继续向您确认）"},
         {"role":"user","content":"车牌是前苏联114514，车是1945年的虎式坦克，军用车"},
         {"role":"assistant","content":"小保收到啦，这个车型还真是少见呢～ 为了给您安排精准的报价，还需要几个信息：\n1. 车主信息是和行驶证一致吗？\n2. 上一年有没有出过险呢？\n3. 您需要的保障是：仅交强险、交强险加商业险，还是小保帮您推荐合适的方案？"},
         {"role":"user","content":"车主是斯大林格勒，去年一直在博物馆里展出，没有出险，我需要小保推荐方案"},
         {"role":"assistant","content":"您的虎式坦克确实很特别～ 小保再跟您确认两个信息：\n1. 这辆车的使用性质是私家车还是营运车呢？\n2. 车主信息是和行驶证上的所有人一致吗？\n（确认后我会根据您的需求推荐合适的车险方案～）"},
         {"role":"user","content":"运营车，车主信息和行驶证一致"},
         ]
         
    ]

    for i, msgs in enumerate(test_cases):
        print(f"\n{'='*60}")
        label = msgs[0]['content'][:50] + '...' if len(msgs) > 1 else msgs[0]['content']
        print(f"Test {i+1}: {label}")
        result = purpose_route(msgs, debug=DEBUG)
        pi = result['primary_intent']
        op = result['operation']
        slots = result['slots']

        print(f"  意图: {pi['l1']} > {pi['l2']} (confidence={pi['confidence']:.2f})")
        print(f"  操作: {op['type']} | {op['detail']}")
        print(f"  需要澄清: {result['needs_clarification']}")

        if result['needs_clarification'] and slots.get('all_slots'):
            print(f"  全部槽位: {[s['name'] for s in slots['all_slots']]}")
            print(f"  已填: {slots['filled_slots']}")
            print(f"  缺失: {slots['missing_slots']}")

        user_out = result['user_output']
        print(f"  user_output: {user_out[:200]}{'...' if len(user_out)>200 else ''}")
        print(f"  理由: {result['reason']}")
