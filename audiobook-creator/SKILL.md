---
name: audiobook-creator
description: "Turn novels (epub/txt) into multi-episode audiobook videos with TTS narration, subtitles, and background music, then publish to video platforms. Use this skill whenever the user wants to create an audiobook, convert a novel to audio/video, produce narrated book content, make a 有声书, or mentions TTS + book + video in any combination. Also triggers on: episode splitting, novel-to-video pipeline, book narration, audiobook publishing."
---

# Audiobook Creator

Turn any novel into a polished multi-episode audiobook video series — from raw text to published content.

## Prerequisites

- Python 3.10+, ffmpeg (with libass), edge-tts, Pillow, numpy
- No external AI model dependency — the agent itself handles all AI decisions
- Optional: Apple Books (macOS only, for epub auto-extraction)
- Optional: `bilibili-cookies.json` in skill root (for B站 publishing)
- Optional: Feishu bot credentials (for completion notifications)

## First-Run Setup (Agent MUST do this on first use)

**Speed principle: never block on a single step. Run checks in parallel, show results fast.**

Check environment (run all 3 in one go):

```bash
python3 --version && ffmpeg -version 2>&1 | head -1 && pip3 show edge-tts Pillow numpy 2>&1 | grep -c "Name:"
```

If anything missing, install:
```bash
pip3 install -r "$SKILL_DIR/requirements.txt"
```

Then ask the user:

> "你想把有声书发布到 B站 吗？如果需要发布，我来帮你登录；不需要的话可以跳过，只生成视频文件。"

**If user wants B站 publishing**, extract cookies from browser:
```bash
python3 "$SKILL_DIR/scripts/login-bilibili.py"
```
Auto-extracts bilibili cookies from user's browser (< 3 seconds, no interaction needed if already logged in).

- `STATUS=DONE` → cookies saved, proceed with pipeline
- `STATUS=EXISTS` → already configured, skip
- `STATUS=NOT_LOGGED_IN` → say exactly this to user:
  > "检测到你的浏览器还没有登录 B站。请在浏览器打开 bilibili.com 并登录你的账号，登录完成后告诉我，我再提取 cookies。"
  Then wait for user to confirm, and re-run the script.
- `ERROR=...` → show the error message to user, ask if they want to skip publishing

**If user skips**, proceed directly with audiobook production.

**For OpenClaw users who want Feishu notifications** (interactive agent users don't need this):
```bash
python3 "$SKILL_DIR/scripts/setup-feishu.py"
```

## Quick Start

```bash
# 1. Initialize project (auto-extracts from Apple Books, or provide --source)
pipeline.sh --novel "书名" --init --author "作者"

# 2. Produce episodes (splits + TTS + video, max 5 per run)
pipeline.sh --novel "书名"

# 3. ⏸ User reviews output quality (agent pauses here for confirmation)

# 4. Publish to platform (only after user says "发布")
pipeline.sh --novel "书名" --publish
```

## Detailed Workflow

### Phase 1: Source Acquisition

**Automatic (Apple Books)**:
Pipeline searches `~/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents/*.epub` by fuzzy title match, extracts cover + full text (excluding non-narrative: preface, copyright, TOC, acknowledgments).

**Manual**:
```bash
pipeline.sh --novel "书名" --init --author "作者" --source ~/path/to/novel.txt --cover ~/path/to/cover.jpg
```

Source text should be clean UTF-8 with chapter headings. The splitter recognizes patterns like `第X章`, `第X回`, `序`, `楔子`, `尾声`, `番外`, `后记`, `终章`.

**AI Decision Point**: If the source contains non-standard chapter markers, the agent should identify them and pass as `extraChapterPatterns` in config.

### Phase 2: Episode Splitting

`split-novel.py` divides the novel into episodes optimized for listening:

| Rule | Value | Rationale |
|------|-------|-----------|
| Target duration | 40-50 min | Ideal commute/session length |
| Max duration | 60 min | Prevents listener fatigue |
| Min tail merge | 15 min | Avoids stub episodes |
| Split boundary | Chapter edges only | Never breaks mid-chapter |
| Character estimate | 280 chars/min | Calibrated for Chinese TTS at normal speed |

**AI Decision Point**: After splitting, review the episode count and durations. If a book yields <3 episodes, consider shorter target durations. If >20 episodes, consider longer targets to reduce total count.

**AI generates episode titles** after splitting: read each episode's `outline.json`, then update the `title` field with a 10-20 character narrative arc summary (not just chapter titles). Write directly to `outline.json` via the file system.

### Phase 3: Narration Generation

`generate-narration.py` takes each episode's text and:
1. Splits evenly into segments (~350 chars each)
2. Inserts `[IMAGE]` tags between segments (for potential future illustration support)
3. Outputs `narration.md` per episode

No AI intervention needed here — purely mechanical.

### Phase 4: TTS Rendering

`render-tts.py` converts narration to speech:
- Engine: Microsoft Edge-TTS (free, high quality)
- Default voice: `zh-CN-YunjianNeural` (Chinese male, authoritative)
- Filters standalone numbers (prevents reading scene markers as digits)
- Outputs: `narration.mp3` + `narration.srt` (with timestamps)
- Retry logic: 2 attempts with 30s delay on failure

**AI Decision Point**: Voice selection based on content:
- Literary fiction / mystery → `zh-CN-YunjianNeural` (male, deep)
- Romance / light novel → `zh-CN-XiaoxiaoNeural` (female, warm)
- Historical epic → `zh-CN-YunxiNeural` (male, narrative)
- For non-Chinese content, select appropriate locale voice

### Phase 5: Video Composition

`compose-video.py` creates the visual layer:
1. **Background**: Book cover with Gaussian blur (radius=40) + 60% brightness
2. **Foreground**: Original cover centered, sharp
3. **Subtitles**: ASS format, burned in (FontSize=52, bold, bottom margin 60px)
4. **BGM**: Looped ambient music at 8% volume with 3s fade in/out
5. **Encoding**: H.264, CRF 23, 1080p @ 30fps

Output: `final.mp4` per episode.

**AI Decision Point**: BGM selection should match genre:
- Mystery/thriller → ambient tension
- Romance → soft piano
- Historical → traditional instruments
- Sci-fi → electronic ambient

### Phase 6: Metadata Generation

After video composition, generate platform metadata:

```json
{
  "novel": "书名",
  "author": "作者",
  "tid": 228,
  "tags": ["有声书", "书名", "作者", "genre1", "有声读物", "tag6-10"],
  "episodes": {
    "EP01": {
      "title": "【有声书】{书名} EP01 {episode_summary} | {作者}",
      "description": "内容简介（绝不提及AI/TTS/自动生成）"
    }
  }
}
```

**Tag rules**: Exactly 10 tags. First 5 fixed (有声书 + 书名 + 作者 + genre + 有声读物), last 5 AI-generated based on content (nationality, sub-genre, era, themes, etc.).

**Description rules**: Write as if narrated by a human. Never mention AI, TTS, automated, or generated. Focus on the story content and what listeners will experience.

### Phase 7: User Review & Publish Confirmation

Production complete does NOT mean auto-publish. The agent MUST pause and let the user review before publishing.

**Review handoff**:
1. Report production results to user: episode count, total duration, output paths
2. Suggest the user check at least one episode (recommend EP01) for quality:
   - Audio clarity and pacing
   - Subtitle accuracy and timing
   - BGM volume balance
   - Overall listening experience
3. Present the user with clear options:
   - **发布** → proceed to `pipeline.sh --novel "NAME" --publish`
   - **暂不发布** → stop here; user can publish later manually or trigger again
   - **重做某集** → rerun specific episodes with adjustments (voice, BGM, etc.)

**Never auto-publish.** Even if the user's original request says "做成有声书发到B站", always pause after production for confirmation. The user may want to spot-check a few episodes, adjust metadata, or tweak the voice before going live.

**Publishing** (only after user confirms):
```bash
pipeline.sh --novel "NAME" --publish [--episode N]
```

Publishing limits: max 3 episodes per run, 30-minute intervals between uploads.

## Command Reference

```bash
pipeline.sh --novel "NAME" --init --author "AUTHOR" [--source FILE] [--cover FILE]
pipeline.sh --novel "NAME" [--episode N] [--max-episodes N] [--compose-only]
pipeline.sh --novel "NAME" --publish [--episode N]
```

| Flag | Purpose |
|------|---------|
| `--init` | Initialize new project |
| `--author` | Author name (required with --init) |
| `--source` | Override auto-extraction with custom text file |
| `--cover` | Override auto-extracted cover image |
| `--episode N` | Process only episode N |
| `--max-episodes N` | Limit episodes per run (default: 5) |
| `--compose-only` | Skip split/TTS, only recompose video |
| `--publish` | Upload to platform |

## Checkpoint & Resume

The pipeline is **idempotent** — it detects completed steps and skips them:
- Episode split exists (`outline.json`) → skip splitting
- Audio exists (`narration.mp3`) → skip TTS
- Video exists (`final.mp4`) → skip composition
- Already published (`published.txt`) → skip upload

To redo a step: delete its output file and rerun.

## Configuration

All tunables live in `config.json`:

```json
{
  "outputDir": "~/Videos/audiobook",
  "tts": {
    "voice": "zh-CN-YunjianNeural",
    "rate": "+0%",
    "novelVolume": "+800%"
  },
  "video": {
    "resolution": "1920x1080",
    "fps": 30,
    "subtitleFontSize": 52,
    "crf": 23
  },
  "narration": {
    "segmentChars": 350,
    "charsPerMinute": 280
  },
  "bgm": {
    "enabled": true,
    "volume": 0.08,
    "fadeIn": 3.0,
    "fadeOut": 3.0
  },
  "bilibili": {
    "copyright": 1,
    "tid": 228
  }
}
```

## Directory Structure

```
{outputDir}/
├── sources/
│   ├── {novel}.txt          # Extracted/provided source text
│   └── {novel}-cover.jpg    # Cover image
├── drafts/
│   ├── {novel}-EP01/
│   │   ├── outline.json     # Episode structure
│   │   ├── narration.md     # Segmented text
│   │   ├── narration.mp3    # TTS audio
│   │   ├── narration.srt    # Subtitle timestamps
│   │   ├── cover.jpg        # Episode cover
│   │   └── final.mp4        # Composed video
│   ├── {novel}-EP02/
│   │   └── ...
│   └── {novel}-publish-meta.json
└── published.txt            # Upload tracking
```

## Intelligent Decisions (Agent Guidelines)

When executing this workflow, the agent makes all AI decisions directly (no external model dependency — the agent IS the model):

1. **Genre detection**: Read the first 2000 characters and determine genre (mystery/romance/historical/electronic) → pass via `--genre` to `split-novel.py` → influences BGM, voice, tags
2. **Episode titles**: After `split-novel.py` finishes, read each episode's `outline.json` and overwrite the `title` field with a 10-20 char narrative summary
3. **Episode count estimation**: `total_chars / (charsPerMinute * target_minutes)` — warn user if >15 episodes (long project)
4. **Quality check after first episode**: Verify TTS rendered correctly, video has audio, subtitles are readable
5. **Metadata generation**: Generate all episode descriptions in one pass for narrative consistency
6. **Error recovery**: On TTS failure → retry with different voice; on compose failure → check ffmpeg codec support

## Timeout Protection

- Single production run: max 5 episodes (configurable)
- Single publish run: max 3 episodes with 30-min intervals
- Total pipeline MUST complete within 2 hours (hard timeout in background execution)
- The agent should estimate total time: `episodes × ~12min/episode` and warn if approaching limit

## Platform Adaptation

**Bilibili** (default): tid=228, copyright=1, cookies in skill root `bilibili-cookies.json`
**YouTube**: Future support — adjust metadata format, no tid/copyright fields
**Local only**: Skip publish step, just produce videos for manual upload

## Bilibili Login (Agent runs this for user)

When user wants to publish to B站 but `bilibili-cookies.json` doesn't exist (or cookies expired):

```bash
python3 "$SKILL_DIR/scripts/login-bilibili.py"        # first time
python3 "$SKILL_DIR/scripts/login-bilibili.py" --force  # re-login (cookies expired)
```

The script auto-extracts bilibili cookies from user's browser via yt-dlp. No interaction needed if user is already logged into bilibili.com.

- `STATUS=DONE` → cookies saved, proceed with pipeline
- `STATUS=EXISTS` → already configured, skip
- `STATUS=NOT_LOGGED_IN` → user not logged in; tell them to log in at bilibili.com first, then retry
- `ERROR=...` → show error, offer to skip publishing

Supports: Chrome, Firefox, Safari, Edge, Chromium, Brave, Opera (auto-detect).

**Cookies expire monthly.** When publish fails with -101/-401 error, re-run with `--force`.

**User can always skip this step** — without cookies, the skill produces videos locally without publishing.

## Feishu Notification (OpenClaw users only)

Interactive agent users don't need this — agent reports results directly in conversation.

For OpenClaw users who want completion notifications after publishing:

```bash
python3 "$SKILL_DIR/scripts/setup-feishu.py"
```

The script checks OpenClaw config for Feishu bot credentials and guides the user to provide their open_id.

Prerequisites (configured in `~/.openclaw/openclaw.json`):
- Feishu bot appId + appSecret (from 飞书开放平台 → 自建应用)

Not configured = silently skipped. No error, no crash.
