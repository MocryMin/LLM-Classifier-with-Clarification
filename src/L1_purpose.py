"""
L1 意图路由层 (Purpose Router)

单次 LLM 调用：将全部意图定义 + 对话历史一次性输入大模型，
LLM 同时完成意图分类 + 澄清判断 + 澄清话术生成。
"""
import os
import json
import re
from openai import OpenAI

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

def _parse_response(response):
    """解析 LLM 输出的 JSON，含容错处理"""
    text = response.strip()

    # 去掉 markdown code block
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 容错：尝试提取关键信息
    result = {
        'primary_intent': {'l1': '', 'l2': '', 'confidence': 0.0},
        'top_candidates': [],
        'needs_clarification': True,
        'clarification': {
            'level': None,
            'question': '您的问题我需要进一步确认，请告诉我更多信息？',
            'options': [],
            'target_slots': [],
        },
        'reason': 'JSON parse error, fallback',
    }

    # 尝试匹配 needs_clarification
    if '"needs_clarification": false' in text.lower() or '"needs_clarification":false' in text.lower():
        result['needs_clarification'] = False
        result['clarification'] = {
            'level': None,
            'question': None,
            'options': [],
            'target_slots': [],
        }

    return result


# ============================================================
# 主入口：一次调用，全部搞定
# ============================================================

def purpose_route(messages):
    """
    L1 意图路由 —— 单次 LLM 调用完成意图分类 + 澄清判断 + 澄清话术生成。

    Args:
        messages: list[dict], OpenAI 格式的完整对话历史

    Returns:
        dict: {
            'primary_intent': {'l1': str, 'l2': str, 'confidence': float},
            'top_candidates': [{'l1': str, 'l2': str, 'probability': float}, ...],
            'needs_clarification': bool,
            'clarification': {
                'level': 'L1'|'L2'|'slot'|'multi_intent'|None,
                'question': str|None,
                'options': [str, ...],
                'target_slots': [str, ...],
            },
            'reason': str,
        }
    """
    conversation = _format_messages(messages)
    template = _load_prompt()
    full_prompt = template.format(conversation=conversation)

    response = _ask(
        [{"role": "user", "content": full_prompt}],
        thinking='enabled',  # 意图路由需要深度思考
    )

    result = _parse_response(response)
    return result


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    test_cases = [
        [{"role": "user", "content": "你好"}],
        [{"role": "user", "content": "帮我查一下"}],
        [{"role": "user", "content": "我要买车险，帮我报个价"}],
        [{"role": "user", "content": "我的车被撞了，要报案"}],
        [{"role": "user", "content": "退保和理赔一起处理"}],
        [{"role": "user", "content": "蓝医保怎么样"}],
        [{"role": "user", "content": "我的保单贷款利息是多少"}],
        [{"role": "user", "content": "我要投诉你们"}],
        [{"role": "user", "content": "车在路上抛锚了，需要拖车"}],
    ]

    for i, msgs in enumerate(test_cases):
        print(f"\n{'='*60}")
        print(f"Test {i+1}: {msgs[0]['content']}")
        result = purpose_route(msgs)
        pi = result['primary_intent']
        print(f"  意图: {pi['l1']} > {pi['l2']} (confidence={pi['confidence']:.2f})")
        print(f"  需要澄清: {result['needs_clarification']}")
        if result['needs_clarification'] and result.get('clarification'):
            c = result['clarification']
            print(f"  澄清层级: {c.get('level')}")
            print(f"  澄清话术: {c.get('question')}")
            if c.get('options'):
                print(f"  选项: {c['options']}")
        print(f"  理由: {result['reason']}")
