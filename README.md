# 智能管家 · Chat Playground (V3-dev)

基于 LLM 的保险智能客服意图路由系统，附带 Web 对话测试工作台。支持 V2（四阶段管道）和 V3（单阶段路由）双模式。

> **当前分支:** `v3-dev` (V3 意图路由 — 单阶段)  
> **V2 分支:** `v2-dev` (V2 管道式 — 四阶段 L0∥L1→L2→L3)  
> **稳定版:** `main` (V1 两段式架构)  

## V2 vs V3 对比

| 维度 | V2 (`v2-dev`) | V3 (`v3-dev`) |
|------|---------------|---------------|
| 架构 | 四阶段 L0∥L1→L2→L3 | **单阶段** L1 only |
| L0 标签检测 | 5 标签 (manual/angry/urgent/sad/non_biz) | 无 |
| 意图分类 | 32 场景 + 槽位收集 | 32 场景, 不收集槽位 |
| 澄清 | 槽位澄清 (L1 收集) | L1 意图竞争 + L2 SOP 驱动 |
| 调用格式 | `###tool_call(28个具名API)` | `###call(L1-L2)` |
| 风险评估 | 规则引擎 (场景+情绪+合规) | 无 |
| 回复分派 | 三级 (generative/faq_first/human) | 路由直出 |
| LLM 调用 | L0: ~22 flash, L1: ~2 pro | L1: ~1 pro |
| prompt 生成 | 手工维护 | **确定性管道** (xlsx→json→prompt) |

## V2 架构

```
                         ┌──────────────────────────┐
                         │     Chat Playground       │
                         │   React + TypeScript      │
                         │   localhost:5173           │
                         └────────────┬─────────────┘
                                      │ HTTP + SSE
                         ┌────────────▼─────────────┐
                         │        FastAPI             │
                         │   server/main.py           │
                         │   localhost:8000           │
                         └────────────┬─────────────┘
                                      │ Python import
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌──────────────────┐   ┌──────────────────────────┐   ┌──────────────────┐
│ Stage 0: L0 标签  │   │ Stage 1: L1 意图路由       │   │ Stage 2+3: 风控   │
│ 5 tags × SC      │   │ 32 场景分类 + 槽位提取     │   │ 风险引擎 + 分派   │
│ ~22 flash 调用    │   │ ~2 pro 调用                │   │ 0 LLM 调用        │
└──────────────────┘   └──────────────────────────┘   └──────────────────┘
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      │
                              ┌───────▼───────┐
                              │  Pipeline      │
                              │  case=0/1/2    │
                              │  + risk_level  │
                              │  + response_mode│
                              └───────────────┘
```

### V1 → V2 核心变更

| 维度 | V1 (`main`) | V2 (`v2-dev`) |
|------|-------------|---------------|
| 架构 | 两段式 L0→L1 | **四阶段管道** L0∥L1→风险评估→分级回复 |
| L0 处置 | 统一拦截 | **差异化** (manual→升级/angry→提风险/urgent→直通/sad→调语气/non_biz→引导) |
| 场景数 | 30 | **32** (新增: 核保/核赔) |
| 风险评估 | 无 | **规则引擎** (场景+情绪+合规 → 低/中/高) |
| 回复策略 | 统一 LLM 生成 | **三级**: 低=生成式, 中=FAQ优先, 高=FAQ+人工 |
| 返回 | case=0/1 | case=0/1/**2**, +risk_level, +response_mode, +decision_trail |
| 地区合规 | 4 模式 A/B/C/D | 风险等级叠加, 非试点高风险禁 LLM |
| 子公司 | 产险/寿险 | 扩展: 宠物/家财/旅行/责任险→产险 |
| 推荐 | 无 | 进线推荐 + 问答后推荐 (本期占位) |

## V3 架构

```
                          ┌──────────────────────────┐
                          │     Chat Playground       │
                          │   React + TypeScript      │
                          │   localhost:5173           │
                          └────────────┬─────────────┘
                                       │ HTTP + SSE
                          ┌────────────▼─────────────┐
                          │        FastAPI             │
                          │   server/main.py           │
                          │   /api/chat  (V2)          │
                          │   /api/chat/v3 (V3)        │
                          └────────────┬─────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │ V2                     │                        │ V3
              ▼                        │                        ▼
    ┌──────────────────┐               │             ┌──────────────────┐
    │ src/entrance.py   │               │             │ v3/entrance.py   │
    │ L0→L1→L2→L3      │               │             │ L1 only          │
    └──────────────────┘               │             └────────┬─────────┘
                                       │                      │
                                       │             ┌────────▼─────────┐
                                       │             │ v3/L1_router.py   │
                                       │             │ V3 prompt + LLM   │
                                       │             └────────┬─────────┘
                                       │                      │
                                       │             ┌────────▼─────────┐
                                       │             │ prompter/         │
                                       │             │ xlsx→json→prompt  │
                                       │             │ (离线生成)        │
                                       │             └──────────────────┘
```

### V3 Prompt 生成管道 (prompter/)

```
xlsx (场景设计表) → L0_xlsx2json → scene_table.json
                                      ↓
                               L0.5_format_json → scene_table_clean.json
                                                      ↓
                                              L1_generator → 文法树 → prompt.txt
                                              (两种模式: full / classify_only)
```

### V3 两种模式

| 模式 | 用法 | SOP 字段 | L2 澄清 | prompt 大小 |
|------|------|:--------:|:-------:|------------|
| `full` | 常规路由 | 显示 | 含 Step 3 | ~12.6K chars |
| `classify_only` | 仅分类+L1澄清 | 隐藏 | 不含 | ~9.4K chars |

```bash
# 生成 V3 prompt
cd prompter/src
python L1_generator.py ../temp/0604/scene_table_clean.json --mode full --out prompt.txt
python L1_generator.py ../temp/0604/scene_table_clean.json --mode classify_only --out prompt_classify.txt

# 重新生成 (xlsx 变更后)
python L0_xlsx2json.py <xlsx路径> --out scene_table.json
python L0.5_format_json.py scene_table.json --out scene_table_clean.json
python L1_generator.py scene_table_clean.json --out ../../v3/L1_router_v3.txt
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+

### 一键启动

双击 `start.bat`，自动安装依赖、启动后端和前端、打开浏览器。

### 手动启动

```bash
# 安装后端依赖
cd server
pip install -r requirements.txt

# 启动后端 (Terminal 1)
python main.py

# 安装前端依赖 (Terminal 2)
cd web
npm install

# 启动前端
npm run dev
```

浏览器打开 http://localhost:5173

**切换 V2/V3:** 在顶部工具栏勾选 `V3` 复选框。勾选后走 `/api/chat/v3` (单阶段 L1)，取消勾选走 `/api/chat` (V2 四阶段管道)。V3 模式下 L0 阈值滑块自动隐藏。

## 项目结构

```
baogu/
├── src/                            # V2 智能管家核心 (不变)
│   ├── entrance.py                 # V2 管道编排器 (唯一对外接口)
│   ├── pipeline_types.py           # 阶段间数据结构
│   ├── L0_tag_judge.py             # L0 跨场景标记检测
│   ├── L1_purpose.py               # L1 意图路由 + 槽位提取
│   ├── L2_risk_assess.py           # 风险评估规则引擎
│   └── L3_response_dispatch.py     # 三级回复分派器
│
├── v3/                             # [V3新增] V3 运行时 (独立于 src/)
│   ├── __init__.py                 # 包声明
│   ├── entrance.py                 # V3 入口 (单阶段 L1)
│   ├── L1_router.py                # V3 L1 路由 (LLM 调用 + JSON 解析)
│   └── L1_router_v3.txt           # 生成的 V3 prompt
│
├── prompter/                       # [V3新增] Prompt 确定性生成管道
│   └── src/
│       ├── L0_xlsx2json.py         # xlsx → JSON (无损提取)
│       ├── L0.5_format_json.py     # 格式清洗 (FAQ拆分, 风险归一)
│       ├── L1_generator.py         # JSON → 文法树 → prompt
│       ├── grammar_tree.py         # 文法树数据模型 (enrich 槽位)
│       ├── serialize.py            # 文法树 → 文本 序列化
│       └── skeletons/              # 历史 skeleton (新版本不再使用)
│
├── prompt/                         # LLM Prompt 模板 (V2)
│   ├── L1_intent_router.txt        # L1 意图路由 prompt
│   ├── tag_*.txt                   # L0 标签判别 prompt
│   └── escalation.txt              # 升级处置 prompt
│
├── server/                         # Web 后端
│   ├── main.py                     # FastAPI (/api/chat + /api/chat/v3)
│   ├── conversation_manager.py     # 对话 CRUD（JSON 存储）
│   ├── workspace_manager.py        # 工作文件夹 + 暂存区
│   ├── parser_registry.py          # 对话解析器注册
│   └── parsers/                    # 解析器插件
│
├── web/                            # Web 前端
│   └── src/
│       ├── types.ts                # TypeScript 类型 (V2/V3 兼容)
│       ├── api.ts                  # API 客户端 (chatSSE + chatV3)
│       ├── store.ts                # Zustand 状态 (useV3 开关)
│       └── components/
│           ├── ChatMain.tsx        # 聊天主区域
│           ├── MessageUnit.tsx     # 消息单元
│           ├── ControlInfoPanel.tsx # 控制信息面板 (动态字段发现)
│           ├── ThresholdSettings.tsx # V2/V3 切换 + L0 阈值
│           ├── ConversationSidebar.tsx
│           └── WorkspaceSidebar.tsx
│
├── test/                           # 测试
│   ├── testL0/                     # L0 测试
│   ├── test_risk_assess.py         # 风险评估单元测试
│   └── test_dispatch.py            # 回复分派单元测试
│
├── data/conversations/             # 对话存储（JSON + .results.json）
├── start.bat                       # 一键启动脚本
└── docs/superpowers/specs/         # 设计文档
    ├── 2026-06-04-chat-playground-design.md  # V1 设计
    └── 2026-06-05-v2-pipeline-design.md      # V2 设计
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | SSE 流式聊天（V2 全链路 L0→L1→L2→L3） |
| `/api/chat/v3` | POST | [V3新增] SSE 流式聊天（V3 单阶段 L1） |
| `/api/conversations` | GET/POST | 对话列表 / 新建 |
| `/api/conversations/:id` | GET/PUT/DELETE | 对话 CRUD |
| `/api/workspace/staging` | GET/POST/DELETE | 暂存区文件管理 |
| `/api/workspace/persisted` | GET | 已持久化文件列表 |
| `/api/workspace/parse` | POST | 解析对话文件 → OpenAI messages |
| `/api/workspace/config` | GET/PUT | 工作路径配置 |
| `/api/parsers` | GET | 已注册解析器列表 |

### entrance 返回值 (V2)

**case=0** — L0 manual 拦截 → 升级人工处置

```json
{
  "case": 0,
  "risk_level": "high",
  "response_mode": "faq_only_human",
  "tag_dispositions": {
    "manual":  {"action": "escalate", "probability": 1.0, "triggered": true},
    "angry":   {"action": "risk_bump", "probability": 0.93, "triggered": true}
  },
  "data": {
    "call_body": "###tool_call(human_intervention_api)",
    "situation_brief": "向人工坐席的情景快速披露",
    "user_comfort": "面向用户的安抚话语",
    "l0_tags": {"manual": 1.0, "angry": 0.93, "sad": 0.04, "urgent": 0.04, "non_biz": 0.0}
  }
}
```

**case=1** — 正常路由 → L1 + 风险评估 + 分级回复

```json
{
  "case": 1,
  "risk_level": "medium",
  "response_mode": "faq_first",
  "tag_dispositions": {...},
  "decision_trail": [
    {"step": "scene_base", "input_value": "车险投保", "result": "medium", "reason": "..."}
  ],
  "data": {
    "primary_intent": {"l1": "售前服务", "l2": "车险投保", "confidence": 0.95},
    "needs_clarification": true,
    "slots": {"all_slots": [...], "filled_slots": {...}, "missing_slots": [...]},
    "operation": {"type": "clarify_slots", "detail": "..."},
    "user_output": "好的，小保帮您准备车险报价...",
    "reason": "...",
    "faq_matched": false,
    "audit_required": true
  }
}
```

**case=2** — L0 urgent 触发 → 跳过澄清+风险评估, 直接操作指引

```json
{
  "case": 2,
  "risk_level": null,
  "response_mode": "direct_guide",
  "tag_dispositions": {...},
  "data": {
    "user_output": "请立即拨打 95500 转救援专线...",
    "escalate_to_human": true
  }
}
```

### entrance 返回值 (V3)

V3 统一返回 `case=1`, 数据更简洁:

```json
{
  "case": 1,
  "risk_level": null,
  "response_mode": "v3",
  "tag_dispositions": {},
  "decision_trail": [],
  "data": {
    "primary_intent": {"l1": "售前服务", "l2": "健康险投保", "confidence": 0.92},
    "top_candidates": [
      {"l1": "售前服务", "l2": "产品咨询", "probability": 0.18}
    ],
    "needs_clarification": false,
    "user_output": "正在为您查询健康险方案...\n###call(售前服务-健康险投保)",
    "reason": "用户明确表达购买医疗险意向, 直接路由"
  }
}
```

V3 与 V2 case=1 的 data 字段差异:
- 移除 `slots` (V3 L1 不收集槽位)
- 移除 `operation` (路由信息隐含在 `user_output` 的 `###call(L1-L2)` 中)
- 移除 `faq_matched`, `audit_required`, `tool_calls` (无风险评估/分派)
- 调用格式: `###call(一级意图-二级意图)` 替换 28 个具名 API

## GUI 协议：约定优于配置

V3/V4/V5 内核迭代 **无需修改 GUI 代码**。只需在 entrance 返回值中遵循命名约定：

| key 后缀 | GUI 渲染器 | 示例 |
|----------|-----------|------|
| `*_level` | 彩色风险 badge | `risk_level: "high"` → 红色"高风险" |
| `*_mode` | 模式 badge | `response_mode: "faq_first"` |
| `*_tags` / `*_dispositions` | 键值表 | `tag_dispositions: {...}` |
| `*_trail` | 步骤时间线 | `decision_trail: [{step, result, reason}]` |
| `*_required` / `*_matched` | 绿/红 布尔 | `audit_required: true` |
| 布尔值 | 绿/红 badge | 自动检测 |
| 对象/数组 | 可展开 JSON 树 | 自动检测 |
| 其他 | 纯文本 | 自动检测 |

详见 `src/entrance.py` 文件头文档和 `web/src/components/ControlInfoPanel.tsx`。

## 测试

```bash
# 规则引擎单元测试 (无需 LLM)
python src/L2_risk_assess.py       # 7 项, <1s

# 回复分派单元测试 (无需 LLM)
python src/L3_response_dispatch.py  # 6 项, <1s

# 全真流程测试 (需 API key)
python src/entrance.py              # 5 场景, ~30s
```

## 对话存储格式

```
data/conversations/
├── abc123.json              # 标准 OpenAI messages 格式
└── abc123.results.json      # 伴生文件：消息索引 → entrance 控制信息 (V2字段)
```

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+B` | 切换左侧对话列表 |
| `Ctrl+Shift+B` | 切换右侧工作文件夹 |
| `Ctrl+N` | 新建对话 |
| `Ctrl+S` | 保存当前对话 |
| `Ctrl+Enter` | 保存编辑中的消息 |
