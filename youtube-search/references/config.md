# Configuration Reference

## config.json

The skill uses `config.example.json` as default. To customize, create `config.json` in the skill directory (takes priority). Only override fields you want to change.

```json
{
  "outputDir": "~/Videos/my-downloads",
  "daysBack": 7,
  "browser": "firefox"
}
```

## Full Configuration Table

| Section | Field | Default | Purpose |
|---------|-------|---------|---------|
| (root) | `outputDir` | `~/Videos/youtube-search` | Base output directory |
| (root) | `daysBack` | `30` | Only show videos from last N days |
| (root) | `maxResults` | `50` | Raw YouTube results to fetch |
| (root) | `topN` | `10` | Filtered results to display |
| `download` | `quality` | `best[height<=1080]` | yt-dlp format selector |
| `download` | `sleepInterval` | `5-15` | Seconds between downloads |
| `download` | `sleepRequests` | `1.5` | Seconds between API requests |
| `download` | `limitRate` | `5M` | Bandwidth cap |
| `subtitles` | `langs` | `en,zh-Hans,zh-Hant,zh` | Subtitle languages |
| `filter` | `excludeCJK` | `true` | Skip CJK-titled videos |
| (root) | `browser` | `chrome` | Browser for cookies |
| `tts` | `voice` | `zh-CN-YunjianNeural` | Edge TTS voice name |
| `tts` | `rate` | `+0%` | TTS speech rate |
| `video` | `subtitleFontSize` | `48` | ASS subtitle font size (px at 1080p) |
| `video` | `subtitleFont` | `PingFang SC` | Subtitle font family |
| `video` | `originalVolumePercent` | `10` | Original audio volume (%) |
| `video` | `narrationVolumePercent` | `500` | Narration audio volume (%) |
| `bilibili` | `cookiePath` | `~/.config/bilibili-cookies.json` | Cookie file path |
| `bilibili` | `defaultTid` | `182` | Bilibili category ID |
| `bilibili` | `copyright` | `1` | 1=original, 2=repost |
| `bilibili` | `brandText` | `""` | Cover overlay brand text |
| `bilibili` | `maxDailyPublish` | `10` | Daily upload limit |
| `bilibili` | `uploadInterval` | `1800` | Seconds between uploads |

## Bilibili Cookie Format

The cookie file must be JSON:

```json
{
  "cookie_info": {
    "cookies": [
      {"name": "SESSDATA", "value": "..."},
      {"name": "bili_jct", "value": "..."},
      {"name": "DedeUserID", "value": "..."},
      {"name": "buvid3", "value": "..."}
    ]
  }
}
```

How to get cookies:
1. Run `python3 "$SKILL_DIR/scripts/login-bilibili.py"` — auto-extracts from browser
2. Or manually: `yt-dlp --cookies-from-browser chrome --cookies bilibili-cookies.txt "https://www.bilibili.com"`, then convert to nested JSON format

File must be `chmod 600`. Cookies expire monthly — watch for `-101`/`-401` errors and re-run `login-bilibili.py --force`.

## Command Reference

### yt-search.sh

```bash
bash "$SKILL_DIR/scripts/yt-search.sh" "query" [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--list-only` | Show results without downloading |
| `--pick N,N` | Download specific results by number |
| `--pick all` | Download all filtered results |
| `--max N` | Override maxResults |
| `--output DIR` | Override outputDir |
| `--days N` | Override daysBack |
| `--top N` | Override topN |
| `--no-subs` | Skip subtitle download |
| `--no-date-check` | Skip individual date queries (faster, but no date filtering) |
| `--browser NAME` | Override browser for cookies |

### tts-render.py

```bash
python3 "$SKILL_DIR/scripts/tts-render.py" [--voice VOICE] <draft_dir> [...]
```

Reads `translated.srt` (or `script.md`), generates `narration.mp3` + `narration.srt`.

### compose-video.py

```bash
python3 "$SKILL_DIR/scripts/compose-video.py" [--keep-draft] <draft_dir> [...]
```

| Option | Description |
|--------|-------------|
| `--keep-draft` | Don't delete the source draft directory after composing |

### publish-bilibili.py

```bash
python3 "$SKILL_DIR/scripts/publish-bilibili.py" [--auto] [--no-quota] [--interval S] [video_dir ...]
```

| Option | Description |
|--------|-------------|
| `--auto` | Auto-collect unpublished from 待发布/ |
| `--no-quota` | Bypass daily quota limit |
| `--interval S` | Override upload interval (seconds) |

### archive.py

```bash
python3 "$SKILL_DIR/scripts/archive.py"
```

Idempotent cleanup: moves published dirs from `待发布/` to `已发布/`.

### login-bilibili.py

```bash
python3 "$SKILL_DIR/scripts/login-bilibili.py" [--browser BROWSER] [--force]
```

Extracts Bilibili cookies from the user's browser. Use `--force` to refresh expired cookies.
