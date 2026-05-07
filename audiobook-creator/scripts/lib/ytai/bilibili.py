"""Bilibili upload with cookie auth, cover generation, and rate limiting."""

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from bilibili_api import video_uploader, Credential
from bilibili_api.exceptions import ResponseCodeException


COVER_FONT_PATHS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/Library/Fonts/AdobeFanHeitiStd-Bold.otf", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
]

BRAND_FONT_PATHS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
]

LINE_COLORS = [
    (255, 230, 0),
    (255, 120, 0),
    (255, 50, 30),
]


def _load_font(candidates, size):
    for path, idx in candidates:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def wrap_cjk_text(text, max_chars_per_line=13):
    """Split CJK text into 1-3 lines for cover overlay."""
    text = text.strip()
    if len(text) <= max_chars_per_line:
        return [text]

    n = len(text)
    break_chars = "，。！？、 :：；…"

    if n <= max_chars_per_line * 2:
        mid = n // 2
        for offset in range(min(4, mid)):
            for pos in [mid + offset, mid - offset]:
                if 0 < pos < n and text[pos] in break_chars:
                    return [text[:pos + 1].strip(), text[pos + 1:].strip()]
        return [text[:mid], text[mid:]]

    third = n // 3
    b1, b2 = third, third * 2
    for offset in range(min(4, third)):
        for pos in [b1 + offset, b1 - offset]:
            if 0 < pos < n and text[pos] in break_chars:
                b1 = pos + 1
                break
        else:
            continue
        break
    for offset in range(min(4, third)):
        for pos in [b2 + offset, b2 - offset]:
            if 0 < pos < n and text[pos] in break_chars:
                b2 = pos + 1
                break
        else:
            continue
        break
    return [text[:b1].strip(), text[b1:b2].strip(), text[b2:].strip()]


def render_cover_overlay(frame_path, title, output_path, brand_text="马不停嘴"):
    """Render cover with multi-color text and black stroke outline."""
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    short_edge = min(w, h)
    font_size = max(70, int(short_edge * 0.13))
    brand_font_size = max(20, int(short_edge * 0.026))
    font = _load_font(COVER_FONT_PATHS, font_size)
    brand_font = _load_font(BRAND_FONT_PATHS, brand_font_size)

    lines = wrap_cjk_text(title, max_chars_per_line=14)[:2]

    max_text_w = int(w * 0.88)
    widest = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widest = max(widest, bbox[2] - bbox[0])
    if widest > max_text_w:
        font_size = int(font_size * max_text_w / widest)
        font = _load_font(COVER_FONT_PATHS, font_size)

    line_spacing = int(font_size * 1.4)
    total_height = len(lines) * line_spacing
    outline_w = max(3, int(font_size * 0.06))

    start_y = h - total_height - int(h * 0.08)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (w - text_w) // 2
        y = start_y + i * line_spacing
        color = LINE_COLORS[i % len(LINE_COLORS)]
        draw.text(
            (x, y), line, font=font,
            fill=color,
            stroke_width=outline_w,
            stroke_fill=(0, 0, 0),
        )

    brand_bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    draw.text(
        (w - brand_w - 20, 15), brand_text, font=brand_font,
        fill=(255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )

    img.save(output_path, "JPEG", quality=95)


def score_frame(image_path):
    """Score a frame by brightness (35%), saturation (35%), and sharpness (30%)."""
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.float32)

    brightness = arr.mean() / 255.0

    hsv = np.array(img.convert("HSV"), dtype=np.float32)
    saturation = hsv[:, :, 1].mean() / 255.0

    gray = np.array(img.convert("L"), dtype=np.float32)
    gy = (gray[2:, 1:-1] + gray[:-2, 1:-1] + gray[1:-1, 2:] +
          gray[1:-1, :-2] - 4 * gray[1:-1, 1:-1])
    sharpness = min(gy.var() / 5000.0, 1.0)

    return 0.35 * brightness + 0.35 * saturation + 0.30 * sharpness


def select_best_cover_frame(mp4_path, duration, tmp_dir, threshold=0.35, step=10):
    """Sample frames every `step` seconds and return the best one."""
    candidates = [0] + list(range(step, int(duration), step))
    if len(candidates) > 15:
        candidates = candidates[:15]

    best_path = None
    best_score = -1

    for ts in candidates:
        frame_path = str(Path(tmp_dir) / f"candidate_{ts}.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(ts), "-i", str(mp4_path),
             "-vframes", "1", "-q:v", "2", frame_path],
            capture_output=True, timeout=15,
        )
        if not Path(frame_path).exists() or Path(frame_path).stat().st_size < 1000:
            continue

        try:
            score = score_frame(frame_path)
        except Exception:
            continue

        if score > best_score:
            best_score = score
            best_path = frame_path

        if best_score >= threshold:
            break

    return best_path, best_score


def load_credential(cookie_path):
    """Load Bilibili credential from cookie JSON file."""
    cookie_path = Path(cookie_path).expanduser()
    if not cookie_path.exists():
        return None
    try:
        with open(cookie_path) as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    cookie_dict = {}
    for c in cookies.get("cookie_info", {}).get("cookies", []):
        cookie_dict[c["name"]] = c["value"]

    if not cookie_dict.get("SESSDATA") or not cookie_dict.get("bili_jct"):
        return None

    return Credential(
        sessdata=cookie_dict.get("SESSDATA", ""),
        bili_jct=cookie_dict.get("bili_jct", ""),
        dedeuserid=cookie_dict.get("DedeUserID", ""),
        buvid3=cookie_dict.get("buvid3", ""),
    )


async def upload_video(mp4_path, meta, credential, source_url="YouTube",
                        copyright_type=1, source_mp4_for_cover=None):
    """Upload a single video to Bilibili with auto-generated cover.

    Returns: dict with bvid on success, "cookie_expired", "rate_limited", or None on failure.
    """
    mp4_path = Path(mp4_path)
    if not mp4_path.exists():
        return None

    title = meta.get("title", mp4_path.stem)[:80]
    desc = meta.get("description", "")
    tags = meta.get("tags", ["AI"])
    tid = int(meta.get("tid", 182))
    is_original = copyright_type == 1

    cover_tmp_dir = tempfile.mkdtemp()
    try:
        cover_path = Path(cover_tmp_dir) / "cover.jpg"

        cover_src = source_mp4_for_cover if source_mp4_for_cover else str(mp4_path)
        duration = float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(cover_src)],
            capture_output=True, text=True,
        ).stdout.strip() or "10")
        cover_raw, cover_score = select_best_cover_frame(
            str(cover_src), duration, cover_tmp_dir)
        if not cover_raw:
            cover_raw = str(Path(cover_tmp_dir) / "fallback.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(int(duration / 3)), "-i", str(cover_src),
                 "-vframes", "1", "-q:v", "2", cover_raw],
                capture_output=True, timeout=30,
            )
        brand = meta.get("brandName", "马不停嘴")
        render_cover_overlay(cover_raw, title, str(cover_path), brand_text=brand)

        vu_meta = video_uploader.VideoMeta(
            tid=tid,
            title=title,
            tags=tags,
            desc=desc,
            cover=str(cover_path),
            original=is_original,
            source=source_url if not is_original else None,
            recreate=is_original,
            no_reprint=is_original,
        )

        page = video_uploader.VideoUploaderPage(
            path=str(mp4_path),
            title=title,
        )

        uploader = video_uploader.VideoUploader(
            pages=[page],
            meta=vu_meta,
            credential=credential,
        )

        try:
            result = await uploader.start()
            return result
        except ResponseCodeException as e:
            if e.code in (-101, -401):
                return "cookie_expired"
            elif e.code == 137022:
                return "rate_limited"
            raise
    finally:
        shutil.rmtree(cover_tmp_dir, ignore_errors=True)


def upload_video_sync(mp4_path, meta, credential, **kwargs):
    """Synchronous wrapper for upload_video."""
    return asyncio.run(upload_video(mp4_path, meta, credential, **kwargs))


def load_published(published_path):
    """Load set of published video directory paths."""
    path = Path(published_path)
    if not path.exists():
        return set()
    return set(line.strip() for line in path.read_text().splitlines() if line.strip())


def mark_published(video_dir, published_path):
    """Append a video directory to the published tracking file."""
    with open(published_path, "a") as f:
        f.write(str(video_dir) + "\n")
