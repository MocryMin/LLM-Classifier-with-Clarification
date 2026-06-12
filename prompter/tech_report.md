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
│           │  （以下为供LLM 微调的可选槽）
│           ├── keywords               **LLM 微调入口1；关键词
│           ├── attention              **LLM 微调入口2；注意区分
│           └── negative_examples      **LLM 微调入口3；边界反例
├── RoutingWorkflow    FixedText       V3 路由工作流（固定，mode 控制是否含 L2 澄清）
├── Constraints        FixedText       反臆想约束（固定）
├── Samples            FixedText       few-shot（固定+后续 LLM enrich，**LLM enrich入口2）
├── OutputFormat       FixedText       输出 JSON schema（固定）
└── Conversation       Placeholder     {conversation}
```

grammar_tree.py定义语法树数据结构；

生成函数（L1_generator.py）从**Step2**返回的json中获取信息填写该文法树节点，并返回完整的文法树；

serializer.py将填写后的语法树展开为完整的文本prompt。

Step1-3都是无LLM的确定性操作，旨在将xlsx无损地格式化，并按照某种组织方式**在不进行语义操作**的情况下组织为prompt.

Step4：**enrich**：将Step3产出的中间prompt拆分并喂LLM，LLM只能返回若干"润色申请"，不直接改prompt。相关代码：L2_enrich.py + L2_enrich_inputs.py + L2_enrich_application.py

**enrich内容产生原则**：
- **申请制**：enricher只给建议，不直接写prompt。每条申请含confidence(0-1)和rationale
- **局部受限操作**：enrich层LLM可进行的操作范围和操作内容严格限定。只能在两处进行共3种修改：group_description（总结L1意图描述）、sample_add（加few-shot）、sample_delete（删现有矛盾的few-shot sample）。确保enrich的“微调”本质，由确定性的受限操作控制LLM的不确定性。
- **最小上下文输入粒度**：进行description enrich的LLM只能看到该L1意图及其的子意图字段；进行sample操作的LLM不能看到原prompt中SOP、Constraints字段。减少噪声和注意力稀释，防止过拟合。
- **退出门**。LLM没把握就严格输出特定空字符。减少强行输出导致的幻觉。

**enrich申请的接受方案**：

```
enrich申请列表 (按confidence降序)
        │
        ▼
L2_validator.py —— **确定性规则，宽松初筛**（零LLM）
  · 事实一致性：description声称"全部集团处理" → 查树中company字段是否真的全集团
  · 格式校验：sample的L1+L2名是否存在、###call格式是否正确
  · 字符串判重：conversation逐字比对
        │
        ▼
L2_golden_validate.py —— **黄金样本贪心验证**（需LLM，支持多线程）
   1、想要执行此方案，需要一个**黄金小样本**：样本标签严格正确；样本具有足够代表性（能基本反映真实测试集分布）；样本数量精简。
   2、对于全部enrich applications，按照confidence从大到小排序；
   3、先测试原始prompt在黄金样本上的表现（例如90% acc）
   4、对于第i条申请（application），在prompt_{i-1}上接受该变更，得到prompt_i。其中prompt_0为原始prompt。
   5、测试prompt_i在黄金测试集上的表现。如果acc_i不低于acc_{i-1}则认为application_i至少是**无害**或者**有益**的，且与之前已经接受的申请无破坏性冲突。此时接受当前application；如果当前application造成了变更后的prompt在黄金测试集上表现下降，则回退到prompt_{i-1}，不接受当前申请。
   6、全部流程完成后，返回被接受的申请列表。
        │
        ▼
L2_applier.py —— 按照被接受的申请列表将变更写入文法树
        │
        ▼
serialize() → 将语法树编译为可读prompt文本，得到L2层最终产出：enriched_prompt
```

当前黄金样本（golden_samples.json）：
- 101条，来自V2时期throughout测试的batch3(96条)+batch4(5条)
- 32个L1+L2场景全覆盖，每场景3变体（2单轮+1多轮）
- 校验标准：L1+L2分类是否完全匹配

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


**Step5：train on test**
此操作需要训练样本支持。通过训练样本反馈+LLM进行分析和语义微调，优化prompt。

可以采用Step4中的黄金小样本。（因为Step4中黄金小样本只被用作测试，样本本身内容对enrich过程透明）

基本操作：通过LLM微调prompt，最大化该prompt在黄金小样本上的表现。

1、对于某个分类错误的样本sample：
   - L3_extractor：将该sample对应的正确意图、分类器认为的错误意图（包括top candidates）的字段全部提取出来返回。
   - L3_context：将对应相关字段和reviser的prompt拼接为reviser的上下文。
   - L3_reviser：reviser根据输出，进行**受限的最小微调**，目标是让新prompt可以正确分类当前错误sample。

2、在某个错误样本上微调后，先在该样本上运行，若未能改正，则放弃该样本；否则，运行全样本测试，若acc提升，则接受该微调。

**reviser允许进行的受限微调操作范围**：

1、**修改关键词**：对其负责的意图说明中的关键词部分进行修改，包括增加新的关键词强化联系/减少旧的，存在混淆或干扰的关键词。

2、**添加边界反例**：对于某个意图的描述，添加恰当泛化的反例，实现对批判边界的微调。

3、**添加区分规则**：对于某个意图的描述，给出其与另一条易混淆的意图的区分规则。

以上微调操作旨在确保在”不产生全局破坏“的条件下，打磨部分意图判定边界。

其他注意：Step4-5由于涉及LLM，为了测试集上表现的稳定性，防止LLM本身的回答震荡影响对enrich和微调效果的判断，建议设置temp=0。