import json
import random
import os
import re
from datasets import load_dataset
import pangu

# ==============================================================================
# RFC-001 多任务数据构建流水线 (35% GEC + 25% Punctuation + 30% FIM + 10% Format)
# ==============================================================================

# 1. 常见英文拼写易错词库
ENGLISH_TYPOS = {
    "definitely": "definately",
    "separate": "seperate",
    "receive": "recieve",
    "accommodate": "accomodate",
    "environment": "enviroment",
    "occurrence": "occurance",
    "necessary": "neccessary",
    "privilege": "privelege",
    "successful": "succesful",
    "development": "developement",
    "performance": "performence",
    "component": "compoment",
    "asynchronous": "asyncronous",
    "architecture": "archetecture",
    "implementation": "implmentation",
    "configuration": "configration",
    "authentication": "authentification",
    "recommend": "recommed",
    "available": "availible",
    "beginning": "begining"
}

def corrupt_english_gec(text):
    """英文语法与拼写破坏器"""
    corrupted = text
    modified = False
    
    # 拼写错误
    for correct_word, typo_word in ENGLISH_TYPOS.items():
        if re.search(r'\b' + correct_word + r'\b', corrupted, re.IGNORECASE) and random.random() < 0.6:
            match = re.search(r'\b' + correct_word + r'\b', corrupted, re.IGNORECASE)
            matched_str = match.group(0)
            replacement = typo_word.capitalize() if matched_str[0].isupper() else typo_word
            corrupted = corrupted[:match.start()] + replacement + corrupted[match.end():]
            modified = True
            break

    # a / an 冠词语病
    if re.search(r'\ban\s+([b-df-hj-np-tv-z][a-z]+)\b', corrupted, re.IGNORECASE) and random.random() < 0.4:
        corrupted = re.sub(r'\ban\s+', 'a ', corrupted, count=1, flags=re.IGNORECASE)
        modified = True
    elif re.search(r'\ba\s+([aeiou][a-z]+)\b', corrupted, re.IGNORECASE) and random.random() < 0.4:
        corrupted = re.sub(r'\ba\s+', 'an ', corrupted, count=1, flags=re.IGNORECASE)
        modified = True

    # 简易主谓一致破坏 (does -> do / have -> has)
    if "does not" in corrupted and random.random() < 0.4:
        corrupted = corrupted.replace("does not", "do not", 1)
        modified = True
    elif "did not" in corrupted and random.random() < 0.4:
        corrupted = corrupted.replace("did not", "do not", 1)
        modified = True

    return corrupted if modified else None

def corrupt_punctuation_and_typography(text):
    """标点符号与排版规范破坏器"""
    corrupted = text
    modified = False
    
    # 1. 破坏盘古之白空格 (中英文间空格)
    if " " in corrupted and random.random() < 0.7:
        corrupted = re.sub(r'([\u4e00-\u9fa5])\s+([a-zA-Z0-9])', r'\1\2', corrupted)
        corrupted = re.sub(r'([a-zA-Z0-9])\s+([\u4e00-\u9fa5])', r'\1\2', corrupted)
        modified = True

    # 2. 中文全角标点退化为半角
    full_to_half = {'，': ',', '。': '.', '！': '!', '？': '?', '：': ':', '；': ';', '（': '(', '）': ')'}
    for full, half in full_to_half.items():
        if full in corrupted and random.random() < 0.5:
            corrupted = corrupted.replace(full, half, 1)
            modified = True
            break

    # 3. 引号规范性破坏
    if '“' in corrupted and '”' in corrupted and random.random() < 0.6:
        corrupted = corrupted.replace('“', '"', 1).replace('”', '"', 1)
        modified = True

    # 4. 省略号与破折号不规范
    if '……' in corrupted and random.random() < 0.6:
        corrupted = corrupted.replace('……', '......', 1)
        modified = True
    elif '——' in corrupted and random.random() < 0.6:
        corrupted = corrupted.replace('——', '--', 1)
        modified = True

    # 5. 英文标点后缺少空格
    if re.search(r'([,\.!?])\s+([A-Za-z])', corrupted) and random.random() < 0.5:
        corrupted = re.sub(r'([,\.!?])\s+([A-Za-z])', r'\1\2', corrupted, count=1)
        modified = True

    # 6. 句首首字母小写
    if corrupted and corrupted[0].isupper() and random.random() < 0.4:
        corrupted = corrupted[0].lower() + corrupted[1:]
        modified = True

    return corrupted if (modified and corrupted != text) else None

# ==============================================================================
# 任务一：中英双语语法与病句纠错 (GEC) [35%]
# ==============================================================================
def build_gec_samples(target_count=3500):
    print("1/4 Building Task: [TASK: GRAMMAR] (35%)...")
    samples = []
    
    # 1. 中文真实拼写/语病 (来自 CSC 数据集)
    ds = load_dataset('shibing624/CSC', split='train', streaming=True)
    for row in ds.take(target_count // 2 + 500):
        orig, corr = row['original_text'], row['correct_text']
        if orig == corr:
            continue
        samples.append({
            "messages": [
                {"role": "user", "content": f"[TASK: GRAMMAR]\nInput:  {orig}"},
                {"role": "assistant", "content": f"Output: {corr}"}
            ]
        })
        if len(samples) >= target_count // 2:
            break

    # 2. 英文语法与拼写语料
    en_seeds = [
        "She do not received the confirmation email yesterday and ask for help.",
        "React is a popular JavaScript library for building interactive user interfaces.",
        "We definitely recommend updating to the latest stable release for better performance.",
        "Please make sure your environment configuration is set up properly before running tests.",
        "It's important to separate business logic from the UI presentation layer.",
        "The authentication component provides secure token verification for all incoming requests.",
        "Asynchronous operations can be easily managed using modern async/await syntax.",
        "They are going to release the new architecture documentation next Monday.",
        "Our team has achieved a successful milestone in this sprint cycle.",
        "The privilege level must be verified before granting administrative access."
    ] * (target_count // 10 + 1)

    for en_clean in en_seeds:
        en_bad = corrupt_english_gec(en_clean)
        if en_bad:
            samples.append({
                "messages": [
                    {"role": "user", "content": f"[TASK: GRAMMAR]\nInput:  {en_bad}"},
                    {"role": "assistant", "content": f"Output: {en_clean}"}
                ]
            })
        if len(samples) >= target_count:
            break

    return samples[:target_count]

# ==============================================================================
# 任务二：标点与排版规范化 (Punctuation & Typography) [25%]
# ==============================================================================
def build_punctuation_samples(target_count=2500):
    print("2/4 Building Task: [TASK: PUNCTUATE] (25%)...")
    samples = []
    
    seed_corpus = [
        "使用 React 开发桌面端，性能提升了 30% 以上 and fixed all memory leaks.",
        "我们在 macOS、Windows 和 Linux 系统上都进行了全面兼容性测试。",
        "请参考《深入浅出 Node.js》这本书，里面对 Buffer 和 Stream 的讲解非常透彻。",
        "他兴奋地说道：“今天发布的 v2.0 版本终于支持本地 AI 模型了！”",
        "目前项目在 GitHub 上已经获得了超过 10,000 个 Star，感谢大家的支持。",
        "这件事情的真相究竟如何……我们至今依然不得而知。",
        "技术发展日新月异——唯有终身学习才能保持竞争力。",
        "TypeScript adds optional static typing and class-based object-oriented programming to JavaScript.",
        "Make sure to pull the latest changes from the main branch before creating a PR.",
        "根据调研，Python、Rust 和 TypeScript 是目前最受青睐的编程语言。"
    ] * (target_count // 10 + 1)

    for clean_text in seed_corpus:
        standard_text = pangu.spacing_text(clean_text)
        corrupted = corrupt_punctuation_and_typography(standard_text)
        if corrupted:
            samples.append({
                "messages": [
                    {"role": "user", "content": f"[TASK: PUNCTUATE]\nInput:  {corrupted}"},
                    {"role": "assistant", "content": f"Output: {standard_text}"}
                ]
            })
        if len(samples) >= target_count:
            break

    return samples[:target_count]

# ==============================================================================
# 任务三：行内 FIM (Fill-In-The-Middle) 极速补全 [30%]
# ==============================================================================
def build_fim_samples(target_count=3000):
    print("3/4 Building Task: Native FIM Completion (30%)...")
    samples = []
    
    markdown_documents = [
        "# 部署指南\n\n在生产环境中运行前，请确保已经执行 `pnpm build` 并使用 pm2 启动服务。\n\n```bash\npm2 start ecosystem.config.js\n```",
        "## 核心特性\n\n- **极速响应**：首字延迟压低至 50ms 以内。\n- **轻量量化**：GGUF Q4_K_M 格式下仅占用 350MB 内存。\n- **离线安全**：无需任何云端 API 依赖。",
        "```typescript\nexport async function getLocalModelStatus(modelId: string): Promise<ModelStatus> {\n  const info = await checkModelCache(modelId);\n  return info.isReady ? ModelStatus.READY : ModelStatus.DOWNLOADING;\n}\n```",
        "### 故障排查 (Troubleshooting)\n\n如果发现端侧推理进程异常退出，请检查是否分配了足够的物理内存，并查看 `~/.md-editor/logs` 下的运行日志。",
        "The authentication pipeline validates incoming JWT tokens against the public key stored in the environment configuration before passing the request to downstream controllers."
    ] * (target_count // 5 + 1)

    for doc in markdown_documents:
        if len(doc) < 30:
            continue
        # 随机挑选切分点
        start = random.randint(10, max(12, len(doc) // 2))
        length = random.randint(10, min(60, len(doc) - start - 5))
        
        prefix = doc[:start]
        middle = doc[start:start + length]
        suffix = doc[start + length:]
        
        # Qwen2.5 原生 FIM 模板: <|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>{middle}<|fim_end|>
        prompt = f"<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>"
        completion = f"{middle}<|fim_end|>"
        
        samples.append({
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": completion}
            ]
        })
        if len(samples) >= target_count:
            break

    return samples[:target_count]

# ==============================================================================
# 任务四：格式保真负样本约束 (Format Preservation) [10%]
# ==============================================================================
def build_format_preservation_samples(target_count=1000):
    print("4/4 Building Task: [TASK: PRESERVE] (10%)...")
    samples = []
    
    complex_structures = [
        # LaTeX 公式
        "$$E = mc^2$$",
        "$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}$$",
        "根据高斯公式：$\\oint_{\\partial \\Omega} \\mathbf{F} \\cdot d\\mathbf{S} = \\iiint_\\Omega (\\nabla \\cdot \\mathbf{F}) dV$",
        # YAML Frontmatter
        "---\ntitle: RFC-001 Architecture\nauthor: Antigravity Agent\ndate: 2026-09-01\ntags: [SLM, GGUF, Tauri]\n---",
        # Markdown 表格
        "| 参数 | 类型 | 默认值 | 说明 |\n| :--- | :--- | :--- | :--- |\n| `max_tokens` | `number` | `24` | 单次最大输出 token |\n| `temperature` | `number` | `0.2` | 采样温度 |",
        # 嵌套代码块
        "```python\ndef fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)\n```"
    ] * (target_count // 6 + 1)

    for item in complex_structures[:target_count]:
        samples.append({
            "messages": [
                {"role": "user", "content": f"[TASK: PRESERVE]\nInput:  {item}"},
                {"role": "assistant", "content": f"Output: {item}"}
            ]
        })

    return samples[:target_count]

# ==============================================================================
# 主执行入口
# ==============================================================================
if __name__ == "__main__":
    gec_data = build_gec_samples(3500)
    punct_data = build_punctuation_samples(2500)
    fim_data = build_fim_samples(3000)
    preserve_data = build_format_preservation_samples(1000)
    
    all_samples = gec_data + punct_data + fim_data + preserve_data
    random.seed(42)
    random.shuffle(all_samples)
    
    # 9:1 划分
    split_idx = int(len(all_samples) * 0.9)
    train_samples = all_samples[:split_idx]
    val_samples = all_samples[split_idx:]
    
    os.makedirs("data", exist_ok=True)
    
    with open("data/train.jsonl", "w", encoding="utf-8") as f:
        for s in train_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            
    with open("data/val.jsonl", "w", encoding="utf-8") as f:
        for s in val_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            
    print(f"\n🎉 RFC-001 多任务全量数据构建完成！")
    print(f"📊 总样本量: {len(all_samples)} (100%)")
    print(f"├── [35%] GEC 语法与错别字:   {len(gec_data)} 条")
    print(f"├── [25%] 标点与排版规范:     {len(punct_data)} 条")
    print(f"├── [30%] FIM 行内补全:       {len(fim_data)} 条")
    print(f"└── [10%] 格式保真负样本:     {len(preserve_data)} 条")
    print(f"\n📁 数据文件已更新:")
    print(f"├── 训练集 (data/train.jsonl): {len(train_samples)} 条")
    print(f"└── 验证集 (data/val.jsonl):   {len(val_samples)} 条")
