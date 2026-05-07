#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$SKILL_DIR/config.json"
SCRIPTS="$SKILL_DIR/scripts"
OUTPUT_DIR=$(python3 -c "import json,os; c=json.load(open(os.path.expanduser('$CONFIG'))); print(os.path.expanduser(c['outputDir']))")

# --- parse args ---
NOVEL_NAME=""
SOURCE_PATH=""
EPISODE=""
COMPOSE_ONLY=false
PUBLISH=false
INIT=false
AUTHOR=""
COVER=""
MAX_EPISODES=5

USAGE="Usage: $0 --novel \"书名\" [--source path.txt] [--episode N] [--compose-only] [--publish] [--init --author \"作者\" [--cover path]] [--max-episodes N]"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --novel) NOVEL_NAME="$2"; shift 2 ;;
    --source) SOURCE_PATH="$2"; shift 2 ;;
    --episode) EPISODE="$2"; shift 2 ;;
    --compose-only) COMPOSE_ONLY=true; shift ;;
    --publish) PUBLISH=true; shift ;;
    --init) INIT=true; shift ;;
    --author) AUTHOR="$2"; shift 2 ;;
    --cover) COVER="$2"; shift 2 ;;
    --max-episodes) MAX_EPISODES="$2"; shift 2 ;;
    *) echo "$USAGE"; exit 1 ;;
  esac
done

if [ -z "$NOVEL_NAME" ]; then
  echo "$USAGE"
  exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# --- Init mode (no lock needed) ---
if [ "$INIT" = true ]; then
  # Auto-extract from Apple Books if no source provided and txt doesn't exist
  AUTO_SOURCE="$OUTPUT_DIR/sources/${NOVEL_NAME}.txt"
  if [ -z "$SOURCE_PATH" ] && [ ! -f "$AUTO_SOURCE" ]; then
    log "Auto-extracting from Apple Books: $NOVEL_NAME"
    python3 "$SCRIPTS/extract-book.py" "$NOVEL_NAME" --output-dir "$OUTPUT_DIR/sources"
    if [ $? -ne 0 ]; then
      log "ERROR: Auto-extraction failed. Provide --source manually or add epub to Apple Books."
      exit 1
    fi
  fi

  INIT_ARGS=(--novel "$NOVEL_NAME" --author "${AUTHOR:-unknown}")
  if [ -n "$SOURCE_PATH" ]; then
    INIT_ARGS+=(--source "$SOURCE_PATH")
  else
    INIT_ARGS+=(--source "$AUTO_SOURCE")
  fi
  # Auto-detect cover from extraction output
  if [ -n "$COVER" ]; then
    INIT_ARGS+=(--cover "$COVER")
  elif [ -f "$OUTPUT_DIR/sources/${NOVEL_NAME}-cover.jpg" ]; then
    INIT_ARGS+=(--cover "$OUTPUT_DIR/sources/${NOVEL_NAME}-cover.jpg")
  fi
  python3 "$SCRIPTS/init-novel.py" "${INIT_ARGS[@]}"
  log "=== Init COMPLETE ==="
  exit 0
fi

# --- lock guard ---
LOCK_DIR="${TMPDIR:-/tmp}/audiobook-creator.lock.d"
mkdir -p "$(dirname "$LOCK_DIR")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  LOCK_PID=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    log "ERROR: Another pipeline is running (PID $LOCK_PID). Exiting."
    exit 1
  fi
  log "WARNING: Stale lock found, removing."
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || { log "ERROR: Cannot acquire lock."; exit 1; }
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

log "=== Novel Pipeline: $NOVEL_NAME ==="

# --- Publish-only mode ---
if [ "$PUBLISH" = true ]; then
  PUBLISH_ARGS=(--novel "$NOVEL_NAME" --max 3)
  if [ -n "$EPISODE" ]; then
    PUBLISH_ARGS+=(--episode "$EPISODE")
  else
    PUBLISH_ARGS+=(--all)
  fi
  log "Publishing..."
  python3 "$SCRIPTS/publish-novel.py" "${PUBLISH_ARGS[@]}"
  log "=== Publish COMPLETE ==="
  exit 0
fi

# --- Compose-only requires --episode ---
if [ "$COMPOSE_ONLY" = true ] && [ -z "$EPISODE" ]; then
  log "ERROR: --compose-only requires --episode N (to prevent full re-encode timeout)"
  exit 1
fi

# --- Step 1: Split (if no episode outlines exist) ---
if [ "$COMPOSE_ONLY" = false ]; then
  # Determine source file
  if [ -z "$SOURCE_PATH" ]; then
    SOURCE_PATH="$OUTPUT_DIR/sources/${NOVEL_NAME}.txt"
  fi
  # Expand ~ in SOURCE_PATH
  SOURCE_PATH="${SOURCE_PATH/#\~/$HOME}"

  if [ ! -f "$SOURCE_PATH" ]; then
    log "Source not found, auto-extracting from Apple Books..."
    python3 "$SCRIPTS/extract-book.py" "$NOVEL_NAME" --output-dir "$OUTPUT_DIR/sources"
    if [ ! -f "$SOURCE_PATH" ]; then
      log "ERROR: Source file not found and auto-extraction failed: $SOURCE_PATH"
      exit 1
    fi
  fi

  # Check if split is needed
  DRAFTS_DIR="$OUTPUT_DIR/drafts"
  FIRST_OUTLINE="$DRAFTS_DIR/${NOVEL_NAME}-EP01/outline.json"

  if [ ! -f "$FIRST_OUTLINE" ]; then
    log "Step 1: Splitting novel into episodes..."
    python3 "$SCRIPTS/split-novel.py" "$SOURCE_PATH" --novel-name "$NOVEL_NAME"
  else
    log "Step 1: Outlines already exist, skipping split."
  fi
fi

# --- Determine which episodes to process ---
DRAFTS_DIR="$OUTPUT_DIR/drafts"
if [ -n "$EPISODE" ]; then
  EP_DIRS=("$DRAFTS_DIR/${NOVEL_NAME}-EP$(printf '%02d' "$EPISODE")")
else
  EP_DIRS=()
  for d in "$DRAFTS_DIR/${NOVEL_NAME}"-EP*/; do
    [ -d "$d" ] && EP_DIRS+=("${d%/}")
  done
fi

if [ ${#EP_DIRS[@]} -eq 0 ]; then
  log "ERROR: No episode directories found."
  exit 1
fi

# Apply max-episodes limit
if [ ${#EP_DIRS[@]} -gt "$MAX_EPISODES" ]; then
  log "Limiting to $MAX_EPISODES episodes (of ${#EP_DIRS[@]} total). Use --max-episodes to adjust."
  EP_DIRS=("${EP_DIRS[@]:0:$MAX_EPISODES}")
fi

# --- Helper: ensure cover exists in episode directory ---
ensure_cover() {
  local ep_dir="$1"
  if [ -f "$ep_dir/cover.jpg" ] || [ -f "$ep_dir/cover.png" ] || [ -f "$ep_dir/cover.jpeg" ] || [ -f "$ep_dir/cover.webp" ]; then
    return 0
  fi
  # Try to copy from sources
  local sources_dir="$OUTPUT_DIR/sources"
  for ext in jpg png jpeg webp; do
    local src="$sources_dir/${NOVEL_NAME}-cover.$ext"
    if [ -f "$src" ]; then
      cp "$src" "$ep_dir/cover.$ext"
      log "  Cover copied from sources: cover.$ext"
      return 0
    fi
  done
  log "  WARNING: No cover found in sources for $NOVEL_NAME"
  return 1
}

PROCESSED=0
for EP_DIR in "${EP_DIRS[@]}"; do
  EP_NAME=$(basename "$EP_DIR")
  log "--- Processing: $EP_NAME ---"

  if [ "$COMPOSE_ONLY" = true ]; then
    log "Step: Compose only mode"
    ensure_cover "$EP_DIR"
    python3 "$SCRIPTS/compose-video.py" "$EP_DIR"
    continue
  fi

  # Step 2: Generate narration
  if [ ! -f "$EP_DIR/narration.md" ]; then
    log "Step 2: Generating narration..."
    python3 "$SCRIPTS/generate-narration.py" "$EP_DIR"
  else
    log "Step 2: narration.md exists, skipping."
  fi

  # Ensure cover is in EP directory before compose
  ensure_cover "$EP_DIR"

  # Step 3: TTS
  if [ ! -f "$EP_DIR/narration.mp3" ] || [ ! -f "$EP_DIR/narration.srt" ]; then
    log "Step 3: Rendering TTS..."
    python3 "$SCRIPTS/render-tts.py" "$EP_DIR"
  else
    log "Step 3: narration.mp3 + srt exist, skipping."
  fi

  # Step 4: Compose video
  if [ ! -f "$EP_DIR/final.mp4" ] || [ "$(stat -f%z "$EP_DIR/final.mp4" 2>/dev/null || echo 0)" -lt 10000000 ]; then
    log "Step 4: Composing video..."
    python3 "$SCRIPTS/compose-video.py" "$EP_DIR"
  else
    log "Step 4: final.mp4 exists (>10MB), skipping."
  fi

  log "--- Done: $EP_NAME ---"
  PROCESSED=$((PROCESSED + 1))
done

log "=== Novel Pipeline: COMPLETE ($PROCESSED episodes processed) ==="
