#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$SKILL_DIR/config.json" ]; then
  CONFIG="$SKILL_DIR/config.json"
else
  CONFIG="$SKILL_DIR/config.example.json"
fi
ARCHIVE="$SKILL_DIR/archive.txt"
LOG_DIR="$SKILL_DIR/logs"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/search-$TODAY.log"

mkdir -p "$LOG_DIR"
touch "$ARCHIVE"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

for cmd in yt-dlp jq python3; do
  if ! command -v "$cmd" &>/dev/null; then
    log "ERROR: $cmd not found."
    exit 1
  fi
done

if [ ! -f "$CONFIG" ]; then
  log "ERROR: config.json and config.example.json both missing."
  exit 1
fi

CACHE_FILE="$SKILL_DIR/last-search.tsv"

QUERY=""
PICK=""
LIST_ONLY=false
MAX_RESULTS=""
OUTPUT_DIR_OVERRIDE=""
DAYS_OVERRIDE=""
TOP_OVERRIDE=""
NO_SUBS=false
NO_DATE_CHECK=false
BROWSER_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pick) PICK="$2"; shift 2 ;;
    --list-only) LIST_ONLY=true; shift ;;
    --max) MAX_RESULTS="$2"; shift 2 ;;
    --output) OUTPUT_DIR_OVERRIDE="$2"; shift 2 ;;
    --days) DAYS_OVERRIDE="$2"; shift 2 ;;
    --top) TOP_OVERRIDE="$2"; shift 2 ;;
    --no-subs) NO_SUBS=true; shift ;;
    --no-date-check) NO_DATE_CHECK=true; shift ;;
    --browser) BROWSER_OVERRIDE="$2"; shift 2 ;;
    --*) echo "Unknown option: $1"; exit 1 ;;
    *) QUERY="$1"; shift ;;
  esac
done

# --pick without query: use cached results
if [ -z "$QUERY" ] && [ -n "$PICK" ] && [ -f "$CACHE_FILE" ]; then
  QUERY=$(head -1 "$CACHE_FILE" | sed 's/^# query: //')
  log "使用缓存结果 (query: $QUERY)"
elif [ -z "$QUERY" ]; then
  echo "Usage: $0 \"search query\" [--pick 1,3,5] [--list-only] [--max 20] [--output DIR] [--days N] [--top N] [--no-subs] [--no-date-check] [--browser NAME]"
  exit 1
fi

OUTPUT_DIR=$(jq -r '.outputDir // "~/Videos/youtube-search"' "$CONFIG" | sed "s|^~|$HOME|")
[ -n "$OUTPUT_DIR_OVERRIDE" ] && OUTPUT_DIR="$OUTPUT_DIR_OVERRIDE"

DAYS_BACK=$(jq -r '.daysBack // 30' "$CONFIG")
[ -n "$DAYS_OVERRIDE" ] && DAYS_BACK="$DAYS_OVERRIDE"

MAX_RESULTS_CFG=$(jq -r '.maxResults // 50' "$CONFIG")
[ -n "$MAX_RESULTS" ] || MAX_RESULTS="$MAX_RESULTS_CFG"

TOP_N=$(jq -r '.topN // 10' "$CONFIG")
[ -n "$TOP_OVERRIDE" ] && TOP_N="$TOP_OVERRIDE"

QUALITY=$(jq -r '.download.quality // "best[height<=1080]"' "$CONFIG")
SLEEP_INTERVAL=$(jq -r '.download.sleepInterval // "5-15"' "$CONFIG")
SLEEP_REQUESTS=$(jq -r '.download.sleepRequests // 1.5' "$CONFIG")
LIMIT_RATE=$(jq -r '.download.limitRate // "5M"' "$CONFIG")

SUBS_ENABLED=$(jq -r '.subtitles.enabled // true' "$CONFIG")
SUBS_LANGS=$(jq -r '.subtitles.langs // "en,zh-Hans,zh-Hant,zh"' "$CONFIG")
SUBS_FORMAT=$(jq -r '.subtitles.format // "srt"' "$CONFIG")

EXCLUDE_CJK=$(jq -r '.filter.excludeCJK // true' "$CONFIG")
KW_MIN_LEN=$(jq -r '.filter.keywordMinLength // 3' "$CONFIG")

BROWSER=$(jq -r '.browser // "chrome"' "$CONFIG")
[ -n "$BROWSER_OVERRIDE" ] && BROWSER="$BROWSER_OVERRIDE"

if [ "$NO_SUBS" = "true" ]; then
  SUBS_ENABLED="false"
fi

USED_SOURCES=$(jq -r '.usedSourcesPath // ""' "$CONFIG" | sed "s|^~|$HOME|")

mkdir -p "$OUTPUT_DIR/search"

log "=== YouTube Search: \"$QUERY\" (max $MAX_RESULTS) ==="

# --- check cache: skip search if --pick and cache matches ---
USE_CACHE=false
if [ -n "$PICK" ] && [ -f "$CACHE_FILE" ]; then
  CACHED_QUERY=$(head -1 "$CACHE_FILE" | sed 's/^# query: //')
  if [ "$CACHED_QUERY" = "$QUERY" ]; then
    USE_CACHE=true
    log "命中缓存，跳过搜索"
  fi
fi

if [ "$USE_CACHE" = "true" ]; then
  # read from cache (skip header line)
  declare -a IDS TITLES CHANNELS DURATIONS VIEWS DATES
  while IFS=$'\t' read -r vid_id vid_title vid_channel vid_dur vid_views vid_date; do
    [ -z "$vid_id" ] && continue
    IDS+=("$vid_id")
    TITLES+=("$vid_title")
    CHANNELS+=("$vid_channel")
    DURATIONS+=("$vid_dur")
    VIEWS+=("$vid_views")
    DATES+=("$vid_date")
  done < <(tail -n +2 "$CACHE_FILE")
  TOTAL=${#IDS[@]}
  log "从缓存加载 $TOTAL 条结果"
else

# --- search phase ---
log "搜索中..."
SEARCH_RAW=$(mktemp)
yt-dlp "ytsearch${MAX_RESULTS}:${QUERY}" \
  --cookies-from-browser "$BROWSER" \
  --flat-playlist \
  --sleep-requests "$SLEEP_REQUESTS" \
  --print "%(id)s	%(title)s	%(channel)s	%(duration_string)s	%(view_count)s	%(upload_date)s" \
  2>/dev/null > "$SEARCH_RAW" || true

RESULT_COUNT=$(wc -l < "$SEARCH_RAW" | tr -d ' ')
if [ "$RESULT_COUNT" -eq 0 ]; then
  log "未找到相关视频"
  rm -f "$SEARCH_RAW"
  echo "SEARCH_RESULTS: 0"
  exit 0
fi

# --- parse raw results ---
PARSED_RAW=$(mktemp)
while IFS=$'\t' read -r vid_id vid_title vid_channel vid_dur vid_views vid_date; do
  [ -z "$vid_id" ] && continue
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$vid_id" "$vid_title" "${vid_channel:-Unknown}" "${vid_dur:-N/A}" "${vid_views:-0}" "${vid_date:-N/A}" >> "$PARSED_RAW"
done < "$SEARCH_RAW"
rm -f "$SEARCH_RAW"

# --- fetch real upload dates (flat-playlist returns NA) ---
DATED_RAW=$(mktemp)
if [ "$NO_DATE_CHECK" = "true" ]; then
  log "跳过日期查询 (--no-date-check)"
  cp "$PARSED_RAW" "$DATED_RAW"
else
  log "查询上传日期..."
  while IFS=$'\t' read -r vid_id vid_title vid_channel vid_dur vid_views vid_date; do
    [ -z "$vid_id" ] && continue
    if [ "$vid_date" = "NA" ] || [ -z "$vid_date" ]; then
      real_date=$(yt-dlp --cookies-from-browser "$BROWSER" \
        --skip-download --print "%(upload_date)s" \
        "https://www.youtube.com/watch?v=$vid_id" 2>/dev/null) || true
      if [ -n "$real_date" ] && [ "$real_date" != "NA" ]; then
        vid_date="$real_date"
      fi
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$vid_id" "$vid_title" "$vid_channel" "$vid_dur" "$vid_views" "$vid_date" >> "$DATED_RAW"
  done < "$PARSED_RAW"
fi
rm -f "$PARSED_RAW"

# --- filter & rank ---
FILTERED=$(mktemp)
python3 -c "
import re, sys, os
from datetime import datetime, timedelta

query = sys.argv[2]
days_back = int(sys.argv[3])
archive_path = sys.argv[4]
used_sources_path = sys.argv[5]
exclude_cjk = sys.argv[6] == 'true'
kw_min_len = int(sys.argv[7])
top_n = int(sys.argv[8])

lines = open(sys.argv[1], encoding='utf-8').readlines()
keywords = [w.lower() for w in query.split() if len(w) >= kw_min_len]
cjk = re.compile(r'[一-鿿㐀-䶿぀-ヿㇰ-ㇿ]')
cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

archive_ids = set()
if os.path.exists(archive_path):
    for l in open(archive_path):
        parts = l.strip().split()
        if len(parts) == 2:
            archive_ids.add(parts[1])

used_ids = set()
used_paths_normalized = ''
if used_sources_path and os.path.exists(used_sources_path):
    for l in open(used_sources_path):
        stripped = l.strip()
        parts_u = stripped.split()
        if len(parts_u) == 2 and parts_u[0] == 'youtube':
            used_ids.add(parts_u[1])
        elif stripped:
            norm = re.sub(r'[^a-zA-Z0-9]', ' ', stripped).lower()
            used_paths_normalized += ' '.join(norm.split()) + '\n'

def is_published(vid_id, title):
    if vid_id in used_ids:
        return True
    if not used_paths_normalized:
        return False
    safe = re.sub(r'[^a-zA-Z0-9]', ' ', title).strip()
    safe = ' '.join(safe.split())[:40].lower()
    return safe in used_paths_normalized

results = []
for line in lines:
    parts = line.rstrip('\n').split('\t', 5)
    if len(parts) < 6:
        continue
    vid_id, title = parts[0], parts[1]
    title_lower = title.lower()
    upload_date = parts[5]
    if exclude_cjk and cjk.search(title):
        continue
    if keywords and not any(kw in title_lower for kw in keywords):
        continue
    if upload_date and upload_date != 'NA' and len(upload_date) == 8:
        if upload_date < cutoff:
            continue
    if vid_id in archive_ids and is_published(vid_id, title):
        continue
    try:
        views = int(parts[4])
    except (ValueError, TypeError):
        views = 0
    results.append((views, line.rstrip('\n')))

results.sort(key=lambda x: x[0], reverse=True)
for _, line in results[:top_n]:
    print(line)
" "$DATED_RAW" "$QUERY" "$DAYS_BACK" "$ARCHIVE" "${USED_SOURCES:-}" "$EXCLUDE_CJK" "$KW_MIN_LEN" "$TOP_N" > "$FILTERED"
rm -f "$DATED_RAW"

declare -a IDS TITLES CHANNELS DURATIONS VIEWS DATES
while IFS=$'\t' read -r vid_id vid_title vid_channel vid_dur vid_views vid_date; do
  [ -z "$vid_id" ] && continue
  IDS+=("$vid_id")
  TITLES+=("$vid_title")
  CHANNELS+=("$vid_channel")
  DURATIONS+=("$vid_dur")
  VIEWS+=("$vid_views")
  DATES+=("$vid_date")
done < "$FILTERED"
rm -f "$FILTERED"

TOTAL=${#IDS[@]}
log "过滤后 $TOTAL 条结果（按播放量倒序）"

# --- save cache for subsequent --pick ---
{
  echo "# query: $QUERY"
  for (( i=0; i<TOTAL; i++ )); do
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${IDS[$i]}" "${TITLES[$i]}" "${CHANNELS[$i]}" "${DURATIONS[$i]}" "${VIEWS[$i]}" "${DATES[$i]}"
  done
} > "$CACHE_FILE"

fi  # end of USE_CACHE else branch

# --- formatting helpers ---
format_views() {
  local v="$1"
  if [ "$v" = "NA" ] || [ "$v" = "None" ] || [ -z "$v" ]; then echo "N/A"; return; fi
  v=$(echo "$v" | tr -d ',')
  if [ "$v" -ge 1000000 ] 2>/dev/null; then
    printf "%.1fM" "$(echo "$v / 1000000" | bc -l)"
  elif [ "$v" -ge 1000 ] 2>/dev/null; then
    printf "%.1fK" "$(echo "$v / 1000" | bc -l)"
  else
    echo "$v"
  fi
}

format_date() {
  local d="$1"
  if [ "$d" = "NA" ] || [ -z "$d" ] || [ ${#d} -ne 8 ]; then echo "N/A"; return; fi
  echo "${d:0:4}-${d:4:2}-${d:6:2}"
}

format_duration() {
  local d="$1"
  if [ "$d" = "NA" ] || [ "$d" = "None" ] || [ -z "$d" ]; then echo "N/A"; return; fi
  if [[ "$d" != *:* ]]; then
    echo "0:$(printf '%02d' "$d" 2>/dev/null || echo "$d")"
  else
    echo "$d"
  fi
}

is_archived() {
  grep -qF "youtube $1" "$ARCHIVE" 2>/dev/null
}

video_status() {
  local vid_id="$1"
  local vid_title="$2"
  if is_archived "$vid_id"; then
    if [ -n "${USED_SOURCES:-}" ] && [ -f "$USED_SOURCES" ]; then
      if grep -qF "youtube $vid_id" "$USED_SOURCES" 2>/dev/null; then
        echo "published"
        return
      fi
      local safe_title
      safe_title=$(echo "$vid_title" | sed 's/[^a-zA-Z0-9]/ /g' | tr -s ' ' | head -c 40)
      if sed 's/[^a-zA-Z0-9]/ /g' "$USED_SOURCES" | tr -s ' ' | grep -qiF "$safe_title" 2>/dev/null; then
        echo "published"
        return
      fi
    fi
    echo "downloaded"
  else
    echo "new"
  fi
}

# --- display results ---
echo ""
echo "YouTube 搜索结果: \"$QUERY\" (${TOTAL}条)"
echo "────────────────────────────────────────────────────────────────────────"
printf " %-3s %-50s %-18s %-8s %-8s %-10s\n" "#" "标题" "频道" "时长" "播放量" "上传日期"
echo "────────────────────────────────────────────────────────────────────────"

for (( i=0; i<TOTAL; i++ )); do
  NUM=$((i + 1))
  TITLE="${TITLES[$i]}"
  if [ ${#TITLE} -gt 48 ]; then TITLE="${TITLE:0:45}..."; fi
  CHANNEL="${CHANNELS[$i]}"
  if [ ${#CHANNEL} -gt 16 ]; then CHANNEL="${CHANNEL:0:13}..."; fi
  DUR=$(format_duration "${DURATIONS[$i]}")
  VIEWS_FMT=$(format_views "${VIEWS[$i]}")
  DATE_FMT=$(format_date "${DATES[$i]}")
  MARKER=""
  STATUS=$(video_status "${IDS[$i]}" "${TITLES[$i]}")
  if [ "$STATUS" = "published" ]; then MARKER=" [已发布]"
  elif [ "$STATUS" = "downloaded" ]; then MARKER=" [已下载]"; fi
  printf " %-3s %-50s %-18s %-8s %-8s %-10s%s\n" "$NUM" "$TITLE" "$CHANNEL" "$DUR" "$VIEWS_FMT" "$DATE_FMT" "$MARKER"
done

echo "────────────────────────────────────────────────────────────────────────"

# --- list-only mode ---
if [ "$LIST_ONLY" = "true" ]; then
  echo ""
  echo "SEARCH_RESULTS: $TOTAL"
  echo ""
  echo "YouTube 搜索结果: \"$QUERY\""
  echo ""
  for (( i=0; i<TOTAL; i++ )); do
    NUM=$((i + 1))
    DUR="${DURATIONS[$i]}"
    VIEWS_FMT=$(format_views "${VIEWS[$i]}")
    DATE_FMT=$(format_date "${DATES[$i]}")
    STATUS=$(video_status "${IDS[$i]}" "${TITLES[$i]}")
    MARKER=""
    if [ "$STATUS" = "downloaded" ]; then MARKER=" [已下载]"; fi
    echo "${NUM}. ${TITLES[$i]} — ${CHANNELS[$i]} (${DUR}, ${VIEWS_FMT}播放, ${DATE_FMT})${MARKER}"
  done
  echo ""
  echo "回复编号即可，比如 1,8 。"
  exit 0
fi

# --- pick phase ---
SELECTED_INDICES=()
if [ -n "$PICK" ]; then
  if [ "$PICK" = "all" ]; then
    for (( i=0; i<TOTAL; i++ )); do SELECTED_INDICES+=("$i"); done
  else
    IFS=',' read -ra NUMS <<< "$PICK"
    for NUM in "${NUMS[@]}"; do
      NUM=$(echo "$NUM" | tr -d ' ')
      if [[ "$NUM" =~ ^[0-9]+$ ]] && [ "$NUM" -ge 1 ] && [ "$NUM" -le "$TOTAL" ]; then
        SELECTED_INDICES+=("$((NUM - 1))")
      else
        log "WARNING: 无效序号 $NUM (范围 1-$TOTAL)"
      fi
    done
  fi
else
  if [ ! -t 0 ]; then
    log "ERROR: 非交互模式下必须使用 --pick 参数"
    exit 1
  fi
  RETRY=0
  while [ ${#SELECTED_INDICES[@]} -eq 0 ] && [ $RETRY -lt 3 ]; do
    echo -n "输入序号 (逗号分隔, 如 1,3,5 或 all, q 取消): "
    read -r INPUT
    if [ "$INPUT" = "q" ] || [ "$INPUT" = "Q" ] || [ -z "$INPUT" ]; then
      log "用户取消"; exit 0
    fi
    if [ "$INPUT" = "all" ]; then
      for (( i=0; i<TOTAL; i++ )); do SELECTED_INDICES+=("$i"); done
    else
      IFS=',' read -ra NUMS <<< "$INPUT"
      for NUM in "${NUMS[@]}"; do
        NUM=$(echo "$NUM" | tr -d ' ')
        if [[ "$NUM" =~ ^[0-9]+$ ]] && [ "$NUM" -ge 1 ] && [ "$NUM" -le "$TOTAL" ]; then
          SELECTED_INDICES+=("$((NUM - 1))")
        fi
      done
      if [ ${#SELECTED_INDICES[@]} -eq 0 ]; then
        echo "无效输入，请重试 ($((2 - RETRY)) 次机会)"
      fi
    fi
    RETRY=$((RETRY + 1))
  done
fi

if [ ${#SELECTED_INDICES[@]} -eq 0 ]; then
  log "未选择任何视频"; exit 1
fi

echo ""
log "选中 ${#SELECTED_INDICES[@]} 个视频，开始下载..."

# --- download phase ---
SUB_ARGS=""
if [ "$SUBS_ENABLED" = "true" ]; then
  SUB_ARGS="--write-subs --write-auto-subs --sub-langs $SUBS_LANGS --sub-format $SUBS_FORMAT --convert-subs $SUBS_FORMAT"
fi

DOWNLOADED=0
SKIPPED=0

for IDX in "${SELECTED_INDICES[@]}"; do
  VID_ID="${IDS[$IDX]}"
  VID_TITLE="${TITLES[$IDX]}"
  VID_CHANNEL="${CHANNELS[$IDX]}"

  if is_archived "$VID_ID"; then
    log "  跳过 (已下载): $VID_TITLE"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  log "  下载: $VID_TITLE ($VID_CHANNEL)"

  DIRS_BEFORE=$(ls -1d "$OUTPUT_DIR/search"/*/ 2>/dev/null | sort)

  if yt-dlp \
    --cookies-from-browser "$BROWSER" \
    --download-archive "$ARCHIVE" \
    --format "$QUALITY" \
    --merge-output-format mp4 \
    --embed-chapters \
    --sleep-requests "$SLEEP_REQUESTS" \
    --sleep-interval "${SLEEP_INTERVAL%%-*}" \
    --max-sleep-interval "${SLEEP_INTERVAL##*-}" \
    --throttled-rate 100K \
    --limit-rate "$LIMIT_RATE" \
    --replace-in-metadata "title" "[^\x00-\x7F一-鿿　-〿＀-￯]" "" \
    --replace-in-metadata "title" "['\"\`!@#\$%^&*(){}\\|;:<>?]" "" \
    $SUB_ARGS \
    --output "$OUTPUT_DIR/search/%(upload_date>%Y-%m-%d)s-%(title)s/video.%(ext)s" \
    --no-overwrites \
    --ignore-errors \
    "https://www.youtube.com/watch?v=$VID_ID" \
    >> "$LOG_FILE" 2> >(tee -a "$LOG_FILE" >&2); then

    DIRS_AFTER=$(ls -1d "$OUTPUT_DIR/search"/*/ 2>/dev/null | sort)
    DL_DIR=$(comm -13 <(echo "$DIRS_BEFORE") <(echo "$DIRS_AFTER") | head -1)
    DL_DIR="${DL_DIR%/}"

    if [ -n "$DL_DIR" ] && [ -d "$DL_DIR" ]; then
      python3 -c "
import json, sys
meta = {'channel': sys.argv[1], 'query': sys.argv[2], 'source': 'search', 'videoId': sys.argv[4]}
with open(sys.argv[3], 'w') as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
" "$VID_CHANNEL" "$QUERY" "$DL_DIR/video.search.json" "$VID_ID"
      printf '%s' "$VID_ID" > "$DL_DIR/video.id"
      log "  完成: $DL_DIR"
      echo "SEARCH_DIR: $DL_DIR"
      DOWNLOADED=$((DOWNLOADED + 1))
    else
      log "  警告: 下载成功但未找到目录"
    fi
  else
    log "  失败: yt-dlp 返回错误 (详见 $LOG_FILE)"
  fi

  if [ $((DOWNLOADED + SKIPPED)) -lt ${#SELECTED_INDICES[@]} ]; then
    sleep 3
  fi
done

echo ""
echo "SEARCH_RESULTS: $TOTAL"
echo "SEARCH_PICKED: ${#SELECTED_INDICES[@]}"
echo "SEARCH_DOWNLOADED: $DOWNLOADED"
echo "SEARCH_SKIPPED: $SKIPPED"
log "=== Search completed: $DOWNLOADED downloaded, $SKIPPED skipped ==="
