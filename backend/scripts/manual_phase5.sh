#!/usr/bin/env bash
# Phase 5 manual test (macOS / Linux / Git Bash): summary, topic notes and caching on a real lecture.
#
# Start the API first (cd backend && uvicorn app.main:app --reload), then from backend/:
#   bash scripts/manual_phase5.sh                          # uploads ../media-files/Scalable_recording.mp3
#   bash scripts/manual_phase5.sh /path/to/lecture.mp4
#   LECTURE_ID=<id> bash scripts/manual_phase5.sh          # reuse an uploaded lecture
#   LECTURE_ID=<id> REGENERATE=true bash scripts/manual_phase5.sh
#
# Needs curl and python3. Uses your Groq free quota; never calls OpenAI unless you configure it.
set -euo pipefail

FILE="${1:-$(dirname "$0")/../../media-files/Scalable_recording.mp3}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${EMAIL:-manual-test@example.com}"
PASSWORD="${PASSWORD:-manual-test-password}"
REGENERATE="${REGENERATE:-false}"
ID="${LECTURE_ID:-}"
OUT_DIR="$(dirname "$0")/../../storage/manual-test"
PY="$(command -v python3 || command -v python)"
mkdir -p "$OUT_DIR"
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

CRED="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
curl -s -o /dev/null -X POST "$BASE_URL/api/auth/register" -H 'Content-Type: application/json' -d "$CRED" || true
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "$CRED" | json 'd["access_token"]')
AUTH="Authorization: Bearer $TOKEN"

if [ -z "$ID" ]; then
  [ -f "$FILE" ] || { echo "File not found: $FILE" >&2; exit 1; }
  echo "Uploading $FILE ..."
  ID=$(curl -s -S -X POST "$BASE_URL/api/lectures/upload" -H "$AUTH" -F "file=@$FILE" | json 'd["lecture_id"]')
fi
echo "Lecture $ID"

START=$(date +%s)
while true; do
  ST=$(curl -s "$BASE_URL/api/lectures/$ID/status" -H "$AUTH")
  STATUS=$(echo "$ST" | json 'd["status"]')
  echo "[$(( $(date +%s) - START ))s] $(echo "$ST" | json 'd["status"] + " " + str(d["progress"]) + "%  " + (d["stage_detail"] or "")')"
  case "$STATUS" in
    ready) break ;;
    failed) echo "Pipeline failed: $(echo "$ST" | json 'd["error"]')" >&2; exit 1 ;;
    transcribed)
      sleep 3
      [ "$(curl -s "$BASE_URL/api/lectures/$ID/status" -H "$AUTH" | json 'd["status"]')" = "transcribed" ] && break
      continue ;;
  esac
  sleep 3
done

t0=$("$PY" -c 'import time; print(time.time())')
curl -s -X POST "$BASE_URL/api/lectures/$ID/summarize" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"regenerate\": $REGENERATE}" --max-time 900 -o "$OUT_DIR/$ID.summary.json"
t1=$("$PY" -c 'import time; print(time.time())')
CACHED=$(curl -s -X POST "$BASE_URL/api/lectures/$ID/summarize" -H "$AUTH" | json 'd["cached"]')
t2=$("$PY" -c 'import time; print(time.time())')

"$PY" - "$OUT_DIR/$ID.summary.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if "error" in d:
    sys.exit(f"summarize failed: {d['error']}")
mm = lambda s: "--:--" if s is None else f"{int(s // 60):02d}:{int(s % 60):02d}"
m = d["meta"]
print(f"\n=== SUMMARY ({m['mode']}, {m['windows']} window(s), {m['llm_calls']} LLM calls, model {m['model']}) ===")
print(d["summary"])
print("\n=== KEY TAKEAWAYS ===")
for k in d["key_takeaways"]:
    print("  -", k)
print("\n=== DEFINITIONS ===")
for x in d["definitions"]:
    print(f"  [{mm(x['timestamp'])}] {x['term']}: {x['definition']}")
print("\n=== TOPICS ===")
for t in d["topics"]:
    print(f"  [{mm(t['start'])} - {mm(t['end'])}] {t['title']}")
PY
"$PY" -c "print(f'\nFirst /summarize call : {$t1 - $t0:.2f} s')"
"$PY" -c "print(f'Second /summarize call: {$t2 - $t1:.2f} s (cached=$CACHED)')"
echo "Saved $OUT_DIR/$ID.summary.json"
