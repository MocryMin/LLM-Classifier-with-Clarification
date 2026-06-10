"""
validator.py — 确定性规则验证
============================

对 enrich 申请进行确定性校验. 不用 LLM, 零幻觉.

规则:
  1. 事实一致性: description 中的声明与 grammar tree 中数据对照
  2. 格式校验: sample 的 JSON 结构和字段合法性
  3. 精确去重: sample conversation 与现有完全一致时标记

用法:
    from L2_validator import validate_all
    passed, failed = validate_all(applications, tree)
"""

import re
import json
from typing import Any

try:
    from .grammar_tree import Prompt, IntentCatalog, IntentGroup
    from .L2_enrich_application import EnrichApplication
except ImportError:
    from grammar_tree import Prompt, IntentCatalog, IntentGroup
    from L2_enrich_application import EnrichApplication


# ═══════════════════════════════════════════════════════════
# 事实一致性检查
# ═══════════════════════════════════════════════════════════

# 模式: (关键词, 检查方式, 错误消息)
_FACT_PATTERNS = [
    (
        r"全部.*集团|统一.*集团",
        "company_all_group",
    ),
    (
        r"全部.*子公司|统一.*子公司|全部路由子公司",
        "company_all_subsidiary",
    ),
    (
        r"无需.*澄清|无.*澄清|无.*SOP|不用.*澄清",
        "sop_all_empty",
    ),
    (
        r"全部.*澄清|均有.*澄清|都有.*SOP",
        "sop_all_present",
    ),
]


def _find_group(tree: Prompt, target: str) -> IntentGroup | None:
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return None
    # target like "intent_catalog.groups[2]"
    m = re.search(r"groups\[(\d+)\]", target)
    if not m:
        return None
    idx = int(m.group(1))
    if 0 <= idx - 1 < len(catalog.groups):
        return catalog.groups[idx - 1]
    return None


def _check_company_fact(description: str, group: IntentGroup) -> tuple[bool, str]:
    """检查 description 中关于 company 的声明."""
    companies = [i.company.strip() for i in group.intents]

    if re.search(r"全部.*集团|统一.*集团", description):
        all_group = all("集团" in c for c in companies)
        if not all_group:
            actual = ", ".join(c if c else "(空)" for c in companies[:5])
            return False, f"声称'全部集团', 实际: [{actual}]"
        return True, ""

    if re.search(r"全部.*子公司|统一.*子公司|全部路由子公司", description):
        all_sub = all(c.strip() and "集团" not in c for c in companies)
        if not all_sub:
            actual = ", ".join(c if c else "(空)" for c in companies[:5])
            return False, f"声称'全部子公司', 实际: [{actual}]"
        return True, ""

    return True, ""  # 没有明确声明 → 不检查


def _check_sop_fact(description: str, group: IntentGroup) -> tuple[bool, str]:
    """检查 description 中关于 SOP 的声明."""
    sop_states = [i.has_sop for i in group.intents]

    if re.search(r"无需.*澄清|无.*澄清|无.*SOP|不用.*澄清", description):
        all_empty = not any(sop_states)
        if not all_empty:
            has_sop = [i.l2 for i in group.intents if i.has_sop]
            return False, f"声称'无需澄清', 但 [{', '.join(has_sop)}] 有SOP"
        return True, ""

    if re.search(r"全部.*澄清|均有.*澄清|都有.*SOP", description):
        all_have = all(sop_states)
        if not all_have:
            no_sop = [i.l2 for i in group.intents if not i.has_sop]
            return False, f"声称'全部有澄清', 但 [{', '.join(no_sop)}] 无SOP"
        return True, ""

    return True, ""  # 没有明确声明 → 不检查


def _validate_description(app: EnrichApplication, tree: Prompt) -> tuple[bool, str]:
    """验证 group_description 申请."""
    desc = app.content.get("description", "")
    if not desc.strip():
        return False, "description 为空"

    if len(desc) > 50:
        return False, f"description 超长 ({len(desc)} chars, 限制 50)"

    group = _find_group(tree, app.target)
    if group is None:
        return False, f"找不到目标分组: {app.target}"

    # 检查 company 声明
    ok, msg = _check_company_fact(desc, group)
    if not ok:
        return False, f"[事实矛盾] {msg}"

    # 检查 SOP 声明
    ok, msg = _check_sop_fact(desc, group)
    if not ok:
        return False, f"[事实矛盾] {msg}"

    return True, ""


# ═══════════════════════════════════════════════════════════
# 格式校验
# ═══════════════════════════════════════════════════════════

def _get_valid_intent_pairs(tree: Prompt) -> set[tuple[str, str]]:
    """获取意图库中所有的 (L1, L2) 组合."""
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return set()
    pairs = set()
    for group in catalog.groups:
        for intent in group.intents:
            pairs.add((intent.l1, intent.l2))
    return pairs


def _validate_sample_add(app: EnrichApplication, tree: Prompt) -> tuple[bool, str]:
    """验证 sample_add 申请."""
    output = app.content.get("output_json", {})
    if not output:
        return False, "output_json 为空"

    # 检查必要字段
    pi = output.get("primary_intent", {})
    if not pi.get("l1") or not pi.get("l2"):
        return False, "primary_intent 缺少 l1/l2"

    # 检查意图存在性
    valid_pairs = _get_valid_intent_pairs(tree)
    intent_pair = (pi.get("l1", ""), pi.get("l2", ""))
    if intent_pair not in valid_pairs:
        return False, f"意图 {intent_pair} 不在意图库中"

    # 检查 confidence 范围
    conf = pi.get("confidence", 0)
    if not (0 <= conf <= 1):
        return False, f"confidence 超出范围: {conf}"

    # 检查 needs_clarification 类型
    if not isinstance(output.get("needs_clarification"), bool):
        return False, "needs_clarification 非布尔值"

    # 检查 ###call 格式 (当不澄清时)
    user_output = output.get("user_output", "")
    if not output.get("needs_clarification") and "###call" in user_output:
        # 检查格式是否为 ###call(L1-L2)
        pattern = r"###call\((.+?)-(.+?)\)"
        m = re.search(pattern, user_output)
        if m:
            call_pair = (m.group(1), m.group(2))
            if call_pair not in valid_pairs:
                return False, f"###call 引用了不存在的意图: {call_pair}"

    # 检查 conversation
    conv = app.content.get("conversation", "")
    if not conv.strip():
        return False, "conversation 为空"

    return True, ""


def _validate_sample_delete(app: EnrichApplication, tree: Prompt) -> tuple[bool, str]:
    """验证 sample_delete 申请."""
    target_id = app.content.get("target_display_id", "")
    if not target_id:
        return False, "target_display_id 为空"

    # 检查目标是否存在于现有 samples 中
    samples_text = tree._find_text("##samples##")
    if target_id not in samples_text:
        return False, f"samples 中未找到 {target_id} (可能已被删除或编号变更)"

    # 检查是否有矛盾描述
    contradiction = app.content.get("contradiction_detail", "")
    if not contradiction.strip():
        return False, "contradiction_detail 为空"

    return True, ""


# ═══════════════════════════════════════════════════════════
# 精确去重
# ═══════════════════════════════════════════════════════════

def _check_duplicate(app: EnrichApplication, tree: Prompt, seen_convos: set[str]) -> tuple[bool, str]:
    """检查 sample conversation 是否与已有重复."""
    if app.operation != "sample_add":
        return True, ""

    conv = app.content.get("conversation", "").strip()
    if not conv:
        return True, ""

    # 精确匹配
    if conv in seen_convos:
        return False, f"conversation 与已有 sample 精确重复: {conv[:50]}..."

    # 检查是否与现有 samples 中的 conversation 重复
    samples_text = tree._find_text("##samples##")
    if conv in samples_text:
        return False, f"conversation 与现有 samples 重复"

    return True, ""


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

_VALIDATORS = {
    "group_description": _validate_description,
    "sample_add": _validate_sample_add,
    "sample_delete": _validate_sample_delete,
}


def validate(
    app: EnrichApplication,
    tree: Prompt,
    seen_convos: set[str] | None = None,
) -> tuple[bool, str]:
    """验证单个申请.

    Args:
        app: 待验证的申请
        tree: 文法树
        seen_convos: 已通过的 sample conversation 集合 (用于去重)

    Returns:
        (is_valid, reason)
    """
    validator = _VALIDATORS.get(app.operation)
    if validator is None:
        return False, f"未知操作类型: {app.operation}"

    ok, msg = validator(app, tree)
    if not ok:
        return False, msg

    # 去重检查
    if seen_convos is not None:
        ok, msg = _check_duplicate(app, tree, seen_convos)
        if not ok:
            return False, msg

    return True, ""


def validate_all(
    applications: list[EnrichApplication],
    tree: Prompt,
) -> tuple[list[EnrichApplication], list[dict]]:
    """批量验证.

    Returns:
        (passed, failed_entries) — failed_entries is [{application, reason}, ...]
    """
    passed = []
    failed = []
    seen_convos: set[str] = set()

    for app in applications:
        ok, reason = validate(app, tree, seen_convos)
        if ok:
            passed.append(app)
            if app.operation == "sample_add":
                seen_convos.add(app.content.get("conversation", "").strip())
        else:
            failed.append({"application": app, "reason": reason})

    return passed, failed
