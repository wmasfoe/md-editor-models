# md-editor-models

专用大模型微调与量化仓库，提供给 md-editor 本地 AI 功能使用。

## 模型档位规划

- **Lite 档 (0.5B)**：基于 `Qwen2.5-0.5B-Instruct`
- **Standard 档 (1.5B)**：基于 `Qwen2.5-Coder-1.5B-Instruct`

## 目录结构

- `data/`: 训练与验证数据集 (50k~80k 条中英文 Markdown 语料，包括续写、错别字纠错、Pangu 标点规范等)
- `scripts/`: 数据预处理、SFT 微调、llama.cpp GGUF 量化脚本
- `configs/`: 微调及环境配置参数 (如 unsloth 或 transformers 训练参数)
