# Demo script

**Full demo plan (narration, timings, who speaks):** _TBD: link to the team's demo plan_.

This page only fixes the **order of screens**, so the video follows the app and every requirement is shown once.
Use a lecture that is already processed (the CI lecture) so nothing waits on the free tier during recording, and
upload a short clip live only to show the pipeline.

## Before recording

- Start the app: `docker compose up -d` (or the dev servers) and Ollama with `study-buddy-qwen` and `study-buddy-qwen-base`.
- Log in with the demo account; check that the CI lecture is `ready` and the LLMOps page shows the evaluation runs.
- Ask one question with the fine-tuned model beforehand, so the model is loaded and the first answer isn't slowed down.

## Screen order

| # | Screen | What to show | Requirement |
|---|---|---|---|
| 1 | Login / Register | Account creation and login | R9 |
| 2 | Dashboard | KPI cards, recent lectures, weak topics, score trend | R9 |
| 3 | Upload → Processing | Drag-and-drop a short clip; the stage stepper (extracting audio → transcribing → indexing → generating) | R1, R4 |
| 4 | Transcript | Timestamped segments, search, click a timestamp to play that moment, TXT/SRT/VTT download | R1, R2 |
| 5 | Summary & Notes | Summary, takeaways, definitions glossary, topic notes with times, Markdown export | R2 |
| 6 | Quiz | Setup (types, difficulty) → answer → results with explanations, "jump to timestamp", weak topics | R2 |
| 7 | Flashcards | Flip with the keyboard, knew / didn't know, Leitner boxes, due today | R2 |
| 8 | Ask (chat) | An on-topic question with source chips; a follow-up; an off-topic question refused ("not in lecture"); the same question with the **fine-tuned** and **base** models | R2, R8 |
| 9 | Analytics | Mastery by topic, quiz history | R9 |
| 10 | LLMOps | KPI cards, latency by task and generator, tokens and cost, errors, model registry with Ollama digests, golden-set results (cloud vs fine-tuned vs base), SciQ offline runs | R7, R8 |
| 11 | Swagger `/docs` | Endpoint list, one request with the error envelope | R6 |
| 12 | Terminal | `docker compose ps` (all services healthy) | R4 |
| 13 | Architecture diagram | `docs/images/architecture.png` to close | R5 |

The Mind map tab is a "planned" placeholder (Phase 9 was not built); leave it out of the video or say so.
