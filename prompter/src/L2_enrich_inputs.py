"""
enrich_inputs.py — enrich 输入上下文构建器
=========================================

为每种 enrich 操作构建精确的 LLM 输入上下文.
不给多余信息, 不给少关键信息.

用法:
    from L2_enrich_inputs import build_description_inputs, build_sample_review_input

    # 调用 1: group_description
    inputs = build_description_inputs(tree)
    for inp in inputs:
        result = llm_call(inp.system, inp.user)

    # 调用 2: sample_review (add+delete 合并)
    inp = build_sample_review_input(tree)
    result = llm_call(inp.system, inp.user)
"""

from dataclasses import dataclass

try:
    from .grammar_tree import Prompt, IntentCatalog, IntentGroup, Intent
except ImportError:
    from grammar_tree import Prompt, IntentCatalog, IntentGroup, Intent


@dataclass
class EnrichInput:
    """一个 enrich 操作的 LLM 输入."""
    system: str    # system prompt
    user: str      # user prompt (结构化上下文)
    metadata: dict  # {operation, target, group_l1_name, ...}


# ═══════════════════════════════════════════════════════════
# 调用 1: group_description
# ═══════════════════════════════════════════════════════════

DESCRIPTION_SYSTEM = """\
你正在优化一个保险客服意图路由系统的 prompt.

请为给定的一级意图分组生成一句话的说明文字, 概括该组场景的共同路由特征.

要求:
1. 用一句话 (<=30字) 适当结合一级意图的名称和组内二级意图定义，概括该组场景的共同特征
2. 不要复述各场景的定义, 要归纳规律
3. 如果该组场景间差异太大, 无法归纳有意义的规律, 返回空字符串
4. 完全只读, 不修改任何内容"""


def _build_single_description_input(
    group: IntentGroup,
    group_index: int,
) -> EnrichInput:
    """为一个 IntentGroup 构建 description 输入."""
    lines = [
        f"【分组信息】",
        f"一级意图名称: {group.l1_name}",
        f"包含 {group.intent_count} 个二级场景:",
        "",
    ]

    for intent in group.intents:
        company_display = intent.company if intent.company.strip() else "(空)"
        sop_display = "有" if intent.has_sop else "无"
        lines.append(f"  - {intent.l2}")
        lines.append(f"    定义: {intent.definition}")
        lines.append(f"    对应子公司: {company_display}")
        lines.append(f"    是否有澄清指引: {sop_display}")
        lines.append("")

    return EnrichInput(
        system=DESCRIPTION_SYSTEM,
        user="\n".join(lines),
        metadata={
            "operation": "group_description",
            "target": f"intent_catalog.groups[{group_index}]",
            "group_l1_name": group.l1_name,
        },
    )


def build_description_inputs(tree: Prompt) -> list[EnrichInput]:
    """为所有 IntentGroup 构建 description 输入列表.

    每个分组一个独立的 LLM 调用.
    """
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        return []

    inputs = []
    for group in catalog.groups:
        inp = _build_single_description_input(group, group.group_index)
        inputs.append(inp)
    return inputs


# ═══════════════════════════════════════════════════════════
# 调用 2: sample_review (add + delete 合并)
# ═══════════════════════════════════════════════════════════

SAMPLE_REVIEW_SYSTEM = """\
你正在审查和补充一个保险客服意图路由系统的 few-shot 示例.

你可以提出两种操作:

【新增示例】
  - 优先补充现有示例未覆盖的意图边界 (如 核保vs投保、报案vs核赔、多意图排优先级)
  - 每个新示例必须绝对正确: 所有字段值与路由规则和意图定义一致
  - 每个新示例应覆盖一个不同的意图或边界场景
  - 不要重复已有示例的模式或边界
  - 如果现有示例已经足够全面, 或无法给出有增益且严格正确的示例，返回空列表

【删除示例】(严格)
  - 仅当示例与路由规则或 intent 定义**明确矛盾**时才标记
  - "矛盾" 指: 示例的路由决策/调用格式/澄清逻辑 直接违背了规则的明文规定
  以下不算矛盾:
    - 示例覆盖了规则中没有明确写出的边界
    - 示例的风格/措辞不完全一致但逻辑正确
    - 示例使用了不同的表述方式但结论正确
  - 如果没有矛盾, 返回空列表

要求:
1. 完全只读, 不修改任何内容
2. 如果没有好的建议, 返回空列表 (不要为了输出而输出)
3. 每个建议必须附带 0-1 之间的 confidence 和 rationale"""


def _build_sample_review_input(tree: Prompt) -> EnrichInput:
    """构建 sample_review 的输入 (add+delete 合并)."""
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        raise ValueError("Prompt tree has no IntentCatalog")

    # ── 意图库 ──
    intent_lines = ["## 意图库", ""]
    for group in catalog.groups:
        intent_lines.append(
            f"{'=' * 40}\n"
            f"{group.group_index}. {group.l1_name} ({group.intent_count}个场景)\n"
            f"{'=' * 40}"
        )
        for intent in group.intents:
            company_display = intent.company if intent.company.strip() else "(空)"
            sop_display = "有" if intent.has_sop else "无"
            intent_lines.append(f"\n【{intent.display_id}】{intent.l2}")
            intent_lines.append(f"定义: {intent.definition}")
            intent_lines.append(f"对应子公司: {company_display}")
            intent_lines.append(f"是否有SOP: {sop_display}")
            if intent.faq_items:
                intent_lines.append("FAQ:")
                for item in intent.faq_items:
                    intent_lines.append(f"  - {item}")
        intent_lines.append("")

    # ── 路由规则 ──
    routing_text = tree._find_text("##路由规则##")
    routing_lines = ["## 路由规则", "", routing_text if routing_text else "(无)", ""]

    # ── 现有示例 ──
    samples_text = tree._find_text("##samples##")
    samples_lines = ["## 现有示例", "", samples_text if samples_text else "(无)", ""]

    # ── 输出格式 ──
    output_text = tree._find_text("##输出格式##")
    output_lines = ["## 输出格式", "", output_text if output_text else "(无)"]

    user = "\n".join(
        intent_lines + routing_lines + samples_lines + output_lines
    )

    return EnrichInput(
        system=SAMPLE_REVIEW_SYSTEM,
        user=user,
        metadata={
            "operation": "sample_review",
            "target": "samples",
        },
    )


def build_sample_review_input(tree: Prompt) -> EnrichInput:
    """构建 sample_review 的输入 (add+delete 合并, 一次调用)."""
    return _build_sample_review_input(tree)
