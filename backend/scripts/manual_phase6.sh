#!/usr/bin/env bash
# Phase 6 manual test (macOS / Linux / Git Bash): quiz generation, grading, mastery and flashcards
# on a lecture that already has its summary/notes (run manual_phase5.sh first).
#
# Start the API first (cd backend && uvicorn app.main:app --reload), then from backend/:
#   bash scripts/manual_phase6.sh                         # newest "ready" lecture of the test account
#   LECTURE_ID=<id> bash scripts/manual_phase6.sh
#   NUM_QUESTIONS=8 DIFFICULTY=hard TYPES=mcq,short_answer bash scripts/manual_phase6.sh
#   REGENERATE_DECK=true bash scripts/manual_phase6.sh    # replace the flashcard deck
#
# It answers automatically (A for MCQs, true for true/false, a vague text for short answers) to
# show the grading. Needs curl and python3. Uses your Groq free quota; never calls OpenAI unless
# you configure it. Saves the JSON responses to ../storage/manual-test/.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${EMAIL:-manual-test@example.com}"
PASSWORD="${PASSWORD:-manual-test-password}"
ID="${LECTURE_ID:-}"
NUM_QUESTIONS="${NUM_QUESTIONS:-6}"
DIFFICULTY="${DIFFICULTY:-mixed}"
TYPES="${TYPES:-mcq,true_false,short_answer}"
REGENERATE_DECK="${REGENERATE_DECK:-false}"
OUT_DIR="$(dirname "$0")/../../storage/manual-test"
PY="$(command -v python3 || command -v python)"
mkdir -p "$OUT_DIR"
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

CRED="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
curl -s -o /dev/null -X POST "$BASE_URL/api/auth/register" -H 'Content-Type: application/json' -d "$CRED" || true
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' -d "$CRED" | json 'd["access_token"]')
AUTH="Authorization: Bearer $TOKEN"

if [ -z "$ID" ]; then
  ID=$(curl -s "$BASE_URL/api/lectures" -H "$AUTH" | json 'next((x["id"] for x in d if x["status"] == "ready"), "")')
  [ -n "$ID" ] || { echo "No 'ready' lecture for $EMAIL. Run scripts/manual_phase5.sh first." >&2; exit 1; }
fi
echo "Lecture $ID"

TYPES_JSON=$("$PY" -c "import json,sys; print(json.dumps(sys.argv[1].split(',')))" "$TYPES")
curl -s -X POST "$BASE_URL/api/lectures/$ID/generate-quiz" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"num_questions\": $NUM_QUESTIONS, \"types\": $TYPES_JSON, \"difficulty\": \"$DIFFICULTY\"}" \
  --max-time 900 -o "$OUT_DIR/$ID.quiz.json"

ANSWERS=$("$PY" - "$OUT_DIR/$ID.quiz.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if "error" in d:
    sys.exit(f"generate-quiz failed: {d['error']}")
m = d["meta"]
print(f"\n=== QUIZ {d['quiz_id']}: {m['generated']} of {m['requested']} questions, {m['llm_calls']} LLM call(s), "
      f"{m['invalid_items']} invalid item(s) regenerated ===", file=sys.stderr)
if m["invalid_items"]:
    print("Rejected:", m["invalid_reasons"], file=sys.stderr)
answers = {}
for q in d["questions"]:
    print(f"\n[{q['id']}] ({q['type']}, {q['difficulty']}, topic: {q['topic']})\n  {q['question']}", file=sys.stderr)
    for letter, opt in zip("ABCD", q["options"] or []):
        print(f"    {letter}) {opt}", file=sys.stderr)
    answers[q["id"]] = {"mcq": "A", "true_false": True}.get(
        q["type"], "I think it is about the main idea of this part of the lecture.")
print(json.dumps({"answers": answers}))
PY
)
QUIZ_ID=$(json 'd["quiz_id"]' < "$OUT_DIR/$ID.quiz.json")

curl -s -X POST "$BASE_URL/api/quizzes/$QUIZ_ID/submit" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "$ANSWERS" --max-time 300 -o "$OUT_DIR/$ID.quiz-result.json"
"$PY" - "$OUT_DIR/$ID.quiz-result.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if "error" in d:
    sys.exit(f"submit failed: {d['error']}")
mm = lambda s: "--:--" if s is None else f"{int(s // 60):02d}:{int(s % 60):02d}"
print(f"\n=== RESULT: {d['score']:g} / {d['total']} ({d['percent']}%), suggested next difficulty: "
      f"{d['suggested_next_difficulty']} ===")
for r in d["results"]:
    mark = "OK   " if r["correct"] else "WRONG"
    print(f"  {mark} {r['id']} [{mm(r['timestamp'])}] you: {r['your_answer']} | correct: {r['correct_answer']} "
          f"| graded by {r['graded_by']}\n       {r['explanation']}")
    if r["feedback"]:
        print(f"       feedback: {r['feedback']}")
print("\nTopic mastery:")
for t in d["topics"]:
    print(f"  {t['topic']:<45} {t['correct']:g}/{t['total']} correct  mastery {t['mastery']:.2f}")
print("Weak topics:", "; ".join(d["weak_topics"]) or "(none)")
PY

curl -s -X POST "$BASE_URL/api/lectures/$ID/flashcards" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"regenerate\": $REGENERATE_DECK}" --max-time 900 -o "$OUT_DIR/$ID.flashcards.json"
CARD_ID=$("$PY" - "$OUT_DIR/$ID.flashcards.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if "error" in d:
    sys.exit(f"flashcards failed: {d['error']}")
mm = lambda s: "--:--" if s is None else f"{int(s // 60):02d}:{int(s % 60):02d}"
defs = sum(c["kind"] == "definition" for c in d["cards"])
print(f"\n=== FLASHCARDS: {d['total']} cards ({defs} definition, {d['total'] - defs} concept), cached={d['cached']} ===",
      file=sys.stderr)
for c in d["cards"][:8]:
    print(f"  [{mm(c['timestamp'])}] ({c['kind']}) {c['front']}\n         -> {c['back']}", file=sys.stderr)
print(d["cards"][0]["id"] if d["cards"] else "")
PY
)
if [ -n "$CARD_ID" ]; then
  curl -s -X POST "$BASE_URL/api/flashcards/$CARD_ID/review" -H "$AUTH" -H 'Content-Type: application/json' \
    -d '{"knew": true}' | json '"\nReviewed the first card as known: now box " + str(d["box"]) + ", next due " + d["due_at"]'
  curl -s "$BASE_URL/api/lectures/$ID/flashcards?due=true" -H "$AUTH" | json '"Cards due now: " + str(d["total"])'
fi
echo "Saved $OUT_DIR/$ID.quiz.json, .quiz-result.json and .flashcards.json"
