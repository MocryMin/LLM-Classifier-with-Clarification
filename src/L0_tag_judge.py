import os
import json
import re
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

client = OpenAI(
    api_key="sk-6172dca8aeb0461a8b84cc8bcac0f9e8",
    base_url="https://api.deepseek.com")


# ============================================================
# 基础 LLM 调用
# ============================================================

def ask(messages, thE='disabled', max_retries=5):
    """调用 DeepSeek API，带重试机制。返回 response.content 字符串。"""
    sign = 1
    retries = 0
    while sign and retries < max_retries:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream=False,
            max_tokens=100000,
            extra_body={"thinking": {"type": thE}}
        )
        if response.choices[0].message.content:
            sign = 0
        else:
            retries += 1
            print(f'no answer, retrying... ({retries}/{max_retries})')
    return response.choices[0].message.content


# ============================================================
# 路径 & prompt 管理
# ============================================================

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'prompt')

_PROMPT_FILES = {
    'angry':   'tag_angry.txt',
    'sad':     'tag_sad.txt',
    'urgent':  'tag_urgent.txt',
    'non_biz': 'tag_non_biz.txt',
    'manual':  'tag_manual.txt',
}

# 需要 SC 验证的标签（manual 除外）
_SC_TAG_TYPES = ('angry', 'sad', 'urgent', 'non_biz')


def _load_prompt(tag_type):
    """加载指定类型的提示词模板"""
    fname = _PROMPT_FILES[tag_type]
    path = os.path.join(_PROMPT_DIR, fname)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# 消息格式化 & 轮次拆分
# ============================================================

def _format_messages(messages, include_system=False):
    """
    将 OpenAI 格式的消息列表转换为可读对话文本。
    跳过 system 消息（除非 include_system=True）。
    """
    lines = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        if role == 'system' and not include_system:
            continue
        elif role == 'user':
            lines.append(f"[用户] {content}")
        elif role == 'assistant':
            lines.append(f"[客服] {content}")
        elif role == 'system':
            lines.append(f"[系统] {content}")
    return '\n'.join(lines)


def _get_user_round_bounds(messages):
    """
    找出每条用户消息在 messages 列表中的索引。
    每条用户消息视为一轮对话的起点。

    Returns:
        list[int]: 各用户消息在 messages 中的索引
    """
    return [i for i, msg in enumerate(messages) if msg.get('role') == 'user']


# ============================================================
# LLM 回复解析（概率 & JSON）
# ============================================================

def _parse_probability_response(response):
    """
    解析 LLM 输出的 0-1 概率值。
    提示词要求 LLM 输出一个 0~1 之间的数字 p。

    容错策略：
      1. 查找文本中所有浮点数模式，取第一个落在 [0,1] 范围内的值
      2. 若不存在合法浮点数，查找独立的 0 或 1
      3. 兜底返回 0.0（安全侧：未检测到异常信号）

    Returns:
        float: [0, 1] 之间的概率值
    """
    text = response.strip()

    # 策略1：匹配所有浮点数 / 整数，取第一个在 [0,1] 内的
    matches = re.findall(r'(\d+\.?\d*|\.\d+)', text)
    for m in matches:
        try:
            val = float(m)
            if 0.0 <= val <= 1.0:
                return val
        except ValueError:
            continue

    # 策略2：找不到合法浮点数时，看文本是否包含独立的 1 或 0
    binary_matches = re.findall(r'\b([01])\b', text)
    if binary_matches:
        return float(binary_matches[-1])

    # 策略3：兜底
    if '1' in text:
        return 1.0
    return 0.0


def _parse_json_response(response):
    """
    解析 LLM 对人工标记的 JSON 回复。
    期望格式: {"hit": 1或0, "reason": "..."}
    容错处理。
    """
    text = response.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError:
        if '"hit": 1' in text or '"hit":1' in text:
            return {'hit': 1, 'reason': 'fallback parse'}
        elif '"hit": 0' in text or '"hit":0' in text:
            return {'hit': 0, 'reason': 'fallback parse'}
        return {'hit': 0, 'reason': 'parse error'}


# ============================================================
# 判别性标签检测（愤怒/不满、悲伤、紧急、非业务闲聊）
# 返回值已从 bool 改为 float [0,1]
# ============================================================

def detect_tag(messages, tag_type):
    """
    判别性标签检测：一次读取全部对话，返回存在目标标签的概率。

    用于以下标签：
      - 'angry'   : 愤怒/不满
      - 'sad'     : 悲伤
      - 'urgent'  : 紧急
      - 'non_biz' : 非业务闲聊

    Args:
        messages: list[dict], OpenAI 格式消息列表
        tag_type: str, 标签类型

    Returns:
        float: [0, 1] 之间的概率值（原为 bool，现改为概率）
    """
    if tag_type not in _SC_TAG_TYPES:
        raise ValueError(f"不支持的 tag_type: {tag_type}。可选: {_SC_TAG_TYPES}")

    prompt_template = _load_prompt(tag_type)
    conversation = _format_messages(messages)
    full_prompt = prompt_template.format(conversation=conversation)

    response = ask([{"role": "user", "content": full_prompt}], thE='enabled')
    return _parse_probability_response(response)


# ============================================================
# 人工标记检测（需 ≥2 次转人工意图）—— 逻辑保持不变
# ============================================================

def detect_manual_transfer(messages):
    """
    检测用户是否表达了 ≥2 次转人工/找真人/找领导的意图。

    采用逐轮检测方案（Approach B）：
      - 将对话按用户消息拆分为 N 轮
      - 对第 i 轮，将第 1 ~ i 轮的全部对话上下文输入 LLM
      - 询问 LLM：最新这一轮的用户消息是否表达了转人工意图
      - 若命中，计数器 +1；计数器达到 2 时立即返回 True

    Args:
        messages: list[dict], OpenAI 格式消息列表

    Returns:
        bool: True = 命中人工标记（≥2次）, False = 未命中
    """
    user_indices = _get_user_round_bounds(messages)

    if len(user_indices) < 2:
        return False

    prompt_template = _load_prompt('manual')
    counter = 0

    for round_idx, user_idx in enumerate(user_indices, start=1):
        sub_messages = messages[:user_idx + 1]
        conversation = _format_messages(sub_messages)
        full_prompt = prompt_template.format(conversation=conversation)

        response = ask([{"role": "user", "content": full_prompt}])
        result = _parse_json_response(response)

        if result.get('hit') == 1:
            counter += 1
            if counter >= 2:
                return True

    return False


# ============================================================
# 主入口（兼容旧接口，但返回值类型已变化）
# ============================================================

def tag_judge(messages):
    """
    对对话历史执行全部 5 种跨场景标记检测（无 SC 验证，单次调用）。

    Returns:
        dict: {
            'manual':  bool,    # 人工标记（≥2次转人工意图）
            'angry':   float,   # 愤怒/不满概率 [0,1]
            'sad':     float,   # 悲伤概率 [0,1]
            'urgent':  float,   # 紧急概率 [0,1]
            'non_biz': float,   # 非业务闲聊概率 [0,1]
        }
    """
    return {
        'manual':  detect_manual_transfer(messages),
        'angry':   detect_tag(messages, 'angry'),
        'sad':     detect_tag(messages, 'sad'),
        'urgent':  detect_tag(messages, 'urgent'),
        'non_biz': detect_tag(messages, 'non_biz'),
    }


# ============================================================
# ====== 以下为新增函数，不改变上述原有函数 ==================
# ============================================================

# ----------------------------------------------------------
# 统计工具：均值、标准差、离群点剔除
# ----------------------------------------------------------

def _compute_stats(probs):
    """
    计算概率列表的均值和标准差（总体标准差）。

    Args:
        probs: list[float], 概率值列表

    Returns:
        tuple: (mean, std)
            - mean: float, 均值
            - std:  float, 标准差（n=1 时返回 0.0）
    """
    n = len(probs)
    if n == 0:
        return 0.0, 0.0
    mean = sum(probs) / n
    if n == 1:
        return mean, 0.0
    variance = sum((p - mean) ** 2 for p in probs) / n
    std = math.sqrt(variance)
    return mean, std


def _filter_outliers(probs):
    """
    剔除 2σ 范围外的离群点（不包含 2σ 边界）。

    即：保留满足 |p - mean| <= 2*std 的值。
    若数据点 < 3 或标准差为 0，不做剔除直接返回原列表。

    Args:
        probs: list[float], 概率值列表

    Returns:
        list[float]: 剔除离群点后的概率列表
    """
    if len(probs) < 3:
        return probs[:]

    mean, std = _compute_stats(probs)
    if std == 0.0:
        return probs[:]

    threshold = 2.0 * std
    return [p for p in probs if abs(p - mean) <= threshold]


def _robust_average(probs):
    """
    剔除 2σ 外离群点后求平均。
    若剔除后列表为空，回退到简单平均。

    Args:
        probs: list[float], 概率值列表

    Returns:
        float: 鲁棒平均概率
    """
    filtered = _filter_outliers(probs)
    if not filtered:
        # 所有值都被剔除了 = 方差极大，回退到简单平均
        return sum(probs) / len(probs)
    return sum(filtered) / len(filtered)


# ----------------------------------------------------------
# SC (Self-Consistency) 单标签检测
# ----------------------------------------------------------

def _sc_detect_tag(messages, tag_type, k=5):
    """
    对单个标签执行 k 次独立判断，经离群点剔除后返回鲁棒平均概率。

    流程：
      1. 并行发起 k 次 detect_tag() 调用
      2. 收集 k 个概率值 p1...pk
      3. 计算均值 μ 和标准差 σ
      4. 剔除 |p - μ| > 2σ 的离群点
      5. 对剩余值求平均作为最终概率

    Args:
        messages:  list[dict], 对话消息
        tag_type: str, 'angry' | 'sad' | 'urgent' | 'non_biz'
        k:        int, 独立判断次数（默认 5）

    Returns:
        float: [0, 1] 鲁棒平均概率
    """
    if k < 1:
        raise ValueError(f"k 必须 >= 1, 实际: {k}")

    if k == 1:
        return detect_tag(messages, tag_type)

    prompt_template = _load_prompt(tag_type)
    conversation = _format_messages(messages)
    full_prompt = prompt_template.format(conversation=conversation)
    user_msg = [{"role": "user", "content": full_prompt}]

    # k 次独立调用并行执行
    with ThreadPoolExecutor(max_workers=k) as executor:
        futures = [executor.submit(ask, user_msg) for _ in range(k)]
        probs = []
        for future in as_completed(futures):
            response = future.result()
            probs.append(_parse_probability_response(response))

    return _robust_average(probs)


# ----------------------------------------------------------
# 并行 orchestrator：根据 ez_judge 调度单次 or SC 检测
# ----------------------------------------------------------

def _tag_dispatcher(messages, tag_type, ez_judge, k):
    """
    单个标签的调度器：
      ez_judge == 0 → SC 验证（k 次独立调用 + 离群点剔除）
      ez_judge != 0 → 单次快速检测

    Args:
        messages: list[dict]
        tag_type: str
        ez_judge: int, 0=SC验证, 非0=快速模式
        k:        int, SC 采样次数

    Returns:
        float: [0, 1] 概率值
    """
    if ez_judge == 0:
        return _sc_detect_tag(messages, tag_type, k)
    else:
        return detect_tag(messages, tag_type)


# ----------------------------------------------------------
# 新主入口：支持 SC 验证 + 全并行
# ----------------------------------------------------------

def tag_judge_v2(messages, ez_judge=0, k=5):
    """
    对对话历史执行全部 5 种跨场景标记检测。

    与 tag_judge() 的差异：
      - 支持 ez_judge 开关控制 SC (Self-Consistency) 验证
      - 4 个判别性标签（angry/sad/urgent/non_biz）在 ez_judge=0 时
        各进行 k 次独立判断，经 2σ 离群点剔除后取鲁棒平均
      - 5 个标签并行检测；SC 模式下每个标签内部的 k 次调用也并行
      - 返回值全部为概率值（manual 转换为 0.0/1.0 浮点数）

    并行架构：
      ┌─────────────────────────────────────────────────┐
      │  ThreadPoolExecutor(max_workers=5) — 5 tags 并行 │
      │  ├─ manual:  detect_manual_transfer (串行逐轮)   │
      │  ├─ angry:   SC(k calls 并行) or 单次            │
      │  ├─ sad:     SC(k calls 并行) or 单次            │
      │  ├─ urgent:  SC(k calls 并行) or 单次            │
      │  └─ non_biz: SC(k calls 并行) or 单次            │
      └─────────────────────────────────────────────────┘

    Args:
        messages: list[dict], OpenAI 格式消息列表
        ez_judge: int, 0 = SC 验证模式（推荐，精度优先）
                       非0 = 快速模式（单次判断，速度优先）
        k:        int, SC 模式下的独立采样次数（默认 5）

    Returns:
        dict: {
            'manual':  float,   # 0.0 或 1.0（≥2 次转人工意图 → 1.0）
            'angry':   float,   # 愤怒/不满概率 [0,1]
            'sad':     float,   # 悲伤概率 [0,1]
            'urgent':  float,   # 紧急概率 [0,1]
            'non_biz': float,   # 非业务闲聊概率 [0,1]
        }
    """
    # 外层：5 个标签并行
    with ThreadPoolExecutor(max_workers=5) as executor:
        # 提交 5 个 future
        future_map = {}

        # manual：独立线程（内部串行，与其余 4 个并行）
        future_map['manual'] = executor.submit(detect_manual_transfer, messages)

        # 4 个判别性标签：每个内部根据 ez_judge 决定 SC 或单次
        for tag in _SC_TAG_TYPES:
            future_map[tag] = executor.submit(
                _tag_dispatcher, messages, tag, ez_judge, k
            )

        # 收集结果
        results = {}
        for key, future in future_map.items():
            results[key] = future.result()

    # manual 从 bool 转换为 float 0.0/1.0（统一接口）
    results['manual'] = 1.0 if results['manual'] else 0.0

    return results
