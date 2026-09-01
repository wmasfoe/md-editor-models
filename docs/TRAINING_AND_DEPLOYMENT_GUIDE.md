# RFC-001 模型微调、量化与部署完整指南

本指南详细记录了如何按照 **RFC-001 技术架构与实施规范**，完成从**多任务语料构建、SFT 监督微调、质量评测、GGUF 量化**到**接入 md-editor 客户端**的全流程操作。

---

## 目录
1. [RFC-001 多任务协议与优势](#1-rfc-001-多任务协议与优势)
2. [环境准备与依赖安装](#2-环境准备与依赖安装)
3. [步骤一：生成 4 任务平衡数据集](#3-步骤一生成-4-任务平衡数据集)
4. [步骤二：执行 SFT 微调训练 (GPU)](#4-步骤二执行-sft-微调训练-gpu)
5. [步骤三：模型自动化验证与评测](#5-步骤三模型自动化验证与评测)
6. [步骤四：GGUF 转换与 Q4_K_M 量化](#6-步骤四gguf-转换与-q4_k_m-量化)
7. [步骤五：客户端推理参数配置与接入](#7-步骤五客户端推理参数配置与接入)

---

## 1. RFC-001 多任务协议与优势

相较于传统的 JSON Schema 包裹方式，RFC-001 采用**裸流式标签与 FIM (Fill-In-The-Middle)** 范式，具有以下质的突破：

* **行内补全首字延迟压低至 <50ms**：模型在 `<|fim_middle|>` 后直接吐出裸文本，无任何冗余 Token 消耗。
* **极紧凑的任务指令**：`[TASK: GRAMMAR]`、`[TASK: PUNCTUATE]`、`[TASK: PRESERVE]`。
* **100% 保护 Markdown 语法树**：包含 LaTeX（`$$...$$`）、YAML Frontmatter、复杂表格的保真负样本。

---

## 2. 环境准备与依赖安装

本仓库使用 [uv](https://docs.astral.sh/uv/) 进行依赖与虚拟环境管理：

```bash
# 1. 克隆本仓库
git clone https://github.com/wmasfoe/md-editor-models.git
cd md-editor-models

# 2. 安装所有 Python 依赖
uv sync
```

---

## 3. 步骤一：生成 4 任务平衡数据集

运行数据构建脚本，自动生成符合 RFC-001 比例的多任务训练集与验证集：

```bash
uv run python scripts/build_dataset.py
```

* **数据集配比**：
  * `[35%] GEC 语法纠错`：中英文时态、拼写、主谓一致。
  * `[25%] 标点与排版规范`：盘古之白空格、全半角标点、中英弯直引号。
  * `[30%] FIM 行内补全`：基于前缀与后缀的极速中间文本预测。
  * `[10%] 格式保真负样本`：保护 LaTeX、YAML Frontmatter、代码块不被破坏。
* **产物位置**：`data/train.jsonl`（训练集）与 `data/val.jsonl`（验证集）。

---

## 4. 步骤二：执行 SFT 微调训练 (GPU)

> 💡 **算力建议**：微调可放在 **Google Colab (免费 T4)**、**AutoDL (单卡 4090/A10，约 1.5 元/时)** 或本地 NVIDIA 显卡上运行。

### 方式 A：一键启动 (推荐)
```bash
# 默认基于 Qwen/Qwen2.5-0.5B-Instruct 进行 SFT 微调并自动合并权重
./scripts/run_train.sh

# 或指定 1.5B 进阶模型
./scripts/run_train.sh Qwen/Qwen2.5-Coder-1.5B-Instruct
```

### 方式 B：自定义超参数运行
```bash
uv run python train_sft.py \
  --model_name_or_path Qwen/Qwen2.5-0.5B-Instruct \
  --train_file data/train.jsonl \
  --val_file data/val.jsonl \
  --output_dir output/qwen-0.5b-editor-lora \
  --num_train_epochs 3 \
  --batch_size 4 \
  --gradient_accumulation_steps 4 \
  --learning_rate 2e-4 \
  --lora_r 16 \
  --lora_alpha 32 \
  --merge_and_save \
  --merged_output_dir output/qwen-0.5b-editor-merged
```

* **产出物**：`output/qwen-0.5b-editor-merged/`（已合并的完整独立模型目录）。

---

## 5. 步骤三：模型自动化验证与评测

运行评测脚本，测试微调后的模型在多任务下的准确率与格式稳定性：

```bash
uv run python scripts/evaluate.py --model_path output/qwen-0.5b-editor-merged
```

---

## 6. 步骤四：GGUF 转换与 Q4_K_M 量化

使用 [llama.cpp](https://github.com/ggerganov/llama.cpp) 将模型转换为端侧专用的 `Q4_K_M` GGUF 二进制：

```bash
# 1. 编译 llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && cmake -B build && cmake --build build --config Release -j

# 2. 转换为全精度 GGUF (FP16)
python3 convert_hf_to_gguf.py ../output/qwen-0.5b-editor-merged/ --outfile ../output/model-f16.gguf

# 3. 量化为 Q4_K_M (体积仅 ~350MB)
./build/bin/llama-quantize ../output/model-f16.gguf ../output/qwen2.5-0.5b-editor-Q4_K_M.gguf Q4_K_M
```

---

## 7. 步骤五：客户端推理参数配置与接入

在 `md-editor` 客户端（或任何基于 `llama-server` / `llama.cpp` 的宿主）中配置推荐的解码参数：

| 任务场景 | Temperature | Top-P | Max Tokens | Stop Tokens |
| :--- | :--- | :--- | :--- | :--- |
| **行内补全 (Ghost Text)** | `0.2` | `0.85` | `24` | `\n`, `<|fim_end|>`, `` ` `` |
| **语法与病句修复** | `0.0` (Greedy) | `1.00` | `原句长度 + 32` | `\n`, `[TASK:` |
| **标点与排版规范** | `0.0` (Greedy) | `1.00` | `原句长度 + 16` | `\n`, `[TASK:` |
| **段落级扩写/续写** | `0.65` | `0.90` | `128 ~ 256` | `[TASK:`, 用户主动中断 |

### 客户端接入配置示例 (Manifest)
```json
{
  "id": "qwen2.5-0.5b-editor",
  "name": "Lite 0.5B (RFC-001 高速补全版)",
  "version": "1.0.0",
  "sizeBytes": 367001600,
  "downloadUrl": "https://huggingface.co/your-org/md-editor-slm/resolve/main/qwen2.5-0.5b-editor-Q4_K_M.gguf",
  "sha256": "8f9b2c3d4e5f...",
  "recommendedMinRamGb": 4
}
```
