#!/usr/bin/env python3
"""Extract cover and text content from an epub file (Apple Books integration).

Supports both zipped epub files and unzipped epub directories (macOS Apple Books
stores epubs as directories).
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

IBOOKS_DIR = Path.home() / "Library/Mobile Documents/iCloud~com~apple~iBooks/Documents"

EXCLUDE_PATTERNS = [
    r'(?i)^(序言|前言|引言|致谢|后记|译者[注序]|版权|出版|目录|contents|preface|acknowledgment)',
    r'(?i)^(copyright|dedication|about the author|附录|参考文献|注释$)',
    r'^.{0,5}(出版社|publishing|press)\s*$',
]

# Content patterns indicating a non-narrative page (checked against full text)
SKIP_CONTENT_PATTERNS = [
    r'(?i)copyright\s*©',
    r'(?i)all rights? reserved',
    r'(?i)ISBN[\s:：]',
]


class EpubReader:
    """Unified reader for both zipped and directory-based epub files."""

    def __init__(self, epub_path):
        self.path = Path(epub_path)
        self.is_dir = self.path.is_dir()
        self._zf = None

    def __enter__(self):
        if not self.is_dir:
            self._zf = zipfile.ZipFile(self.path)
        return self

    def __exit__(self, *args):
        if self._zf:
            self._zf.close()

    def namelist(self):
        if self.is_dir:
            return [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]
        return self._zf.namelist()

    def read(self, name):
        if self.is_dir:
            return (self.path / name).read_bytes()
        return self._zf.read(name)

    def file_size(self, name):
        if self.is_dir:
            return (self.path / name).stat().st_size
        return self._zf.getinfo(name).file_size


def find_epub(query):
    """Find epub in Apple Books by fuzzy name match."""
    if not IBOOKS_DIR.exists():
        return None
    candidates = []
    for f in IBOOKS_DIR.glob("*.epub"):
        if query in f.stem:
            candidates.append(f)
    if not candidates:
        for f in IBOOKS_DIR.glob("*.epub"):
            if all(ch in f.stem for ch in query):
                candidates.append(f)
    if candidates:
        candidates.sort(key=lambda f: len(f.stem))
        return candidates[0]
    return None


def extract_cover(reader, output_path):
    """Extract cover image from epub."""
    cover_patterns = ['cover', 'Cover', 'COVER']
    image_exts = ['.jpg', '.jpeg', '.png', '.webp']

    opf_path = None
    for name in reader.namelist():
        if name.endswith('.opf'):
            opf_path = name
            break

    if opf_path:
        opf_content = reader.read(opf_path).decode('utf-8')
        cover_id = None
        for match in re.finditer(r'name="cover"\s+content="([^"]+)"', opf_content):
            cover_id = match.group(1)
        if cover_id:
            for match in re.finditer(rf'id="{re.escape(cover_id)}"[^>]*href="([^"]+)"', opf_content):
                href = match.group(1)
                opf_dir = str(Path(opf_path).parent)
                full_path = f"{opf_dir}/{href}" if opf_dir != '.' else href
                for name in reader.namelist():
                    if name.endswith(href) or name == full_path:
                        data = reader.read(name)
                        Path(output_path).write_bytes(data)
                        return True

    # Fallback: find by filename pattern
    for name in reader.namelist():
        name_lower = name.lower()
        if any(p.lower() in name_lower for p in cover_patterns):
            if any(name_lower.endswith(ext) for ext in image_exts):
                data = reader.read(name)
                if len(data) > 5000:
                    Path(output_path).write_bytes(data)
                    return True

    # Fallback: first large image file
    for name in reader.namelist():
        if any(name.lower().endswith(ext) for ext in image_exts):
            if reader.file_size(name) > 10000:
                data = reader.read(name)
                Path(output_path).write_bytes(data)
                return True

    return False


def _strip_html(html_content):
    """Strip HTML tags, keeping text content."""
    text = re.sub(r'<head[^>]*>.*?</head>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<p[^>]*>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<div[^>]*>', '\n', text)
    text = re.sub(r'</div>', '\n', text)
    text = re.sub(r'<h[1-6][^>]*>', '\n', text)
    text = re.sub(r'</h[1-6]>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _should_exclude_chapter(title):
    """Check if a chapter title indicates non-narrative content."""
    for pattern in EXCLUDE_PATTERNS:
        if re.match(pattern, title.strip()):
            return True
    return False


def extract_text(reader):
    """Extract main text content from epub, excluding non-narrative parts."""
    opf_path = None
    for name in reader.namelist():
        if name.endswith('.opf'):
            opf_path = name
            break

    if not opf_path:
        return None

    opf_content = reader.read(opf_path).decode('utf-8')
    opf_dir = str(Path(opf_path).parent)

    # Parse spine order from OPF
    opf_clean = re.sub(r'\sxmlns="[^"]*"', '', opf_content, count=1)
    try:
        root = ET.fromstring(opf_clean)
    except ET.ParseError:
        root = None

    id_to_href = {}
    if root is not None:
        for item in root.iter():
            if item.tag.endswith('item') or item.tag == 'item':
                item_id = item.get('id', '')
                href = item.get('href', '')
                media = item.get('media-type', '')
                if 'html' in media or 'xml' in media:
                    id_to_href[item_id] = href

    spine_ids = []
    if root is not None:
        for itemref in root.iter():
            if itemref.tag.endswith('itemref') or itemref.tag == 'itemref':
                idref = itemref.get('idref', '')
                if idref in id_to_href:
                    spine_ids.append(idref)

    all_text_parts = []
    skipped = []

    content_files = [id_to_href[sid] for sid in spine_ids] if spine_ids else []
    if not content_files:
        content_files = sorted(
            [n for n in reader.namelist() if n.endswith(('.xhtml', '.html', '.htm'))
             and 'toc' not in n.lower() and 'nav' not in n.lower()]
        )

    # Skip titlepage/cover page files
    skip_files = {'titlepage', 'cover', 'copyright'}

    for href in content_files:
        basename_lower = Path(href).stem.lower()
        if any(s in basename_lower for s in skip_files):
            continue
        if opf_dir and opf_dir != '.':
            full_path = f"{opf_dir}/{href}"
        else:
            full_path = href

        actual_path = None
        for name in reader.namelist():
            if name == full_path or name.endswith(href):
                actual_path = name
                break
        if not actual_path:
            continue

        html = reader.read(actual_path).decode('utf-8', errors='replace')
        text = _strip_html(html)

        if not text or len(text.strip()) < 50:
            continue

        # Skip short pages that are likely title/copyright pages
        stripped = text.strip()
        if len(stripped) < 3000:
            if any(re.search(p, stripped) for p in SKIP_CONTENT_PATTERNS):
                skipped.append(stripped.split('\n')[0].strip()[:30])
                continue

        first_line = stripped.split('\n')[0].strip()
        if _should_exclude_chapter(first_line):
            skipped.append(first_line[:30])
            continue

        all_text_parts.append(text)

    if skipped:
        print(f"  Excluded {len(skipped)} non-narrative sections: {skipped[:5]}")

    return '\n\n'.join(all_text_parts)


# Common chapter heading patterns for Chinese/English books
_CHAPTER_RE = re.compile(
    r'^(第[一二三四五六七八九十百千\d]+[章节篇回卷部]'
    r'|chapter\s+\d+'
    r'|part\s+(one|two|three|four|five|\d+)'
    r'|PART\s+(ONE|TWO|THREE|FOUR|FIVE|\d+))',
    re.IGNORECASE | re.MULTILINE,
)


def _trim_to_first_chapter(text):
    """Trim text to start from the first chapter heading, skipping front matter."""
    m = _CHAPTER_RE.search(text)
    if m and m.start() > 0:
        if m.start() < 10000:
            trimmed = text[m.start():]
            return trimmed
    return text


def main():
    parser = argparse.ArgumentParser(description="Extract epub from Apple Books")
    parser.add_argument("query", help="Book name to search for")
    parser.add_argument("--output-dir", help="Output directory for txt and cover")
    parser.add_argument("--epub", help="Direct path to epub file (skip search)")
    args = parser.parse_args()

    if args.epub:
        epub_path = Path(args.epub).expanduser()
    else:
        epub_path = find_epub(args.query)

    if not epub_path or not epub_path.exists():
        print(f"ERROR: epub not found for '{args.query}'", file=sys.stderr)
        if IBOOKS_DIR.exists():
            available = [f.stem for f in IBOOKS_DIR.glob("*.epub") if args.query[:2] in f.stem]
            if available:
                print(f"  Similar: {available[:5]}", file=sys.stderr)
        sys.exit(1)

    print(f"Found epub: {epub_path.name}")

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else epub_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    novel_name = args.query
    txt_path = output_dir / f"{novel_name}.txt"
    cover_path = output_dir / f"{novel_name}-cover.jpg"

    with EpubReader(epub_path) as reader:
        if extract_cover(reader, cover_path):
            size_kb = cover_path.stat().st_size / 1024
            print(f"  Cover extracted: {cover_path} ({size_kb:.0f} KB)")
        else:
            print(f"  WARNING: Could not extract cover", file=sys.stderr)

        text = extract_text(reader)

    if not text:
        print("ERROR: Could not extract text from epub", file=sys.stderr)
        sys.exit(1)

    # Trim to first chapter heading (skip front matter like author bio)
    text = _trim_to_first_chapter(text)

    txt_path.write_text(text, encoding="utf-8")
    char_count = len(text)
    est_minutes = char_count / 280
    print(f"  Text extracted: {txt_path} ({char_count} chars, ~{est_minutes:.0f} min)")
    print(f"\nEXTRACT_OK: {novel_name}")


if __name__ == "__main__":
    main()
