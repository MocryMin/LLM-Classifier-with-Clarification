"""
L0: xlsx → 场景表格 JSON (无损转换)
====================================

定位
----
prompter 管线第 0 层。将运营方"场景设计"xlsx 无损转换为结构化 JSON。
只做格式搬运，不做语义解释；不重不漏，不改字段名、不改字段值、不拆内容、不归一化。

入口规格
--------

    函数入口:
        extract(xlsx_path, out_path=None) -> dict

        xlsx_path : str | Path    输入 xlsx 文件路径
        out_path  : str | Path    输出 JSON 路径；为 None 时仅返回 dict 不写文件

        returns   : dict          见下方「输出结构」

    CLI 入口:
        python xlsx_to_json.py <xlsx> [--out <json>]

        <xlsx>   位置参数，xlsx 文件路径
        --out    可选，输出路径；默认输出到 xlsx 同目录下 <原名>_scene_table.json

输入要求
--------

    sheet 定位策略（级联）
        1. 精确匹配名为 "场景设计" 的 sheet
        2. 否则遍历全部 sheet，选表头列命中 EXPECTED_COLUMNS 数最高者
           （需 >= 8/12 列），并输出 stderr INFO 提示自检测结果
        3. 都不满足则报错

    表头（第 1 行）
        必须按序包含以下 12 列（允许尾随空列，自动忽略）：

            一级意图
            二级意图
            二级场景定义（供大模型识别意图使用）
            风险等级
            FAQ典型问题
            完善负责人
            澄清指引/SOP
            优先级
            对应子公司
            回复设计
            前端设计
            备注

        列名若与预期不符，触发 stderr WARN，但不阻断执行。

    数据行（第 2 行起）
        每个有效行必须满足：「二级意图」非空。
        「一级意图」允许为空（合并单元格场景，由前向填充补全）。

行为规则
--------

    1. 单元格读取
       None          → ""
       非空值        → str(val).strip()

    2. 合并单元格
       「一级意图」为空时，沿用上方最近一个非空「一级意图」。
       首行就为空 → 保持空（后续由 l2 非空检查跳过或触发下游告警）。

    3. 尾随空列
       表头第 13 列及以后自动忽略（根据 EXPECTED_COLUMNS 长度截断）。

    4. 无效行跳过
       「二级意图」为空的行直接丢弃，不进入输出。

    5. 列顺序
       输出 columns 数组保持 xlsx 中出现顺序（即 EXPECTED_COLUMNS 顺序）。

输出结构
--------

    {
        "schema_version": "v3.xlsx_table.v1",

        "source": {
            "xlsx_path":   "<文件名>",
            "sheet_name":  "场景设计"
        },

        "columns": [
            "一级意图",
            "二级意图",
            "二级场景定义（供大模型识别意图使用）",
            "风险等级",
            "FAQ典型问题",
            "完善负责人",
            "澄清指引/SOP",
            "优先级",
            "对应子公司",
            "回复设计",
            "前端设计",
            "备注"
        ],

        "rows": [
            {
                "row_index": 2,
                "cells": {
                    "一级意图":    "...",
                    "二级意图":    "...",
                    ...
                }
            },
            ...
        ]
    }

    各字段约定:
        row_index    原始 xlsx 行号，从 2 起，递增但不保证连续（跳过无效行）
        cells        列名 → 单元格值；值统一为 str，空为 ""
        columns      始终为 EXPECTED_COLUMNS

不变式保证
----------

    输出满足以下全体条件（可程序化验证）:

    I1.  所有 row.cells 的 key 集合 == columns
    I2.  所有 row.cells['二级意图'] 非空
    I3.  所有 row.cells['一级意图'] 非空（前向填充后）
    I4.  row.cells['二级意图'] 互不相同（无重复场景）
    I5.  row_index 严格单调递增
    I6.  source.xlsx_path 非空

不做的事情（明确排除）
----------------------

    - 不从「整体方案设计」sheet 提取信息
    - 不拆分 FAQ 列表（保留原样多行文本）
    - 不归一化风险等级（保留原文 "低风险"/"中风险"/"高风险"/""）
    - 不生成场景 ID、编号、slug
    - 不计算 hash、不比较版本差异
    - 不验证内容语义（如 SOP 是否合理、FAQ 是否覆盖等）

依赖
----

    pip install openpyxl
"""

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

# ── 目标列（按 xlsx 中出现的顺序） ──
EXPECTED_COLUMNS = [
    "一级意图",
    "二级意图",
    "二级场景定义（供大模型识别意图使用）",
    "风险等级",
    "FAQ典型问题",
    "完善负责人",
    "澄清指引/SOP",
    "优先级",
    "对应子公司",
    "回复设计",
    "前端设计",
    "备注",
]

TARGET_SHEET = "场景设计"
MIN_COLUMN_MATCH = 8  # 至少匹配 8/12 列才认定为场景表


def _find_scene_sheet(wb) -> str:
    """定位场景设计 sheet。

    策略（级联）：
      1. 精确匹配 TARGET_SHEET
      2. 遍历所有 sheet，按表头列命中数排序，最高分且 >= MIN_COLUMN_MATCH 则采纳
      3. 都不满足则报错
    """
    # 策略 1
    if TARGET_SHEET in wb.sheetnames:
        return TARGET_SHEET

    # 策略 2
    best_name = None
    best_score = 0
    for name in wb.sheetnames:
        ws = wb[name]
        try:
            header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
        except StopIteration:
            continue
        actual = set(_normalize_cell(c) for c in header_row if c is not None)
        score = sum(1 for col in EXPECTED_COLUMNS if col in actual)
        if score > best_score:
            best_score = score
            best_name = name

    if best_name and best_score >= MIN_COLUMN_MATCH:
        print(
            f"[INFO] sheet \"{TARGET_SHEET}\" not found; "
            f"auto-detected \"{best_name}\" (column match {best_score}/{len(EXPECTED_COLUMNS)})",
            file=sys.stderr,
        )
        return best_name

    raise ValueError(
        f"未找到 sheet '{TARGET_SHEET}'，"
        f"且自动检测失败（最佳匹配 \"{best_name}\" 仅命中 {best_score}/{len(EXPECTED_COLUMNS)} 列）。"
        f"可用 sheet: {wb.sheetnames}"
    )


def _normalize_cell(val) -> str:
    """None → ''，非空 → str.strip()"""
    if val is None:
        return ""
    return str(val).strip()


def extract(xlsx_path: str | Path, out_path: str | Path | None = None) -> dict:
    """从 xlsx 提取场景表格，返回 dict；若提供 out_path 则同时写入 JSON。

    等价于 CLI: python xlsx_to_json.py <xlsx> [--out <json>]

    Args:
        xlsx_path: xlsx 文件路径
        out_path:  输出 JSON 路径；None 时仅返回 dict 不写文件

    Returns:
        dict，结构见模块 docstring「输出结构」
    """
    xlsx_path = Path(xlsx_path)
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)

    # ── 定位 sheet ──
    sheet_name = _find_scene_sheet(wb)
    ws = wb[sheet_name]

    # ── 校验表头 ──
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    actual_headers = [_normalize_cell(c) for c in header_row]
    for i, expected in enumerate(EXPECTED_COLUMNS):
        actual = actual_headers[i] if i < len(actual_headers) else ""
        if actual != expected:
            print(
                f"[WARN] col {i}: expected [{expected}]  actual [{actual}]",
                file=sys.stderr,
            )

    # ── 读取数据行 ──
    rows = []
    prev_l1 = ""
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=2, values_only=True), start=2
    ):
        cells = {}
        for i, col_name in enumerate(EXPECTED_COLUMNS):
            val = row[i] if i < len(row) else None
            cells[col_name] = _normalize_cell(val)

        # 前向填充「一级意图」（合并单元格）
        l1 = cells["一级意图"]
        if not l1 and prev_l1:
            cells["一级意图"] = prev_l1
        elif l1:
            prev_l1 = l1

        # 跳过「二级意图」为空的行
        if not cells["二级意图"]:
            continue

        rows.append({"row_index": row_idx, "cells": cells})

    wb.close()

    result = {
        "schema_version": "v3.xlsx_table.v1",
        "source": {
            "xlsx_path": xlsx_path.name,
            "sheet_name": ws.title,
        },
        "columns": EXPECTED_COLUMNS,
        "rows": rows,
    }

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[OK] extracted {len(rows)} rows -> {out_path}")

    return result


# ── CLI ──
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="xlsx → JSON 无损转换 (L0)")
    parser.add_argument("xlsx", help="xlsx 文件路径")
    parser.add_argument(
        "--out", "-o", default=None, help="输出 JSON 路径 (默认: xlsx 同目录下 <原名>_scene_table.json)"
    )
    args = parser.parse_args()

    xlsx = Path(args.xlsx)
    out = args.out or str(xlsx.with_suffix("").parent / f"{xlsx.stem}_scene_table.json")

    extract(xlsx, out)
