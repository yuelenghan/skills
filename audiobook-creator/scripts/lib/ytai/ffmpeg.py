"""ffmpeg wrappers for video processing."""

import subprocess
import tempfile
from pathlib import Path


def escape_drawtext(text):
    """Escape special characters for ffmpeg drawtext filter."""
    return (text
        .replace("\\", "\\\\")
        .replace("'", "'\\''")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("%", "%%")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def get_duration(media_path):
    """Get media duration in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(media_path)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def has_audio_stream(media_path):
    """Check if a media file has an audio stream."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(media_path)],
        capture_output=True, text=True, timeout=10,
    )
    return bool(result.stdout.strip())


def get_resolution(media_path):
    """Get video width,height."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(media_path)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        w, h = result.stdout.strip().split(",")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1920, 1080


def concat_videos(input_files, output_path, codec="libx264", preset="medium",
                  crf="23", audio_codec="aac", audio_bitrate="192k"):
    """Concatenate multiple video files using the concat demuxer."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        concat_list = tmp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for vf in input_files:
                f.write(f"file '{vf}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", codec, "-preset", preset, "-crf", crf,
            "-c:a", audio_codec, "-b:a", audio_bitrate,
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        return result.returncode == 0
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def create_title_card_video(text, output_mp4, duration=3, width=1920, height=1080,
                            bg_color="0x1a1a2e", text_color="white", font_size=52,
                            brand_text="", brand_color="0xcccccc", brand_font_size=22,
                            font_name="PingFang SC"):
    """Create a gradient-color background video with centered text + optional branding."""
    escaped_text = escape_drawtext(text)
    vf = (
        f"drawtext=text='{escaped_text}':fontsize={font_size}:fontcolor={text_color}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:font={font_name}"
    )
    if brand_text:
        escaped_brand = escape_drawtext(brand_text)
        vf += (
            f",drawtext=text='{escaped_brand}':fontsize={brand_font_size}:"
            f"fontcolor={brand_color}:x=w-text_w-40:y=h-50:font={font_name}"
        )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={bg_color}:s={width}x{height}:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-shortest",
        str(output_mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def create_image_video(image_path, audio_path, output_path, srt_path=None,
                       font_size=60, width=1920, height=1080):
    """Static image + audio + optional subtitles -> video segment."""
    from ytai.subtitle import generate_ass

    duration = get_duration(str(audio_path))
    if duration <= 0:
        return False

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        vf_parts = [f"scale={width}:{height},fps=30"]

        if srt_path and Path(srt_path).exists():
            tmp_ass = tmp_dir / "sub.ass"
            generate_ass(str(srt_path), str(tmp_ass), font_size, width, height)
            ass_escaped = str(tmp_ass).replace("\\", "/").replace(":", r"\:")
            vf_parts.append(f"subtitles={ass_escaped}")

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-i", str(audio_path),
            "-t", str(duration),
            "-vf", ",".join(vf_parts),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def mix_audio_video_narration(video_path, narration_path, output_path,
                               orig_vol=0.08, narr_vol=1.0, subtitle_ass_path=None,
                               codec="libx264", preset="medium", crf="23"):
    """Mix original video audio (reduced) with narration audio, burn subtitles."""
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(narration_path)]

    has_orig = has_audio_stream(video_path)
    vf_parts = []

    if subtitle_ass_path and Path(subtitle_ass_path).exists():
        ass_escaped = str(subtitle_ass_path).replace("\\", "/").replace(":", r"\:")
        vf_parts.append(f"subtitles={ass_escaped}")

    if has_orig:
        af = (f"[0:a]volume={orig_vol}[orig];[1:a]volume={narr_vol}[narr];"
              f"[orig][narr]amix=inputs=2:duration=first[aout]")
        cmd += ["-filter_complex", af]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-map", "0:v", "-map", "[aout]"]
    else:
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-map", "0:v", "-map", "1:a"]

    cmd += [
        "-c:v", codec, "-preset", preset, "-crf", crf,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    return result.returncode == 0


def clip_video(input_path, start_time, duration, output_path):
    """Clip a segment from a video."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.returncode == 0


def analyze_audio_loudness(video_path):
    """Get audio loudness curve as list of (time, loudness) pairs."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-af",
         "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    import json
    for line in result.stderr.split("\n"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None
