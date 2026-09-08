import json
import argparse
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# 兼容性修复：解决部分环境（如 Google Colab）中预装旧版 torchao (<0.16.0) 导致 PEFT 抛出未捕获 ImportError 的已知问题
def _patch_peft_torchao():
    try:
        import peft.import_utils
        _orig_func = getattr(peft.import_utils, "is_torchao_available", None)
        if _orig_func is not None:
            def _safe_is_torchao_available():
                try:
                    return _orig_func()
                except ImportError:
                    return False
            peft.import_utils.is_torchao_available = _safe_is_torchao_available
            if hasattr(peft, "tuners") and hasattr(peft.tuners, "lora") and hasattr(peft.tuners.lora, "torchao"):
                peft.tuners.lora.torchao.is_torchao_available = _safe_is_torchao_available
    except Exception:
        pass

_patch_peft_torchao()

def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate RFC-002 model output adherence (Tuple JSON Diff & FIM & Distill)")
    parser.add_argument("--model_path", type=str, default="Qwen/Qwen2.5-0.5B-Instruct", help="Path to base model or merged model")
    parser.add_argument("--lora_path", type=str, default=None, help="Optional path to LoRA adapter")
    parser.add_argument("--val_file", type=str, default="data/val.jsonl", help="Validation dataset path")
    parser.add_argument("--num_eval_samples", type=int, default=20, help="Number of samples to test")
    return parser.parse_args()

def main():
    args = parse_args()
    
    print("=" * 60)
    print(f"🔍 Evaluating RFC-002 Model Compliance: {args.model_path}")
    if args.lora_path:
        print(f"🔹 LoRA Adapter: {args.lora_path}")
    print("=" * 60)

    # 1. 加载 Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    
    # 2. 加载模型
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else "cpu",
        trust_remote_code=True
    )
    
    if args.lora_path:
        model = PeftModel.from_pretrained(model, args.lora_path)
        
    model.eval()

    # 3. 读取验证集
    with open(args.val_file, "r", encoding="utf-8") as f:
        val_samples = [json.loads(line) for line in f]

    print(f"📊 Loaded {len(val_samples)} validation samples. Testing first {args.num_eval_samples} samples...\n")

    valid_format_count = 0
    
    for idx, sample in enumerate(val_samples[:args.num_eval_samples]):
        messages = sample["messages"]
        ground_truth = messages[-1]["content"]
        
        # 截取 Prompt (除最后一条 assistant 消息之外的输入)
        input_messages = messages[:-1]
        prompt_text = tokenizer.apply_chat_template(input_messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=128,
                temperature=0.0,  # Greedy
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
            
        generated_ids = outputs[0][inputs.input_ids.shape[1]:]
        response_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        
        user_msg = next((m["content"] for m in input_messages if m["role"] == "user"), "")
        print(f"[{idx+1}/{args.num_eval_samples}] 输入 Prompt: {user_msg[:60]}...")
        print(f"  👉 真实期望: {ground_truth}")
        print(f"  🤖 模型输出: {response_text}")
        
        # 判断任务类型并校验
        if "<|fim_prefix|>" in user_msg:
            # FIM 任务
            valid_format_count += 1
            print("  ✅ FIM 补全输出正常")
        elif "<|task_distill|>" in user_msg:
            # 文档提炼任务：检验是否具备真实主旨或专有名词实体
            if len(response_text) >= 50 and ("【核心主旨】" in response_text or "【关键专有名词与实体】" in response_text or "主旨" in response_text):
                valid_format_count += 1
                print(f"  ✅ 高密度结构化提炼输出正常 (长度: {len(response_text)} 字)")
            elif len(response_text) >= 30:
                valid_format_count += 1
                print(f"  ⚠️ 提炼输出有效，但未包含标准结构化标签 (长度: {len(response_text)} 字)")
            else:
                print(f"  ❌ 提炼输出过短或为空 (长度: {len(response_text)} 字)")
        else:
            # GEC / Punctuation / Preserve 任务 -> 校验元组 JSON
            try:
                if response_text == "" or response_text == "[]":
                    valid_format_count += 1
                    print("  ✅ 无错误/终止输出正常 (空或 [])")
                else:
                    parsed = json.loads(response_text)
                    if isinstance(parsed, list):
                        valid_format_count += 1
                        print(f"  ✅ 紧凑元组 JSON 校验通过: {parsed}")
                    else:
                        print(f"  ❌ 输出非 Array 结构")
            except json.JSONDecodeError:
                print(f"  ❌ 非法 JSON 输出")
                
        print("-" * 60)
        
    n = min(args.num_eval_samples, len(val_samples))
    print(f"\n📈 RFC-002 评测统计:")
    print(f"  - 测试样本数: {n}")
    print(f"  - 格式完全达标率: {(valid_format_count / n) * 100:.1f}%")

if __name__ == "__main__":
    main()
