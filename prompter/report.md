# prompter技术细节描述：

读入完整的**场景设计表**（xlsx）。

Step1：**xlsx2Json**：将该xlsx格式设计表进行无损转化，转化为json格式。相关代码：L0_xlsx2json.py

Step2：**Clean**：对该json中人工编写的内容进行**格式清洗**。包括1、清洗xlsx中的换行符/多余空格/点符...2、将部分文字量转为统一数字/字符格式。相关代码：L0.5_format_json.py

Step3：**Generator**：将json按照一定prompt生成模式生成初始prompt。

按照如下文法树生成中间prompt：

```
Prompt
├── Role               FixedText       角色描述（固定）
├── IntentCatalog      IntentCatalog    xlsx 驱动
│   └── IntentGroup[]
│       ├── header                     自动："一、开场（3个场景）"
│       ├── description                **LLM enrich入口1
│       └── Intent[]
│           ├── header                 自动："【意图1.1】欢迎引导"
│           ├── definition             xlsx: 二级场景定义
│           ├── faq                    xlsx: FAQ典型问题
│           ├── sop                    xlsx: 澄清指引/SOP      ← mode=仅分类时隐藏
│           ├── company                xlsx: 对应子公司
│           ├── reply_design           xlsx: 回复设计
|           |  （以下为供LLM enrich的可选槽）
|           ├── keywords               **LLM 微调入口1；关键词
|           ├── attention              **LLM 微调入口2；注意区分
|           └── negative_examples      **LLM 微调入口3；边界反例
├── RoutingWorkflow    FixedText       V3 路由工作流（固定，mode 控制是否含 L2 段）
├── Constraints        FixedText       反臆想约束（固定）
├── Samples            FixedText       few-shot（固定+后续 LLM enrich，**LLM enrich入口2）
├── OutputFormat       FixedText       输出 JSON schema（固定）
└── Conversation       Placeholder     {conversation}
```

grammar_tree.py定义语法树数据结构结构；

生成函数（L1_generator.py）从**Step2**返回的json中获取信息填写该文法树节点，并返回完整的文法树；

serializer.py将填写后的语法树展开为完整的文本prompt。

Step1-3都是无LLM的确定性操作，旨在将xlsx无损地格式化，并按照某种组织方式**在不进行语义操作**的情况下组织为prompt.

Step4：**enrich**：喂LLM中间prompt，LLM只能返回"申请"，不能直接改prompt。相关代码：L2_enrich.py + L2_enrich_inputs.py + L2_enrich_application.py

**设计原则**：
- 申请制。enricher只给建议，不直接写prompt。每条申请含confidence(0-1)和rationale
- 操作类型严格限定。只有3种：group_description（写L1分组说明）、sample_add（加few-shot）、sample_delete（删矛盾sample）
- 输入粒度精确。每种操作只看它需要的上下文，不给多余信息。description不看routing rules（让数据说话），sample必须看routing rules（让规则把关）
- 退出门。LLM没把握就不输出，不强制

**enricher只管提案，后续管线决定采纳与否**：

```
enrich申请列表 (按confidence降序)
        │
        ▼
L2_validator.py —— 确定性规则验证（零LLM）
  · 事实一致性：description声称"全部集团处理" → 查树中company字段是否真的全集团
  · 格式校验：sample的L1+L2名是否存在、###call格式是否正确
  · 精确去重：conversation逐字比对
        │
        ▼
L2_golden_validate.py —— 黄金样本贪心验证（需LLM，支持多线程）
  1. 跑基线（不加任何enrich）
  2. 逐条接受申请 → 临时应用到文法树 → 序列化 → 跑101条黄金样本
  3. 准确率不降 → 永久接受；降了 → 回退跳过
        │
        ▼
L2_applier.py —— 确定性写入文法树（不碰xlsx原始cells）
  · group_description → tree.groups[N].description
  · sample_add → 追加到##samples##末尾
  · sample_delete → 正则匹配删除
        │
        ▼
serialize() → 最终富化prompt
```

**黄金样本**（golden_samples.json）：
- 101条，来自V2时期throughout测试的batch3(96条)+batch4(5条)
- 32个L1+L2场景全覆盖，每场景3变体（2单轮+1多轮）
- 校验标准：L1+L2分类是否完全匹配（不比user_output/confidence）

---

# 效果报告

**测试配置**：deepseek-v4-pro, 8线程, 101条黄金样本

| 阶段 | 准确率 | 说明 |
|------|--------|------|
| 基线（无enrich） | 92.08% (93/101) | V3 prompt直接跑V2测试集 |
| +L1分组说明(desc) | 93.07% (+1.0%) | 增值服务分组加了描述文字 |
| +意图澄清触发(add) | 94.06% (+1.0%) | 补了"用户输入不明确"的sample |
| +多意图排优先级(add) | 94.06% (无害) | 准确率不变，未引入新错误 |
| +欢迎引导直接回复(add) | 95.05% (+1.0%) | 补了集团直接回复的sample |
| ~~+核保直接路由(add)~~ | ~~93.07%~~ ❌ 拒绝 | 核保vs投保边界敏感，2%下降，贪心回退 |

**最终**：4/5申请接受，准确率 **92.08% → 95.05% (+3.0%)**

**分析**：
- 基线上90%，enrich前prompt已经基本可用。enrich是锦上添花
- 唯一被拒的申请（核保sample, confidence=0.90）恰好是confidence最低的——排序机制生效
- validator零误杀（5/5通过），零漏网（无事实错误漏过）
- 黄金验证有效识别了"看似正确但实际干扰"的sample（核保边界case）
- 3个微调槽（keywords/attention/negative_examples）本次未开放——它们与xlsx规定性内容直接相关，留给test-feedback-train阶段
