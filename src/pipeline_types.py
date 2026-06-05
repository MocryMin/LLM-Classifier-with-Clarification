"""
pipeline_types.py — V2 Pipeline 阶段间数据结构定义
====================================================

定义了四阶段管道（L0 → L1 → Risk → Dispatch）之间传递的所有数据结构。
每个阶段只依赖这些类型，不直接依赖其他阶段的实现。
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Stage 0: L0 输出
# ============================================================

@dataclass
class TagResult:
    """单个L0标签的检测结果 + 处置建议"""
    tag_type: str            # "manual" | "angry" | "urgent" | "sad" | "non_biz"
    probability: float       # 原始概率值 [0, 1]
    triggered: bool          # 是否超过阈值
    action: str              # "escalate" | "risk_bump" | "skip_risk" | "tone_soften" | "redirect" | "none"
    risk_modifier: int       # 风险等级调整量 (0 或 1)
    skip_clarification: bool # 是否应跳过澄清轮次


@dataclass
class L0Output:
    """Stage 0 完整输出"""
    tags: dict[str, TagResult]   # {tag_type: TagResult}
    should_escalate: bool        # → case=0，立即转人工
    should_skip_risk: bool       # → case=2，跳过风险评估，直接操作指引
    raw_probabilities: dict[str, float] = field(default_factory=dict)  # 原始概率（调试用）


# ============================================================
# Stage 1: L1 输出
# ============================================================

@dataclass
class SlotDef:
    """单个槽位定义"""
    name: str
    description: str
    options: list[str] = field(default_factory=list)


@dataclass
class SlotsInfo:
    """槽位信息"""
    all_slots: list[SlotDef] = field(default_factory=list)
    filled_slots: dict[str, str] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)


@dataclass
class L1Output:
    """Stage 1 完整输出（与V1兼容，扩展 scene_risk_base）"""
    primary_intent: dict          # {l1, l2, confidence}
    top_candidates: list[dict]    # [{l1, l2, probability}, ...]
    needs_clarification: bool
    slots: SlotsInfo
    operation: dict               # {type, detail}
    user_output: str              # L1 LLM生成的原始对客文本（Stage 3可能替换）
    reason: str
    scene_risk_base: str = "medium"  # V2新增：该场景的基础风险等级


# ============================================================
# Stage 2: 风险评估输出
# ============================================================

@dataclass
class RiskDecision:
    """单步决策记录（审计用）"""
    step: str           # 规则名，如 "scene_base", "angry_bump"
    input_value: str    # 触发值，如 "车险投保" 或 "angry=0.85"
    result: str         # 决策结果，如 "medium" 或 "risk+1"
    reason: str         # 决策理由


@dataclass
class RiskOutput:
    """Stage 2 完整输出"""
    risk_level: Optional[str]        # "low" | "medium" | "high" | None(跳过)
    response_mode: str               # "generative" | "faq_first" | "faq_only_human" | "skip_risk_direct_guide"
    score_detail: dict               # {"base": 1, "angry_bump": "+1", ...} → total
    decision_trail: list[RiskDecision]  # 完整决策链
    triggered_rules: list[str]       # 触发的规则名称列表
    compliance_hits: list[str]       # 命中的合规关键词类别


# ============================================================
# Stage 3: 回复分派输出
# ============================================================

@dataclass
class DispatchResult:
    """Stage 3 完整输出"""
    response_mode: str          # "generative" | "faq_first" | "faq_only_human" | "direct_guide"
    user_output: str            # 最终对客文本
    tool_calls: list[str]       # 提取的 ###tool_call(xxx)
    faq_matched: bool           # FAQ是否命中
    recommendation: Optional[dict]  # 问答后推荐（占位，当前始终None）
    audit_required: bool        # 是否需要人工审核
    escalate_to_human: bool     # 是否转人工
    tone_modifier: str          # "" | "sad" — 语气调整标记


# ============================================================
# 管道最终返回
# ============================================================

@dataclass
class PipelineResult:
    """entrance() 的最终返回值"""
    case: int                    # 0=拦截升级, 1=正常路由, 2=紧急直通
    risk_level: Optional[str]    # 风险等级
    response_mode: str           # 回复模式
    tag_dispositions: dict[str, dict]  # 各tag处置（序列化用）
    decision_trail: list[dict]   # 决策链（序列化用）
    data: dict                   # 业务数据


# ============================================================
# 工具函数
# ============================================================

def make_safe_l0() -> L0Output:
    """构造安全的零值L0（Stage 0失败时使用）"""
    safe_tags = {}
    for tag_type in ["manual", "angry", "urgent", "sad", "non_biz"]:
        safe_tags[tag_type] = TagResult(
            tag_type=tag_type,
            probability=0.0,
            triggered=False,
            action="none",
            risk_modifier=0,
            skip_clarification=False,
        )
    return L0Output(
        tags=safe_tags,
        should_escalate=False,
        should_skip_risk=False,
        raw_probabilities={t: 0.0 for t in safe_tags},
    )


def make_safe_risk() -> RiskOutput:
    """构造安全的默认中风险（Stage 2失败时使用）"""
    fallback_decision = RiskDecision(
        step="fallback",
        input_value="风险评估异常",
        result="medium",
        reason="风险评估模块异常，默认保守处理为中风险",
    )
    return RiskOutput(
        risk_level="medium",
        response_mode="faq_first",
        score_detail={"fallback": "medium"},
        decision_trail=[fallback_decision],
        triggered_rules=["fallback"],
        compliance_hits=[],
    )


def make_safe_dispatch(l1: L1Output) -> DispatchResult:
    """构造安全的分派结果（Stage 3失败时使用）"""
    return DispatchResult(
        response_mode="faq_first",
        user_output=l1.user_output,
        tool_calls=[],
        faq_matched=False,
        recommendation=None,
        audit_required=True,
        escalate_to_human=False,
        tone_modifier="",
    )
