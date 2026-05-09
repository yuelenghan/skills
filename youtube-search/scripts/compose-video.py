#!/usr/bin/env python3
"""Compose final video: burn translated subtitles + mix narration audio."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    config_path = SKILL_DIR / "config.json"
    if not config_path.exists():
        config_path = SKILL_DIR / "config.example.json"
    with open(config_path) as f:
        return json.load(f)


def _is_wide_char(ch):
    cp = ord(ch)
    return (0x4e00 <= cp <= 0x9fff or 0x3400 <= cp <= 0x4dbf or
            0xf900 <= cp <= 0xfaff or 0x3000 <= cp <= 0x303f or
            0xff01 <= cp <= 0xff60 or 0xfe30 <= cp <= 0xfe4f or
            0x20000 <= cp <= 0x2a6df)


def _wrap_line(line, max_width):
    if not line:
        return ['']
    lines = []
    cur = ''
    w = 0.0
    for ch in line:
        cw = 1.0 if _is_wide_char(ch) else 0.5
        if w + cw > max_width and cur:
            lines.append(cur)
            cur = ch
            w = cw
        else:
            cur += ch
            w += cw
    if cur:
        lines.append(cur)
    return lines or ['']


def generate_ass(srt_path, ass_path, font_size, font_name="PingFang SC",
                 video_width=1920, video_height=1080):
    """Convert SRT to ASS with outline-style subtitles."""
    entries = []
    with open(srt_path, encoding='utf-8') as f:
        content = f.read()
    for block in re.split(r'\n\n+', content.strip()):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            lines[1],
        )
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start_ms = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3]
        end_ms = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7]
        entries.append((start_ms, end_ms, '\n'.join(lines[2:])))

    def ms_to_ass(ms):
        h = ms // 3600000
        mi = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{mi:02d}:{s:02d}.{cs:02d}"

    margin_h = int(video_width * 0.04)
    max_chars = (video_width - 2 * margin_h) / font_size
    margin_v = 30
    text_color = "&H00FFFFFF"
    outline_color = "&H00000000"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Text,{font_name},{font_size},{text_color},&H000000FF,"
        f"{outline_color},&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    events = []
    for start_ms, end_ms, text in entries:
        start = ms_to_ass(start_ms)
        end = ms_to_ass(end_ms)
        wrapped = []
        for seg in text.split('\n'):
            wrapped.extend(_wrap_line(seg, max_chars))
        ass_text = '\\N'.join(wrapped)
        events.append(
            f"Dialogue: 0,{start},{end},Text,,0,0,0,,{ass_text}"
        )

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write('\n'.join(events))
        f.write('\n')


def has_audio_stream(media_path):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(media_path)],
        capture_output=True, text=True, timeout=10,
    )
    return bool(result.stdout.strip())


def compose_single(draft_dir, output_dir, config, keep_draft=False):
    """Compose video for a single draft: subtitle burn-in + narration mix."""
    draft = Path(draft_dir)
    source_path = draft / "source.json"
    translated_srt = draft / "translated.srt"
    narration_mp3 = draft / "narration.mp3"
    narration_srt = draft / "narration.srt"
    meta_json = draft / "meta.json"

    if not source_path.exists() or not meta_json.exists():
        return "skip"

    subtitle_srt = translated_srt if translated_srt.exists() else narration_srt
    has_narration = narration_mp3.exists()

    if has_narration and narration_srt.exists():
        subtitle_srt = narration_srt

    if not subtitle_srt or not subtitle_srt.exists():
        return "skip"

    with open(source_path) as f:
        source = json.load(f)

    original_mp4 = source["mp4"]
    if not Path(original_mp4).exists():
        return "fail"

    today = date.today().isoformat()
    name = draft.name
    date_prefix = re.match(r'^\d{4}-\d{2}-\d{2}-', name)
    if date_prefix:
        name = name[date_prefix.end():]
    safe_title = re.sub(r'[/:*?"<>|]', '-', name)[:60]
    safe_title = safe_title.replace("..", "").strip(". ") or "untitled"
    out_dir = Path(output_dir).expanduser() / "待发布" / f"{today}-{safe_title}"
    out_dir.mkdir(parents=True, exist_ok=True)

    output_mp4 = out_dir / "video.mp4"
    video_cfg = config.get("video", {})
    font_size = video_cfg.get("subtitleFontSize", 48)
    font_name = video_cfg.get("subtitleFont", "PingFang SC")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        cmd = ["ffmpeg", "-y"]
        cmd += ["-i", original_mp4]
        if has_narration:
            cmd += ["-i", str(narration_mp3)]

        vf_parts = []

        tmp_ass = tmp_dir / "subtitle.ass"
        generate_ass(str(subtitle_srt), str(tmp_ass), font_size, font_name)
        ass_escaped = str(tmp_ass).replace("\\", "/").replace(":", r"\:")
        vf_parts.append(f"subtitles={ass_escaped}")

        if has_narration:
            orig_vol = video_cfg.get("originalVolumePercent", 10) / 100.0
            narr_vol = video_cfg.get("narrationVolumePercent", 500) / 100.0
            has_orig_audio = has_audio_stream(original_mp4)
            if has_orig_audio:
                af = f"[0:a]volume={orig_vol}[orig];[1:a]volume={narr_vol}[narr];[orig][narr]amix=inputs=2:duration=first[aout]"
                cmd += ["-filter_complex", af]
                if vf_parts:
                    cmd += ["-vf", ",".join(vf_parts)]
                cmd += ["-map", "0:v", "-map", "[aout]"]
            else:
                if vf_parts:
                    cmd += ["-vf", ",".join(vf_parts)]
                cmd += ["-map", "0:v", "-map", "1:a"]
        else:
            if vf_parts:
                cmd += ["-vf", ",".join(vf_parts)]
            cmd += ["-map", "0:v", "-map", "0:a"]

        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_mp4),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            print(f"FFMPEG_ERROR: {result.stderr[-500:]}", file=sys.stderr)
            shutil.rmtree(out_dir, ignore_errors=True)
            return "fail"

        for src_file in [meta_json, source_path]:
            dst = out_dir / src_file.name
            dst.write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")

        script_md = draft / "script.md"
        if script_md.exists():
            (out_dir / "script.md").write_text(script_md.read_text(encoding="utf-8"), encoding="utf-8")
        if translated_srt.exists():
            (out_dir / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")

        if narration_mp3.exists():
            (out_dir / "narration.mp3").write_bytes(narration_mp3.read_bytes())
        if narration_srt.exists():
            (out_dir / "narration.srt").write_text(
                narration_srt.read_text(encoding="utf-8"), encoding="utf-8")

        if not keep_draft:
            shutil.rmtree(str(draft), ignore_errors=True)
        return str(out_dir)
    except Exception as e:
        print(f"COMPOSE_EXCEPTION: {e}", file=sys.stderr)
        shutil.rmtree(out_dir, ignore_errors=True)
        return "fail"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    keep_draft = "--keep-draft" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--keep-draft"]

    if not args:
        print(f"Usage: {sys.argv[0]} [--keep-draft] <draft_dir> [draft_dir2 ...]", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    output_dir = config.get("outputDir", "~/Videos/youtube-search")

    ok_count = 0
    fail_count = 0
    for draft_dir in args:
        result = compose_single(draft_dir, output_dir, config, keep_draft=keep_draft)
        if result == "skip":
            print(f"COMPOSE_SKIP: {draft_dir}")
        elif result == "fail":
            print(f"COMPOSE_FAILED: {draft_dir}")
            fail_count += 1
        else:
            print(f"COMPOSE_OK: {result}")
            ok_count += 1
    print(f"\nDone: {ok_count} composed, {fail_count} failed")


if __name__ == "__main__":
    main()
