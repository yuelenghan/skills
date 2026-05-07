"""Subtitle parsing, conversion, and ASS generation."""

import re
from pathlib import Path


def _is_wide_char(ch):
    cp = ord(ch)
    return (0x4e00 <= cp <= 0x9fff or 0x3400 <= cp <= 0x4dbf or
            0xf900 <= cp <= 0xfaff or 0x3000 <= cp <= 0x303f or
            0xff01 <= cp <= 0xff60 or 0xfe30 <= cp <= 0xfe4f or
            0x20000 <= cp <= 0x2a6df)


def wrap_line_cjk(line, max_width):
    """Wrap a line at max_width, counting CJK chars as 1.0 and ASCII as 0.5.
    Avoids wrapping if the remainder would be shorter than 4 characters."""
    if not line:
        return ['']

    def _line_width(text):
        return sum(1.0 if _is_wide_char(ch) else 0.5 for ch in text)

    total_w = _line_width(line)
    if total_w <= max_width:
        return [line]

    # Find wrap point, but ensure remainder >= 4 chars
    lines = []
    cur = ''
    w = 0.0
    for i, ch in enumerate(line):
        cw = 1.0 if _is_wide_char(ch) else 0.5
        if w + cw > max_width and cur:
            remainder = line[i:]
            if len(remainder) < 4:
                cur += remainder
                break
            lines.append(cur)
            cur = ch
            w = cw
        else:
            cur += ch
            w += cw
    if cur:
        lines.append(cur)
    return lines or ['']


def parse_srt(text):
    """Parse SRT text into list of {idx, ts, text} dicts."""
    blocks = re.split(r"\n\n+", text.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        timestamp = lines[1].strip()
        content = "\n".join(lines[2:]).strip()
        entries.append({"idx": idx, "ts": timestamp, "text": content})
    return entries


def entries_to_srt(entries):
    """Convert {idx, ts, text} dicts back to SRT text."""
    parts = []
    for e in entries:
        parts.append(f"{e['idx']}\n{e['ts']}\n{e['text']}")
    return "\n\n".join(parts) + "\n"


def read_srt_entries(srt_path):
    """Read SRT file and return parsed entries."""
    text = Path(srt_path).read_text(encoding="utf-8")
    return parse_srt(text)


def deduplicate_youtube_subs(entries):
    """Clean YouTube auto-generated subtitles with semantic segmentation.

    Preserves original timing (audio-synced) while producing readable,
    properly segmented subtitle lines.
    """
    NOISE_PATTERN = re.compile(r"^\[.*\]$")
    SENTENCE_END = set("。！？")
    CLAUSE_END = set("，、；：")
    SINGLE_CHAR_STARTERS = set("这那但而却")
    MULTI_CHAR_STARTERS = ("不过", "可是", "所以", "因此", "因为", "由于",
                           "于是", "然后", "接着", "随后", "之后", "如果",
                           "假如", "要是", "并且", "而且", "还有",
                           "虽然", "尽管", "只是", "其实", "总之", "结果")

    def _parse_ts(ts_str):
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', ts_str)
        if not m:
            return 0, 0
        g = [int(x) for x in m.groups()]
        s = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3]
        e = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7]
        return s, e

    def _make_ts(start_ms, end_ms):
        def fmt(ms):
            h = ms // 3600000
            mi = (ms % 3600000) // 60000
            s = (ms % 60000) // 1000
            frac = ms % 1000
            return f"{h:02d}:{mi:02d}:{s:02d},{frac:03d}"
        return f"{fmt(start_ms)} --> {fmt(end_ms)}"

    def _starts_new_clause(text):
        if not text:
            return False
        if any(text.startswith(w) for w in MULTI_CHAR_STARTERS):
            return True
        if text[0] in SINGLE_CHAR_STARTERS:
            return True
        return False

    def _split_long_entry(text, start, end):
        """Split a single long entry at clause-starter positions."""
        if len(text) <= 20:
            return [{"text": text, "start": start, "end": end}]
        # Scan for split points
        for i in range(8, len(text)):
            remainder = text[i:]
            if _starts_new_clause(remainder) and len(remainder) >= 3:
                ratio = i / len(text)
                mid = start + int((end - start) * ratio)
                return [
                    {"text": text[:i], "start": start, "end": mid},
                    {"text": text[i:], "start": mid, "end": end},
                ]
            if text[i] in CLAUSE_END:
                ratio = (i + 1) / len(text)
                mid = start + int((end - start) * ratio)
                return [
                    {"text": text[:i+1], "start": start, "end": mid},
                    {"text": text[i+1:], "start": mid, "end": end},
                ]
        # No good split point found, keep as-is
        return [{"text": text, "start": start, "end": end}]

    if not entries:
        return []

    # Step 1: deduplicate YouTube sliding window + filter noise
    deduped = []
    prev_last_line = ""
    for entry in entries:
        lines = entry["text"].split("\n")
        bottom = lines[-1].strip() if len(lines) > 1 else lines[0].strip()
        if len(lines) == 1 and bottom == prev_last_line:
            continue
        if not bottom or NOISE_PATTERN.match(bottom) or len(bottom) <= 1:
            continue
        s, e = _parse_ts(entry["ts"])
        if s == 0 and e == 0:
            continue
        deduped.append({"text": bottom, "start": s, "end": e})
        prev_last_line = bottom

    if not deduped:
        return []

    # Step 2: split overly long single entries at semantic points
    split_items = []
    for item in deduped:
        split_items.extend(_split_long_entry(item["text"], item["start"], item["end"]))

    # Step 3: merge fragments + segment at semantic boundaries
    result = []
    buf_text = ""
    buf_start = 0
    buf_end = 0

    def _flush_buf():
        nonlocal buf_text, buf_start, buf_end
        if buf_text:
            result.append({"text": buf_text, "start": buf_start, "end": buf_end})
            buf_text = ""
            buf_start = 0
            buf_end = 0

    for item in split_items:
        new_text = item["text"]

        if not buf_text:
            buf_text = new_text
            buf_start = item["start"]
            buf_end = item["end"]
            continue

        # Pre-append checks: should we flush BEFORE adding this item?
        if _starts_new_clause(new_text) and len(buf_text) >= 6:
            _flush_buf()
            buf_text = new_text
            buf_start = item["start"]
            buf_end = item["end"]
            continue

        if len(buf_text) + len(new_text) > 20:
            _flush_buf()
            buf_text = new_text
            buf_start = item["start"]
            buf_end = item["end"]
            continue

        # Append
        buf_text += new_text
        buf_end = item["end"]

        # Post-append checks
        if buf_text[-1] in SENTENCE_END:
            _flush_buf()
        elif buf_text[-1] in CLAUSE_END and len(buf_text) >= 8:
            _flush_buf()

    # Flush remaining
    if buf_text:
        if result and len(buf_text) < 4:
            result[-1]["text"] += buf_text
            result[-1]["end"] = buf_end
        else:
            _flush_buf()

    # Step 4: convert to entry format
    final = []
    for i, item in enumerate(result, 1):
        final.append({
            "idx": i,
            "ts": _make_ts(item["start"], item["end"]),
            "text": item["text"],
        })

    return final


def extract_srt_range(entries, start_ms, end_ms, offset_ms=None):
    """Extract SRT entries within [start_ms, end_ms) and shift timestamps.

    Args:
        entries: list of {idx, ts, text} dicts from parse_srt/read_srt_entries.
        start_ms: start of range in milliseconds.
        end_ms: end of range in milliseconds.
        offset_ms: value to subtract from timestamps. Defaults to start_ms
                   (so the first entry starts near 0).

    Returns:
        list of new {idx, ts, text} dicts with renumbered indices and shifted timestamps.
    """
    if offset_ms is None:
        offset_ms = start_ms

    def _ts_to_ms_pair(ts_str):
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', ts_str)
        if not m:
            return None, None
        g = [int(x) for x in m.groups()]
        s = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3]
        e = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7]
        return s, e

    def _ms_to_srt_ts(ms):
        h = ms // 3600000
        mi = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        frac = ms % 1000
        return f"{h:02d}:{mi:02d}:{s:02d},{frac:03d}"

    result = []
    idx = 1
    for entry in entries:
        s, e = _ts_to_ms_pair(entry["ts"])
        if s is None:
            continue
        if e <= start_ms or s >= end_ms:
            continue
        ns = max(s - offset_ms, 0)
        ne = min(e, end_ms) - offset_ms
        ne = max(ne, ns + 1)
        new_ts = f"{_ms_to_srt_ts(ns)} --> {_ms_to_srt_ts(ne)}"
        result.append({"idx": idx, "ts": new_ts, "text": entry["text"]})
        idx += 1

    return result


def generate_ass(srt_path, ass_path, font_size=60, video_width=1920, video_height=1080,
                 font_name="Hiragino Sans GB", text_color="&H00FFFFFF",
                 outline_color="&H00000000", outline_width=4, margin_v=80,
                 bold=True, shadow=2):
    """Convert SRT to ASS subtitle file with outline style."""
    entries = read_srt_entries(srt_path)
    if not entries:
        return False

    def _ts_to_ms(ts_str):
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', ts_str)
        if not m:
            return 0, 0
        g = [int(x) for x in m.groups()]
        start = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3]
        end = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7]
        return start, end

    def _ms_to_ass(ms):
        h = ms // 3600000
        mi = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{mi:02d}:{s:02d}.{cs:02d}"

    bold_flag = -1 if bold else 0
    margin_h = int(video_width * 0.04)
    max_chars = (video_width - 2 * margin_h) / font_size

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
        f"{outline_color},&H80000000,{bold_flag},0,0,0,100,100,0,0,1,"
        f"{outline_width},{shadow},2,"
        f"{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    events = []
    for entry in entries:
        start_ms, end_ms = _ts_to_ms(entry["ts"])
        if start_ms == 0 and end_ms == 0:
            continue
        start = _ms_to_ass(start_ms)
        end = _ms_to_ass(end_ms)
        wrapped = []
        for seg in entry["text"].split('\n'):
            wrapped.extend(wrap_line_cjk(seg, max_chars))
        ass_text = '\\N'.join(wrapped)
        events.append(
            f"Dialogue: 0,{start},{end},Text,,0,0,0,,{ass_text}"
        )

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write('\n'.join(events))
        f.write('\n')

    return True


def _apply_highlight_tags(text, highlight_color="&H0000FFFF", base_color="&H00FFFFFF"):
    """Convert <<keyword>> markers to ASS inline color override tags."""
    result = text.replace("<<", "{\\c" + highlight_color + "}").replace(">>", "{\\c" + base_color + "}")
    return result


def strip_highlight_markers(text):
    """Remove <<>> markers, returning plain text for TTS."""
    return re.sub(r'<<(.+?)>>', r'\1', text)


def generate_ass_highlighted(srt_path, ass_path, commentary_marked,
                             font_size=52, video_width=1920, video_height=1080,
                             font_name="Hiragino Sans GB",
                             text_color="&H00FFFFFF",
                             highlight_color="&H0000FFFF",
                             outline_color="&H00000000", outline_width=4,
                             margin_v=60, bold=True, shadow=2):
    """Generate ASS subtitle with keyword highlighting from <<>> markers.

    Args:
        srt_path: TTS-generated SRT (provides timing)
        ass_path: output ASS file path
        commentary_marked: original commentary text with <<keyword>> markers
    """
    entries = read_srt_entries(srt_path)
    if not entries:
        return False

    marked_words = re.findall(r'<<(.+?)>>', commentary_marked)

    def _ts_to_ms(ts_str):
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', ts_str)
        if not m:
            return 0, 0
        g = [int(x) for x in m.groups()]
        start = g[0]*3600000 + g[1]*60000 + g[2]*1000 + g[3]
        end = g[4]*3600000 + g[5]*60000 + g[6]*1000 + g[7]
        return start, end

    def _ms_to_ass(ms):
        h = ms // 3600000
        mi = (ms % 3600000) // 60000
        s = (ms % 60000) // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{mi:02d}:{s:02d}.{cs:02d}"

    def _highlight_entry_text(entry_text):
        result = entry_text
        for word in marked_words:
            if word in result:
                colored = "{\\c" + highlight_color + "}" + word + "{\\c" + text_color + "}"
                result = result.replace(word, colored, 1)
        return result

    margin_h = int(video_width * 0.04)
    max_chars = (video_width - 2 * margin_h) / font_size

    bold_flag = -1 if bold else 0

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
        f"{outline_color},&H80000000,{bold_flag},0,0,0,100,100,0,0,1,"
        f"{outline_width},{shadow},2,"
        f"{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    events = []
    for entry in entries:
        start_ms, end_ms = _ts_to_ms(entry["ts"])
        if start_ms == 0 and end_ms == 0:
            continue
        start = _ms_to_ass(start_ms)
        end = _ms_to_ass(end_ms)
        raw_text = entry["text"]
        wrapped = []
        for seg in raw_text.split('\n'):
            wrapped.extend(wrap_line_cjk(seg, max_chars))
        highlighted_lines = [_highlight_entry_text(line) for line in wrapped]
        ass_text = '\\N'.join(highlighted_lines)
        events.append(
            f"Dialogue: 0,{start},{end},Text,,0,0,0,,{ass_text}"
        )

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write('\n'.join(events))
        f.write('\n')

    return True
