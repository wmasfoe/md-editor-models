import os
import argparse
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, TaskType, PeftModel
from trl import SFTTrainer, SFTConfig

# RFC-002 专属控制符清单（作为 Special Tokens 固化进词表）
SPECIAL_TOKENS = [
    "<|task_gec_zh|>",
    "<|task_gec_en|>",
    "<|task_gec_ja|>",
    "<|task_gec_ko|>",
    "<|task_gec_ru|>",
    "<|task_gec_fr|>",
    "<|task_punc|>",
    "<|task_preserve|>",
    "<|fim_prefix|>",
    "<|fim_suffix|>",
    "<|fim_middle|>",
    "<|fim_end|>"
]

def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen2.5 on Markdown SLM dataset with RFC-002 tokens and LoRA")
    
    # 模型与数据路径
    parser.add_argument("--model_name_or_path", type=str, default="Qwen/Qwen2.5-0.5B-Instruct", help="Base model identifier or local path")
    parser.add_argument("--train_file", type=str, default="data/train.jsonl", help="Path to training jsonl file")
    parser.add_argument("--val_file", type=str, default="data/val.jsonl", help="Path to validation jsonl file")
    parser.add_argument("--output_dir", type=str, default="output/qwen-0.5b-editor-lora", help="Directory to save LoRA checkpoints")
    
    # 训练超参数
    parser.add_argument("--num_train_epochs", type=int, default=3, help="Total training epochs")
    parser.add_argument("--batch_size", type=int, default=4, help="Per-device batch size")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--learning_rate", type=float, default=2e-4, help="Initial learning rate")
    parser.add_argument("--max_seq_length", type=int, default=1024, help="Maximum sequence length")
    parser.add_argument("--warmup_ratio", type=float, default=0.05, help="Warmup steps ratio")
    parser.add_argument("--logging_steps", type=int, default=10, help="Log metrics every N steps")
    parser.add_argument("--save_steps", type=int, default=100, help="Save checkpoint every N steps")
    
    # LoRA / QLoRA 配置
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA scaling factor")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout rate")
    parser.add_argument("--use_qlora", action="store_true", help="Enable 4-bit QLoRA to save VRAM")
    
    # 导出与合并
    parser.add_argument("--merge_and_save", action="store_true", help="Merge LoRA weights into base model after training")
    parser.add_argument("--merged_output_dir", type=str, default="output/qwen-0.5b-editor-merged", help="Directory to save the merged standalone model")

    return parser.parse_args()

def main():
    args = parse_args()
    
    print("=" * 60)
    print(f"🚀 Starting RFC-002 SLM Fine-Tuning Pipeline")
    print(f"🔹 Base Model:   {args.model_name_or_path}")
    print(f"🔹 Train Dataset: {args.train_file}")
    print(f"🔹 Val Dataset:   {args.val_file}")
    print(f"🔹 Output Dir:    {args.output_dir}")
    print(f"🔹 CUDA Available: {torch.cuda.is_available()}")
    print("=" * 60)

    # 1. 检查数据文件
    if not os.path.exists(args.train_file):
        raise FileNotFoundError(f"Training dataset not found: {args.train_file}. Please run scripts/build_dataset.py first!")

    # 2. 加载数据集
    data_files = {"train": args.train_file}
    if os.path.exists(args.val_file):
        data_files["validation"] = args.val_file
        
    dataset = load_dataset("json", data_files=data_files)
    print(f"✅ Loaded {len(dataset['train'])} training samples" + 
          (f" and {len(dataset['validation'])} validation samples." if "validation" in dataset else "."))

    # 3. 加载 Tokenizer 并注册 RFC-002 专用控制符
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name_or_path,
        trust_remote_code=True,
        padding_side="right"
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 注入特殊控制符（确保不被拆分为普通 subwords）
    num_added = tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})
    if num_added > 0:
        print(f"✨ Registered {num_added} RFC-002 special control tokens in tokenizer vocabulary!")

    # 4. 加载基座模型（支持 QLoRA 4-bit 量化加载）
    bnb_config = None
    if args.use_qlora:
        print("💡 QLoRA enabled: loading base model in 4-bit NormalFloat precision...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            bnb_4bit_use_double_quant=True
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        quantization_config=bnb_config,
        device_map="auto" if torch.cuda.is_available() else None,
        torch_dtype=torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float32,
        trust_remote_code=True
    )

    # 若添加了新 token，扩充 embedding 层
    if num_added > 0:
        model.resize_token_embeddings(len(tokenizer))

    # 5. 配置 LoRA
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none"
    )

    # 6. 配置 SFTTrainer 训练参数
    sft_config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=3,
        evaluation_strategy="steps" if "validation" in dataset else "no",
        eval_steps=args.save_steps if "validation" in dataset else None,
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
        max_seq_length=args.max_seq_length,
        dataset_text_field=None,
        report_to="none"
    )

    # 7. 实例化 Trainer 并启动训练
    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=dataset["train"],
        eval_dataset=dataset.get("validation", None),
        peft_config=peft_config,
        processing_class=tokenizer
    )

    print("\n🔥 Starting training...")
    trainer.train()

    # 8. 保存最佳 LoRA Adapter 权重与更新后的 Tokenizer
    print(f"\n💾 Saving final LoRA adapter to {args.output_dir}...")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"✅ LoRA Adapter saved successfully!")

    # 9. 可选：合并 LoRA 权重到基座模型并导出完整模型（供 llama.cpp 转换为 GGUF）
    if args.merge_and_save:
        print("\n🔄 Merging LoRA adapter with base model for standalone GGUF export...")
        base_model = AutoModelForCausalLM.from_pretrained(
            args.model_name_or_path,
            torch_dtype=torch.float16,
            device_map="auto" if torch.cuda.is_available() else "cpu",
            trust_remote_code=True
        )
        if num_added > 0:
            base_model.resize_token_embeddings(len(tokenizer))
            
        merged_model = PeftModel.from_pretrained(base_model, args.output_dir)
        merged_model = merged_model.merge_and_unload()
        
        os.makedirs(args.merged_output_dir, exist_ok=True)
        merged_model.save_pretrained(args.merged_output_dir)
        tokenizer.save_pretrained(args.merged_output_dir)
        print(f"🎉 Merged standalone model saved to: {args.merged_output_dir}")
        print(f"👉 Ready for llama.cpp convert_hf_to_gguf.py and Q4_K_M quantization!")

if __name__ == "__main__":
    main()
