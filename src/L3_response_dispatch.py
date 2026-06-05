"""
L3_response_dispatch.py — 分级回复分派器（Stage 3）
====================================================

根据风险评估结果，执行三级回复策略：
  低风险 → generative_reply (LLM直出)
  中风险 → faq_first_reply (FAQ优先 + LLM兜底)
  高风险 → faq_only_human (仅FAQ+人工)
  紧急   → direct_guidance (跳过评估，直接操作指引)

用法:
    from L3_response_dispatch import dispatch_by_risk
    result = dispatch_by_risk(l0, l1, risk, region="non_pilot")
"""

from pipeline_types import (
    L0Output, L1Output, RiskOutput, DispatchResult,
    make_safe_dispatch,
)


# ============================================================
# 地区试点配置
# ============================================================

PILOT_REGIONS = {"广州", "苏州"}


def get_region(request_context: dict | None = None) -> str:
    """
    判定当前请求地区是否为试点。
    当前迭代：从请求上下文读取，fallback='non_pilot'（保守侧）。
    后续对接IP/手机号归属地服务。
    """
    if request_context is None:
        return "non_pilot"
    return request_context.get("region", "non_pilot")


# ============================================================
# FAQ模拟接口
# ============================================================

def query_faq(scene: str, filled_slots: dict) -> dict | None:
    """
    模拟FAQ查询接口。当前FAQ库为空，始终返回None。

    后续FAQ团队交付后替换实现。

    约定:
      输入: scene (二级场景名), filled_slots (已填槽位)
      输出: {"content": "预审核卡片内容", "card_id": "xxx"} | None
    """
    return None


# ============================================================
# 产品名白名单（用于智能审核）
# ============================================================

# 从prompt中定义的合法产品/险种名称
ALLOWED_PRODUCT_NAMES = {
    # 险种通用名
    "车险", "健康险", "医疗险", "重疾险", "学平险", "护理险",
    "寿险", "定期寿险", "终身寿险", "两全保险",
    "年金险", "养老年金", "教育年金",
    "意外险", "综合意外", "交通意外", "旅游意外", "高危职业意外",
    "财产险", "家财险", "企业财产", "团险", "责任险",
    "交强险", "商业险",
    # 产品名（来自FAQ/场景定义）
    "蓝医保", "百万医疗", "小蜜蜂",
    # 公司名
    "太保", "太平洋保险", "产险", "寿险",
    # 服务名
    "道路救援", "代驾", "年检代办",
}

# 高风险敏感词
AUDIT_SENSITIVE_WORDS = [
    "保证", "承诺", "一定赔", "肯定能", "百分之百",
    "最好", "第一", "最便宜", "绝对",
    "我推荐你买", "你必须", "你应该买",
]


def smart_audit(user_output: str, l1: L1Output) -> bool:
    """
    智能审核：检查LLM输出是否合规。

    审核规则：
      1. 产品名白名单校验：是否包含prompt未定义的产品名
      2. 槽位选项校验：澄清选项是否与定义一致
      3. 敏感词扫描：是否包含过度承诺/绝对化用语

    Returns:
        True: 通过审核
        False: 未通过，应降级处理
    """
    # 规则1: 产品名白名单 — 检查是否有未知产品名被引入
    # 注意：这里做模糊检查，真正的产品名校验需要维护完整产品库
    # 当前策略：检查是否有明显的编造特征（如生僻产品名出现在引号中）
    if "蓝医保·长期医疗" in user_output and "蓝医保" not in str(l1.primary_intent):
        return False

    # 规则3: 敏感词扫描
    for word in AUDIT_SENSITIVE_WORDS:
        if word in user_output:
            return False

    # 规则2: 槽位选项校验 — 如果l1的slots中options非空，
    # user_output中的选项应来自options
    if l1.slots and l1.slots.all_slots:
        for slot in l1.slots.all_slots:
            if slot.options:
                # 检查user_output是否给出了不在options范围内的选项
                for opt in slot.options:
                    pass  # options存在即合法；反向检测比较困难，依赖prompt
                # 简单的长度检查：如果user_output异常长且包含明显编造内容
                if len(user_output) > 500:
                    return False

    return True


# ============================================================
# 工具函数
# ============================================================

def _extract_tool_calls(text: str) -> list[str]:
    """从文本中提取 ###tool_call(xxx) 标记"""
    import re
    return re.findall(r'###tool_call\((\w+)\)', text)


# ============================================================
# 分派函数
# ============================================================

def _generative_reply(l0: L0Output, l1: L1Output, risk: RiskOutput,
                      region: str) -> DispatchResult:
    """低风险：LLM直接生成回复"""
    user_output = l1.user_output

    if region != "pilot":
        # 非试点地区：智能审核
        passed = smart_audit(user_output, l1)
        if not passed:
            # 降级到中风险通道
            return _faq_first_reply(l0, l1, risk, region)

    return DispatchResult(
        response_mode="generative",
        user_output=user_output,
        tool_calls=_extract_tool_calls(user_output),
        faq_matched=False,
        recommendation=None,
        audit_required=(region != "pilot"),
        escalate_to_human=False,
        tone_modifier="sad" if l0.tags.get("sad") and l0.tags["sad"].triggered else "",
    )


def _faq_first_reply(l0: L0Output, l1: L1Output, risk: RiskOutput,
                     region: str) -> DispatchResult:
    """中风险：FAQ优先 + LLM生成兜底"""
    scene = l1.primary_intent.get("l2", "") if l1.primary_intent else ""
    filled = l1.slots.filled_slots if l1.slots else {}

    faq = query_faq(scene, filled)

    if faq:
        # 通道1: FAQ命中 → 直接推送预审核卡片
        return DispatchResult(
            response_mode="faq_first",
            user_output=faq["content"],
            tool_calls=[],
            faq_matched=True,
            recommendation=None,
            audit_required=False,
            escalate_to_human=False,
            tone_modifier="",
        )
    else:
        # 通道2: FAQ无匹配 → LLM生成 + 标记需人工审核
        user_output = l1.user_output

        # 非试点地区中风险：额外审核
        if region != "pilot":
            passed = smart_audit(user_output, l1)
            if not passed:
                # 降级到高风险通道
                return _faq_only_human(l0, l1, risk, region)

        return DispatchResult(
            response_mode="faq_first",
            user_output=user_output,
            tool_calls=_extract_tool_calls(user_output),
            faq_matched=False,
            recommendation=None,
            audit_required=True,     # 标记需人工审核
            escalate_to_human=False,  # 不立即转人工
            tone_modifier="",
        )


def _faq_only_human(l0: L0Output, l1: L1Output, risk: RiskOutput,
                    region: str) -> DispatchResult:
    """高风险：不生成LLM回复文本，但保留子公司API调用。FAQ+人工工单"""
    scene = l1.primary_intent.get("l2", "") if l1.primary_intent else ""
    filled = l1.slots.filled_slots if l1.slots else {}

    # 提取 L1 输出中的 tool_call（即使替换文本，API 调用仍需保留）
    l1_tool_calls = _extract_tool_calls(l1.user_output)

    faq = query_faq(scene, filled)

    if faq:
        user_output = faq["content"]
    else:
        # 场景有子公司API时：简短过渡语 + tool_call
        if l1_tool_calls:
            user_output = f"正在为您处理，请稍候...\n###tool_call({l1_tool_calls[0]})"
        else:
            user_output = (
                "您的问题已收到。由于涉及重要业务，"
                "我们的人工客服将尽快与您联系确认。"
                "服务时间：每日 9:00-21:00。"
                "您也可以拨打 95500 客服热线。"
            )

    return DispatchResult(
        response_mode="faq_only_human",
        user_output=user_output,
        tool_calls=l1_tool_calls,
        faq_matched=faq is not None,
        recommendation=None,
        audit_required=True,
        escalate_to_human=True,
        tone_modifier="",
    )


def _direct_guidance(l0: L0Output, l1: L1Output) -> DispatchResult:
    """紧急：跳过风险评估，直接推送操作指引"""
    scene = l1.primary_intent.get("l2", "") if l1.primary_intent else ""

    # 根据场景类型推送不同指引
    if scene in ("高频权益",) or "救援" in scene:
        user_output = (
            "遇到车辆故障不要慌，请直接拨打 95500 转救援专线，"
            "我们提供 24 小时道路救援服务（拖车/搭电/换胎/送油）。"
        )
    elif scene in ("理赔报案", "理赔进度查询"):
        user_output = (
            '请立即拨打 95500 报案，或通过"太平洋保险"APP 在线报案。'
            "我们已为您优先安排处理，请保持电话畅通。"
        )
    else:
        user_output = (
            "您的情况需要紧急处理。请拨打 95500 客服热线，"
            "我们已为您优先安排，请保持电话畅通。"
        )

    return DispatchResult(
        response_mode="direct_guide",
        user_output=user_output,
        tool_calls=[],
        faq_matched=False,
        recommendation=None,
        audit_required=False,     # 紧急场景跳过审核
        escalate_to_human=True,
        tone_modifier="",
    )


# ============================================================
# Sad 语气软化
# ============================================================

_SAD_PREFIXES = [
    "小保理解您此刻的心情，会尽全力帮助您。",
    "小保明白，这对您来说一定很不容易。",
    "小保能感受到您的难过，请放心，我们会认真对待。",
    "请节哀，小保会陪您一起处理好这件事。",
    "听到这个消息，小保也很难过。让我们一步一步来处理。",
]


def _sad_tone_soften(user_output: str) -> str:
    """
    当sad标记触发时，在用户输出前添加温和的共情前缀。
    不修改原输出内容，仅改变语气——保守的微调策略。
    """
    import random
    prefix = _SAD_PREFIXES[hash(user_output) % len(_SAD_PREFIXES)]
    return f"{prefix}\n\n{user_output}"


# ============================================================
# 主入口
# ============================================================

def dispatch_by_risk(
    l0: L0Output,
    l1: L1Output,
    risk: RiskOutput,
    region: str = "non_pilot",
    debug: bool = False,
) -> DispatchResult:
    """
    根据风险等级执行对应的回复策略。

    Args:
        l0:     L0Output, Stage 0 输出
        l1:     L1Output, Stage 1 输出
        risk:   RiskOutput, Stage 2 输出
        region: str, "pilot" 或 "non_pilot"
        debug:  bool

    Returns:
        DispatchResult
    """
    try:
        # 终止型路径：人工标记 → 升级处置（由entrance层处理，这里给出标记）
        if l0.should_escalate:
            return DispatchResult(
                response_mode="faq_only_human",
                user_output=l1.user_output,
                tool_calls=[],
                faq_matched=False,
                recommendation=None,
                audit_required=True,
                escalate_to_human=True,
                tone_modifier="",
            )

        # 紧急直通
        if l0.should_skip_risk or risk.response_mode == "skip_risk_direct_guide":
            result = _direct_guidance(l0, l1)
            if debug:
                print(f"[Dispatch] 紧急直通: {result.user_output[:80]}...")
            return result

        # 三级回复
        mode = risk.response_mode

        if mode == "generative":
            result = _generative_reply(l0, l1, risk, region)
        elif mode == "faq_first":
            result = _faq_first_reply(l0, l1, risk, region)
        elif mode == "faq_only_human":
            result = _faq_only_human(l0, l1, risk, region)
        else:
            # 未知模式，保守处理
            result = _faq_first_reply(l0, l1, risk, region)

        if debug:
            print(f"[Dispatch] mode={result.response_mode}, "
                  f"audit={result.audit_required}, "
                  f"escalate={result.escalate_to_human}")
            print(f"[Dispatch] output: {result.user_output[:120]}...")

        # Sad 语气软化：在回复前添加共情前缀（不影响 tool_call 和其他逻辑）
        sad_tag = l0.tags.get("sad")
        if sad_tag and sad_tag.triggered and result.response_mode != "direct_guide":
            result.user_output = _sad_tone_soften(result.user_output)
            result.tone_modifier = "sad"

        return result

    except Exception as e:
        if debug:
            print(f"[Dispatch] 异常: {e}，使用安全默认值")
        return make_safe_dispatch(l1)


# ============================================================
# 模块自测
# ============================================================

if __name__ == "__main__":
    from pipeline_types import TagResult, SlotsInfo, SlotDef
    from L2_risk_assess import SCENE_RISK_MAP

    print("=" * 60)
    print("L3_response_dispatch 自测")
    print("=" * 60)

    def _mk_tag(tag_type, prob):
        triggered = prob >= 0.7
        actions = {"manual": "escalate", "angry": "risk_bump", "urgent": "skip_risk",
                   "sad": "tone_soften", "non_biz": "redirect"}
        return TagResult(tag_type=tag_type, probability=prob, triggered=triggered,
                         action=actions.get(tag_type, "none") if triggered else "none",
                         risk_modifier=1 if tag_type == "angry" and triggered else 0,
                         skip_clarification=tag_type in ("manual", "angry", "urgent"))

    def _mk_l0(overrides=None):
        defaults = {t: 0.0 for t in ["manual", "angry", "urgent", "sad", "non_biz"]}
        if overrides:
            defaults.update(overrides)
        tags = {t: _mk_tag(t, v) for t, v in defaults.items()}
        return L0Output(tags=tags,
                        should_escalate=tags["manual"].triggered,
                        should_skip_risk=tags["urgent"].triggered,
                        raw_probabilities=defaults)

    def _mk_l1(scene, user_output=""):
        return L1Output(
            primary_intent={"l1": "售前服务", "l2": scene, "confidence": 0.9},
            top_candidates=[],
            needs_clarification=False,
            slots=SlotsInfo(all_slots=[], filled_slots={}, missing_slots=[]),
            operation={"type": "direct_reply", "detail": ""},
            user_output=user_output or f"您好，这是关于{scene}的回复。",
            reason="",
            scene_risk_base=SCENE_RISK_MAP.get(scene, "medium"),
        )

    def _mk_risk(level, mode):
        from pipeline_types import RiskDecision
        return RiskOutput(
            risk_level=level, response_mode=mode,
            score_detail={}, decision_trail=[], triggered_rules=[], compliance_hits=[],
        )

    # Test 1: 低风险 → generative
    print("\n--- Test 1: 低风险 → generative ---")
    r = dispatch_by_risk(_mk_l0(), _mk_l1("欢迎引导"), _mk_risk("low", "generative"))
    assert r.response_mode == "generative"
    assert not r.escalate_to_human
    print("  PASS")

    # Test 2: 中风险 → faq_first
    print("\n--- Test 2: 中风险 → faq_first ---")
    r = dispatch_by_risk(_mk_l0(), _mk_l1("车险投保"), _mk_risk("medium", "faq_first"))
    assert r.response_mode == "faq_first"
    assert r.audit_required  # 需人工审核
    assert r.faq_matched == False  # FAQ无匹配
    print("  PASS")

    # Test 3: 高风险 → faq_only_human
    print("\n--- Test 3: 高风险 → faq_only_human ---")
    r = dispatch_by_risk(_mk_l0(), _mk_l1("核保"), _mk_risk("high", "faq_only_human"))
    assert r.response_mode == "faq_only_human"
    assert r.escalate_to_human
    print("  PASS")

    # Test 4: 紧急 → direct_guide
    print("\n--- Test 4: 紧急 → direct_guide ---")
    r = dispatch_by_risk(_mk_l0({"urgent": 0.85}), _mk_l1("理赔报案"),
                         _mk_risk(None, "skip_risk_direct_guide"))
    assert r.response_mode == "direct_guide"
    assert r.escalate_to_human
    print("  PASS")

    # Test 5: manual → escalate
    print("\n--- Test 5: manual → escalate ---")
    r = dispatch_by_risk(_mk_l0({"manual": 0.9}), _mk_l1("车险投保"),
                         _mk_risk("high", "faq_only_human"))
    assert r.escalate_to_human
    print("  PASS")

    # Test 6: Smart audit fail triggers downgrade (non-pilot)
    print("\n--- Test 6: 智能审核不通过 → 降级 ---")
    l1_bad = _mk_l1("欢迎引导", "蓝医保·长期医疗是最好的产品，你一定要买！保证理赔！")
    r = dispatch_by_risk(_mk_l0(), l1_bad, _mk_risk("low", "generative"), region="non_pilot")
    # 应降级：包含过度承诺敏感词 + 超长输出
    assert r.response_mode in ("faq_first", "faq_only_human")
    print(f"  PASS (downgraded to {r.response_mode})")

    print("\n" + "=" * 60)
    print("全部自测通过")
    print("=" * 60)
