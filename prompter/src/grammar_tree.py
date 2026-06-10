"""
文法树数据模型
==============

L1 generator 的主产物是文法树(不是文本).
prompt 文本 = 文法树的序列化.

LLM enrich 阶段直接修改树的节点字段,不需要 parse 回文本.

节点类型:
  Prompt         - 根节点,包含 sections 列表
  Section        - 带标题的段落
  FixedText      - 叶子：固定文本
  Placeholder    - 叶子：运行时占位符 {conversation}
  IntentCatalog  - 意图库(所有 L1 分组)
  IntentGroup    - 一个 L1 分组(含 L2 意图列表 + 可选的 L1 说明)
  Intent         - 单个 L2 意图卡片
"""

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════
# enrich 槽位定义
# ═══════════════════════════════════════════════════════════

@dataclass
class EnrichSlot:
    """一个可选的 enrich 槽位规格."""
    key: str                          # 槽位键名,如 "keywords"
    label: str                        # 展示标签,如 "关键词"
    description: str                  # 说明(给 LLM 的 prompt 用)
    value_type: str                   # "list[str]" | "str"


ENRICH_SLOTS: dict[str, EnrichSlot] = {
    "keywords": EnrichSlot(
        key="keywords",
        label="关键词",
        description="用于意图匹配的关键词/短语,覆盖用户多样表达.每个关键词5-15字.",
        value_type="list[str]",
    ),
    "attention": EnrichSlot(
        key="attention",
        label="注意区分",
        description="容易与此意图混淆的其他意图及区分要点.每条包含'看起来像X但实际属于Y,区别在于Z'.",
        value_type="list[str]",
    ),
    "typical_ask": EnrichSlot(
        key="typical_ask",
        label="典型问法",
        description="用户表达此意图的典型/高频问法示例,每条是一个完整的用户问句.",
        value_type="list[str]",
    ),
    "negative_examples": EnrichSlot(
        key="negative_examples",
        label="边界反例",
        description="看起来像但实际不属于此意图的例子,标注正确归属.格式：'用户说\"...\" → 实际属于【X.X XXX】'",
        value_type="list[str]",
    ),
}


# ═══════════════════════════════════════════════════════════
# 节点类型
# ═══════════════════════════════════════════════════════════

@dataclass
class FixedText:
    """固定文本块."""
    text: str

    def __bool__(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Placeholder:
    """运行时占位符,如 {conversation}."""
    key: str


@dataclass
class Intent:
    """单个 L2 意图卡片.

    字段全部来自 xlsx(L0/L0.5),enriched 初始为空 dict.
    """
    display_id: str          # "1.1", "2.3", ...
    l1: str                  # 一级意图名称
    l2: str                  # 二级意图名称
    definition: str          # 场景定义
    faq_items: list[str]     # FAQ 列表(来自 clean.faq_items)
    sop: str                 # 澄清指引/SOP(原始文本)
    priority: str            # 优先级 P0/P1/P2
    company: str             # 对应子公司
    reply_design: str        # 回复设计
    notes: str               # 备注
    enriched: dict[str, Any] = field(default_factory=dict)

    @property
    def has_sop(self) -> bool:
        return bool(self.sop.strip())

    @property
    def call_tag(self) -> str:
        """生成统一调用标记 ###call(L1-L2)"""
        return f"###call({self.l1}-{self.l2})"


@dataclass
class IntentGroup:
    """一个 L1 分组,包含若干 L2 意图."""
    l1_name: str
    group_index: int         # 从 1 开始
    description: str = ""    # L1 说明文字(LLM enrich 目标,初始为空)
    intents: list[Intent] = field(default_factory=list)

    @property
    def intent_count(self) -> int:
        return len(self.intents)


@dataclass
class IntentCatalog:
    """意图库：所有 L1 分组."""
    groups: list[IntentGroup] = field(default_factory=list)

    @property
    def total_intents(self) -> int:
        return sum(g.intent_count for g in self.groups)


@dataclass
class Section:
    """一个 prompt 段落.

    content 可以是 FixedText / Placeholder / IntentCatalog,
    或者是它们的列表(用于一个段落内混合多种内容).
    """
    title: str                     # "##role##", "##意图库##", ...
    content: FixedText | Placeholder | IntentCatalog | list


@dataclass
class Prompt:
    """文法树的根节点.

    sections 是有序的段落列表,序列化时按顺序输出.
    """
    sections: list[Section] = field(default_factory=list)
    mode: str = "full"            # "full" | "classify_only"

    def section_by_title(self, title: str) -> Section | None:
        """按标题查找段落."""
        for s in self.sections:
            if s.title == title:
                return s
        return None

    def _find_content(self, cls):
        """在 sections 中查找第一个指定类型的 content."""
        for s in self.sections:
            if isinstance(s.content, cls):
                return s.content
        return None

    def _find_text(self, title: str) -> str:
        """查找指定标题的段落文本内容."""
        section = self.section_by_title(title)
        if section is None:
            return ""
        content = section.content
        if hasattr(content, "text"):
            return content.text
        return ""
