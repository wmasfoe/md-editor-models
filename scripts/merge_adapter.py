#!/usr/bin/env python3
"""将已训练好的任务 LoRA Adapter 合并回基座模型，导出可转换 GGUF 的完整模型。

为什么需要合并而不是直接转换 LoRA：
- 任务控制 Token（15 个新增词）需要扩展 embedding，训练时以 modules_to_save
  保存完整权重；llama.cpp convert_lora_to_gguf 只接受 lora_A/lora_B delta，
  无法表达完整权重副本。
- 合并后的完整模型包含扩展词表与全部 LoRA 增量，可直接交给
  convert_hf_to_gguf.py 输出 Q8_0/f16 GGUF，推理无需 --lora。

用法：
  python3 scripts/merge_adapter.py \
    --base Qwen/Qwen3-0.6B \
    --adapter output/lora-lite-gec \
    --output output/merged-lite-gec
"""
import argparse
import os

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=str, required=True, help="Base model id or path")
    parser.add_argument("--adapter", type=str, required=True, help="Trained LoRA adapter dir")
    parser.add_argument("--output", type=str, required=True, help="Merged model output dir")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    adapter_config = os.path.join(args.adapter, "adapter_config.json")
    if not os.path.exists(adapter_config):
        raise SystemExit(f"❌ Adapter 目录缺少 adapter_config.json: {args.adapter}")

    tokenizer = AutoTokenizer.from_pretrained(args.adapter, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base,
        torch_dtype=torch.float16,
        device_map="auto" if torch.cuda.is_available() else "cpu",
        trust_remote_code=True,
    )
    base_model.resize_token_embeddings(len(tokenizer))

    merged = PeftModel.from_pretrained(base_model, args.adapter)
    merged = merged.merge_and_unload()

    os.makedirs(args.output, exist_ok=True)
    merged.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    print(f"🎉 合并完成，已保存到: {args.output}")


if __name__ == "__main__":
    main()
