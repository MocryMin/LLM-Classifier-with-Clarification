"""
enrich.py — enrich 主逻辑
========================

输入文法树, 输出按 confidence 排序的申请列表.
不修改文法树.

两次 LLM 调用:
  调用 1 (×N): group_description  — 每个 L1 分组生成一句说�?
  调用 2 (×1): sample_review      — add+delete 合并, 一次调用

用法:
    python enrich.py <scene_table_clean.json> [--mode full] [--model ...]

代码:
    from L2_enrich import L2_enrich
    applications = enrich(tree)
    # 返回按 confidence 降序排列的申请列表
"""

import json
import os
import sys
from pathlib import Path
from openai import OpenAI

# 兼容直接执行和包导入
try:
    from .grammar_tree import Prompt
    from .L2_enrich_application import (
        EnrichApplication,
        enrich_applications_to_json,
        sort_by_confidence,
    )
    from .L2_enrich_inputs import (
        build_description_inputs,
        build_sample_review_input,
    )
    from .L1_generator import generate as build_tree
except ImportError:
    from grammar_tree import Prompt
    from L2_enrich_application import (
        EnrichApplication,
        enrich_applications_to_json,
        sort_by_confidence,
    )
    from L2_enrich_inputs import (
        build_description_inputs,
        build_sample_review_input,
    )
    from L1_generator import generate as build_tree


# ═══════════════════════════════════════════════════════════
# LLM 配置
# ═══════════════════════════════════════════════════════════

_DEFAULT_MODEL = "deepseek-v4-pro"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_API_KEY = "sk-6172dca8aeb0461a8b84cc8bcac0f9e8"


def _get_client(api_key: str | None = None):
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or _DEFAULT_API_KEY
    return OpenAI(api_key=key, base_url=_DEFAULT_BASE_URL)


# ═══════════════════════════════════════════════════════════
# LLM 调�?
# ═══════════════════════════════════════════════════════════

def _call_llm(
    system: str,
    user: str,
    output_schema: dict,
    model: str = _DEFAULT_MODEL,
    max_tokens: int = 8000,
    api_key: str | None = None,
) -> dict | None:
    """单次 LLM 调用, 要求结构化输出.

    Args:
        system: system prompt
        user: user prompt (结构化上下文)
        output_schema: JSON schema 描�?
        model: 模型名称
        max_tokens: 最大输出 token
        api_key: API key (默认从环境变量读取)

    Returns:
        解析后的 dict, 或 None (失败时)
    """
    client = _get_client(api_key=api_key)

    # 在 user prompt 末尾追加输出格式要求
    schema_str = json.dumps(output_schema, ensure_ascii=False, indent=2)
    full_user = (
        f"{user}\n\n"
        f"请严格按照以下 JSON 格式输出 (不要输出其他文�?:\n"
        f"```json\n{schema_str}\n```"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": full_user},
            ],
            stream=False,
            max_tokens=max_tokens,
        )
        raw = response.choices[0].message.content
        if not raw:
            return None

        return _extract_json(raw)

    except Exception as e:
        print(f"[enrich] LLM call failed: {e}", file=sys.stderr)
        return None


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON 对象."""
    import re

    t = text.strip()

    # 策略1: ```json ... ```
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略2: 花括号边�?
    first = t.find("{")
    last = t.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(t[first : last + 1])
        except json.JSONDecodeError:
            pass

    # 策略3: 整段
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════════════════
# 输出 schema 定义
# ═══════════════════════════════════════════════════════════

DESCRIPTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "descriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group_l1_name": {
                        "type": "string",
                        "description": "一级意图名称",
                    },
                    "description": {
                        "type": "string",
                        "description": "一句话说明 (<=30字). 空字符串表示无法归纳",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "申请理由 (1-2句)",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "申请意愿: 0=完全不确定, 1=绝对确定",
                    },
                },
                "required": ["group_l1_name", "description", "rationale", "confidence"],
            },
        },
    },
    "required": ["descriptions"],
}

SAMPLE_REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sample_additions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "示例标题, 如 '核保vs健康险投保'",
                    },
                    "conversation": {
                        "type": "string",
                        "description": "对话内容, 格式: [用户] xxx",
                    },
                    "output_json": {
                        "type": "object",
                        "description": "完整的 JSON 输出示例",
                        "properties": {
                            "primary_intent": {
                                "type": "object",
                                "properties": {
                                    "l1": {"type": "string"},
                                    "l2": {"type": "string"},
                                    "confidence": {"type": "number"},
                                },
                            },
                            "top_candidates": {"type": "array"},
                            "needs_clarification": {"type": "boolean"},
                            "user_output": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                    "correct_answer": {
                        "type": "string",
                        "description": "为什么这个路由正确 (1-2句)",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "为什么需要这个新示例 (1-2句)",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": [
                    "title", "conversation", "output_json",
                    "correct_answer", "rationale", "confidence",
                ],
            },
        },
        "sample_deletions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_display_id": {
                        "type": "string",
                        "description": "要删除的示例编号, 如 '示例3'",
                    },
                    "contradiction_detail": {
                        "type": "string",
                        "description": "矛盾描述: 哪个字段/规则被违背",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "申请理由 (1-2句)",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": [
                    "target_display_id", "contradiction_detail",
                    "rationale", "confidence",
                ],
            },
        },
    },
    "required": ["sample_additions", "sample_deletions"],
}


# ═══════════════════════════════════════════════════════════
# Enrich 操作
# ═══════════════════════════════════════════════════════════

def enrich_description(
    tree: Prompt,
    model: str = _DEFAULT_MODEL,
    verbose: bool = False,
    api_key: str | None = None,
) -> list[EnrichApplication]:
    """为每个 L1 分组生成 description 申请.

    每个分组一次独立的 LLM 调用.
    """
    inputs = build_description_inputs(tree)
    applications = []

    for inp in inputs:
        if verbose:
            print(f"  [enrich] group_description: {inp.metadata['group_l1_name']}")

        result = _call_llm(
            system=inp.system,
            user=inp.user,
            output_schema=DESCRIPTION_OUTPUT_SCHEMA,
            model=model,
            api_key=api_key,
        )

        if result is None:
            if verbose:
                print(f"    -> LLM call failed, skipping")
            continue

        for item in result.get("descriptions", []):
            desc = item.get("description", "").strip()
            if not desc:  # 空字符串 = 无法归纳, 跳过
                if verbose:
                    print(f"    -> no meaningful description (skipped)")
                continue

            app = EnrichApplication(
                operation="group_description",
                target=inp.metadata["target"],
                content={
                    "group_l1_name": item.get("group_l1_name", inp.metadata["group_l1_name"]),
                    "description": desc,
                },
                confidence=item.get("confidence", 0.0),
                rationale=item.get("rationale", ""),
            )
            applications.append(app)

            if verbose:
                print(f"    -> confidence={app.confidence:.2f}: {desc[:60]}...")

    return applications


def enrich_samples(
    tree: Prompt,
    model: str = _DEFAULT_MODEL,
    verbose: bool = False,
    api_key: str | None = None,
) -> list[EnrichApplication]:
    """生成 sample_add + sample_delete 申请 (合并调用).

    一次 LLM 调用同时处理两种操�?.
    """
    inp = build_sample_review_input(tree)
    applications = []

    if verbose:
        print(f"  [enrich] sample_review (add+delete)")

    result = _call_llm(
        system=inp.system,
        user=inp.user,
        output_schema=SAMPLE_REVIEW_OUTPUT_SCHEMA,
        model=model,
        max_tokens=12000,
        api_key=api_key,
    )

    if result is None:
        if verbose:
            print(f"    -> LLM call failed, skipping")
        return applications

    # sample_additions
    for item in result.get("sample_additions", []):
        app = EnrichApplication(
            operation="sample_add",
            target="samples",
            content={
                "title": item.get("title", ""),
                "conversation": item.get("conversation", ""),
                "output_json": item.get("output_json", {}),
                "correct_answer": item.get("correct_answer", ""),
            },
            confidence=item.get("confidence", 0.0),
            rationale=item.get("rationale", ""),
        )
        applications.append(app)

        if verbose:
            print(
                f"    -> add: {item.get('title', '?')} "
                f"(confidence={app.confidence:.2f})"
            )

    # sample_deletions
    for item in result.get("sample_deletions", []):
        app = EnrichApplication(
            operation="sample_delete",
            target="samples",
            content={
                "target_display_id": item.get("target_display_id", ""),
                "contradiction_detail": item.get("contradiction_detail", ""),
            },
            confidence=item.get("confidence", 0.0),
            rationale=item.get("rationale", ""),
        )
        applications.append(app)

        if verbose:
            print(
                f"    -> delete: {item.get('target_display_id', '?')} "
                f"(confidence={app.confidence:.2f})"
            )

    return applications


# ═══════════════════════════════════════════════════════════
# 主入�?
# ═══════════════════════════════════════════════════════════

def enrich(
    tree: Prompt,
    model: str = _DEFAULT_MODEL,
    verbose: bool = False,
    api_key: str | None = None,
) -> list[EnrichApplication]:
    """执行全部 enrich 操作, 返回按 confidence 排序的申请列表.

    不修改文法树, 只返回申请列�?.

    Args:
        tree: 文法树根节�?
        model: LLM 模型名称
        verbose: 打印进度信息
        api_key: API key (默认从环境变量读取)

    Returns:
        按 confidence 降序排列的申请列表
    """
    print(f"[enrich] starting (model={model})")

    applications: list[EnrichApplication] = []

    # 调用 1: group_description
    print(f"[enrich] step 1/2: group_description ...")
    apps_desc = enrich_description(tree, model=model, verbose=verbose, api_key=api_key)
    applications.extend(apps_desc)
    print(f"[enrich]   -> {len(apps_desc)} applications")

    # 调用 2: sample_review
    print(f"[enrich] step 2/2: sample_review (add+delete) ...")
    apps_samples = enrich_samples(tree, model=model, verbose=verbose, api_key=api_key)
    applications.extend(apps_samples)
    print(f"[enrich]   -> {len(apps_samples)} applications "
          f"(add={sum(1 for a in apps_samples if a.operation=='sample_add')}, "
          f"delete={sum(1 for a in apps_samples if a.operation=='sample_delete')})")

    # 排序
    applications = sort_by_confidence(applications)

    print(
        f"[enrich] done: {len(applications)} total applications "
        f"(desc={sum(1 for a in applications if a.operation=='group_description')}, "
        f"add={sum(1 for a in applications if a.operation=='sample_add')}, "
        f"delete={sum(1 for a in applications if a.operation=='sample_delete')})"
    )

    return applications


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="enrich: 从文法树生成 enrich 申请列表"
    )
    parser.add_argument(
        "registry",
        help="L0.5 产出的 scene_table_clean.json",
    )
    parser.add_argument(
        "--mode", "-m",
        default="full",
        choices=["full", "classify_only"],
        help="生成模式 (默认: full)",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"LLM 模型名称 (默认: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--out", "-o",
        default=None,
        help="输出申请列表 JSON 路径",
    )
    parser.add_argument(
        "--api-key", "-k",
        default=None,
        help="API key (默认从 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量读取)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="打印详细进度",
    )
    args = parser.parse_args()

    # 构建文法树
    print(f"[enrich] building grammar tree (mode={args.mode})...")
    tree = build_tree(args.registry, mode=args.mode)

    # 执行 enrich
    applications = enrich(
        tree,
        model=args.model,
        verbose=args.verbose,
        api_key=args.api_key,
    )

    # 输出
    output_json = enrich_applications_to_json(applications)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        print(f"[enrich] applications -> {out_path}")
    else:
        print(output_json)
