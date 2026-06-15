# 智能管家 V3 — 意图路由 Chat Playground

基于 LLM 的保险智能客服意图路由系统。单阶段 L1 架构，配套 prompt 自动生成器与对话调试工作台。

---

## 项目概览

```
                          ┌──────────────────────────┐
                          │   Chat Playground (web)  │
                          │   localhost:5173         │
                          └────────────┬─────────────┘
                                       │ HTTP + SSE
                          ┌────────────▼─────────────┐
                          │   FastAPI (server)       │
                          │   localhost:8000         │
                          │   /api/chat              │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │   v3/entrance.py         │  V3 单阶段 L1 路由
                          │   v3/L1_router.py        │  LLM + JSON 解析
                          │   v3/L1_router_v3.txt    │  生成的 V3 prompt
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │   prompter/              │  Prompt 确定性生成器
                          │   xlsx → json → prompt   │  + LLM 调优 (可选)
                          └──────────────────────────┘
```

---

## 快速上手

### 环境要求

- **Windows 10 / 11** （或 Windows Server 2019+）
- Python 3.10+
- Node.js 18+

### 一键启动

双击 `start.bat`：自动检查依赖、安装、启动后端+前端、打开浏览器。

启动后访问：[http://localhost:5173](http://localhost:5173)

### 手动启动

```bash
# 后端
cd server
pip install -r requirements.txt
python main.py

# 前端 (新终端)
cd web
npm install
npm run dev
```

---

## V3 核心特性

| 维度 | 说明 |
|------|------|
| 架构 | 单阶段 L1 意图路由，无 L0/L2/L3 标签检测和风险评估 |
| 场景数 | 32 个二级业务场景 + 6 个一级分组 |
| 调用格式 | `###call(L1-L2)` 统一格式（不再用 28 个具名 API） |
| 澄清模式 | L1 意图竞争澄清 + L2 SOP 驱动澄清（可选） |
| Prompt 生成 | 由 prompter 模块从 xlsx 自动生成（确定性 + LLM 调优） |

### V3 入口返回值

```json
{
  "case": 1,
  "response_mode": "v3",
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

---

## 项目结构

```
.
├── start.bat            ← 一键启动脚本
├── README.md            ← 本文件
│
├── v3/                  V3 运行时
│   ├── entrance.py      入口（单阶段 L1）
│   ├── L1_router.py     LLM 调用 + JSON 解析
│   └── L1_router_v3.txt 生成的 V3 prompt
│
├── prompter/            Prompt 自动生成器
│   ├── build.py         一键编译: xlsx → prompt
│   ├── README.md        prompter 用户手册
│   ├── report.md        prompter 技术细节
│   ├── xlsx/            场景设计 xlsx 输入
│   ├── golden/          黄金样本 xlsx (可选)
│   ├── output/          产物输出
│   ├── test/            内部黄金样本
│   └── src/             生成器源码 (L0→L3)
│
├── server/              Web 后端 (FastAPI)
│   ├── main.py          /api/chat (SSE 流式)
│   ├── conversation_manager.py  对话 CRUD (JSON 存储)
│   ├── workspace_manager.py     工作文件夹 + 暂存区
│   ├── parser_registry.py       对话解析器注册
│   └── parsers/                 解析器插件
│
└── web/                 Web 前端 (React + TS)
    └── src/
        ├── App.tsx
        ├── api.ts       API 客户端
        ├── store.ts     Zustand 状态
        ├── types.ts     TypeScript 类型
        └── components/  UI 组件
```

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/chat` | POST | V3 SSE 流式聊天 |
| `/api/conversations` | GET / POST | 对话列表 / 新建 |
| `/api/conversations/:id` | GET / PUT / DELETE | 对话 CRUD |
| `/api/workspace/staging` | GET / POST / DELETE | 暂存区文件管理 |
| `/api/workspace/persisted` | GET | 持久化文件列表 |
| `/api/workspace/parse` | POST | 解析对话文件 → messages |
| `/api/workspace/config` | GET / PUT | 工作路径配置 |
| `/api/parsers` | GET | 已注册解析器列表 |

---

## Prompt 自动生成器（prompter）

把场景设计 xlsx 一键变成生产可用的 V3 prompt：

```bash
cd prompter
python build.py                                    # 小白模式（自动检测）
python build.py --xlsx xlsx/0604.xlsx              # 指定 xlsx
python build.py --xlsx xlsx/0604.xlsx --no-llm     # 跳过 LLM 调优 (最快)
python build.py --xlsx xlsx/0604.xlsx --deploy     # 编译 + 部署到 v3/
python build.py --list                             # 列出可用文件
```

详细说明见 [prompter/README.md](prompter/README.md)，技术原理见 [prompter/report.md](prompter/report.md)。

---

## GUI 协议：约定优于配置

V3/V4/V5 内核迭代 **无需修改 GUI 代码**。GUI 通过字段命名后缀自动选择渲染器：

| key 后缀 | GUI 渲染器 |
|----------|-----------|
| `*_level` | 彩色 badge |
| `*_mode` | 模式 badge |
| `*_tags` / `*_dispositions` | 键值表 |
| `*_candidates` | 排序候选表 |
| `*_trail` | 步骤时间线 |
| `*_required` / `*_matched` | 绿/红布尔 |
| 布尔值 | 绿/红 badge |
| 对象/数组 | 可展开 JSON 树 |

详见 [web/src/components/ControlInfoPanel.tsx](web/src/components/ControlInfoPanel.tsx) 文件头注释。

---

## 对话存储格式

```
data/conversations/
├── abc123.json              # OpenAI messages 格式
└── abc123.results.json      # 伴生文件: 消息索引 → entrance 返回值
```

`data/` 目录被 gitignore，仅本地保存。

---

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+B` | 切换左侧对话列表 |
| `Ctrl+Shift+B` | 切换右侧工作文件夹 |
| `Ctrl+N` | 新建对话 |
| `Ctrl+S` | 保存当前对话 |
| `Ctrl+Enter` | 保存编辑中的消息 |

---

## 分支说明

- `main` — 主线（V3）
- `v3-dev` — 当前开发分支
