#!/usr/bin/env python3
"""Render TTS audio from narration.md."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from ytai.tts import render_tts_sync, get_audio_duration

SKILL_DIR = Path(__file__).resolve().parent.parent


def load_config():
    with open(SKILL_DIR / "config.json") as f:
        return json.load(f)


def extract_narration_text(narration_md):
    """Extract plain narration text from narration.md, stripping IMAGE tags and headers."""
    lines = narration_md.split("\n")
    text_lines = []
    for line in lines:
        if line.startswith("## "):
            continue
        # Strip [IMAGE: ...] tags anywhere in the line (not just whole-line matches)
        cleaned = re.sub(r'\[IMAGE:[^\]]*\]\s*', '', line).strip()
        # Skip standalone numbers (scene/section markers from original text)
        if re.match(r'^\d+$', cleaned):
            continue
        if cleaned:
            text_lines.append(cleaned)
        elif text_lines and text_lines[-1] != "":
            text_lines.append("")

    return "\n".join(text_lines).strip()


MAX_RETRIES = 2
RETRY_DELAY = 30


def main():
    parser = argparse.ArgumentParser(description="Render TTS from narration.md")
    parser.add_argument("episode_dir", help="Path to episode draft directory")
    args = parser.parse_args()

    config = load_config()
    ep_dir = Path(args.episode_dir).expanduser()

    narration_path = ep_dir / "narration.md"
    if not narration_path.exists():
        print(f"ERROR: narration.md not found in {ep_dir}", file=sys.stderr)
        sys.exit(1)

    narration_md = narration_path.read_text(encoding="utf-8")
    text = extract_narration_text(narration_md)

    if not text:
        print("ERROR: No narration text extracted", file=sys.stderr)
        sys.exit(1)

    voice = config["tts"]["voice"]
    rate = config["tts"]["rate"]
    volume = config["tts"].get("novelVolume", config["tts"].get("volume", "+0%"))
    output_mp3 = str(ep_dir / "narration.mp3")
    output_srt = str(ep_dir / "narration.srt")

    print(f"Rendering TTS: {len(text)} chars, voice={voice}, rate={rate}, volume={volume}")

    import time
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            render_tts_sync(text, output_mp3, output_srt, voice=voice, rate=rate, volume=volume)
            break
        except Exception as e:
            Path(output_mp3).unlink(missing_ok=True)
            Path(output_srt).unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                print(f"  TTS attempt {attempt} failed: {e}. Retrying in {RETRY_DELAY}s...", file=sys.stderr)
                time.sleep(RETRY_DELAY)
            else:
                print(f"TTS_FAILED: All {MAX_RETRIES} attempts failed. Last error: {e}", file=sys.stderr)
                sys.exit(1)

    # Verify outputs
    if not Path(output_mp3).exists() or Path(output_mp3).stat().st_size < 1000:
        Path(output_mp3).unlink(missing_ok=True)
        Path(output_srt).unlink(missing_ok=True)
        print("TTS_FAILED: output mp3 missing or too small", file=sys.stderr)
        sys.exit(1)

    if not Path(output_srt).exists() or Path(output_srt).stat().st_size == 0:
        Path(output_mp3).unlink(missing_ok=True)
        Path(output_srt).unlink(missing_ok=True)
        print("TTS_FAILED: output srt missing or empty", file=sys.stderr)
        sys.exit(1)

    duration = get_audio_duration(output_mp3)
    print(f"TTS_OK: {output_mp3} ({duration:.1f}s)")


if __name__ == "__main__":
    main()
