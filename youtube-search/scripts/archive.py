#!/usr/bin/env python3
"""Archive successfully published videos from 待发布/ to 已发布/."""

import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    config_path = SKILL_DIR / "config.json"
    if not config_path.exists():
        config_path = SKILL_DIR / "config.example.json"
    with open(config_path) as f:
        return json.load(f)


def main():
    config = load_config()
    output_dir = Path(config.get("outputDir", "~/Videos/youtube-search")).expanduser()
    pending = output_dir / "待发布"
    archive = output_dir / "已发布"
    published_path = SKILL_DIR / "published.txt"

    if not published_path.exists():
        print("No published.txt found, nothing to archive.")
        return

    if not pending.is_dir():
        print(f"WARNING: {pending} does not exist")
        return

    published_lines = [line.strip() for line in published_path.read_text().splitlines() if line.strip()]
    published_full = set(published_lines)
    published_basenames = set(Path(p).name for p in published_lines)

    archive.mkdir(parents=True, exist_ok=True)
    moved = 0

    for d in sorted(pending.iterdir()):
        if not d.is_dir():
            continue
        if str(d) in published_full or d.name in published_basenames:
            dest = archive / d.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(d), str(dest))
            print(f"ARCHIVED: {d.name}")
            moved += 1
        else:
            print(f"KEPT: {d.name} (not in published.txt)")

    print(f"\nDone: {moved} archived")


if __name__ == "__main__":
    main()
