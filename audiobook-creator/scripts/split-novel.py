#!/usr/bin/env python3
"""Split a novel into episodes by chapters, merging short ones."""

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

BASE_CHAPTER_PATTERN = re.compile(
    r'^(第.{1,5}[章回]|尾声|序[章幕]?|楔子|番外|后记|终章)',
    re.MULTILINE
)

MIN_EPISODE_MINUTES = 40
MAX_EPISODE_MINUTES = 60


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def build_chapter_pattern(config):
    extra = config.get("extraChapterPatterns", [])
    if not extra:
        return BASE_CHAPTER_PATTERN
    combined = BASE_CHAPTER_PATTERN.pattern.rstrip(')') + '|' + '|'.join(extra) + ')'
    return re.compile(combined, re.MULTILINE)


def split_into_chapters(text, pattern):
    """Split text into chapters by detecting headings."""
    matches = list(pattern.finditer(text))
    if not matches:
        return None

    chapters = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group().strip()
        chapter_text = text[start:end]
        chapters.append((title, chapter_text))
    return chapters


def split_by_chars(text, max_chars):
    """Split text into chunks of approximately max_chars at paragraph boundaries."""
    chunks = []
    pos = 0
    while pos < len(text):
        if pos + max_chars >= len(text):
            chunks.append(("段落", text[pos:]))
            break
        end = pos + max_chars
        best = end
        for offset in range(0, min(500, end - pos)):
            if end + offset < len(text) and text[end + offset] == '\n':
                best = end + offset + 1
                break
            if end - offset > pos and text[end - offset] == '\n':
                best = end - offset + 1
                break
        chunks.append(("段落", text[pos:best]))
        pos = best
    return chunks


def merge_short_episodes(chapters, chars_per_minute):
    """Merge chapters into episodes targeting MIN-MAX minute range."""
    max_chars = int(MAX_EPISODE_MINUTES * chars_per_minute)
    episodes = []
    current_chapters = []
    current_chars = 0

    for title, text in chapters:
        ch_len = len(text)
        # If single chapter exceeds max, force-split it
        if ch_len > max_chars and not current_chapters:
            sub_chunks = split_by_chars(text, max_chars)
            for sub_title, sub_text in sub_chunks:
                episodes.append(([(f"{title}(续)" if sub_title == "段落" else title, sub_text)], len(sub_text)))
            continue
        elif ch_len > max_chars and current_chapters:
            episodes.append((list(current_chapters), current_chars))
            current_chapters = []
            current_chars = 0
            sub_chunks = split_by_chars(text, max_chars)
            for sub_title, sub_text in sub_chunks:
                episodes.append(([(f"{title}(续)" if sub_title == "段落" else title, sub_text)], len(sub_text)))
            continue

        current_chapters.append((title, text))
        current_chars += ch_len
        duration = current_chars / chars_per_minute
        if duration >= MIN_EPISODE_MINUTES:
            episodes.append((list(current_chapters), current_chars))
            current_chapters = []
            current_chars = 0

    if current_chapters:
        tail_duration = current_chars / chars_per_minute
        if episodes and tail_duration < 15:
            last_chs, last_chars = episodes[-1]
            last_chs.extend(current_chapters)
            episodes[-1] = (last_chs, last_chars + current_chars)
        else:
            episodes.append((current_chapters, current_chars))

    return episodes


def generate_episode_title(novel_name, ep_num, chapter_titles, chapter_texts):
    """Generate episode title from chapter titles (no AI dependency)."""
    return " + ".join(chapter_titles[:3])


def main():
    parser = argparse.ArgumentParser(description="Split novel into episodes")
    parser.add_argument("source", help="Path to novel text file")
    parser.add_argument("--novel-name", help="Novel name (default: filename without ext)")
    parser.add_argument("--genre", choices=["mystery", "romance", "historical", "electronic"],
                        default="mystery", help="Novel genre (determined by agent)")
    args = parser.parse_args()

    config = load_config()
    source_path = Path(args.source).expanduser()
    if not source_path.exists():
        print(f"ERROR: Source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    novel_name = args.novel_name or source_path.stem
    chars_per_minute = config["narration"]["charsPerMinute"]
    novel_text = source_path.read_text(encoding="utf-8")

    print(f"Novel: {novel_name}")
    print(f"Text length: {len(novel_text)} chars")
    print(f"Chars/min: {chars_per_minute}")

    chapter_pattern = build_chapter_pattern(config)
    chapters = split_into_chapters(novel_text, chapter_pattern)

    if chapters is None:
        max_chars = int(MAX_EPISODE_MINUTES * chars_per_minute)
        print(f"No chapter headings detected, splitting by {max_chars} chars")
        chapters = split_by_chars(novel_text, max_chars)

    print(f"Chapters detected: {len(chapters)}")
    for title, text in chapters:
        dur = len(text) / chars_per_minute
        print(f"  {title}: {len(text)} chars (~{dur:.1f} min)")

    episodes = merge_short_episodes(chapters, chars_per_minute)
    print(f"\nMerged into {len(episodes)} episodes (target {MIN_EPISODE_MINUTES}-{MAX_EPISODE_MINUTES} min):")

    output_dir = Path(config["outputDir"]).expanduser() / "drafts"
    output_dir.mkdir(parents=True, exist_ok=True)

    full_text_path = output_dir / f"{novel_name}-fulltext.txt"
    full_text_path.write_text(novel_text, encoding="utf-8")
    print(f"Full text saved: {len(novel_text)} chars -> {full_text_path}")

    char_offset = 0
    for i, (ep_chapters, ep_chars) in enumerate(episodes):
        ep_num = i + 1
        ep_dir = output_dir / f"{novel_name}-EP{ep_num:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        chapter_titles = [t for t, _ in ep_chapters]
        chapter_texts = [txt for _, txt in ep_chapters]
        duration = ep_chars / chars_per_minute

        title = generate_episode_title(novel_name, ep_num, chapter_titles, chapter_texts)

        char_start = char_offset
        char_end = char_offset + ep_chars
        char_offset = char_end

        segments_count = max(1, round(duration / 3))

        outline = {
            "novel": novel_name,
            "episode": ep_num,
            "totalEpisodes": len(episodes),
            "title": title,
            "chapters": chapter_titles,
            "charRange": [char_start, char_end],
            "segments": segments_count,
            "estimatedMinutes": round(duration, 1),
        }

        outline_path = ep_dir / "outline.json"
        with open(outline_path, "w", encoding="utf-8") as f:
            json.dump(outline, f, ensure_ascii=False, indent=2)

        ch_str = " + ".join(chapter_titles)
        print(f"  EP{ep_num:02d}: {title} [{ch_str}] (~{duration:.0f} min)")
        print(f"    SPLIT_OK: {ep_dir}")

    # Write genre to publish-meta.json
    genre = args.genre
    print(f"\nGenre: {genre}")

    meta_path = output_dir / f"{novel_name}-publish-meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({
        "novel": novel_name,
        "genre": genre,
        "totalEpisodes": len(episodes),
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Genre written to: {meta_path}")

    print(f"\nSplit into {len(episodes)} episodes")


if __name__ == "__main__":
    main()
