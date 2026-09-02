# md-editor-models 文档中心 (Documentation Portal)

欢迎来到 [`wmasfoe/md-editor-models`](https://github.com/wmasfoe/md-editor-models) 核心技术文档中心。

本仓库专为 [`md-editor`](https://github.com/wmasfoe/md-editor) 及现代桌面 Markdown 编辑器研发**端侧原生、首字极速响应 (<30ms)、低内存占用 (<300MB)、零云端依赖**的垂直小语言模型 (SLM)。

---

## 📚 核心文档索引导航

### 1. 架构方案与 RFC 演进规范 (`docs/agent/architecture/`)

| 规范文档 | 版本状态 | 核心内容概述 |
| :--- | :--- | :--- |
| [**RFC-001: 端侧小模型架构与基座设计**](./agent/architecture/local_ai_model_integration_plan.md) | `v1.0.0` (Active) | 基座选型 (Qwen2.5)、SLO 服务等级指标、C++ 原生推理架构设计 |
| [**RFC-002: 客户端多模型分发与推理接入规范**](./agent/architecture/app_integration_spec_rfc002.md) | `v1.1.0` (Active) | 多模型矩阵 (Lite/Standard)、`manifest.json` 协议、GBNF 状态机约束 |
| [**RFC-003: v1.2.0 GEC 语法纠错强化与接力发版规范**](./agent/architecture/gec_enhancement_and_handover_rfc003.md) | `v1.2.0` (Target) | 生产环境反馈对齐：草稿短句切片、拼音输入法同音词扰动、Hard Negatives |

---

### 2. 训练与运维部署指南 (`docs/agent/guides/`)

| 操作指南 | 适用环境 | 核心内容概述 |
| :--- | :--- | :--- |
| [**Google Colab 极速微调与一键发版指南**](./agent/guides/training_and_deployment_guide.md) | NVIDIA A100 / L4 / T4 | 一键微调流水线、自动权重合并、Q4_K_M GGUF 量化与 GitHub Release 同步 |

---

### 3. AI Agent 专项规范 (`docs/agent/`)

* [**Agent 专项文档索引 (`docs/agent/index.md`)**](./agent/index.md)：为 AI Agent 专属定制的任务上下文导航与开发守则。

---

## 🚀 快速启动指南

### 训练与发版流水线
```bash
# 1. 自动构建 RFC-003 终极增强版平衡数据集
python3 scripts/build_dataset.py

# 2. 一键执行微调、量化与 GitHub Release 发布
./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-0.5B-Instruct
./scripts/release_model.sh v1.2.0 Qwen/Qwen2.5-Coder-1.5B-Instruct
```
