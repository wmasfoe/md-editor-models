import json
import argparse
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate fine-tuned writing assistant model against md-editor contract")
    parser.add_argument("--model_path", type=str, default="Qwen/Qwen2.5-0.5B-Instruct", help="Path to base model or merged model")
    parser.add_argument("--lora_path", type=str, default=None, help="Optional path to LoRA adapter")
    parser.add_argument("--val_file", type=str, default="data/val.jsonl", help="Validation dataset path")
    parser.add_argument("--num_eval_samples", type=int, default=20, help="Number of samples to test")
    return parser.parse_args()

def main():
    args = parse_args()
    
    print("=" * 60)
    print(f"🔍 Evaluating Model against md-editor Contract: {args.model_path}")
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

    valid_json_count = 0
    schema_adherence_count = 0
    
    for idx, sample in enumerate(val_samples[:args.num_eval_samples]):
        messages = sample["messages"]
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]
        ground_truth = json.loads(messages[2]["content"])
        
        conversation = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]
        
        prompt_text = tokenizer.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                temperature=0.1,
                top_p=0.9,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
            
        generated_ids = outputs[0][inputs.input_ids.shape[1]:]
        response_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        
        print(f"[{idx+1}/{args.num_eval_samples}] 输入 Prompt 摘要:")
        # 提取光标前文本展示
        match = re.search(r'【光标前】\s*([^\n]+)', user_content)
        cursor_before = match.group(1) if match else user_content[:50]
        print(f"  [光标前]: {cursor_before}")
        print(f"  👉 真实期望: hasEdit={ground_truth.get('hasEdit')}, hasContinuation={ground_truth.get('hasContinuation')}")
        print(f"  🤖 模型输出: {response_text}")
        
        try:
            parsed = json.loads(response_text)
            valid_json_count += 1
            # 校验四个必需字段是否存在
            if all(k in parsed for k in ["hasEdit", "edit", "hasContinuation", "continuation"]):
                schema_adherence_count += 1
                print(f"  ✅ 完美符合 md-editor 契约: hasEdit={parsed['hasEdit']}, hasContinuation={parsed['hasContinuation']}")
            else:
                print(f"  ⚠️ JSON 合法但缺少必需字段 (需要 hasEdit, edit, hasContinuation, continuation)")
        except json.JSONDecodeError:
            print(f"  ❌ JSON 解析失败 (输出格式非法)")
            
        print("-" * 60)
        
    n = min(args.num_eval_samples, len(val_samples))
    print(f"\n📈 评测统计:")
    print(f"  - 测试样本数: {n}")
    print(f"  - JSON 解析成功率: {(valid_json_count / n) * 100:.1f}%")
    print(f"  - md-editor 契约完全达标率: {(schema_adherence_count / n) * 100:.1f}%")

if __name__ == "__main__":
    import re
    main()
