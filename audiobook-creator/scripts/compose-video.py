#!/usr/bin/env python3
"""Compose audiobook video: single cover image + narration audio + subtitles."""

import argparse
import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from ytai.subtitle import generate_ass
from ytai.tts import get_audio_duration

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def escape_filter_path(path):
    """Escape path for ffmpeg filter (subtitles/drawtext)."""
    s = str(path).replace("\\", "/")
    for ch in ":'[] ":
        s = s.replace(ch, f"\\{ch}")
    return s


def create_composite_frame(cover_path, width, height, out_path):
    """Create blurred background + sharp cover centered, reserving bottom for subtitles."""
    cover = Image.open(cover_path).convert("RGB")

    bg = cover.copy().resize((width, height), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
    bg = ImageEnhance.Brightness(bg).enhance(0.6)

    max_h = height - 150
    cw, ch = cover.size
    scale = min(width / cw, max_h / ch)
    new_w, new_h = int(cw * scale), int(ch * scale)
    fg = cover.resize((new_w, new_h), Image.LANCZOS)

    x = (width - new_w) // 2
    y = (max_h - new_h) // 2
    bg.paste(fg, (x, y))

    bg.save(str(out_path), quality=95)
    return new_w, new_h


def main():
    parser = argparse.ArgumentParser(description="Compose audiobook video")
    parser.add_argument("episode_dir", help="Path to episode draft directory")
    args = parser.parse_args()

    config = load_config()
    ep_dir = Path(args.episode_dir).expanduser()

    narration_mp3 = ep_dir / "narration.mp3"
    narration_srt = ep_dir / "narration.srt"
    cover_path = ep_dir / "cover.jpg"

    for f in [narration_mp3, narration_srt]:
        if not f.exists():
            print(f"ERROR: Required file not found: {f}", file=sys.stderr)
            sys.exit(1)

    if not cover_path.exists():
        for ext in [".png", ".jpeg", ".webp"]:
            alt = ep_dir / f"cover{ext}"
            if alt.exists():
                cover_path = alt
                break
        else:
            print(f"ERROR: cover image not found in {ep_dir}", file=sys.stderr)
            sys.exit(1)

    total_duration = get_audio_duration(str(narration_mp3))
    if total_duration <= 0:
        print("ERROR: Audio duration is 0 or negative, cannot compose video", file=sys.stderr)
        sys.exit(1)

    width, height = 1920, 1080
    fps = config["video"].get("fps", 30)
    font_size = config["video"]["subtitleFontSize"]
    margin_v = config["video"]["subtitleMarginV"]

    print(f"Composing audiobook video: {total_duration:.0f}s ({total_duration/60:.1f} min)")
    print(f"  Cover: {cover_path.name}")
    print(f"  Audio: {narration_mp3.name}")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        # Pre-render composite frame (blurred bg + sharp cover)
        frame_path = tmp_dir / "frame.png"
        fw, fh = create_composite_frame(cover_path, width, height, frame_path)
        print(f"  Frame: {fw}x{fh} cover on blurred bg")

        # Generate ASS subtitle with final parameters directly
        ass_path = tmp_dir / "subtitle.ass"
        generate_ass(str(narration_srt), str(ass_path), font_size, width, height,
                     font_name="STHeiti", outline_width=2, margin_v=margin_v, shadow=1)

        # Mix BGM if configured
        final_audio = narration_mp3
        bgm_config = config.get("bgm", {})
        if bgm_config.get("enabled"):
            # Select BGM based on genre from publish-meta.json
            library = bgm_config.get("library", {})
            genre = None
            meta_path = ep_dir.parent / f"{ep_dir.name.rsplit('-EP', 1)[0]}-publish-meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                genre = meta.get("genre")
            if genre and genre in library:
                bgm_path = SKILL_DIR / library[genre]
            else:
                bgm_path = SKILL_DIR / bgm_config.get("file", "")
        else:
            bgm_path = None
        if bgm_path and bgm_path.exists():
            bgm_vol = bgm_config.get("volume", 0.08)
            fade_in = bgm_config.get("fadeIn", 3.0)
            fade_out = bgm_config.get("fadeOut", 3.0)
            fade_out_start = max(total_duration - fade_out, 0)

            mixed_audio = tmp_dir / "mixed_audio.mp3"
            print(f"  Mixing BGM: vol={bgm_vol}")
            bgm_cmd = [
                "ffmpeg", "-y",
                "-i", str(narration_mp3),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-filter_complex",
                f"[1:a]volume={bgm_vol},"
                f"afade=t=in:d={fade_in},"
                f"afade=t=out:st={fade_out_start:.2f}:d={fade_out}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[out]",
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(mixed_audio),
            ]
            result = subprocess.run(bgm_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                final_audio = mixed_audio
                print(f"  BGM mixed OK")
            else:
                print(f"  BGM mix failed, using narration only")

        # Compose: static frame + audio + subtitles
        final_output = ep_dir / "final.mp4"
        ass_escaped = escape_filter_path(ass_path)
        crf = str(config["video"]["crf"])

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-r", str(fps), "-i", str(frame_path),
            "-i", str(final_audio),
            "-vf", f"format=yuv420p,subtitles={ass_escaped}",
            "-c:v", "libx264", "-preset", "medium", "-crf", crf,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-shortest",
            str(final_output),
        ]

        print(f"  Encoding...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if result.returncode != 0:
            print(f"COMPOSE_FAILED: {result.stderr[-300:]}", file=sys.stderr)
            sys.exit(1)

        final_size_mb = final_output.stat().st_size / (1024 * 1024)
        print(f"\nCOMPOSE_OK: {final_output} ({final_size_mb:.1f} MB, {total_duration:.0f}s)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
