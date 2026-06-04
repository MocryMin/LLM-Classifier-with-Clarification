# 智能管家 · Chat Playground

基于 LLM 的保险智能客服系统，集成 L0 跨场景标记检测 + L1 意图路由，附带 Web 对话测试工作台。

## 架构

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
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
     ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
     │ L0 标签检测   │   │ L1 意图路由   │   │ 升级处置智能体    │
     │ 5 tags × SC  │   │ purpose_route │   │ escalation LLM   │
     │ ~22 API 调用  │   │ ~2 API 调用   │   │ ~1 API 调用      │
     └──────────────┘   └──────────────┘   └──────────────────┘
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

## 项目结构

```
baogu/
├── src/                        # 智能管家核心
│   ├── entrance.py             # 路由层统一入口
│   ├── L0_tag_judge.py         # L0 跨场景标记检测（5 标签并行）
│   └── L1_purpose.py           # L1 意图路由 + 槽位提取
│
├── prompt/                     # LLM Prompt 模板
│   ├── tag_*.txt               # L0 标签判别 prompt
│   ├── L1_intent_router.txt    # L1 意图路由 prompt
│   └── escalation.txt          # 升级处置 prompt
│
├── server/                     # Web 后端
│   ├── main.py                 # FastAPI 入口 + SSE chat
│   ├── conversation_manager.py # 对话 CRUD（JSON 存储）
│   ├── workspace_manager.py    # 工作文件夹 + 暂存区
│   ├── parser_registry.py      # 对话解析器注册
│   └── parsers/                # 解析器插件
│
├── web/                        # Web 前端
│   └── src/
│       ├── types.ts            # TypeScript 类型定义
│       ├── api.ts              # 后端 API 客户端
│       ├── store.ts            # Zustand 状态管理
│       └── components/         # React 组件
│           ├── ChatMain.tsx    # 聊天主区域
│           ├── MessageUnit.tsx # 消息单元（可展开控制信息）
│           ├── ControlInfoPanel.tsx  # 控制信息面板
│           ├── ConversationSidebar.tsx  # 对话列表侧边栏
│           └── WorkspaceSidebar.tsx     # 工作文件夹侧边栏
│
├── data/conversations/         # 对话存储（JSON + .results.json）
├── start.bat                   # 一键启动脚本
└── docs/superpowers/           # 设计文档 + 实施计划
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | SSE 流式聊天（entrance 全链路） |
| `/api/conversations` | GET/POST | 对话列表 / 新建 |
| `/api/conversations/:id` | GET/PUT/DELETE | 对话 CRUD |
| `/api/workspace/staging` | GET/POST/DELETE | 暂存区文件管理 |
| `/api/workspace/persisted` | GET | 已持久化文件列表 |
| `/api/workspace/parse` | POST | 解析对话文件 → OpenAI messages |
| `/api/workspace/config` | GET/PUT | 工作路径配置 |
| `/api/parsers` | GET | 已注册解析器列表 |

### entrance 返回值

**case=0** — L0 拦截 → 升级人工处置

```json
{
  "case": 0,
  "data": {
    "call_body": "###tool_call(human_intervention_api)",
    "situation_brief": "向人工坐席的情景快速披露",
    "user_comfort": "面向用户的安抚话语",
    "l0_tags": {"manual": 1.0, "angry": 0.93, "sad": 0.04, "urgent": 0.04, "non_biz": 0.0}
  }
}
```

**case=1** — L0 通过 → L1 意图路由

```json
{
  "case": 1,
  "data": {
    "primary_intent": {"l1": "售前服务", "l2": "车险投保", "confidence": 0.95},
    "top_candidates": [{"l1": "售前服务", "l2": "车险投保", "probability": 0.95}],
    "needs_clarification": true,
    "slots": {
      "all_slots": [{"name": "车牌号", "description": "车辆牌照号码", "options": []}],
      "filled_slots": {"保障需求": "交强险+商业险"},
      "missing_slots": ["车牌号", "车型年份"]
    },
    "operation": {"type": "clarify_slots", "detail": "意图已确认为车险投保"},
    "user_output": "好的，小保帮您准备车险报价...",
    "reason": "用户明确说要买车险并请求报价"
  }
}
```

## 对话存储格式

```
data/conversations/
├── abc123.json              # 标准 OpenAI messages 格式
└── abc123.results.json      # 伴生文件：消息索引 → entrance 控制信息
```

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+B` | 切换左侧对话列表 |
| `Ctrl+Shift+B` | 切换右侧工作文件夹 |
| `Ctrl+N` | 新建对话 |
| `Ctrl+S` | 保存当前对话 |
| `Ctrl+Enter` | 保存编辑中的消息 |
