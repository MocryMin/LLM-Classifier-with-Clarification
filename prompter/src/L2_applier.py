"""
applier.py — 将 enrich 申请写入文法树
====================================

确定性操作. 不调 LLM, 不移除原始数据 (cells 不变).

操作:
  group_description → tree.sections[X].content.groups[Y].description
  sample_add        → 追加到 ##samples## FixedText 末尾
  sample_delete     → 从 ##samples## FixedText 中删除指定示例

用法:
    from L2_applier import apply, apply_all
    apply(tree, application)           # 单条
    apply_all(tree, applications)      # 批量
"""

import re

try:
    from .grammar_tree import Prompt, FixedText, IntentCatalog, Section
    from .L2_enrich_application import EnrichApplication
except ImportError:
    from grammar_tree import Prompt, FixedText, IntentCatalog, Section
    from L2_enrich_application import EnrichApplication


# ═══════════════════════════════════════════════════════════
# 单条应用
# ═══════════════════════════════════════════════════════════

def _apply_description(tree: Prompt, app: EnrichApplication):
    """将 description 写入指定 IntentGroup."""
    catalog = tree._find_content(IntentCatalog)
    if catalog is None:
        raise ValueError("tree has no IntentCatalog")

    m = re.search(r"groups\[(\d+)\]", app.target)
    if not m:
        raise ValueError(f"cannot parse target: {app.target}")

    idx = int(m.group(1)) - 1
    if idx < 0 or idx >= len(catalog.groups):
        raise ValueError(f"group index {idx} out of range (0-{len(catalog.groups)-1})")

    desc = app.content.get("description", "")
    catalog.groups[idx].description = desc


def _find_samples_section(tree: Prompt) -> Section | None:
    """查找 ##samples## 段落."""
    return tree.section_by_title("##samples##")


def _apply_sample_add(tree: Prompt, app: EnrichApplication):
    """将新 sample 追加到 ##samples## 末尾."""
    section = _find_samples_section(tree)
    if section is None:
        raise ValueError("tree has no ##samples## section")

    if not isinstance(section.content, FixedText):
        raise ValueError("##samples## content is not FixedText")

    title = app.content.get("title", "新示例")
    conversation = app.content.get("conversation", "")
    output_json = app.content.get("output_json", {})
    correct_answer = app.content.get("correct_answer", "")

    import json

    # 构建示例文本块
    sample_text = f"""

{'=' * 60}
{title}
{'=' * 60}
对话：{conversation}

输出：
{json.dumps(output_json, ensure_ascii=False, indent=2)}

说明：{correct_answer}"""

    section.content.text += sample_text


def _apply_sample_delete(tree: Prompt, app: EnrichApplication):
    """从 ##samples## 中删除指定示例."""
    section = _find_samples_section(tree)
    if section is None:
        raise ValueError("tree has no ##samples## section")

    if not isinstance(section.content, FixedText):
        raise ValueError("##samples## content is not FixedText")

    target_id = app.content.get("target_display_id", "")
    text = section.content.text

    # 匹配示例块: "示例X：..." 到下一个 "示例Y：" 或末尾
    # 格式: =====\n示例N...\n=====\n...content...
    pattern = re.compile(
        r"\n?={3,}\n"  # 分隔线
        + re.escape(target_id) + r"[^\n]*\n"  # 示例标题行
        r"={3,}\n"  # 分隔线
        r".*?"  # 内容 (最小匹配)
        r"(?=\n={3,}\n示例\d|$)",  # 到下一个示例或末尾
        re.DOTALL,
    )

    new_text = pattern.sub("", text, count=1)
    if new_text == text:
        raise ValueError(f"sample block '{target_id}' not found in ##samples##")

    # 清理多余空行
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    section.content.text = new_text


_APPLIERS = {
    "group_description": _apply_description,
    "sample_add": _apply_sample_add,
    "sample_delete": _apply_sample_delete,
}


def apply(tree: Prompt, app: EnrichApplication) -> Prompt:
    """将单条申请写入文法树 (原地修改).

    Args:
        tree: 文法树 (会被修改)
        app:  待应用的申请

    Returns:
        修改后的树 (与输入同一对象)

    Raises:
        ValueError: 目标节点不存在或操作不合法
    """
    applier = _APPLIERS.get(app.operation)
    if applier is None:
        raise ValueError(f"unknown operation: {app.operation}")

    applier(tree, app)
    return tree


def apply_all(tree: Prompt, applications: list[EnrichApplication]) -> Prompt:
    """批量应用申请.

    Args:
        tree: 文法树 (会被修改)
        applications: 待应用的申请列表

    Returns:
        修改后的树
    """
    for app in applications:
        apply(tree, app)
    return tree
