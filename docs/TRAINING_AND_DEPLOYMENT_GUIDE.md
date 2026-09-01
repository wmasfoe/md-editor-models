# md-editor-models 微调、量化与部署全流程手册 (RFC-002 终极版)

> 本指南专为模型微调工程开发人员设计，涵盖从**多领域真实开源语料构建**、**ChatML + `<|task_distill|>` SFT 微调**、**llama.cpp Q4_K_M 量化** 到 **GitHub Releases 自动化发版** 的完整工业级闭环流程。

---

## 1. 核心架构与多任务规范

模型微调基于 **Qwen2.5-0.5B / 1.5B**，通过固化专用控制符与注入 `[Document Context]` 实现端侧写作辅助：

| 任务类型 | 控制 Token | 输入格式 | 目标输出格式 |
| :--- | :--- | :--- | :--- |
| **异步文档提炼** | `<|task_distill|>` | 前 800 字内容或标题大纲 | `主题：...；领域：...；风格：...` (<=30字) |
| **行内 FIM 续写** | `<|task_completion|>` + FIM | ChatML System + `<|fim_prefix|>...<|fim_suffix|>` | `<|fim_middle|>...<|fim_end|>` (10~30字) |
| **语法与错字纠错** | `<|task_gec_zh|>` 等 | 待检测句子 | `[[start, end, "orig", "repl"]]` (无错输出 `[]`) |
| **标点排版规范** | `<|task_punc|>` | 待排版句子 | 盘古之白与全半角替换元组 JSON |

---

## 2. 语料 1:1 双轨平衡与真实数据源

**100% 拒绝人工模板！** 语料直接流式对接国际权威开源数据集：
* **50% 日常生活通用写作**：`wikimedia/wikipedia` (多语种生活常识/历史/艺术)、`BelleGroup/train_1M_CN` (日常随笔/游记/办公周报/食谱)；
* **50% 专业技术工程写作**：`bigcode/the-stack-v2` / `codeparrot/github-code` (GitHub 真实 Markdown)、`HuggingFaceTB/smollm-corpus` (技术教程/架构指南)。

---

## 3. 本地环境准备 (uv)

本项目使用现代 Python 包管理器 `uv` 进行极速依赖管理：

```bash
# 1. 克隆代码仓库
git clone https://github.com/wmasfoe/md-editor-models.git
cd md-editor-models

# 2. 安装 uv (如未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 一键同步全套依赖 (PyTorch, TRL, PEFT, llama.cpp 依赖)
uv sync
```

---

## 4. 构建真实平衡数据集 (`scripts/build_dataset.py`)

```bash
# 执行多领域数据流式抽取与 AST 大纲切分
uv run python scripts/build_dataset.py
```
* **产物**：
  * `data/train.jsonl` (~22,500 条)
  * `data/val.jsonl` (~2,500 条)

---

## 5. 一键训练、量化与发布到 GitHub Releases

### 5.1 在 Google Colab (L4 GPU / T4 GPU) 上一键运行
直接打开 Notebook 运行即可：
👉 **[Open in Colab](https://colab.research.google.com/github/wmasfoe/md-editor-models/blob/master/notebooks/train_and_release_t4.ipynb)**

### 5.2 在任意 GPU 服务器命令行上运行
```bash
# 发布 0.5B 轻量极速版
./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-0.5B-Instruct

# 发布 1.5B 高精度进阶版 (自动增量追加到同一 Release)
./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-Coder-1.5B-Instruct
```

---

## 6. 模型产物校验与评测

运行自动化测试脚本，验证 GEC 语法纠错、无错误快速终止、FIM 续写以及 `<|task_distill|>` 的准确率：

```bash
uv run python scripts/evaluate.py --model_path output/qwen-editor-merged
```
