#!/usr/bin/env python3
"""Render narration audio from translated.srt or script.md using edge-tts."""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    config_path = SKILL_DIR / "config.json"
    if not config_path.exists():
        config_path = SKILL_DIR / "config.example.json"
    with open(config_path) as f:
        return json.load(f)


def _is_cjk(ch):
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF)


def _smart_join(lines):
    result = []
    for line in lines:
        if result:
            prev = result[-1]
            if prev and line and (_is_cjk(prev[-1]) or prev[-1] in "，。！？；：") and _is_cjk(line[0]):
                pass
            elif prev and line and _is_cjk(prev[-1]) and line[0] in "，。！？；：、""''）】":
                pass
            else:
                result.append(" ")
        result.append(line)
    text = "".join(result)
    text = re.sub(r"\s+([，。！？；：、""''）】])", r"\1", text)
    text = re.sub(r"([（【""''])\s+", r"\1", text)
    text = re.sub(r"([，。！？；：])\s+([一-鿿㐀-䶿])", r"\1\2", text)
    text = re.sub(r"([一-鿿㐀-䶿])\s+([一-鿿㐀-䶿])", r"\1\2", text)
    text = re.sub(r"  +", " ", text)
    return text


def extract_text_from_srt(srt_path):
    content = srt_path.read_text(encoding="utf-8")
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.match(r"\d{2}:\d{2}:\d{2}", line):
            continue
        lines.append(line)
    return _smart_join(lines)


def _split_text_chunks(text, max_chars=3000):
    sentences = re.split(r'(?<=[。！？.!?\n])', text)
    chunks = []
    current = ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) > max_chars and current:
            chunks.append(current)
            current = s
        else:
            current += s
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


async def render_tts(text, output_mp3, output_srt, voice, rate):
    import edge_tts
    import tempfile

    chunks = _split_text_chunks(text)

    if len(chunks) == 1:
        communicate = edge_tts.Communicate(chunks[0], voice, rate=rate)
        submaker = edge_tts.SubMaker()
        with open(output_mp3, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    submaker.feed(chunk)
        srt_content = submaker.get_srt()
        Path(output_srt).write_text(srt_content, encoding="utf-8")
        return

    tmp_dir = tempfile.mkdtemp(prefix="tts_chunks_")
    chunk_files = []
    all_srt_parts = []
    time_offset_ms = 0

    for i, chunk_text in enumerate(chunks):
        chunk_mp3 = f"{tmp_dir}/chunk_{i:03d}.mp3"
        communicate = edge_tts.Communicate(chunk_text, voice, rate=rate)
        submaker = edge_tts.SubMaker()
        with open(chunk_mp3, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    submaker.feed(chunk)
        chunk_files.append(chunk_mp3)

        srt_text = submaker.get_srt()
        if srt_text.strip():
            for block in re.split(r"\n\n+", srt_text.strip()):
                lines = block.strip().split("\n")
                if len(lines) >= 3:
                    ts_line = lines[1]
                    ts_match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})", ts_line)
                    if ts_match:
                        g = [int(x) for x in ts_match.groups()]
                        start_ms = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3] + time_offset_ms
                        end_ms = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7] + time_offset_ms
                        new_ts = f"{start_ms//3600000:02d}:{(start_ms%3600000)//60000:02d}:{(start_ms%60000)//1000:02d},{start_ms%1000:03d} --> {end_ms//3600000:02d}:{(end_ms%3600000)//60000:02d}:{(end_ms%60000)//1000:02d},{end_ms%1000:03d}"
                        all_srt_parts.append(f"{new_ts}\n" + "\n".join(lines[2:]))

        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", chunk_mp3],
            capture_output=True, text=True, timeout=10,
        )
        chunk_dur_ms = int(float(result.stdout.strip()) * 1000)
        time_offset_ms += chunk_dur_ms

    concat_list = f"{tmp_dir}/concat.txt"
    with open(concat_list, "w") as f:
        for cf in chunk_files:
            f.write(f"file '{cf}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output_mp3],
        capture_output=True, timeout=60,
    )

    srt_out = []
    for idx, part in enumerate(all_srt_parts, 1):
        srt_out.append(f"{idx}\n{part}")
    Path(output_srt).write_text("\n\n".join(srt_out) + "\n", encoding="utf-8")

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


def render_draft(draft_dir, voice, rate):
    draft = Path(draft_dir)
    translated_srt = draft / "translated.srt"
    script_path = draft / "script.md"

    if not translated_srt.exists() and not script_path.exists():
        return "skip"

    output_mp3 = draft / "narration.mp3"
    output_srt = draft / "narration.srt"

    if output_mp3.exists():
        if output_mp3.stat().st_size > 0:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(output_mp3)],
                    capture_output=True, text=True, timeout=10,
                )
                dur = float(result.stdout.strip())
                if dur > 0:
                    return "skip"
            except (ValueError, subprocess.TimeoutExpired):
                pass
        print(f"TTS_RERENDER: {draft_dir}")
        output_mp3.unlink(missing_ok=True)
        output_srt.unlink(missing_ok=True)

    text = None
    if translated_srt.exists():
        text = extract_text_from_srt(translated_srt)
    elif script_path.exists():
        content = script_path.read_text(encoding="utf-8")
        match = re.search(r"## 解说脚本\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if match:
            text = match.group(1).strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = re.sub(r"\*(.+?)\*", r"\1", text)
            text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = text.strip()

    if not text:
        return "fail"

    try:
        asyncio.run(render_tts(text, str(output_mp3), str(output_srt), voice, rate))
        return "ok"
    except Exception as e:
        print(f"TTS_ERROR: {e}", file=sys.stderr)
        Path(output_mp3).unlink(missing_ok=True)
        Path(output_srt).unlink(missing_ok=True)
        return "fail"


def main():
    config = load_config()
    voice = config.get("tts", {}).get("voice", "zh-CN-YunjianNeural")
    rate = config.get("tts", {}).get("rate", "+0%")

    if "--voice" in sys.argv:
        vi = sys.argv.index("--voice")
        if vi + 1 < len(sys.argv):
            voice = sys.argv[vi + 1]
            sys.argv = sys.argv[:vi] + sys.argv[vi + 2:]

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [--voice VOICE] <draft_dir> [draft_dir2 ...]", file=sys.stderr)
        sys.exit(1)

    ok_count = 0
    fail_count = 0
    skip_count = 0

    for draft_dir in sys.argv[1:]:
        status = render_draft(draft_dir, voice, rate)
        if status == "ok":
            print(f"TTS_OK: {draft_dir}")
            ok_count += 1
        elif status == "fail":
            print(f"TTS_FAILED: {draft_dir}")
            fail_count += 1
        else:
            skip_count += 1

    print(f"\nDone: {ok_count} rendered, {fail_count} failed, {skip_count} skipped")


if __name__ == "__main__":
    main()
