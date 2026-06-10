"""
golden_validate.py — 黄金样本贪心验证
====================================

对每条通过 validator 的申请, 按 confidence 降序依次接受.
接受后跑黄金样本, 准确率不降 → 保留; 降了 → 回退.

用法:
    from L2_golden_validate import greedy_accept
    accepted, rejected = greedy_accept(tree, applications, gold_samples)

CLI:
    python golden_validate.py <tree_or_json> <applications.json> <golden_samples.json>
"""

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中 (用于 import v3)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from .grammar_tree import Prompt
    from .L2_enrich_application import EnrichApplication
    from .serialize import serialize
    from .L2_applier import apply as apply_one
except ImportError:
    from grammar_tree import Prompt
    from L2_enrich_application import EnrichApplication
    from serialize import serialize
    from L2_applier import apply as apply_one

# ═══════════════════════════════════════════════════════════
# V3 router 调用
# ═══════════════════════════════════════════════════════════

def _inject_prompt(prompt_text: str):
    """将自定义 prompt 注入 v3.L1_router. 线程安全: 在启动线程前调用一次."""
    import v3.L1_router as router
    router._prompt_template = prompt_text


def _run_single_golden(sample: dict, idx: int, total: int, verbose: bool) -> dict | None:
    """对单个黄金样本调 V3 router, 返回 actual L1+L2."""
    import v3.L1_router as router

    try:
        result = router.route(sample["messages"], debug=False)
        pi = result.get("primary_intent", {})

        is_correct = (
            pi.get("l1", "") == sample["expected_l1"]
            and pi.get("l2", "") == sample["expected_l2"]
        )

        return {
            "id": sample["id"],
            "expected_l1": sample["expected_l1"],
            "expected_l2": sample["expected_l2"],
            "actual_l1": pi.get("l1", ""),
            "actual_l2": pi.get("l2", ""),
            "correct": is_correct,
        }
    except Exception as e:
        return {
            "id": sample["id"],
            "expected_l1": sample["expected_l1"],
            "expected_l2": sample["expected_l2"],
            "actual_l1": "",
            "actual_l2": "",
            "correct": False,
            "error": str(e),
        }


def _run_golden_set(
    prompt_text: str,
    gold_samples: list[dict],
    max_samples: int | None = None,
    workers: int = 8,
    verbose: bool = False,
) -> tuple[float, int, int, list[dict]]:
    """用指定 prompt 并发跑黄金样本集.

    Args:
        prompt_text: 注入的 prompt
        gold_samples: 黄金样本列表
        max_samples: 限制样本数 (None=全部)
        workers: 并发数
        verbose: 打印进度

    Returns:
        (accuracy, correct, total, details)
    """
    _inject_prompt(prompt_text)  # 线程启动前注入, 所有线程读同一值

    samples_to_run = gold_samples[:max_samples] if max_samples else gold_samples
    total = len(samples_to_run)

    details_dict: dict[str, dict] = {}
    lock = threading.Lock()
    done_count = [0]

    def _run_with_progress(sample, idx):
        result = _run_single_golden(sample, idx, total, verbose=False)
        with lock:
            done_count[0] += 1
            if verbose and done_count[0] % 20 == 0:
                print(f"  [{done_count[0]}/{total}]", end=" ", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_with_progress, s, i): s["id"]
            for i, s in enumerate(samples_to_run)
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                result = future.result()
                if result:
                    details_dict[sid] = result
            except Exception as e:
                details_dict[sid] = {
                    "id": sid, "correct": False, "error": str(e),
                }

    if verbose:
        print(f"  [{total}/{total}] done")

    # 按原始顺序排列
    details = []
    correct = 0
    for s in samples_to_run:
        d = details_dict.get(s["id"], {"id": s["id"], "correct": False, "error": "missing"})
        details.append(d)
        if d.get("correct"):
            correct += 1

    accuracy = correct / total if total > 0 else 0.0
    return accuracy, correct, total, details


# ═══════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════

def generate_golden_report(
    round_details: list[dict],
    gold_samples: list[dict],
    accepted: list[EnrichApplication],
    rejected: list[EnrichApplication],
    baseline_details: list[dict] | None = None,
) -> str:
    """生成黄金验证报告 (markdown 格式).

    包含:
      - 总览
      - 逐轮详情
      - 各意图准确率明细
      - 被拒申请列表
    """
    lines = [
        "# L2 Golden Validation Report",
        "",
        f"**样本数**: {len(gold_samples)}",
        f"**覆盖**: {len(set((s['expected_l1'], s['expected_l2']) for s in gold_samples))} 个L1+L2场景",
        "",
    ]

    # ── 总览 ──
    if round_details:
        baseline = round_details[0]
        # 最终准确率: 找最后一个 accepted 轮次, 或基线
        final_acc = baseline['accuracy']
        final_correct = baseline['correct']
        for rd in reversed(round_details):
            if rd.get("action") == "accepted":
                final_acc = rd.get("accuracy_after", rd.get("accuracy", final_acc))
                final_correct = rd.get("correct_after", rd.get("correct", final_correct))
                break
        lines.extend([
            "## 总览",
            "",
            f"| 指标 | 基线 | 最终 | 变化 |",
            f"|------|------|------|------|",
            f"| 准确率 | {baseline['accuracy']:.4f} | {final_acc:.4f} "
            f"| {final_acc - baseline['accuracy']:+.4f} |",
            f"| 正确数 | {baseline['correct']} | {final_correct} | |",
            f"| 接受申请 | — | {len(accepted)} | — |",
            f"| 拒绝申请 | — | {len(rejected)} | — |",
            "",
        ])

    # ── 逐轮详情 ──
    lines.extend([
        "## 逐轮详情",
        "",
        "| 轮次 | 操作 | confidence | 准确率 | 变化 | 结果 |",
        "|------|------|-----------|--------|------|------|",
    ])
    for rd in round_details:
        if rd["round"] == 0:
            lines.append(
                f"| 0 | baseline | — | {rd['accuracy']:.4f} | — | — |"
            )
        else:
            acc_before = rd.get("accuracy_before", 0)
            if rd["action"] == "accepted":
                acc_after = rd.get("accuracy_after", acc_before)
            else:
                acc_after = acc_before  # 被拒, 准确率回退到申请前
            delta = acc_after - acc_before
            action = "[ACCEPT]" if rd["action"] == "accepted" else "[REJECT]"
            lines.append(
                f"| {rd['round']} | {rd['type']} | {rd['confidence']:.2f} "
                f"| {acc_before:.4f}→{acc_after:.4f} "
                f"| {delta:+.4f} | {action} |"
            )
    lines.append("")

    # ── 各意图准确率 (基于基线) ──
    if baseline_details:
        intent_stats: dict[tuple[str, str], dict] = {}
        for d in baseline_details:
            key = (d.get("expected_l1", "?"), d.get("expected_l2", "?"))
            if key not in intent_stats:
                intent_stats[key] = {"total": 0, "correct": 0}
            intent_stats[key]["total"] += 1
            if d.get("correct"):
                intent_stats[key]["correct"] += 1

        lines.extend([
            "## 各意图准确率 (基线)",
            "",
            "| L1 | L2 | 样本数 | 正确 | 准确率 |",
            "|----|----|--------|------|--------|",
        ])
        for (l1, l2), stats in sorted(intent_stats.items()):
            acc = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
            lines.append(
                f"| {l1} | {l2} | {stats['total']} | {stats['correct']} "
                f"| {acc:.2%} |"
            )
        lines.append("")

    # ── 被拒申请 ──
    if rejected:
        lines.extend([
            "## 被拒申请",
            "",
        ])
        for i, app in enumerate(rejected, 1):
            reason = ""
            for rd in round_details:
                if rd.get("round", 0) > 0 and rd["action"] == "rejected":
                    if rd.get("rationale", "").startswith(app.rationale[:20]):
                        reason = rd.get("reason", "")
            lines.extend([
                f"### {i}. [{app.operation}] confidence={app.confidence:.2f}",
                f"**理由**: {app.rationale}",
                f"**拒绝原因**: {reason}",
                "",
            ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 贪心接受
# ═══════════════════════════════════════════════════════════

def greedy_accept(
    tree: Prompt,
    applications: list[EnrichApplication],
    gold_samples: list[dict],
    max_samples: int | None = None,
    workers: int = 8,
    verbose: bool = False,
) -> tuple[list[EnrichApplication], list[EnrichApplication], list[dict]]:
    """贪心接受申请.

    对每条申请 (按 confidence 降序):
      1. 临时应用到树的副本
      2. 序列化 → 注入 prompt
      3. 跑黄金样本
      4. 准确率不降 → 正式接受; 降了 → 回退

    Args:
        tree: 当前文法树 (会被原地修改, 保留最终接受的申请)
        applications: 待验证的申请列表 (已排序)
        gold_samples: 黄金样本列表
        max_samples: 限制黄金样本数 (None=全部, 用于快速测试)
        verbose: 打印详细进度

    Returns:
        (accepted, rejected, round_details)
    """
    # 基线
    base_prompt = serialize(tree)
    print(f"[golden] baseline: running {max_samples or len(gold_samples)} gold samples (workers={workers})...")
    baseline_acc, baseline_correct, total, baseline_details = _run_golden_set(
        base_prompt, gold_samples, max_samples=max_samples, workers=workers, verbose=verbose,
    )
    print(f"[golden] baseline accuracy: {baseline_acc:.4f} ({baseline_correct}/{total})")

    accepted = []
    rejected = []
    round_details = [{
        "round": 0,
        "type": "baseline",
        "accuracy": baseline_acc,
        "correct": baseline_correct,
        "total": total,
    }]
    current_acc = baseline_acc

    for i, app in enumerate(applications):
        op_label = {
            "group_description": "desc",
            "sample_add": "add",
            "sample_delete": "delete",
        }.get(app.operation, app.operation)

        print(
            f"[golden] [{i+1}/{len(applications)}] {op_label} "
            f"(confidence={app.confidence:.2f}): "
            f"{app.rationale[:60]}",
            end=" ",
            flush=True,
        )

        # 临时应用
        temp_tree = deepcopy(tree)
        try:
            apply_one(temp_tree, app)
        except Exception as e:
            print(f"-> SKIP (apply error: {e})")
            rejected.append(app)
            round_details.append({
                "round": i + 1,
                "type": app.operation,
                "confidence": app.confidence,
                "rationale": app.rationale,
                "action": "rejected",
                "reason": f"apply error: {e}",
            })
            continue

        # 序列化 → 跑测试
        temp_prompt = serialize(temp_tree)
        test_acc, test_correct, _, _ = _run_golden_set(
            temp_prompt, gold_samples, max_samples=max_samples, workers=workers, verbose=False,
        )

        acc_before = current_acc

        # 判断
        if test_acc >= current_acc:
            # 接受
            apply_one(tree, app)  # 永久应用到原树
            accepted.append(app)
            current_acc = test_acc
            print(f"ACCEPT (acc: {acc_before:.4f} -> {test_acc:.4f})")
            round_details.append({
                "round": i + 1,
                "type": app.operation,
                "confidence": app.confidence,
                "rationale": app.rationale,
                "action": "accepted",
                "accuracy_before": acc_before,
                "accuracy_after": test_acc,
            })
        else:
            # 回退
            rejected.append(app)
            print(f"REJECT (acc drop: {acc_before:.4f} -> {test_acc:.4f})")
            round_details.append({
                "round": i + 1,
                "type": app.operation,
                "confidence": app.confidence,
                "rationale": app.rationale,
                "action": "rejected",
                "accuracy_before": acc_before,
                "accuracy_after": test_acc,
                "reason": f"accuracy drop: {acc_before:.4f} -> {test_acc:.4f}",
            })

    print(
        f"[golden] final: {len(accepted)} accepted, {len(rejected)} rejected, "
        f"accuracy: {baseline_acc:.4f} -> {current_acc:.4f}"
    )

    return accepted, rejected, round_details, baseline_details


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="golden_validate: 贪心验证 enrich 申请"
    )
    parser.add_argument(
        "registry", help="L0.5 产出的 scene_table_clean.json"
    )
    parser.add_argument(
        "--applications", "-a", required=True,
        help="enrich 申请的 JSON 文件",
    )
    parser.add_argument(
        "--golden", "-g", required=True,
        help="黄金样本 JSON 文件",
    )
    parser.add_argument(
        "--max-samples", "-n", type=int, default=None,
        help="限制黄金样本数 (快速模式)",
    )
    parser.add_argument(
        "--mode", "-m", default="full",
        choices=["full", "classify_only"],
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=8,
        help="并发 worker 数 (default 8)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )
    parser.add_argument(
        "--out", "-o", default=None,
        help="输出最终 prompt 路径",
    )
    args = parser.parse_args()

    # 加载
    from L1_generator import generate as build_tree

    with open(args.applications, "r", encoding="utf-8") as f:
        apps_raw = json.load(f)
    with open(args.golden, "r", encoding="utf-8") as f:
        gold_samples = json.load(f)

    # 反序列化申请
    applications = []
    for a in apps_raw:
        applications.append(EnrichApplication(
            operation=a["operation"],
            target=a["target"],
            content=a["content"],
            confidence=a["confidence"],
            rationale=a["rationale"],
        ))

    # 建树
    tree = build_tree(args.registry, mode=args.mode)

    # Step 1: validator (确定性)
    from L2_validator import validate_all
    validated, validation_failed = validate_all(applications, tree)
    print(f"[golden] validator: {len(validated)} passed, {len(validation_failed)} failed")
    for f_entry in validation_failed:
        a = f_entry["application"]
        print(f"  FAIL [{a.operation}] {f_entry['reason'][:80]}")

    if not validated:
        print("[golden] no applications passed validator, exiting")
        sys.exit(0)

    # Step 2: golden validate (贪心)
    accepted, rejected, details = greedy_accept(
        tree, validated, gold_samples,
        max_samples=args.max_samples,
        workers=args.workers,
        verbose=args.verbose,
    )

    # 输出最终 prompt
    if args.out:
        final_prompt = serialize(tree)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final_prompt, encoding="utf-8")
        print(f"[golden] final prompt -> {out_path}")

    # 打印结果
    print(f"\nAccepted ({len(accepted)}):")
    for a in accepted:
        print(f"  [{a.operation}] {a.rationale[:80]} (confidence={a.confidence:.2f})")
    print(f"\nRejected ({len(rejected)}):")
    for a in rejected:
        print(f"  [{a.operation}] {a.rationale[:80]} (confidence={a.confidence:.2f})")
