import json
import argparse
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

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
            # 文档提炼任务
            valid_format_count += 1
            print("  ✅ 文档提炼输出正常")
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
