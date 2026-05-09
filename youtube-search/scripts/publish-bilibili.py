#!/usr/bin/env python3
"""Upload composed videos to Bilibili (subtitles already burned into video)."""

import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bilibili_api import video_uploader, Credential
from bilibili_api.exceptions import ResponseCodeException

SKILL_DIR = Path(__file__).resolve().parent.parent
PUBLISHED_PATH = SKILL_DIR / "published.txt"
QUOTA_COUNT_PATH = SKILL_DIR / "quota-today.txt"
USED_SOURCES_PATH = SKILL_DIR / "used-sources.txt"


def load_config():
    config_path = SKILL_DIR / "config.json"
    if not config_path.exists():
        config_path = SKILL_DIR / "config.example.json"
    with open(config_path) as f:
        return json.load(f)


COVER_FONT_PATHS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/Library/Fonts/AdobeFanHeitiStd-Bold.otf", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
]

BRAND_FONT_PATHS = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
]


def _load_font(candidates, size):
    for path, idx in candidates:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def wrap_cjk_text(text, max_chars_per_line=13):
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


LINE_COLORS = [
    (255, 230, 0),
    (255, 120, 0),
    (255, 50, 30),
]


def render_cover_overlay(frame_path, title, output_path, brand_text=""):
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    short_edge = min(w, h)
    font_size = max(70, int(short_edge * 0.13))
    font = _load_font(COVER_FONT_PATHS, font_size)

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

    if brand_text:
        brand_font_size = max(20, int(short_edge * 0.026))
        brand_font = _load_font(BRAND_FONT_PATHS, brand_font_size)
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
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.float32)

    brightness = arr.mean() / 255.0

    hsv = np.array(img.convert("HSV"), dtype=np.float32)
    saturation = hsv[:, :, 1].mean() / 255.0

    gray = np.array(img.convert("L"), dtype=np.float32)
    gy = gray[2:, 1:-1] + gray[:-2, 1:-1] + gray[1:-1, 2:] + gray[1:-1, :-2] - 4 * gray[1:-1, 1:-1]
    sharpness = min(gy.var() / 5000.0, 1.0)

    return 0.35 * brightness + 0.35 * saturation + 0.30 * sharpness


def select_best_cover_frame(mp4_path, duration, tmp_dir, threshold=0.35, step=10):
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


def load_credential(config):
    bili = config.get("bilibili", {})
    cookie_path_raw = bili.get("cookiePath", "")
    if not cookie_path_raw:
        cookie_path = SKILL_DIR / "bilibili-cookies.json"
    else:
        cookie_path = Path(cookie_path_raw).expanduser()
    if not cookie_path.exists():
        print(f"PUBLISH_ERROR: cookie file not found: {cookie_path}", file=sys.stderr)
        print("HINT: run  python3 scripts/login-bilibili.py  to extract from browser", file=sys.stderr)
        return None
    try:
        with open(cookie_path) as f:
            cookies = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"PUBLISH_ERROR: invalid cookie file: {e}", file=sys.stderr)
        return None

    cookie_dict = {}
    for c in cookies.get("cookie_info", {}).get("cookies", []):
        cookie_dict[c["name"]] = c["value"]

    if not cookie_dict.get("SESSDATA") or not cookie_dict.get("bili_jct"):
        print("PUBLISH_ERROR: cookie file missing SESSDATA or bili_jct", file=sys.stderr)
        return None

    return Credential(
        sessdata=cookie_dict.get("SESSDATA", ""),
        bili_jct=cookie_dict.get("bili_jct", ""),
        dedeuserid=cookie_dict.get("DedeUserID", ""),
        buvid3=cookie_dict.get("buvid3", ""),
    )


def load_published():
    if not PUBLISHED_PATH.exists():
        return set()
    return set(line.strip() for line in PUBLISHED_PATH.read_text().splitlines() if line.strip())


def mark_published(video_dir):
    with open(PUBLISHED_PATH, "a") as f:
        f.write(str(video_dir) + "\n")


def archive_published(video_dir):
    vdir = Path(video_dir)
    if vdir.parent.name != "待发布":
        return
    archive_dir = vdir.parent.parent / "已发布"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / vdir.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(vdir), str(dest))


def mark_source_used(video_dir):
    source_path = Path(video_dir) / "source.json"
    if not source_path.exists():
        return
    with open(source_path) as f:
        source = json.load(f)
    video_id = source.get("videoId", "")
    video_dir_str = source.get("videoDir", "")
    existing = set()
    if USED_SOURCES_PATH.exists():
        existing = set(line.strip() for line in USED_SOURCES_PATH.read_text().splitlines() if line.strip())
    if video_id:
        entry = f"youtube {video_id}"
        if entry not in existing:
            with open(USED_SOURCES_PATH, "a") as f:
                f.write(entry + "\n")
    elif video_dir_str and video_dir_str not in existing:
        with open(USED_SOURCES_PATH, "a") as f:
            f.write(video_dir_str + "\n")


async def publish_video(video_dir, config, credential):
    vdir = Path(video_dir)
    mp4 = vdir / "video.mp4"
    meta_path = vdir / "meta.json"

    if not mp4.exists() or not meta_path.exists():
        return "skip"

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        print(f"META_JSON_ERROR: {meta_path}: {e}", file=sys.stderr)
        return None

    bili = config.get("bilibili", {})
    title = meta.get("title", vdir.name)[:80]
    desc = meta.get("description", "")
    tags = meta.get("tags", ["AI"])
    tid = int(meta.get("tid", bili.get("defaultTid", 182)))
    is_original = meta.get("copyright", bili.get("copyright", 2)) == 1
    source_url = bili.get("source", "YouTube")
    brand_text = bili.get("brandText", "")

    cover_tmp_dir = tempfile.mkdtemp()
    try:
        cover_path = Path(cover_tmp_dir) / "cover.jpg"

        source_mp4 = mp4
        source_path = vdir / "source.json"
        if source_path.exists():
            try:
                with open(source_path) as f:
                    src = json.load(f)
                orig = Path(src.get("mp4", ""))
                if orig.exists():
                    source_mp4 = orig
            except (json.JSONDecodeError, OSError):
                pass

        duration = float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(source_mp4)],
            capture_output=True, text=True,
        ).stdout.strip() or "10")

        cover_raw, cover_score = select_best_cover_frame(str(source_mp4), duration, cover_tmp_dir)
        if not cover_raw:
            cover_raw = str(Path(cover_tmp_dir) / "fallback.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(int(duration / 3)), "-i", str(source_mp4),
                 "-vframes", "1", "-q:v", "2", cover_raw],
                capture_output=True, timeout=30,
            )
        print(f"COVER: score={cover_score:.2f}, file={Path(cover_raw).name}")
        render_cover_overlay(cover_raw, title, str(cover_path), brand_text)

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
            path=str(mp4),
            title=title,
        )

        uploader = video_uploader.VideoUploader(
            pages=[page],
            meta=vu_meta,
            credential=credential,
        )

        try:
            result = await uploader.start()
            bvid = result.get("bvid", "")
            print(f"BVID: {bvid}")
            mark_published(vdir)
            mark_source_used(vdir)
            archive_published(vdir)
            return result
        except ResponseCodeException as e:
            if e.code in (-101, -401):
                print(f"COOKIE_EXPIRED: {e}", file=sys.stderr)
                return "cookie_expired"
            elif e.code == 137022:
                print(f"RATE_LIMITED: {e}", file=sys.stderr)
                return "rate_limited"
            else:
                print(f"BILIAPI_ERROR: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"BILIAPI_ERROR: {e}", file=sys.stderr)
            return None
    finally:
        shutil.rmtree(cover_tmp_dir, ignore_errors=True)


def count_today_published():
    today = date.today().isoformat()
    if not QUOTA_COUNT_PATH.exists():
        return 0
    content = QUOTA_COUNT_PATH.read_text().strip()
    if not content:
        return 0
    parts = content.split(":", 1)
    if len(parts) == 2 and parts[0] == today:
        return int(parts[1])
    return 0


def increment_today_quota():
    today = date.today().isoformat()
    current = count_today_published()
    QUOTA_COUNT_PATH.write_text(f"{today}:{current + 1}")


def collect_unpublished(output_dir):
    ready_dir = Path(output_dir).expanduser() / "待发布"
    published = load_published()
    dirs = []
    if ready_dir.is_dir():
        for vdir in sorted(ready_dir.iterdir()):
            if not vdir.is_dir():
                continue
            if (vdir / "video.mp4").exists() and (vdir / "meta.json").exists():
                if str(vdir) not in published:
                    dirs.append(str(vdir))
    return dirs


async def main():
    interval = None
    no_quota = False
    args = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--auto":
            args = None
            i += 1
        elif sys.argv[i] == "--no-quota":
            no_quota = True
            i += 1
        else:
            args.append(sys.argv[i])
            i += 1

    config = load_config()
    bili = config.get("bilibili", {})
    max_daily = bili.get("maxDailyPublish", 10)
    if interval is None:
        interval = bili.get("uploadInterval", 1800)

    if args is None:
        args = collect_unpublished(config.get("outputDir", "~/Videos/youtube-search"))
        if not args:
            print("No unpublished videos found in 待发布/")
            print("\nDone: 0 published, 0 failed (status=ok)")
            return

    if not args:
        print(f"Usage: {sys.argv[0]} [--auto] [--no-quota] [--interval S] [video_dir ...]", file=sys.stderr)
        sys.exit(1)

    credential = load_credential(config)
    if not credential:
        sys.exit(1)

    today_count = count_today_published()
    if no_quota:
        remaining_quota = len(args)
        print(f"Daily quota: BYPASSED (--no-quota), today published {today_count}")
    else:
        remaining_quota = max(0, max_daily - today_count)
        print(f"Daily quota: {today_count}/{max_daily} used, {remaining_quota} remaining")

    if remaining_quota <= 0:
        print(f"QUOTA_REACHED: already published {today_count} today (limit {max_daily}). Try again tomorrow.")
        print(f"\nDone: 0 published, 0 failed (status=quota_reached)")
        return

    ok_count = 0
    fail_count = 0
    rate_limited = False

    published = load_published()
    for idx, video_dir in enumerate(args):
        if str(Path(video_dir)) in published:
            print(f"PUBLISH_SKIP: {video_dir}")
            continue

        if ok_count >= remaining_quota:
            print(f"\nQUOTA_REACHED: {ok_count} uploaded, daily limit {max_daily} reached.")
            print(f"Remaining: {len(args) - idx} videos. Will continue tomorrow.")
            break

        result = await publish_video(video_dir, config, credential)
        if result == "cookie_expired":
            print(f"COOKIE_EXPIRED: stopping all uploads")
            print(f"PUBLISH_FAILED: {video_dir}")
            fail_count += 1
            break
        elif result == "rate_limited":
            print(f"RATE_LIMITED: B站限流，停止本批上传。已成功 {ok_count} 个。")
            print(f"Remaining: {len(args) - idx} videos. Wait a few hours then re-run.")
            rate_limited = True
            break
        elif result is None:
            print(f"PUBLISH_FAILED: {video_dir}")
            fail_count += 1
        elif result == "skip":
            print(f"PUBLISH_SKIP: {video_dir}")
        else:
            print(f"PUBLISH_OK: {video_dir}")
            ok_count += 1
            published.add(str(Path(video_dir)))
            if not no_quota:
                increment_today_quota()

        if result in ("skip", "cookie_expired", "rate_limited"):
            continue
        if idx < len(args) - 1 and ok_count < remaining_quota:
            print(f"Rate limit: waiting {interval}s before next upload...")
            await asyncio.sleep(interval)

    status = "rate_limited" if rate_limited else "ok"
    total_today = today_count + ok_count
    print(f"\nDone: {ok_count} published, {fail_count} failed (today total: {total_today}/{max_daily}, status={status})")


if __name__ == "__main__":
    asyncio.run(main())
