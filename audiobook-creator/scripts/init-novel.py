#!/usr/bin/env python3
"""Initialize a new audiobook novel project."""

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Initialize a new audiobook novel project")
    parser.add_argument("--novel", required=True, help="Novel name (used as directory name)")
    parser.add_argument("--author", required=True, help="Author name")
    parser.add_argument("--source", required=True, help="Path to novel text file (UTF-8)")
    parser.add_argument("--cover", help="Path to cover image (optional)")
    parser.add_argument("--tid", type=int, help="Bilibili category ID (default from config)")
    parser.add_argument("--tags", nargs="+", help="Bilibili tags (default: 有声书 + novel name)")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["outputDir"]).expanduser()
    sources_dir = output_dir / "sources"
    drafts_dir = output_dir / "drafts"

    sources_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(args.source).expanduser()
    if not source_path.exists():
        print(f"ERROR: Source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    dest_source = sources_dir / f"{args.novel}.txt"
    if dest_source.exists() and source_path.resolve() == dest_source.resolve():
        print(f"Source already in place: {dest_source}")
    elif dest_source.exists():
        print(f"WARNING: Source already exists: {dest_source}")
    else:
        shutil.copy2(str(source_path), str(dest_source))
        print(f"Source copied: {dest_source} ({dest_source.stat().st_size / 1024:.0f} KB)")

    if args.cover:
        cover_path = Path(args.cover).expanduser()
        if cover_path.exists():
            suffix = cover_path.suffix or ".jpg"
            dest_cover = sources_dir / f"{args.novel}-cover{suffix}"
            if cover_path.resolve() == dest_cover.resolve():
                print(f"Cover already in place: {dest_cover}")
            else:
                shutil.copy2(str(cover_path), str(dest_cover))
                print(f"Cover copied: {dest_cover}")
        else:
            print(f"WARNING: Cover file not found: {cover_path}", file=sys.stderr)

    tid = args.tid or config["bilibili"]["tid"]
    tags = args.tags or ["有声书", args.novel, args.author, "有声读物"]

    publish_meta = {
        "novel": args.novel,
        "author": args.author,
        "tid": tid,
        "tags": tags,
        "brandName": "马不停嘴",
        "copyrightType": config["bilibili"]["copyright"],
        "episodes": {},
    }

    meta_path = drafts_dir / f"{args.novel}-publish-meta.json"
    if meta_path.exists():
        print(f"WARNING: publish-meta.json already exists: {meta_path}")
    else:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(publish_meta, f, ensure_ascii=False, indent=2)
        print(f"Publish meta created: {meta_path}")

    print(f"\nINIT_OK: {args.novel}")
    print(f"\n后续步骤：")
    print(f"  1. 运行 pipeline: pipeline.sh --novel \"{args.novel}\"")
    print(f"  2. 检查各集 final.mp4 效果")
    print(f"  3. 编辑 {meta_path.name} 填写每集标题和简介")
    print(f"  4. 发布: pipeline.sh --novel \"{args.novel}\" --publish")


if __name__ == "__main__":
    main()
