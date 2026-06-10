"""
文法树 → prompt 文本 序列化
============================

纯确定性的序列化：给定一个 Prompt 树,输出最终 prompt 文本.

规则：
  - 空字段不展示(不会出现 "SOP:" 这样的空白行)
  - enrich 槽位仅当非空时展示
  - mode="classify_only" 时隐藏 SOP 字段
  - 空行仅用于段落之间和意图卡片之间的视觉分隔
"""

try:
    from .grammar_tree import (
        Prompt, Section, FixedText, Placeholder,
        IntentCatalog, IntentGroup, Intent,
        EnrichSlot, ENRICH_SLOTS,
    )
except ImportError:
    from grammar_tree import (
        Prompt, Section, FixedText, Placeholder,
        IntentCatalog, IntentGroup, Intent,
        EnrichSlot, ENRICH_SLOTS,
    )

# ── 中文数字映射 ──
_CN_NUM = [
    "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
]


def _cn_num(n: int) -> str:
    if 0 <= n < len(_CN_NUM):
        return _CN_NUM[n]
    return str(n)


# ═══════════════════════════════════════════════════════════
# 单个节点渲染
# ═══════════════════════════════════════════════════════════

def _render_fixed_text(node: FixedText) -> str:
    return node.text


def _render_placeholder(node: Placeholder) -> str:
    return f"{{{node.key}}}"


def _render_faq(faq_items: list[str]) -> str:
    if not faq_items:
        return ""
    return "FAQ典型问题：\n" + "\n".join(f"  - {item}" for item in faq_items)


def _render_enriched(enriched: dict) -> str:
    """渲染 enrich 槽位.只输出非空槽位."""
    parts = []
    for slot_key, slot in ENRICH_SLOTS.items():
        value = enriched.get(slot_key)
        if not value:
            continue
        if slot.value_type == "list[str]" and isinstance(value, list) and len(value) > 0:
            parts.append(f"{slot.label}：")
            for item in value:
                parts.append(f"  - {item}")
        elif slot.value_type == "str" and isinstance(value, str) and value.strip():
            parts.append(f"{slot.label}：{value.strip()}")
    return "\n".join(parts)


def _render_intent(intent: Intent, mode: str) -> str:
    """渲染单个意图卡片.空字段不展示."""
    lines = [f"【意图{intent.display_id}】{intent.l2}"]

    # 定义(必有,来自 xlsx)
    if intent.definition.strip():
        lines.append(f"定义：{intent.definition.strip()}")

    # FAQ(按需)
    faq_block = _render_faq(intent.faq_items)
    if faq_block:
        lines.append(faq_block)

    # 澄清指引/SOP(仅 full 模式展示,空不展示)
    if mode == "full" and intent.sop.strip():
        lines.append(f"澄清指引/SOP：\n{intent.sop.strip()}")

    # 对应子公司(空不展示)
    if intent.company.strip():
        lines.append(f"对应子公司：{intent.company.strip()}")

    # 回复设计(空不展示)
    if intent.reply_design.strip():
        lines.append(f"回复设计：\n{intent.reply_design.strip()}")

    # 备注(空不展示)
    if intent.notes.strip():
        lines.append(f"备注：{intent.notes.strip()}")

    # enrich 槽位(非空才展示)
    enrich_block = _render_enriched(intent.enriched)
    if enrich_block:
        lines.append(enrich_block)

    return "\n".join(lines)


def _render_intent_group(group: IntentGroup, mode: str) -> str:
    """渲染一个 L1 分组."""
    count = group.intent_count
    lines = [
        f"{'=' * 60}",
        f"{_cn_num(group.group_index)}、{group.l1_name}({count}个场景)",
        f"{'=' * 60}",
    ]

    # L1 说明文字(如果有)
    if group.description.strip():
        lines.append(group.description.strip())

    lines.append("")  # 空行

    # 逐个意图
    for intent in group.intents:
        lines.append(_render_intent(intent, mode))
        lines.append("")  # 意图间空行

    return "\n".join(lines)


def _render_intent_catalog(catalog: IntentCatalog, mode: str) -> str:
    """渲染整个意图库."""
    sections = []
    for group in catalog.groups:
        sections.append(_render_intent_group(group, mode))
    return "\n".join(sections)


def _render_section_content(
    content: FixedText | Placeholder | IntentCatalog | list,
    mode: str,
) -> str:
    """渲染段落内容,分派到具体渲染函数."""
    if isinstance(content, FixedText):
        return _render_fixed_text(content)
    elif isinstance(content, Placeholder):
        return _render_placeholder(content)
    elif isinstance(content, IntentCatalog):
        return _render_intent_catalog(content, mode)
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, FixedText):
                parts.append(_render_fixed_text(item))
            elif isinstance(item, Placeholder):
                parts.append(_render_placeholder(item))
            elif isinstance(item, IntentCatalog):
                parts.append(_render_intent_catalog(item, mode))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def serialize(prompt: Prompt) -> str:
    """将文法树序列化为 prompt 文本.

    Args:
        prompt: 文法树根节点

    Returns:
        完整的 prompt 文本
    """
    parts = []
    for section in prompt.sections:
        content_text = _render_section_content(section.content, prompt.mode)
        if section.title:
            parts.append(section.title)
        if content_text:
            parts.append(content_text)
        parts.append("")  # 段落间空行

    return "\n".join(parts)
