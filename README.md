# md-editor-models 端侧垂直小模型 (SLM)

> 基于 **RFC-001** 规范的端侧 Markdown 写作、纠错、排版与极速 FIM 补全小模型矩阵。

本仓库专注于 **Qwen2.5 (0.5B / 1.5B)** 的多任务 SFT 微调、格式保真与 GGUF 量化。产出的模型专为端侧极速响应打造（首字延迟 **<50ms**，量化体积 **<400MB**，内存占用 **<500MB**），可直接接入 [md-editor](https://github.com/wmasfoe/md-editor) 或任何基于 `llama-server` / `llama.cpp` 的端侧应用。

---

## 🌟 核心能力 (RFC-001 多任务体系)

1. **行内 FIM 极速补全 (<50ms)**：基于 `<|fim_prefix|>` 与 `<|fim_suffix|>` 的裸流式解码，彻底告别 JSON 延迟，带来丝滑的 Ghost Text 体验。
2. **中英双语语法与病句修复 (GEC)**：精准修正中英文时态、主谓一致、语序不当与错别字。
3. **标点与排版规范化**：自动修复中英文空格（盘古之白）、全半角标点、中英弯直引号、破折号与省略号。
4. **Markdown 格式保真**：对 LaTeX 公式（`$$...$$`）、YAML Frontmatter、复杂表格进行无损结构保护。

---

## 📊 数据集配比 (10 万条规划)

```
┌─────────────────────────────────────────────────────────────┐
│                 RFC-001 SFT Multi-Task 数据配比             │
│  ├── [35%] GEC 语法与病句纠错 (中英文双语)                   │
│  ├── [25%] 标点与排版规范 (盘古之白 / 全半角标点)           │
│  ├── [30%] FIM 行内极速补全 (Prefix / Suffix 预测)          │
│  └── [10%] 格式保真负样本 (LaTeX / Frontmatter / 表格)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 项目结构

```
md-editor-models/
├── data/
│   ├── train.jsonl               # 训练集 (8,519 条 4 任务平衡样本)
│   └── val.jsonl                 # 验证集 (947 条用于评测)
├── docs/
│   ├── TRAINING_AND_DEPLOYMENT_GUIDE.md  # 📖 RFC-001 完整微调与部署手册
│   └── agent/architecture/               # 架构设计与 RFC 规范
├── scripts/
│   ├── build_dataset.py          # RFC-001 多任务数据生成与清洗脚本
│   ├── run_train.sh              # GPU 一键微调与权重合并脚本
│   └── evaluate.py               # 自动化多任务评测脚本
├── train_sft.py                  # 基于 HuggingFace TRL + PEFT 的 SFT 核心训练代码
└── pyproject.toml                # uv 依赖管理配置
```

---

## 🚀 快速上手 (Quick Start)

### 1. 安装依赖
```bash
uv sync
```

### 2. 生成 RFC-001 多任务平衡数据集
```bash
uv run python scripts/build_dataset.py
```

### 3. 在 GPU 算力机上一键启动 SFT 微调
```bash
./scripts/run_train.sh Qwen/Qwen2.5-0.5B-Instruct
```

### 4. 转换与量化为 GGUF
```bash
python llama.cpp/convert_hf_to_gguf.py output/qwen-0.5b-writing-merged/ --outfile model-f16.gguf
llama-quantize model-f16.gguf qwen2.5-0.5b-editor-Q4_K_M.gguf Q4_K_M
```

---

## 📖 详细操作指南
关于在 Google Colab / AutoDL 上训练、推理参数配置表（Greedy vs Sampling）、KV Cache 复用及客户端接入细节，请参阅：  
👉 [RFC-001 微调、量化与部署完整指南 (docs/TRAINING_AND_DEPLOYMENT_GUIDE.md)](docs/TRAINING_AND_DEPLOYMENT_GUIDE.md)
