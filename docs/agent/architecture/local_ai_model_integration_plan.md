# RFC-001 实施方案：md-editor 端侧垂直小模型 (SLM) 技术架构与微调规范

> **适用目标**：[`wmasfoe/md-editor`](https://github.com/wmasfoe/md-editor) 及通用 Markdown 编辑器  
> **核心基座**：Qwen2.5-0.5B / Qwen2.5-1.5B (GGUF Q4_K_M)  
> **推理环境**：C++ 原生绑定 / `llama-server` (Metal / Vulkan / AVX 加速)  
> **文档状态**：Active Architecture & Training Guide  

---

## 1. 核心目标与服务等级指标 (SLO)

构建**端侧原生、极速响应（<50ms 首字延迟）、低内存占用（<500MB）、零云端依赖**的垂直小语言模型子系统。

| 核心维度 | 指标要求 | 技术实现路径 |
| :--- | :--- | :--- |
| **首字延迟 (TTFT)** | 行内补全 < 50ms；段落纠错 < 150ms | C++ 绑定推理 + KV Cache 前缀缓存 + 局部 FIM 裸文本流式解码 |
| **内存与磁盘开销** | 磁盘 < 400MB (0.5B)；常驻内存 < 500MB | GGUF `Q4_K_M` 量化 + 内存映射 (`mmap`) |
| **排版格式保真度** | 100% 保护 Markdown 标记、代码块、LaTeX 公式 | 构建格式保真负样本微调 + 正则语法边界保护 |
| **数据安全性** | 100% 本地离线执行，零数据外传 | 完全内嵌于桌面端本地主进程 / 本地 Sidecar |

---

## 2. 基座选型决策 (Why Qwen2.5)

| 评估维度 | Qwen2.5 (0.5B / 1.5B) | Gemma 4 (E2B / E4B) | 决策结论 |
| :--- | :--- | :--- | :--- |
| **最小体积/显存** | 0.5B 量化仅 **~350MB**，内存 < 500MB | E2B 内存占用仍超 **1.6GB** | **Qwen 胜出**：极轻量，不挤占编辑器宿主资源 |
| **打字补全延迟** | **30 ~ 60ms**（高吞吐极速响应） | 80 ~ 150ms | **Qwen 胜出**：单字补全对延迟极敏感 |
| **中文与混排排版** | **S 级**（原生覆盖海量中文病句与排版规范） | **A 级**（偏英文/多语言，中文细粒度偏弱） | **Qwen 胜出**：中英混排与错别字先验充分 |
| **FIM 补全与缓存** | 标准 Dense Transformer，KV Cache 命中极稳 | 混合滑动窗口/全局注意力，局部编辑缓存复杂度高 | **Qwen 胜出**：局部反复编辑时缓存命中更高 |

---

## 3. 多任务微调指令协议 (Multi-Task Paradigm)

模型放弃冗长的 JSON 包裹，直接采用紧凑的高吞吐任务标签：

### 3.1 任务一：行内 FIM (Fill-In-The-Middle) 极速补全 (<50ms)
* **Prompt 格式**：
  ```text
  <|fim_prefix|># 部署指南
  在生产环境中运行前，请确保已经执行 <|fim_suffix|> 启动服务。<|fim_middle|>
  ```
* **期望输出**：
  ```text
  `pnpm build` 并使用 pm2<|fim_end|>
  ```

### 3.2 任务二：中英双语语法与病句修复 (GEC)
* **Prompt 格式与示例**：
  ```text
  [TASK: GRAMMAR]
  Input:  尽管系统吞吐量提升了，但是延迟依然非常高因为数据库缺少索引。
  Output: 尽管系统吞吐量提升了，但由于数据库缺少索引，延迟依然非常高。

  Input:  She do not received the confirmation email yesterday and ask for help.
  Output: She did not receive the confirmation email yesterday and asked for help.
  ```

### 3.3 任务三：标点修复与中英排版规范 (Punctuation & Typography)
* **Prompt 格式与示例**：
  ```text
  [TASK: PUNCTUATE]
  Input:  使用react开发桌面端,性能提升了30%以上and fixed all memory leaks.
  Output: 使用 React 开发桌面端，性能提升了 30% 以上 and fixed all memory leaks.
  ```

### 3.4 任务四：Markdown / LaTeX / 表格格式保真 (Preservation)
* **规则**：遇到 LaTeX 公式（`$$...$$`）、Frontmatter YAML、Markdown 表格时，严格保持原有结构，禁止破坏。

---

## 4. 训练数据集配比（目标：10 万条）

```
┌─────────────────────────────────────────────────────────────┐
│                   100k SFT Dataset 配比                     │
│  ┌──────────────────────┬──────────────────────┐           │
│  │ GEC 语法纠错 (35%)   │ FIM 行内补全 (30%)   │           │
│  ├──────────────────────┼──────────────────────┤           │
│  │ 标点排版规范 (25%)   │ 格式保真负样本 (10%) │           │
│  └──────────────────────┴──────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

1. **中英双语语法纠错 (GEC) [35%]**：MuCGEC、NLPCC-2018、BEA-2019、JFLEG 以及针对技术文档合成的语料。
2. **中英标点与排版规范 [25%]**：高质量开源 Markdown README / 技术博客，脚本自动化扰动生成全半角、大小写、中英文空格样本。
3. **Markdown FIM 补全语料 [30%]**：覆盖标题、列表、代码块、表格、段落，随机在 10%~90% 位置切分 Prefix/Suffix。
4. **格式保真负样本 [10%]**：包含复杂 Markdown 表格、LaTeX 公式、YAML Frontmatter，确保无损复现。

---

## 5. 推理工程与解码参数规范

| 场景 | Temperature | Top-P | Max Tokens | Stop Tokens |
| :--- | :--- | :--- | :--- | :--- |
| **行内补全 (Ghost Text)** | `0.2` | `0.85` | `24` | `\n`, `<|fim_end|>`, `` ` `` |
| **语法与病句修复** | `0.0` (Greedy) | `1.00` | `原句长度 + 32` | `\n`, `[TASK:` |
| **标点与排版规范** | `0.0` (Greedy) | `1.00` | `原句长度 + 16` | `\n`, `[TASK:` |
| **段落级扩写/续写** | `0.65` | `0.90` | `128 ~ 256` | `[TASK:`, 用户主动中断 |
