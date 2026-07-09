"""
kernel.py - V4 两阶段渐进式注入内核
=====================================
Layer_1 (粗筛): Flash + 32 类"名称+定义"摘要 -> top-k 候选
Layer_2 (精排): Flash + k 候选的【完整描述】+ V3 的路由规则/约束/示例/输出格式
               -> 从候选中选出唯一最佳, 输出与 V3 同格式的 JSON

判定要点(两层共用): 标签由对话最后所处的意图状态决定, 不是由对话开头决定。
"""

import re
import json
from .llm import DEFAULT_FLASH
from .prompt_parser import LABEL_RE

# ═══════════════════════════════════════════════════════════
# JSON 解析(三策略级联, 复用 V3 L1_router 风格)
# ═══════════════════════════════════════════════════════════


def _sanitize_json_control_chars(text: str) -> str:
    result = []
    in_string = False
    escape_next = False
    for c in text:
        if escape_next:
            result.append(c)
            escape_next = False
            continue
        if c == "\\":
            result.append(c)
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            elif ord(c) < 32:
                result.append(f"\\u{ord(c):04x}")
            else:
                result.append(c)
        else:
            result.append(c)
    return "".join(result)


def extract_json(text: str) -> dict | None:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", t, re.DOTALL)
    if m:
        try:
            return json.loads(_sanitize_json_control_chars(m.group(1).strip()))
        except json.JSONDecodeError:
            pass
    first, last = t.find("{"), t.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(_sanitize_json_control_chars(t[first: last + 1]))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(_sanitize_json_control_chars(t))
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════════════════
# Prompt 构建
# ═══════════════════════════════════════════════════════════

L1_SYSTEM = """你是保险客服意图分类器(粗筛层)。
给定意图类别清单(名称+定义)和一段坐席与客户的对话, 从全部意图中选出最可能的 top-k 候选, 按可能性从高到低排序。

判定要点:
- 标签由对话最后所处的意图状态决定, 不是由对话开头决定。
- 例如对话以"你好"开头, 但后续展开产品咨询直到结束 -> 应分类为产品咨询, 而非欢迎引导。

只输出 JSON, 不要输出任何解释。"""


def _build_l1_prompt(parsed: dict, conversation: str, k: int) -> str:
    summary = "\n".join(
        f"{c['label']}{c['name']} - 定义：{c['definition']}" for c in parsed["categories"]
    )
    return (
        f"=== 意图类别清单（名称+定义）===\n{summary}\n\n"
        f"=== 对话 ===\n{conversation}\n\n"
        f"=== 输出要求 ===\n"
        f"选出最可能的 top-{k} 个意图, 按概率从高到低排序。\n"
        f"只输出如下 JSON(不要 markdown 代码块、不要解释):\n"
        f'{{"top_candidates": [{{"label": "【意图X.X】", "probability": 0.85}}, ...]}}'
    )


def _build_l2_prompt(parsed: dict, candidate_labels: list[str], conversation: str) -> str:
    """Layer_2: V3 的 role + k 候选完整描述 + V3 的规则/约束/示例/输出格式 + 对话。

    即把 V3 prompt 中的"完整 32 类意图库"替换为"k 个候选的完整描述",
    其余(路由规则/约束/samples/输出格式)原样保留, 保持与 V3 同构。
    """
    cats = parsed["label_to_cat"]
    blocks = "\n\n".join(cats[l]["full_desc"] for l in candidate_labels)
    return (
        f"{parsed['role_text']}\n\n"
        f"##意图库##\n{blocks}\n\n"
        f"{parsed['aux_text']}\n\n"
        f"##对话内容##\n{conversation}"
    )


# ═══════════════════════════════════════════════════════════
# 输出解析
# ═══════════════════════════════════════════════════════════


def _parse_topk(raw: str, legal: set[str], name_to_label: dict[str, str]) -> list[str]:
    """从 Layer_1 输出解析 top-k labels(保序、去重、过滤非法)。"""
    data = extract_json(raw)
    if not data:
        return []
    candidates = data.get("top_candidates") or data.get("candidates") or []
    labels, seen = [], set()
    for c in candidates:
        val = c if isinstance(c, str) else (c.get("label") or c.get("name") or "")
        lbl = None
        m = LABEL_RE.search(val)
        if m and m.group(1) in legal:
            lbl = m.group(1)
        elif val in name_to_label:
            lbl = name_to_label[val]
        if lbl and lbl not in seen:
            seen.add(lbl)
            labels.append(lbl)
    return labels


def _chosen_label(data: dict, name_to_label: dict[str, str], legal: set[str]) -> str | None:
    """从 Layer_2 的 V3 格式输出中提取被选中的 label。"""
    pi = data.get("primary_intent", {}) or {}
    for field in ("l2", "label", "name"):
        val = pi.get(field, "") or ""
        m = LABEL_RE.search(val)
        if m and m.group(1) in legal:
            return m.group(1)
        if val in name_to_label:
            return name_to_label[val]
    # 退到 top_candidates[0]
    for c in data.get("top_candidates", []) or []:
        val = c.get("l2", "") or c.get("name", "") or c.get("label", "") or ""
        m = LABEL_RE.search(val)
        if m and m.group(1) in legal:
            return m.group(1)
        if val in name_to_label:
            return name_to_label[val]
    return None


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════


def _fallback(parsed: dict, label: str | None, reason: str) -> dict:
    """兜底: 用给定 label(常为 L1 top-1)构造 V3 格式结果。"""
    if label and label in parsed["label_to_cat"]:
        c = parsed["label_to_cat"][label]
        pi = {"l1": c["l1"], "l2": c["name"], "confidence": 0.0}
    else:
        pi = {"l1": "", "l2": "", "confidence": 0.0}
    return {
        "primary_intent": pi,
        "top_candidates": [],
        "needs_clarification": True,
        "user_output": "小保没有完全理解您的需求，请换个方式描述一下您想咨询或办理的业务，好吗？",
        "reason": reason,
    }


def classify(
    parsed: dict,
    conversation: str,
    client,
    model: str = DEFAULT_FLASH,
    k: int = 5,
    thinking: str = "disabled",
    debug: bool = False,
) -> dict:
    """两阶段分类, 返回 V3 格式的 data dict。"""
    legal = set(parsed["label_to_cat"])
    name_to_label = parsed["name_to_label"]

    # ── Layer_1: 粗筛 top-k ──
    l1_prompt = _build_l1_prompt(parsed, conversation, k)
    l1_raw = client.call(
        [{"role": "system", "content": L1_SYSTEM}, {"role": "user", "content": l1_prompt}],
        model=model,
        thinking=thinking,
        max_tokens=2048,
    )
    topk = _parse_topk(l1_raw, legal, name_to_label)[:k]
    if debug:
        print(f"[V4 L1] top-{k}: {topk}")
    if not topk:
        return _fallback(parsed, None, "Layer_1 returned no candidates")

    # ── Layer_2: 精排 + V3 路由决策 ──
    l2_prompt = _build_l2_prompt(parsed, topk, conversation)
    l2_raw = client.call(
        [{"role": "user", "content": l2_prompt}],
        model=model,
        thinking=thinking,
        max_tokens=4096,
    )
    if debug:
        print(f"[V4 L2 RAW]: {l2_raw[:400]}")

    data = extract_json(l2_raw)
    chosen = _chosen_label(data, name_to_label, legal) if data else None

    if data and chosen and chosen in topk:
        # 用解析库校正 l1/l2 (保证与意图库一致), 保留 L2 的置信度/澄清/回复
        c = parsed["label_to_cat"][chosen]
        pi = data.get("primary_intent", {}) or {}
        pi["l1"] = c["l1"]
        pi["l2"] = c["name"]
        data["primary_intent"] = pi
        data.setdefault("top_candidates", [])
        data.setdefault("needs_clarification", False)
        data.setdefault("user_output", "")
        data.setdefault("reason", "")
        return data

    # L2 解析失败或选了候选外的标签 -> 退回 L1 top-1
    if debug:
        print(f"[V4 L2] parse/validate failed, fallback to L1 top-1: {topk[0]}")
    return _fallback(parsed, topk[0], "Layer_2 parse/validate failed, used Layer_1 top-1")
