"""
L1 Generator: clean JSON → 文法树
=================================

读取 L0.5 产出的 scene_table_clean.json,构建文法树(Prompt).
文法树可被 serialize.py 渲染为最终 prompt 文本.

V3 规则：
  - 调用格式统一为 ###call(L1-L2)
  - L2 澄清仅当 SOP 非空且用户未提供任何 SOP 要求的内容时触发
  - 两种模式：full(含 L2 澄清)/ classify_only(仅分类+L1澄清)

用法:
  python L1_generator.py <scene_table_clean.json> [--mode full|classify_only] [--out <tree.json>]

示例:
  python prompter/src/L1_generator.py artifacts/0604/scene_table_clean.json
  python prompter/src/L1_generator.py scene_table_clean.json --mode classify_only --out tree.json
"""

import json
import sys
from pathlib import Path

# 兼容直接执行和包导入
try:
    from .grammar_tree import (
        Prompt, Section, FixedText, Placeholder,
        IntentCatalog, IntentGroup, Intent,
    )
    from .serialize import serialize
except ImportError:
    from grammar_tree import (
        Prompt, Section, FixedText, Placeholder,
        IntentCatalog, IntentGroup, Intent,
    )
    from serialize import serialize


# ═══════════════════════════════════════════════════════════
# 中文数字
# ═══════════════════════════════════════════════════════════

_CN_NUM = [
    "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
]


def _cn_num(n: int) -> str:
    if 0 <= n < len(_CN_NUM):
        return _CN_NUM[n]
    return str(n)


# ═══════════════════════════════════════════════════════════
# 固定文本段 - V3
# ═══════════════════════════════════════════════════════════

ROLE_TEXT = """\
你是一个保险客服意图路由助手(L1 层).
你的唯一任务：将用户消息分类到对应的二级业务场景,并决定路由方式.
你不收集槽位,不做保险顾问,不生成核保/核赔结论."""


ROUTING_WORKFLOW_HEADER = """\
============================================================
Step 1 - 意图分类
============================================================

将用户消息分类到意图库中的二级场景.
输出 primary_intent(L1+L2 名称)及 top_candidates(如有竞争意图)."""


ROUTING_L1_CLARIFICATION = """\
============================================================
Step 2 - L1 澄清判断
============================================================

触发 L1 澄清的条件(满足任一)：
  A. 分类结果为"开场-意图澄清"(1.2)
  B. primary_intent.confidence < 0.7
  C. top-1 与 top-2 的 probability 差距 < 0.15

L1 澄清做法：
  - user_output 中列出 top-2/3 候选场景名(具体业务场景,非大类)
  - 例："您是想办理健康险投保,还是想了解核保信息？"
  - 禁止展示"A.车险/财产险 B.人身寿险/年金 C...."等固定大类格式
  - L1 澄清不涉及槽位收集

不触发 L1 澄清 → 进入 Step 3."""


ROUTING_L2_CLARIFICATION = """\
============================================================
Step 3 - L2 澄清判断
============================================================

前提：意图已明确(未触发 L1 澄清).

L2 澄清需同时满足两个条件：
  条件1：该 L2 意图的"澄清指引/SOP"非空,且明确给出了需要澄清的项目
  条件2：用户对话历史中**没有提供任何**需要澄清的项目
         (重要：如果 SOP 要求澄清 A、B、C 三项,用户只提供了 A,
          即使缺少 B、C,也**不要澄清**--视为用户已提供信息,直接路由)

L2 澄清生成规则：
  - 若 SOP 为空 → 不澄清,直接进入 Step 4
  - 若 SOP 内容为澄清指引(描述需要收集什么)→ 按指引生成最小言语澄清(1-2句),
    不超出 SOP 范围,无幻觉
  - 若 SOP 内容本身为澄清文本样例 → 直接输出该样例

不触发 L2 澄清 → 进入 Step 4."""


ROUTING_REPLY = """\
============================================================
Step 4 - 回复/路由
============================================================

根据该 L2 意图的"对应子公司"字段：

  A. "对应子公司"为空
     → 生成简短衔接词 + ###call(L1-L2)
       例："正在为您查询...\\n###call(售前服务-产品咨询)"

  B. "对应子公司"不为空,且要求集团直接回复
     → 进行最小绝对正确回复(≤2句).
       仅限：欢迎引导(1.1)、客服热线(6.3)、产品咨询(2.1)中"大而无当"的通用问题
       (如"什么是保险？""你们提供哪些险种？")
       一旦涉及可能出错的产品细节/条款/报价 → 输出衔接词 + ###call(L1-L2)

  C. "对应子公司"不为空,且要求子公司处理
     → 生成简短衔接词 + ###call(L1-L2)
       例："正在为您查询保单信息...\\n###call(保单服务-保单查询)"

调用格式：统一使用 ###call(L1-L2)
  L1-L2 即分类结果的两级意图名称,例如：
    ###call(售前服务-健康险投保)
    ###call(保单服务-退保/减保)
    ###call(理赔服务-理赔报案)"""


# ── classify_only 模式：不含 L2 段,Step 2 后直接跳 Step 4 ──

ROUTING_L2_SKIP = """\
============================================================
Step 3 - 回复/路由
============================================================

无需 L2 澄清.确定意图后直接路由：

  A. "对应子公司"为空
     → 生成简短衔接词 + ###call(L1-L2)

  B. "对应子公司"不为空,且要求集团直接回复
     → 进行最小绝对正确回复(≤2句)

  C. "对应子公司"不为空,且要求子公司处理
     → 生成简短衔接词 + ###call(L1-L2)

调用格式：统一使用 ###call(L1-L2)"""


CONSTRAINTS_TEXT = """\
============================================================
反臆想约束(严格遵守)
============================================================

【知识边界】
  - 你是意图路由系统,不是保险顾问系统
  - 严禁：保险知识科普、险种介绍对比、术语解释、产品推荐、核保核赔结论
  - 涉及具体产品条款/报价/细则 → ###call(L1-L2)

【最小言语原则】
  - 路由时：1句简短衔接词 + ###call(L1-L2),衔接词≤15字
  - L1 澄清时：列出2-3个候选场景名让用户选,≤2句
  - L2 澄清时：严格按 SOP 指引生成,≤2句,不超出 SOP 范围
  - 集团直接回复：简洁明了,≤2句

【输出自检】(每次输出前逐条检查)
  1. 我是否在科普/介绍/对比/推荐？ → 改为 ###call(L1-L2)
  2. 我是否在收集 SOP 范围以外的信息？ → 删除
  3. 我是否展示了5大类固定格式？ → 删除
  4. 我的回复是否超出了"最小绝对正确"范围？ → 缩减或改为 ###call(L1-L2)"""


CONSTRAINTS_CLASSIFY_ONLY = """\
============================================================
反臆想约束(严格遵守)
============================================================

【知识边界】
  - 你是意图路由系统,不是保险顾问系统
  - 严禁：保险知识科普、险种介绍对比、术语解释、产品推荐、核保核赔结论
  - 涉及具体产品条款/报价/细则 → ###call(L1-L2)

【最小言语原则】
  - 路由时：1句简短衔接词 + ###call(L1-L2),衔接词≤15字
  - L1 澄清时：列出2-3个候选场景名让用户选,≤2句
  - 集团直接回复：简洁明了,≤2句

【输出自检】(每次输出前逐条检查)
  1. 我是否在科普/介绍/对比/推荐？ → 改为 ###call(L1-L2)
  2. 我是否展示了5大类固定格式？ → 删除
  3. 我的回复是否超出了"最小绝对正确"范围？ → 缩减或改为 ###call(L1-L2)"""


SAMPLES_TEXT = """\
============================================================
示例1：意图明确 + 无需L2澄清 → 直接路由
============================================================
对话：[用户] 我想查一下我的保单

输出：
{
  "primary_intent": {"l1": "保单服务", "l2": "保单查询", "confidence": 0.95},
  "needs_clarification": false,
  "user_output": "正在为您查询保单信息...\\n###call(保单服务-保单查询)",
  "reason": "意图明确.SOP为空,无需L2澄清.子公司处理→直接路由."
}

============================================================
示例2：意图明确 + 需L2澄清(SOP有要求且用户未提供任何项)
============================================================
对话：[用户] 我想买个医疗险

("健康险投保"SOP：需要澄清 → 被保人年龄、健康状况)

输出：
{
  "primary_intent": {"l1": "售前服务", "l2": "健康险投保", "confidence": 0.90},
  "needs_clarification": true,
  "user_output": "请问被保人的年龄是？是否有高血压、糖尿病等既往病史？",
  "reason": "意图明确.SOP要求澄清年龄+健康状况,用户未提供任何项 → L2澄清."
}

============================================================
示例3：意图明确 + SOP有要求但用户已提供部分 → 不澄清,直接路由
============================================================
对话：[用户] 我35岁,想买个医疗险

输出：
{
  "primary_intent": {"l1": "售前服务", "l2": "健康险投保", "confidence": 0.92},
  "needs_clarification": false,
  "user_output": "正在为您查询健康险方案...\\n###call(售前服务-健康险投保)",
  "reason": "意图明确.SOP要求年龄+健康状况,但用户已提供年龄 → 不再L2澄清."
}

============================================================
示例4：竞争意图 → L1澄清
============================================================
对话：[用户] 车险

输出：
{
  "primary_intent": {"l1": "售前服务", "l2": "车险投保", "confidence": 0.55},
  "top_candidates": [
    {"l1": "售前服务", "l2": "车险投保", "probability": 0.55},
    {"l1": "理赔服务", "l2": "理赔报案", "probability": 0.35}
  ],
  "needs_clarification": true,
  "user_output": "您是想购买车险,还是已经出险需要报案？",
  "reason": "top-1置信度不足,且与top-2差距小 → L1澄清."
}

============================================================
示例5：SOP为澄清样例 → 直接输出样例
============================================================
对话：[用户] 我想买车险

("车险投保"SOP为澄清样例："请问您的车牌号是多少？")

输出：
{
  "primary_intent": {"l1": "售前服务", "l2": "车险投保", "confidence": 0.88},
  "needs_clarification": true,
  "user_output": "请问您的车牌号是多少？",
  "reason": "意图明确.SOP为澄清样例,用户未提供任何信息 → 直接输出样例."
}"""


# classify_only 模式不含 L2 澄清示例
SAMPLES_CLASSIFY_ONLY = """\
============================================================
示例1：意图明确 → 直接路由
============================================================
对话：[用户] 我想查一下我的保单

输出：
{
  "primary_intent": {"l1": "保单服务", "l2": "保单查询", "confidence": 0.95},
  "needs_clarification": false,
  "user_output": "正在为您查询保单信息...\\n###call(保单服务-保单查询)",
  "reason": "意图明确,直接路由."
}

============================================================
示例2：竞争意图 → L1澄清
============================================================
对话：[用户] 车险

输出：
{
  "primary_intent": {"l1": "售前服务", "l2": "车险投保", "confidence": 0.55},
  "top_candidates": [
    {"l1": "售前服务", "l2": "车险投保", "probability": 0.55},
    {"l1": "理赔服务", "l2": "理赔报案", "probability": 0.35}
  ],
  "needs_clarification": true,
  "user_output": "您是想购买车险,还是已经出险需要报案？",
  "reason": "top-1置信度不足,且与top-2差距小 → L1澄清."
}

============================================================
示例3：开场问候 → 集团直接回复
============================================================
对话：[用户] 你好

输出：
{
  "primary_intent": {"l1": "开场", "l2": "欢迎引导", "confidence": 0.98},
  "needs_clarification": false,
  "user_output": "您好,我是太保集团的智能管家小保,请问有什么可以帮您？",
  "reason": "纯问候,欢迎引导 → 集团直接回复."
}"""


OUTPUT_FORMAT_TEXT = """\
============================================================
输出 JSON 格式
============================================================

请只输出以下 JSON(不要输出任何其他文字)：

{
  "primary_intent": {
    "l1": "一级意图名称",
    "l2": "二级意图名称",
    "confidence": 0.95
  },
  "top_candidates": [
    {"l1": "...", "l2": "...", "probability": 0.XX}
  ],
  "needs_clarification": false,
  "user_output": "面向用户的输出文本",
  "reason": "简要判断依据(1-2句话)"
}

字段说明：
- primary_intent: 最可能的意图及置信度
- top_candidates: 概率>0.1 的候选意图(可选,竞争意图时填写)
- needs_clarification: true 表示需要澄清(L1 意图不明确 或 L2 需收集信息)
  - true → user_output 为澄清文本
  - false → user_output 为回复/路由文本
- user_output:
  - 路由时：1句衔接词 + ###call(L1-L2)
  - 澄清时：L1→候选场景列表 / L2→按SOP生成
  - 集团直接回复时：最小绝对正确回复
- reason: 判断依据(1-2句话)"""


OUTPUT_FORMAT_CLASSIFY_ONLY = """\
============================================================
输出 JSON 格式
============================================================

请只输出以下 JSON(不要输出任何其他文字)：

{
  "primary_intent": {
    "l1": "一级意图名称",
    "l2": "二级意图名称",
    "confidence": 0.95
  },
  "top_candidates": [
    {"l1": "...", "l2": "...", "probability": 0.XX}
  ],
  "needs_clarification": false,
  "user_output": "面向用户的输出文本",
  "reason": "简要判断依据(1-2句话)"
}

字段说明：
- primary_intent: 最可能的意图及置信度
- top_candidates: 概率>0.1 的候选意图(可选,竞争意图时填写)
- needs_clarification: true 表示 L1 意图不明确需要澄清
  - true → user_output 为澄清文本
  - false → user_output 为回复/路由文本
- user_output:
  - 路由时：1句衔接词 + ###call(L1-L2)
  - L1 澄清时：候选场景列表
  - 集团直接回复时：最小绝对正确回复
- reason: 判断依据(1-2句话)"""


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _build_cell_getter(columns: list[str]):
    """构建 cells 字段访问器,避免硬编码列名中的 Unicode 字符.

    列顺序固定(12列):
      0:一级意图, 1:二级意图, 2:二级场景定义,
      3:风险等级, 4:FAQ典型问题, 5:完善负责人,
      6:澄清指引/SOP, 7:优先级, 8:对应子公司,
      9:回复设计, 10:前端设计, 11:备注
    """
    keys = {
        "l1": columns[0],
        "l2": columns[1],
        "definition": columns[2],
        "risk": columns[3],
        "faq": columns[4],
        "sop": columns[6],
        "priority": columns[7],
        "company": columns[8],
        "reply": columns[9],
        "notes": columns[11],
    }

    def get(cells: dict, logical_name: str, default: str = "") -> str:
        key = keys.get(logical_name, logical_name)
        return cells.get(key, default).strip()

    return get


def _build_intent_catalog(rows: list[dict], columns: list[str]) -> IntentCatalog:
    """从 clean JSON 的 rows 构建 IntentCatalog.

    保持 xlsx 中出现的一级/二级顺序.
    """
    cell = _build_cell_getter(columns)

    groups: list[IntentGroup] = []
    seen_l1: list[str] = []
    l1_to_group: dict[str, IntentGroup] = {}

    for row in rows:
        cells = row["cells"]
        clean = row.get("clean", {})

        l1 = cell(cells, "l1")

        # 新的 L1 分组
        if l1 not in seen_l1:
            seen_l1.append(l1)
            group = IntentGroup(
                l1_name=l1,
                group_index=len(seen_l1),
            )
            groups.append(group)
            l1_to_group[l1] = group

        group = l1_to_group[l1]

        # 构建 Intent
        intent = Intent(
            display_id=f"{group.group_index}.{len(group.intents) + 1}",
            l1=l1,
            l2=clean.get("intent_name", cell(cells, "l2")),
            definition=cell(cells, "definition"),
            faq_items=clean.get("faq_items", []),
            sop=cell(cells, "sop"),
            priority=cell(cells, "priority"),
            company=cell(cells, "company"),
            reply_design=cell(cells, "reply"),
            notes=cell(cells, "notes"),
        )
        group.intents.append(intent)

    return IntentCatalog(groups=groups)


def _build_routing_section(mode: str) -> FixedText:
    """构建 ##路由规则## 段(mode 决定是否含 Step 3 L2澄清)."""
    parts = [ROUTING_WORKFLOW_HEADER, "", ROUTING_L1_CLARIFICATION]

    if mode == "full":
        parts.extend(["", ROUTING_L2_CLARIFICATION, "", ROUTING_REPLY])
    else:
        parts.extend(["", ROUTING_L2_SKIP])

    return FixedText("\n".join(parts))


def _build_constraints_section(mode: str) -> FixedText:
    """构建 ##约束## 段."""
    if mode == "full":
        return FixedText(CONSTRAINTS_TEXT)
    else:
        return FixedText(CONSTRAINTS_CLASSIFY_ONLY)


def _build_output_format_section(mode: str) -> FixedText:
    """构建 ##输出格式## 段."""
    if mode == "full":
        return FixedText(OUTPUT_FORMAT_TEXT)
    else:
        return FixedText(OUTPUT_FORMAT_CLASSIFY_ONLY)


def _build_samples_section(mode: str) -> FixedText:
    """构建 ##samples## 段."""
    if mode == "full":
        return FixedText(SAMPLES_TEXT)
    else:
        return FixedText(SAMPLES_CLASSIFY_ONLY)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def generate(
    registry_path: str | Path,
    mode: str = "full",
) -> Prompt:
    """从 clean JSON 构建文法树.

    Args:
        registry_path: L0.5 产出的 scene_table_clean.json
        mode: "full"(常规模式,含L2澄清)| "classify_only"(仅分类+L1澄清)

    Returns:
        Prompt 文法树根节点
    """
    if mode not in ("full", "classify_only"):
        raise ValueError(f"Unknown mode: {mode!r}, expected 'full' or 'classify_only'")

    registry_path = Path(registry_path)

    # ── 读取 clean JSON ──
    with open(registry_path, "r", encoding="utf-8") as f:
        table = json.load(f)
    rows = table["rows"]
    columns = table["columns"]

    # ── 构建意图库 ──
    catalog = _build_intent_catalog(rows, columns)

    # ── 组装段落 ──
    prompt = Prompt(mode=mode, sections=[
        Section(title="##role##", content=FixedText(ROLE_TEXT)),
        Section(title="##意图库##", content=catalog),
        Section(title="##路由规则##", content=_build_routing_section(mode)),
        Section(title="##约束##", content=_build_constraints_section(mode)),
        Section(title="##samples##", content=_build_samples_section(mode)),
        Section(title="##输出格式##", content=_build_output_format_section(mode)),
        Section(title="##对话内容##", content=Placeholder(key="conversation")),
    ])

    return prompt


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="L1 Generator: clean JSON → 文法树 → prompt 文本"
    )
    parser.add_argument("registry", help="L0.5 产出的 scene_table_clean.json")
    parser.add_argument(
        "--mode", "-m",
        default="full",
        choices=["full", "classify_only"],
        help="生成模式: full(含L2澄清)| classify_only(仅分类+L1澄清)",
    )
    parser.add_argument(
        "--out-tree", "-t",
        default=None,
        help="输出文法树 JSON(可选)",
    )
    parser.add_argument(
        "--out", "-o",
        default=None,
        help="输出 prompt 文本路径",
    )
    args = parser.parse_args()

    # 生成文法树
    tree = generate(args.registry, mode=args.mode)

    print(f"[OK] generated tree: {tree.sections[1].content.total_intents} intents "
          f"in {len(tree.sections[1].content.groups)} groups, mode={tree.mode}")

    # 输出文法树 JSON
    if args.out_tree:
        import dataclasses

        class TreeEncoder(json.JSONEncoder):
            def default(self, obj):
                if dataclasses.is_dataclass(obj):
                    return dataclasses.asdict(obj)
                return super().default(obj)

        out_tree = Path(args.out_tree)
        out_tree.parent.mkdir(parents=True, exist_ok=True)
        with open(out_tree, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2, cls=TreeEncoder)
        print(f"[OK] tree JSON -> {out_tree}")

    # 序列化并输出 prompt 文本
    prompt_text = serialize(tree)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        print(f"[OK] prompt ({len(prompt_text)} chars) -> {out_path}")
    else:
        print(prompt_text)
