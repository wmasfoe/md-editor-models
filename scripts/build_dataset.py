import json
import random
import os
import re
import difflib
from datasets import load_dataset
import pangu

# ==============================================================================
# RFC-002 终极多任务数据构建流水线
# 包含 6 语种、带原文锚点 Diff 语法、FIM 结构 A、纯删/纯插边界对齐
# ==============================================================================

def unicode_len(s):
    return len(list(s))

def extract_compact_diff(original, correct):
    """
    提取带原文锚点的 Diff 结构: [start:end|"original"|"replacement"]
    使用 Unicode Code Points (字符计数) 作为偏移量基准
    """
    orig_chars = list(original)
    corr_chars = list(correct)
    
    s = difflib.SequenceMatcher(None, orig_chars, corr_chars)
    diffs = []
    
    for tag, i1, i2, j1, j2 in s.get_opcodes():
        if tag != 'equal':
            orig_slice = "".join(orig_chars[i1:i2])
            corr_slice = "".join(corr_chars[j1:j2])
            # 转义内部双引号
            escaped_orig = orig_slice.replace('"', '\\"')
            escaped_corr = corr_slice.replace('"', '\\"')
            diffs.append(f'[{i1}:{i2}|"{escaped_orig}"|"{escaped_corr}"]')
            
    return "".join(diffs) if diffs else ""

# 6 语种拼写/语法易错库
ENGLISH_TYPOS = {
    "definitely": "definately", "separate": "seperate", "receive": "recieve",
    "accommodate": "accomodate", "environment": "enviroment", "occurrence": "occurance",
    "necessary": "neccessary", "successful": "succesful", "architecture": "archetecture"
}

def corrupt_multilingual_gec(text, lang="zh"):
    """多语种语法与排版破坏器"""
    corrupted = text
    if lang == "en":
        for correct_word, typo_word in ENGLISH_TYPOS.items():
            if re.search(r'\b' + correct_word + r'\b', corrupted, re.IGNORECASE) and random.random() < 0.6:
                match = re.search(r'\b' + correct_word + r'\b', corrupted, re.IGNORECASE)
                replacement = typo_word.capitalize() if match.group(0)[0].isupper() else typo_word
                return corrupted[:match.start()] + replacement + corrupted[match.end():]
        if "does not" in corrupted and random.random() < 0.5:
            return corrupted.replace("does not", "do not", 1)
    elif lang == "ja":
        # 日文助词/长音误用
        if "サーバー" in corrupted and random.random() < 0.6:
            return corrupted.replace("サーバー", "サーバ", 1)
        if "を行っています" in corrupted and random.random() < 0.6:
            return corrupted.replace("を行っています", "をしてます", 1)
    elif lang == "ko":
        # 韩文常见拼写/助词
        if "되었습니다" in corrupted and random.random() < 0.6:
            return corrupted.replace("되었습니다", "됬습니다", 1)
    elif lang == "ru":
        # 俄语软音符/前缀
        if "сделать" in corrupted and random.random() < 0.6:
            return corrupted.replace("сделать", "зделать", 1)
    elif lang == "fr":
        # 法语重音缺失
        if "développement" in corrupted and random.random() < 0.6:
            return corrupted.replace("développement", "developpement", 1)
    return None

def corrupt_punc(text):
    """标点与排版破坏器"""
    corrupted = text
    if " " in corrupted and random.random() < 0.7:
        corrupted = re.sub(r'([\u4e00-\u9fa5])\s+([a-zA-Z0-9])', r'\1\2', corrupted)
        corrupted = re.sub(r'([a-zA-Z0-9])\s+([\u4e00-\u9fa5])', r'\1\2', corrupted)
    full_to_half = {'，': ',', '。': '.', '！': '!', '？': '?', '：': ':'}
    for full, half in full_to_half.items():
        if full in corrupted and random.random() < 0.5:
            corrupted = corrupted.replace(full, half, 1)
            break
    if '“' in corrupted and '”' in corrupted and random.random() < 0.5:
        corrupted = corrupted.replace('“', '"', 1).replace('”', '"', 1)
    return corrupted if corrupted != text else None

# ==============================================================================
# 数据集构建
# ==============================================================================
def build_dataset_rfc002():
    samples = []
    
    # 1. GEC 语法纠错 (中文 + 英/日/韩/俄/法)
    print("1/5 Building GEC (6 Languages) with Compact Diff [start:end|\"orig\"|\"repl\"]...")
    
    # 中文 CSC 数据
    ds = load_dataset('shibing624/CSC', split='train', streaming=True)
    for row in ds.take(2500):
        orig, corr = row['original_text'], row['correct_text']
        if orig == corr:
            # 无错误样本：输出直接为空 (EOS)
            samples.append({"messages": [{"role": "user", "content": f"<|task_gec_zh|>{orig}"}, {"role": "assistant", "content": ""}]})
            continue
        diff = extract_compact_diff(orig, corr)
        if diff:
            samples.append({"messages": [{"role": "user", "content": f"<|task_gec_zh|>{orig}"}, {"role": "assistant", "content": diff}]})

    # 多语种语料
    multilingual_seeds = {
        "en": ("<|task_gec_en|>", ["We definitely recommend updating to the latest stable release for better performance.", "She does not receive the email yesterday."]),
        "ja": ("<|task_gec_ja|>", ["クラウドサーバーの構築を行っています。", "Reactを使用したフロントエンド開発の手法について解説します。"]),
        "ko": ("<|task_gec_ko|>", ["새로운 버전의 배포가 성공적으로 완료되었습니다.", "타입스크립트를 사용하여 안정적인 코드를 작성합니다."]),
        "ru": ("<|task_gec_ru|>", ["Мы хотим сделать архитектуру приложения более быстрой и надежной.", "Использование Rust позволяет достичь высокой производительности."]),
        "fr": ("<|task_gec_fr|>", ["Le développement de cette fonctionnalité est en cours.", "Veuillez vérifier la configuration du système avant le déploiement."])
    }
    
    for lang, (token, texts) in multilingual_seeds.items():
        for clean in texts * 300:
            bad = corrupt_multilingual_gec(clean, lang=lang)
            if bad:
                diff = extract_compact_diff(bad, clean)
                samples.append({"messages": [{"role": "user", "content": f"{token}{bad}"}, {"role": "assistant", "content": diff}]})
            else:
                samples.append({"messages": [{"role": "user", "content": f"{token}{clean}"}, {"role": "assistant", "content": ""}]})

    # 2. 标点与排版规范 (<|task_punc|>)
    print("2/5 Building Punctuation & Typography with Compact Diff...")
    punc_seeds = [
        "使用 React 开发桌面端，性能提升了 30% 以上 and fixed all memory leaks.",
        "我们在 macOS、Windows 和 Linux 系统上都进行了全面兼容性测试。",
        "请参考《深入浅出 Node.js》这本书，里面对 Buffer 和 Stream 的讲解非常透彻。",
        "他兴奋地说道：“今天发布的 v2.0 版本终于支持本地 AI 模型了！”",
        "TypeScript adds optional static typing and class-based object-oriented programming to JavaScript."
    ] * 400

    for clean in punc_seeds:
        std = pangu.spacing_text(clean)
        bad = corrupt_punc(std)
        if bad:
            diff = extract_compact_diff(bad, std)
            samples.append({"messages": [{"role": "user", "content": f"<|task_punc|>{bad}"}, {"role": "assistant", "content": diff}]})
        else:
            samples.append({"messages": [{"role": "user", "content": f"<|task_punc|>{std}"}, {"role": "assistant", "content": ""}]})

    # 3. FIM 极速补全（采用结构 A：画像置顶）
    print("3/5 Building FIM (Structure A with Prefix Profile)...")
    fim_docs = [
        "# 部署指南\n\n在生产环境中运行前，请确保执行 `pnpm build` 并使用 pm2 启动服务。\n\n```bash\npm2 start ecosystem.config.js\n```",
        "## 核心特性\n\n- **极速响应**：首字延迟压低至 30ms 以内。\n- **轻量量化**：GGUF Q4_K_M 格式下仅占用 220MB 磁盘。\n- **离线安全**：无需任何云端 API 依赖。",
        "The authentication pipeline validates incoming JWT tokens against the public key stored in the environment configuration before passing the request to downstream controllers."
    ] * 800

    profile_template = "[User Style Profile]\n- Language: Mixed (zh-en)\n- Punctuation: Strict Pangu-spacing\n\n"

    for doc in fim_docs:
        start = random.randint(10, max(12, len(doc) // 2))
        length = random.randint(10, min(50, len(doc) - start - 5))
        prefix, middle, suffix = doc[:start], doc[start:start + length], doc[start + length:]
        
        # 结构 A: Profile 在 <|fim_prefix|> 外侧
        prompt = f"{profile_template}<|fim_prefix|>{prefix}<|fim_suffix|>{suffix}<|fim_middle|>"
        samples.append({"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": f"{middle}<|fim_end|>"}]})

    # 4. 边界用例：纯删除与纯插入
    print("4/5 Injecting Pure Delete and Pure Insert Edge Cases...")
    samples.append({"messages": [{"role": "user", "content": "<|task_gec_zh|>这是多余的的内容"}, {"role": "assistant", "content": '[4:6|"的的"|"的"]'}]})
    samples.append({"messages": [{"role": "user", "content": "<|task_gec_zh|>我们必须严格遵相关规定"}, {"role": "assistant", "content": '[6:6|""|"守"]'}]})

    # 5. 格式保真 (<|task_preserve|>)
    print("5/5 Building Format Preservation Cases...")
    preserves = [
        "$$E = mc^2$$",
        "$$\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}$$",
        "---\ntitle: Doc\nauthor: Me\n---",
        "| a | b |\n|---|---|\n| 1 | 2 |"
    ] * 200
    for p in preserves:
        samples.append({"messages": [{"role": "user", "content": f"<|task_preserve|>{p}"}, {"role": "assistant", "content": ""}]})

    random.seed(42)
    random.shuffle(samples)
    
    split_idx = int(len(samples) * 0.9)
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]
    
    os.makedirs("data", exist_ok=True)
    with open("data/train.jsonl", "w", encoding="utf-8") as f:
        for s in train_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open("data/val.jsonl", "w", encoding="utf-8") as f:
        for s in val_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            
    print(f"\n🎉 RFC-002 终极多任务数据集构建完成！总计: {len(samples)} 条")
    print(f"├── 训练集 (data/train.jsonl): {len(train_samples)} 条")
    print(f"└── 验证集 (data/val.jsonl):   {len(val_samples)} 条")

if __name__ == "__main__":
    build_dataset_rfc002()
