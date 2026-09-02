#!/usr/bin/env bash
# ==============================================================================
# RFC-002 一键微调、量化与 GitHub Release 多模型聚合发布流水线脚本
# 用法: ./scripts/release_model.sh [VERSION] [BASE_MODEL]
# 示例: ./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-0.5B-Instruct
#       ./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-Coder-1.5B-Instruct
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

if [[ "$BASE_MODEL" == *"1.5B"* ]]; then
  MODEL_ID="qwen2.5-1.5b-editor"
  TIER="standard"
  DISPLAY_NAME="Qwen 2.5 1.5B (高精度进阶版)"
  DESCRIPTION="更强复杂长句纠错与代码续写能力，推荐 M 系列 Mac 或高配 PC"
  RECOMMENDED=""
  BATCH_SIZE=64
  GRAD_ACCUM=1
else
  MODEL_ID="qwen2.5-0.5b-editor"
  TIER="lite"
  DISPLAY_NAME="Qwen 2.5 0.5B (轻量极速版)"
  DESCRIPTION="首字延迟 <30ms，内存仅占 280MB，适合所有轻薄本与日常流畅写作"
  RECOMMENDED="--recommended"
  BATCH_SIZE=64
  GRAD_ACCUM=1
fi

LORA_DIR="${OUTPUT_DIR}/${MODEL_ID}-lora"
MERGED_DIR="${OUTPUT_DIR}/${MODEL_ID}-merged"
F16_GGUF="${OUTPUT_DIR}/${MODEL_ID}-f16.gguf"
FINAL_GGUF="${OUTPUT_DIR}/${MODEL_ID}-${VERSION}-Q4_K_M.gguf"
MANIFEST_FILE="${OUTPUT_DIR}/manifest.json"

echo "======================================================================"
echo "🚀 开始执行 RFC-002 多模型矩阵聚合发布流水线"
echo "🔹 版本标签 (Version):  $VERSION"
echo "🔹 目标基座 (Model):    $BASE_MODEL ($MODEL_ID - $TIER)"
echo "🔹 目标 GGUF 文件:      $FINAL_GGUF"
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
      --batch_size $BATCH_SIZE \
      --gradient_accumulation_steps $GRAD_ACCUM \
      --learning_rate 2e-4 \
      --lora_r 32 \
      --lora_alpha 64 \
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
# 步骤 4: 增量合并与生成客户端多模型 Manifest
# ------------------------------------------------------------------------------
echo -e "\n📋 [4/5] 增量合并与更新客户端 Manifest.json..."

# 尝试从现有 Release 下载已有的 manifest.json 进行合并
if command -v gh &> /dev/null && gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
    echo "📥 发现现有 Release $VERSION，正在拉取已有 manifest.json 进行增量合并..."
    gh release download "$VERSION" -p "manifest.json" -O "$MANIFEST_FILE" --repo "$REPO" --clobber || true
fi

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/$(basename "$FINAL_GGUF")"

$PY_CMD scripts/update_manifest.py \
  --manifest_path "$MANIFEST_FILE" \
  --version "$VERSION" \
  --model_id "$MODEL_ID" \
  --tier "$TIER" \
  --display_name "$DISPLAY_NAME" \
  --description "$DESCRIPTION" \
  --quant "Q4_K_M" \
  --filename "$(basename "$FINAL_GGUF")" \
  --size_bytes "$GGUF_SIZE" \
  --sha256 "$GGUF_SHA256" \
  --download_url "$DOWNLOAD_URL" \
  $RECOMMENDED

# ------------------------------------------------------------------------------
# 步骤 5: 增量发布到 GitHub Releases
# ------------------------------------------------------------------------------
echo -e "\n🚀 [5/5] 发布与资产同步检查..."

HAS_GH_AUTH=false
if command -v gh &> /dev/null; then
    if [ -n "$GH_TOKEN" ] || [ -n "$GITHUB_TOKEN" ] || gh auth status &> /dev/null; then
        HAS_GH_AUTH=true
    fi
fi

if [ "$HAS_GH_AUTH" = true ]; then
    echo "✨ 正在同步产物至 GitHub Releases (${REPO}@${VERSION})..."
    RELEASE_TITLE="md-editor SLM Models Matrix (${VERSION})"
    RELEASE_NOTES="### md-editor 专属端侧小模型矩阵 (${VERSION})

支持多语种语法纠错 (Tuple JSON Diff)、排版标点规范化与极速行内 FIM 补全。

#### 📋 客户端多模型 Manifest
\`\`\`json
$(cat "$MANIFEST_FILE")
\`\`\`
"
    if gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
        echo "🔄 增量追加新模型到已有 Release $VERSION..."
        gh release upload "$VERSION" "$FINAL_GGUF" "$MANIFEST_FILE" --repo "$REPO" --clobber
        gh release edit "$VERSION" --repo "$REPO" --notes "$RELEASE_NOTES"
    else
        echo "✨ 创建全新 Release $VERSION..."
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
