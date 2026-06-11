"""
L2_entry.py — L2 enrich 统一入口
================================

Co-agent 可直接调用 run_l2_pipeline()，传入 clean JSON 路径即可完成全流程。

流程:
  1. 构建 PromptArtifact (文法树 + 渲染文本 双生容器)
  2. enrich 产生申请 (L2_enrich)
  3. 确定性验证 (L2_validator)
  4. 黄金样本贪心验证 (L2_golden_validate, 如提供 golden_samples)
  5. 应用通过的申请 (L2_applier)
  6. invalidate → 重新序列化 → 最终 prompt
  7. 生成报告

用法:
    from L2_entry import run_l2_pipeline

    result = run_l2_pipeline(
        registry="prompter/temp/0604/scene_table_clean.json",
        mode="full",
        golden_samples="prompter/test/golden_samples.json",
        workers=8,
    )

    # result["output_prompt"]        → 最终 prompt 文本 (面向用户/LLM)
    # result["output_artifact"]      → PromptArtifact 双生容器 (面向程序, 可继续操作文法树)
    # result["output_artifact"].tree → 当前文法树
    # result["output_artifact"].prompt → 当前 prompt 文本 (与 output_prompt 一致)
    # result["report"]               → 黄金验证报告 (markdown)
    # result["metadata"]             → 结构化元数据 (供程序消费)
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 兼容直接执行和包导入
try:
    from .grammar_tree import PromptArtifact
    from .L2_enrich import enrich
    from .L2_validator import validate_all
    from .L2_golden_validate import greedy_accept, generate_golden_report
    from .L2_applier import apply_all
except ImportError:
    from grammar_tree import PromptArtifact
    from L2_enrich import enrich
    from L2_validator import validate_all
    from L2_golden_validate import greedy_accept, generate_golden_report
    from L2_applier import apply_all


def run_l2_pipeline(
    registry: str | Path,
    mode: str = "full",
    artifact: PromptArtifact | None = None,  # 可传入已有 artifact
    golden_samples: str | Path | None = None,
    model: str = "deepseek-v4-pro",
    workers: int = 8,
    max_golden_samples: int | None = None,
    api_key: str | None = None,
    output_prompt: str | Path | None = None,
    output_report: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """L2 enrich 全流程统一入口.

    始终维护两个数据: tree (面向程序) 和 prompt (面向用户/LLM).
    通过 PromptArtifact 双生容器保持一致.

    Args:
        registry: L0.5 产出的 scene_table_clean.json 路径
        mode: "full" | "classify_only"
        artifact: 已有的 PromptArtifact (None=从 registry 构建)
        golden_samples: 黄金样本 JSON 路径 (None=跳过黄金验证)
        model: LLM 模型名称
        workers: 黄金验证并发数
        max_golden_samples: 限制黄金样本数 (None=全部)
        api_key: API key (默认从环境变量读取)
        output_prompt: 输出最终 prompt 路径 (None=不保存文件)
        output_report: 输出报告路径 (None=不保存文件)
        verbose: 打印详细进度

    Returns:
        {
            "status": "ok" | "partial" | "no_golden" | "no_applications",
            "output_prompt": str,                # 最终 prompt 文本 (面向用户/LLM)
            "output_artifact": PromptArtifact,   # 双生容器 (面向程序, 可继续操作文法树)
            "output_prompt_path": str | None,
            "report": str | None,
            "report_path": str | None,
            "metadata": {...},
        }
    """
    t_start = datetime.now()
    metadata: dict[str, Any] = {}

    # ── Step 3: 构建/使用 PromptArtifact ──
    if artifact is not None:
        if verbose:
            print(f"[L2 entry] using provided PromptArtifact")
    else:
        if verbose:
            print(f"[L2 entry] building PromptArtifact (mode={mode})")
        artifact = PromptArtifact.from_registry(str(registry), mode=mode)

    tree = artifact.tree
    intent_count = tree.sections[1].content.total_intents
    group_count = len(tree.sections[1].content.groups)
    if verbose:
        print(f"[L2 entry] artifact: {intent_count} intents in {group_count} groups, "
              f"prompt={len(artifact.prompt)} chars")

    # ── Step 4a: enrich 产生申请 ──
    if verbose:
        print(f"[L2 entry] running enrich (model={model})")
    applications = enrich(tree, model=model, verbose=verbose)
    metadata["enrich"] = {
        "total": len(applications),
        "by_operation": {
            "group_description": sum(1 for a in applications if a.operation == "group_description"),
            "sample_add": sum(1 for a in applications if a.operation == "sample_add"),
            "sample_delete": sum(1 for a in applications if a.operation == "sample_delete"),
        },
    }

    if not applications:
        elapsed = (datetime.now() - t_start).total_seconds()
        return {
            "status": "no_applications",
            "output_prompt": artifact.prompt,
            "output_artifact": artifact,
            "output_prompt_path": str(output_prompt) if output_prompt else None,
            "report": None,
            "report_path": None,
            "metadata": {**metadata, "elapsed_seconds": elapsed},
        }

    # ── Step 4b: 确定性验证 ──
    if verbose:
        print(f"[L2 entry] running validator")
    validated, validation_failed = validate_all(applications, tree)
    metadata["validator"] = {
        "passed": len(validated),
        "failed": len(validation_failed),
        "failures": [
            {"operation": f["application"].operation, "reason": f["reason"]}
            for f in validation_failed
        ],
    }

    if verbose:
        for f in validation_failed:
            print(f"  VALIDATOR FAIL [{f['application'].operation}]: {f['reason'][:80]}")

    if not validated:
        elapsed = (datetime.now() - t_start).total_seconds()
        return {
            "status": "all_rejected_by_validator",
            "output_prompt": artifact.prompt,
            "output_artifact": artifact,
            "output_prompt_path": str(output_prompt) if output_prompt else None,
            "report": None,
            "report_path": None,
            "metadata": {**metadata, "elapsed_seconds": elapsed},
        }

    # ── Step 4c: 黄金样本贪心验证 ──
    report = None
    golden_meta = None
    baseline_details = None

    if golden_samples and Path(golden_samples).exists():
        if verbose:
            print(f"[L2 entry] running golden validation")

        with open(golden_samples, "r", encoding="utf-8") as f:
            gs = json.load(f)

        accepted, rejected, round_details, baseline_details = greedy_accept(
            tree, validated, gs,
            max_samples=max_golden_samples,
            workers=workers,
            verbose=verbose,
        )

        golden_meta = {
            "baseline_accuracy": round_details[0]["accuracy"] if round_details else 0,
            "final_accuracy": round_details[-1].get("accuracy_after", round_details[-1].get("accuracy", 0)) if round_details else 0,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rounds": round_details,
        }

        report = generate_golden_report(
            round_details, gs, accepted, rejected, baseline_details,
        )
        final_apps = accepted
    else:
        if verbose:
            print(f"[L2 entry] no golden samples, applying all validated")
        final_apps = validated

    # ── Step 4d: 应用到文法树, 然后 invalidate 让 prompt 重新序列化 ──
    if verbose:
        print(f"[L2 entry] applying {len(final_apps)} applications")
    apply_all(tree, final_apps)
    artifact.invalidate()  # ← tree 已修改, 标记 prompt 缓存失效
    final_text = artifact.prompt  # ← 重新序列化

    metadata["applier"] = {
        "applied_count": len(final_apps),
        "prompt_chars": len(final_text),
    }
    if golden_meta:
        metadata["golden_validate"] = golden_meta

    # ── 输出 ──
    output_prompt_path = None
    if output_prompt:
        out_p = Path(output_prompt)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(final_text, encoding="utf-8")
        output_prompt_path = str(out_p)
        if verbose:
            print(f"[L2 entry] prompt saved to {output_prompt_path}")

    report_path = None
    if output_report and report:
        out_r = Path(output_report)
        out_r.parent.mkdir(parents=True, exist_ok=True)
        out_r.write_text(report, encoding="utf-8")
        report_path = str(out_r)
        if verbose:
            print(f"[L2 entry] report saved to {report_path}")

    elapsed = (datetime.now() - t_start).total_seconds()
    metadata["elapsed_seconds"] = elapsed

    status = "ok"
    if golden_samples and Path(golden_samples).exists():
        if len(rejected) > 0:
            status = "partial"  # 部分被拒
    else:
        status = "no_golden"

    if verbose:
        print(f"[L2 entry] done ({elapsed:.1f}s): status={status}, "
              f"{len(final_apps)} applied, prompt={len(final_text)} chars")

    return {
        "status": status,
        "output_prompt": final_text,
        "output_artifact": artifact,      # ← 双生容器, 后续程序可继续操作 artifact.tree
        "output_prompt_path": output_prompt_path,
        "report": report,
        "report_path": report_path,
        "metadata": metadata,
    }


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="L2 Entry: 一键运行 enrich 全流程"
    )
    parser.add_argument("registry", help="L0.5 产出的 scene_table_clean.json")
    parser.add_argument("--mode", "-m", default="full",
                        choices=["full", "classify_only"])
    parser.add_argument("--golden", "-g", default=None,
                        help="黄金样本 JSON (默认: prompter/test/golden_samples.json)")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--workers", "-w", type=int, default=8)
    parser.add_argument("--max-samples", "-n", type=int, default=None)
    parser.add_argument("--api-key", "-k", default=None)
    parser.add_argument("--out", "-o", default=None,
                        help="输出最终 prompt 路径")
    parser.add_argument("--report", "-r", default=None,
                        help="输出报告路径")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # 自动查找 golden samples
    golden_path = args.golden
    if golden_path is None:
        default_golden = Path(__file__).resolve().parent.parent / "test" / "golden_samples.json"
        if default_golden.exists():
            golden_path = str(default_golden)

    result = run_l2_pipeline(
        registry=args.registry,
        mode=args.mode,
        golden_samples=golden_path,
        model=args.model,
        workers=args.workers,
        max_golden_samples=args.max_samples,
        api_key=args.api_key,
        output_prompt=args.out,
        output_report=args.report,
        verbose=args.verbose,
    )

    # 打印摘要
    m = result["metadata"]
    print(f"\n[L2 entry] status: {result['status']}")
    print(f"[L2 entry] enrich: {m['enrich']['total']} applications "
          f"(desc={m['enrich']['by_operation']['group_description']}, "
          f"add={m['enrich']['by_operation']['sample_add']}, "
          f"delete={m['enrich']['by_operation']['sample_delete']})")
    print(f"[L2 entry] validator: {m['validator']['passed']} passed, "
          f"{m['validator']['failed']} failed")
    if m.get("golden_validate"):
        gv = m["golden_validate"]
        print(f"[L2 entry] golden: {gv['accepted']} accepted, "
              f"{gv['rejected']} rejected, "
              f"acc={gv['baseline_accuracy']:.4f}->{gv['final_accuracy']:.4f}")
    print(f"[L2 entry] applier: {m['applier']['applied_count']} applied, "
          f"prompt={m['applier']['prompt_chars']} chars")
    print(f"[L2 entry] elapsed: {m['elapsed_seconds']:.1f}s")

    if result["report"]:
        print(f"\n{result['report']}")
