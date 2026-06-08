"""
5-batch full-flow test runner.

Usage:
  python test/throughout/test.py batch1
  python test/throughout/test.py batch2
  python test/throughout/test.py batch3
  python test/throughout/test.py batch4
  python test/throughout/test.py batch5
  python test/throughout/test.py all
  python test/throughout/test.py all --workers 16

Reports are written to:
  test/throughout/5batch_samples/report/
  (including json_parse_report_*.xlsx for each batch)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SAMPLES_FILE = ROOT / "test" / "throughout" / "5batch_samples" / "5batch_samples.xlsx"
REPORT_DIR = ROOT / "test" / "throughout" / "5batch_samples" / "report"

sys.path.insert(0, str(SRC))
from entrance import entrance  # noqa: E402
from L1_purpose import get_and_clear_parse_events  # noqa: E402


def _l1_parse_status() -> str:
    """Return aggregated L1 JSON parse status for the most recent entrance() call.
    Called AFTER entrance() returns; reads and clears the parse event log.
    Returns: 'ok' | 'retry_recovered' | 'full_failure' | 'no_parse'"""
    events = get_and_clear_parse_events()
    if not events:
        return 'ok'  # no events recorded = all parses succeeded first try
    # The last event tells us the final outcome
    last = events[-1]
    return last.get('status', 'unknown')


def parse_json_cell(value: str) -> Any:
    if value == "-":
        return "-"
    return json.loads(value)


def load_samples() -> list[dict[str, Any]]:
    wb = load_workbook(SAMPLES_FILE, read_only=True, data_only=True)
    ws = wb["samples"]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        messages, correct_label, batch = row
        rows.append({
            "messages": json.loads(messages),
            "correct_label": parse_json_cell(correct_label),
            "batch": str(batch),
        })
    return rows


def batch_filter(samples: list[dict[str, Any]], batch: str) -> list[dict[str, Any]]:
    if batch == "batch1":
        return [s for s in samples if s["batch"].startswith("1.")]
    if batch == "batch2":
        return [s for s in samples if s["batch"].startswith("2.")]
    if batch == "batch3":
        return [s for s in samples if s["batch"] == "3"]
    if batch == "batch4":
        return [s for s in samples if s["batch"] == "4"]
    if batch == "batch5":
        return [s for s in samples if s["batch"].startswith("5.")]
    raise ValueError(f"unknown batch: {batch}")


def run_one(messages: list[dict[str, str]], debug: bool, l0_threshold: float) -> dict[str, Any]:
    return entrance(messages, l0_threshold=l0_threshold, debug=debug)


def output_risk(result: dict[str, Any]) -> str | None:
    return result.get("risk_level")


def output_intent(result: dict[str, Any]) -> dict[str, str | None]:
    pi = result.get("data", {}).get("primary_intent", {}) or {}
    return {"l1": pi.get("l1"), "l2": pi.get("l2")}


def messages_text(messages: list[dict[str, str]]) -> str:
    return json.dumps(messages, ensure_ascii=False)


def result_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def report_path(name: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPORT_DIR / f"{name}_{ts}.xlsx"


def _run_concurrent(
    samples: list[dict[str, Any]],
    debug: bool,
    l0_threshold: float,
    max_workers: int,
    batch_name: str,
) -> tuple[list[tuple[int, dict, dict]], list[dict]]:
    """Run all samples concurrently.
    Returns: (ordered_results, parse_log).
    ordered_results: list of (index, sample, result) sorted by original index.
    parse_log: list of {batch, idx, messages, status, attempts} for each sample."""
    total = len(samples)
    lock = threading.Lock()
    done_count = [0]
    parse_log: list[dict] = []

    def _run_with_progress(s: dict[str, Any], idx: int) -> dict[str, Any]:
        r = run_one(s["messages"], debug=debug, l0_threshold=l0_threshold)
        status = _l1_parse_status()
        with lock:
            done_count[0] += 1
            parse_log.append({
                "batch": s["batch"],
                "idx": idx,
                "messages": s["messages"],
                "status": status,
            })
        return r

    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_with_progress, s, idx): idx
            for idx, s in enumerate(samples)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"  [{batch_name}] sample {idx + 1} FAILED: {e}", file=sys.stderr)
                results[idx] = {"error": str(e)}
                with lock:
                    parse_log.append({
                        "batch": samples[idx]["batch"],
                        "idx": idx,
                        "messages": samples[idx]["messages"],
                        "status": "error",
                    })

        print(f"  {batch_name} {done_count[0]}/{total} completed")

    ordered = [(idx, samples[idx], results[idx]) for idx in sorted(results.keys())]
    return ordered, parse_log


def write_parse_report(
    name: str, parse_log: list[dict],
) -> Path:
    """Write a per-batch JSON parse status report."""
    wb = Workbook()
    ws = wb.active
    ws.title = f"{name}_parse"
    ws.append(["batch", "sample_idx", "messages", "parse_status"])
    for entry in sorted(parse_log, key=lambda e: (e["batch"], e["idx"])):
        ws.append([
            entry["batch"],
            entry["idx"] + 1,  # 1-based for readability
            json.dumps(entry["messages"], ensure_ascii=False),
            entry["status"],
        ])
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 90
    ws.column_dimensions["D"].width = 18
    path = report_path(f"{name}_parse_report")
    wb.save(path)
    return path


def write_batch1_report(
    samples: list[dict[str, Any]], debug: bool, l0_threshold: float, max_workers: int = 8,
) -> list[Path]:
    print(f"  batch1 0/{len(samples)} (launching {max_workers} workers)")
    ordered, parse_log = _run_concurrent(samples, debug, l0_threshold, max_workers, "batch1")

    wb = Workbook()
    ws = wb.active
    ws.title = "batch1"
    ws.append(["测试messages", "该样本运行时输出的全部控制信息json"])
    for _, s, result in ordered:
        ws.append([messages_text(s["messages"]), result_text(result)])
    ws.column_dimensions["A"].width = 90
    ws.column_dimensions["B"].width = 120
    path = report_path("batch1_report")
    wb.save(path)
    ppath = write_parse_report("batch1", parse_log)
    return [path, ppath]


def write_risk_report(
    name: str, samples: list[dict[str, Any]], debug: bool, l0_threshold: float, max_workers: int = 8,
) -> list[Path]:
    print(f"  {name} 0/{len(samples)} (launching {max_workers} workers)")
    ordered, parse_log = _run_concurrent(samples, debug, l0_threshold, max_workers, name)

    rows = []
    correct = 0
    for _, s, result in ordered:
        expected = s["correct_label"].get("risk_level")
        actual = output_risk(result)
        if actual == expected:
            correct += 1
        rows.append([messages_text(s["messages"]), json.dumps(s["correct_label"], ensure_ascii=False), actual])

    total = len(samples)
    acc = correct / total if total else 0.0

    wb = Workbook()
    ws = wb.active
    ws.title = name
    ws.append([f"total={total}", f"correct={correct}", f"acc={acc:.4f}"])
    ws.append(["messages", "正确标签", "输出标签（风险等级）"])
    for row in rows:
        ws.append(row)
    ws.column_dimensions["A"].width = 90
    ws.column_dimensions["B"].width = 35
    ws.column_dimensions["C"].width = 20
    path = report_path(f"{name}_report")
    wb.save(path)
    ppath = write_parse_report(name, parse_log)
    return [path, ppath]


def write_routing_report(
    name: str, samples: list[dict[str, Any]], debug: bool, l0_threshold: float, max_workers: int = 8,
) -> list[Path]:
    print(f"  {name} 0/{len(samples)} (launching {max_workers} workers)")
    ordered, parse_log = _run_concurrent(samples, debug, l0_threshold, max_workers, name)

    rows = []
    exact = 0
    l1_correct = 0
    l2_correct = 0
    for _, s, result in ordered:
        expected = s["correct_label"]
        actual = output_intent(result)
        if actual.get("l1") == expected.get("l1"):
            l1_correct += 1
        if actual.get("l2") == expected.get("l2"):
            l2_correct += 1
        if actual.get("l1") == expected.get("l1") and actual.get("l2") == expected.get("l2"):
            exact += 1
        rows.append([
            messages_text(s["messages"]),
            json.dumps(expected, ensure_ascii=False),
            json.dumps(actual, ensure_ascii=False),
        ])

    total = len(samples)
    acc = exact / total if total else 0.0
    l1_acc = l1_correct / total if total else 0.0
    l2_acc = l2_correct / total if total else 0.0

    wb = Workbook()
    ws = wb.active
    ws.title = name
    ws.append([f"total={total}", f"acc={acc:.4f}", f"L1acc={l1_acc:.4f}", f"L2acc={l2_acc:.4f}"])
    ws.append(["messages", "正确标签", "输出标签（两级意图）"])
    for row in rows:
        ws.append(row)
    ws.column_dimensions["A"].width = 90
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 40
    path = report_path(f"{name}_report")
    wb.save(path)
    ppath = write_parse_report(name, parse_log)
    return [path, ppath]


def run_batch(batch: str, debug: bool, l0_threshold: float, max_workers: int) -> list[Path]:
    samples = load_samples()
    selected = batch_filter(samples, batch)
    if batch == "batch1":
        return write_batch1_report(selected, debug=debug, l0_threshold=l0_threshold, max_workers=max_workers)
    if batch == "batch2":
        return write_risk_report("batch2", selected, debug=debug, l0_threshold=l0_threshold, max_workers=max_workers)
    if batch == "batch3":
        return write_routing_report("batch3", selected, debug=debug, l0_threshold=l0_threshold, max_workers=max_workers)
    if batch == "batch4":
        return write_routing_report("batch4", selected, debug=debug, l0_threshold=l0_threshold, max_workers=max_workers)
    if batch == "batch5":
        return write_risk_report("batch5", selected, debug=debug, l0_threshold=l0_threshold, max_workers=max_workers)
    raise ValueError(batch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=["batch1", "batch2", "batch3", "batch4", "batch5", "all"])
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--l0-threshold", type=float, default=0.7)
    parser.add_argument("--workers", type=int, default=8,
                        help="并发 worker 数 (default 8). DeepSeek flash 并发限制 2500, pro 500.")
    args = parser.parse_args(argv)

    batches = ["batch1", "batch2", "batch3", "batch4", "batch5"] if args.batch == "all" else [args.batch]
    paths: list[Path] = []
    for b in batches:
        print(f"Running {b}...")
        paths.extend(run_batch(b, debug=args.debug, l0_threshold=args.l0_threshold, max_workers=args.workers))
    for p in paths:
        print(f"Wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
