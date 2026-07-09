# V4 -- 两阶段渐进式注入意图路由

智能客服场景下的保险意图分类器。接口与 V3 完全一致（一个入口，输入消息，输出标签），内核换成**两阶段渐进式加载（Progressive Disclosure）**：先用低成本模型 + 类别摘要做粗筛召回，再对少量候选注入完整描述做精排。

---

## 一、面向使用者

### 1.1 它做什么

输入一段客服对话（OpenAI 消息格式），输出一个意图标签（一级分组 + 二级意图）及路由决策，返回结构与 V3 一致，可直接替换 V3 的 `entrance`。

### 1.2 安装

```bash
pip install -r v4/requirements.txt   # 仅依赖 openai
```

### 1.3 配置 API Key（**必须用自己的 key，本仓库不含任何内置 key**）

任选其一：

```bash
# 方式 A：环境变量
export DEEPSEEK_API_KEY=sk-你的key        # Linux/Mac
set DEEPSEEK_API_KEY=sk-你的key           # Windows cmd
```

```python
# 方式 B：调用时传入
entrance(messages, api_key="sk-你的key")
```

获取 key：https://platform.deepseek.com/api_keys

### 1.4 调用

```python
from v4.entrance import entrance

messages = [
    {"role": "user", "content": "我想查一下我的保单"},
]
result = entrance(messages, debug=True)
```

**返回**（与 V3 同构）：

```json
{
  "case": 1,
  "risk_level": null,
  "response_mode": "v4",
  "tag_dispositions": {},
  "decision_trail": [],
  "data": {
    "primary_intent": {"l1": "保单服务", "l2": "保单查询", "confidence": 0.95},
    "top_candidates": [{"l1": "...", "l2": "...", "probability": 0.08}],
    "needs_clarification": false,
    "user_output": "正在为您查询保单信息...\n###call(保单服务-保单查询)",
    "reason": "用户明确表达查询保单意图..."
  }
}
```

- `primary_intent.l1` / `l2`：一级分组 / 二级意图（即标签）
- `needs_clarification`：是否需澄清
- `user_output`：路由时为 `衔接词 + ###call(l1-l2)`；澄清时为澄清话术

### 1.5 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `model` | `deepseek-v4-flash` | 两层均用 Flash（性价比最优；可换 `deepseek-v4-pro`） |
| `k` | `5` | Layer_1 召回的 top-k |
| `thinking` | `disabled` | 分类任务关 thinking 省时延；开 `enabled` 推理更细但更贵更慢 |
| `prompt_file` | 包内 `prompt.txt` | V3 prompter 产物；更新分类方案后替换此文件即可 |

### 1.6 更新分类方案

`prompt.txt` 由 **V3 的 prompter**（`prompter/build.py`，不在本仓库）从场景设计 xlsx 编译生成。更新方案时：在 V3 侧用 prompter 重新编译并 `--deploy`，把生成的新 `prompt.txt` 拷贝到本目录覆盖即可，V4 内核会自动重新解析全部类别与辅助信息。

---

## 二、技术方法与结果

### 2.1 问题

V3 单阶段方案把 32 类的完整描述（定义 + FAQ + SOP + 回复设计）一次性注入 Prompt，交由 Pro 模型判别。准确率高，但 Prompt 约 7300 token，带来高 API 成本与长 TTFT 时延，实时客服场景不可接受。直接换小模型则准确率大幅下降。

### 2.2 方法：两阶段渐进式注入

将一次 32 分类拆成两层：

```
对话 x
  │
  ▼
Layer_1（粗筛）：Flash + 32 类「名称+定义」摘要  ──►  top-k 候选 Y_L1
  │
  ▼
Layer_2（精排）：Flash + k 候选的「完整描述」+ V3 路由规则/约束/示例/输出格式
  │                                                 ──►  top-1 标签 + 路由决策
  ▼
V3 同构 JSON 输出
```

- **Layer_1** 只注入每类的「名称+定义」一行摘要（而非完整描述），让 Flash 输出 top-k。Prompt 从 ~7300 token 降到 ~3170 token。
- **Layer_2** 只把 top-k 候选的**完整描述**注入（而非全部 32 类），并原样复用 V3 的路由规则、约束、示例、输出格式，让 Flash 从候选中选出唯一最佳并产出与 V3 同格式的路由决策。Prompt ~1960 token。
- 选择限定在候选内：Layer_1 没召回的样本不可救，故 Layer_1 recall@k 是系统天花板。

类别定义与辅助信息全部从 V3 prompter 生成的 `prompt.txt` 解析（`prompt_parser.py`），不重复维护类别源。

### 2.3 关键设计选择（实验验证）

| 维度 | 选择 | 依据 |
|---|---|---|
| 模型 | 两层均 Flash | Pro 仅比 Flash 高 1.07pp，却贵约 7× |
| k | 5 | k=10 抬高天花板但精排精度同比例下降，净收益为 0 |
| Layer_2 上下文 | 仅 k 候选完整描述 | 额外注入其余 27 类「名称+定义」对 Flash 为负收益（-0.58pp） |
| thinking | disabled | 分类任务够用，显著降本降时延 |

### 2.4 结果

在 6259 条 Gold+Silver 测试集（baoguv4/lora_dataset）上：

| 指标 | Gold | Silver |
|---|---|---|
| Layer_1 recall@5（天花板） | 99.7% | 74.1% |
| **Layer_2 top-1（系统准确率）** | **95.4%** | **58.4%** |

- **公平对照**：Silver 上两阶段 Flash（58.4%）较 V3 单阶段 Flash（45.7%）提升 **+12.7pp**，是评测集中唯一的非循环公平对照（Gold/Silver 标签由 Pro Judger 参与投票，V3-Pro 在其上按构造为 100%，不能作公平基线）。
- **成本**：两阶段总输入 5130 token（2×Flash）< V3 单阶段 7265 token（1×Pro），叠加 Flash 相对 Pro 的单价优势，约为 V3-Pro 成本的 **10%**；单次 Prompt 大幅缩短利于降低 TTFT。
- **残余瓶颈**：Silver 上的主要拖累是【意图1.1】欢迎引导边界（Pro 判开场、Flash 判业务，根本分歧），需 few-shot 或对比学习 negative sample 解决。

### 2.5 目录结构

```
.
├── README.md            # 本文件（分层说明）
└── v4/
    ├── entrance.py        # 入口：entrance(messages) -> V3 同构 dict
    ├── kernel.py          # 两阶段内核：Layer_1 粗筛 + Layer_2 精排
    ├── prompt_parser.py   # 解析 prompt.txt -> 32 类 + 辅助信息
    ├── llm.py             # DeepSeek 客户端（用户提供自己的 key，无内置 key）
    ├── prompt.txt         # V3 prompter 产物（类别定义 + 规则，更新方案时替换）
    ├── requirements.txt   # openai
    └── .env.example       # DEEPSEEK_API_KEY 模板
```

### 2.6 与 V3 的关系

接口完全一致（`entrance(messages) -> dict`），可直接替换。差异仅在内核：V3 单阶段全量 Prompt + Pro；V4 两阶段渐进式注入 + Flash。类别源（prompt.txt）与 prompter 仍由 V3 维护，V4 只提供内核。
