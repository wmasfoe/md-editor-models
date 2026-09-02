# Adapter 能力矩阵、Qwen3 Lite 与训练发布方案

> 状态：方案确认，训练/发布代码尚未改造
>
> 适用范围：`md-editor-models` 的 Qwen3-0.6B Lite、任务专用 Adapter、模型资产 manifest 与发布流程。
>
> 客户端对应文档：`md-editor/docs/agent/architecture/local_ai_task_adapter_architecture.md`

## 1. 当前阶段目标

当前只聚焦本地能力：

```text
GEC 修复建议
Completion 续写
文档总结
用户风格分析（逐步增加）
```

端云协作只在架构扩展部分提及，不影响本阶段训练和发布。

产品对用户只暴露：

```text
Lite
Standard
```

Adapter 是内部实现细节，不在用户界面展示。

## 2. Qwen3-0.6B Lite 决策

Qwen3-0.6B 作为 Lite 基座进入训练验证，理由：

- 参数规模接近当前 Lite，适合保持端侧定位。
- 官方模型卡标注原生 32K 上下文；客户端当前仍可保持 8K 配置。
- 官方提供 `Qwen3-0.6B-GGUF`，llama.cpp 部署路径可复用。
- Qwen 系列对中文、英文、代码和 GGUF 生态有综合适配性。
- Qwen3 支持 thinking / non-thinking，需要在 GEC 推理时明确关闭 thinking。

参考：

- https://huggingface.co/Qwen/Qwen3-0.6B
- https://huggingface.co/Qwen/Qwen3-0.6B-GGUF

注意：Qwen3-0.6B 目前只是新的 Lite 候选基座。只有完成同数据、同协议、同测试集的 A/B 后，才能替换生产 Lite。

## 3. 任务 Adapter 矩阵

一个选中的 Model Tier 使用一个 Base，但可以拥有多个任务 Adapter：

```text
Lite Base：Qwen3-0.6B
    ├── GEC Adapter
    ├── Completion Adapter
    ├── Distill Adapter（可选）
    └── Style Analysis Adapter（可选）
```

Standard 可以拥有不同能力集合：

```text
Standard Base：Qwen3-1.5B
    ├── GEC Adapter
    ├── Completion Adapter
    ├── Distill Adapter
    └── Style Analysis Adapter
```

Lite 和 Standard 不要求拥有完全相同的 Adapter。Lite 缺少某个能力时，manifest 必须明确记录为不可用；客户端不能静默使用错误 Adapter 替代。

任务类型与实际 Adapter ID 分离：

```text
任务：Gec
Lite → qwen3-0.6b-gec
Standard → qwen3-1.5b-gec
```

这样训练产物可以变化，客户端业务协议不需要变化。

## 4. 训练产物组织

同一个 Base 的任务 Adapter 共享 Base 文件：

```text
qwen3-0.6b-base-v1.2.0.gguf
qwen3-0.6b-gec-adapter-v1.2.0.gguf
qwen3-0.6b-completion-adapter-v1.2.0.gguf
qwen3-0.6b-distill-adapter-v1.2.0.gguf
```

Adapter 不是独立模型，必须与兼容的 Base 一起使用。

每个 Adapter 必须记录：

```text
adapterId
adapterVersion
baseModelId
baseModelVersion
baseSha256
adapterSha256
trainingDataVersion
taskKind
promptProtocolVersion
grammarProtocolVersion
```

如果最终为了生产简单性将 Adapter 合并成完整 GGUF，训练产物仍然应保留 Adapter 元数据，便于复现和后续发布。

## 5. 模型 manifest 目标

manifest 从当前“一个 model entry = 一个完整 GGUF”逐步扩展为：

```json
{
  "schemaVersion": 2,
  "version": "v1.2.0",
  "contextSize": 8192,
  "models": [
    {
      "modelId": "md-editor-writer-lite",
      "tier": "lite",
      "displayName": "Lite",
      "base": {
        "id": "qwen3-0.6b-base",
        "version": "v1.2.0",
        "filename": "qwen3-0.6b-base-v1.2.0.gguf",
        "sizeBytes": 0,
        "sha256": "...",
        "downloadUrl": "..."
      },
      "capabilities": {
        "gec": {
          "adapterId": "qwen3-0.6b-gec",
          "version": "v1.2.0",
          "filename": "qwen3-0.6b-gec-adapter-v1.2.0.gguf",
          "sizeBytes": 0,
          "sha256": "...",
          "downloadUrl": "...",
          "promptProtocol": "gec-v2",
          "grammar": "tuple-diff"
        },
        "completion": null,
        "distill": null,
        "style-analysis": null
      }
    }
  ]
}
```

发布脚本必须实际读取文件计算 `sizeBytes` 和 SHA256，不能从模型名称或旧 manifest 复制。

## 6. 当前训练仓库需要改动的地方

### 6.1 基座参数

当前 `train_sft.py` 默认基座仍是：

```text
Qwen/Qwen2.5-0.5B-Instruct
```

Qwen3 Lite 训练需要通过参数切换到：

```text
Qwen/Qwen3-0.6B
```

不能只改文件名，还要验证：

- tokenizer Chat Template
- thinking 开关
- assistant 起始/结束 Token
- 特殊 Token 是否独立编码
- llama.cpp GGUF 转换
- GBNF 从首 Token 开始是否生效

### 6.2 任务专用训练入口

当前训练脚本是一个多任务 SFT 入口。后续至少需要支持：

```text
--task gec
--task completion
--task distill
--task style-analysis
```

或者使用统一数据集但按 task 配置不同采样比例和输出目录。

每个 Adapter 必须有清晰的：

```text
base_model
train_file
validation_file
output_dir
adapter_id
prompt_protocol
```

### 6.3 特殊 Token 的保存风险

当前脚本会新增特殊 Token 并 `resize_token_embeddings`，但 LoRA 配置只指定了线性层 target modules。后续训练 Qwen3 前必须验证新增 Token 的 embedding / lm_head 是否训练并随产物保存。

重点检查是否需要：

```python
modules_to_save=["embed_tokens", "lm_head"]
```

实际模块名必须根据 Qwen3 模型结构确认。重新加载 merged model 和 GGUF 后必须再次验证任务 Token。

### 6.4 数据集重建和质量门禁

当前工作区实测数据为：

```text
data/train.jsonl：32,310 条
data/val.jsonl：3,590 条
```

当前训练集实测存在约 26.1% 精确重复行，主要来自固定模板、Hard Negative 和 Preserve 样本重复扩展。

训练 Qwen3 前必须：

1. 重新运行当前 RFC-003 数据构建逻辑；
2. 对最终样本做 exact dedup 和 near dedup；
3. 按原始文档/来源先切分 train、validation、test，再做扰动增强；
4. 限制固定模板重复次数；
5. 增加真实 Markdown / MDX、代码、配置和技术文档样本；
6. 增加真实误报样本和专业词保护样本；
7. 检查 `pangu` 中英空格策略是否符合产品风格；
8. 检查 Distill 目标，减少固定模板式摘要；
9. 给每条样本保留 source、task、augmentation、source_id 等元数据。

### 6.5 GEC 训练目标

GEC Adapter 的目标必须保持：

```text
看到 GEC 任务标记就只输出紧凑 Diff JSON
没有错误就输出 []
不解释
不续写
不修改代码、URL、路径、版本号和专业术语
```

GEC 验证集需要覆盖：

- 中文同音/近音候选词
- 草稿短句和冒号结尾
- 多错误
- 正确文本负样本
- 中英混排
- Markdown 语法
- 代码块、行内代码、URL、路径和版本号保护
- UTF-16 / Unicode 索引正确性

### 6.6 Completion 训练目标

Completion Adapter 不应与 GEC 共享完全相同的输出目标。它需要覆盖：

- Markdown 段落
- 标题、列表、引用
- 表格
- Frontmatter
- MDX
- TypeScript、Rust、Python、Shell 等代码
- 有后缀的 FIM
- 不重复后文
- 正确闭合 Markdown / 代码结构

## 7. 量化与发布需要改动的地方

当前 release 流程主要围绕完整模型合并和 Q4_K_M GGUF。Adapter 方案需要扩展：

```text
训练 Base + Adapter
    ↓
保存 Adapter 原始权重
    ↓
转换 Adapter 为 GGUF（如果生产 Runtime 需要）
    ↓
验证 Base + Adapter 推理
    ↓
可选：合并完整 GGUF 作为兼容/回退产物
    ↓
生成新的 manifest
    ↓
发布 Base、Adapters、manifest
```

发布校验必须包括：

```text
Base 文件存在且 SHA256 正确
每个 Adapter 文件存在且 SHA256 正确
Adapter 声明的 Base ID / SHA256 匹配
任务协议版本匹配
GGUF 可以被 llama-server 加载
GEC Grammar 输出可解析
Completion 停止词行为正确
```

## 8. 客户端需要的协议契约

客户端不会直接选择 Adapter 文件名，而是传递逻辑任务：

```text
Gec
Completion
Distill
StyleAnalysis
```

模型仓库必须保证 manifest 可以回答：

```text
当前 Lite 是否支持该任务？
支持时使用哪个 Adapter？
该 Adapter 依赖哪个 Base？
对应 Prompt / Grammar / Stop Token 版本是什么？
需要下载哪些文件？
```

如果 Lite 不支持某任务，返回明确的 capability unavailable，不要静默换用其他任务 Adapter。

## 9. 当前支持与待实现矩阵

| 能力 | models 当前状态 | 目标状态 |
|---|---|---|
| Qwen2.5 完整 GGUF 发布 | 已支持 | 保留兼容历史 |
| Qwen3-0.6B 基座训练参数 | 未支持 | 增加并验证 |
| 单一多任务 SFT | 已有 | 作为基线保留 |
| 任务专用 Adapter 训练 | 未支持 | 新增任务入口/产物目录 |
| Adapter 转 GGUF | 发布流程未形成 | 增加并做 llama-server 验证 |
| Base + Adapter manifest | 未支持 | manifest schema v2 |
| Lite / Standard 不同能力集合 | 未支持 | capabilities 显式建模 |
| Adapter 与 Base SHA256 绑定 | 未支持 | 发布和客户端双重校验 |
| GEC 专用数据集 | 已有 GEC 数据 | 去重、防泄漏、质量重建 |
| Completion 专用数据集 | 当前混在多任务数据 | 独立数据与评测 |
| Distill 专用数据集 | 当前有提炼数据 | 修正模板化目标 |
| Style Analysis 数据集 | 当前仅有有限类型/Prompt 雏形 | 后续独立设计 |
| 端云协议 | 非当前范围 | 仅保留字段扩展空间 |

## 10. 推荐实施顺序

1. 修正/同步当前数据集，建立独立 test 集。
2. 增加 Qwen3-0.6B 基座可配置训练入口。
3. 先训练 GEC Adapter，和当前 Qwen2.5-0.5B 做 A/B。
4. 训练 Completion Adapter，再验证任务隔离效果。
5. 完成 Adapter / Base 兼容性与 GGUF 推理验证。
6. 更新 manifest schema，使 Lite 对应一个 Base 和多个隐藏 Adapter。
7. 更新发布脚本，生成真实文件大小、SHA256 和兼容关系。
8. 客户端在新 `feature/` 分支实现 Model/Capability Resolver 和 Adapter Runtime。
9. 通过客户端真实调用后，再考虑 Standard Adapter 和多 slot 并行。

## 11. 未来扩展

将来端侧可能增加文档摘要、用户风格和行为分析，并将结构化分析结果提供给更强的外部模型。该方向不改变当前 Adapter 的职责：Adapter 负责稳定的任务能力，用户级个性化应由结构化上下文和缓存承载，而不是为每个用户训练独立 Adapter。
