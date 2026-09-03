#!/usr/bin/env bash
# ==============================================================================
# md-editor-models 一键微调、量化与 GitHub Release 发布流水线
#
# 三种资产模式：
# 1) legacy-model（默认，兼容旧版完整 GGUF）:
#    ./scripts/release_model.sh v1.2.0 Qwen/Qwen3-0.6B
# 2) base（v2：从官方 GGUF 拉取并重量化为 Q4_K_M 的基座资产）:
#    ./scripts/release_model.sh v1.2.0 Qwen/Qwen3-0.6B --tier lite --asset base
# 3) adapter（v2：任务专用 LoRA，转 GGUF 后与 base 配合加载）:
#    ./scripts/release_model.sh v1.2.0 Qwen/Qwen3-0.6B --tier lite --asset adapter --task gec
#
# 依赖：llama.cpp 源码树（脚本自动克隆并编译 llama-quantize；
#       convert_lora_to_gguf.py 需要 llama.cpp 仓库内 conversion/ 与 gguf-py）
# ==============================================================================

set -e

VERSION=${1:-"v1.0.0"}
BASE_MODEL=${2:-"Qwen/Qwen3-0.6B"}
ASSET_KIND="legacy-model"
TASK=""
TIER=""
shift 2 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --asset) ASSET_KIND="$2"; shift 2;;
    --task) TASK="$2"; shift 2;;
    --tier) TIER="$2"; shift 2;;
    *) echo "❌ 未知参数: $1"; exit 1;;
  esac
done

if [ "$ASSET_KIND" = "adapter" ] && [ -z "$TASK" ]; then
  echo "❌ --asset adapter 必须提供 --task (gec|completion|distill|style-analysis)"; exit 1
fi

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

# ------------------------------------------------------------------------------
# 模型档位与元数据推断
# ------------------------------------------------------------------------------
MODEL_FAMILY="qwen3"
if [[ "$BASE_MODEL" == *"Qwen2.5"* ]]; then
    MODEL_FAMILY="qwen2.5"
fi

if [ -z "$TIER" ]; then
    if [[ "$BASE_MODEL" == *"1.5B"* ]] || [[ "$BASE_MODEL" == *"1.7B"* ]]; then
        TIER="standard"
    else
        TIER="lite"
    fi
fi

if [[ "$BASE_MODEL" == *"1.7B"* ]]; then
    PARAM_TAG="1.7b"
elif [[ "$BASE_MODEL" == *"1.5B"* ]]; then
    PARAM_TAG="1.5b"
elif [[ "$BASE_MODEL" == *"3.8B"* ]]; then
    PARAM_TAG="3.8b"
elif [[ "$BASE_MODEL" == *"3B"* ]]; then
    PARAM_TAG="3b"
else
    PARAM_TAG="0.6b"
fi

# v2 逻辑档位统一使用客户端逻辑 modelId（与 md-editor manifest 对齐）
if [ "$ASSET_KIND" = "legacy-model" ]; then
    MODEL_ID="${MODEL_FAMILY}-${PARAM_TAG}-editor"
    DISPLAY_NAME="Qwen ${PARAM_TAG} Editor (自动档)"
    DESCRIPTION="端侧垂直小模型（多任务统一版）"
    RECOMMENDED=""
    if [ "$TIER" = "standard" ]; then
        DISPLAY_NAME="Qwen ${PARAM_TAG} Editor (高精度进阶版)"
        DESCRIPTION="更强复杂长句纠错与代码续写能力，推荐 M 系列 Mac 或高配 PC"
    else
        RECOMMENDED="--recommended"
    fi
else
    MODEL_ID="md-editor-writer-${TIER}"
    if [ "$ASSET_KIND" = "base" ]; then
        DISPLAY_NAME=$( [ "$TIER" = "lite" ] && echo "Lite (${PARAM_TAG})" || echo "Standard (${PARAM_TAG})" )
        DESCRIPTION="本地基座模型：与任务 Adapter 配合实现 GEC/续写等能力"
        RECOMMENDED=""
        [ "$TIER" = "lite" ] && RECOMMENDED="--recommended"
    else
        DISPLAY_NAME=$( [ "$TIER" = "lite" ] && echo "Lite (${PARAM_TAG})" || echo "Standard (${PARAM_TAG})" )
        DESCRIPTION="任务专用 LoRA Adapter（${TASK}）"
        RECOMMENDED=""
    fi
fi

BATCH_SIZE=64
GRAD_ACCUM=1
MANIFEST_FILE="${OUTPUT_DIR}/manifest.json"

# 量化标签：base/legacy 产物为 Q4_K_M，adapter LoRA 为 f16（精度优先，体积小不量化）
if [ "$ASSET_KIND" = "adapter" ]; then
    QUANT_LABEL="f16"
else
    QUANT_LABEL="Q4_K_M"
fi

# 产物路径（按资产类型区分）
if [ "$ASSET_KIND" = "legacy-model" ]; then
    LORA_DIR="${OUTPUT_DIR}/${MODEL_ID}-lora"
    MERGED_DIR="${OUTPUT_DIR}/${MODEL_ID}-merged"
    F16_GGUF="${OUTPUT_DIR}/${MODEL_ID}-f16.gguf"
    FINAL_GGUF="${OUTPUT_DIR}/${MODEL_ID}-${VERSION}-Q4_K_M.gguf"
else
    LORA_DIR="${OUTPUT_DIR}/lora-${TIER}-${TASK:-base}"
    MERGED_DIR="${OUTPUT_DIR}/merged-${TIER}-${TASK:-base}"
    F16_GGUF="${OUTPUT_DIR}/tmp-${TIER}-${TASK:-base}-f16.gguf"
    if [ "$ASSET_KIND" = "base" ]; then
        # base：官方 GGUF Q8_0 → 重量化为 Q4_K_M。保留 Hugging Face 命名空间：
        # Qwen/Qwen3-0.6B -> Qwen/Qwen3-0.6B-GGUF，而不是错误的 Qwen3-0.6B-GGUF。
        HF_NAMESPACE=$(dirname "$BASE_MODEL")
        HF_BASENAME=$(basename "$BASE_MODEL")
        if [ "$HF_NAMESPACE" = "." ]; then
            echo "❌ --asset base 需要 Hugging Face 格式的基座 ID（例如 Qwen/Qwen3-0.6B）。"
            exit 1
        fi
        OFFICIAL_GGUF_URL="https://huggingface.co/${HF_NAMESPACE}/${HF_BASENAME}-GGUF/resolve/main/${HF_BASENAME}-Q8_0.gguf"
        FINAL_GGUF="${OUTPUT_DIR}/${TIER}-base-${MODEL_FAMILY}-${PARAM_TAG}-${VERSION}-Q4_K_M.gguf"
    else
        # adapter：LoRA adapter GGUF（f16，精度优先）
        FINAL_GGUF="${OUTPUT_DIR}/${TIER}-${TASK}-${MODEL_FAMILY}-${PARAM_TAG}-${VERSION}-lora-f16.gguf"
    fi
fi

echo "======================================================================"
echo "🚀 md-editor-models 发布流水线"
echo "🔹 版本 (Version):     $VERSION"
echo "🔹 基座 (Base):        $BASE_MODEL"
echo "🔹 资产类型 (Asset):   $ASSET_KIND"
echo "🔹 任务 (Task):        ${TASK:-（无）}"
echo "🔹 档位 (Tier):        $TIER"
echo "🔹 产物 (Output):      $FINAL_GGUF"
echo "======================================================================"

# ------------------------------------------------------------------------------
# 步骤 1: 准备 llama.cpp（quantize + LoRA 转换工具）
# ------------------------------------------------------------------------------
echo -e "\n📦 [1/5] 准备 llama.cpp 量化/LoRA 工具..."
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
# 步骤 2: 按资产类型准备模型权重
# ------------------------------------------------------------------------------
echo -e "\n🔥 [2/5] 准备模型权重 (asset=$ASSET_KIND)..."

if [ "$ASSET_KIND" = "base" ]; then
    # base：下载官方 GGUF 并重量化为 Q4_K_M（无需训练）
    if [ ! -f "$FINAL_GGUF" ]; then
        echo "📥 下载官方基座 GGUF: $OFFICIAL_GGUF_URL"
        curl -sL --fail --max-time 900 -o "${OUTPUT_DIR}/official-${HF_BASENAME}-Q8_0.gguf" "$OFFICIAL_GGUF_URL"
        echo "⚙️ 重量化为 Q4_K_M..."
        "$QUANTIZE_BIN" "${OUTPUT_DIR}/official-${HF_BASENAME}-Q8_0.gguf" "$FINAL_GGUF" Q4_K_M
        rm -f "${OUTPUT_DIR}/official-${HF_BASENAME}-Q8_0.gguf"
    fi
elif [ "$ASSET_KIND" = "adapter" ]; then
    # adapter：任务专用 LoRA 训练（不合并），转 LoRA GGUF
    if [ ! -f "$FINAL_GGUF" ]; then
        if [ ! -d "$LORA_DIR" ] || [ ! -f "$LORA_DIR/adapter_model.safetensors" ]; then
            if [ ! -f "data/train.jsonl" ]; then
                echo "📊 正在自动构建 RFC-003 数据集..."
                $PY_CMD scripts/build_dataset.py
            fi
            $PY_CMD train_sft.py \
              --model_name_or_path "$BASE_MODEL" \
              --train_file "data/train.jsonl" \
              --val_file "data/val.jsonl" \
              --output_dir "$LORA_DIR" \
              --task "$TASK" \
              --adapter_id "${MODEL_ID}-${TASK}" \
              --num_train_epochs 3 \
              --batch_size $BATCH_SIZE \
              --gradient_accumulation_steps $GRAD_ACCUM \
              --learning_rate 2e-4 \
              --lora_r 32 \
              --lora_alpha 64
            echo "✅ 任务专用 LoRA 训练完成: $LORA_DIR"
        fi
        echo "🔄 转换 LoRA → GGUF (f16)..."
        python3 llama.cpp/convert_lora_to_gguf.py "$LORA_DIR" \
          --outfile "$FINAL_GGUF" \
          --outtype f16 \
          --base-model-id "$BASE_MODEL"
    fi
else
    # legacy-model：多任务 SFT → 合并完整模型（向后兼容）
    if [ -d "$MERGED_DIR" ] && [ -f "$MERGED_DIR/model.safetensors" ]; then
        echo "✨ 检测到已训练合并好的模型 ($MERGED_DIR)，直接进入 GGUF 量化阶段！"
    else
        if [ ! -f "data/train.jsonl" ]; then
            echo "📊 正在自动构建 RFC-003 数据集..."
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
fi

# ------------------------------------------------------------------------------
# 步骤 3: 转换为 GGUF 并进行 Q4_K_M 量化（legacy 完整模型需要）
# ------------------------------------------------------------------------------
if [ "$ASSET_KIND" = "legacy-model" ]; then
    echo -e "\n⚡ [3/5] 正在转换为 GGUF 并执行 Q4_K_M 端侧极致量化..."
    python3 llama.cpp/convert_hf_to_gguf.py "$MERGED_DIR" --outfile "$F16_GGUF" --outtype f16
    "$QUANTIZE_BIN" "$F16_GGUF" "$FINAL_GGUF" Q4_K_M
    rm -f "$F16_GGUF"
else
    echo -e "\n⚡ [3/5] 资产已就绪，跳过完整模型转换。"
fi

GGUF_SIZE=$(stat -c%s "$FINAL_GGUF" 2>/dev/null || stat -f%z "$FINAL_GGUF")
GGUF_SHA256=$(sha256sum "$FINAL_GGUF" | awk '{print $1}')

echo "✅ 产物校验完成!"
echo "├── 文件路径: $FINAL_GGUF"
echo "├── 文件大小: $(( GGUF_SIZE / 1024 / 1024 )) MB ($GGUF_SIZE 字节)"
echo "└── SHA256:  $GGUF_SHA256"

# ------------------------------------------------------------------------------
# 步骤 4: 更新客户端 Manifest（schema v2）
# ------------------------------------------------------------------------------
echo -e "\n📋 [4/5] 更新客户端 Manifest.json..."

# 尝试从现有 Release 下载已有 manifest.json 进行增量合并
if command -v gh &> /dev/null && gh release view "$VERSION" --repo "$REPO" &> /dev/null; then
    echo "📥 发现现有 Release $VERSION，正在拉取已有 manifest.json 进行增量合并..."
    gh release download "$VERSION" -p "manifest.json" -O "$MANIFEST_FILE" --repo "$REPO" --clobber || true
fi

DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/$(basename "$FINAL_GGUF")"

MANIFEST_ARGS=(
  --manifest_path "$MANIFEST_FILE"
  --version "$VERSION"
  --model_id "$MODEL_ID"
  --tier "$TIER"
  --display_name "$DISPLAY_NAME"
  --description "$DESCRIPTION"
  --quant "$QUANT_LABEL"
  --filename "$(basename "$FINAL_GGUF")"
  --size_bytes "$GGUF_SIZE"
  --sha256 "$GGUF_SHA256"
  --download_url "$DOWNLOAD_URL"
  --asset_kind "$ASSET_KIND"
)

if [ "$ASSET_KIND" = "adapter" ]; then
    MANIFEST_ARGS+=(--task "$TASK" --base_model_id "md-editor-writer-${TIER}")
fi
[ -n "$RECOMMENDED" ] && MANIFEST_ARGS+=("$RECOMMENDED")

$PY_CMD scripts/update_manifest.py "${MANIFEST_ARGS[@]}"

# Pro 档位占位条目：确保 manifest 始终向客户端表达“Pro 尚未发布”，由远端唯一决定展示状态
$PY_CMD scripts/update_manifest.py \
  --manifest_path "$MANIFEST_FILE" \
  --version "$VERSION" \
  --model_id "md-editor-writer-pro" \
  --tier "pro" \
  --display_name "Pro" \
  --description "旗舰级深度长文创作、论文润色与逻辑重构（敬请期待）。" \
  --asset_kind "legacy-model" \
  --filename "" \
  --size_bytes 0 \
  --sha256 "" \
  --download_url "" \
  --no-available

# ------------------------------------------------------------------------------
# 步骤 5: 发布到 GitHub Releases
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
        echo "🔄 增量追加资产到已有 Release $VERSION..."
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
