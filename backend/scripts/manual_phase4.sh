#!/usr/bin/env bash
# Phase 4 manual test (macOS / Linux / Git Bash): upload a real recording and fetch its transcript.
#
# Start the API first (cd backend && uvicorn app.main:app --reload), then from backend/:
#   bash scripts/manual_phase4.sh                         # uses ../media-files/Scalable_recording.mp3
#   bash scripts/manual_phase4.sh /path/to/lecture.mp4
#
# Needs curl and python3 (for JSON parsing). Uses your real ASR provider (Groq free tier by default).
set -euo pipefail

FILE="${1:-$(dirname "$0")/../../media-files/Scalable_recording.mp3}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${EMAIL:-manual-test@example.com}"
PASSWORD="${PASSWORD:-manual-test-password}"
OUT_DIR="$(dirname "$0")/../../storage/manual-test"
PY="$(command -v python3 || command -v python)"
mkdir -p "$OUT_DIR"
[ -f "$FILE" ] || { echo "File not found: $FILE" >&2; exit 1; }

json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# 1. Account: register (409 = already exists is fine), then log in.
CRED="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/auth/register" -H 'Content-Type: application/json' -d "$CRED")
[ "$code" = "201" ] && echo "Registered $EMAIL" || echo "Account $EMAIL exists (HTTP $code); logging in"
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "$CRED" | json 'd["access_token"]')
AUTH="Authorization: Bearer $TOKEN"

# 2. Upload.
echo "Uploading $FILE ..."
UPLOAD=$(curl -s -S -X POST "$BASE_URL/api/lectures/upload" -H "$AUTH" -F "file=@$FILE")
ID=$(echo "$UPLOAD" | json 'd.get("lecture_id","")')
[ -n "$ID" ] || { echo "Upload failed: $UPLOAD" >&2; exit 1; }
echo "Lecture $ID accepted"

# 3. Poll status every 3 s.
START=$(date +%s)
while true; do
  sleep 3
  ST=$(curl -s "$BASE_URL/api/lectures/$ID/status" -H "$AUTH")
  STATUS=$(echo "$ST" | json 'd["status"]')
  echo "[$(( $(date +%s) - START ))s] $(echo "$ST" | json 'f"{d[\"status\"]:<16} {d[\"progress\"]:>3}%  {d[\"stage_detail\"] or \"\"}"')"
  case "$STATUS" in transcribed|ready) break ;; failed) echo "Pipeline failed: $(echo "$ST" | json 'd["error"]')" >&2; exit 1 ;; esac
done

# 4. Transcript + downloads.
curl -s "$BASE_URL/api/lectures/$ID/transcript" -H "$AUTH" | json '"Language: %s  Duration: %s s  Segments: %d\n" % (d["language"], d["duration_sec"], len(d["segments"])) + "\n".join("  [%8.2f - %8.2f] %s" % (s["start"], s["end"], s["text"]) for s in d["segments"][:5])'
for fmt in txt srt vtt; do
  curl -s "$BASE_URL/api/lectures/$ID/transcript/download?format=$fmt" -H "$AUTH" -o "$OUT_DIR/$ID.$fmt"
  echo "Saved $OUT_DIR/$ID.$fmt"
done
echo "Open the .srt in VLC next to the media file to check the timing."
echo "Delete the lecture when done:  curl -X DELETE $BASE_URL/api/lectures/$ID -H 'Authorization: Bearer <token>'"
