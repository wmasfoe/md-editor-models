#!/usr/bin/env bash
# 一键在 GPU 算力机上启动训练的脚本 (适用于 AutoDL / Colab / 本地显卡)
set -e

MODEL_NAME=${1:-"Qwen/Qwen2.5-0.5B-Instruct"}
OUTPUT_DIR="output/qwen-0.5b-writing-lora"
MERGED_DIR="output/qwen-0.5b-writing-merged"

echo "========================================================"
echo "🚀 启动写作辅助模型 SFT 微调任务"
echo "🔹 基座模型: $MODEL_NAME"
echo "🔹 LoRA 目录: $OUTPUT_DIR"
echo "🔹 合并导出: $MERGED_DIR"
echo "========================================================"

# 执行训练，并自动合并 LoRA 权重供后续 GGUF 量化使用
python train_sft.py \
  --model_name_or_path "$MODEL_NAME" \
  --train_file "data/train.jsonl" \
  --val_file "data/val.jsonl" \
  --output_dir "$OUTPUT_DIR" \
  --num_train_epochs 3 \
  --batch_size 4 \
  --gradient_accumulation_steps 4 \
  --learning_rate 2e-4 \
  --max_seq_length 1024 \
  --lora_r 16 \
  --lora_alpha 32 \
  --merge_and_save \
  --merged_output_dir "$MERGED_DIR"

echo "========================================================"
echo "🎉 训练与模型合并完成！"
echo "👉 完整模型已保存在: $MERGED_DIR"
echo "👉 接下来可以使用 llama.cpp 转换为 Q4_K_M GGUF 文件"
echo "========================================================"
