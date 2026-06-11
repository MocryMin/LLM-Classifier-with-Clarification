# Prompter — V3 Prompt 自动生成器

把一张场景设计 xlsx 变成生产可用的 V3 意图路由 prompt。支持纯确定性生成（快、稳），也可接入 LLM 自动调优（慢、但更准）。

---

## 小白快速上手

### 你只需要 3 步

**第 1 步：把 xlsx 放进去**

将场景设计表（xlsx 格式）放到 `prompter/xlsx/` 目录下。只放一个。

xlsx 必须包含名为 `场景设计` 的 sheet，列名固定（一级意图、二级意图、二级场景定义…）。不多不少 12 列。如果你不确定格式对不对，找开发确认。

**第 2 步（可选）：把黄金样本放进去**

如果你有标注好的测试样本，把它做成 xlsx 放到 `prompter/golden/` 下。格式见[黄金样本格式](#黄金样本-xlsx-格式)。

没有也没关系——系统会自动跳过 LLM 调优，只出基础 prompt。

**第 3 步：运行**

```bash
cd prompter
python build.py
```

等待完成。产物在 `prompter/output/<你的xlsx名>/` 里：

| 文件 | 说明 |
|------|------|
| `L1_router_v3.txt` | 基础 prompt（确定性的，无 LLM 参与） |
| `L3_router_v3.txt` | 调优后的 prompt（如有黄金样本） |
| `BUILD_REPORT.txt` | 构建报告 |

把 `.txt` 文件里的内容复制到 V3 路由系统即可使用。

---

## 进阶用法

### 命令行参数

```bash
# 指定 xlsx
python build.py --xlsx xlsx/0604.xlsx

# 选择模式: full=含L2澄清(默认) | classify_only=仅分类+L1澄清
python build.py --xlsx xlsx/0604.xlsx --mode classify_only

# 跳过 LLM 调优（只出 L1 prompt，最快）
python build.py --xlsx xlsx/0604.xlsx --no-llm

# 指定自己的黄金样本
python build.py --xlsx xlsx/0604.xlsx --golden golden/my_test.xlsx

# 编译完直接部署到 v3/
python build.py --xlsx xlsx/0604.xlsx --deploy

# 查看可用文件
python build.py --list
```

### 两种模式的区别

| | `full`（默认） | `classify_only` |
|---|---|---|
| L2 澄清（SOP 驱动） | 含 | 不含 |
| SOP 字段 | 显示在 prompt 中 | 隐藏 |
| 适用场景 | 常规路由 | 仅需意图分类 |

### LLM 调优流程

当你提供了黄金样本 xlsx，系统会自动执行两阶段调优：

```
L0: xlsx → json         (确定性的, 无LLM)
L0.5: 格式清洗           (确定性的, 无LLM)
L1: 生成基础 prompt      (确定性的, 无LLM)
         │
    ┌────▼──── 以下需黄金样本 ────┐
    │                             │
    ▼                             ▼
L2 enrich: LLM 全局补充          L3 micro-revise: LLM 局部打磨
  - 给 L1 分组写说明文字            - 改关键词
  - 补充 few-shot 示例             - 加边界反例
                                  - 加区分规则
```

每步修改都会在黄金样本上验证——准确率不降才保留。

没有黄金样本时，L2/L3 自动跳过，只出 L1 prompt。

---

## 黄金样本 xlsx 格式

如果你想让 LLM 帮你调优 prompt，你需要准备一个黄金样本 xlsx。格式极简，只有 3 列：

| 列 A：用户输入 | 列 B：一级意图 | 列 C：二级意图 |
|---|---|---|
| 我想查一下保单 | 保单服务 | 保单查询 |
| 我要买车险 | 售前服务 | 车险投保 |
| 你好 | 开场 | 欢迎引导 |

**要求**：
- 第一行为表头（随便写什么，会自动跳过）
- 每个 L2 意图至少有 1-2 条样本
- 样本尽量覆盖不同表达方式
- 标签必须与场景设计表里的意图名完全一致（包括标点符号）

**多轮对话**：列 A 中用换行写各轮，格式为 `角色:内容`：

```
用户:我想买个医疗险
客服:请问被保人年龄是？
用户:35岁，有高血压
```

支持的 `角色`：`用户` / `客服` / `user` / `assistant`

**放哪里**：`prompter/golden/` 目录下，只放一个 xlsx。

**转 json**（如果你需要程序调用）：

```bash
python src/golden_xlsx2json.py golden/my_test.xlsx --out golden_samples.json
```

---

## 目录结构

```
prompter/
├── build.py              ← 一键编译入口（你只需要这个）
├── README.md             ← 本文件
├── report.md             ← 技术细节（给开发者看）
│
├── xlsx/                 ← 【放场景设计 xlsx 的地方】
├── golden/               ← 【放黄金样本 xlsx 的地方（可选）】
├── output/               ← 产物输出（自动生成，不要手动改）
│
├── test/
│   └── golden_samples.json  ← 内部测试用的黄金样本（101条）
│
└── src/                  ← 源代码
    ├── L0_xlsx2json.py       Step1: xlsx → json
    ├── L0.5_format_json.py   Step2: 格式清洗
    ├── L1_generator.py       Step3: json → 文法树 → prompt
    ├── grammar_tree.py       文法树 + PromptArtifact 双生容器
    ├── serialize.py          树 → 文本
    ├── golden_xlsx2json.py   黄金样本 xlsx → json
    │
    ├── L2_entry.py           L2 统一入口（co-agent 接口）
    ├── L2_enrich.py          enrich LLM 调用
    ├── L2_enrich_application.py  申请数据模型
    ├── L2_enrich_inputs.py   输入上下文构建
    ├── L2_validator.py       确定性验证
    ├── L2_golden_validate.py 黄金样本贪心验证 + 报告
    ├── L2_applier.py         L2 写入文法树
    │
    ├── L3_entry.py           L3 统一入口
    ├── L3_reviser.py         错例分析 + 微调提案
    └── L3_applier.py         L3 写入 Intent.enriched
```

---

## 常见问题

**Q: 运行很慢？**
A: 如果不提供黄金样本，`--no-llm` 模式只需要几秒钟。LLM 调优需要调用 API（约 5-10 分钟），取决于网络和黄金样本数量。

**Q: xlsx 放进去报错了？**
A: 检查：① sheet 名是不是 `场景设计`；② 列名是否完整（12 列）；③ 一级意图列的合并单元格是否正确（首行有值，后续行可以为空，系统会自动填充）。

**Q: 黄金样本放进去没用？**
A: 检查：① 意图名是否与场景设计表完全一致（含括号、斜杠等）；② 是否放在了 `prompter/golden/` 下；③ 运行日志里有没有报错。

**Q: 想要修改 prompt 的固定部分（角色描述、路由规则、约束等）？**
A: 修改 `prompter/src/L1_generator.py` 中的对应文本常量。改完后不用动其他地方，重新运行 `build.py` 即可。

**Q: 想要给 co-agent 调用？**
A: 看 `report.md` 的 Step4/Step5，或直接 import：

```python
from L2_entry import run_l2_pipeline
from L3_entry import run_l3_pipeline
from grammar_tree import PromptArtifact
```
