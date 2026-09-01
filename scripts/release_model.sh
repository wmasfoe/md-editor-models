#!/usr/bin/env bash
# ==============================================================================
# RFC-002 一键微调、量化与 GitHub Release 发布流水线脚本
# 用法: ./scripts/release_model.sh [VERSION] [BASE_MODEL]
# 示例: ./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-0.5B-Instruct
# ==============================================================================

set -e

VERSION=${1:-"v1.0.0"}
BASE_MODEL=${2:-"Qwen/Qwen2.5-0.5B-Instruct"}
REPO="wmasfoe/md-editor-models"

# 自动检测 Python 执行器
if command -v uv &> /dev/null && [ -d ".venv" ]; then
    PY_CMD="uv run python"
elif [ -f ".venv/bin/python" ]; then
    PY_CMD=".venv/bin/python"
else
    PY_CMD="python3"
fi

OUTPUT_DIR="output"
LORA_DIR="${OUTPUT_DIR}/qwen-editor-lora"
MERGED_DIR="${OUTPUT_DIR}/qwen-editor-merged"
F16_GGUF="${OUTPUT_DIR}/model-f16.gguf"

if [[ "$BASE_MODEL" == *"1.5B"* ]]; then
  MODEL_ID="qwen2.5-1.5b-editor"
  TIER="standard"
else
  MODEL_ID="qwen2.5-0.5b-editor"
  TIER="lite"
fi

FINAL_GGUF="${OUTPUT_DIR}/${MODEL_ID}-${VERSION}-Q4_K_M.gguf"
MANIFEST_FILE="${OUTPUT_DIR}/manifest.json"

echo "======================================================================"
echo "🚀 开始执行 RFC-002 端侧小模型一键构建与发布流水线"
echo "🔹 版本标签 (Version):  $VERSION"
echo "🔹 目标基座 (Model):    $BASE_MODEL"
echo "🔹 Python 执行器:       $PY_CMD"
echo "🔹 最终 GGUF 文件:      $FINAL_GGUF"
echo "======================================================================"

# ------------------------------------------------------------------------------
# 步骤 1: 检查前置依赖与编译 llama.cpp
# ------------------------------------------------------------------------------
echo -e "\n📦 [1/5] 检查系统环境与量化工具..."

pip install -q sentencepiece gguf protobuf "torchao>=0.16.0"

if [ ! -f "llama.cpp/build/bin/llama-quantize" ] && [ ! -f "llama.cpp/llama-quantize" ]; then
    echo "⚙️ 正在自动拉取并轻量编译 llama.cpp 量化工具..."
    if [ ! -d "llama.cpp" ]; then
        git clone --depth 1 https://github.com/ggerganov/llama.cpp
    fi
    cmake -B llama.cpp/build -S llama.cpp -DCMAKE_BUILD_TYPE=Release
    cmake --build llama.cpp/build --config Release -j --target llama-quantize
fi

QUANTIZE_BIN="llama.cpp/build/bin/llama-quantize"
if [ ! -f "$QUANTIZE_BIN" ]; then
    QUANTIZE_BIN="llama.cpp/llama-quantize"
fi

# ------------------------------------------------------------------------------
# 步骤 2: SFT 训练与 LoRA 权重合并 (若已合并则跳过训练)
# ------------------------------------------------------------------------------
echo -e "\n🔥 [2/5] 检查 SFT 微调模型..."

if [ -d "$MERGED_DIR" ] && [ -f "$MERGED_DIR/model.safetensors" ]; then
    echo "✨ 检测到已训练合并好的模型 ($MERGED_DIR)，直接进入 GGUF 量化阶段！"
else
    if [ ! -f "data/train.jsonl" ]; then
        echo "📊 正在自动构建 RFC-002 数据集..."
        $PY_CMD scripts/build_dataset.py
    fi

    $PY_CMD train_sft.py \
      --model_name_or_path "$BASE_MODEL" \
      --train_file "data/train.jsonl" \
      --val_file "data/val.jsonl" \
      --output_dir "$LORA_DIR" \
      --num_train_epochs 3 \
      --batch_size 16 \
      --gradient_accumulation_steps 1 \
      --learning_rate 2e-4 \
      --lora_r 16 \
      --lora_alpha 32 \
      --merge_and_save \
      --merged_output_dir "$MERGED_DIR"

    echo "✅ SFT 训练与模型合并完成: $MERGED_DIR"
fi

# ------------------------------------------------------------------------------
# 步骤 3: 转换为 GGUF 并进行 Q4_K_M 量化
# ------------------------------------------------------------------------------
echo -e "\n⚡ [3/5] 正在转换为 GGUF 并执行 Q4_K_M 端侧极致量化..."

python3 llama.cpp/convert_hf_to_gguf.py "$MERGED_DIR" --outfile "$F16_GGUF" --outtype f16
"$QUANTIZE_BIN" "$F16_GGUF" "$FINAL_GGUF" Q4_K_M
rm -f "$F16_GGUF"

GGUF_SIZE=$(stat -c%s "$FINAL_GGUF" 2>/dev/null || stat -f%z "$FINAL_GGUF")
GGUF_SHA256=$(sha256sum "$FINAL_GGUF" | awk '{print $1}')

echo "✅ GGUF 量化完成!"
echo "├── 文件路径: $FINAL_GGUF"
echo "├── 文件大小: $(( GGUF_SIZE / 1024 / 1024 )) MB ($GGUF_SIZE 字节)"
echo "└── SHA256:  $GGUF_SHA256"

# ------------------------------------------------------------------------------
# 步骤 4: 生成 md-editor 客户端 Manifest 描述文件
# ------------------------------------------------------------------------------
echo -e "\n📋 [4/5] 生成客户端 Manifest 配置文件..."

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/$(basename "$FINAL_GGUF")"

cat <<EOF > "$MANIFEST_FILE"
{
  "modelId": "${MODEL_ID}",
  "version": "${VERSION#v}",
  "tier": "${TIER}",
  "quant": "Q4_K_M",
  "sizeBytes": ${GGUF_SIZE},
  "sha256": "${GGUF_SHA256}",
  "downloadUrl": "${DOWNLOAD_URL}",
  "contextSize": 8192,
  "languages": ["zh", "en", "ja", "ko", "ru", "fr"],
  "specialTokens": {
    "fimPrefix": "<|fim_prefix|>",
    "fimSuffix": "<|fim_suffix|>",
    "fimMiddle": "<|fim_middle|>",
    "fimEnd": "<|fim_end|>",
    "gecZh": "<|task_gec_zh|>",
    "gecEn": "<|task_gec_en|>",
    "gecJa": "<|task_gec_ja|>",
    "gecKo": "<|task_gec_ko|>",
    "gecRu": "<|task_gec_ru|>",
    "gecFr": "<|task_gec_fr|>",
    "punc": "<|task_punc|>",
    "preserve": "<|task_preserve|>"
  }
}
EOF

echo "✅ Manifest 已生成: $MANIFEST_FILE"

# ------------------------------------------------------------------------------
# 步骤 5: 发布到 GitHub Releases
# ------------------------------------------------------------------------------
echo -e "\n🚀 [5/5] 发布检查..."

HAS_GH_AUTH=false
if command -v gh &> /dev/null; then
    if [ -n "$GH_TOKEN" ] || [ -n "$GITHUB_TOKEN" ] || gh auth status &> /dev/null; then
        HAS_GH_AUTH=true
    fi
fi

if [ "$HAS_GH_AUTH" = true ]; then
    echo "✨ 检测到 GitHub 凭证，正在发布产物至 GitHub Releases (${REPO}@${VERSION})..."
    RELEASE_TITLE="md-editor SLM ${MODEL_ID} ${VERSION}"
    RELEASE_NOTES="### md-editor 专属端侧小模型 (${VERSION})

#### 🌟 模型规格
- **Base Model**: \`${BASE_MODEL}\`
- **Format**: GGUF (\`Q4_K_M\`)
- **Size**: \`$(( GGUF_SIZE / 1024 / 1024 )) MB\`
- **SHA256**: \`${GGUF_SHA256}\`
- **Supported Languages**: 中、英、日、韩、俄、法 (6 语种)

#### 📋 客户端 Manifest 配置
\`\`\`json
$(cat "$MANIFEST_FILE")
\`\`\`
"
    if gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
        gh release upload "$VERSION" "$FINAL_GGUF" "$MANIFEST_FILE" --repo "$REPO" --clobber
    else
        gh release create "$VERSION" "$FINAL_GGUF" "$MANIFEST_FILE" \
          --repo "$REPO" \
          --title "$RELEASE_TITLE" \
          --notes "$RELEASE_NOTES"
    fi
    echo "🎉 发布成功！上线地址: https://github.com/${REPO}/releases/tag/${VERSION}"
else
    echo "ℹ️ 未检测到 GitHub Token (GH_TOKEN)，已跳过 Release 上传。"
    echo "👉 GGUF 模型与 Manifest 完好保存在: ${OUTPUT_DIR}/"
fi

echo -e "\n======================================================================"
echo "🎉 全流程构建完成！"
echo "📦 GGUF 文件: $FINAL_GGUF"
echo "📋 Manifest:  $MANIFEST_FILE"
echo "======================================================================"
