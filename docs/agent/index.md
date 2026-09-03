# md-editor-models Agent 文档索引

这里是 `md-editor-models` 仓库的 AI / Agent 专属技术文档索引目录。  
**注意**：请按需阅读子目录下的具体文件，不要一次性加载所有文档。

如果在开发过程中有新的记录或规范，请添加在 `docs/agent/` 及其子目录下，并在本文档中更新说明其用途。

---

## 1. 架构方案与 RFC 演进规范 (`architecture/`)

- [**local_ai_model_integration_plan.md**](./architecture/local_ai_model_integration_plan.md)  
  **用途 (RFC-001)**：记录本地小模型的产品边界、技术架构、多档位规划（Lite 0.5B / Standard 1.5B 等）、硬件检测以及专属模型工程微调方案。

- [**app_integration_spec_rfc002.md**](./architecture/app_integration_spec_rfc002.md)  
  **用途 (RFC-002)**：客户端与模型服务间的分发与推理接入协议。包含 `manifest.json` 规范、Special Tokens 字典、Prefix Slot 缓存加速与 GBNF 语法强约束状态机。

- [**gec_enhancement_and_handover_rfc003.md**](./architecture/gec_enhancement_and_handover_rfc003.md)  
  **用途 (RFC-003)**：v1.2.0 GEC 语法纠错端侧强化方案与下一任 Agent 极简交接指南。包含 25,000 条 GEC 扩容、草稿短句切片（冒号纠错）、拼音输入法候选词扰动及 Hard Negative 假阳性压制。

---

## 2. 训练与部署操作指南 (`guides/`)

- [**training_and_deployment_guide.md**](./guides/training_and_deployment_guide.md)  
  **用途**：Google Colab (A100/H100/L4) 极速微调与发版流水线实操手册，涵盖环境自检、LoRA 合并、`Q4_K_M` GGUF 量化与 GitHub Release 自动增量发布。

---

## 3. 全局总索引

- [**../index.md**](../index.md)：项目全局总文档入口与快速启动指引。
- [**adapter_capability_training_release_plan.md**](./architecture/adapter_capability_training_release_plan.md)
  **用途**：记录 Qwen3-0.6B Lite、任务专用 Adapter、Lite/Standard 能力差异、manifest schema、训练数据质量门禁与发布流程。
