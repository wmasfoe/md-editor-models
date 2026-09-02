# RFC-003: v1.2.0 端侧小模型全矩阵增强与交接落地规范文档
> **文档版本**：v1.2.0-Draft  
> **所属仓库**：[`wmasfoe/md-editor-models`](https://github.com/wmasfoe/md-editor-models)  
> **面向对象**：后续接力 Agent、算法工程师、客户端（`md-editor`）开发团队  
> **创建时间**：2026-09-02  

---

## 1. 背景与客户端生产环境测试反馈

在 `md-editor` 客户端生产环境联调测试中，基于 `v1.1.0` 模型矩阵的实测表现如下：

### 🟢 验证通过的优秀能力：
1. **长句及标准语境语法纠错 100% 精准**：如 *“波顿在巴林告诉记者说...可玫击莫国...”* 能稳定产出紧凑元组 JSON Diff。
2. **GBNF 状态机强约束有效**：客户端通过 GBNF 语法规则强行限定模型仅能输出合法 JSON，彻底杜绝了模型吐出自然语言闲聊废话。

### 🔴 发现的极端边缘场景痛点：
1. **草稿短句 + 冒号边界模糊**：用户刚打完半句话带冒号（如 *“那下一步瀛该是：”*），模型易将其误认为文章大纲进而倾向于“往下续写”，在 GBNF 约束下会退化输出 `[]`；
2. **拼音输入法同音/近音错选（“瀛该 ➔ 应该”）**：中文日常打字 95% 为输入法候选词误选，训练集中此类同音字覆盖需进一步扩大；
3. **多任务数据配比失衡**：旧数据集中 FIM 续写占 1.6 万条，而 GEC 语法纠错仅 5,000 条，导致任务注意力先验向续写倾斜。

---

## 2. v1.2.0 六大核心增强体系 (3 大客户端反馈 + 3 项专家级优化)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   RFC-003 v1.2.0 终极多任务数据增强全景图                         │
├──────────────────────────┬──────────────────────────┬────────────────────────────┤
│ 1. GEC 样本大幅扩充 (45%) │ 2. 草稿短句与末尾冒号切片 │ 3. 中文拼音输入法扰动引擎   │
│ 扩至 25,000+ 条真实语料  │ 5~15字从句+冒号/破折号   │ 精准覆盖同音候选字选错     │
├──────────────────────────┼──────────────────────────┼────────────────────────────┤
│ 4. Markdown 语法纠错强化 │ 5. 技术专有名词防误改负样本│ 6. 多尺度 (200~650) FIM 续写 │
│ 标题空格、代码闭合、加粗 │ 压制 LoRA/Tauri/GGUF 假阳性│ 系统提示词 + 前缀缓存加速  │
└──────────────────────────┴──────────────────────────┴────────────────────────────┘
```

### 升级 1：大幅扩充 GEC 真实语料库（25,000+ 条）
* **数据来源**：`shibing624/CSC`（汇聚 SIGHAN 2013/2014/2015、Wang271k、ECSpell）；
* **配比调整**：GEC 在多任务中的占比由原来的 15% 提升至 **45%**。

### 升级 2：注入 20%「5~15 字草稿短句与片段」
* **原理**：专门切片带有末尾冒号（`：`）、破折号（`——`）、逗号（`，`）的未完结片段（如 *“那下一步瀛该是：”* ➔ `[[4, 5, "瀛", "应"]]`）；
* **目标**：让模型在残缺片段下形成铁律条件反射——看到 `<|task_gec_zh|>`，哪怕以冒号结尾也坚决输出 JSON Diff，绝不续写。

### 升级 3：真实文章底色 + 拼音输入法候选词扰动引擎
* **机制**：通过 `inject_pinyin_homophone_typos()` 函数，对真实文章中的高频词以 60% 概率替换为真实输入法高频错选词（如 `应该 ➔ 瀛该/因该`、`部署 ➔ 布署`、`必须 ➔ 必需`、`知识 ➔ 只识`、`登录 ➔ 登陆` 等）。

### 升级 4：Markdown 语法与格式纠错
* 覆盖 `#标题` 缺少空格、`**加粗*` 未配对、`` `行内代码 `` 未闭合、`-列表` 缺少空格等 Markdown 原生语法失误。

### 升级 5：技术专有名词假阳性抑制（Hard Negatives）
* 注入包含 `LoRA`, `GGUF`, `Tauri`, `React`, `PyTorch`, `llama.cpp`, `Next.js`, `SFT` 的正确句子，目标输出严格为 `[]`，防止模型过度纠错。

### 升级 6：多尺度 (Multi-Scale) 动态 FIM 极速续写
* 保持 `200~650` 字符动态前缀窗口与 `[User Style Profile]` System Prompt，兼顾局部衔接与长篇深度逻辑。

---

## 3. 架构落地与代码清单

### 1. 数据集构建脚本：[`scripts/build_dataset.py`](file:///home/debian/code/md-editor-models/scripts/build_dataset.py)
* **运行命令**：`python3 scripts/build_dataset.py`
* **产物输出**：
  * `data/train.jsonl` (~45,000 条高质量平衡样本)
  * `data/val.jsonl` (~5,000 条验证样本)

### 2. SFT 训练与合并：[`train_sft.py`](file:///home/debian/code/md-editor-models/train_sft.py)
* **优化特性**：
  * NVIDIA A100 (40GB/80GB) 满血参数：`batch_size=64`, `gradient_accumulation_steps=1`；
  * `dataloader_num_workers=4`，`bf16=True`，PyTorch 2.x 原生 `sdpa` 注意力加速；
  * 余弦退火学习率调度（Cosine Decay, `lr=3e-4`）；
  * LoRA 全线性层覆盖：`r=32`, `alpha=64`。

### 3. 一键量化与发版流水线：[`scripts/release_model.sh`](file:///home/debian/code/md-editor-models/scripts/release_model.sh)
* **用法**：`./scripts/release_model.sh [VERSION] [BASE_MODEL]`
* **示例**：
  * 微调并发布 0.5B Lite：`./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-0.5B-Instruct`
  * 微调并发布 1.5B Standard：`./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-Coder-1.5B-Instruct`
* **自动发布逻辑**：
  * 自动将 LoRA 权重与基座合并；
  * 编译 llama.cpp 并执行 `Q4_K_M` 极致量化；
  * 自动增量更新 `manifest.json`；
  * 自动创建 GitHub Release 并上传模型资产。

---

## 4. 下一任 Agent / 工程师极简接力执行指南

如果你是接力本任务的 Agent 或工程师，触发 `v1.2.0` 全自动训练与发版只需执行以下 2 步：

```bash
# 步骤 1: 重新构建 RFC-003 数据集
python3 scripts/build_dataset.py

# 步骤 2: 在 A100 GPU 环境上一键发版 v1.2.0
./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-0.5B-Instruct
./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-Coder-1.5B-Instruct
```

---

## 5. 附录：客户端 Special Tokens 规范速查

| 控制符 | 任务类型 | 输入格式示例 | 预期输出格式 |
| :--- | :--- | :--- | :--- |
| `<|task_gec_zh|>` | 纯中文纠错 | `<|task_gec_zh|>那下一步瀛该是：` | `[[4, 5, "瀛", "应"]]` |
| `<|task_gec_mixed|>` | 中英混排纠错 | `<|task_gec_mixed|>调用了inovke方法` | `[[3, 9, "inovke", "invoke"]]` |
| `<|task_completion|>` | 行内 FIM 续写 | `<|fim_prefix|>前缀<|fim_suffix|>后缀<|fim_middle|>` | `补全内容<|fim_end|>` |
| `<|task_distill|>` | 滚动语义提炼 | `<|task_distill|>\n【文档标题】...` | `主题：...；要点：...` |
| `<|task_preserve|>` | 格式保真 | `<|task_preserve|>$$E=mc^2$$` | `[]` |
