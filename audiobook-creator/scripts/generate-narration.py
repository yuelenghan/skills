#!/usr/bin/env python3
"""Generate narration from original novel text (audiobook style)."""

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Generate narration for an episode")
    parser.add_argument("episode_dir", help="Path to episode draft directory")
    args = parser.parse_args()

    config = load_config()
    ep_dir = Path(args.episode_dir).expanduser()

    outline_path = ep_dir / "outline.json"
    if not outline_path.exists():
        print(f"ERROR: outline.json not found in {ep_dir}", file=sys.stderr)
        sys.exit(1)

    with open(outline_path) as f:
        outline = json.load(f)

    novel_name = outline["novel"]
    episode = outline["episode"]
    title = outline["title"]
    raw_segments = outline["segments"]

    # Load full text
    drafts_dir = ep_dir.parent
    fulltext_path = drafts_dir / f"{novel_name}-fulltext.txt"
    if not fulltext_path.exists():
        print(f"ERROR: fulltext file not found: {fulltext_path}", file=sys.stderr)
        sys.exit(1)

    full_text = fulltext_path.read_text(encoding="utf-8")
    char_start, char_end = outline["charRange"]
    episode_text = full_text[char_start:char_end]

    # Normalize segments: if integer, generate auto segment list
    if isinstance(raw_segments, int):
        segments = [{"id": i + 1, "topic": f"段落{i + 1}"} for i in range(raw_segments)]
    else:
        segments = raw_segments

    print(f"Generating audiobook narration: {novel_name} EP{episode:02d} \"{title}\"")
    print(f"Segments: {len(segments)}, Source text: {len(episode_text)} chars")

    # Split episode text evenly across segments
    total_segments = len(segments)
    chunk_size = len(episode_text) // total_segments

    narration_parts = []
    current_start = 0
    for i, segment in enumerate(segments):
        seg_id = segment["id"]
        topic = segment["topic"]

        start_pos = current_start
        if i == total_segments - 1:
            end_pos = len(episode_text)
        else:
            # Find a natural break point (paragraph or sentence end)
            target_end = start_pos + chunk_size
            end_pos = target_end
            # Look for paragraph break within ±200 chars
            best_break = end_pos
            for offset in range(0, 200):
                if end_pos + offset < len(episode_text) and episode_text[end_pos + offset] == '\n':
                    best_break = end_pos + offset + 1
                    break
                if end_pos - offset > start_pos and episode_text[end_pos - offset] == '\n':
                    best_break = end_pos - offset + 1
                    break
            end_pos = best_break
        current_start = end_pos

        segment_text = episode_text[start_pos:end_pos].strip()

        # Clean up: remove excessive blank lines
        segment_text = re.sub(r'\n{3,}', '\n\n', segment_text)

        # Use segment topic as image description
        image_desc = f"{novel_name} 电影 {topic}"

        narration_parts.append(f"## 段落 {seg_id}\n\n[IMAGE: {image_desc}]\n\n{segment_text}")

        print(f"  Segment {seg_id}/{total_segments}: {topic} ({len(segment_text)} chars)")

    narration_md = "\n\n".join(narration_parts)

    narration_path = ep_dir / "narration.md"
    narration_path.write_text(narration_md, encoding="utf-8")

    print(f"\nNARRATION_OK: {narration_path}")
    print(f"Total: {len(narration_md)} chars, {total_segments} segments")


if __name__ == "__main__":
    main()
