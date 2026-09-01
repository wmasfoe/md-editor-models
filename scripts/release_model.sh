#!/usr/bin/env bash
# ==============================================================================
# RFC-002 一键微调、量化与 GitHub Release 发布流水线脚本
# 用法: ./scripts/release_model.sh [VERSION] [BASE_MODEL] [REPO_TAG]
# 示例: ./scripts/release_model.sh v1.0.0 Qwen/Qwen2.5-0.5B-Instruct
# ==============================================================================

set -e

VERSION=${1:-"v1.0.0"}
BASE_MODEL=${2:-"Qwen/Qwen2.5-0.5B-Instruct"}
REPO="wmasfoe/md-editor-models"

# 输出路径配置
OUTPUT_DIR="output"
LORA_DIR="${OUTPUT_DIR}/qwen-editor-lora"
MERGED_DIR="${OUTPUT_DIR}/qwen-editor-merged"
F16_GGUF="${OUTPUT_DIR}/model-f16.gguf"

# 根据基座名称决定 GGUF 文件名与标识
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
echo "🔹 目标仓库 (GitHub):   $REPO"
echo "🔹 最终 GGUF 文件:      $FINAL_GGUF"
echo "======================================================================"

# ------------------------------------------------------------------------------
# 步骤 1: 检查前置依赖与工具
# ------------------------------------------------------------------------------
echo -e "\n📦 [1/5] 检查系统工具与环境..."

if ! command -v gh &> /dev/null; then
    echo "❌ 错误: 未检测到 GitHub CLI (gh)。请先安装并登录 gh。"
    exit 1
fi

if ! gh auth status &> /dev/null; then
    echo "❌ 错误: gh 未登录，请先执行 'gh auth login'。"
    exit 1
fi

# 检查/自动构建 llama.cpp 量化工具
if [ ! -f "llama.cpp/build/bin/llama-quantize" ] && [ ! -f "llama.cpp/llama-quantize" ]; then
    echo "⚙️ 未检测到 llama.cpp，正在自动拉取并轻量编译量化工具..."
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
# 步骤 2: SFT 训练与 LoRA 权重合并
# ------------------------------------------------------------------------------
echo -e "\n🔥 [2/5] 开始执行 SFT 多任务微调并自动合并权重..."

# 确保数据集存在
if [ ! -f "data/train.jsonl" ]; then
    echo "📊 正在自动构建 RFC-002 数据集..."
    python scripts/build_dataset.py
fi

python train_sft.py \
  --model_name_or_path "$BASE_MODEL" \
  --train_file "data/train.jsonl" \
  --val_file "data/val.jsonl" \
  --output_dir "$LORA_DIR" \
  --num_train_epochs 3 \
  --batch_size 4 \
  --gradient_accumulation_steps 4 \
  --learning_rate 2e-4 \
  --lora_r 16 \
  --lora_alpha 32 \
  --merge_and_save \
  --merged_output_dir "$MERGED_DIR"

echo "✅ SFT 训练与模型合并完成: $MERGED_DIR"

# ------------------------------------------------------------------------------
# 步骤 3: 转换为 GGUF 并进行 Q4_K_M 量化
# ------------------------------------------------------------------------------
echo -e "\n⚡ [3/5] 正在转换为 GGUF 并执行 Q4_K_M 端侧极致量化..."

python3 llama.cpp/convert_hf_to_gguf.py "$MERGED_DIR" --outfile "$F16_GGUF" --outtype f16
"$QUANTIZE_BIN" "$F16_GGUF" "$FINAL_GGUF" Q4_K_M

# 清理巨大的全精度中间文件
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
echo -e "\n🚀 [5/5] 发布产物至 GitHub Releases (${REPO}@${VERSION})..."

RELEASE_TITLE="md-editor SLM ${MODEL_ID} ${VERSION}"
RELEASE_NOTES="### md-editor 专属端侧小模型 (${VERSION})

#### 🌟 模型规格
- **Base Model**: \`${BASE_MODEL}\`
- **Format**: GGUF (\`Q4_K_M\`)
- **Size**: \`$(( GGUF_SIZE / 1024 / 1024 )) MB\`
- **SHA256**: \`${GGUF_SHA256}\`
- **Supported Languages**: 中、英、日、韩、俄、法 (6 语种)

#### 🚀 核心特性
- **行内 FIM 极速补全** (Ghost Text, 首字延迟 <30ms)
- **多语种语法纠错 (GEC)** (紧凑元组 JSON Diff 输出)
- **标点排版规范化** (盘古之白空格 / 全半角纠正)
- **Markdown / LaTeX / 表格格式保真**

#### 📋 客户端 Manifest 配置
\`\`\`json
$(cat "$MANIFEST_FILE")
\`\`\`
"

# 创建或更新 Release
if gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
    echo "⚠️ Release $VERSION 已存在，正在上传/覆盖最新资源..."
    gh release upload "$VERSION" "$FINAL_GGUF" "$MANIFEST_FILE" --repo "$REPO" --clobber
else
    echo "✨ 正在创建全新 Release $VERSION..."
    gh release create "$VERSION" "$FINAL_GGUF" "$MANIFEST_FILE" \
      --repo "$REPO" \
      --title "$RELEASE_TITLE" \
      --notes "$RELEASE_NOTES"
fi

echo -e "\n======================================================================"
echo "🎉 发布成功！模型产物已正式上线 GitHub Release！"
echo "🌐 Release 页面: https://github.com/${REPO}/releases/tag/${VERSION}"
echo "📦 GGUF 下载直链: ${DOWNLOAD_URL}"
echo "======================================================================"
