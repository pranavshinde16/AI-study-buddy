#!/usr/bin/env bash
# Phase 7 manual test (macOS / Linux / Git Bash): grounded Q&A (/ask), refusals, chat with a
# follow-up (/chat), chat history, the generator list (/models) and the fine-tuned switch.
#
# Start the API first (cd backend && uvicorn app.main:app --reload), then from backend/:
#   bash scripts/manual_phase7.sh
#   LECTURE_ID=<id> QUESTION="..." FOLLOW_UP="..." OFF_TOPIC="..." bash scripts/manual_phase7.sh
#
# Defaults fit the demo lecture (serverless computing). Needs curl and python3. Uses your Groq
# free quota. "finetuned" is expected to return 503 MODEL_UNAVAILABLE until Ollama is set up (Phase 10).
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${EMAIL:-manual-test@example.com}"
PASSWORD="${PASSWORD:-manual-test-password}"
ID="${LECTURE_ID:-}"
QUESTION="${QUESTION:-What are the two types of serverless architecture?}"
FOLLOW_UP="${FOLLOW_UP:-Can you give an example of the first one?}"
OFF_TOPIC="${OFF_TOPIC:-Who won the 2022 FIFA World Cup?}"
NEAR_TOPIC="${NEAR_TOPIC:-What is the difference between TCP and UDP?}"
OUT_DIR="$(dirname "$0")/../../storage/manual-test"
PY="$(command -v python3 || command -v python)"
mkdir -p "$OUT_DIR"
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
body() { "$PY" -c "import json,sys; print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2]))))" "$@"; }
show() {  # $1 = label, stdin = response JSON
  local f
  f=$(mktemp)
  cat > "$f"
  "$PY" - "$1" "$f" <<'PY'
import json, sys
label, path = sys.argv[1], sys.argv[2]
d = json.load(open(path, encoding="utf-8"))
print(f"\n=== {label} ===")
if "error" in d:
    print(f"{d['error']['code']}: {d['error']['message']}")
    sys.exit(0)
m = d["meta"]
mm = lambda s: f"{int(s // 60):02d}:{int(s % 60):02d}"
print(f"answerable={d['answerable']}  refusal={m['refusal_reason']}  top_score={m['top_score']}  "
      f"min_score={m['min_score']}  generator={m['generator']}  {m['latency_ms']:.0f} ms")
if m.get("rewritten_question"):
    print("rewritten:", m["rewritten_question"])
print(d["answer"])
for s in d["sources"]:
    print(f"  {s['chunk_id']} [{mm(s['start'])} - {mm(s['end'])}] score {s['score']:.3f} "
          f"cited={s['cited']}  {s['excerpt'][:90]}")
PY
  rm -f "$f"
}

CRED="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
curl -s -o /dev/null -X POST "$BASE_URL/api/auth/register" -H 'Content-Type: application/json' -d "$CRED" || true
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "$CRED" | json 'd["access_token"]')
AUTH="Authorization: Bearer $TOKEN"
if [ -z "$ID" ]; then
  ID=$(curl -s "$BASE_URL/api/lectures" -H "$AUTH" | json 'next((x["id"] for x in d if x["status"] == "ready"), "")')
  [ -n "$ID" ] || { echo "No 'ready' lecture for $EMAIL. Run scripts/manual_phase5.sh first." >&2; exit 1; }
fi
echo "Lecture $ID"
curl -s "$BASE_URL/api/models" -H "$AUTH" | json '"Generators: " + ", ".join(g["name"] + " (" + g["provider"] + "/" + g["model"] + ")" for g in d)'

for pair in "ON-TOPIC|$QUESTION" "OFF-TOPIC|$OFF_TOPIC" "NEAR-TOPIC (not in the lecture)|$NEAR_TOPIC"; do
  label="${pair%%|*}"; q="${pair#*|}"
  curl -s -X POST "$BASE_URL/api/lectures/$ID/ask" -H "$AUTH" -H 'Content-Type: application/json' \
    -d "$(body question "$q" model cloud)" --max-time 600 | show "$label: $q"
done

C1=$(curl -s -X POST "$BASE_URL/api/lectures/$ID/chat" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "$(body message "$QUESTION")" --max-time 600)
echo "$C1" | show "CHAT 1: $QUESTION"
SID=$(echo "$C1" | json 'd["session_id"]')
curl -s -X POST "$BASE_URL/api/lectures/$ID/chat" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "$(body message "$FOLLOW_UP" session_id "$SID")" --max-time 600 | tee "$OUT_DIR/$ID.chat.json" | show "CHAT 2 (follow-up): $FOLLOW_UP"
curl -s "$BASE_URL/api/lectures/$ID/chat/$SID" -H "$AUTH" | json '"\nHistory: " + str(len(d["messages"])) + " messages (" + ", ".join(m["role"] for m in d["messages"]) + ")"'

curl -s -X POST "$BASE_URL/api/lectures/$ID/ask" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "$(body question "$QUESTION" model finetuned)" --max-time 120 | show "FINETUNED"
echo "Check: each answer matches the lecture, the cited times point to where it is said, and off-topic questions are refused."
