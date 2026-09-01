# md-editor-models 端侧垂直小模型 (SLM)

> 基于 **RFC-002** 规范的端侧 Markdown 写作、多语种纠错、排版规范与极速 FIM 补全小模型矩阵。

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/wmasfoe/md-editor-models/blob/master/notebooks/train_and_release_t4.ipynb)

本仓库专注于 **Qwen2.5 (0.5B / 1.5B)** 的多任务 SFT 微调、格式保真与 GGUF 量化。产出的模型专为端侧极速响应打造（首字延迟 **<30ms**，量化体积 **<250MB**，内存占用 **<300MB**），可直接接入 [md-editor](https://github.com/wmasfoe/md-editor) 或任何基于 `llama-server` 的端侧应用。

---

## ⚡ 免费 T4 GPU 一键训练与发布 (Google Colab)

无需本地高配显卡，点击上方 👆 **[Open in Colab]** 徽标，即可在 Google 提供的免费 **T4 GPU** 上一键启动全流程流水线：
* 自动拉取代码与多任务数据集；
* 执行 SFT 多任务微调（0.5B 模型约 **15 分钟** 跑完 3 个 Epoch）；
* 自动量化为 GGUF `Q4_K_M`；
* 自动计算 SHA256 与字节数，生成 `manifest.json`；
* 自动调用 GitHub API 发布到 **GitHub Releases**！

---

## 🌟 核心能力 (RFC-002 多任务体系)

1. **行内 FIM 极速补全 (<30ms)**：基于 `<|fim_prefix|>` 与 `<|fim_suffix|>` 的裸流式解码，彻底告别 JSON 延迟。
2. **中英日韩俄法（6语种）语法纠错**：采用标准紧凑元组 JSON（`[[start, end, "orig", "repl"], ...]`）输出。
3. **标点与排版规范化**：自动修复中英文空格（盘古之白）、全半角标点、中英弯直引号、破折号与省略号。
4. **Markdown 格式硬保真**：对 LaTeX 公式（`$$...$$`）、YAML Frontmatter、复杂表格进行无损结构保护。

---

## 📂 项目结构

```
md-editor-models/
├── data/
│   ├── train.jsonl               # 训练集 (9,631 条 6 语种多任务平衡样本)
│   └── val.jsonl                 # 验证集 (1,071 条用于评测)
├── docs/
│   ├── APP_INTEGRATION_SPEC_RFC002.md   # 📖 RFC-002 客户端对接与实施终极规范
│   └── TRAINING_AND_DEPLOYMENT_GUIDE.md # 📖 微调、量化与部署手册
├── notebooks/
│   └── train_and_release_t4.ipynb# 🚀 Google Colab 免费 T4 一键训练与发布 Notebook
├── scripts/
│   ├── build_dataset.py          # 多任务数据生成与清洗脚本
│   ├── release_model.sh          # 🚀 一键微调、量化与 GitHub Release 发布流水线
│   └── evaluate.py               # 自动化多任务评测脚本
├── train_sft.py                  # 基于 HuggingFace TRL + PEFT 的 SFT 核心训练代码
└── pyproject.toml                # uv 依赖管理配置
```

---

## 🚀 命令行一键运行 (在已有 GPU 的机器上)

```bash
# 1. 克隆并安装依赖
git clone https://github.com/wmasfoe/md-editor-models.git
cd md-editor-models && uv sync

# 2. 一键训练、量化并发布到 GitHub Release
./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-0.5B-Instruct
```

---

## 📖 详细规范文档
* 👉 [RFC-002 客户端对接实施终极规范 (docs/APP_INTEGRATION_SPEC_RFC002.md)](docs/APP_INTEGRATION_SPEC_RFC002.md)
* 👉 [微调、量化与部署操作指南 (docs/TRAINING_AND_DEPLOYMENT_GUIDE.md)](docs/TRAINING_AND_DEPLOYMENT_GUIDE.md)
