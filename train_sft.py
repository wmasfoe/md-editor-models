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

# 兼容性修复：解决部分环境（如 Google Colab）中预装旧版 torchao (<0.16.0) 导致 PEFT 抛出未捕获 ImportError 的已知问题
def _patch_peft_torchao():
    try:
        import peft.import_utils
        _orig_func = getattr(peft.import_utils, "is_torchao_available", None)
        if _orig_func is not None:
            def _safe_is_torchao_available():
                try:
                    return _orig_func()
                except Exception:
                    return False
            peft.import_utils.is_torchao_available = _safe_is_torchao_available
            if hasattr(peft, "tuners") and hasattr(peft.tuners, "lora") and hasattr(peft.tuners.lora, "torchao"):
                peft.tuners.lora.torchao.is_torchao_available = _safe_is_torchao_available
    except Exception:
        pass

_patch_peft_torchao()



def materialize_meta_tensors(model, device):
    """确保模型中所有遗留在 meta 上的非持久化缓冲区和参数（如 Gemma 4 架构特性）被物化到目标设备"""
    if device is None:
        return
    for name, buf in model.named_buffers():
        if getattr(buf, "is_meta", False):
            parent_name, buf_name = name.rsplit(".", 1) if "." in name else ("", name)
            parent = model.get_submodule(parent_name) if parent_name else model
            parent.register_buffer(buf_name, torch.zeros(buf.shape, dtype=buf.dtype, device=device), persistent=False)

    for name, param in model.named_parameters():
        if getattr(param, "is_meta", False):
            parent_name, param_name = name.rsplit(".", 1) if "." in name else ("", name)
            parent = model.get_submodule(parent_name) if parent_name else model
            parent.register_parameter(param_name, torch.nn.Parameter(torch.zeros(param.shape, dtype=param.dtype, device=device)))


# RFC-002 专属全集控制符（作为 Special Tokens 固化进词表）
SPECIAL_TOKENS = [
    "<|task_distill|>",
    "<|task_completion|>",
    "<|task_gec_mixed|>",
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
    parser = argparse.ArgumentParser(description="Fine-tune Qwen/Gemma on Markdown SLM dataset with RFC-002 tokens and LoRA")
    
    # 模型与数据路径 (支持 Qwen/Qwen3-0.6B、Qwen/Qwen3-1.7B 与 google/gemma-4-e2b)
    parser.add_argument("--model_name_or_path", type=str, default="Qwen/Qwen3-0.6B", help="Base model identifier or local path")
    parser.add_argument("--train_file", type=str, default="data/train.jsonl", help="Path to training jsonl file")
    parser.add_argument("--task", type=str, default="multi", choices=["multi", "gec", "completion", "distill", "style-analysis"], help="Task profile for this adapter")
    parser.add_argument("--adapter_id", type=str, default="", help="Stable adapter identifier")
    parser.add_argument("--val_file", type=str, default="data/val.jsonl", help="Path to validation jsonl file")
    parser.add_argument("--output_dir", type=str, default="output/editor-lora", help="Directory to save LoRA checkpoints")
    
    # 训练超参数 (针对 L4 / A100 / T4 GPU 优化，防过拟合调优)
    parser.add_argument("--num_train_epochs", type=int, default=2, help="Total training epochs (1-2 for optimal LoRA convergence)")
    parser.add_argument("--batch_size", type=int, default=32, help="Per-device batch size")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2, help="Gradient accumulation steps")
    parser.add_argument("--learning_rate", type=float, default=1e-4, help="Initial learning rate (1e-4 for stable convergence)")
    parser.add_argument("--weight_decay", type=float, default=0.01, help="Weight decay for regularization")
    parser.add_argument("--max_seq_length", type=int, default=1536, help="Maximum sequence length")
    parser.add_argument("--warmup_steps", type=int, default=30, help="Warmup steps")
    parser.add_argument("--logging_steps", type=int, default=10, help="Log metrics every N steps")
    
    # LoRA / QLoRA 配置 (轻量化防过拟合)
    parser.add_argument("--lora_r", type=int, default=8, help="LoRA rank (8 is optimal for SLM format alignment)")
    parser.add_argument("--lora_alpha", type=int, default=16, help="LoRA scaling factor")
    parser.add_argument("--lora_dropout", type=float, default=0.1, help="LoRA dropout rate for regularization")
    parser.add_argument("--use_qlora", action="store_true", help="Enable 4-bit QLoRA to save VRAM")
    parser.add_argument("--assistant_only_loss", action="store_true", default=True, help="Compute loss ONLY on assistant responses, preventing prompt memorization and overfitting")
    
    # 导出与合并
    parser.add_argument("--merge_and_save", action="store_true", help="Merge LoRA weights into base model after training")
    parser.add_argument("--merged_output_dir", type=str, default="output/editor-merged", help="Directory to save the merged standalone model")

    return parser.parse_args()

def filter_dataset_by_task(dataset, task):
    """任务专用训练：按消息文本中的任务控制符过滤样本。
    仅当 --task 指定为单一任务时生效，--task multi 保持全量多任务数据。
    """
    if task == "multi":
        return dataset

    def _markers(task_name):
        # 控制符 → 任务关键词映射（与 build_dataset.py 产出一致）
        return {
            "gec": ["<|task_gec_zh|>", "<|task_gec_mixed|>", "<|task_gec_en|>",
                    "<|task_punc|>", "<|task_preserve|>"],
            "completion": ["<|task_completion|>", "<|fim_prefix|>"],
            "distill": ["<|task_distill|>"],
            "style-analysis": ["<|task_distill|>"],  # 风格分析尚未有专属语料，先复用提炼入口
        }[task_name]

    def _sample_text(sample):
        parts = []
        for msg in sample.get("messages", []):
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
        return "".join(parts)

    def _keep(sample):
        text = _sample_text(sample)
        return any(marker in text for marker in _markers(task))

    filtered = dataset.filter(_keep)
    print(f"🎯 任务过滤 ({task}): {len(dataset)} → {len(filtered)} 条")
    if len(filtered) == 0:
        raise ValueError(
            f"--task {task} 过滤后训练样本为 0，请检查数据是否包含对应任务控制符。"
        )
    return filtered


def main():
    args = parse_args()
    
    print("=" * 60)
    print(f"🚀 Starting SLM High-Throughput Fine-Tuning Pipeline")
    print(f"🔹 Base Model:   {args.model_name_or_path}")
    print(f"🔹 Task:         {args.task}" + (f" (adapter: {args.adapter_id})" if args.adapter_id else ""))
    print(f"🔹 Train Dataset: {args.train_file}")
    print(f"🔹 Val Dataset:   {args.val_file}")
    print(f"🔹 Batch Size:    {args.batch_size} (Grad Accum: {args.gradient_accumulation_steps})")
    print(f"🔹 BF16 Support:  {torch.cuda.is_available() and torch.cuda.is_bf16_supported()}")
    print(f"🔹 Output Dir:    {args.output_dir}")
    print("=" * 60)

    # 1. 检查数据文件
    if not os.path.exists(args.train_file):
        raise FileNotFoundError(f"Training dataset not found: {args.train_file}. Please run scripts/build_dataset.py first!")

    # 2. 加载数据集（任务专用训练时按任务控制符过滤）
    data_files = {"train": args.train_file}
    if os.path.exists(args.val_file):
        data_files["validation"] = args.val_file
        
    dataset = load_dataset("json", data_files=data_files)
    dataset["train"] = filter_dataset_by_task(dataset["train"], args.task)
    if "validation" in dataset:
        dataset["validation"] = filter_dataset_by_task(dataset["validation"], args.task)
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

    # 3.1 为 Gemma 等模型注入 training-compatible chat template (含 TRL {% generation %} 标记)
    if args.assistant_only_loss:
        if "gemma" in args.model_name_or_path.lower() or (tokenizer.chat_template and "<start_of_turn>" in tokenizer.chat_template):
            gemma_train_template = (
                "{{ bos_token }}"
                "{% for message in messages %}"
                "{% if message['role'] == 'user' %}"
                "{{ '<start_of_turn>user\n' + message['content'] | trim + '<end_of_turn>\n' }}"
                "{% elif message['role'] == 'assistant' or message['role'] == 'model' %}"
                "{{ '<start_of_turn>model\n' }}"
                "{% generation %}"
                "{{ message['content'] | trim + '<end_of_turn>\n' }}"
                "{% endgeneration %}"
                "{% endif %}"
                "{% endfor %}"
                "{% if add_generation_prompt %}"
                "{{ '<start_of_turn>model\n' }}"
                "{% endif %}"
            )
            tokenizer.chat_template = gemma_train_template
            print("✨ 为 Gemma 架构注入 training-compatible chat template (已启用 {% generation %} 助手掩码标记)")
        elif tokenizer.chat_template and "{% generation %}" not in tokenizer.chat_template:
            try:
                from trl.chat_template_utils import add_generation_tags
                tokenizer = add_generation_tags(tokenizer)
                print("✨ 自动调用 add_generation_tags 补齐 {% generation %} 助手掩码标记")
            except Exception as e:
                print(f"ℹ️ add_generation_tags 提示: {e}")

    # 任务控制符按训练模式区分处理：
    # - multi（legacy 完整模型）：注册为特殊 Token 并扩展词表，保持 v1.1 兼容语义
    # - 单任务 Adapter：不注册 Token。<|task_*|> 作为普通文本参与训练（客户端 prompt
    #   也以文本字符串发送，两侧编码一致），从而保持纯 LoRA delta，可被
    #   llama.cpp convert_lora_to_gguf 接受（该格式不支持扩词表/modules_to_save 完整权重）。
    num_added = 0
    if args.task == "multi":
        num_added = tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})
        if num_added > 0:
            print(f"✨ Registered {num_added} RFC-002 special control tokens in tokenizer vocabulary: {SPECIAL_TOKENS}")
    else:
        print(f"ℹ️ 单任务 Adapter 模式（{args.task}）：任务控制符按普通文本训练，不扩展词表。")

    # 4. 加载基座模型（支持 QLoRA 4-bit 量化加载，L4 显存足够直接 FP16/BF16）
    bnb_config = None
    if args.use_qlora:
        print("💡 QLoRA enabled: loading base model in 4-bit NormalFloat precision...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            bnb_4bit_use_double_quant=True
        )

    model_dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else (torch.float16 if torch.cuda.is_available() else torch.float32)

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        quantization_config=bnb_config,
        device_map="auto" if torch.cuda.is_available() else None,
        torch_dtype=model_dtype,
        attn_implementation="sdpa" if torch.cuda.is_available() else None,
        trust_remote_code=True
    )

    # 🛡️ 鲁棒性防线：自动检测并物化任何遗留在 meta 上的非持久化缓冲区与参数（如 Gemma 4 架构特性）
    target_device = torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")
    materialize_meta_tensors(model, target_device)

    # 若添加了新 token，扩充 embedding 层
    if num_added > 0:
        model.resize_token_embeddings(len(tokenizer))

    # 5. 配置 LoRA
    # 单任务 Adapter 必须保持纯 delta（仅 lora_A/lora_B），不包含 modules_to_save：
    # llama.cpp LoRA GGUF 无法表达完整权重副本，任何 modules_to_save 都会导致转换失败。
    adapter_modules_to_save = ["embed_tokens", "lm_head"] if args.task == "multi" else None

    # Gemma 4 等多模态模型在视觉与音频塔使用了 Gemma4ClippableLinear (非标准 nn.Linear)，
    # 若全局匹配 ["q_proj", ...] 会匹配到视觉/音频编码器。
    # 因此在存在 language_model 时，精准限定仅对 language_model 的文本解码层注入 LoRA。
    if hasattr(model, "language_model") or "gemma-4" in args.model_name_or_path.lower() or "gemma4" in args.model_name_or_path.lower():
        target_modules = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
        print("🎯 检测到 Gemma 4 多模态架构，自动精准锁定 language_model 文本解码层注入 LoRA。")
    else:
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=target_modules,
        modules_to_save=adapter_modules_to_save,
        bias="none"
    )

    # 6. 配置 SFTTrainer 训练参数与 Assistant-Only Loss
    has_valid_eval = "validation" in dataset and len(dataset["validation"]) > 0

    data_collator = None
    dataset_text_field = None
    use_completion_collator = False

    if args.assistant_only_loss:
        try:
            from trl import DataCollatorForCompletionOnlyLM
            if "gemma" in args.model_name_or_path.lower() or (tokenizer.chat_template and "<start_of_turn>" in tokenizer.chat_template):
                response_template = "<start_of_turn>model\n"
            else:
                response_template = "<|im_start|>assistant\n"

            def format_prompts(batch):
                return {"text": [tokenizer.apply_chat_template(m, tokenize=False) for m in batch["messages"]]}

            dataset["train"] = dataset["train"].map(format_prompts, batched=True, desc="Formatting train chat template")
            if has_valid_eval:
                dataset["validation"] = dataset["validation"].map(format_prompts, batched=True, desc="Formatting val chat template")

            data_collator = DataCollatorForCompletionOnlyLM(
                response_template=response_template,
                tokenizer=tokenizer
            )
            dataset_text_field = "text"
            use_completion_collator = True
            print(f"✨ 启用 DataCollatorForCompletionOnlyLM (响应标记: {repr(response_template)})，实现精确助手 Loss 掩码。")
        except Exception as e:
            print(f"ℹ️ Completion collator 初始化提示: {e}，将采用标准 SFTConfig 模式。")

    sft_config = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        warmup_steps=args.warmup_steps,
        logging_steps=args.logging_steps,
        save_strategy="epoch",
        save_total_limit=2,
        eval_strategy="epoch" if has_valid_eval else "no",
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
        lr_scheduler_type="cosine",
        max_length=args.max_seq_length,
        assistant_only_loss=args.assistant_only_loss if not use_completion_collator else False,
        dataloader_num_workers=min(4, os.cpu_count()) if os.cpu_count() else 0,
        dataloader_pin_memory=True if torch.cuda.is_available() else False,
        report_to="none"
    )

    # 7. 实例化 Trainer 并启动训练
    trainer_kwargs = {
        "model": model,
        "args": sft_config,
        "train_dataset": dataset["train"],
        "eval_dataset": dataset["validation"] if has_valid_eval else None,
        "peft_config": peft_config,
        "processing_class": tokenizer,
    }
    if data_collator is not None:
        trainer_kwargs["data_collator"] = data_collator
    if dataset_text_field is not None:
        trainer_kwargs["dataset_text_field"] = dataset_text_field

    try:
        trainer = SFTTrainer(**trainer_kwargs)
    except Exception as e:
        if "chat template" in str(e).lower() or "generation" in str(e).lower() or "prefix-preservation" in str(e).lower():
            print(f"⚠️ 捕获到 Chat Template 兼容性异常: {e}，自动降级至标准 SFT 模式继续训练...")
            sft_config.assistant_only_loss = False
            trainer_kwargs.pop("data_collator", None)
            trainer_kwargs.pop("dataset_text_field", None)
            trainer = SFTTrainer(**trainer_kwargs)
        else:
            raise e

    # 自动检测检查点以支持中断续训
    last_checkpoint = None
    if os.path.isdir(args.output_dir):
        from transformers.trainer_utils import get_last_checkpoint
        last_checkpoint = get_last_checkpoint(args.output_dir)
        if last_checkpoint is not None:
            print(f"🔄 发现可用检查点: {last_checkpoint}，自动接续训练...")

    print("\n📊 LoRA 可训练参数分布:")
    if hasattr(trainer.model, "print_trainable_parameters"):
        trainer.model.print_trainable_parameters()

    print("\n🔥 Starting training...")
    trainer.train(resume_from_checkpoint=last_checkpoint)

    # 8. 保存最佳 LoRA Adapter 权重与更新后的 Tokenizer
    print(f"\n💾 Saving final LoRA adapter to {args.output_dir}...")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"✅ LoRA Adapter saved successfully!")

    # 9. 可选：合并 LoRA 权重到基座模型并导出完整模型（供 llama.cpp 转换为 GGUF）
    if args.merge_and_save and args.task != "multi":
        raise SystemExit(
            "❌ --merge_and_save 仅适用于 multi（legacy 完整模型）模式。"
            "单任务 Adapter 应直接转换 LoRA（llama.cpp convert_lora_to_gguf）。"
        )
    if args.merge_and_save:
        print("\n🔄 Merging LoRA adapter with base model for standalone GGUF export...")
        base_model = AutoModelForCausalLM.from_pretrained(
            args.model_name_or_path,
            torch_dtype=torch.float16,
            device_map="auto" if torch.cuda.is_available() else "cpu",
            trust_remote_code=True
        )
        materialize_meta_tensors(base_model, target_device)
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
