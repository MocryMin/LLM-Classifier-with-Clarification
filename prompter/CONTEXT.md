# Prompter Context — 当前状态与下一步工作

> 写于 2026-06-10, 上下文压缩前。
> 供下一会话快速恢复工作上下文。

## 已完成

### L0 + L0.5 + L1 Generator (确定性管道)

三层管道，无 LLM 参与：

```
xlsx → L0_xlsx2json → scene_table.json
                         ↓
                  L0.5_format_json → scene_table_clean.json (FAQ拆分/风险归一)
                                          ↓
                                   L1_generator → 文法树 → prompt.txt
```

### 文法树 (grammar_tree.py)

Generator 的主产物是 **文法树** (不是文本)。Prompt 文本 = 树的序列化。

节点类型:
- `Prompt` — 根，含 `sections` 列表 + `mode` 标记
- `Section` — 带标题的段落 (##role##, ##意图库##, ...)
- `FixedText` — 固定文本 (skeleton 中的内容已内嵌到 L1_generator.py)
- `Placeholder` — 运行时占位符 (`{conversation}`)
- `IntentCatalog` — 意图库，含 `IntentGroup` 列表
- `IntentGroup` — 一个 L1 分组 (description 字段预留为 enrich 目标)
- `Intent` — 单个 L2 意图卡片 (enriched dict 预留)

### Enrich 槽位系统 (ENRICH_SLOTS)

已定义 4 个可选 enrich 槽位，每个 Intent 都有 `enriched: dict` 字段:

| slot key | 中文标签 | 类型 | 用途 |
|----------|---------|------|------|
| `keywords` | 关键词 | `list[str]` | 扩充意图匹配关键词 |
| `attention` | 注意区分 | `list[str]` | 与其他意图的区分要点 |
| `typical_ask` | 典型问法 | `list[str]` | 高频用户问法示例 |
| `negative_examples` | 边界反例 | `list[str]` | 像但不属于此意图的例子 |

### 序列化规则 (serialize.py)

- 空字段不展示 (不会出现空 "SOP:" 行)
- enrich 槽位仅当 `enriched` 中对应 key 非空时才渲染
- `mode="classify_only"` 时隐藏所有 SOP 字段
- `IntentGroup.description` 为空时不展示

### 两种编译模式

| 模式 | SOP | L2澄清 | prompt 大小 |
|------|:---:|:-----:|------------|
| `full` | 显示 | 含 Step 3 | ~12.6K chars |
| `classify_only` | 隐藏 | 不含 | ~9.4K chars |

### Build 工具 (prompter/build.py)

运营团队一键工具:
- `python prompter/build.py` — 交互式
- `python prompter/build.py --xlsx <path> --mode full --deploy` — 命令行
- 输出到 `prompter/output/<xlsx名>/` (含 BUILD_REPORT.txt)
- `--deploy` 自动复制到 `v3/L1_router_v3.txt`

## 下一步: Enrich + 微调

### 设计思路 (已讨论，待实现)

**核心概念: LLM enrich 操作在文法树上进行，不操作文本。**

```
文法树 (Prompt)
    │
    ▼
enrich 阶段 (LLM 调用)
    │  修改特定节点:
    │  - tree.intent_catalog.groups[2].description  ← L1 分组说明文字
    │  - tree.intent_catalog.groups[1].intents[0].enriched.keywords
    │  - tree.sections[4].content (samples 扩充)
    │
    ▼
序列化 → 富化后的 prompt 文本
```

**关键设计原则:**
1. 每个 enrich 操作是 **一个独立 LLM 调用 + 有 schema 的小输出**
2. 不是让 LLM 重新生成整个 prompt
3. enriched 字段不覆盖原始 xlsx 数据 (cells 保持不变)
4. 清空 enriched 即回到确定性版本，可回滚

**Enrich 操作示例:**

```python
# 给每个 L1 分组生成一句话说明
enrich(
    target="intent_catalog.groups[2].description",
    context={
        "l1_name": "保单服务",
        "intents": [
            {"l2": "保单查询", "definition": "...", "company": "..."},
            ...
        ]
    },
    instruction="用一句话总结该组场景的共同路由特征",
)
# → 期望输出: "基于保单归属调用对应子公司智能客服。全部不需要澄清槽位，直接路由。"
```

**需要 enrich 的目标 (优先级排序):**

1. **IntentGroup.description** — 每个 L1 分组的说明文字 (当前为空，LLM 归纳生成)
2. **Intent.enriched.keywords** — 关键词扩充 (覆盖更多用户表达)
3. **Intent.enriched.attention** — 易混淆意图的区分要点
4. **Intent.enriched.typical_ask** — 典型问法补充
5. **Intent.enriched.negative_examples** — 边界反例
6. **Samples 扩充** — LLM 从 xlsx 数据自动生成 few-shot 示例

### 微调上下文

用户的原始想法:
> "当我们根据 skeleton generate prompt 的时候，我们采用文法产生... 在后续 LLM 微调的时，微调应该是局部微调... 如何让在后续微调操作中操作这些细节的地方？是否需要在微调前进行一次真正的编译？将中间 prompt 转为由元素和素材结构的文法树？然后微调的修改对象是其中一个元素？"

**结论: 文法树已是主产物，不需要 parse 回来。** Generator 产出文法树 → LLM enrich 直接修改树节点 → serialize 输出富化后的 prompt。

### 文件位置

```
prompter/
├── build.py              ← 一键编译工具
├── CONTEXT.md            ← 本文件
├── src/
│   ├── L0_xlsx2json.py
│   ├── L0.5_format_json.py
│   ├── L1_generator.py   ← 确定性 generator (不含 enrich)
│   ├── grammar_tree.py   ← 文法树数据模型 + ENRICH_SLOTS 定义
│   └── serialize.py      ← 树 → prompt 序列化
├── xlsx/                 ← 运营团队放置 xlsx 的位置
└── output/               ← 构建产物 (gitignored)
```

### V3 运行时 (已独立部署)

```
v3/
├── __init__.py
├── entrance.py           ← V3 单阶段入口
├── L1_router.py          ← 加载 prompt + 调 LLM
└── L1_router_v3.txt      ← 生成的 V3 prompt (build.py --deploy 更新)
```

### Server 端点

- `/api/chat` — V2 (不变)
- `/api/chat/v3` — V3 单阶段 L1 (新增)

### 关键约束

- V2 代码 (`src/`) 完全不动
- V3 代码 (`v3/`) 独立运行
- GUI 通过 `useV3` 开关在两种模式间切换
- 当前分支: `v3-dev`
