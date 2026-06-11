"""
L3_entry.py — L3 train-on-test 统一入口
=======================================

对黄金验证中分类错误的样本, 逐个分析并局部微调 prompt,
通过贪心验证确保准确率不降.

流程:
  1. 从 baseline details 中提取错例
  2. 对每个错例 (按 confidence 从高到低, 优先修 "最自信的错误"):
     a. L3_reviser 生成微调申请
     b. 单样本测试 (修了目标样本吗?)
     c. 全量测试 (伤了其他样本吗?)
     d. 不降 → 接受; 降 → 回退
  3. 生成微调报告

用法:
    from L3_entry import run_l3_pipeline

    result = run_l3_pipeline(
        artifact=artifact,
        baseline_details=baseline_run["details"],
        golden_samples="golden_samples.json",
        workers=4,
    )
"""

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .grammar_tree import Prompt, PromptArtifact
    from .L2_enrich_application import EnrichApplication, sort_by_confidence
    from .L3_reviser import revise
    from .L3_applier import apply as l3_apply
    from .L2_golden_validate import _run_golden_set, _inject_prompt, _run_single_golden
    from .serialize import serialize
except ImportError:
    from grammar_tree import Prompt, PromptArtifact
    from L2_enrich_application import EnrichApplication, sort_by_confidence
    from L3_reviser import revise
    from L3_applier import apply as l3_apply
    from L2_golden_validate import _run_golden_set, _inject_prompt, _run_single_golden
    from serialize import serialize


def _extract_errors(baseline_details: list[dict]) -> list[dict]:
    """从基线验证结果中提取分类错误的样本."""
    errors = []
    for d in baseline_details:
        if not d.get("correct") and not d.get("error"):
            errors.append(d)
    return errors


def _test_single_sample(tree: Prompt, sample: dict) -> bool:
    """对单个样本测试是否分类正确. 返回 True=正确."""
    prompt_text = serialize(tree)
    _inject_prompt(prompt_text)

    try:
        result = _run_single_golden(sample, 0, 1, verbose=False)
    except Exception:
        return False

    if result is None:
        return False
    return result.get("correct", False)


def run_l3_pipeline(
    artifact: PromptArtifact,
    baseline_details: list[dict],
    golden_samples: str | Path | list[dict],
    model: str = "deepseek-v4-pro",
    workers: int = 4,
    max_errors: int | None = None,
    api_key: str | None = None,
    output_report: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """L3 微调全流程.

    Args:
        artifact: 当前 PromptArtifact (会被原地修改)
        baseline_details: 基线黄金验证的 per-sample details
        golden_samples: 黄金样本 (JSON 路径或 list)
        model: LLM 模型
        workers: 全量测试并发数
        max_errors: 最多处理多少错例 (None=全部)
        api_key: API key
        output_report: 报告输出路径
        verbose: 打印进度

    Returns:
        {
            "status": "ok" | "partial",
            "output_artifact": PromptArtifact,
            "error_count": int,              # 基线错例数
            "fixed_count": int,              # 修好的错例数
            "rounds": [{sample_id, action, revisions_count, accuracy_before, accuracy_after}],
            "report": str,                   # 微调报告
        }
    """
    t_start = datetime.now()
    tree = artifact.tree

    # ── 加载黄金样本 ──
    if isinstance(golden_samples, (str, Path)):
        with open(golden_samples, "r", encoding="utf-8") as f:
            gs = json.load(f)
    else:
        gs = golden_samples

    # ── 提取错例 ──
    errors = _extract_errors(baseline_details)
    # 按错误预测的 confidence 排序 (优先修模型最自信的错判)
    errors.sort(key=lambda e: e.get("confidence", 0), reverse=True)

    if max_errors:
        errors = errors[:max_errors]

    print(f"[L3 entry] baseline errors: {len(errors)}/{len(gs)}")
    if verbose:
        for e in errors[:5]:
            print(f"  {e['id']}: expected={e.get('expected_l1','?')}/{e.get('expected_l2','?')} "
                  f"actual={e.get('actual_l1','?')}/{e.get('actual_l2','?')}")

    if not errors:
        return {
            "status": "ok",
            "output_artifact": artifact,
            "error_count": 0,
            "fixed_count": 0,
            "rounds": [],
            "report": "# L3 Revision Report\n\n基线无错例, 无需微调.",
        }

    # ── 获取当前基线准确率 ──
    baseline_prompt = serialize(tree)
    _inject_prompt(baseline_prompt)
    current_acc, correct_count, total, _ = _run_golden_set(
        baseline_prompt, gs, workers=workers, verbose=False,
    )
    print(f"[L3 entry] current accuracy: {current_acc:.4f} ({correct_count}/{total})")

    # ── 逐个处理错例 ──
    rounds = []
    fixed_count = 0
    original_errors = len(errors)

    for i, error in enumerate(errors):
        sample_id = error.get("id", f"error_{i}")
        exp_l1 = error.get("expected_l1", "?")
        exp_l2 = error.get("expected_l2", "?")

        print(
            f"\n[L3] [{i+1}/{len(errors)}] {sample_id}: "
            f"{exp_l1}/{exp_l2} <- {error.get('actual_l1','?')}/{error.get('actual_l2','?')}",
            flush=True,
        )

        # ── a. 构建错例样本供 reviser 使用 ──
        sample_for_reviser = {
            "id": sample_id,
            "expected_l1": exp_l1,
            "expected_l2": exp_l2,
            "actual_l1": error.get("actual_l1", ""),
            "actual_l2": error.get("actual_l2", ""),
        }
        # 尝试从 gs 中找到完整的 messages
        for g in gs:
            if g["id"] == sample_id:
                sample_for_reviser["messages"] = g.get("messages", [])
                sample_for_reviser["expected_l1"] = g["expected_l1"]
                sample_for_reviser["expected_l2"] = g["expected_l2"]
                break

        # ── b. 调 reviser ──
        revisions = revise(tree, sample_for_reviser, model=model, api_key=api_key, verbose=verbose)
        if not revisions:
            print(f"  -> SKIP: no revisions proposed")
            rounds.append({
                "sample_id": sample_id,
                "action": "skipped",
                "reason": "no revisions",
            })
            continue

        print(f"  -> {len(revisions)} revisions proposed")

        # ── c. 临时应用 ──
        temp_tree = deepcopy(tree)
        for rev in revisions:
            try:
                l3_apply(temp_tree, rev)
            except Exception as e:
                print(f"  -> SKIP: apply error: {e}")
                rounds.append({
                    "sample_id": sample_id,
                    "action": "skipped",
                    "reason": f"apply error: {e}",
                })
                continue

        # ── d. 单样本测试 ──
        try:
            fixed = _test_single_sample(temp_tree, sample_for_reviser)
        except Exception as e:
            print(f"  -> SKIP: test error: {e}")
            rounds.append({
                "sample_id": sample_id,
                "action": "skipped",
                "reason": f"test error: {e}",
                "revisions_count": len(revisions),
            })
            continue

        if not fixed:
            print(f"  -> SKIP: target sample not fixed")
            rounds.append({
                "sample_id": sample_id,
                "action": "skipped",
                "reason": "target not fixed",
                "revisions_count": len(revisions),
            })
            continue

        print(f"  -> target sample fixed")

        # ── e. 全量测试 ──
        temp_prompt = serialize(temp_tree)
        test_acc, test_correct, _, _ = _run_golden_set(
            temp_prompt, gs, workers=workers, verbose=False,
        )

        if test_acc >= current_acc:
            # 接受
            for rev in revisions:
                try:
                    l3_apply(tree, rev)
                except Exception:
                    pass
            artifact.invalidate()
            current_acc = test_acc
            fixed_count += 1
            print(f"  -> ACCEPT (acc: {current_acc:.4f})")
            rounds.append({
                "sample_id": sample_id,
                "action": "accepted",
                "revisions_count": len(revisions),
                "accuracy_before": current_acc,
                "accuracy_after": test_acc,
            })
        else:
            print(f"  -> REJECT (acc drop: {current_acc:.4f} -> {test_acc:.4f})")
            rounds.append({
                "sample_id": sample_id,
                "action": "rejected",
                "reason": f"accuracy drop: {current_acc:.4f} -> {test_acc:.4f}",
                "revisions_count": len(revisions),
            })

    # ── 最终统计 ──
    final_prompt = serialize(tree)
    final_acc, final_correct, _, _ = _run_golden_set(
        final_prompt, gs, workers=workers, verbose=False,
    )

    elapsed = (datetime.now() - t_start).total_seconds()

    # ── 生成报告 ──
    report = _generate_l3_report(
        original_errors=original_errors,
        fixed_count=fixed_count,
        rounds=rounds,
        artifact=artifact,
        elapsed=elapsed,
    )

    if output_report:
        out_r = Path(output_report)
        out_r.parent.mkdir(parents=True, exist_ok=True)
        out_r.write_text(report, encoding="utf-8")
        print(f"[L3 entry] report saved to {out_r}")

    # ── 输出当前 prompt ──
    artifact.invalidate()

    print(f"\n[L3 entry] done ({elapsed:.1f}s): {fixed_count}/{original_errors} errors fixed, "
          f"acc={final_acc:.4f} (baseline was {baseline_details})")

    return {
        "status": "ok" if fixed_count > 0 else "no_fixes",
        "output_artifact": artifact,
        "error_count": original_errors,
        "fixed_count": fixed_count,
        "rounds": rounds,
        "report": report,
    }


# ═══════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════

def _generate_l3_report(
    original_errors: int,
    fixed_count: int,
    rounds: list[dict],
    artifact: PromptArtifact,
    elapsed: float,
) -> str:
    lines = [
        "# L3 Micro-Revision Report",
        "",
        f"**基线错例**: {original_errors}",
        f"**修复成功**: {fixed_count}",
        f"**耗时**: {elapsed:.1f}s",
        "",
        "## 逐轮详情",
        "",
        "| # | 样本 | 操作 | 修订数 | 结果 |",
        "|---|------|------|--------|------|",
    ]

    for i, rd in enumerate(rounds, 1):
        action_label = {
            "accepted": "[ACCEPT]",
            "rejected": "[REJECT]",
            "skipped": "[SKIP]",
        }.get(rd["action"], rd["action"])

        reason = rd.get("reason", "")
        result = action_label
        if reason and action_label == "[SKIP]":
            result = f"{action_label} ({reason[:30]})"
        elif action_label == "[REJECT]":
            result = f"{action_label} ({reason[:40]})"

        lines.append(
            f"| {i} | {rd['sample_id']} | {rd['action']} "
            f"| {rd.get('revisions_count', 0)} | {result} |"
        )

    lines.append("")

    # 当前 enrich 字段
    lines.extend([
        "## 最终的 enrich 字段",
        "",
    ])
    catalog = artifact.tree._find_content(IntentCatalog)
    if catalog:
        for group in catalog.groups:
            has_enrich = False
            for intent in group.intents:
                if intent.enriched:
                    has_enrich = True
                    break
            if not has_enrich:
                continue
            lines.append(f"### {group.l1_name}")
            for intent in group.intents:
                if not intent.enriched:
                    continue
                lines.append(f"**{intent.display_id} {intent.l2}**:")
                for slot_key in ["keywords", "attention", "negative_examples"]:
                    val = intent.enriched.get(slot_key)
                    if val:
                        lines.append(f"  - {slot_key}: {', '.join(val[:5])}")
                lines.append("")

    return "\n".join(lines)
