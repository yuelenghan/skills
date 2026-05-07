#!/usr/bin/env python3
"""Publish audiobook episodes to Bilibili using publish-meta.json."""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from ytai.bilibili import upload_video_sync, load_credential, load_published, mark_published
from ytai.notify import send_feishu_message

SKILL_DIR = Path(__file__).resolve().parent.parent
COOKIE_PATH = SKILL_DIR / "bilibili-cookies.json"
PUBLISH_INTERVAL = 1800


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Publish audiobook episodes to Bilibili")
    parser.add_argument("--novel", required=True, help="Novel name")
    parser.add_argument("--episode", type=int, help="Publish specific episode number only")
    parser.add_argument("--all", action="store_true", help="Publish all episodes with final.mp4")
    parser.add_argument("--max", type=int, default=3, help="Max episodes to publish in one run (default 3)")
    parser.add_argument("--dry-run", action="store_true", help="Print metadata without uploading")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["outputDir"]).expanduser()
    drafts_dir = output_dir / "drafts"
    published_path = output_dir / "published.txt"

    meta_path = drafts_dir / f"{args.novel}-publish-meta.json"
    if not meta_path.exists():
        print(f"ERROR: publish-meta.json not found: {meta_path}", file=sys.stderr)
        print(f"  Run init-novel.py first, then edit the file to add episode metadata.", file=sys.stderr)
        sys.exit(1)

    with open(meta_path, encoding="utf-8") as f:
        publish_meta = json.load(f)

    episodes = publish_meta.get("episodes", {})
    if not episodes:
        print("ERROR: No episodes defined in publish-meta.json", file=sys.stderr)
        sys.exit(1)

    if args.episode:
        ep_key = f"EP{args.episode:02d}"
        if ep_key not in episodes:
            print(f"ERROR: {ep_key} not found in publish-meta.json", file=sys.stderr)
            sys.exit(1)
        to_publish = [(ep_key, episodes[ep_key])]
    elif args.all:
        to_publish = list(episodes.items())
    else:
        print("ERROR: Specify --episode N or --all", file=sys.stderr)
        sys.exit(1)

    already_published = load_published(str(published_path))

    # Filter to only publishable episodes (have final.mp4 and not already published)
    publishable = []
    for ep_key, ep_meta in to_publish:
        ep_dir = drafts_dir / f"{args.novel}-{ep_key}"
        mp4_path = ep_dir / "final.mp4"
        if not mp4_path.exists():
            continue
        if str(ep_dir) in already_published:
            continue
        publishable.append((ep_key, ep_meta))
    to_publish = publishable

    # Limit batch size
    if len(to_publish) > args.max:
        print(f"Limiting to {args.max} episodes (of {len(to_publish)} publishable). Use --max to adjust.")
        to_publish = to_publish[:args.max]

    if not args.dry_run:
        credential = load_credential(str(COOKIE_PATH))
        if not credential:
            print("ERROR: Failed to load Bilibili credential", file=sys.stderr)
            sys.exit(1)

    copyright_type = publish_meta.get("copyrightType", 1)
    tid = publish_meta.get("tid", 228)
    tags = publish_meta.get("tags", ["有声书"])
    brand = publish_meta.get("brandName", "马不停嘴")
    is_original = copyright_type == 1

    published = []
    for i, (ep_key, ep_meta) in enumerate(to_publish):
        ep_dir = drafts_dir / f"{args.novel}-{ep_key}"
        mp4_path = ep_dir / "final.mp4"

        meta = {
            "title": ep_meta["title"],
            "description": ep_meta["description"],
            "tags": ep_meta.get("tags", tags),
            "tid": ep_meta.get("tid", tid),
            "brandName": brand,
        }

        size_mb = mp4_path.stat().st_size / (1024 * 1024)
        print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}{ep_key}:")
        print(f"  Title: {meta['title']}")
        print(f"  TID: {meta['tid']}, Tags: {meta['tags']}")
        print(f"  Video: {size_mb:.0f} MB")
        print(f"  Copyright: {'自制' if is_original else '转载'}")

        if args.dry_run:
            continue

        try:
            result = upload_video_sync(
                str(mp4_path), meta, credential,
                copyright_type=copyright_type,
            )
        except Exception as e:
            print(f"ERROR: Upload exception for {ep_key}: {e}", file=sys.stderr)
            sys.exit(1)

        if result == "cookie_expired":
            msg = f"[有声书] Cookie 过期，发布中断于 {ep_key}。请刷新 bilibili-cookies.json"
            print(f"ERROR: {msg}", file=sys.stderr)
            send_feishu_message(msg)
            sys.exit(1)
        elif result == "rate_limited":
            print(f"  Rate limited, waiting 5 minutes...")
            time.sleep(300)
            try:
                result = upload_video_sync(
                    str(mp4_path), meta, credential,
                    copyright_type=copyright_type,
                )
            except Exception as e:
                print(f"ERROR: Retry exception for {ep_key}: {e}", file=sys.stderr)
                sys.exit(1)
            if result in ("cookie_expired", "rate_limited", None):
                msg = f"[有声书] 发布重试失败 {ep_key}: {result}"
                print(f"ERROR: {msg}", file=sys.stderr)
                send_feishu_message(msg)
                sys.exit(1)

        if result is None:
            print(f"ERROR: Upload failed for {ep_key}", file=sys.stderr)
            sys.exit(1)

        bvid = result.get("bvid", "unknown")
        print(f"  PUBLISH_OK: {bvid}")
        published.append((ep_key, bvid))

        mark_published(str(ep_dir), str(published_path))

        # Archive to published/
        archive_dir = output_dir / "published"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_dest = archive_dir / ep_dir.name
        if archive_dest.exists():
            print(f"  WARNING: Archive destination exists, overwriting: {archive_dest}")
            shutil.rmtree(archive_dest)
        shutil.move(str(ep_dir), str(archive_dest))
        print(f"  Archived: {archive_dest}")

        if i < len(to_publish) - 1:
            print(f"  Waiting {PUBLISH_INTERVAL}s before next upload...")
            time.sleep(PUBLISH_INTERVAL)

    if published:
        print(f"\n=== Published {len(published)} episodes ===")
        for ep_key, bvid in published:
            print(f"  {ep_key}: https://www.bilibili.com/video/{bvid}")
    elif not args.dry_run:
        print("\nNo episodes published.")


if __name__ == "__main__":
    main()
