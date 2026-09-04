#!/usr/bin/env python3
"""Changelog 管理与自动化工具。

功能：
1. validate: 强校验 changelog.json 的 7 项契约不变量；
2. generate: 由 changelog.json 单向编译生成人类阅读的 CHANGELOG.md；
3. check-version: 校验指定版本是否存在于 changelog.json（用于发版前拦截）；
4. get-notes: 提取指定版本的 Release Notes（用于 GitHub Release 自动组装）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+$")
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VALID_IMPACTS = {"major", "normal"}
VALID_ITEM_TYPES = {"feat", "perf", "fix", "refactor", "breaking", "other"}

SECTION_EMOJI_MAP = [
    (["下载", "流量", "省流量", "更新"], "📦 "),
    (["纠错", "续写", "文本", "体验", "写作"], "✍️ "),
    (["矩阵", "模型", "档位", "参数", "架构"], "💻 "),
    (["特性", "改进", "首发", "发布"], "🚀 "),
]


def get_section_icon(title: str) -> str:
    for keywords, icon in SECTION_EMOJI_MAP:
        if any(kw in title for kw in keywords):
            return icon
    return "✨ "


def parse_semver_tuple(ver_str: str) -> tuple[int, int, int]:
    parts = ver_str.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def load_changelog(filepath: str = "changelog.json") -> dict:
    if not os.path.exists(filepath):
        print(f"❌ 找不到更新日志文件: {filepath}", file=sys.stderr)
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as err:
            print(f"❌ JSON 语法解析失败: {err}", file=sys.stderr)
            sys.exit(1)


def validate_changelog(data: dict) -> list[str]:
    errors: list[str] = []

    # 1. schemaVersion
    if data.get("schemaVersion") != 1:
        errors.append(f"schemaVersion 必须严格为整数 1，当前为: {data.get('schemaVersion')}")

    # 2. latestVersion
    latest_version = data.get("latestVersion")
    if not isinstance(latest_version, str) or not SEMVER_REGEX.match(latest_version):
        errors.append(f"latestVersion 必须为语义化版本格式 (X.Y.Z，无 v 前缀)，当前为: {latest_version}")

    # 3. releases 数组非空
    releases = data.get("releases")
    if not isinstance(releases, list) or len(releases) == 0:
        errors.append("releases 必须为非空数组")
        return errors

    # 4. latestVersion 必须等于 releases[0].version
    first_release_version = releases[0].get("version")
    if latest_version != first_release_version:
        errors.append(f"latestVersion ('{latest_version}') 必须与首项 releases[0].version ('{first_release_version}') 严格相等")

    seen_versions = set()
    prev_date = None

    for idx, rel in enumerate(releases):
        ver = rel.get("version")
        prefix = f"releases[{idx}] (version={ver}):"

        # 5. 版本格式与唯一性
        if not isinstance(ver, str) or not SEMVER_REGEX.match(ver):
            errors.append(f"{prefix} 版本必须符合 X.Y.Z 格式（不可带 v 前缀）")
        elif ver in seen_versions:
            errors.append(f"{prefix} 版本号重复: '{ver}'")
        else:
            seen_versions.add(ver)

        # 6. 日期格式与有效性
        date_str = rel.get("date")
        if not isinstance(date_str, str) or not DATE_REGEX.match(date_str):
            errors.append(f"{prefix} 日期必须为 YYYY-MM-DD 格式，当前为: {date_str}")
        else:
            try:
                curr_date = datetime.strptime(date_str, "%Y-%m-%d")
                if prev_date is not None and curr_date > prev_date:
                    errors.append(f"{prefix} 发布日期 ({date_str}) 比前一个版本发布日期更晚，releases 必须按时间由新到旧降序排列")
                prev_date = curr_date
            except ValueError:
                errors.append(f"{prefix} 日期非有效公历日期: {date_str}")

        # 7. impact 校验
        impact = rel.get("impact")
        if impact is not None and impact not in VALID_IMPACTS:
            errors.append(f"{prefix} impact 必须为 'major' 或 'normal'，当前为: {impact}")

        # 8. summary 校验
        summary = rel.get("summary")
        if not isinstance(summary, str) or len(summary.strip()) == 0:
            errors.append(f"{prefix} summary 必须为非空字符串")

        # 9. sections 校验
        sections = rel.get("sections")
        if not isinstance(sections, list) or len(sections) == 0:
            errors.append(f"{prefix} sections 必须为非空数组")
            continue

        for s_idx, sec in enumerate(sections):
            sec_title = sec.get("title")
            sec_prefix = f"{prefix} sections[{s_idx}]"
            if not isinstance(sec_title, str) or len(sec_title.strip()) == 0:
                errors.append(f"{sec_prefix} title 必须为非空字符串")

            items = sec.get("items")
            if not isinstance(items, list) or len(items) == 0:
                errors.append(f"{sec_prefix} items 必须为非空数组")
                continue

            for i_idx, item in enumerate(items):
                item_prefix = f"{sec_prefix} items[{i_idx}]"
                item_title = item.get("title")
                item_desc = item.get("description")
                item_type = item.get("type")

                if not isinstance(item_title, str) or len(item_title.strip()) == 0:
                    errors.append(f"{item_prefix} title 必须为非空字符串")
                if not isinstance(item_desc, str) or len(item_desc.strip()) == 0:
                    errors.append(f"{item_prefix} description 必须为非空字符串")
                if item_type is not None and item_type not in VALID_ITEM_TYPES:
                    errors.append(f"{item_prefix} type 必须为 {VALID_ITEM_TYPES} 之一，当前为: {item_type}")

    return errors


def generate_markdown(data: dict) -> str:
    lines: list[str] = [
        "# 更新日志 (Changelog)",
        "",
        "这里记录 `md-editor-models` 本地 AI 模型的历次更新与改进。",
        "",
        "---",
        "",
    ]

    for idx, rel in enumerate(data.get("releases", [])):
        version = rel["version"]
        date = rel["date"]
        summary = rel.get("summary", "").strip()
        sections = rel.get("sections", [])

        lines.append(f"## {version} - {date}")
        lines.append("")

        if summary:
            lines.append(summary)
            lines.append("")

        is_single_generic_section = (
            len(sections) == 1 and sections[0].get("title", "").strip() in {"核心改进", "核心特性", "通用改进", "其他改进"}
        )

        for sec in sections:
            sec_title = sec.get("title", "").strip()
            items = sec.get("items", [])

            if not is_single_generic_section:
                icon = get_section_icon(sec_title)
                lines.append(f"### {icon}{sec_title}")

            for item in items:
                title = item.get("title", "").strip()
                desc = item.get("description", "").strip()
                lines.append(f"- **{title}**：{desc}")

            lines.append("")

        if idx < len(data["releases"]) - 1:
            lines.append("---")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def get_version_notes(data: dict, target_version: str) -> str:
    clean_target = target_version.lstrip("v")
    target_rel = next((r for r in data.get("releases", []) if r.get("version") == clean_target), None)
    if not target_rel:
        return ""

    lines: list[str] = []
    summary = target_rel.get("summary", "").strip()
    if summary:
        lines.append(summary)
        lines.append("")

    sections = target_rel.get("sections", [])
    is_single_generic_section = (
        len(sections) == 1 and sections[0].get("title", "").strip() in {"核心改进", "核心特性", "通用改进", "其他改进"}
    )

    for sec in sections:
        sec_title = sec.get("title", "").strip()
        items = sec.get("items", [])

        if not is_single_generic_section:
            icon = get_section_icon(sec_title)
            lines.append(f"### {icon}{sec_title}")

        for item in items:
            title = item.get("title", "").strip()
            desc = item.get("description", "").strip()
            lines.append(f"- **{title}**：{desc}")

        lines.append("")

    return "\n".join(lines).strip()


def main():
    parser = argparse.ArgumentParser(description="Changelog 工具链")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    val_p = subparsers.add_parser("validate", help="校验 changelog.json 契约不变量")
    val_p.add_argument("--file", default="changelog.json", help="changelog.json 路径")

    # generate
    gen_p = subparsers.add_parser("generate", help="根据 changelog.json 生成 CHANGELOG.md")
    gen_p.add_argument("--file", default="changelog.json", help="输入 changelog.json 路径")
    gen_p.add_argument("--out", default="CHANGELOG.md", help="输出 CHANGELOG.md 路径")

    # check-version
    chk_p = subparsers.add_parser("check-version", help="检查指定版本是否存在于 changelog 中")
    chk_p.add_argument("--version", required=True, help="待检查版本号（如 v1.3.0 或 1.3.0）")
    chk_p.add_argument("--file", default="changelog.json", help="changelog.json 路径")

    # get-notes
    note_p = subparsers.add_parser("get-notes", help="提取指定版本的 Markdown Release Notes")
    note_p.add_argument("--version", required=True, help="版本号（如 v1.3.0 或 1.3.0）")
    note_p.add_argument("--file", default="changelog.json", help="changelog.json 路径")

    args = parser.parse_args()
    data = load_changelog(args.file)

    if args.command == "validate":
        errors = validate_changelog(data)
        if errors:
            print(f"❌ 契约校验失败，共发现 {len(errors)} 处错误:", file=sys.stderr)
            for err in errors:
                print(f"   • {err}", file=sys.stderr)
            sys.exit(1)
        print(f"✅ changelog 契约校验通过！共 {len(data['releases'])} 个版本，最新版本: {data['latestVersion']}")

    elif args.command == "generate":
        errors = validate_changelog(data)
        if errors:
            print(f"❌ 契约校验失败，无法生成 Markdown:", file=sys.stderr)
            for err in errors:
                print(f"   • {err}", file=sys.stderr)
            sys.exit(1)
        content = generate_markdown(data)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ 成功从 {args.file} 编译生成 {args.out}！")

    elif args.command == "check-version":
        clean_ver = args.version.lstrip("v")
        exists = any(r.get("version") == clean_ver for r in data.get("releases", []))
        if not exists:
            print(f"❌ changelog.json 中尚未登记版本 {clean_ver}！发版前请先添加更新日志。", file=sys.stderr)
            sys.exit(1)
        print(f"✅ 版本 {clean_ver} 已在 changelog.json 中就绪。")

    elif args.command == "get-notes":
        notes = get_version_notes(data, args.version)
        if not notes:
            print(f"⚠️ 未找到版本 {args.version} 的详细更新说明。", file=sys.stderr)
            sys.exit(1)
        print(notes)


if __name__ == "__main__":
    main()
