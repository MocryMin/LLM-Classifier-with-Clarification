# 智能管家 · 对话测试工作台 — 设计规格

> 日期: 2026-06-04 | 版本: v1.0

---

## 一、概述

基于 `entrance.py` 构建一个本地 Web 对话测试工作台。同时面向用户（行业级聊天 GUI）和开发者（消息检查、对话编辑、文件管理）。技术栈：React + TypeScript (前端) / FastAPI (后端)。

### 核心目标

1. **行业级对话界面** — 类似 Google AI Playground 的成熟聊天体验
2. **开发者检查能力** — 每条 AI 消息可展开查看 entrance 返回的全部控制信息
3. **消息自由编辑** — 增删改任意消息，快速构造测试变体
4. **工作文件夹** — 暂存区 + 持久化两层文件管理，支持拖拽加载对话
5. **对话解析器插件化** — OpenAI JSON 为默认格式，架构预留扩展点

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    浏览器 (localhost:5173)                        │
│                                                                  │
│  ┌──────────┐  ┌───────────────────────────┐  ┌──────────────┐  │
│  │ 对话列表  │  │       聊天主区域            │  │ 工作文件夹    │  │
│  │ (左)     │  │                           │  │ (右)         │  │
│  │          │  │  ┌─────────────────────┐   │  │              │  │
│  │ • 新建   │  │  │ 消息单元 × N         │   │  │ • 暂存区     │  │
│  │ • 搜索   │  │  │  (可展开/可编辑)      │   │  │ • 已加载     │  │
│  │ • 列表   │  │  └─────────────────────┘   │  │ • 拖入导入   │  │
│  │ • 拖入   │  │  输入区 + 发送 + 参数设置    │  │ • 双击加载   │  │
│  │   加载   │  │                           │  │ • 拖入对话   │  │
│  └──────────┘  └───────────────────────────┘  └──────────────┘  │
│                    │  HTTP REST + SSE                             │
└────────────────────┼─────────────────────────────────────────────┘
                     │
┌────────────────────┼─────────────────────────────────────────────┐
│              FastAPI (localhost:8000)                              │
│                                                                   │
│  /api/chat          → entrance(messages, threshold, debug)       │
│  /api/conversations → 对话 CRUD                                   │
│  /api/workspace     → 文件暂存/持久化/扫描                         │
│  /api/parsers       → 对话解析器注册与调用                          │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐           │
│  │ Conversation│  │  Workspace   │  │ ParserRegistry │           │
│  │ Manager     │  │  Manager     │  │                │           │
│  └─────────────┘  └──────────────┘  └────────────────┘           │
│                                                                   │
│  entrance.py ──► L0_tag_judge.py ──► L1_purpose.py              │
└──────────────────────────────────────────────────────────────────┘
```

### 技术选型

| 层 | 技术 | 理由 |
|----|------|------|
| 前端框架 | React 18 + TypeScript | 生态最丰富，类型安全 |
| 状态管理 | Zustand | 轻量、无 boilerplate |
| UI 组件 | shadcn/ui + Tailwind CSS | 高质量原语，暗色模式内置 |
| 后端 | FastAPI + uvicorn | 原生 async，直接 import entrance |
| 文件操作 | Python pathlib + shutil | 标准库，无依赖 |
| 核心逻辑 | entrance.py | **零修改** |

---

## 三、后端 API 设计

### 3.1 对话相关

```
POST  /api/conversations          创建空白对话 → { id, created_at }
GET   /api/conversations          对话列表 → [{ id, title, msg_count, updated_at }]
GET   /api/conversations/:id      获取完整对话 → { id, messages[], meta }
PUT   /api/conversations/:id      保存对话 → 覆盖 messages
DELETE /api/conversations/:id     删除对话
```

### 3.2 聊天

```
POST /api/chat
```

**请求体：**
```json
{
  "messages": [
    {"role": "user", "content": "我要买车险"}
  ],
  "l0_threshold": 0.7,
  "debug": false
}
```

**响应（SSE 流式）：**
```
event: progress
data: {"stage": "l0", "done": 12, "total": 22}

event: progress
data: {"stage": "l1"}

event: progress
data: {"stage": "escalation"}

event: result
data: {"case": 1, "data": {...完整 entrance 返回...}}
```

SSE 推送 L0/L1 进度，前端展示 "正在检测标签 (12/22)..." 或 "正在路由意图..." 的加载状态。最终 `result` 事件携带完整 entrance 返回值。

### 3.3 工作文件夹

```
POST   /api/workspace/import       导入文件 → 暂存区（临时目录）
GET    /api/workspace/staging      暂存区文件列表
GET    /api/workspace/persisted    工作路径内已持久化的文件列表
POST   /api/workspace/persist      指定暂存文件 → 复制到工作路径
DELETE /api/workspace/staging/:id  删除暂存文件
GET    /api/workspace/config       获取当前工作路径
PUT    /api/workspace/config       设置工作路径 { "path": "/path/to/folder" }
```

### 3.4 对话解析

```
POST /api/workspace/parse
```

**请求：** `{ "staging_id": "abc123.json" }`
**响应：** `{ "format": "openai_messages", "parser_used": "openai_json", "messages": [...] }`

解析在后端完成。暂存区文件 → ParserRegistry 自动匹配解析器 → 返回标准 OpenAI messages。

---

## 四、Parser 插件系统

位于 `server/parsers/`，每个解析器一个文件。

```python
# server/parsers/base.py
from abc import ABC, abstractmethod

class BaseParser(ABC):
    name: str                          # "openai_json"
    display_name: str                  # "OpenAI Messages JSON"
    file_extensions: list[str]         # [".json"]

    @abstractmethod
    def detect(self, raw_content: str) -> bool: ...
    # 返回 True 表示该解析器能处理此内容

    @abstractmethod
    def parse(self, raw_content: str) -> list[dict]: ...
    # 返回标准 OpenAI messages 列表
```

**内置解析器（v1.0）：**

| 解析器 | 文件扩展名 | 说明 |
|--------|-----------|------|
| `OpenAIMessagesParser` | `.json` | 标准 `[{"role":"user","content":"..."}]` 格式 |
| `PlainTextDumpParser` | `.txt` | 纯文本对话 → 调 LLM 整理为 messages（可选启用，需额外 API 调用） |

**注册方式：** 放在 `server/parsers/` 目录下，类名末尾为 `Parser`，服务启动时自动发现并注册。新增格式只需新增一个文件。

---

## 五、前端组件树

```
App
├── LayoutShell                          # 全局布局壳（三栏可伸缩）
│   ├── ConversationSidebar (左侧栏)      # 可收起
│   │   ├── NewChatButton
│   │   ├── SearchBar
│   │   ├── ConversationList             # 虚拟滚动（对话多时）
│   │   │   └── ConversationItem × N     # 标题、时间、消息数
│   │   └── DropZone                     # 拖入对话文件 → 加载
│   │
│   ├── ChatMain (中间主区域)
│   │   ├── ChatHeader                   # 对话标题 + 参数设置入口
│   │   ├── MessageList                  # 虚拟滚动
│   │   │   └── MessageUnit × N          # ★ 核心组件 (见 §六)
│   │   ├── ChatInput                    # 输入框 + 发送按钮
│   │   └── ThresholdSettings            # l0_threshold 滑块 (可折叠)
│   │
│   └── WorkspaceSidebar (右侧栏)         # 可收起
│       ├── WorkspaceConfig              # 路径设置
│       ├── StagingArea                  # 暂存区文件列表
│       │   └── StagingFileItem × N      # 可拖拽到对话列表或聊天区
│       └── PersistedArea                # 已持久化文件列表
│           └── PersistedFileItem × N    # 双击 → 加载对话
```

---

## 六、消息单元 (MessageUnit) 详细设计

这是整个 UI 最核心的组件。每条消息（user 或 AI）都是一个独立的 `MessageUnit`。

### 6.1 用户消息单元

```
┌────────────────────────────────────────────┐
│ 👤 用户                        [✏️] [🗑️]  │  ← 悬浮显示编辑/删除
│                                            │
│ 我要买车险，帮我报个价                       │  ← content (可双击编辑)
└────────────────────────────────────────────┘
```

- 悬浮出现编辑/删除按钮
- 双击 content 进入行内编辑模式（textarea），回车或失焦保存
- 编辑后自动清空该消息之后的所有 AI 回复（因为已过期）

### 6.2 对话气泡文本来源

| case | 显示文本来源 | 说明 |
|------|-------------|------|
| case=0 | `data.user_comfort` | 面向用户的安抚话语 |
| case=1 | `data.user_output` | L1 生成的用户回复（可能内含 `###tool_call(...)`） |

### 6.3 AI 消息单元（用户视图，默认折叠）

```
┌────────────────────────────────────────────┐
│ 🤖 小保                        [🔽 展开]   │
│                                            │
│ 好的，小保帮您准备车险报价。请提供以下信息：   │  ← user_output
│ 1. 您的车牌号是多少？                        │
│ 2. 车辆的品牌型号和购买年份？                  │
│ ...                                        │
└────────────────────────────────────────────┘
```

### 6.4 AI 消息单元（开发者视图，展开后）

```
┌──────────────────────────────────────────────────────────────────┐
│ 🤖 小保                                            [🔼 收起]     │
│                                                                  │
│ 好的，小保帮您准备车险报价。请提供以下信息：                         │
│ 1. 您的车牌号是多少？                                              │
│ ...                                                              │
│ ──────────────────────────────────────────────────────────────── │
│ 控制信息                                           [全部展开/折叠] │
│                                                                  │
│ ┌─ case ────────────────────────────────────── [📋] ──────────┐ │
│ │ 1                                              ⓘ            │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ primary_intent ──────────────────────────── [📋] ──────────┐ │
│ │ {"l1":"售前服务","l2":"车险投保","confidence":0.95}  ⓘ       │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ top_candidates ─────────────────────────── [📋] ───────────┐ │
│ │ [{"l1":"售前服务","l2":"车险投保","probability":0.95}]  ⓘ    │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ needs_clarification ────────────────────── [📋] ───────────┐ │
│ │ true                                           ⓘ             │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ slots ──────────────────────────────────── [📋] ───────────┐ │
│ │ all_slots:    [{"name":"车牌号","description":"...",...}]  ⓘ  │ │
│ │ filled_slots: {"保障需求":"交强险+商业险"}                     │ │
│ │ missing_slots:["车牌号","车型年份","使用性质"]                  │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ operation ──────────────────────────────── [📋] ───────────┐ │
│ │ {"type":"clarify_slots","detail":"意图已确认为车险投保..."} ⓘ  │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ user_output ────────────────────────────── [📋] ───────────┐ │
│ │ 好的，小保帮您准备车险报价...                       ⓘ         │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│ ┌─ reason ─────────────────────────────────── [📋] ───────────┐ │
│ │ 用户明确说要买车险并请求报价                        ⓘ         │ │
│ └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 6.5 控制信息交互细节

**ⓘ 行内帮助：** 一个 `?` 图标（`HelpCircle`），hover 显示 tooltip：
- `case`: "entrance 路由结果。0 = L0 拦截升级人工，1 = L1 意图路由"
- `primary_intent`: "L1 分类的主导意图，含一级/二级分类和置信度"
- `slots`: "槽位信息。all_slots 为全部待填项，filled_slots 为已提取，missing_slots 为缺失"
- `operation`: "操作决策。clarify_L1/clarify_slots/direct_reply/route_to_subsidiary/fallback"
- `l0_tags` (case=0 时): "L0 五个标签的原始概率值。manual/angry/sad/urgent/non_biz"
- `situation_brief` (case=0 时): "向人工坐席的情景快速披露"
- `user_comfort` (case=0 时): "面向用户的安抚话语"

**📋 复制按钮：** 点击将该字段的 JSON 值复制到剪贴板。

**折叠/展开：** 每个控制信息行默认折叠，只显示字段名和值的摘要（最多一行）。点击行或右侧展开箭头展开/折叠该字段。

**值格式化：**
- 短文本/数字：直接显示（如 `case: 1`）
- 长文本（>80 字符）：折叠，显示前 80 字符 + "..."
- JSON 对象/数组：语法高亮 + 缩进展示（用轻量 JSON viewer）
- `user_output`：特殊处理——同时作为对话气泡的文本展示，因此在控制信息区也完整显示

### 6.6 case=0 的特殊展示

当 `case=0`（L0 拦截）时，控制信息列表为：

```
┌─ case ──────────────────────────────────────┐
│ 0                                              ⓘ
├─ call_body ───────────────────────────────────┤
│ ###tool_call(human_intervention_api)            ⓘ
├─ situation_brief ─────────────────────────────┤
│ 用户在对话中多次表达强烈转人工意图...               ⓘ
├─ user_comfort ────────────────────────────────┤
│ 小保已经注意到您的需求，正在为您转接人工坐席...     ⓘ
├─ l0_tags ────────────────────────────────────┤
│ {"manual":1.0,"angry":0.93,"sad":0.04,...}     ⓘ
└───────────────────────────────────────────────┘
```

### 6.7 消息编辑交互

```
操作方式：
  - 双击消息文本 → 行内编辑
  - 悬浮 → 出现 ✏️ 🗑️ 按钮
  - 右键 → 上下文菜单（编辑 / 在上面插入 / 在下面插入 / 删除）
  - 删除时弹出确认 toast
  - 编辑某条消息后 → 该消息之后的所有 AI 回复自动标记为"已过期"（灰色虚线边框）
  - 点击"重新发送" → 用编辑后的 messages 重新调用 entrance
```

---

## 七、数据流

### 7.1 正常对话流程

```
用户在输入框输入
       │
       ▼
前端组装 messages (历史 + 新用户消息)
       │
       ▼
POST /api/chat (SSE)
       │
       ▼
后端 entrance(messages)
  ├─ L0 tag_judge_v2 (并行 22 次调用)
  │   └─ SSE progress: {stage:"l0", done:n, total:22}
  ├─ case=0 → escalation → SSE result
  └─ case=1 → purpose_route → SSE result
       │
       ▼
前端收到 result → 追加 AI MessageUnit (默认折叠)
       │
       ▼
用户/开发者可展开检查控制信息
```

### 7.2 文件导入 → 加载对话流程

```
用户拖文件到右侧工作文件夹
       │
       ▼
POST /api/workspace/import → 文件进入暂存区 (临时目录)
       │
       ▼
暂存区列表刷新，显示新文件
       │
       ▼
用户双击暂存文件（或拖到对话列表）
       │
       ▼
POST /api/workspace/parse → 解析器识别格式 → 返回 messages
       │
       ▼
POST /api/workspace/persist → 文件复制到工作路径
       │
       ▼
前端创建新对话，加载 messages → 显示在对话列表 + 聊天区
```

### 7.3 编辑重发流程

```
开发者编辑第 N 条 user 消息
       │
       ▼
前端标记 messages[N+1:] 为"已过期"
       │
       ▼
开发者点击"重新发送"
       │
       ▼
POST /api/chat (messages[0:N+1])
       │
       ▼
新 AI 回复替换旧的过期消息
```

---

## 八、工作文件夹 & 暂存机制

### 8.1 生命周期

```
文件拖入 → 暂存区 (临时目录, 不持久)
     │
     ├── 用户双击加载 → persist → 复制到工作路径 → 出现在对话列表
     │
     ├── 用户手动删除 → 从暂存区移除
     │
     └── 程序关闭 → 暂存区自动清理（未加载的文件消失）
```

### 8.2 路径结构

```
{用户配置的工作路径}/           ← 工作文件夹（持久）
  ├── conversation_1.json
  ├── conversation_2.json
  └── ...

{临时目录}/staging/            ← 暂存区（会话级别）
  ├── imported_test.json       ← 拖入但未加载
  └── ...

程序关闭时：扫描暂存区，删除所有未被 persist 的文件。
```

### 8.3 安全约束

- 后端只允许访问用户配置的工作路径 + 暂存临时目录
- 导入文件时校验扩展名白名单（`.json`, `.jsonl`, `.txt`）
- 文件大小限制 10MB

---

## 九、对话存储格式

采用 **OpenAI messages 标准格式**，JSON 文件存储：

```json
{
  "version": 1,
  "created_at": "2026-06-04T10:30:00Z",
  "updated_at": "2026-06-04T11:00:00Z",
  "meta": {
    "l0_threshold": 0.7,
    "last_case": 1
  },
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "您好，我是智能管家小保..."},
    {"role": "user", "content": "我要买车险"}
  ]
}
```

- `messages` 数组与 entrance 输入格式完全一致，可直接传入
- `meta` 记录最后使用的参数和结果，方便复现
- `version` 预留格式演进

---

## 十、项目目录结构

```
baogu/
├── src/                    # 现有智能管代码（不动）
│   ├── entrance.py
│   ├── L0_tag_judge.py
│   ├── L1_purpose.py
│   └── ...
├── prompt/                 # 现有 prompt（不动）
├── server/                 # ★ 新增：后端
│   ├── main.py             # FastAPI 入口
│   ├── conversation_manager.py
│   ├── workspace_manager.py
│   ├── parser_registry.py
│   └── parsers/
│       ├── base.py
│       ├── openai_json.py
│       └── plain_text.py
├── web/                    # ★ 新增：前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── store.ts            # Zustand
│       ├── api.ts              # 后端 API 封装
│       ├── components/
│       │   ├── LayoutShell.tsx
│       │   ├── ConversationSidebar.tsx
│       │   ├── ChatMain.tsx
│       │   ├── MessageUnit.tsx
│       │   ├── ControlInfoPanel.tsx
│       │   ├── ChatInput.tsx
│       │   ├── WorkspaceSidebar.tsx
│       │   └── ui/             # shadcn/ui 组件
│       ├── types.ts            # TypeScript 类型定义
│       └── utils.ts
└── docs/superpowers/specs/
    └── 2026-06-04-chat-playground-design.md   # 本文档
```

---

## 十一、错误处理

| 场景 | 处理 |
|------|------|
| entrance 调用超时 (>60s) | 前端显示超时提示 + 重试按钮 |
| entrance JSON 解析失败 | 后端返回 fallback 结果（entrance 已有兜底），前端标记为 "解析异常" |
| 工作路径不存在 | 后端返回 400 + 提示设置有效路径 |
| 暂存区文件无法解析 | 显示 "无法识别格式" 行内错误，列出支持的格式 |
| 对话文件过大 (>10MB) | 拒绝导入，提示文件过大 |
| 网络断开 (fetch SSE 中断) | 自动重连 + 显示连接状态指示器 |

---

## 十二、实施阶段

### Phase 1 — 最小可用 (MVP)
- FastAPI 启动 + POST /api/chat
- React 骨架 + 基础 MessageList + ChatInput
- 能发消息、看到 AI 回复
- 无侧边栏、无控制信息展开

### Phase 2 — 开发者核心
- MessageUnit 展开/折叠控制信息
- 行内帮助 tooltip
- 消息编辑/删除/插入
- case=0 和 case=1 完整展示

### Phase 3 — 工作文件夹
- 左右侧边栏
- 对话列表 CRUD
- 暂存区 + 持久化
- 拖拽导入 + 双击加载

### Phase 4 — 打磨
- 虚拟滚动（大量消息/对话）
- 暗色/亮色主题
- SSE 进度条
- Parser 插件系统
- Toast 通知、快捷键

---

## 十三、不做什么（v1.0 范围外）

- 对话树/分支（保持线性覆盖）
- 多用户/登录系统（本地单用户工具）
- 对话导出为 PDF/HTML
- 对话全文搜索（先用文件名+标题匹配）
- 移动端适配（桌面优先）
