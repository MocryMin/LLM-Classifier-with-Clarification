"""
L2_risk_assess.py — 智能问答风险检验（Stage 2）
================================================

纯规则引擎，零LLM调用。基于场景基础风险 + 情绪标签修饰 + 合规关键词扫描，
输出风险等级和对应的回复模式。

每条规则独立可测，决策链完整可审计。

用法:
    from L2_risk_assess import assess_risk
    result = assess_risk(l0_output, l1_output, messages, debug=False)
"""

import re
from pipeline_types import (
    L0Output, L1Output, RiskOutput, RiskDecision,
    make_safe_risk,
)


# ============================================================
# 32场景 → 基础风险等级映射（来源：V2 场景设计明细表）
# ============================================================

SCENE_RISK_MAP: dict[str, str] = {
    # === 低风险 (8) ===
    "欢迎引导":   "low",
    "意图澄清":   "low",
    "未覆盖兜底": "low",
    "产品咨询":   "low",
    "服务介绍":   "low",
    "行权使用":   "low",
    "高频权益":   "low",
    "客服热线":   "low",

    # === 中风险 (15) ===
    "健康险投保":     "medium",
    "车险投保":       "medium",
    "寿险/年金投保":  "medium",
    "意外险投保":     "medium",
    "其他险种投保":   "medium",
    "明确产品":       "medium",
    "承保/保单获取":  "medium",
    "保单查询":       "medium",
    "续期缴费":       "medium",
    "保单变更":       "medium",
    "理赔报案":       "medium",
    "理赔进度查询":   "medium",
    "权益查询":       "medium",
    "业务员联系":     "medium",
    "网点查询":       "medium",

    # === 高风险 (9) ===
    "核保":           "high",
    "核赔":           "high",
    "退保/减保":      "high",
    "保单贷款/还款":  "high",
    "分红/年金/领取": "high",
    "保单复效":       "high",
    "理赔材料/条件":  "high",
    "撤销报案":       "high",
    "投诉建议":       "high",
}

RISK_SCORE = {"low": 0, "medium": 1, "high": 2}
SCORE_RISK = {0: "low", 1: "medium"}  # ≥2 → "high"

RESPONSE_MODE_MAP = {
    "low":    "generative",
    "medium": "faq_first",
    "high":   "faq_only_human",
}


# ============================================================
# 合规关键词（覆盖4个类别）
# ============================================================

COMPLIANCE_CATEGORIES: dict[str, list[str]] = {
    "监管投诉": ["监管", "银保监", "12378", "保监会"],
    "媒体曝光": ["曝光", "媒体", "微博", "抖音", "记者", "315", "消费者协会"],
    "资金安全": ["骗保", "诈骗", "洗钱", "非法", "盗刷"],
    "法律风险": ["起诉", "律师函", "法院", "判决", "违法"],
}


# ============================================================
# 规则函数（每条独立，统一签名）
# ============================================================

def rule_manual_override(l0: L0Output, l1: L1Output, msgs: list[dict]) -> RiskDecision | None:
    """人工标记 → 强制高风险，终止后续规则"""
    tag = l0.tags.get("manual")
    if tag and tag.triggered:
        return RiskDecision(
            step="manual_override",
            input_value=f"manual={tag.probability:.2f}",
            result="force_high",
            reason="人工标记触发（用户多次表达转人工），直接升级高风险+转人工",
        )
    return None


def rule_urgent_skip(l0: L0Output, l1: L1Output, msgs: list[dict]) -> RiskDecision | None:
    """紧急标记 → 跳过风险评估，终止后续规则"""
    tag = l0.tags.get("urgent")
    if tag and tag.triggered:
        return RiskDecision(
            step="urgent_skip",
            input_value=f"urgent={tag.probability:.2f}",
            result="skip_risk",
            reason="紧急标记触发（事故/受伤/紧急语境），跳过风险评估，直接推送操作指引",
        )
    return None


def rule_scene_base(l0: L0Output, l1: L1Output, msgs: list[dict]) -> RiskDecision:
    """场景基础风险"""
    scene = l1.primary_intent.get("l2", "") if l1.primary_intent else ""
    base = SCENE_RISK_MAP.get(scene, "medium")
    return RiskDecision(
        step="scene_base",
        input_value=scene or "未知场景",
        result=base,
        reason=f"场景'{scene}'基础风险={base}" if scene else "未识别到场景，默认中风险",
    )


def rule_angry_bump(l0: L0Output, l1: L1Output, msgs: list[dict]) -> RiskDecision | None:
    """愤怒 → 风险+1"""
    tag = l0.tags.get("angry")
    if tag and tag.triggered:
        return RiskDecision(
            step="angry_bump",
            input_value=f"angry={tag.probability:.2f}",
            result="risk+1",
            reason="愤怒/不满标记触发，风险等级+1",
        )
    return None


def rule_compliance_scan(l0: L0Output, l1: L1Output, msgs: list[dict]) -> RiskDecision | None:
    """合规关键词扫描"""
    all_text = " ".join(
        m.get("content", "") for m in msgs if m.get("role") == "user"
    )
    hits = []
    for category, keywords in COMPLIANCE_CATEGORIES.items():
        for kw in keywords:
            if kw in all_text:
                hits.append(category)
                break  # 每个类别只计一次

    if hits:
        return RiskDecision(
            step="compliance_scan",
            input_value=", ".join(hits),
            result=f"risk+{len(hits)}",
            reason=f"命中合规敏感词类别: {', '.join(hits)}",
        )
    return None


# ============================================================
# 规则链配置: (规则名, 规则函数, 是否为终止型)
# ============================================================

RISK_RULES: list[tuple[str, callable, bool]] = [
    ("manual_override",  rule_manual_override,  True),   # 终止型
    ("urgent_skip",      rule_urgent_skip,       True),   # 终止型
    ("scene_base",       rule_scene_base,        False),  # 累加型
    ("angry_bump",       rule_angry_bump,        False),  # 累加型
    ("compliance_scan",  rule_compliance_scan,   False),  # 累加型
]


# ============================================================
# 主入口
# ============================================================

def assess_risk(
    l0: L0Output,
    l1: L1Output,
    messages: list[dict],
    debug: bool = False,
) -> RiskOutput:
    """
    综合风险评估：场景基础风险 + 情绪标签叠加 + 合规关键词扫描。

    终止型规则（manual/urgent）命中后直接返回，不继续执行累加型规则。
    累加型规则依次执行，分数累积后映射到风险等级。

    Args:
        l0:       L0Output, Stage 0 输出
        l1:       L1Output, Stage 1 输出
        messages: list[dict], 原始对话消息
        debug:    bool, 为 True 时打印决策链

    Returns:
        RiskOutput
    """
    trail: list[RiskDecision] = []
    score = 0
    score_detail: dict[str, str] = {}
    triggered: list[str] = []
    compliance_hits: list[str] = []
    final_risk: str | None = None
    final_mode: str = "faq_first"

    try:
        for rule_name, rule_fn, is_terminal in RISK_RULES:
            decision = rule_fn(l0, l1, messages)

            if decision is None:
                continue

            trail.append(decision)
            triggered.append(rule_name)

            if is_terminal:
                # 终止型规则直接决定最终结果
                if rule_name == "manual_override":
                    final_risk = "high"
                    final_mode = "faq_only_human"
                elif rule_name == "urgent_skip":
                    final_risk = None  # 跳过
                    final_mode = "skip_risk_direct_guide"
                break
            else:
                # 累加型：提取分数调整
                result_str = decision.result
                if rule_name == "scene_base":
                    base_score = RISK_SCORE.get(result_str, 1)
                    score = base_score
                    score_detail["base"] = result_str
                elif "risk+" in result_str:
                    bump = int(result_str.split("+")[-1])
                    score += bump
                    score_detail[rule_name] = result_str

        # 分数→等级（仅累加型路径）
        if final_risk is None and final_mode != "skip_risk_direct_guide":
            if score <= 0:
                final_risk = "low"
            elif score == 1:
                final_risk = "medium"
            else:
                final_risk = "high"
            final_mode = RESPONSE_MODE_MAP.get(final_risk, "faq_first")

        # 收集合规命中
        for d in trail:
            if d.step == "compliance_scan":
                compliance_hits = [h.strip() for h in d.input_value.split(",")]

    except Exception as e:
        if debug:
            print(f"[RiskEngine] 异常: {e}，使用安全默认值")
        return make_safe_risk()

    if debug:
        _print_trail(trail, score_detail, final_risk, final_mode)

    return RiskOutput(
        risk_level=final_risk,
        response_mode=final_mode,
        score_detail=score_detail,
        decision_trail=trail,
        triggered_rules=triggered,
        compliance_hits=compliance_hits,
    )


# ============================================================
# 调试输出
# ============================================================

def _print_trail(trail, score_detail, risk, mode):
    """人类可读的决策链输出"""
    print("[RiskEngine] ========== 决策链 ==========")
    for i, d in enumerate(trail):
        print(f"  {i+1}. [{d.step}] {d.input_value} → {d.result}")
        print(f"     原因: {d.reason}")
    if score_detail:
        print(f"[RiskEngine] 评分: {score_detail}")
    print(f"[RiskEngine] 结论: 风险等级={risk}, 回复模式={mode}")
    print("[RiskEngine] ==============================")


# ============================================================
# 模块自测
# ============================================================

if __name__ == "__main__":
    from pipeline_types import TagResult

    print("=" * 60)
    print("L2_risk_assess 自测")
    print("=" * 60)

    # 辅助构造
    def _mk_tag(tag_type, prob, threshold=0.7):
        triggered = prob >= threshold
        actions = {
            "manual": "escalate", "angry": "risk_bump", "urgent": "skip_risk",
            "sad": "tone_soften", "non_biz": "redirect",
        }
        modifiers = {"manual": 999, "angry": 1, "urgent": 0, "sad": 0, "non_biz": 0}
        return TagResult(
            tag_type=tag_type, probability=prob, triggered=triggered,
            action=actions.get(tag_type, "none") if triggered else "none",
            risk_modifier=modifiers.get(tag_type, 0),
            skip_clarification=tag_type in ("manual", "angry", "urgent"),
        )

    def _mk_l0(overrides=None):
        defaults = {t: 0.0 for t in ["manual", "angry", "urgent", "sad", "non_biz"]}
        if overrides:
            defaults.update(overrides)
        tags = {t: _mk_tag(t, v) for t, v in defaults.items()}
        should_escalate = tags["manual"].triggered
        should_skip_risk = tags["urgent"].triggered
        return L0Output(tags=tags, should_escalate=should_escalate,
                        should_skip_risk=should_skip_risk,
                        raw_probabilities=defaults)

    def _mk_l1(scene, confidence=0.9):
        return L1Output(
            primary_intent={"l1": "售前服务", "l2": scene, "confidence": confidence},
            top_candidates=[],
            needs_clarification=False,
            slots=None,
            operation={"type": "direct_reply", "detail": ""},
            user_output="",
            reason="",
            scene_risk_base=SCENE_RISK_MAP.get(scene, "medium"),
        )

    # Test 1: 正常车险 → 中风险
    print("\n--- Test 1: 车险投保（中风险）---")
    r = assess_risk(_mk_l0(), _mk_l1("车险投保"), [], debug=True)
    assert r.risk_level == "medium"
    assert r.response_mode == "faq_first"
    print("  PASS")

    # Test 2: 车险 + 愤怒 → 高风险
    print("\n--- Test 2: 车险投保 + 愤怒 → 高风险 ---")
    r = assess_risk(_mk_l0({"angry": 0.85}), _mk_l1("车险投保"), [], debug=True)
    assert r.risk_level == "high"
    assert r.response_mode == "faq_only_human"
    assert "angry_bump" in r.triggered_rules
    print("  PASS")

    # Test 3: 欢迎引导 → 低风险
    print("\n--- Test 3: 欢迎引导（低风险）---")
    r = assess_risk(_mk_l0(), _mk_l1("欢迎引导"), [], debug=True)
    assert r.risk_level == "low"
    assert r.response_mode == "generative"
    print("  PASS")

    # Test 4: manual override
    print("\n--- Test 4: manual触发 → 直接高风险 ---")
    r = assess_risk(_mk_l0({"manual": 0.9}), _mk_l1("欢迎引导"), [], debug=True)
    assert r.risk_level == "high"
    assert "manual_override" in r.triggered_rules
    print("  PASS")

    # Test 5: urgent skip
    print("\n--- Test 5: urgent触发 → 跳过评估 ---")
    r = assess_risk(_mk_l0({"urgent": 0.85}), _mk_l1("理赔报案"), [], debug=True)
    assert r.risk_level is None
    assert r.response_mode == "skip_risk_direct_guide"
    print("  PASS")

    # Test 6: 合规关键词
    print("\n--- Test 6: 合规关键词 → 升风险 ---")
    r = assess_risk(_mk_l0(), _mk_l1("保单查询"),
                    [{"role": "user", "content": "我要去银保监投诉你们"}], debug=True)
    assert r.risk_level == "high"  # 中风险(保单查询) + 合规命中(+1) = high
    assert "compliance_scan" in r.triggered_rules
    assert len(r.compliance_hits) >= 1
    print("  PASS")

    # Test 7: 核保 → 高风险
    print("\n--- Test 7: 核保（高风险）---")
    r = assess_risk(_mk_l0(), _mk_l1("核保"), [], debug=True)
    assert r.risk_level == "high"
    assert r.response_mode == "faq_only_human"
    print("  PASS")

    print("\n" + "=" * 60)
    print("全部自测通过")
    print("=" * 60)
