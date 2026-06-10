"""
L0.5: scene_table.json 格式清洗
================================

在 L0 无损产物的基础上做纯格式清洗，不丢失信息，不引入语义判断。
所有清洗结果写入每个 row 的 `clean` 字段，原始 `cells` 不动。

清洗操作（均可独立开关）:
  FAQ 拆分        → clean.faq_items
  空白归一        → 所有 cells 多行文本首尾去空白、连续空行压缩、\r\n → \n
  风险等级归一化  → clean.risk_level（默认开，--no-normalize-risk 关闭）
  二级意图名修剪  → clean.intent_name

扩展: 后续操作只需新增一个 _clean_*() 函数并在 _clean_row() 中调用即可。

用法:
  python clean_scene_table.py <scene_table.json> [--out <json>] [--no-normalize-risk]

示例:
  python prompter/src/clean_scene_table.py artifacts/0604/scene_table.json
  python prompter/src/clean_scene_table.py scene_table.json --out clean.json --no-normalize-risk
"""

import json
import sys
from pathlib import Path


# ═══════════════════════════════════════════════════════════
# 单个清洗操作
# ═══════════════════════════════════════════════════════════

def _normalize_multiline(text: str) -> str:
    """多行文本空白归一：每行去首尾空白，连续空行压为单空行，\\r\\n → \\n。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = []
    prev_empty = False
    for line in lines:
        stripped = line.strip()
        if stripped:
            result.append(stripped)
            prev_empty = False
        elif not prev_empty:
            result.append("")
            prev_empty = True
    # 去掉尾部空行
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def _split_faq(text: str) -> list[str]:
    """将 FAQ 原始文本拆分为列表。

    支持常见 bullet: • · - 数字编号等。
    去空前缀后返回非空项。
    """
    lines = text.replace("\r\n", "\n").split("\n")
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 去掉常见 bullet 前缀
        for prefix in ("•", "·", "-", "●", "○", "■", "□"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
                break
        if stripped:
            items.append(stripped)
    return items


_RISK_MAP = {
    "低风险": "low",
    "中风险": "medium",
    "高风险": "high",
}


def _normalize_risk(raw: str) -> str | None:
    """中文风险等级 → 英文枚举。未知值返回 None。"""
    return _RISK_MAP.get(raw.strip())


# ═══════════════════════════════════════════════════════════
# 行清洗
# ═══════════════════════════════════════════════════════════

def _clean_row(cells: dict, *, normalize_risk: bool = True) -> dict:
    """对单行 cells 执行全部清洗操作，返回 clean dict。

    新增操作: 在下方添加 _clean_xxx() 调用即可。
    """
    clean: dict = {}

    # FAQ 拆分
    faq_text = cells.get("FAQ典型问题", "")
    if faq_text.strip():
        clean["faq_items"] = _split_faq(faq_text)

    # 风险等级归一化
    if normalize_risk:
        raw_risk = cells.get("风险等级", "")
        if raw_risk.strip():
            normalized = _normalize_risk(raw_risk)
            if normalized is not None:
                clean["risk_level"] = normalized
            else:
                clean["risk_level"] = None  # 未知值 → null
                print(
                    f"[WARN] row: unknown risk level [{raw_risk}]",
                    file=sys.stderr,
                )
        else:
            clean["risk_level"] = None

    # 二级意图名修剪
    intent_name = cells.get("二级意图", "").strip()
    if intent_name:
        clean["intent_name"] = intent_name

    # 空白归一（对关键长文本字段）
    for field in [
        "二级场景定义（供大模型识别意图使用）",
        "澄清指引/SOP",
        "回复设计",
        "前端设计",
        "备注",
    ]:
        text = cells.get(field, "")
        if text.strip():
            normalized = _normalize_multiline(text)
            # 仅当与原文不同时才写入
            if normalized != text:
                key = field.replace("（供大模型识别意图使用）", "")
                clean[f"text_{key}"] = normalized

    return clean


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def clean_table(
    registry_path: str | Path,
    out_path: str | Path | None = None,
    *,
    normalize_risk: bool = True,
) -> dict:
    """对 scene_table.json 执行格式清洗。

    Args:
        registry_path: L0 产出的 scene_table.json
        out_path:      输出路径；None 则仅返回 dict
        normalize_risk: 是否归一化风险等级

    Returns:
        清洗后的 dict（结构同 L0，每行增加 clean 字段）
    """
    registry_path = Path(registry_path)

    with open(registry_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 更新 schema version 标记
    data["schema_version"] = "v3.xlsx_table_clean.v1"

    for row in data["rows"]:
        row["clean"] = _clean_row(row["cells"], normalize_risk=normalize_risk)

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        n_cleaned = sum(1 for r in data["rows"] if r.get("clean"))
        print(f"[OK] cleaned {n_cleaned} rows -> {out_path}")

    return data


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="scene_table.json 格式清洗 (L0.5)")
    parser.add_argument("registry", help="L0 产出的 scene_table.json")
    parser.add_argument("--out", "-o", default=None, help="输出路径")
    parser.add_argument(
        "--no-normalize-risk",
        action="store_true",
        help="关闭风险等级归一化",
    )
    args = parser.parse_args()

    clean_table(
        args.registry,
        args.out,
        normalize_risk=not args.no_normalize_risk,
    )
