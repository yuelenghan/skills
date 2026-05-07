"""TTS rendering via edge-tts."""

import asyncio
import re
import subprocess
from pathlib import Path


def _is_cjk(ch):
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF)


def smart_join_cjk(lines):
    """Join subtitle lines with CJK-aware spacing."""
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
    """Extract plain text from SRT file (strip indices and timestamps)."""
    content = Path(srt_path).read_text(encoding="utf-8")
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
    return smart_join_cjk(lines)


async def render_tts(text, output_mp3, output_srt, voice="zh-CN-YunjianNeural", rate="+5%", volume="+0%"):
    """Render TTS audio and subtitle via edge-tts."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    submaker = edge_tts.SubMaker()

    with open(output_mp3, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                submaker.feed(chunk)

    srt_content = submaker.get_srt()
    Path(output_srt).write_text(srt_content, encoding="utf-8")


def render_tts_sync(text, output_mp3, output_srt, voice="zh-CN-YunjianNeural", rate="+5%", volume="+0%"):
    """Synchronous wrapper for render_tts."""
    return asyncio.run(render_tts(text, output_mp3, output_srt, voice, rate, volume))


def get_audio_duration(mp3_path):
    """Get duration of an audio file in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp3_path)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0
