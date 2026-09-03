#!/usr/bin/env python3
"""生成/更新客户端可消费的模型资产 manifest。

兼容旧版完整 GGUF 条目，同时支持 v2 的 Base + Adapter 能力矩阵。
"""
import argparse
import json
import os
from datetime import datetime, timezone


def parse_args():
    parser = argparse.ArgumentParser(description="Update model asset manifest for md-editor releases")
    parser.add_argument("--manifest_path", default="output/manifest.json")
    parser.add_argument("--version", required=True)
    parser.add_argument("--model_id", required=True)
    parser.add_argument("--tier", required=True, choices=["lite", "standard", "pro"])
    parser.add_argument("--display_name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--quant", default="Q4_K_M")
    parser.add_argument("--filename")
    parser.add_argument("--size_bytes", type=int, default=0)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--download_url", default="")
    parser.add_argument("--recommended", action="store_true")
    parser.add_argument("--asset_kind", choices=["legacy-model", "base", "adapter"], default="legacy-model")
    parser.add_argument("--task", choices=["gec", "completion", "distill", "style-analysis"])
    parser.add_argument("--base_model_id", default="")
    parser.add_argument("--base_model_version", default="")
    parser.add_argument("--base_sha256", default="")
    parser.add_argument("--prompt_protocol", default="")
    parser.add_argument("--grammar", default="")
    parser.add_argument("--available", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def empty_manifest(version: str) -> dict:
    return {
        "schemaVersion": 2,
        "version": version.lstrip("v"),
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
            "preserve": "<|task_preserve|>",
        },
        "models": [],
    }


def load_manifest(path: str, version: str) -> dict:
    if not os.path.exists(path):
        return empty_manifest(version)
    with open(path, "r", encoding="utf-8") as file:
        manifest = json.load(file)
    manifest.setdefault("schemaVersion", 2)
    manifest.setdefault("models", [])
    manifest["version"] = version.lstrip("v")
    return manifest


def asset(args) -> dict:
    result = {
        "version": args.version.lstrip("v"),
        "filename": args.filename or "",
        "sizeBytes": args.size_bytes,
        "sha256": args.sha256.lower(),
        "downloadUrl": args.download_url,
    }
    if args.quant:
        result["quant"] = args.quant
    if args.asset_kind == "adapter":
        result.update({
            "adapterId": f"{args.base_model_id}-{args.task}",
            "task": args.task,
            "baseModelId": args.base_model_id,
            "baseModelVersion": args.base_model_version,
            "baseSha256": args.base_sha256.lower(),
        })
        if args.prompt_protocol:
            result["promptProtocol"] = args.prompt_protocol
        if args.grammar:
            result["grammar"] = args.grammar
    return result


def upsert(args, manifest: dict) -> None:
    models = manifest["models"]
    model = next((item for item in models if item.get("modelId") == args.model_id), None)
    if model is None:
        model = {
            "modelId": args.model_id,
            "tier": args.tier,
            "displayName": args.display_name,
            "description": args.description,
            "recommended": args.recommended,
            "isAvailable": args.available,
            "capabilities": {},
        }
        models.append(model)
    else:
        model.update({
            "tier": args.tier,
            "displayName": args.display_name,
            "description": args.description,
            "recommended": args.recommended,
            "isAvailable": args.available,
        })

    if args.asset_kind == "legacy-model":
        model.update(asset(args))
        return
    if args.asset_kind == "base":
        model["base"] = asset(args)
        return
    if not args.task:
        raise ValueError("--asset_kind adapter requires --task")
    model.setdefault("capabilities", {})[args.task] = asset(args)


def main():
    args = parse_args()
    manifest = load_manifest(args.manifest_path, args.version)
    upsert(args, manifest)
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(os.path.abspath(args.manifest_path)), exist_ok=True)
    with open(args.manifest_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2, ensure_ascii=False)
        file.write("\n")
    print(f"✅ Manifest 已更新（schemaVersion={manifest['schemaVersion']}，模型档位 {len(manifest['models'])} 个）：{args.manifest_path}")


if __name__ == "__main__":
    main()
