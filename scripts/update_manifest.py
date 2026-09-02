import os
import json
import argparse
from datetime import datetime, timezone

def parse_args():
    parser = argparse.ArgumentParser(description="Update and merge multi-model manifest.json for md-editor releases")
    parser.add_argument("--manifest_path", type=str, default="output/manifest.json", help="Path to manifest.json")
    parser.add_argument("--version", type=str, required=True, help="Release version string (e.g. 1.0.0)")
    parser.add_argument("--model_id", type=str, required=True, help="Unique model identifier")
    parser.add_argument("--tier", type=str, required=True, choices=["lite", "standard", "pro"], help="Model tier")
    parser.add_argument("--display_name", type=str, required=True, help="Display name for editor UI")
    parser.add_argument("--description", type=str, required=True, help="Description of model features")
    parser.add_argument("--quant", type=str, default="Q4_K_M", help="Quantization method")
    parser.add_argument("--filename", type=str, required=True, help="GGUF filename")
    parser.add_argument("--size_bytes", type=int, required=True, help="File size in bytes")
    parser.add_argument("--sha256", type=str, required=True, help="SHA256 checksum")
    parser.add_argument("--download_url", type=str, required=True, help="Download URL")
    parser.add_argument("--recommended", action="store_true", help="Set as recommended model")
    return parser.parse_args()

def main():
    args = parse_args()
    
    # 默认多模型清单框架
    manifest = {
        "version": args.version.lstrip("v"),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "contextSize": 8192,
        "languages": ["zh", "en", "ja", "ko", "ru", "fr"],
        "specialTokens": {
            "fimPrefix": "<|fim_prefix|>",
            "fimSuffix": "<|fim_suffix|>",
            "fimMiddle": "<|fim_middle|>",
            "fimEnd": "<|fim_end|>",
            "distill": "<|task_distill|>",
            "completion": "<|task_completion|>",
            "gecMixed": "<|task_gec_mixed|>",
            "gecZh": "<|task_gec_zh|>",
            "gecEn": "<|task_gec_en|>",
            "gecJa": "<|task_gec_ja|>",
            "gecKo": "<|task_gec_ko|>",
            "gecRu": "<|task_gec_ru|>",
            "gecFr": "<|task_gec_fr|>",
            "punc": "<|task_punc|>",
            "preserve": "<|task_preserve|>"
        },
        "models": []
    }
    
    # 如果已存在旧的 manifest.json，尝试读取并增量合并
    if os.path.exists(args.manifest_path):
        try:
            with open(args.manifest_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing.get("models"), list):
                    manifest["models"] = existing["models"]
                    manifest["version"] = existing.get("version", manifest["version"])
        except Exception as e:
            print(f"⚠️ 读取已有 manifest 失败，将创建新文件: {e}")
            
    # 构建当前模型的元数据对象
    new_model_entry = {
        "modelId": args.model_id,
        "tier": args.tier,
        "displayName": args.display_name,
        "description": args.description,
        "quant": args.quant,
        "filename": args.filename,
        "sizeBytes": args.size_bytes,
        "sha256": args.sha256,
        "downloadUrl": args.download_url,
        "recommended": args.recommended
    }
    
    # 检查是否已存在同名 modelId，存在则替换，不存在则追加
    updated = False
    for i, m in enumerate(manifest["models"]):
        if m.get("modelId") == args.model_id:
            manifest["models"][i] = new_model_entry
            updated = True
            break
            
    if not updated:
        manifest["models"].append(new_model_entry)
        
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    
    # 确保目录存在并保存
    os.makedirs(os.path.dirname(os.path.abspath(args.manifest_path)), exist_ok=True)
    with open(args.manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    print(f"✅ Manifest 已成功更新 (包含 {len(manifest['models'])} 个模型规格): {args.manifest_path}")

if __name__ == "__main__":
    main()
