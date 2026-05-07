#!/usr/bin/env python3
"""Fetch illustrations from Bing Image Search for each narration segment."""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def extract_image_descriptions(narration_md):
    """Extract [IMAGE: ...] descriptions from narration.md, keyed by segment number."""
    descriptions = {}
    current_segment = 0
    for line in narration_md.split("\n"):
        m = re.match(r'^## 段落 (\d+)', line)
        if m:
            current_segment = int(m.group(1))
        img_match = re.search(r'\[IMAGE:\s*(.+?)\]', line)
        if img_match and current_segment > 0:
            if current_segment not in descriptions:
                descriptions[current_segment] = img_match.group(1).strip()
    return descriptions


def search_bing_images(query, count=5):
    """Search Bing Images and return a list of image URLs."""
    import html as html_mod

    encoded_q = urllib.parse.quote(query)
    url = f"https://www.bing.com/images/search?q={encoded_q}&form=HDRSC2&first=1"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    Search failed: {e}")
        return []

    # Bing stores image metadata in class="iusc" elements' m attribute (HTML-escaped JSON)
    m_values = re.findall(r'class="iusc"[^>]*m="([^"]+)"', page)

    urls = []
    for m_escaped in m_values:
        decoded = html_mod.unescape(m_escaped)
        murl_match = re.search(r'"murl":"(https?://[^"]+)"', decoded)
        if murl_match:
            img_url = murl_match.group(1)
            u_lower = img_url.lower()
            if any(ext in u_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if 'icon' not in u_lower and 'logo' not in u_lower:
                    urls.append(img_url)
        if len(urls) >= count:
            break

    return urls


def download_image(url, output_path, min_bytes=20000):
    """Download image from URL to local file. Skip images smaller than min_bytes."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < min_bytes:
            return 0
        with open(output_path, "wb") as f:
            f.write(data)
        return len(data)
    except Exception:
        return 0


def build_query(novel_name, scene_desc):
    """Build search query from novel name and scene description."""
    # Extract key nouns from scene description (remove common verbs/particles)
    keywords = scene_desc
    # Keep it short for better search results
    if len(keywords) > 20:
        keywords = keywords[:20]
    return f"{novel_name} 电影 {keywords}"


def main():
    parser = argparse.ArgumentParser(description="Fetch illustrations from Bing Images")
    parser.add_argument("episode_dir", help="Path to episode draft directory")
    args = parser.parse_args()

    config = load_config()
    ep_dir = Path(args.episode_dir).expanduser()

    narration_path = ep_dir / "narration.md"
    if not narration_path.exists():
        print(f"ERROR: narration.md not found in {ep_dir}", file=sys.stderr)
        sys.exit(1)

    # Get novel name from outline
    outline_path = ep_dir / "outline.json"
    novel_name = ""
    if outline_path.exists():
        with open(outline_path) as f:
            outline = json.load(f)
        novel_name = outline.get("novel", "")

    narration_md = narration_path.read_text(encoding="utf-8")
    descriptions = extract_image_descriptions(narration_md)

    if not descriptions:
        print("ERROR: No [IMAGE: ...] tags found in narration.md", file=sys.stderr)
        sys.exit(1)

    num_segments = len(descriptions)
    images_dir = ep_dir / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"Fetching {num_segments} illustrations from Bing Images...")

    image_seq = []
    for seg_num in sorted(descriptions.keys()):
        filename = f"{seg_num:03d}.jpg"
        output_path = images_dir / filename

        if output_path.exists() and output_path.stat().st_size > 20000:
            print(f"  [{seg_num}/{num_segments}] Already exists, skipping")
            image_seq.append({
                "segment": seg_num,
                "file": filename,
                "keywords": descriptions[seg_num],
            })
            continue

        scene_desc = descriptions[seg_num]
        query = build_query(novel_name, scene_desc)

        print(f"  [{seg_num}/{num_segments}] Searching: {query}")

        success = False
        for retry in range(3):
            urls = search_bing_images(query, count=15)
            if not urls:
                # Fallback: try English query
                eng_query = f"Death on the Nile movie {scene_desc[:15]}"
                urls = search_bing_images(eng_query)

            for img_url in urls:
                size_bytes = download_image(img_url, output_path)
                if size_bytes > 5000:
                    print(f"    OK: {filename} ({size_bytes // 1024}KB)")
                    success = True
                    break

            if success:
                break
            print(f"    Retry {retry+1}/3...")
            time.sleep(3 * (retry + 1))

        if not success:
            print(f"  WARNING: Failed to fetch segment {seg_num}, using placeholder")
            _create_placeholder(output_path)
            filename = f"{seg_num:03d}.jpg"

        image_seq.append({
            "segment": seg_num,
            "file": filename,
            "keywords": scene_desc,
        })

        if seg_num < max(descriptions.keys()):
            time.sleep(2)

    seq_path = ep_dir / "image-seq.json"
    with open(seq_path, "w", encoding="utf-8") as f:
        json.dump(image_seq, f, ensure_ascii=False, indent=2)

    print(f"\nILLUST_OK: {len(image_seq)} illustrations fetched → {seq_path}")


def _create_placeholder(output_path):
    """Create a simple white placeholder image."""
    try:
        from PIL import Image
        img = Image.new("RGB", (1024, 1024), (255, 255, 255))
        img.save(str(output_path))
    except ImportError:
        import struct
        import zlib

        def create_minimal_png():
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = b'\x00\xff\xff\xff'
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + idat_data) & 0xffffffff
            idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            return sig + ihdr + idat + iend
        with open(output_path, 'wb') as f:
            f.write(create_minimal_png())


if __name__ == "__main__":
    main()
