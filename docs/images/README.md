# Images for the README and the report

The README, `docs/architecture.md` and the report generator (`docs/report/build_report.js`) use these files by
name. The report shows a labelled placeholder for any file that is missing. After adding one, rebuild the report:
`cd docs/report && npm install && npm run build` (same commands in PowerShell, macOS and Linux).

Browser screenshots were cropped to remove the browser's address and bookmarks bars.

| File | What it shows | Status |
|---|---|---|
| `architecture.png` | System architecture, exported from the team's design canvas | present |
| `dashboard.png` | Dashboard: KPI cards, recent lectures, score trend, weak topics | present |
| `processing.png` | Processing page: the stage stepper after a lecture finished | present |
| `transcript.png` | Transcript tab: segments with timestamps, search, play and downloads | present |
| `notes.png` | Summary & Notes tab: summary, takeaways, definitions, a topic | present |
| `quiz_setup.png` | Quiz setup: types, difficulty, topics | present |
| `quiz.png` | Quiz results: score, topic mastery, explanations, timestamps | present |
| `flashcards.png` | Flashcard review (answer side) | present |
| `ask.png` | Ask tab: grounded answer with a source chip | present |
| `ask_refusal.png` | Ask tab: "not in lecture" refusal and the model switch | present |
| `ask_models.png` | Ask tab: an answer from the fine-tuned model | present |
| `llmops.png` | LLMOps: KPI cards and latency chart | present |
| `llmops_eval.png` | LLMOps: transcription speed, prompt versions, evaluation runs | present |
| `docker_ps.png` | Terminal: `docker compose ps`, every service healthy | present |
| `docker_desktop.png` | Docker Desktop: the compose project | present |
| `colab_notebook.png` | The Colab training notebook and GPU check | present |
| `analytics.png` | Analytics page: mastery by topic and quiz history | **missing** |
| `swagger.png` | Swagger UI at `/docs` | **missing** |
| `upload.png` | Upload page with a file selected (optional; used only if added to the README) | optional |

The training screenshot used for the reconstructed training time stays in `docs/screenshots/training_progress.png`.
