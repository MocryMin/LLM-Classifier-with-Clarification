# V2 智能管家 — 管道式重构设计

> 基于 V1 (`智能管家_场景设计需求0528.xlsx`) → V2 (`超级智能管家方案设计0604.xlsx`) 的进化设计
> 
> 日期: 2026-06-05 | 分支: `v2-dev` | 状态: 设计完成，待审核

---

## 一、V1→V2 变更概要

### 1.1 架构变化

| V1 | V2 |
|----|----|
| 两段式（L0→L1） | **三段式**（意图澄清 → 风险评估 → 分级回复） |
| L0 统一拦截（任一超阈值→case=0） | L0 **差异化处置**（5个tag各自独立处置路径） |
| L1 统一LLM生成回复 | 回复分**三级**：低=生成式，中=FAQ优先+人工审核，高=FAQ+纯人工 |

### 1.2 场景变化

- V1: 30个场景（6大类）
- V2: **32个场景**（6大类）
- 新增: **核保**(2.8)、**核赔**(2.9)，均在售前服务下，均标记高风险
- 30个共有场景的定义、FAQ、澄清指引/SOP、子公司归属**无变化**
- 全部32场景新增**风险等级**列（低8/中15/高9）

### 1.3 跨场景标记变化

| Tag | V1 处置 | V2 处置 | 风险影响 |
|-----|---------|---------|----------|
| manual | 拦截→升级 | 立即转人工，不继续澄清 | 直接升级高风险 |
| angry | 拦截→升级 | 跳过澄清，转人工 | 风险+1（低→中，中→高） |
| urgent | 拦截→升级 | 跳过澄清+风险评估，直接操作指引 | 跳过风险检验 |
| sad | 拦截→升级 | 语气温和安抚，不打断流程 | 不影响风险等级 |
| non_biz | 拦截→升级 | 礼貌引导回业务 | 不影响风险等级 |

### 1.4 子公司归属变化

新增3条单一子公司映射（全部→产险）：
- 宠物/家财/房屋等财产保险
- 旅行险
- 雇主责任/熊孩子责任等责任险

### 1.5 地区合规简化

V1的4模式(A/B/C/D) → V2简化为风险等级+地区叠加：
- 试点地区：按风险等级正常分流
- 非试点地区：在风险等级基础上加强审核
- 非试点+高风险：**禁止LLM参与任何生成**，仅FAQ+人工

### 1.6 个性化推荐（新增）

- **进线推荐**：用户进入对话前，基于客户画像推送入口卡片（独立API，本期占位）
- **问答后推荐**：意图+槽位确认后，附加产品推荐卡片（本期占位）

---

## 二、管道架构

### 2.1 文件结构

```
src/
├── entrance.py              # 重构：管道编排器（~250行）
├── L0_tag_judge.py          # 修改：增加tag_disposition映射（原~600行，小幅修改）
├── L1_purpose.py            # 修改：prompt增强+few-shot（原~290行，小幅修改）
├── L2_risk_assess.py        # 新增：风险评估规则引擎（~200行）
├── L3_response_dispatch.py  # 新增：三级回复分派器（~150行）
└── pipeline_types.py        # 新增：阶段间数据结构（~80行）

prompt/
├── L1_intent_router.txt     # 修改：增强约束+few-shot+核保/核赔+子公司归属
├── tag_*.txt                # 不变
└── escalation.txt           # 修改：适配新tag处置路径

test/
├── test_risk_assess.py      # 新增：风险评估单元测试
└── test_dispatch.py         # 新增：回复分派单元测试
```

### 2.2 管道流程

```
messages
    │
    ▼
┌─────────────────────────────────────────────────┐
│  entrance(messages, l0_threshold=0.7, debug)     │
│                                                   │
│  ┌──────────────────┐  ┌──────────────────────┐  │
│  │ Stage 0: L0       │  │ Stage 1: L1           │  │
│  │ tag_judge_v2()    │  │ purpose_route()       │  │
│  │ → L0Output        │  │ → L1Output            │  │
│  └───────┬──────────┘  └──────────┬───────────┘  │
│          │ (并行，L0通常先返回)      │              │
│          └──────────┬──────────────┘              │
│                     ▼                              │
│          ┌──────────────────────┐                 │
│          │ Stage 2: Risk Assess │                 │
│          │ assess_risk()        │                 │
│          │ → RiskOutput         │                 │
│          └──────────┬──────────┘                 │
│                     ▼                              │
│          ┌──────────────────────┐                 │
│          │ Stage 3: Response    │                 │
│          │ dispatch_by_risk()   │                 │
│          │ → DispatchResult     │                 │
│          └──────────┬──────────┘                 │
│                     ▼                              │
│              return PipelineResult                 │
└─────────────────────────────────────────────────┘
```

### 2.3 entrance 返回结构（向后兼容）

```python
# case=0: L0拦截 → 升级处置（同V1，扩展tag_dispositions）
{
    "case": 0,
    "risk_level": "high",        # 新增
    "response_mode": "faq_only_human",  # 新增
    "tag_dispositions": {...},
    "data": {
        "call_body": "###tool_call(human_intervention_api)",
        "situation_brief": "...",
        "user_comfort": "...",
        "l0_tags": {"manual": 1.0, ...}
    }
}

# case=1: 正常路由 → L1 意图路由 + 风险评估 + 分级回复
{
    "case": 1,
    "risk_level": "medium",      # 新增
    "response_mode": "faq_first", # 新增
    "tag_dispositions": {...},    # 新增
    "decision_trail": [...],      # 新增：风险评估决策链
    "data": {
        # 同V1 L1 result +
        "primary_intent": {...},
        "slots": {...},
        "operation": {...},
        "user_output": "...",     # Stage 3处理后的最终输出
        "reason": "...",
        "faq_matched": false,     # 新增
        "audit_required": false,  # 新增
        "recommendation": null,   # 新增（占位）
    }
}

# case=2: 紧急直通（新增）→ 跳过澄清+风险评估，直接操作指引
{
    "case": 2,
    "risk_level": null,           # 跳过评估，无等级
    "response_mode": "direct_guide",
    "tag_dispositions": {...},
    "data": {
        "user_output": "请立即拨打95500...",  # 直接操作指引
        "escalate_to_human": true,
        "primary_intent": {...},  # L1的意图结果（如有）
    }
}
```

---

## 三、Stage 0: L0 Tag处置差异化

### 3.1 数据结构

```python
# pipeline_types.py

@dataclass
class TagResult:
    tag_type: str            # "manual" | "angry" | "urgent" | "sad" | "non_biz"
    probability: float       # 原始概率值 [0,1]
    triggered: bool          # 是否超过阈值
    action: str              # 处置动作
    risk_modifier: int       # 风险等级调整量
    skip_clarification: bool # 是否跳过澄清轮次

@dataclass
class L0Output:
    tags: dict[str, TagResult]
    should_escalate: bool    # → case=0
    should_skip_risk: bool   # → case=2
```

### 3.2 Tag处置规则表

| Tag | 触发条件 | action | risk_modifier | skip_clarify | 副作用 |
|-----|---------|--------|:---:|:---:|------|
| manual | prob ≥ threshold | `escalate` | 直接high | Yes | case=0 |
| angry | prob ≥ threshold | `risk_bump` | +1 | Yes | 转人工 |
| urgent | prob ≥ threshold | `skip_risk` | 0 | Yes | case=2 |
| sad | prob ≥ threshold | `tone_soften` | 0 | No | 语气调整 |
| non_biz | prob ≥ threshold | `redirect` | 0 | No | 引导回业务 |

### 3.3 优先级

```
manual > urgent > angry > sad > non_biz
```

高优先级tag触发时覆盖低优先级。多tag同时触发取最高优先级处置。

---

## 四、Stage 1: L1 Prompt增强

### 4.1 Prompt变更清单

| # | 位置 | 变更 |
|---|------|------|
| 1 | 行2 | "30个" → "32个" |
| 2 | 行33 | "售前服务（7个场景）" → "（10个场景）" |
| 3 | 产品咨询(2.1)末尾 | 增加核保/核赔区分提示 |
| 4 | 承保后新增 | **意图2.8 核保**（含定义/关键词/区分规则/槽位/操作规则） |
| 5 | 承保后新增 | **意图2.9 核赔**（含定义/关键词/区分规则/槽位/操作规则） |
| 6 | tool_call列表 | +`underwriting_api`、+`claim_assess_api` |
| 7 | tool_call输出规则 | +核保/核赔不生成LLM回复文本 |
| 8 | 判断规则 | +规则7(投保vs核保)、+规则8(报案vs核赔) |
| 9 | 子公司归属 | +宠物/家财/旅行/责任险→产险（3条） |
| 10 | 槽位填写规则 | 增加推理豁免规则 |
| 11 | 输出格式前 | **反臆想约束段**（产品信息/知识边界/输出自检） |
| 12 | 输出格式前 | **3-5个few-shot示例** |

### 4.2 新增场景定义

**意图2.8 核保**
- 定义：用户基于个人信息咨询是否能承保、保费试算。尚未明确投保意向。
- 关键词：能保吗, 核保, 能不能承保, 保费多少, 试算
- 区分：有投保意向→2.2-2.6；承保能力疑问→2.8
- 操作：高风险，集团通用指引→具体结论 ###tool_call(underwriting_api)
- 槽位：核保险种、核保关键信息、用户诉求

**意图2.9 核赔**
- 定义：咨询假设性赔付场景（"假如XX能赔吗"），用户未出险。
- 关键词：能赔吗, 赔不赔, 赔付范围, 能不能报销
- 区分：已出险→4.1；假设性→2.9；流程咨询→4.3
- 操作：高风险，集团通用原则→具体结论 ###tool_call(claim_assess_api)
- 槽位：核赔险种、核赔场景描述、用户诉求

### 4.3 反臆想约束

在输出格式前增加约20行的严格约束段，覆盖：
- 产品信息约束（prompt为唯一合法来源）
- 知识边界约束（系统是路由系统，非顾问系统）
- 输出自检清单（4项检查）

### 4.4 Few-Shot示例

选取5个关键边界情况标注正确/错误输出：
1. 本人推论（防蠢）："我35岁想买医疗险" → 被保人=本人
2. 反臆想（防编造）：不可自创产品描述
3. 多意图处理：退保+购买 → 先确认优先级
4. 投保vs核保区分："我能买吗" → 核保
5. 报案vs核赔区分："万一撞了能赔吗" → 核赔

### 4.5 槽位推理豁免规则

```
以下情况应直接推理填充，不应追问用户：
a. 被保人关系=本人：用户以第一人称描述自身情况，未指定其他人时
b. 单对象推论：用户只提及一人且信息完整
c. 保障需求明确：用户已指定险种且该险种仅一种保障方向
每次澄清不超过2个问题
```

---

## 五、Stage 2: 风险评估规则引擎

### 5.1 模块设计

`src/L2_risk_assess.py` — 纯Python规则引擎，零LLM调用。

```python
def assess_risk(l0: L0Output, l1: L1Output, messages: list[dict],
                debug: bool = False) -> RiskOutput:
    """
    基于场景+情绪+合规的综合风险评估。
    
    规则链架构：终止型规则在前（命中即停止），累加型规则在后。
    每一步决策记录在 decision_trail 中，支持完整审计。
    """
```

### 5.2 32场景基础风险映射

**低风险（8个）：**
欢迎引导、意图澄清、未覆盖兜底、产品咨询、服务介绍、行权使用、高频权益、客服热线

**中风险（15个）：**
健康险投保、车险投保、寿险/年金投保、意外险投保、其他险种投保、明确产品、承保/保单获取、保单查询、续期缴费、保单变更、理赔报案、理赔进度查询、权益查询、业务员联系、网点查询

**高风险（9个）：**
核保、核赔、退保/减保、保单贷款/还款、分红/年金/领取、保单复效、理赔材料/条件、撤销报案、投诉建议

### 5.3 规则链

```python
# 规则统一签名
RiskRule = Callable[[L0Output, L1Output, list[dict]], Optional[RiskDecision]]

RISK_RULES = [
    ("manual_override",   rule_manual_override,  True),   # 终止型
    ("urgent_skip",       rule_urgent_skip,       True),   # 终止型
    ("scene_base",        rule_scene_base,        False),  # 累加型
    ("angry_bump",        rule_angry_bump,        False),  # 累加型
    ("compliance_scan",   rule_compliance_scan,   False),  # 累加型
]
```

### 5.4 评分逻辑

```
base_score = {low:0, medium:1, high:2}[场景基础风险]
+ angry触发 → +1
+ 合规关键词命中 → 每个类别+1 (监管投诉/媒体曝光/资金安全/法律风险)

total_score → risk_level:
  0 → low
  1 → medium
  ≥2 → high

manual触发 → 直接 high（不经过计分）
urgent触发 → 跳过本模块（entrance层处理）
```

### 5.5 可调试性

```python
@dataclass
class RiskDecision:
    step: str           # 规则名
    input_value: str    # 触发值
    result: str         # 决策结果
    reason: str         # 理由

@dataclass
class RiskOutput:
    risk_level: str              # "low" | "medium" | "high" | None
    response_mode: str           # 对应回复模式
    score_detail: dict           # {base: 1, angry: +1, ...} → total
    decision_trail: list[RiskDecision]  # 完整决策链
    triggered_rules: list[str]   # 触发规则名列表

# debug=True 时自动打印决策链
def _print_trail(trail, score, risk):
    print("[RiskEngine] === 决策链 ===")
    for i, d in enumerate(trail):
        print(f"  {i+1}. [{d.step}] {d.input_value} → {d.result}  ({d.reason})")
    print(f"[RiskEngine] 总分={score} → 风险={risk}")
```

每条规则独立函数——可单独测试、单独开关、单独调试。

---

## 六、Stage 3: 分级回复分派

### 6.1 模块设计

`src/L3_response_dispatch.py`

```python
@dataclass
class DispatchResult:
    response_mode: str         # "generative" | "faq_first" | "faq_only_human" | "direct_guide"
    user_output: str           # 最终对客文本
    tool_calls: list[str]      # ###tool_call(xxx) 列表
    faq_matched: bool          # FAQ是否命中
    recommendation: dict | None  # 问答后推荐（占位）
    audit_required: bool       # 是否需要人工审核
    escalate_to_human: bool    # 是否转人工

def dispatch_by_risk(l0: L0Output, l1: L1Output, risk: RiskOutput,
                     region: str = "non_pilot") -> DispatchResult:
```

### 6.2 三级响应逻辑

```
manual触发        → escalate_to_human()          case=0
urgent触发        → direct_guidance()             case=2
risk == "low"     → generative_reply()            LLM直出
risk == "medium"  → faq_first_reply()             FAQ优先
risk == "high"    → faq_only_human()              仅FAQ+人工
```

### 6.3 各模式详情

**generative_reply (低风险):**
- 试点地区：直接使用L1的user_output
- 非试点地区：LLM输出→智能审核→通过/降级到中风险通道
- 智能审核规则（纯代码，无LLM）：
  1. 产品名白名单校验：user_output中出现的产品名是否都在prompt定义的合法集合中
  2. 槽位选项校验：澄清选项是否与prompt定义的options一致（options非空时）
  3. 敏感词扫描：是否包含监管/投诉/媒体/资金安全等高风险词
  4. 任一不通过 → 降级到中风险通道（faq_first）

**faq_first_reply (中风险):**
- 通道1（默认）：查询FAQ → 命中→直接推送预审核卡片
- 通道2（兜底）：FAQ无匹配 → LLM生成 + 标记需人工审核
- FAQ接口当前模拟，始终返回None

**faq_only_human (高风险):**
- 不调用LLM生成任何文本
- 推送标准口径 + 创建人工工单
- 服务时间外：FAQ + 留言工单

**direct_guidance (紧急):**
- 跳过风险评估和澄清
- 根据场景类型直接推送操作指引
- 道路救援→救援电话；理赔→报案入口

### 6.4 地区判定

```python
PILOT_REGIONS = {"广州", "苏州"}

def get_region(request_context) -> str:
    """当前迭代：硬编码试点列表，后续对接IP/手机号归属地服务"""
    return request_context.get("region", "non_pilot")
```

### 6.5 FAQ模拟接口

```python
def query_faq(l1: L1Output) -> dict | None:
    """
    模拟FAQ查询。FAQ库为空，始终返回None。
    后续FAQ团队交付后替换实现。
    
    约定接口:
      输入: L1Output (primary_intent.l2, slots.filled_slots)
      输出: {"content": "...", "card_id": "..."} | None
    """
    return None
```

### 6.6 推荐占位

- 进线推荐：独立API `GET /api/recommendations/entry` → `{"items": []}`
- 问答后推荐：DispatchResult.recommendation 字段预留，当前始终为None

### 6.7 升级处置适配

V1的升级处置（escalation）在V2中触发条件变化：
- V1：任一tag超阈值 → escalation
- V2：仅 **manual** 和 **angry** 触发转人工；**urgent** 走 direct_guidance 而非 escalation

`prompt/escalation.txt` 适配：
- 模板入参增加 `triggered_tags` 的类型信息（不仅是概率值，还有触发的是哪种tag）
- situation_brief 中根据tag类型调整披露内容：manual→用户主动求转人工；angry→情绪触发转人工
- user_comfort 安抚话术根据tag类型差异：manual→"已为您转接"；angry→"非常抱歉给您带来不好的体验"

---

## 七、错误处理与降级

### 7.1 逐层降级

```
Stage 0 失败 → 全0.0 safe L0，不触发任何tag → 流入Stage 1
Stage 1 失败 → fallback result (operation=clarify_L1) → 流入Stage 2
Stage 2 失败 → 默认medium + faq_first → 流入Stage 3
Stage 3 失败 → 直接使用L1.user_output
```

每层独立兜底，单层失败不中断管道。

### 7.2 超时控制

```python
future_l0.result(timeout=30)   # flash模型，30s足够
future_l1.result(timeout=60)   # pro模型，60s足够
```

### 7.3 安全侧原则

任何不确定情况→保守处理：
- 未知场景 → 默认为中风险
- 非试点地区 → 加严审核
- JSON解析失败 → fallback + clarify_L1

---

## 八、测试策略

### 8.1 单元测试（无需LLM，毫秒级）

| 测试文件 | 用例数 | 覆盖重点 |
|----------|--------|----------|
| test_risk_assess.py | ~15 | 32场景查表、tag修饰叠加、合规关键词、边界组合、决策链完整性 |
| test_dispatch.py | ~12 | 三级分流路径、紧急直通、地区判定、FAQ降级、推荐占位 |
| test_pipeline_types.py | ~5 | 数据结构构造、序列化、默认值 |

### 8.2 集成测试（需LLM，按需运行）

保留V1的3个entrance测试用例，新增5个V2关键路径：

| 场景 | 期望 |
|------|------|
| "我35岁想买医疗险" | case=1, risk=medium, 被保人关系="本人" |
| "转人工！说了三遍了！" | case=0, manual.triggered=True |
| "高速上撞车了快帮我！" | case=2, response_mode=direct_guide |
| "你们太烂了我要曝光" | angry触发, risk升一级 |
| "我有癌症能买保险吗" | scene=核保, risk=high, mode=faq_only_human |

利用现有的 Chat Playground（`localhost:5173`）进行人工验证。

### 8.3 Prompt回归测试

每次修改L1 prompt后，用固定测试用例集跑entrance，对比输出结构确保无退化。

---

## 九、迁移方案

### 9.1 Git分支策略

```
ReferenceV1/
  main (V1稳定版，不动)
    │
    └── git checkout -b v2-dev     ← V2开发分支
         │
         ├── 不改动的文件:
         │     prompt/tag_*.txt
         │     server/* (conversation_manager, workspace_manager, parsers)
         │     web/* (GUI层)
         │
         ├── 修改的文件:
         │     src/entrance.py              → 管道编排重写
         │     src/L1_purpose.py            → prompt增强
         │     src/L0_tag_judge.py          → 增加tag_disposition映射
         │     prompt/L1_intent_router.txt  → 增强+新场景
         │     prompt/escalation.txt        → 适配新tag路径
         │
         └── 新增的文件:
               src/L2_risk_assess.py
               src/L3_response_dispatch.py
               src/pipeline_types.py
               test/test_risk_assess.py
               test/test_dispatch.py
```

### 9.2 防退化措施

- entrance函数签名不变：`entrance(messages, l0_threshold=0.7, debug=False)`
- 返回结构 `case` 字段保留，GUI无需改动
- L0核心SC并行架构不变
- L1核心 `_ask`/`_try_parse_json` 不变
- 每模块独立commit，改动范围清晰

---

## 十、实现顺序

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 1 | `pipeline_types.py` — 数据结构定义 | 无 |
| 2 | `L2_risk_assess.py` — 风险评估 + `test_risk_assess.py` | 阶段1 |
| 3 | `L3_response_dispatch.py` — 回复分派 + `test_dispatch.py` | 阶段1 |
| 4 | `L0_tag_judge.py` — 增加tag_disposition映射 | 阶段1 |
| 5 | `L1_intent_router.txt` — prompt增强 | 无 |
| 6 | `L1_purpose.py` — 适配新prompt | 阶段5 |
| 7 | `entrance.py` — 管道编排重写 | 阶段2,3,4,6 |
| 8 | 集成测试 + Chat Playground验证 | 阶段7 |
