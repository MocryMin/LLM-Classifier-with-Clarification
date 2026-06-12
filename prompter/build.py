"""
prompter/build.py — V3 Prompt 一键编译 (运营团队工具)
====================================================

用法:
  【Case 1: 小白模式】
    1. 把场景设计 xlsx 放到 prompter/xlsx/ 里 (只能放一个)
    2. (可选) 把黄金样本 xlsx 放到 prompter/golden/ 里
    3. 双击运行: python build.py
    → 自动检测 golden, 有就跑全流程, 没有就只出 L1 prompt

  【Case 2: 进阶模式】
    python build.py --xlsx <path>                    指定 xlsx
    python build.py --xlsx <path> --mode classify_only
    python build.py --xlsx <path> --golden <xlsx>    指定黄金样本
    python build.py --xlsx <path> --no-llm           跳过 LLM 调优
    python build.py --xlsx <path> --deploy           编译后自动部署到 v3/
    python build.py --list                           列出可用文件

黄金样本 xlsx 格式 (极简, 放 prompter/golden/):
  列A: 用户输入    列B: 一级意图    列C: 二级意图
  支持多轮对话, 列A 中换行写: 用户:xxx \n 客服:xxx \n 用户:xxx

输出:
  prompter/output/<xlsx名>/
    scene_table.json           L0 产物
    scene_table_clean.json     L0.5 产物
    L1_router_v3.txt           L1 prompt (无LLM)
    L3_router_v3.txt           L3 prompt (经过 enrich + 微调, 如有 golden)
    golden_samples.json        (如有 golden xlsx)
    BUILD_REPORT.txt           构建报告
    L3_REPORT.md               微调报告 (如有 golden)
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE / "src"
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_PROJECT_ROOT))

import importlib.util

def _load_module(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# 按依赖顺序加载: 底层模块先加�?
_gt_mod   = _load_module("grammar_tree", _SRC / "grammar_tree.py")
_ser_mod  = _load_module("serialize", _SRC / "serialize.py")
_l0_mod   = _load_module("L0", _SRC / "L0_xlsx2json.py")
_l05_mod  = _load_module("L05", _SRC / "L0.5_format_json.py")
_l1_mod   = _load_module("L1", _SRC / "L1_generator.py")
_gxu_mod  = _load_module("golden_xlsx2json", _SRC / "golden_xlsx2json.py")
_l2_entry = _load_module("L2_entry", _SRC / "L2_entry.py")
_l3_entry = _load_module("L3_entry", _SRC / "L3_entry.py")


# ═══════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════

XLSX_DIR   = _HERE / "xlsx"
GOLDEN_DIR = _HERE / "golden"
OUTPUT_DIR = _HERE / "output"
V3_PROMPT  = _PROJECT_ROOT / "v3" / "prompt.txt"


# ═══════════════════════════════════════════════════════════
# Case 1: 小白模式 — 全自动
# ═══════════════════════════════════════════════════════════

def _find_xlsx(dir_path: Path) -> Path | None:
    """在目录中找唯一的 xlsx. 多个→报错, 零个→报错."""
    files = sorted(
        p for p in dir_path.iterdir()
        if p.suffix.lower() in (".xlsx", ".xls")
        and not p.name.startswith("~")
    )
    if not files:
        return None
    if len(files) > 1:
        names = ", ".join(f.name for f in files)
        raise RuntimeError(
            f"{dir_path} 下有多个 xlsx 文件: {names}\n"
            f"请只保留一个, 或使用 --xlsx 指定."
        )
    return files[0]


def _find_golden() -> Path | None:
    """查找黄金样本 xlsx."""
    if not GOLDEN_DIR.exists():
        return None
    return _find_xlsx(GOLDEN_DIR)


def _convert_golden(golden_xlsx: Path, out_dir: Path) -> Path:
    """将 ops golden xlsx 转为内部 json."""
    out_path = out_dir / "golden_samples.json"
    _gxu_mod.convert(str(golden_xlsx), str(out_path))
    return out_path


def build_case1() -> None:
    """小白模式: xlsx 放进去 → prompt 产出来."""
    print("\n" + "=" * 60)
    print("  V3 Prompt 一键编译 (小白模式)")
    print("=" * 60)

    # 1. 找场景 xlsx
    XLSX_DIR.mkdir(parents=True, exist_ok=True)
    xlsx_path = _find_xlsx(XLSX_DIR)
    if xlsx_path is None:
        print(f"\n[错误] {XLSX_DIR} 下没有 xlsx 文件.")
        print(f"请将场景设计 xlsx 放到该目录后重新运行.")
        print(f"运行 `python build.py --help` 查看进阶用法.")
        sys.exit(1)

    print(f"\n[场景表] {xlsx_path.name}")

    # 2. 找黄金样本
    golden_xlsx = _find_golden()
    has_golden = golden_xlsx is not None
    if has_golden:
        print(f"[黄金样本] {golden_xlsx.name}")
        print(f"[模式] 全流程 (L0→L1→L2→L3)")
    else:
        internal_golden = _HERE / "test" / "golden_samples.json"
        if internal_golden.exists():
            print(f"[黄金样本] 未在 {GOLDEN_DIR}/ 找到 xlsx，但检测到内部测试集")
            print(f"[模式] 全流程 (L0→L1→L2→L3, 使用内部 golden_samples.json)")
        else:
            print(f"[黄金样本] 未找到 (跳过 LLM 调优)")
            print(f"[模式] 快速模式 (仅 L0→L1)")

    # 3. 编译
    mode = "full"  # 默认需要 L2 澄清
    _build_pipeline(xlsx_path, mode, golden_xlsx=None if not has_golden else golden_xlsx, verbose=True)


# ═══════════════════════════════════════════════════════════
# Case 2: 进阶模式
# ═══════════════════════════════════════════════════════════

def build_case2(
    xlsx_path: str,
    mode: str = "full",
    golden_xlsx: str | None = None,
    no_llm: bool = False,
    deploy: bool = False,
    workers: int = 32,
    max_samples: int | None = None,
    verbose: bool = False,
) -> None:
    """进阶模式: 自定义参数."""

    xlsx_p = Path(xlsx_path).resolve()
    if not xlsx_p.exists():
        raise FileNotFoundError(f"xlsx 不存在: {xlsx_path}")

    golden_p = Path(golden_xlsx).resolve() if golden_xlsx else None
    if golden_p and not golden_p.exists():
        raise FileNotFoundError(f"黄金样本不存在: {golden_xlsx}")

    if golden_p and no_llm:
        print("[提示] 提供了黄金样本但 --no-llm 开启, 跳过 LLM 调优.")
        golden_p = None

    if not golden_p and not no_llm:
        # 尝试自动找
        auto_golden = _find_golden()
        if auto_golden:
            print(f"[自动检测] 找到黄金样本: {auto_golden.name}")
            golden_p = auto_golden
        else:
            print(f"[提示] 未找到黄金样本, LLM 调优跳过.")
            print(f"  如需 LLM 调优, 请将黄金样本 xlsx 放到 {GOLDEN_DIR}/")
            print(f"  或使用 --golden <path> 指定.")
            print(f"  或使用 --no-llm 跳过 LLM 调优 (仅输出 L1 prompt).")

    _build_pipeline(xlsx_p, mode, golden_xlsx=golden_p, workers=workers, max_samples=max_samples, verbose=verbose, skip_llm=no_llm)

    if deploy:
        _do_deploy()


# ═══════════════════════════════════════════════════════════
# 核心流水线
# ═══════════════════════════════════════════════════════════

def _build_pipeline(
    xlsx_path: Path,
    mode: str,
    golden_xlsx: Path | None = None,
    workers: int = 32,
    max_samples: int | None = None,
    verbose: bool = False,
    skip_llm: bool = False,
) -> dict:
    """统一流水线: L0→L0.5→L1→(L2)→(L3)."""

    xlsx_name = xlsx_path.stem
    out_dir = OUTPUT_DIR / xlsx_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  V3 Prompt 编译")
    print(f"  输入: {xlsx_path.name}")
    print(f"  模式: {mode}")
    print(f"  输出: {out_dir}")
    print(f"{'=' * 60}")

    t_start = datetime.now()

    # ── Step 1: L0 ──
    print("\n[1/5] L0: xlsx → JSON ...")
    scene_path = out_dir / "scene_table.json"
    l0_data = _l0_mod.extract(str(xlsx_path), str(scene_path))
    row_count = len(l0_data["rows"])
    print(f"       [OK] {row_count} 行 -> {scene_path.name}")

    # ── Step 2: L0.5 ──
    print("\n[2/5] L0.5: 格式清洗 ...")
    clean_path = out_dir / "scene_table_clean.json"
    _l05_mod.clean_table(str(scene_path), str(clean_path))
    print(f"       [OK] -> {clean_path.name}")

    # ── Step 3: L1 ──
    print(f"\n[3/5] L1: 文法树 (mode={mode}) ...")
    tree = _l1_mod.generate(str(clean_path), mode=mode)
    catalog = tree.sections[1].content
    intent_count = catalog.total_intents
    group_count = len(catalog.groups)
    print(f"       {group_count} 组, {intent_count} 场景")

    # 保存 L1 prompt (基线)
    l1_prompt = _ser_mod.serialize(tree)
    l1_path = out_dir / "L1_router_v3.txt"
    l1_path.write_text(l1_prompt, encoding="utf-8")
    print(f"       [OK] L1 prompt ({len(l1_prompt)} chars) -> {l1_path.name}")

    # ── 如果无 golden 或 skip_llm, 到此为止 ──
    if skip_llm:
        print(f"\n[提示] --no-llm 开启, 跳过 LLM 调优. 最终产物: {l1_path.name}")
        _write_build_report(out_dir, xlsx_name, mode, row_count, intent_count, group_count,
                          len(l1_prompt), has_llm=False)
        print(f"\n  最终 prompt: {l1_path}")
        return {}

    golden_json: Path | None = None
    has_llm = False

    if golden_xlsx and golden_xlsx.exists():
        golden_json = _convert_golden(golden_xlsx, out_dir)
        has_llm = True
    else:
        internal_golden = _HERE / "test" / "golden_samples.json"
        if internal_golden.exists():
            golden_json = internal_golden
            has_llm = True
            print(f"\n[黄金样本] 使用内部测试集: {len(json.loads(internal_golden.read_text('utf-8')))} 条")
        else:
            print(f"\n[提示] 无黄金样本, 跳过 LLM 调优. 最终产物: {l1_path.name}")
            _write_build_report(out_dir, xlsx_name, mode, row_count, intent_count, group_count,
                              len(l1_prompt), has_llm=False)
            print(f"\n  最终 prompt: {l1_path}")
            return {}

    # ── Step 4+5: L2+L3 (LLM 调优) ──
    print(f"\n[4/5] L2 enrich + L3 微调 (需要 LLM, 请耐心等待) ...")
    artifact = _gt_mod.PromptArtifact(tree=tree)

    # L2
    result_l2 = _l2_entry.run_l2_pipeline(
        registry=str(clean_path),
        mode=mode,
        artifact=artifact,
        golden_samples=str(golden_json),
        workers=workers,
        max_golden_samples=max_samples,
        verbose=verbose,
    )

    # 保存 L2 中间产物
    l2_prompt = artifact.prompt
    l2_path = out_dir / "L2_router_v3.txt"
    l2_path.write_text(l2_prompt, encoding="utf-8")
    if verbose:
        print(f"       [OK] L2 prompt ({len(l2_prompt)} chars) -> {l2_path.name}")

    # 如果 L2 有 golden 结果, 继续 L3
    baseline_details = None
    if has_llm and golden_json and golden_json.exists():
        # 重新跑一次基线获取 per-sample details (L2 内部有自己的基线跑法)
        # 我们直接从 L2 的 golden_validate 里拿
        from L2_golden_validate import _run_golden_set
        current_prompt = artifact.prompt
        _, _, _, baseline_details = _run_golden_set(
            current_prompt,
            json.loads(golden_json.read_text("utf-8")),
            max_samples=max_samples,
            workers=workers,
            verbose=False,
        )

    if baseline_details:
        # L3
        print(f"\n[5/5] L3: 错例微调 ...")
        result_l3 = _l3_entry.run_l3_pipeline(
            artifact=artifact,
            baseline_details=baseline_details,
            golden_samples=str(golden_json),
            workers=workers,
            max_errors=max_samples,
            verbose=False,
        )
        l3_report = result_l3.get("report", "")
    else:
        l3_report = ""

    # ── 保存最终产物 ──
    final_prompt = artifact.prompt
    final_path = out_dir / "L3_router_v3.txt"
    final_path.write_text(final_prompt, encoding="utf-8")
    print(f"       [OK] 最终 prompt ({len(final_prompt)} chars) -> {final_path.name}")

    if l3_report:
        report_md = out_dir / "L3_REPORT.md"
        report_md.write_text(l3_report, encoding="utf-8")
        print(f"       [OK] 微调报告 -> {report_md.name}")

    # ── 构建报告 ──
    _write_build_report(out_dir, xlsx_name, mode, row_count, intent_count, group_count,
                      len(final_prompt), has_llm=has_llm, l3_report=l3_report)

    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"  完成! ({elapsed:.1f}s)")
    print(f"  L1 prompt (无LLM): {l1_path}")
    if has_llm:
        print(f"  L3 prompt (经调优): {final_path}")
    print(f"  构建报告: {out_dir / 'BUILD_REPORT.txt'}")
    print(f"{'=' * 60}")

    return {}


# ═══════════════════════════════════════════════════════════
# 部署
# ═══════════════════════════════════════════════════════════

def _do_deploy():
    """部署最终 prompt 到 v3/."""
    # 找最新的 L3 或 L1 prompt
    outputs = sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for out_dir in outputs:
        if not out_dir.is_dir():
            continue
        l3 = out_dir / "L3_router_v3.txt"
        l1 = out_dir / "L1_router_v3.txt"
        src = l3 if l3.exists() else l1
        if not src.exists():
            continue

        if V3_PROMPT.exists():
            backup = V3_PROMPT.with_suffix(".txt.bak")
            shutil.copy2(str(V3_PROMPT), str(backup))
            print(f"       [OK] 旧版本备份: {backup.name}")

        shutil.copy2(str(src), str(V3_PROMPT))
        print(f"       [OK] 部署到 {V3_PROMPT} (重启 server 生效)")
        return
    print(f"       [WARN] 未找到可部署的 prompt")


# ═══════════════════════════════════════════════════════════
# 构建报告
# ═══════════════════════════════════════════════════════════

_CN_NUM = ["零", "一", "二", "三", "四", "五", "六"]

def _write_build_report(
    out_dir: Path, xlsx_name: str, mode: str,
    row_count: int, intent_count: int, group_count: int,
    prompt_chars: int, has_llm: bool = False, l3_report: str = "",
):
    mode_label = "常规模式 (含L2澄清)" if mode == "full" else "仅分类+L1澄清"
    llm_label = "L0→L1→L2→L3 (LLM调优)" if has_llm else "L0→L1 (无LLM, 最快)"

    lines = [
        f"V3 Prompt 构建报告",
        f"{'=' * 60}",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"源文件: {xlsx_name}",
        f"模式: {mode_label}",
        f"流程: {llm_label}",
        f"",
        f"数据统计",
        f"{'=' * 60}",
        f"  场景行数: {row_count}",
        f"  二级意图: {intent_count}",
        f"  一级分组: {group_count}",
        f"  Prompt: {prompt_chars} chars",
        f"",
        f"输出文件",
        f"{'=' * 60}",
        f"  {out_dir / 'L1_router_v3.txt'}  ← L1 prompt (无LLM基线)",
    ]
    if has_llm:
        lines.append(f"  {out_dir / 'L3_router_v3.txt'}  ← L3 prompt (经过调优)")
        lines.append(f"  {out_dir / 'L3_REPORT.md'}      ← 微调报告")
    lines.append(f"  {out_dir / 'BUILD_REPORT.txt'}   ← 本报告")

    report_path = out_dir / "BUILD_REPORT.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# 交互式 (Case 1 入口)
# ═══════════════════════════════════════════════════════════

def _interactive():
    """Case 1 交互式向导."""
    print("\n  欢迎使用 V3 Prompt 编译工具!")
    print()

    # 1. 检查 xlsx
    XLSX_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    xlsx_files = sorted(
        p for p in XLSX_DIR.iterdir()
        if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~")
    )

    if not xlsx_files:
        print(f"[错误] 在 {XLSX_DIR} 下没有找到 xlsx 文件.")
        print(f"请将场景设计表 xlsx 放到该目录后重新运行.")
        sys.exit(1)

    # 2. 选择 xlsx
    if len(xlsx_files) == 1:
        xlsx_path = xlsx_files[0]
        print(f"[场景表] {xlsx_path.name}")
    else:
        print("找到多个 xlsx 文件:")
        for i, f in enumerate(xlsx_files, 1):
            print(f"  [{i}] {f.name}")
        choice = input(f"请选择 [1-{len(xlsx_files)}]: ").strip()
        try:
            xlsx_path = xlsx_files[int(choice) - 1]
        except (ValueError, IndexError):
            print("无效选择.")
            sys.exit(1)

    # 3. 检查 golden
    golden_files = sorted(
        p for p in GOLDEN_DIR.iterdir()
        if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~")
    )

    has_golden = False
    golden_path = None
    if golden_files:
        if len(golden_files) == 1:
            golden_path = golden_files[0]
            print(f"[黄金样本] {golden_path.name}")
        else:
            print("\n找到多个黄金样本:")
            for i, f in enumerate(golden_files, 1):
                print(f"  [{i}] {f.name}")
            print(f"  [s] 跳过 LLM 调优")
            choice = input(f"请选择 [1-{len(golden_files)}/s]: ").strip()
            if choice.lower() != "s":
                try:
                    golden_path = golden_files[int(choice) - 1]
                except (ValueError, IndexError):
                    print("无效选择, 跳过 LLM 调优.")

        has_golden = golden_path is not None
    else:
        internal_golden = _HERE / "test" / "golden_samples.json"
        if internal_golden.exists():
            print(f"[黄金样本] 未在 {GOLDEN_DIR}/ 找到 xlsx，但检测到内部测试集 (test/golden_samples.json)")
        else:
            print(f"[黄金样本] 未找到 (跳过 LLM 调优)")
            print(f"  如需 LLM 调优, 请将黄金样本 xlsx 放到 {GOLDEN_DIR}/")

    # 4. 编译
    mode = "full"  # 默认含 L2 澄清
    _build_pipeline(xlsx_path, mode, golden_xlsx=golden_path)


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="V3 Prompt 一键编译 (运营团队)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build.py                             小白模式 (自动检测)
  python build.py --xlsx xlsx/0604.xlsx       指定文件
  python build.py --xlsx xlsx/0604.xlsx --mode classify_only
  python build.py --xlsx xlsx/0604.xlsx --golden golden/test.xlsx
  python build.py --xlsx xlsx/0604.xlsx --no-llm
  python build.py --xlsx xlsx/0604.xlsx --deploy
  python build.py --list                      列出可用文件

黄金样本 xlsx 格式:
  列A: 用户输入    列B: 一级意图    列C: 二级意图
  放在 prompter/golden/ 下, build.py 自动检测.
        """,
    )
    parser.add_argument("--xlsx", "-x", help="场景设计 xlsx 路径")
    parser.add_argument("--mode", "-m", choices=["full", "classify_only"], default="full",
                       help="full=含L2澄清(默认) | classify_only=仅分类")
    parser.add_argument("--golden", "-g", help="黄金样本 xlsx 路径")
    parser.add_argument("--no-llm", action="store_true",
                       help="跳过 LLM 调优 (仅输出 L1 prompt)")
    parser.add_argument("--workers", "-w", type=int, default=32,
                       help="黄金验证并发 worker 数 (默认: 32)")
    parser.add_argument("--max-samples", type=int, default=None,
                       help="快速调试用: 限制黄金验证样本数 (默认: 全量)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="详细输出 (显示 enrich/sample/revision 内容)")
    parser.add_argument("--deploy", "-d", action="store_true",
                       help="编译后自动部署到 v3/")
    parser.add_argument("--list", "-l", action="store_true",
                       help="列出可用文件")

    args = parser.parse_args()

    XLSX_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        xlsx_files = sorted(p for p in XLSX_DIR.iterdir() if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~"))
        golden_files = sorted(p for p in GOLDEN_DIR.iterdir() if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~"))
        print(f"\n{XLSX_DIR}/ (场景设计):")
        for f in xlsx_files:
            print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")
        if not xlsx_files:
            print(f"  (空)")
        print(f"\n{GOLDEN_DIR}/ (黄金样本):")
        for f in golden_files:
            print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")
        if not golden_files:
            print(f"  (空)")
        sys.exit(0)

    if args.xlsx:
        build_case2(args.xlsx, mode=args.mode, golden_xlsx=args.golden,
                    no_llm=args.no_llm, deploy=args.deploy,
                    workers=args.workers, max_samples=args.max_samples,
                    verbose=args.verbose)
    elif args.no_llm or args.deploy or args.golden or args.workers != 16 or args.max_samples is not None:
        # 有 CLI flag 但没有 --xlsx → 自动找 xlsx 并接管
        XLSX_DIR.mkdir(parents=True, exist_ok=True)
        xlsx_files = sorted(
            p for p in XLSX_DIR.iterdir()
            if p.suffix.lower() in (".xlsx", ".xls") and not p.name.startswith("~")
        )
        if not xlsx_files:
            print(f"[错误] prompter/xlsx/ 下没有 xlsx 文件.")
            sys.exit(1)
        if len(xlsx_files) > 1:
            print(f"[错误] prompter/xlsx/ 下有多个文件，使用 --xlsx 指定.")
            sys.exit(1)
        auto_xlsx = str(xlsx_files[0])
        print(f"[自动检测] {xlsx_files[0].name}")
        build_case2(auto_xlsx, mode=args.mode, golden_xlsx=args.golden,
                    no_llm=args.no_llm, deploy=args.deploy,
                    workers=args.workers, max_samples=args.max_samples,
                    verbose=args.verbose)
    else:
        # Case 1: 交互式小白模式
        _interactive()
