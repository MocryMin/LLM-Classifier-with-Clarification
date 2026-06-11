"""
L3_reviser.py — 错例驱动的局部微调
=================================

对单个分类错误的黄金样本, 提取相关意图字段, 调用 LLM 生成微调申请.

操作范围 (仅限 L3):
  modify_keywords     — 增/删关键词
  add_negative_examples — 添加边界反例
  add_attention       — 添加与另一个意图的区分规则

用法:
    from L3_reviser import revise
    applications = revise(tree, error_sample, model="deepseek-v4-pro")
"""

import json
import re
import sys
from typing import Any

from openai import OpenAI

try:
    from .grammar_tree import Prompt, IntentCatalog, Intent, IntentGroup
    from .L2_enrich_application import EnrichApplication
except ImportError:
    from grammar_tree import Prompt, IntentCatalog, Intent, IntentGroup
    from L2_enrich_application import EnrichApplication


# ═══════════════════════════════════════════════════════════
# LLM
# ═══════════════════════════════════════════════════════════

_DEFAULT_MODEL = "deepseek-v4-pro"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_API_KEY = "sk-6172dca8aeb0461a8b84cc8bcac0f9e8"


def _get_client(api_key: str | None = None):
    import os
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or _DEFAULT_API_KEY
    return OpenAI(api_key=key, base_url=_DEFAULT_BASE_URL)


def _extract_json(text: str) -> dict | None:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", t, re.DOTALL)
    if m:
        try: return json.loads(m.group(1).strip())
        except json.JSONDecodeError: pass
    first = t.find("{"); last = t.rfind("}")
    if first != -1 and last != -1 and last > first:
        try: return json.loads(t[first:last+1])
        except json.JSONDecodeError: pass
    try: return json.loads(t)
    except json.JSONDecodeError: return None


# ═══════════════════════════════════════════════════════════
# 意图字段提取
# ═══════════════════════════════════════════════════════════

def _find_intent(tree: Prompt, l1: str, l2: str) -> Intent | None:
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return None
    for group in catalog.groups:
        for intent in group.intents:
            if intent.l1 == l1 and intent.l2 == l2:
                return intent
    return None


def _format_intent_fields(intent: Intent | None) -> str:
    if intent is None:
        return "(未找到该意图)"
    lines = [
        f"【{intent.display_id}】{intent.l2}",
        f"定义: {intent.definition}",
    ]
    if intent.faq_items:
        lines.append(f"FAQ: {', '.join(intent.faq_items[:5])}")
    if intent.company.strip():
        lines.append(f"对应子公司: {intent.company}")
    # 当前 enrich 字段 (L2 或之前 L3 轮次写入的)
    enriched = intent.enriched
    if enriched.get("keywords"):
        lines.append(f"当前关键词: {', '.join(enriched['keywords'])}")
    if enriched.get("attention"):
        lines.append(f"当前区分规则: {'; '.join(enriched['attention'])}")
    if enriched.get("negative_examples"):
        lines.append(f"当前边界反例: {'; '.join(enriched['negative_examples'])}")
    # 同级其他意图 (用于写区分规则时参考)
    return "\n".join(lines)


def _format_candidates(tree: Prompt, candidates: list[dict]) -> str:
    """格式化 top candidates 的简要信息."""
    if not candidates:
        return "(无)"
    lines = []
    for c in candidates[:3]:
        intent = _find_intent(tree, c.get("l1", ""), c.get("l2", ""))
        if intent:
            lines.append(f"  - {intent.display_id} {intent.l2}: {intent.definition[:60]}...")
        else:
            lines.append(f"  - {c.get('l1', '?')}/{c.get('l2', '?')}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Reviser 输入构建
# ═══════════════════════════════════════════════════════════

REVISER_SYSTEM = """\
你是一个保险客服意图路由系统的 prompt 微调器.

你的任务: 分析一个分类错误的样本, 提出**最小局部修改**来修正该错误.

你可以进行的操作 (仅限):
1. modify_keywords: 对某个意图增/删关键词
   - add: 添加能强化该意图识别的关键词 (避免太泛, 避免与其他意图重叠)
   - remove: 删除可能导致混淆的旧关键词
2. add_negative_examples: 为某个意图添加边界反例
   - 格式: "用户说'...' → 实际属于【X.X XXX】"
   - 反例要适当泛化, 不是原样复制当前错例
3. add_attention: 为某个意图添加与另一个易混淆意图的区分规则
   - 写清楚两个意图的关键判断差异

原则:
- 最小修改: 能用一个关键词解决就不加三个
- 不碰定义: 不修改 definition (那是业务方写的)
- 不破坏全局: 你的修改只应影响当前错例涉及的边界, 不应改变其他正确分类的样本
- 如果无法确定怎么改, 或者改动风险太高, 返回空列表

输出格式: JSON, 包含 revisions 数组."""


def build_reviser_input(
    tree: Prompt,
    error_sample: dict,
) -> tuple[str, str]:
    """构建 reviser 的输入.

    Args:
        tree: 当前文法树
        error_sample: 包含 expected_l1/l2, actual_l1/l2, conversation 的错例

    Returns:
        (system_prompt, user_prompt)
    """
    correct_intent = _find_intent(tree, error_sample["expected_l1"], error_sample["expected_l2"])
    wrong_intent = _find_intent(tree, error_sample.get("actual_l1", ""), error_sample.get("actual_l2", ""))
    candidates = error_sample.get("top_candidates", [])

    user = f"""## 分类错误样本

对话: {_format_conversation(error_sample)}

正确意图: {error_sample['expected_l1']} / {error_sample['expected_l2']}
模型误判为: {error_sample.get('actual_l1', '?')} / {error_sample.get('actual_l2', '?')}

---

## 正确意图的当前 prompt 内容

{_format_intent_fields(correct_intent)}

---

## 被误判意图的当前 prompt 内容

{_format_intent_fields(wrong_intent)}

---

## 其他竞争意图 (top candidates)

{_format_candidates(tree, candidates)}

---

请分析为什么模型会误判, 并提出最小修改方案.
如果修改方案涉及 **add_attention**, 必须指定是针对哪个意图添加区分规则.
"""

    return REVISER_SYSTEM, user


def _format_conversation(sample: dict) -> str:
    msgs = sample.get("messages", [sample.get("conversation", "")])
    if isinstance(msgs, str):
        return msgs
    if isinstance(msgs, list):
        return "\n".join(
            f"[{m.get('role', '?')}] {m.get('content', '')}" for m in msgs
        )
    return str(msgs)


# ═══════════════════════════════════════════════════════════
# Reviser 调�?
# ═══════════════════════════════════════════════════════════

REVISER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {
            "type": "string",
            "description": "简短分析为什么误判 (1-2句)",
        },
        "revisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["modify_keywords", "add_negative_examples", "add_attention"],
                    },
                    "target_intent_display_id": {
                        "type": "string",
                        "description": "目标意图的 display_id, 如 '2.2'",
                    },
                    "content": {"type": "object"},
                    "rationale": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["operation", "target_intent_display_id", "content", "rationale", "confidence"],
            },
        },
    },
    "required": ["analysis", "revisions"],
}


def _call_reviser(
    system: str,
    user: str,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
) -> dict | None:
    client = _get_client(api_key=api_key)
    schema_str = json.dumps(REVISER_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    full_user = f"{user}\n\n请严格按照以下 JSON 格式输出:\n```json\n{schema_str}\n```"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": full_user},
            ],
            stream=False,
            max_tokens=4000,
        )
        raw = response.choices[0].message.content
        if not raw:
            return None
        return _extract_json(raw)
    except Exception as e:
        print(f"  [L3 reviser] LLM error: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════
# 主入�?
# ═══════════════════════════════════════════════════════════

def revise(
    tree: Prompt,
    error_sample: dict,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
    verbose: bool = False,
) -> list[EnrichApplication]:
    """对一个错误样本生成微调申请.

    Args:
        tree: 当前文法树
        error_sample: 分类错误的样本 (含 expected_l1/l2, actual_l1/l2, top_candidates)
        model: LLM 模型
        api_key: API key
        verbose: 打印分析

    Returns:
        微调申请列表 (可能为空)
    """
    system, user = build_reviser_input(tree, error_sample)
    result = _call_reviser(system, user, model=model, api_key=api_key)

    if result is None:
        if verbose:
            print(f"  [L3 reviser] LLM call failed")
        return []

    analysis = result.get("analysis", "")
    if verbose:
        print(f"  [L3 reviser] analysis: {analysis[:100]}")

    applications = []
    for item in result.get("revisions", []):
        display_id = item.get("target_intent_display_id", "")
        intent = _find_intent_by_display_id(tree, display_id)
        if intent is None:
            if verbose:
                print(f"  [L3 reviser] skip: intent {display_id} not found")
            continue

        app = EnrichApplication(
            operation=item["operation"],
            target=f"intent_catalog.intents[{display_id}]",
            content=item.get("content", {}),
            confidence=item.get("confidence", 0.0),
            rationale=item.get("rationale", ""),
        )
        applications.append(app)

    return applications


def _find_intent_by_display_id(tree: Prompt, display_id: str) -> Intent | None:
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return None
    for group in catalog.groups:
        for intent in group.intents:
            if intent.display_id == display_id:
                return intent
    return None
