# Changelog

All notable changes to the `md-editor-models` project will be documented in this file.

---

## 1.3.0 - 2026-09-03

### 🚀 架构重大升级：纯 LoRA 增量适配器矩阵（Base + Adapter）

- **纯 LoRA Delta 架构落地**：彻底摒弃任务扩展词表与 `modules_to_save` 导致的全量权重冗余，任务控制标记（如 `<|task_gec_zh|>`）作为原生 BPE 文本参与训练与推理，产物恢复为标准 llama.cpp LoRA GGUF。
- **极致轻量产物**：每个任务 Adapter（GEC 纠错、Completion 行内续写、Distill 摘要提炼）体积骤降至 **~38.5 MB**（f16），相比合并大模型体积缩减 **95% 以上**。后续模型功能更新只需分发几十兆补丁，用户无需重复下载基座。
- **Lite + Standard 双档位矩阵**：
  - **Lite 档位**：官方高精度 `Qwen3-0.6B-Q8_0` 基座（~609 MB）+ 3 个 38.5 MB 任务 LoRA 适配器；
  - **Standard 档位**：官方高精度 `Qwen3-1.7B-Q8_0` 基座（~1.75 GB）+ 对应 1.7B 任务 LoRA 适配器；
  - **Pro 档位**：在 Manifest 中保留显式占位与可用性门禁（`isAvailable: false`）。

### 📊 RFC-003 数据集质量重构

- **数据集严格去重与零泄漏隔离**：清洗原始 5.4 万条语料至 4.7 万条高质量样本；训练集（42,561 条）与验证集（4,729 条）完全按文档级隔离切分，实现训练集与验证集**样本零重叠**，消除数据穿越风险。
- **拼音输入法同音字错别字增强**：注入高频中文打字翻车同音/近音混淆表（如「瀛该→应该」、「布署→部署」），显著提升拼音输入场景下的错别字捕获率。
- **假阳性抑制与专业术语保护（Hard Negative）**：增加对 LoRA、GGUF、Tauri、React、PyTorch 等中英文技术术语、路径、URL 与 Markdown 语法结构的保护样本，杜绝过度纠错。
- **草稿短句负样本**：注入 20% 未完结的短句与冒号/破折号结尾片段，根除“检测到冒号误触发文章续写”的漂移问题。

### ⚙️ 训练与流水线工程优化

- **显存与硬件自适应批处理**：`release_model.sh` 支持自动探测 GPU 物理显存（A100/H100、L4/3090、T4）；全局严格维持 **等效批大小 = 64**（A100 采用 `BS=64, Accum=1` 满血单步吞吐，L4/T4 采用分级累积），数学计算完全等价，彻底根除 1.7B 模型的显存溢出（OOM）隐患。
- **2 Epoch 最佳收敛与防过拟合**：LoRA 微调轮数设为 2 轮，总步数从 1197 步压缩至 798 步，训练耗时缩短 33% 的同时降低模板记忆与误报率。
- **支持自动断点续训**：`train_sft.py` 接入 `get_last_checkpoint`，训练中断后自动接续最近中间检查点，无需从第 0 步重跑。
- **Manifest v2 增量合并流水线**：发版时自动拉取远端已发布的 `manifest.json` 进行同版本增量合入，避免跨资产发布时覆盖丢失已累积的 capabilities。

---

## 1.2.0 - 2026-09-03

### 🌟 核心特性

- **Qwen3 基座探索与迁移**：确定 `Qwen/Qwen3-0.6B` 与 `Qwen/Qwen3-1.7B` 作为新一代端侧 SLM 候选基座，具备原生 32K 上下文支持与更优的多语言代码理解能力。
- **免 C++ 编译官方 Base 发布流程**：Base 资产直接采用 Qwen 官方发布的 `Q8_0` GGUF，彻底摒弃在 Colab 等临时环境中 cmake 本地编译 `llama-quantize` 的复杂链路，提升发布可靠性。
- **Manifest Schema v2 规范建立**：重构模型清单规范，单模型条目拆分为 `base` 与 `capabilities`（GEC / Completion / Distill 等能力映射）。
- **发布脚本实时诊断增强**：`release_model.sh` 开启管道实时日志合流（`bufsize=1` 与 pipefail），提供执行阶段诊断输出，避免长耗时任务被误判为卡死。

---

## 1.1.0 - 2026-09-02

### 🌟 核心特性

- **多模型档位矩阵初步成型**：
  - Lite 档位：`qwen2.5-0.5b-editor`（~380 MB，Q4_K_M）
  - Standard 档位：`qwen2.5-1.5b-editor`（~940 MB，Q4_K_M）
- **RFC-002 均衡数据集发布**：
  - 构建包含 51,377 条真实样本的微调数据集，平衡 GEC 纠错与 FIM 补全比例；
  - 引入 `<|task_distill|>` 滚动提炼控制标记，支持文档渐进式摘要上下文注入。
- **训练性能优化**：
  - 接入 SDPA（Scaled Dot-Product Attention）硬件加速，适配 NVIDIA L4 优化原生批次（`batch_size=32/16`），微调耗时大幅缩减至 50 分钟内。
- **Manifest 自动化合并**：支持单脚本多次运行自动汇总多模型条目至统一 `manifest.json`。

---

## 1.0.0 - 2026-09-01

### 🚀 初始里程碑发布

- **端侧微调流水线建立**：首次跑通基于 `Qwen/Qwen2.5-0.5B-Instruct` 的 LoRA 微调、权重合并与 llama.cpp GGUF 量化全链路。
- **RFC-002 任务控制协议固化**：在 Tokenizer 注册 `<|task_gec_zh|>`, `<|task_gec_en|>`, `<|task_punc|>`, `<|task_preserve|>`, `<|fim_prefix|>`, `<|fim_suffix|>`, `<|fim_middle|>`, `<|fim_end|>` 等控制符。
- **输出格式规范化**：训练模型遵循紧凑元组 JSON Diff 格式输出（`[[start, end, "orig", "repl"], ...]`），消除解释性闲聊。
- **发布与集成**：发布首版 `qwen2.5-0.5b-editor-v1.0.0-Q4_K_M.gguf` 及 Manifest 文件，正式集成至 `md-editor` 桌面客户端。
