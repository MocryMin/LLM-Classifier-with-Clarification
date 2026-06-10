"""
L1: JSON + skeleton → prompt 编译器
===================================

读取 scene_table.json 和 skeleton 模板，生成 L1 intent router prompt。

用法:
  python compile_prompt.py <scene_table.json> [--skeleton <skel>] [--out <prompt>]

示例:
  python prompter/src/compile_prompt.py artifacts/0604/scene_table.json
  python prompter/src/compile_prompt.py scene_table.json --skeleton skeletons/L1_intent_router_v3.skel.txt --out prompt/generated_L1.txt
"""

import json
import sys
from pathlib import Path

# ── 中文数字映射 ──
_CN_NUM = [
    "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
]


def _cn_num(n: int) -> str:
    """1→一, 2→二, ..."""
    if 0 <= n < len(_CN_NUM):
        return _CN_NUM[n]
    return str(n)


def _format_faq(faq_text: str) -> str:
    """格式化 FAQ 文本为缩进列表。

    输入可能是:
      "• 问题1\\n• 问题2\\n• 问题3"
      "问题1\\n问题2"
    输出统一为:
      "  - 问题1\n  - 问题2\n  - 问题3"
    """
    if not faq_text.strip():
        return ""
    lines = [l.strip() for l in faq_text.strip().split("\n") if l.strip()]
    if not lines:
        return ""
    return "\n".join(f"  - {l.lstrip('•·- ')}" for l in lines)


def _build_intent_card(
    display_id: str,
    cells: dict,
) -> str:
    """从 scene_table.json 的一行 cells 构建单个意图卡片。"""
    l2 = cells["二级意图"]

    lines = [f"【意图{display_id}】{l2}"]

    # 定义
    definition = cells.get("二级场景定义（供大模型识别意图使用）", "")
    if definition:
        lines.append(f"定义：{definition}")

    # 风险等级
    risk = cells.get("风险等级", "")
    if risk:
        lines.append(f"风险等级：{risk}")

    # FAQ
    faq = cells.get("FAQ典型问题", "")
    if faq.strip():
        lines.append("FAQ典型问题：")
        lines.append(_format_faq(faq))

    # 澄清指引/SOP
    sop = cells.get("澄清指引/SOP", "")
    if sop.strip():
        lines.append(f"澄清指引/SOP：\n{sop}")

    # 优先级
    priority = cells.get("优先级", "")
    if priority:
        lines.append(f"优先级：{priority}")

    # 对应子公司
    company = cells.get("对应子公司", "")
    if company:
        lines.append(f"对应子公司/路由说明：{company}")

    # 回复设计
    reply = cells.get("回复设计", "")
    if reply.strip():
        lines.append(f"回复设计：\n{reply}")

    # 备注
    notes = cells.get("备注", "")
    if notes.strip():
        lines.append(f"备注：{notes}")

    return "\n".join(lines)


def _build_intent_catalog(rows: list[dict]) -> str:
    """从 scene_table.json 的 rows 生成完整意图库文本。

    按一级意图分组，自动编号。
    """
    # 分组：保持 xlsx 出现顺序
    groups: list[tuple[str, list[dict]]] = []
    seen_l1 = []
    for row in rows:
        l1 = row["cells"]["一级意图"]
        if l1 not in seen_l1:
            seen_l1.append(l1)
            groups.append((l1, []))
        for g_l1, g_rows in groups:
            if g_l1 == l1:
                g_rows.append(row)
                break

    sections = []
    for g_idx, (l1, g_rows) in enumerate(groups, start=1):
        count = len(g_rows)
        header = f"{'=' * 60}\n{_cn_num(g_idx)}、{l1}（{count}个场景）\n{'=' * 60}"
        sections.append(header)

        for s_idx, row in enumerate(g_rows, start=1):
            display_id = f"{g_idx}.{s_idx}"
            card = _build_intent_card(display_id, row["cells"])
            sections.append(card)
            sections.append("")  # 空行分隔

    return "\n".join(sections)


def compile_prompt(
    registry_path: str | Path,
    skeleton_path: str | Path | None = None,
    out_path: str | Path | None = None,
) -> str:
    """从 scene_table.json + skeleton 生成最终 prompt。

    Args:
        registry_path: scene_table.json 路径 (L0 产物)
        skeleton_path: skeleton 模板路径；默认自动查找
        out_path:      输出路径；None 则仅返回字符串

    Returns:
        生成的 prompt 全文
    """
    registry_path = Path(registry_path)

    # ── 读取场景表 ──
    with open(registry_path, "r", encoding="utf-8") as f:
        table = json.load(f)
    rows = table["rows"]

    # ── 读取 skeleton ──
    if skeleton_path is None:
        skeleton_path = Path(__file__).parent / "skeletons" / "L1_intent_router_v3.skel.txt"
    else:
        skeleton_path = Path(skeleton_path)
    with open(skeleton_path, "r", encoding="utf-8") as f:
        skeleton = f.read()

    # ── 生成意图库 ──
    catalog = _build_intent_catalog(rows)

    # ── 填充占位符 ──
    prompt = skeleton.replace("{{INTENT_CATALOG}}", catalog)
    # {conversation} 保留为运行时占位符，不做替换

    # ── 输出 ──
    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"[OK] compiled prompt ({len(prompt)} chars) -> {out_path}")

    return prompt


# ── CLI ──
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JSON + skeleton → prompt 编译器 (L1)")
    parser.add_argument("registry", help="scene_table.json 路径")
    parser.add_argument(
        "--skeleton", "-s", default=None, help="skeleton 模板路径 (默认: skeletons/L1_intent_router_v3.skel.txt)"
    )
    parser.add_argument(
        "--out", "-o", default=None, help="输出 prompt 路径"
    )
    args = parser.parse_args()

    compile_prompt(args.registry, args.skeleton, args.out)
