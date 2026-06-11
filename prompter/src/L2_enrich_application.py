"""
enrich_application.py — enrich 申请数据模型
==========================================

LLM 不直接修改 prompt. 每次 enrich 调用产生零个或多个申请.
后续处理程序决定是否应用.

用法:
    from L2_enrich_application import EnrichApplication, enrich_applications_to_json
    apps = [EnrichApplication(...), ...]
    print(enrich_applications_to_json(apps))
"""

from dataclasses import dataclass, field, asdict
from typing import Any
import json


@dataclass
class EnrichApplication:
    """一个 enrich 申请.

    operation 决定 content 的 schema:

    group_description:
        content = {
            "group_l1_name": str,
            "description": str,       # 生成的一句话说�?
        }

    sample_add:
        content = {
            "title": str,
            "conversation": str,      # [用户] xxx
            "output_json": dict,      # 完整的 JSON 输出示例
            "correct_answer": str,    # 为什么路由正确
        }

    sample_delete:
        content = {
            "target_display_id": str,       # e.g. 示例3
            "contradiction_detail": str,    # contradiction description
        }
    """
    operation: str           # "group_description" | "sample_add" | "sample_delete"
    target: str              # 目标节点路径, 如 "intent_catalog.groups[2]"
    content: dict            # 结构化内容 (operation 相关)
    confidence: float        # 0-1 申请意愿
    rationale: str           # 申请理由 (1-2�?

    def __post_init__(self):
        if self.operation not in (
            "group_description", "sample_add", "sample_delete",        # L2
            "modify_keywords", "add_negative_examples", "add_attention",  # L3
        ):
            raise ValueError(f"Unknown operation: {self.operation!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


def enrich_applications_to_json(apps: list[EnrichApplication]) -> str:
    """序列化申请列表为 JSON 字符串."""
    return json.dumps(
        [asdict(app) for app in apps],
        ensure_ascii=False,
        indent=2,
    )


def enrich_applications_to_list(apps: list[EnrichApplication]) -> list[dict]:
    """序列化申请列表为 Python list[dict]."""
    return [asdict(app) for app in apps]


def sort_by_confidence(apps: list[EnrichApplication]) -> list[EnrichApplication]:
    """按 confidence 降序排列, 同分数时 group_description 优先."""
    op_order = {"group_description": 3, "sample_add": 2, "sample_delete": 1}
    return sorted(apps, key=lambda a: (a.confidence, op_order.get(a.operation, 0)), reverse=True)


def filter_by_threshold(
    apps: list[EnrichApplication],
    thresholds: dict[str, float] | None = None,
) -> tuple[list[EnrichApplication], list[EnrichApplication]]:
    """按阈值�?�选申请.

    Args:
        apps: 申请列表
        thresholds: {operation: min_confidence}, 默认使用建议�?�?

    Returns:
        (通过, 待review)
    """
    if thresholds is None:
        thresholds = {
            "group_description": 0.6,
            "sample_add": 0.9,
            "sample_delete": 0.95,
        }

    accepted = []
    pending = []
    for app in apps:
        threshold = thresholds.get(app.operation, 0.5)
        if app.confidence >= threshold:
            accepted.append(app)
        else:
            pending.append(app)
    return accepted, pending
