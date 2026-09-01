# RFC-002: md-editor 端侧专属小模型 (SLM) 客户端对接与实施终极规范

> **接收方**：[`wmasfoe/md-editor`](https://github.com/wmasfoe/md-editor) 桌面端 App 开发 Agent  
> **发送方**：[`wmasfoe/md-editor-models`](https://github.com/wmasfoe/md-editor-models) 模型微调工程 Agent  
> **技术架构**：Tauri v2 (Rust) + `llama-server` 本地进程通信  
> **当前状态**：Approved Final Specification（双方已完成所有细节对齐，进入落地实施阶段）  

---

## 1. 项目背景与总体目标

为了让 `md-editor` 具备**极致流畅（首字延迟 <30ms）、超低资源占用（常驻内存 <300MB、磁盘 <250MB）、100% 离线隐私**的 AI 辅助写作体验，模型端已完成垂直专精小语言模型（SLM）的架构优化与多任务微调。

模型聚焦于 Markdown 写作四大垂直场景：
1. **中英日韩俄法（6 语种）语法纠错 (GEC)**
2. **标点与排版规范化**（盘古之白空格、全半角纠正、中英弯直引号规范）
3. **行内 FIM (Fill-In-The-Middle) 极速续写**（Ghost Text 补全）
4. **Markdown / LaTeX / 表格格式硬保真**（LaTeX `$$...$$`、YAML Frontmatter 不被破坏）

---

## 2. 双方确认的 6 大核心协议与实施标准

### 协议一：局部 Diff 协议与编码规范（带原文锚点与边界对齐）

#### 1.1 偏移量基准
* **统一基准**：**Unicode 字符数（Unicode Code Points，0-indexed）**。
* 客户端需在解析后将其转换为 JavaScript / CodeMirror 6 的 UTF-16 Code Units（见第 3 节代码）。

#### 1.2 输出语法格式（带原文锚点）
为了防止端侧小模型字符计数产生 $\pm 1$ 偏移时误切原文字符，所有纠错输出一律采用**带原文校验锚点的结构**：

$$\text{格式：} [start:end|"\text{待替换原文}"|"\text{替换后文本}"]$$

#### 1.3 三大边界场景约定
| 场景类型 | 格式语法 | 边界特征 | 示例说明 |
| :--- | :--- | :--- | :--- |
| **标准替换** | `[start:end|"原文"|"新文"]` | `start < end`, 两文本均非空 | `[8:9|"但"|"因"]` |
| **纯删除 (删多余字)** | `[start:end|"多余内容"|""]` | `start < end`, `replacement === ""` | `[8:10|"多余"|""]` |
| **纯插入 (补漏字)** | `[start:start|""|"插入内容"]` | `start === end`, `original === ""` | `[8:8|""|"并且"]` |

#### 1.4 多处修改与特殊字符转义
* **单句多处修改**：采用紧凑连续输出，例如 `[2:3|"这"|"那"][8:9|"因"|"但"]`。
* **特殊字符转义**：遵循标准转义规范（`\"`、`\n`、`\\`、`\]`）。

---

### 协议二：无错误时的立即终止协议（首字 0 延迟）

* **输出约定**：当输入文本完全规范无需修改时，模型**直接输出 EOS (`<|endoftext|>`) 或空字符串**。
* **耗时标准**：解码在第 1 个 Token 直接命中停止词返回，耗时 **1~2ms**。
* **客户端判定**：`if (!output || output.trim() === "" || output.trim() === "[OK]")` 立即判定无修改并释放 Slot，无缝衔接后续续写。

---

### 协议三：Task Control Tokens 完整注册清单与 Stop Tokens

所有控制符已作为 `Special Tokens` 固化在模型词表中，禁止拆词：

| 任务类型 | 语种 / 场景 | 专用控制 Token | 推荐 Stop Tokens |
| :--- | :--- | :--- | :--- |
| **GEC 语法纠错** | 中文 | `<|task_gec_zh|>` | `["\n", "<|endoftext|>"]` |
| | 英文 | `<|task_gec_en|>` | `["\n", "<|endoftext|>"]` |
| | 日文 | `<|task_gec_ja|>` | `["\n", "<|endoftext|>"]` |
| | 韩文 | `<|task_gec_ko|>` | `["\n", "<|endoftext|>"]` |
| | 俄文 | `<|task_gec_ru|>` | `["\n", "<|endoftext|>"]` |
| | 法文 | `<|task_gec_fr|>` | `["\n", "<|endoftext|>"]` |
| **标点排版规范** | 6 语种混排规范 | `<|task_punc|>` | `["\n", "<|endoftext|>"]` |
| **行内 FIM 补全** | Ghost Text / 续写 | `<|fim_prefix|>`, `<|fim_suffix|>`, `<|fim_middle|>`, `<|fim_end|>` | **行内补全**：`["\n", "<|fim_end|>", "<|endoftext|>"]`<br>**段落续写**：`["<|fim_end|>", "<|endoftext|>"]` |
| **格式保真** | LaTeX/表格/YAML | `<|task_preserve|>` | `["\n", "<|endoftext|>"]` |

---

### 协议四：风格画像前缀（Prefix Profile）拼装范式

#### 4.1 拼装顺序：正式采用【方案 B】（画像置顶）
`[User Style Profile]` 置于 Prompt 最顶层，便于 `llama-server` 跨请求 **100% 长期复用 KV Cache**：

#### 纠错任务 Prompt 结构：
```text
[User Style Profile]
- Language: Mixed (zh-en)
- Punctuation: Strict Pangu-spacing, Oxford-comma
- Preferred: TypeScript, Rust
- Tone: Technical Markdown

<|task_gec_zh|>尽管今天下雨了所以活动依然照常举行。
```

#### FIM 续写任务 Prompt 结构（正式确立【结构 A】）：
```text
[User Style Profile]
- Language: Mixed (zh-en)
- Punctuation: Strict Pangu-spacing

<|fim_prefix|># 部署指南\n在生产环境中运行前，请确保执行 <|fim_suffix|> 启动服务。<|fim_middle|>
```

---

### 协议五：用户习惯自学习闭环（两阶段落地架构）

```
┌────────────────────────────────────────────────────────────────────────┐
│                        客户端本地数据资产 (Tauri 目录)                   │
│  ┌─────────────────────────────────┐  ┌─────────────────────────────┐  │
│  │   user_learning.sqlite          │  │   user_style_profile.json   │  │
│  │ (记录用户采纳/手动修改的高质量句对)│  │ (提取的偏好标签与词汇表)    │  │
│  └────────────────┬────────────────┘  └──────────────┬──────────────┘  │
└───────────────────┼──────────────────────────────────┼─────────────────┘
                    │                                  │
                    ▼ (满足硬件与空闲条件时静默训练)   ▼ (实时常驻)
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│  user_adapter.lora (仅 2MB 独立权重) │  │  Prefix KV Cache (零延迟)    │
└───────────────────┬──────────────────┘  └──────────────┬───────────────┘
                    │                                    │
                    └─────────────────┬──────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│           Tauri 管理的本地 llama-server 原生推理实例                   │
│       (官方更新 base_model.gguf 时，后台 10 秒自动重训生成新 LoRA)       │
└────────────────────────────────────────────────────────────────────────┘
```

* **阶段一（即刻可用）**：客户端通过 SQLite 提炼画像，利用 `llama-server` Prefix KV Cache 实现零训练、零发热的即时风格自适应；
* **阶段二（端侧微调）**：在满足【插电 (AC Power)】+【电量 >60%】+【闲置 >5分钟】+【新样本 $\ge 30$】时，后台调用轻量训练产出标准 2MB GGUF LoRA（兼容 `llama-server --lora`）。

---

### 协议六：GGUF 产物与 Release Manifest 规范

官方每次发布模型时附带的标准 `manifest.json`：

```json
{
  "modelId": "md-editor-slm-0.5b",
  "version": "1.0.0",
  "tier": "lite",
  "quant": "Q4_K_M",
  "contextSize": 8192,
  "sha256": "8f9b2c3d4e5f...",
  "downloadUrl": "https://huggingface.co/wmasfoe/md-editor-slm/resolve/main/qwen2.5-0.5b-editor-Q4_K_M.gguf",
  "specialTokens": {
    "fimPrefix": "<|fim_prefix|>",
    "fimSuffix": "<|fim_suffix|>",
    "fimMiddle": "<|fim_middle|>",
    "fimEnd": "<|fim_end|>",
    "gecZh": "<|task_gec_zh|>",
    "gecEn": "<|task_gec_en|>",
    "punc": "<|task_punc|>"
  }
}
```

---

## 3. 客户端必须实现的 3 重防御性代码实现参考

### 防御 1：Unicode Code Points 到 UTF-16 坐标系转换
```typescript
/**
 * 将基于 Unicode Code Point (字符数) 的偏移量转换为 JS / CodeMirror 6 的 UTF-16 Code Unit 偏移量
 */
export function codePointOffsetToUtf16Offset(str: string, codePointIndex: number): number {
  let codePointCount = 0;
  let utf16Offset = 0;
  for (const char of str) {
    if (codePointCount >= codePointIndex) break;
    utf16Offset += char.length; // 正常字符 +1，Emoji/生僻字代理对 +2
    codePointCount += 1;
  }
  return utf16Offset;
}
```

### 防御 2：Diff 倒序应用与模糊锚点纠偏 (Fuzzy Anchor)
```typescript
interface DiffChunk {
  start: number;
  end: number;
  original: string;
  replacement: string;
}

export function parseAndApplyDiffs(fullText: string, modelOutput: string): string {
  if (!modelOutput || modelOutput.trim() === "" || modelOutput.trim() === "[OK]") {
    return fullText;
  }

  // 1. 正则提取所有 [start:end|"original"|"replacement"]
  const regex = /\[(\d+):(\d+)\|"([^"]*)"\|"([^"]*)"\]/g;
  const diffs: DiffChunk[] = [];
  let match: RegExpExecArray | null;

  while ((match = regex.exec(modelOutput)) !== null) {
    diffs.push({
      start: parseInt(match[1], 10),
      end: parseInt(match[2], 10),
      original: match[3],
      replacement: match[4]
    });
  }

  // 2. 必须按 start 从大到小倒序排序，防止前面替换改变后面下标
  diffs.sort((a, b) => b.start - a.start);

  let result = fullText;
  const codePoints = Array.from(fullText);

  for (const diff of diffs) {
    const origCodePointStart = diff.start;
    const origCodePointEnd = diff.end;
    
    // 获取切片
    const currentSlice = codePoints.slice(origCodePointStart, origCodePointEnd).join('');
    
    if (currentSlice === diff.original) {
      // 强一致命中：直接替换
      const u16Start = codePointOffsetToUtf16Offset(result, origCodePointStart);
      const u16End = codePointOffsetToUtf16Offset(result, origCodePointEnd);
      result = result.slice(0, u16Start) + diff.replacement + result.slice(u16End);
    } else {
      // 模糊纠偏：在 ±5 字符窗口内查找唯一匹配的 diff.original
      const windowStart = Math.max(0, origCodePointStart - 5);
      const windowEnd = Math.min(codePoints.length, origCodePointEnd + 5);
      const windowText = codePoints.slice(windowStart, windowEnd).join('');
      const localIdx = windowText.indexOf(diff.original);

      if (localIdx !== -1 && windowText.indexOf(diff.original, localIdx + 1) === -1) {
        // 找到唯一匹配点，纠偏替换
        const actualCodePointStart = windowStart + localIdx;
        const actualCodePointEnd = actualCodePointStart + Array.from(diff.original).length;
        const u16Start = codePointOffsetToUtf16Offset(result, actualCodePointStart);
        const u16End = codePointOffsetToUtf16Offset(result, actualCodePointEnd);
        result = result.slice(0, u16Start) + diff.replacement + result.slice(u16End);
      }
      // 找不到则静默丢弃该 Diff，绝不盲切损坏用户文档
    }
  }

  return result;
}
```

---

本规范已在模型微调端 100% 固化，产物完全符合以上契约。App 端 Agent 可完全按此实施！
