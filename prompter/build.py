"""
prompter/build.py —— 一键编译 V3 Prompt (运营团队工具)
======================================================

将 xlsx 场景设计表放到 prompter/xlsx/ 目录, 运行本脚本,
自动完成 L0→L0.5→L1 全套编译, 输出可直接使用的 prompt 文件。

用法:
  python build.py                          交互式: 列出文件 → 选择 → 编译
  python build.py --xlsx <path>            指定 xlsx, 默认 full 模式
  python build.py --xlsx <path> --mode classify_only  仅分类+L1澄清
  python build.py --xlsx <path> --deploy   编译后自动部署到 v3/
  python build.py --list                   列出可用 xlsx 文件

输出:
  prompter/output/<xlsx名>/scene_table.json         L0 产物
  prompter/output/<xlsx名>/scene_table_clean.json   L0.5 产物
  prompter/output/<xlsx名>/L1_router_v3.txt         L1 产物 (最终)
  prompter/output/<xlsx名>/BUILD_REPORT.txt         构建报告
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

# ── 确保 prompter/src 可导入 ──
_HERE = Path(__file__).resolve().parent
_SRC = _HERE / "src"
sys.path.insert(0, str(_SRC))

from L0_xlsx2json import extract as l0_extract

# L0.5 / L1_generator / serialize 文件名含点或为包内模块, 用 importlib 加载
import importlib.util

def _load_module(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_l0_5 = _load_module("l0_5", _SRC / "L0.5_format_json.py")
l0_5_clean = _l0_5.clean_table

_l1_gen = _load_module("l1_gen", _SRC / "L1_generator.py")
l1_generate = _l1_gen.generate

_ser = _load_module("serialize", _SRC / "serialize.py")
serialize = _ser.serialize


# ═══════════════════════════════════════════════════════════
# 路径配置
# ═══════════════════════════════════════════════════════════

PROJECT_ROOT = _HERE.parent
XLSX_DIR = _HERE / "xlsx"
OUTPUT_DIR = _HERE / "output"
V3_PROMPT_PATH = PROJECT_ROOT / "v3" / "L1_router_v3.txt"


# ═══════════════════════════════════════════════════════════
# 核心编译
# ═══════════════════════════════════════════════════════════

def build(xlsx_path: str | Path, mode: str = "full") -> dict:
    """
    一键编译: xlsx → L0 → L0.5 → L1 文法树 → prompt 文本.

    Args:
        xlsx_path: xlsx 文件路径
        mode: "full" | "classify_only"

    Returns:
        {
            "xlsx_path": str,
            "xlsx_name": str,
            "mode": str,
            "output_dir": Path,
            "scene_table_path": Path,
            "scene_table_clean_path": Path,
            "prompt_path": Path,
            "report_path": Path,
            "intent_count": int,
            "group_count": int,
            "prompt_chars": int,
        }
    """
    xlsx_path = Path(xlsx_path).resolve()
    if not xlsx_path.exists():
        raise FileNotFoundError(f"xlsx not found: {xlsx_path}")

    xlsx_name = xlsx_path.stem  # 不含扩展名的文件名
    out_dir = OUTPUT_DIR / xlsx_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  V3 Prompt 一键编译")
    print(f"  输入: {xlsx_path.name}")
    print(f"  模式: {mode}")
    print(f"  输出: {out_dir}")
    print(f"{'=' * 60}")

    # ── Step 1: L0 xlsx → json ──
    print("\n[1/3] L0: xlsx → JSON ...")
    scene_path = out_dir / "scene_table.json"
    l0_data = l0_extract(str(xlsx_path), str(scene_path))
    row_count = len(l0_data["rows"])
    print(f"       [OK] {row_count} 行场景数据 -> {scene_path.name}")

    # ── Step 2: L0.5 格式清洗 ──
    print("\n[2/3] L0.5: 格式清洗 ...")
    clean_path = out_dir / "scene_table_clean.json"
    l0_5_data = l0_5_clean(str(scene_path), str(clean_path))
    faq_count = sum(
        1 for r in l0_5_data["rows"]
        if r.get("clean", {}).get("faq_items")
    )
    risk_count = sum(
        1 for r in l0_5_data["rows"]
        if r.get("clean", {}).get("risk_level") is not None
    )
    print(f"       [OK] FAQ 拆分: {faq_count} 行, 风险归一: {risk_count} 行")

    # ── Step 3: L1 文法树 → prompt ──
    print(f"\n[3/3] L1: 文法树生成 (mode={mode}) ...")
    tree = l1_generate(str(clean_path), mode=mode)
    catalog = tree.sections[1].content  # IntentCatalog
    intent_count = catalog.total_intents
    group_count = len(catalog.groups)
    print(f"       {group_count} 个一级分组, {intent_count} 个二级场景")

    # 序列化
    prompt_text = serialize(tree)
    prompt_path = out_dir / "L1_router_v3.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    print(f"       [OK] prompt ({len(prompt_text)} chars) -> {prompt_path.name}")

    # ── 生成构建报告 ──
    report = _generate_report(
        xlsx_path=xlsx_path,
        xlsx_name=xlsx_name,
        mode=mode,
        out_dir=out_dir,
        row_count=row_count,
        intent_count=intent_count,
        group_count=group_count,
        prompt_chars=len(prompt_text),
        faq_count=faq_count,
        risk_count=risk_count,
        groups=catalog.groups,
    )
    report_path = out_dir / "BUILD_REPORT.txt"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  编译完成!")
    print(f"  Prompt: {prompt_path}")
    print(f"  报告:   {report_path}")
    print(f"{'=' * 60}")

    return {
        "xlsx_path": str(xlsx_path),
        "xlsx_name": xlsx_name,
        "mode": mode,
        "output_dir": out_dir,
        "scene_table_path": scene_path,
        "scene_table_clean_path": clean_path,
        "prompt_path": prompt_path,
        "report_path": report_path,
        "intent_count": intent_count,
        "group_count": group_count,
        "prompt_chars": len(prompt_text),
    }


def deploy(prompt_path: str | Path) -> None:
    """将生成的 prompt 部署到 v3/ 目录, 使其立即生效。"""
    prompt_path = Path(prompt_path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt not found: {prompt_path}")

    # 备份旧版本
    if V3_PROMPT_PATH.exists():
        backup = V3_PROMPT_PATH.with_suffix(".txt.bak")
        shutil.copy2(str(V3_PROMPT_PATH), str(backup))
        print(f"       [OK] 已备份旧版本 -> {backup.name}")

    # 部署
    shutil.copy2(str(prompt_path), str(V3_PROMPT_PATH))
    print(f"       [OK] 已部署到 v3/L1_router_v3.txt (重启 server 后生效)")


# ═══════════════════════════════════════════════════════════
# 构建报告
# ═══════════════════════════════════════════════════════════

_CN_NUM = [
    "零", "一", "二", "三", "四", "五", "六",
]


def _generate_report(
    xlsx_path: Path,
    xlsx_name: str,
    mode: str,
    out_dir: Path,
    row_count: int,
    intent_count: int,
    group_count: int,
    prompt_chars: int,
    faq_count: int,
    risk_count: int,
    groups,
) -> str:
    mode_label = "常规模式 (含L2澄清)" if mode == "full" else "仅分类+L1澄清"

    lines = [
        f"V3 Prompt 构建报告",
        f"{'=' * 60}",
        f"",
        f"构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"源文件:   {xlsx_path.name}",
        f"Sheet:    场景设计",
        f"模式:     {mode_label}",
        f"",
        f"数据统计",
        f"{'=' * 60}",
        f"  场景行数:     {row_count}",
        f"  二级意图:     {intent_count}",
        f"  一级分组:     {group_count}",
        f"  FAQ 拆分:     {faq_count} 行",
        f"  风险归一:     {risk_count} 行",
        f"  Prompt 字符:  {prompt_chars}",
        f"",
        f"一级分组明细",
        f"{'=' * 60}",
    ]

    for g in groups:
        n = _CN_NUM[g.group_index] if g.group_index < len(_CN_NUM) else str(g.group_index)
        lines.append(f"  {n}. {g.l1_name} ({g.intent_count} 个场景)")
        for intent in g.intents:
            sop_mark = " [有SOP]" if intent.has_sop else ""
            lines.append(f"     {intent.display_id} {intent.l2}{sop_mark}")

    lines.extend([
        f"",
        f"输出文件",
        f"{'=' * 60}",
        f"  {out_dir / 'scene_table.json'}",
        f"  {out_dir / 'scene_table_clean.json'}",
        f"  {out_dir / 'L1_router_v3.txt'}  ← 最终 prompt",
        f"",
        f"部署方法",
        f"{'=' * 60}",
        f"  python prompter/build.py --xlsx <路径> --deploy",
        f"  或手动复制:",
        f"  cp {out_dir / 'L1_router_v3.txt'} {V3_PROMPT_PATH}",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 交互模式
# ═══════════════════════════════════════════════════════════

def _list_xlsx() -> list[Path]:
    """列出 prompter/xlsx/ 下所有 xlsx 文件。"""
    if not XLSX_DIR.exists():
        return []
    return sorted(
        p for p in XLSX_DIR.iterdir()
        if p.suffix.lower() in (".xlsx", ".xls")
        and not p.name.startswith("~")
    )


def _interactive():
    """交互式模式: 列出文件 → 用户选择 → 编译。"""
    xlsx_files = _list_xlsx()

    if not xlsx_files:
        print("错误: prompter/xlsx/ 目录下没有 xlsx 文件。")
        print(f"\n请将场景设计 xlsx 放到: {XLSX_DIR}")
        print("然后重新运行: python build.py")
        sys.exit(1)

    print("\n可用的 xlsx 文件:\n")
    for i, f in enumerate(xlsx_files):
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  [{i + 1}] {f.name}  ({size_kb:.0f} KB, {mtime})")

    print(f"\n  [q] 退出")

    # 选择文件
    while True:
        choice = input(f"\n请选择文件 [1-{len(xlsx_files)}]: ").strip()
        if choice.lower() == "q":
            print("已取消.")
            sys.exit(0)
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(xlsx_files):
                xlsx_path = xlsx_files[idx]
                break
        except ValueError:
            pass
        print(f"  请输入 1-{len(xlsx_files)} 或 q")

    # 选择模式
    print("\n选择编译模式:")
    print("  [1] full (常规模式, 含L2澄清) ← 默认")
    print("  [2] classify_only (仅分类+L1澄清)")
    mode_choice = input("请选择 [1/2, 默认1]: ").strip()
    mode = "classify_only" if mode_choice == "2" else "full"

    # 编译
    result = build(xlsx_path, mode=mode)

    # 是否部署
    deploy_choice = input(f"\n是否部署到 v3/ 使其立即生效? [y/N]: ").strip().lower()
    if deploy_choice == "y":
        deploy(result["prompt_path"])

    # 打印报告
    print()
    print(Path(result["report_path"]).read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="V3 Prompt 一键编译工具 (运营团队)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build.py                             交互式选择
  python build.py --list                      列出可用 xlsx
  python build.py --xlsx ../xlsx/0604.xlsx    指定文件编译
  python build.py --xlsx ../xlsx/0604.xlsx --mode classify_only
  python build.py --xlsx ../xlsx/0604.xlsx --deploy  编译+部署
        """,
    )
    parser.add_argument("--xlsx", "-x", help="xlsx 文件路径")
    parser.add_argument(
        "--mode", "-m",
        choices=["full", "classify_only"],
        default="full",
        help="编译模式 (默认: full)",
    )
    parser.add_argument("--deploy", "-d", action="store_true",
                       help="编译后自动部署到 v3/")
    parser.add_argument("--list", "-l", action="store_true",
                       help="列出可用 xlsx 文件")

    args = parser.parse_args()

    # 确保输出目录存在
    XLSX_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        files = _list_xlsx()
        if files:
            print(f"\n{XLSX_DIR}/ 下的文件:\n")
            for f in files:
                size_kb = f.stat().st_size / 1024
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                print(f"  {f.name}  ({size_kb:.0f} KB, {mtime})")
        else:
            print(f"\n{XLSX_DIR}/ 下暂无 xlsx 文件")
        sys.exit(0)

    # 交互模式
    if not args.xlsx:
        _interactive()
        sys.exit(0)

    # 命令行模式
    result = build(args.xlsx, args.mode)

    if args.deploy:
        print()
        deploy(result["prompt_path"])

    # 打印报告
    print()
    print(Path(result["report_path"]).read_text(encoding="utf-8"))
