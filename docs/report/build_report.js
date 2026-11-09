// Builds docs/report/AI_Study_Buddy_Report.docx (Phase 13).
//
// Every number in the report is read at build time from a results file or a generated document:
//   finetune/results/*.json            fine-tuning data, training and base-vs-fine-tuned evaluation
//   docs/llmops_results.md             LLMOps metrics and golden-set evaluation (generated from the database)
//   docs/testing.md                    test counts and coverage (copied from real test output)
// Text that explains design decisions comes from the docs in docs/. Images come from docs/images/ and
// docs/screenshots/; a missing image becomes a labelled placeholder, so re-run this script after adding screenshots.
//
//   cd docs/report
//   npm install          (once; installs the pinned "docx" package)
//   npm run build

const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, Footer, HeadingLevel, ImageRun, LevelFormat, PageBreak, PageNumber,
  Packer, Paragraph, ShadingType, Table, TableCell, TableOfContents, TableRow, TextRun, WidthType,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(__dirname, "AI_Study_Buddy_Report.docx");
const RESULTS = path.join(ROOT, "finetune", "results");
const FONT = "Arial";
const CONTENT_WIDTH = 9026; // A4 width 11906 - 2 x 1440 margins (DXA)
const ACCENT = "1F3A68";
const missingImages = [];

// ---------- sources ----------

const readJson = (name) => JSON.parse(fs.readFileSync(path.join(RESULTS, name), "utf8"));
const evalHf = readJson("eval_hf.json");
const evalOllama = readJson("eval_ollama_subset50.json");
const dataStats = readJson("data_stats.json");
const training = readJson("training.json");
const trainTime = readJson("training_time_reconstructed.json");
const mcqSecondary = readJson("mcq_secondary_hf.json");
const outputStats = readJson("output_stats_hf.json");
const llmopsMd = fs.readFileSync(path.join(ROOT, "docs", "llmops_results.md"), "utf8");
const testingMd = fs.readFileSync(path.join(ROOT, "docs", "testing.md"), "utf8");

// The first markdown table after the first line that contains `marker` (and, optionally, after `after`).
function mdTable(md, marker, after) {
  const lines = md.split(/\r?\n/);
  let i = lines.findIndex((l) => l.includes(marker));
  if (i < 0) throw new Error(`marker not found: ${marker}`);
  if (after) {
    const j = lines.slice(i).findIndex((l) => l.includes(after));
    if (j < 0) throw new Error(`marker not found: ${after}`);
    i += j;
  }
  while (i < lines.length && !lines[i].trim().startsWith("|")) i++;
  const rows = [];
  for (; i < lines.length && lines[i].trim().startsWith("|"); i++) {
    const cells = lines[i].trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
    if (cells.every((c) => /^:?-+:?$/.test(c))) continue;
    rows.push(cells);
  }
  return { header: rows[0], rows: rows.slice(1) };
}

// A sentence in the markdown that starts with `prefix` (up to the end of the line).
function mdLine(md, prefix) {
  const line = md.split(/\r?\n/).find((l) => l.startsWith(prefix));
  if (!line) throw new Error(`line not found: ${prefix}`);
  return line;
}

const fmt = (v, nd = 4) => {
  if (v === null || v === undefined) return "n/a";
  if (typeof v !== "number") return String(v);
  if (Math.abs(v) >= 100) return v.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return String(Number(v.toFixed(nd)));
};
const int = (v) => v.toLocaleString("en-US");

// ---------- building blocks ----------

// Inline **bold** and `code` in a string.
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ ...base, text: tok.slice(1, -1), font: "Consolas", size: (base.size || 21) - 2 }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const P = (text, opts = {}) => new Paragraph({ children: runs(text), spacing: { after: 120, line: 276 }, ...opts });
const H1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)], pageBreakBefore: true });
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const H3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
const bullets = (items) => items.map((t) => new Paragraph({ children: runs(t), numbering: { reference: "bullets", level: 0 }, spacing: { after: 60, line: 264 } }));
let listInstance = 0; // each numbered list restarts at 1
const numbered = (items) => { listInstance += 1; const inst = listInstance; return items.map((t) => new Paragraph({ children: runs(t), numbering: { reference: "numbers", level: 0, instance: inst }, spacing: { after: 60, line: 264 } })); };
const source = (text) => new Paragraph({ children: runs(text, { italics: true, size: 18, color: "555555" }), spacing: { before: 60, after: 200 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: "B7C3D4" };
const borders = { top: border, bottom: border, left: border, right: border };

function table(header, rows, widths) {
  const n = header.length;
  const w = widths ? widths.map((x) => Math.round((x / widths.reduce((a, b) => a + b, 0)) * CONTENT_WIDTH)) : Array(n).fill(Math.floor(CONTENT_WIDTH / n));
  const diff = CONTENT_WIDTH - w.reduce((a, b) => a + b, 0);
  w[w.length - 1] += diff;
  const cell = (text, i, head) => new TableCell({
    borders,
    width: { size: w[i], type: WidthType.DXA },
    shading: head ? { fill: "E3EAF4", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: runs(String(text), { size: 18, bold: head || undefined }) })],
  });
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: w,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, i, false)) })),
    ],
  });
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  if (b.toString("ascii", 1, 4) !== "PNG") throw new Error(`not a PNG: ${file}`);
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

let figureNo = 0;
function figure(relPath, caption, whatToCapture, maxWidthPx) {
  figureNo += 1;
  const file = path.join(ROOT, relPath);
  const label = `Figure ${figureNo}: ${caption}`;
  const out = [];
  if (fs.existsSync(file)) {
    const { width, height } = pngSize(file);
    // App screenshots are about 2:1; 500 px wide fits three per page. Diagrams use the full width.
    const maxW = maxWidthPx || (relPath.includes("architecture") ? 620 : 500);
    const maxH = 720;
    const scale = Math.min(maxW / width, maxH / height, 1);
    out.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext: true,
      spacing: { before: 120, after: 60 },
      children: [new ImageRun({ type: "png", data: fs.readFileSync(file), transformation: { width: Math.round(width * scale), height: Math.round(height * scale) }, altText: { title: caption, description: caption, name: path.basename(file) } })],
    }));
  } else {
    missingImages.push(relPath);
    const box = { style: BorderStyle.DASHED, size: 8, color: "8A99B0", space: 8 };
    out.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      keepNext: true,
      border: { top: box, bottom: box, left: box, right: box },
      shading: { fill: "F2F5F9", type: ShadingType.CLEAR, color: "auto" },
      spacing: { before: 200, after: 60 },
      children: [
        new TextRun({ text: "[Image placeholder]", bold: true, color: "5A6B85", break: 2 }),
        new TextRun({ text: `Add ${relPath.replace(/\\/g, "/")}`, color: "5A6B85", break: 1 }),
        new TextRun({ text: whatToCapture || "", italics: true, color: "5A6B85", break: 1 }),
        new TextRun({ text: "", break: 2 }),
      ],
    }));
  }
  out.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: label, italics: true, size: 18 })] }));
  return out;
}

// ---------- numbers from the files ----------

const base = evalHf.models.base;
const ft = evalHf.models.finetuned;
const oBase = evalOllama.models.base;
const oFt = evalOllama.models.finetuned;
const tr = dataStats.splits.train;
const va = dataStats.splits.validation;
const te = dataStats.splits.test;
const evalLoss = training.log_history.filter((h) => h.eval_loss !== undefined);
const evalLossByStep = [...new Map(evalLoss.map((h) => [h.step, h.eval_loss])).entries()];
const lora = training.config.lora;
const tcfg = training.config.train;
const mcqBase = mcqSecondary.models.base;
const mcqFt = mcqSecondary.models.finetuned;

// ---------- content ----------

const children = [];
const add = (...xs) => xs.flat().forEach((x) => children.push(x));

// Title page
add(
  new Paragraph({ spacing: { before: 2400 }, children: [] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "AI Study Buddy", bold: true, size: 56, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200 }, children: [new TextRun({ text: "Turning recorded lectures into grounded study material", size: 30 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120 }, children: [new TextRun({ text: "Technical report", size: 26, color: "555555" })] }),
  new Paragraph({ spacing: { before: 1600 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Course / module: TBD", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Team members: see Chapter 11 (to be completed by the team)", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "November 2026", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 1200 }, children: [new TextRun({ text: "Every measured value in this report is read from a results file or a document generated from the project database when the report is built.", italics: true, size: 18, color: "555555" })] }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ children: [new TextRun({ text: "Contents", bold: true, size: 32, font: FONT, color: ACCENT })], spacing: { after: 200 } }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  P("If the table of contents is empty, right-click it in Word and choose **Update Field**."),
);

// 1 Introduction
add(
  H1("1. Introduction and problem"),
  H2("1.1 Problem"),
  P("University courses are increasingly delivered as recorded lectures. Recordings are long, and turning them into revision material (notes, practice questions, flashcards) is slow manual work. General-purpose chatbots can summarise or answer questions, but they mix in outside knowledge, may invent content, and cannot point the student to the moment in the recording where a topic is explained."),
  H2("1.2 Goal"),
  P("**AI Study Buddy** is a web application that turns a lecture recording into study material that is **grounded in the lecture**: a timestamped transcript, a summary and topic-wise notes, quizzes with explanations, a flashcard deck, and a question-answering chat that answers only from the lecture and says clearly when the lecture does not cover a question. Every timestamp shown to the student comes from the speech-recognition output, never from a language model."),
  H2("1.3 Objectives and constraints"),
  ...bullets([
    "Use two AI categories (speech recognition and natural language processing) across at least five subtasks, each mapped to a suitable model.",
    "Provide a REST API with validation, a uniform error format, logging and interactive documentation.",
    "Measure the system with LLMOps metrics (latency, tokens, cost, errors, retrieval quality, faithfulness, refusal accuracy) and show them on a dashboard.",
    "Fine-tune a small language model on an educational dataset, compare it with its base model, and use it in the app.",
    "Run on **free tiers** by default, with no automatic fallback to a paid provider, and never report a number that no run produced.",
  ]),
  H2("1.4 Scope"),
  P("Phases 1–8 and 10–13 of the project plan were implemented: authentication, upload and processing, transcription, summary and notes, quizzes and grading, flashcards, grounded Q&A and chat, the React frontend, the fine-tuned model, the LLMOps dashboard and evaluation harness, Docker deployment, tests and documentation. **Phase 9** (mind map, adaptive difficulty, study recommendations) was not implemented and is described as future work in Chapter 10."),
);

// 2 Domain, categories, subtasks
add(
  H1("2. Domain, AI categories and subtasks"),
  P("The domain is **higher education**: the input is a recorded lecture (audio or video) and the users are students revising its content. The application combines two AI categories."),
  ...bullets([
    "**Speech Recognition** turns the lecture audio into text with segment timestamps.",
    "**Natural Language Processing** produces summaries, notes, questions, flashcards, grading feedback and grounded answers, and embeds text for search.",
  ]),
  H2("2.1 Subtasks and models"),
  table(["#", "Subtask", "Category", "Model / API", "Feature"], [
    ["1", "Automatic speech recognition", "Speech", "Whisper large-v3-turbo (Groq API)", "Timestamped transcript, media player seek, TXT/SRT/VTT"],
    ["2", "Abstractive summarization", "NLP", "openai/gpt-oss-120b (Groq API)", "Summary, key takeaways, revision notes"],
    ["3", "Question generation", "NLP", "gpt-oss-120b, JSON output", "MCQ, true/false and short-answer quizzes"],
    ["4", "Question answering (RAG)", "NLP", "bge-small + ChromaDB retriever; gpt-oss-120b, fine-tuned or base Qwen3-1.7B generator", "Ask page: grounded answers, sources, refusals, chat"],
    ["5", "Text generation", "NLP", "gpt-oss-120b", "Topic notes, definitions, flashcards, short-answer feedback"],
    ["6", "Semantic embeddings / similarity", "NLP", "BAAI/bge-small-en-v1.5 (local)", "Indexing and retrieval; short-answer grading fallback"],
    ["7", "Information / keyphrase extraction", "NLP", "gpt-oss-120b, JSON output", "Topics with time ranges, glossary terms, topic tags for mastery"],
    ["+", "Domain fine-tuning", "NLP", "Qwen3-1.7B + QLoRA on SciQ (Ollama)", "\"Fine-tuned SLM\" option on the Ask page"],
  ], [4, 18, 9, 30, 39]),
  source("Source: docs/ai_mapping.md. The evaluation judge (qwen/qwen3.8-27b on Groq) is a further NLP use, described in Chapter 7."),
  H2("2.2 Grounding rules"),
  P("Grounding is enforced by the application, not only requested in prompts:"),
  ...numbered([
    "**Timestamps come only from ASR segments.** The model is shown transcript lines as `[segment id] text` and refers to segment ids; the app converts ids to times from the stored segments. Ids outside the given window are clamped, and a definition with an invalid id gets no timestamp.",
    "**Only the transcript is used.** Every prompt forbids outside knowledge; the RAG prompt answers only from numbered chunks and must set `answerable: false` when they do not contain the answer.",
    "**Generated items are checked.** Quiz questions and flashcards that cite a segment outside their batch, or fail any other rule, are discarded and regenerated or dropped.",
    "**Low-similarity questions are refused before any LLM call** (threshold `RAG_MIN_SCORE`).",
  ]),
  H2("2.3 Hugging Face integration"),
  table(["Asset", "Use in the project", "Version / evidence"], [
    ["BAAI/bge-small-en-v1.5 (sentence-transformers)", "Local embedding model for indexing, retrieval and grading fallback", "Revision 5c38ec7c405e… logged in llm_calls"],
    ["allenai/sciq (Datasets)", "Training and test data for the fine-tune", `Revision ${dataStats.dataset_revision.slice(0, 12)}…`],
    ["unsloth/Qwen3-1.7B", "Base model for QLoRA and the \"base\" generator", `Revision ${training.config.base_model_revision.slice(0, 12)}…`],
    ["Transformers, PEFT, TRL, Unsloth, bitsandbytes", "Training stack on Colab", `transformers ${training.versions.transformers}, peft ${training.versions.peft}, trl ${training.versions.trl}, unsloth ${training.versions.unsloth}`],
    ["Hub repo TusharDecoded/study-buddy-qwen3-1.7b-sciq-lora (private)", "LoRA adapter, GGUF q4_k_m and model card", `GGUF ${int(training.exports.gguf_bytes)} bytes`],
  ], [32, 38, 30]),
  source("Sources: docs/ai_mapping.md §2, finetune/results/training.json, finetune/results/data_stats.json."),
);

// 3 Model selection
add(
  H1("3. Model selection"),
  P("Models were chosen on four criteria: measured accuracy where available, cost, free-tier availability and integration effort. The project decision was to run on free tiers by default: Groq serves both speech recognition and the LLM, and OpenAI is used only when explicitly configured."),
  table(["Need", "Chosen", "Alternatives", "Reasons"], [
    ["Speech recognition", "Groq whisper-large-v3-turbo", "local faster-whisper; OpenAI whisper-1 (paid)", "Free, fast, segment timestamps, OpenAI-compatible API"],
    ["LLM", "Groq openai/gpt-oss-120b", "gpt-5-mini (paid); gpt-oss-20b", "Free, JSON output, best quality on the golden set"],
    ["Embeddings", "BAAI/bge-small-en-v1.5", "all-MiniLM-L6-v2; OpenAI text-embedding-3-small", "Free, CPU, 384 dimensions, good retrieval for its size"],
    ["Vector database", "ChromaDB", "FAISS", "Metadata filter by lecture, persistence, no extra server"],
    ["SLM", "Qwen3-1.7B", "Llama-3.2-1B, SmolLM2-1.7B", "Fits QLoRA on a free T4, Apache-2.0, GGUF export"],
    ["Fine-tuning", "Unsloth + TRL + PEFT", "Transformers + PEFT", "Faster, less memory on a T4"],
    ["SLM serving", "Ollama (GGUF q4_k_m)", "Transformers in FastAPI", "Runs on a laptop CPU; OpenAI-compatible API"],
    ["Evaluation judge", "Groq qwen/qwen3.8-27b", "llama-3.3-70b-versatile", "Free; different family from the cloud generator"],
  ], [16, 22, 28, 34]),
  source("Source: docs/model_selection.md."),
  H2("3.1 Measured evidence for the choices"),
  table(["Model", "Measurement", "Value", "Source"], [
    ["whisper-large-v3-turbo", "Transcriptions / pooled real-time factor", mdTable(llmopsMd, "## 1. Overview").rows.find((r) => r[0].startsWith("Transcriptions"))[1], "llmops_results.md §1"],
    ["gpt-oss-120b", "Golden set: faithfulness / correctness / refusal accuracy", (() => { const t = mdTable(llmopsMd, "**Generators**"); const g = (k) => t.rows.find((r) => r[0].startsWith(k))[1]; return `${g("M7 faithfulness")} / ${g("Correctness (answered)")} / ${g("M8 refusal accuracy")}`; })(), "llmops_results.md §8"],
    ["bge-small-en-v1.5", "Golden set: hit@3 / MRR (12 answerable questions)", (() => { const t = mdTable(llmopsMd, "**M6 retrieval"); return `${t.rows[0][2]} / ${t.rows[0][4]}`; })(), "llmops_results.md §8"],
    ["Qwen3-1.7B fine-tuned", "SciQ grounded-QA accuracy, base → fine-tuned (n = 375)", `${base.gqa.accuracy} → ${ft.gqa.accuracy}`, "eval_hf.json"],
    ["All models", "Actual cost over all live traffic", mdTable(llmopsMd, "## 1. Overview").rows.find((r) => r[0].startsWith("Actual cost"))[1], "llmops_results.md §1"],
  ], [20, 40, 20, 20]),
  P("Word error rate of the speech recognition was **not measured** (TBD: no reference transcript was produced); transcripts were checked by hand during the golden-set alignment."),
  H2("3.2 Free-tier limits encountered"),
  table(["Limit", "Effect", "Response"], [
    ["gpt-oss-120b: 8K tokens per minute (30 RPM, 1K requests and 200K tokens per day)", "A long transcript does not fit one request; consecutive calls exceed the per-minute budget", "Single pass only up to 3,500 tokens, map-reduce windows ≤ 2,500 tokens, client-side token pacer"],
    ["Token pacer waits", "Waits of 54.5 s (Phase 5) and 57.3 s (Phase 7) observed; the cloud generator's p95 in the evaluation includes such waits", "Accepted instead of failing with 429; the UI shows a \"waiting for the free-tier rate limit\" notice"],
    ["Whisper: 25 MB per file", "Lecture files are larger", "ffmpeg converts to 16 kHz mono and cuts ≤ 24 MB, 10-minute pieces; timestamps are shifted back"],
    ["Model availability", "llama-3.3-70b-versatile returned 404 during the evaluation", "Judge switched to qwen/qwen3.8-27b; unavailable models return 503 MODEL_UNAVAILABLE"],
    ["Colab free T4", "Limited session time; no native bf16 tensor cores", "fp16, 4-bit QLoRA, one epoch, checkpoints on Google Drive"],
  ], [30, 35, 35]),
  source(`Sources: docs/model_selection.md §3 (limits as published by Groq, checked 2026-11-06), development logs. Rate-limited calls that reached the user: ${mdTable(llmopsMd, "## 6. Errors").rows.reduce((a, r) => a + Number(r[4]), 0)} (llmops_results.md §6).`),
);

// 4 Architecture
add(
  H1("4. Architecture"),
  ...figure("docs/images/architecture.png", "System architecture", "Export from the team's design canvas"),
  P("The system has three runtime parts: a **React single-page app**, a **FastAPI backend** with a background processing pipeline, and external or local **model services** (Groq for speech and the LLM; a local embedding model; Ollama for the fine-tuned and base SLMs). PostgreSQL stores all application data and the LLMOps logs; ChromaDB stores the vectors; uploaded files live in a storage folder or Docker volume."),
  H2("4.1 Backend components"),
  table(["Layer", "Folder", "Responsibility"], [
    ["Routers", "app/api/routers/", "HTTP only: validate input, call a service, shape the response"],
    ["Schemas", "app/schemas/", "Pydantic request and response models (shown in Swagger)"],
    ["Services", "app/services/", "Business logic: lectures, media, ASR, summaries, quizzes, grading, flashcards, chunking, indexing, vector store, RAG, chat, LLMOps, evaluation"],
    ["Model wrappers", "services/llm/client.py, services/asr/client.py, services/embeddings.py", "The only code that calls a model; every request writes an llm_calls row"],
    ["Worker", "app/workers/pipeline.py", "Lecture pipeline run by FastAPI BackgroundTasks"],
    ["Models / migrations", "app/models/, alembic/", "SQLAlchemy 2 tables and Alembic migrations"],
    ["Prompts", "app/prompts/*.yaml", "Versioned prompt templates (id, version)"],
    ["Core", "app/core/", "Settings, error envelope, structlog logging, request ids, JWT and bcrypt"],
  ], [18, 32, 50]),
  H2("4.2 Data flow: processing a lecture"),
  ...numbered([
    "`POST /api/lectures/upload` checks the type and size, stores the file and returns **202** with a status URL.",
    "The background pipeline extracts the audio with ffmpeg (16 kHz mono), cuts it into pieces and transcribes each piece with Whisper (status `extracting_audio` → `transcribing`).",
    "Segment times are shifted by each piece's offset and merged into one timeline (`transcript_segments`).",
    "The transcript is split into retrieval chunks, embedded and stored in ChromaDB (`indexing`).",
    "Topics, notes and the summary are generated from the transcript (`generating` → `ready`).",
    "The frontend polls `GET /status` and opens the lecture workspace when it is ready.",
  ]),
  P("Each stage writes a `pipeline_runs` row; each model request writes an `llm_calls` row. On restart, interrupted lectures are marked failed (or returned to `transcribed` if only generation was interrupted)."),
  H2("4.3 API communication"),
  P("The backend exposes **39 REST operations** under `/api` (OpenAPI 0.1.0), documented in Swagger UI at `/docs` and exported to `docs/openapi.json`. Requests use JSON with a Bearer JWT; uploads use multipart form data. Long work returns 202 and is polled. Generation endpoints are cached and idempotent unless `regenerate: true` is sent. Every error uses one envelope, `{\"error\": {\"code\", \"message\", \"details\"}}`, and each response carries an `X-Request-ID` that matches the server's JSON log lines."),
  source("Sources: docs/architecture.md, docs/api.md, docs/openapi.json."),
  ...figure("docs/images/swagger.png", "Swagger UI at /docs", "Swagger UI with the endpoint list"),
);

// 5 Implementation
add(
  H1("5. Implementation"),
  H2("5.1 Processing pipeline"),
  ...bullets([
    "**Media:** ffprobe reads the duration; ffmpeg converts to 16 kHz mono FLAC and cuts pieces of `ASR_CHUNK_SEC` (600 s) and at most 24 MB, below Groq's 25 MB file limit.",
    "**ASR:** one OpenAI-compatible adapter serves Groq (default) and OpenAI (opt-in) with `verbose_json`, which returns segment start and end times. A provider that returns text without segments is rejected rather than given invented times. Local faster-whisper is an optional offline provider.",
    "**Retries:** on 429 or an outage the client retries the same provider with exponential backoff and honours `Retry-After`; it never switches to a paid provider.",
    "**Status:** `uploaded → extracting_audio → transcribing → indexing → transcribed → generating → ready | failed`, with a progress percentage and a stage detail such as \"chunk 2 of 3\".",
  ]),
  H2("5.2 Summarization and notes"),
  P("A transcript of up to 3,500 estimated tokens is processed in a single pass; a longer one is split into windows of about 600 s and at most 2,500 tokens (map-reduce), which keeps each request within the free tier's 8K tokens per minute. The `topics@v1` prompt returns topics as segment-id ranges with key points and definitions; the app clamps and orders the ranges, closes gaps and looks up the real times. The `notes@v1` prompt then writes notes for each topic from that topic's segments only, and `summary@v1` writes the summary, key takeaways and revision notes. Number of LLM calls per lecture: windows + topics + 1. Every JSON answer is validated with Pydantic; an invalid answer gets one repair request, and a second failure returns `502 LLM_OUTPUT_INVALID`. Results are cached in `lecture_outputs`."),
  H2("5.3 Quizzes, grading and flashcards"),
  ...bullets([
    "**Slots:** the app plans every question (type and difficulty) before calling the model, spreads the slots over transcript batches of at most 2,500 tokens, and takes the difficulty from the slot, not from the model.",
    "**Validation:** each question must fill an open slot, match its type, have four unique options for MCQ with the answer among them, a boolean for true/false, a model answer for short answers, and cite a segment inside its batch. Invalid items are requested again for up to `QUIZ_MAX_REGEN_ROUNDS` (2) extra rounds. MCQ options are shuffled by the app.",
    "**Answers stay hidden** until `POST /quizzes/{id}/submit`.",
    "**Grading:** MCQ and true/false by rule; short answers by one LLM request against the reference answer and key points (`grade_short@v1`); if that fails, by embedding similarity with threshold 0.85. Results record `graded_by`.",
    "**Mastery:** per topic, an exponential moving average (alpha 0.3); topics below 0.6 are weak topics; the next difficulty is suggested from the score.",
    "**Flashcards:** definition cards come from the summary without an LLM call; concept cards from `flashcards@v1`; duplicates are removed; review uses Leitner boxes 1–5 with intervals of 0, 1, 3, 7 and 14 days.",
  ]),
  H2("5.4 Retrieval-augmented question answering"),
  ...bullets([
    "**Indexing:** consecutive transcript segments are grouped into chunks of about 350 words and at most 90 s with about 15 % overlap, so chunk times are real segment times. Chunks are embedded with bge-small (no prefix) and stored in ChromaDB with cosine distance and a `lecture_id` filter.",
    "**Retrieval:** the question is embedded with bge's query prefix; the top 5 chunks are returned with score = 1 − cosine distance.",
    "**Layer 1, threshold:** if the best score is below `RAG_MIN_SCORE` (0.50) the app refuses without calling an LLM (`below_threshold`) and lists the closest timestamps.",
    "**Layer 2, model:** otherwise the chosen generator answers from chunks labelled C1…C5 with `rag_answer@v1` and may still refuse (`not_in_chunks`).",
    "**Citation check:** cited ids that were not provided are removed; sources carry start and end times from the chunks.",
    "**Chat:** a follow-up is first rewritten into a standalone question (`rag_rewrite@v1`) from the last 6 turns, so earlier answers cannot leak unsupported claims.",
    "**Generators:** `cloud` (gpt-oss-120b), `finetuned` and `base` (Ollama) share the same prompt and pipeline, so they can be compared fairly; more can be added through configuration.",
  ]),
  P("**Threshold calibration (Phase 7).** On the first demo lecture, 10 on-topic questions scored 0.580–0.788 and 10 off-topic questions 0.304–0.566. The calibration script proposed 0.573, the midpoint of a gap of only 0.013. The team chose **0.50**, which keeps a margin of 0.08 below the lowest on-topic score and leaves near-domain questions to the model. The Phase 11 re-check is in Section 7.5."),
  source("Sources: docs/summarization.md, docs/quizzes.md, docs/rag.md."),
  H2("5.5 Frontend"),
  P("The frontend is a React 18 + Vite + TypeScript single-page app styled with Tailwind CSS and shadcn/ui. A typed API client mirrors the backend schemas and turns the error envelope into a typed error; TanStack Query handles caching and polling; pages are lazy-loaded with React Router. Pages: Login and Register, Dashboard, Upload, Processing (stage stepper), the lecture workspace with Transcript, Summary & Notes, Quiz, Ask, Flashcards and a Mind map placeholder, Analytics, and LLMOps. No page uses mock data."),
  ...figure("docs/images/dashboard.png", "Dashboard", "KPI cards, recent lectures, weak topics, score trend"),
  ...figure("docs/images/processing.png", "Processing page: the stage stepper, here after every stage has finished", "Processing page"),
  ...figure("docs/images/transcript.png", "Transcript with timestamps, search and media player", "Transcript tab of the CI lecture"),
  ...figure("docs/images/notes.png", "Summary and topic notes", "Summary & Notes tab with a topic opened"),
  ...figure("docs/images/quiz_setup.png", "Quiz setup: question types, difficulty and topics", "Quiz setup panel"),
  ...figure("docs/images/quiz.png", "Quiz results with topic mastery, explanations and timestamps", "Quiz results screen"),
  ...figure("docs/images/flashcards.png", "Flashcard review (answer side) with its timestamp and Leitner box", "A flipped card"),
  ...figure("docs/images/ask.png", "Grounded answer with a timestamped source chip", "Ask tab"),
  ...figure("docs/images/ask_refusal.png", "Refusal below the similarity threshold (no LLM call) and the model switch", "Ask tab with a refusal"),
  ...figure("docs/images/analytics.png", "Analytics: mastery by topic and quiz history", "Analytics page"),
);

// 6 Fine-tuning
add(
  H1("6. Fine-tuning"),
  P("The app's \"finetuned\" answer generator is **Qwen3-1.7B** adapted with QLoRA to the exact task the app gives it: answer a question only from numbered excerpts, reply in JSON (`answerable`, `answer`, `citations`), and refuse when the excerpts do not contain the answer."),
  H2("6.1 Dataset"),
  P(`**SciQ** (\`${dataStats.dataset}\`, CC-BY-NC-3.0) contains crowd-sourced science exam questions, each with a correct answer, three distractors and a support paragraph. The support paragraph makes it possible to train grounded answering and refusal. Rows without a support paragraph were removed; the official splits were used, with seed ${dataStats.seed} and a maximum length of ${dataStats.max_seq_len} tokens.`),
  table(["Split", "Rows", "Dropped (no support)", "Examples used", "Grounded QA / refusal / MCQ", "Tokens mean / p95 / max"], [
    ["train", int(tr.rows), int(tr.dropped_empty_support), int(tr.examples), `${int(tr.by_task.gqa)} / ${tr.by_task.refusal} / ${tr.by_task.mcq}`, `${tr.tokens.mean} / ${tr.tokens.p95} / ${int(tr.tokens.max)}`],
    ["validation", int(va.rows), int(va.dropped_empty_support), int(va.examples), `${va.by_task.gqa} / ${va.by_task.refusal} / ${va.by_task.mcq}`, `${va.tokens.mean} / ${va.tokens.p95} / ${int(va.tokens.max)}`],
    ["test (evaluation only)", int(te.rows), int(te.dropped_empty_support), int(te.examples), `${te.by_task.gqa} / ${te.by_task.refusal} / ${te.by_task.mcq}`, `${te.tokens.mean} / ${te.tokens.p95} / ${int(te.tokens.max)}`],
  ], [18, 10, 16, 14, 22, 20]),
  source("Source: finetune/results/data_stats.json."),
  ...bullets([
    "**Grounded QA:** question + its own support paragraph + 1–2 unrelated paragraphs (shuffled) → correct answer, the support sentence containing it, and a citation.",
    "**Refusal:** question + only unrelated paragraphs → `answerable: false`.",
    "**MCQ generation:** passage → question with the correct answer and SciQ's three distractors as JSON.",
    "Answers and justifications come from SciQ, never from a model. The training prompt is the app's own `rag_answer@v1`; a test fails if the copies drift apart.",
  ]),
  H2("6.2 Method"),
  table(["Setting", "Value"], [
    ["Base model", `${training.config.base_model} @ ${training.config.base_model_revision.slice(0, 12)}…`],
    ["Method", `4-bit QLoRA (Unsloth), r = ${lora.r}, alpha = ${lora.alpha}, dropout ${lora.dropout}`],
    ["Target modules", lora.target_modules.join(", ")],
    ["Epochs / steps", `${tcfg.epochs} / ${training.global_steps}`],
    ["Effective batch size", `${tcfg.effective_batch} (${tcfg.per_device_batch} × ${tcfg.grad_accum} gradient accumulation), optimizer ${tcfg.optim}, seed ${tcfg.seed}`],
    ["Learning rate / schedule", `${tcfg.lr}, ${tcfg.scheduler}, ${tcfg.warmup_steps} warm-up steps`],
    ["Precision / hardware", `${training.config.dtype} / ${training.gpu} (free Colab)`],
    ["Thinking mode", "Off in training, evaluation and serving (embedded in the GGUF chat template)"],
    ["Exports", `LoRA adapter, merged 16-bit, GGUF q4_k_m (${int(training.exports.gguf_bytes)} bytes)`],
  ], [30, 70]),
  source("Source: finetune/results/training.json (config, versions, exports)."),
  ...figure("docs/images/colab_notebook.png", "The Colab training notebook: steps and the GPU check on a Tesla T4", "Colab notebook"),
  H2("6.3 Training"),
  P(`Validation loss fell from ${fmt(evalLossByStep[0][1])} at step ${evalLossByStep[0][0]} to ${fmt(training.final_eval.eval_loss)} at step ${training.global_steps} and was still decreasing slightly at the end, with no sign of overfitting.`),
  table(["Step", ...evalLossByStep.map(([s]) => String(s))], [["Validation loss", ...evalLossByStep.map(([, l]) => fmt(l))]]),
  H3("Reconstructed training time"),
  P(`**Training time ≈ ${trainTime.estimate_min} min (reconstructed; at least ${fmt(trainTime.lower_bound_s / 60, 1)} min).** The notebook's own measurement was lost: after training had finished, the training step was run again in a new Colab session, which resumed from the final checkpoint, trained 0 steps and overwrote the file (train_runtime ${training.train_metrics.train_runtime} s). The weights were not affected. The time was rebuilt from the original run's progress bar, \`${trainTime.sources.progress_bar_screenshot.text}\` (${trainTime.sources.progress_bar_screenshot.elapsed_at_step_180_s} s elapsed at step 180 plus ${trainTime.sources.progress_bar_screenshot.eta_remaining_s} s estimated remaining), plus the logged final evaluation (${trainTime.sources.training_json_log_history.eval_runtime_s_at_step_188} s). The notebook now logs every session so this cannot happen again.`),
  ...figure("docs/screenshots/training_progress.png", "Original training run at step 180 of 188 (source of the reconstructed time)"),
  source("Source: finetune/results/training_time_reconstructed.json."),
  H2("6.4 Results: base vs fine-tuned"),
  P(`Both models were evaluated on the same ${evalHf.n_items} SciQ test items with the same prompts, greedy decoding and at most ${evalHf.decoding.max_new_tokens} new tokens. **Base** is the same 4-bit model with the LoRA adapter switched off; **fine-tuned** has it switched on (${evalHf.gpu}). No generation failed.`),
  table(["Metric", "Base", "Fine-tuned"], [
    [`Grounded-QA accuracy (n = ${base.gqa.n})`, fmt(base.gqa.accuracy), fmt(ft.gqa.accuracy)],
    ["Token F1", fmt(base.gqa.token_f1), fmt(ft.gqa.token_f1)],
    ["ROUGE-L", fmt(base.gqa.rouge_l), fmt(ft.gqa.rouge_l)],
    ["Cites the right excerpt", fmt(base.gqa.gold_citation_rate), fmt(ft.gqa.gold_citation_rate)],
    [`Refusal precision / recall (n = ${base.refusal.n_should_refuse} should refuse)`, `${fmt(base.refusal.precision)} / ${fmt(base.refusal.recall)}`, `${fmt(ft.refusal.precision)} / ${fmt(ft.refusal.recall)}`],
    ["Refusal confusion tp / fp / fn / tn", `${base.refusal.confusion.tp} / ${base.refusal.confusion.fp} / ${base.refusal.confusion.fn} / ${base.refusal.confusion.tn}`, `${ft.refusal.confusion.tp} / ${ft.refusal.confusion.fp} / ${ft.refusal.confusion.fn} / ${ft.refusal.confusion.tn}`],
    ["RAG JSON validity", fmt(base.rag_json_valid_rate), fmt(ft.rag_json_valid_rate)],
    [`MCQ JSON validity (n = ${base.mcq.n})`, fmt(base.mcq.json_valid_rate), fmt(ft.mcq.json_valid_rate)],
    ["MCQ answer matches source (strict)", fmt(base.mcq.answer_matches_source_rate), fmt(ft.mcq.answer_matches_source_rate)],
    ["Latency per answer, GPU, mean / p95 (ms)", `${fmt(base.latency_ms.mean)} / ${fmt(base.latency_ms.p95)}`, `${fmt(ft.latency_ms.mean)} / ${fmt(ft.latency_ms.p95)}`],
    [`Latency through Ollama on CPU, ${oBase.latency_ms.n}-item subset, mean / p95 (ms)`, `${fmt(oBase.latency_ms.mean)} / ${fmt(oBase.latency_ms.p95)}`, `${fmt(oFt.latency_ms.mean)} / ${fmt(oFt.latency_ms.p95)}`],
  ], [50, 25, 25]),
  source("Sources: finetune/results/eval_hf.json and eval_ollama_subset50.json."),
  P(`**Gains.** The fine-tuned model answers in the trained format (answer + support sentence + citation), so token F1 and ROUGE-L more than double. Accuracy rises from ${fmt(base.gqa.accuracy)} to ${fmt(ft.gqa.accuracy)}, and the right excerpt is cited in ${fmt(ft.gqa.gold_citation_rate)} of answers. Refusals become far more precise: the base model wrongly refused ${base.refusal.confusion.fp} answerable questions, the fine-tuned model ${ft.refusal.confusion.fp}.`),
  H2("6.5 Regressions"),
  ...bullets([
    `**MCQ JSON validity ${fmt(base.mcq.json_valid_rate)} → ${fmt(ft.mcq.json_valid_rate)}.** All invalid fine-tuned outputs are valid JSON with four identical options (\`duplicate_options\`), while the base model's failures are broken JSON. Likely cause: MCQ generation was only 10 % of the training mix (${tr.by_task.mcq} examples). The app's quizzes do not use this model.`,
    `**GPU latency, mean ${fmt(base.latency_ms.mean)} → ${fmt(ft.latency_ms.mean)} ms.** Likely cause: the comparison computes the unmerged LoRA adapter at every token. Output length does not explain it: mean answer length rose from ${outputStats.models.base.all.mean_tokens} to ${outputStats.models.finetuned.all.mean_tokens} tokens, but the mean longest output per batch of 8, which sets the batch time, is about the same (${outputStats.models.base.all.mean_batch_max_tokens} vs ${outputStats.models.finetuned.all.mean_batch_max_tokens}). Through Ollama, with the adapter merged, the two models are about 1 % apart (${fmt(oBase.latency_ms.mean)} vs ${fmt(oFt.latency_ms.mean)} ms), which supports this explanation.`,
  ]),
  P("Two looser MCQ checks were added after the first results were seen and re-scored from the saved predictions (secondary only):"),
  table(["Secondary MCQ check (all 50 items)", "Base", "Fine-tuned"], [
    ["Loose match with SciQ's answer", fmt(mcqBase.loose_match_rate), fmt(mcqFt.loose_match_rate)],
    ["Marked option appears word for word in the passage", fmt(mcqBase.answer_in_passage_rate), fmt(mcqFt.answer_in_passage_rate)],
  ], [60, 20, 20]),
  source("Sources: finetune/results/mcq_secondary_hf.json, output_stats_hf.json."),
  H2("6.6 Transfer to lecture text"),
  P("The model was trained on school-level science passages, not lecture transcripts. Transfer was measured on the lecture golden set (Chapter 7):"),
  (() => {
    const t = mdTable(llmopsMd, "**Generators**");
    const pick = ["M7 faithfulness", "Hallucination rate", "Correctness (answered)", "M8 refusal accuracy", "Latency p50 / p95"];
    return table(["Metric (golden set ci_lecture)", "cloud", "finetuned", "base"], pick.map((k) => { const r = t.rows.find((x) => x[0].startsWith(k)); return [r[0], r[1], r[2], r[3]]; }), [34, 22, 22, 22]);
  })(),
  source("Source: docs/llmops_results.md §8 (generated from the database)."),
  P("On lecture text the fine-tuned model stays much closer to the excerpts and refuses more reliably than the base model, but its answers are often incomplete, so its correctness is lower. With 20 questions on one lecture, one question moves a rate by 5 to 8 points."),
  H2("6.7 Serving"),
  P("The merged model was exported to GGUF q4_k_m with a chat template that always disables thinking, loaded into Ollama as `study-buddy-qwen`, and selected in the app by `FINETUNED_MODEL_TAG`. No backend code change was needed: the generator registry points the `finetuned` and `base` generators at Ollama's OpenAI-compatible API. The model registry records the Ollama digest of each model so different builds remain distinguishable."),
  ...figure("docs/images/ask_models.png", "The same question answered by the fine-tuned model through Ollama (generator and latency shown under the answer)", "Ask tab with the finetuned generator"),
);

// 7 LLMOps
const ov = mdTable(llmopsMd, "## 1. Overview");
const ret = mdTable(llmopsMd, "**M6 retrieval");
const thr = mdTable(llmopsMd, "**RAG_MIN_SCORE check**");
const gens = mdTable(llmopsMd, "**Generators**");
const lat = mdTable(llmopsMd, "## 3. M2-M3");
const qa = mdTable(llmopsMd, "## 4. M4");
const exportedLine = mdLine(llmopsMd, "> **Generated by");
add(
  H1("7. LLMOps"),
  P("LLMOps is implemented in the application, not described only. Every request to a model goes through one of three wrappers and writes a row to `llm_calls` (task, provider, model, model version, prompt version, tokens, latency, cost, status, error type). Pipeline stages write `pipeline_runs`; every question writes `qa_logs`; evaluation runs write `eval_runs` and `eval_items`. The dashboard and `/api/llmops/*` compute every metric from these rows on request, and `scripts/export_llmops.py` writes the snapshot used below."),
  source(exportedLine.replace(/^> /, "").replace(/\*\*/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "docs/$1")),
  H2("7.1 Metrics"),
  table(["#", "Metric", "How it is measured"], [
    ["M1", "Transcription time and real-time factor", "transcribing stage duration ÷ audio seconds (pipeline_runs)"],
    ["M2–M3", "Summary and quiz latency (every task)", "p50 / p95 of successful requests per task and model (llm_calls)"],
    ["M4", "Question latency end to end", "qa_logs per generator, split into answered and refused"],
    ["M5", "Tokens and cost", "Sums per task, lecture and day; actual cost and equivalent cost at list prices"],
    ["M6", "Retrieval quality", "Hit@k, MRR, context precision on the golden set"],
    ["M7", "Faithfulness / hallucination rate", "LLM-as-judge splits answers into claims and checks them against the given chunks"],
    ["M8", "Refusal accuracy", "Share of unanswerable golden questions refused, split by layer"],
    ["+", "Error and JSON parse-failure rates, refusals by layer", "status and refusal_reason columns"],
  ], [8, 32, 60]),
  H2("7.2 Live metrics"),
  table(ov.header, ov.rows, [55, 45]),
  source("Source: docs/llmops_results.md §1. Evaluation traffic is excluded."),
  table(lat.header, lat.rows.filter((r) => !/smoke|calibration/.test(r[0])), [18, 12, 30, 8, 16, 16]),
  source("Source: docs/llmops_results.md §3 (latency of successful requests; smoke and calibration tasks omitted)."),
  table(qa.header, qa.rows, [12, 6, 12, 12, 14, 16, 16, 12]),
  source("Source: docs/llmops_results.md §4 (end-to-end question latency per generator, ms)."),
  ...figure("docs/images/llmops.png", "LLMOps dashboard", "KPI cards and latency charts"),
  H2("7.3 Versioning"),
  ...bullets([
    "**Prompt versioning:** prompts are YAML files with `id` and `version`; changing what a prompt does requires a new version. Every call logs `prompt_id@version`, and the dashboard compares latency, failure rates and tokens per version.",
    "**Model versions:** `llm_calls.model_version` stores the model string the provider returned; for Ollama models, the tag plus the model's digest (`study-buddy-qwen@sha256:…`); for embeddings, the Hugging Face commit. The model registry adds the fine-tune's provenance (base model and dataset revisions, LoRA settings, GGUF size).",
  ]),
  H2("7.4 Evaluation and golden set"),
  P("The golden set `ci_lecture` was written by the team for one 10.8-minute lecture: 20 questions (12 answerable with a labelled time range, 4 near-topic and 4 off-topic). No model generated the questions or labels. The harness reports retrieval once (all generators share the retriever), then runs each generator through the real answering path and asks the judge model (`qwen/qwen3.8-27b`, deliberately not the cloud generator's model) for faithfulness and correctness."),
  table(ret.header, ret.rows),
  source("Source: docs/llmops_results.md §8, M6 retrieval."),
  table(gens.header, gens.rows.filter((r) => !/Model \/ version|Status|Errors|Run finished/.test(r[0])), [40, 20, 20, 20]),
  source("Source: docs/llmops_results.md §8, generators."),
  ...figure("docs/images/llmops_eval.png", "LLMOps page: transcription speed (M1), prompt versions and the evaluation runs per generator", "cloud vs fine-tuned vs base"),
  H2("7.5 Threshold decision"),
  table(thr.header, thr.rows),
  source("Source: docs/llmops_results.md §8, RAG_MIN_SCORE check."),
  P(mdLine(llmopsMd, "Answerable questions refused by the threshold alone")),
  P("**Decision: RAG_MIN_SCORE stays at 0.50.** At 0.50 no answerable question is refused by the threshold, and most clearly unrelated questions are refused without an LLM call. Near-topic questions overlap with on-topic ones, so no threshold alone can separate them; they are handled by the model's own refusal. This confirms the two-layer design. The evaluation reports the scores but does not change the setting; the value was kept as a team decision."),
  H2("7.6 Limitations of the measurements"),
  ...bullets([
    "An LLM judge can be lenient or strict in ways a human would not; every claim and verdict is stored for a human spot check.",
    "Twenty questions on one lecture give noisy rates.",
    "Cloud latency includes free-tier pacing waits; local model latency depends on the CPU.",
    "Equivalent cost uses list prices that change; models without a published price are counted as unpriced.",
  ]),
);

// 8 Testing
const tests = mdTable(testingMd, "## 1. Results at a glance");
add(
  H1("8. Testing"),
  P("The backend is tested with pytest on in-memory SQLite with fake speech, LLM and embedding providers, and a real in-memory ChromaDB. A fixture fails any test that opens a network connection, so no test calls Groq or needs a key. The frontend is tested with Vitest and Testing Library against mocked API responses."),
  table(tests.header, tests.rows, [36, 34, 30]),
  source("Source: docs/testing.md §1 (real test output, 2026-11-09)."),
  H2("8.1 What is covered"),
  ...bullets([
    "**Free-tier rules:** Groq is the default; no code path switches to OpenAI; 429 backoff stays on the same provider.",
    "**Grounding:** segment ids turned into real times, invalid ids clamped or nulled, quiz items with out-of-range segments rejected, refusal below the threshold without an LLM call, citation check.",
    "**API contract:** status codes and the error envelope for every router; uploads, Range requests, downloads.",
    "**LLMOps:** percentiles, cost, error and refusal rates, Ollama digests, retrieval metrics, judge parsing, the generated results page.",
    "**Deployment:** migrations create exactly the model tables; the compose file, Dockerfiles and nginx configuration are checked offline.",
    "**Frontend:** API client error handling, routes, upload checks, transcript search and seek, the quiz flow and the chat (sources, refusal badge, unavailable model, free-tier waiting notice), flashcards.",
  ]),
  H2("8.2 Known gaps"),
  ...bullets([
    "No end-to-end browser test (the planned Playwright test was dropped from scope); the full flow is checked by hand.",
    "No frontend coverage figure; tests run on SQLite, not PostgreSQL; real providers are exercised only by manual scripts and the evaluation harness.",
    "Command-line wrappers in eval/ and scripts/ are largely untested, although the logic they call is covered.",
    "No continuous-integration pipeline.",
  ]),
);

// 9 Deployment
add(
  H1("9. Deployment"),
  P("`docker compose up --build` runs the whole application. The backend image is built from `python:3.12-slim` with ffmpeg and CPU-only PyTorch and runs as a non-root user; on start it applies the migrations. The frontend is a multi-stage build served by nginx, which also proxies `/api` and `/docs` to the backend. Each service waits for the previous one's health check."),
  table(["Service", "Role", "Data"], [
    ["db", "PostgreSQL 16", "volume pgdata"],
    ["backend", "FastAPI + ffmpeg + embedding model (CPU)", "volumes storage, chroma, hf-cache"],
    ["frontend", "nginx: React build, /api proxy (port 8080)", "none"],
    ["ollama (optional profile)", "Fine-tuned and base SLMs in a container", "volume ollama"],
    ["seed (one-off profile)", "Copies existing development data into the volumes", "none"],
  ], [25, 45, 30]),
  source("Source: docs/deployment.md §1."),
  P("**Measured footprint** (development machine, 2026-11-09, `docker stats` after transcribing a lecture and answering questions): backend 518 MiB, database 56 MiB, frontend 18 MiB of memory; the backend image is about 3.2 GB on disk. Each GGUF model adds about 1.1 GB."),
  P("**Cloud deployment** was documented but not carried out. The guide targets a small Linux VM running the same compose file behind Caddy for HTTPS, with production settings (`APP_ENV=production`, a random `SECRET_KEY`, a database password, the database port closed). A managed platform such as Render was compared: it offers HTTPS and Git deploys, but its free services have no persistent disk, little memory for the embedding model, sleep when idle and cannot run Ollama, so the VM is the better fit for this app."),
  ...figure("docs/images/docker_ps.png", "All services healthy under Docker Compose (docker compose ps)", "Terminal output of docker compose ps"),
  ...figure("docs/images/docker_desktop.png", "The compose project in Docker Desktop (the optional Ollama container stopped)", "Docker Desktop containers view"),
);

// 10 Limitations and future work
add(
  H1("10. Limitations and future work"),
  H2("10.1 Limitations"),
  ...bullets([
    "**Phase 9 not built:** no mind map, no adaptive difficulty, no revision recommendations. Topic mastery is stored but only used for weak topics and a suggested difficulty.",
    "**Domain transfer:** the SLM was trained on SciQ science passages; on lecture text its answers are faithful but often incomplete (golden-set correctness below the base model and the cloud model).",
    "**Small evaluation:** one golden set of 20 questions on one lecture; LLM-as-judge scores without a human-rated sample; no word-error-rate measurement for speech recognition.",
    "**Threshold:** near-topic questions cannot be separated from on-topic questions by retrieval score alone, so the model's own refusal remains essential.",
    "**Latency:** the free tier's token budget adds waits to cloud requests; the local SLM takes seconds per answer on a laptop CPU.",
    "**Operations:** background jobs run inside the web process (a restart interrupts transcription); media is fetched as a whole file, which suits short lectures only; metrics are system-wide (single-team demo); no CI pipeline.",
    "**Licence:** the fine-tuned model inherits SciQ's non-commercial licence.",
  ]),
  H2("10.2 Future work"),
  ...bullets([
    "**Phase 9 features:** a concept mind map built from extracted topics and relations (React Flow), adaptive quiz difficulty from topic mastery, weak-topic recommendations, a progress endpoint and spaced-repetition scheduling across lectures.",
    "**Cloud deployment:** carry out the VM deployment with HTTPS, backups and monitoring; move background jobs to a task queue; stream media with short-lived tokens.",
    "**Domain transfer:** fine-tune on lecture-style data (transcripts with labelled answers), add refusal examples from near-topic questions, and lengthen training prompts to the app's real context size.",
    "**Evaluation:** more golden sets across subjects, a human-rated sample to check the judge, word error rate for speech recognition, and a frontend end-to-end test in CI.",
  ]),
);

// 11 Team contributions
add(
  H1("11. Team contributions"),
  P("This chapter is completed from `docs/contributions.md`, which records what each member actually did. The repository cannot show who did which part, so nothing has been filled in on the team's behalf."),
  table(["Member", "Role", "Phases", "Main contributions", "Evidence"], [
    ["To be completed", "", "", "", ""],
    ["To be completed", "", "", "", ""],
    ["To be completed", "", "", "", ""],
    ["To be completed", "", "", "", ""],
  ], [18, 16, 12, 32, 22]),
  P("**Use of AI assistance:** to be described by the team (see `docs/contributions.md` §4)."),
);

// References
const refs = [
  "Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C. and Sutskever, I. (2022). Robust Speech Recognition via Large-Scale Weak Supervision. arXiv:2212.04356.",
  "OpenAI (2025). gpt-oss-120b and gpt-oss-20b Model Card. arXiv:2508.10925.",
  "Qwen Team (2025). Qwen3 Technical Report. arXiv:2505.09388.",
  "Xiao, S., Liu, Z., Zhang, P. and Muennighoff, N. (2023). C-Pack: Packaged Resources To Advance General Chinese Embedding (BGE models). arXiv:2309.07597.",
  "Welbl, J., Liu, N. F. and Gardner, M. (2017). Crowdsourcing Multiple Choice Science Questions. Proceedings of the 3rd Workshop on Noisy User-generated Text. (SciQ dataset)",
  "Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020. arXiv:2005.11401.",
  "Hu, E. J. et al. (2021). LoRA: Low-Rank Adaptation of Large Language Models. arXiv:2106.09685.",
  "Dettmers, T., Pagnoni, A., Holtzman, A. and Zettlemoyer, L. (2023). QLoRA: Efficient Finetuning of Quantized LLMs. arXiv:2305.14314.",
  "Zheng, L. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. arXiv:2306.05685.",
  "Es, S., James, J., Espinosa-Anke, L. and Schockaert, S. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation. arXiv:2309.15217.",
  "Leitner, S. (1972). So lernt man lernen. Freiburg: Herder. (Leitner box system)",
  "Hugging Face. Transformers, PEFT, TRL and Datasets documentation. https://huggingface.co/docs",
  "Unsloth. Documentation. https://docs.unsloth.ai",
  "Groq. GroqCloud documentation: models and rate limits. https://console.groq.com/docs (checked November 2026).",
  "Ollama. Documentation. https://github.com/ollama/ollama",
  "Chroma. Documentation. https://docs.trychroma.com",
  "FastAPI. Documentation. https://fastapi.tiangolo.com",
  "Project documentation: README.md, IMPLEMENTATION_PLAN.md, docs/*.md, finetune/MODEL_CARD.md and finetune/results/*.json in the project repository.",
];
add(
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("References")], pageBreakBefore: true }),
  ...refs.map((r, i) => new Paragraph({ children: runs(`[${i + 1}] ${r}`), spacing: { after: 100 }, indent: { left: 540, hanging: 540 } })),
);

// ---------- document ----------

const doc = new Document({
  creator: "AI Study Buddy team",
  title: "AI Study Buddy: Technical Report",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 34, bold: true, color: ACCENT }, paragraph: { spacing: { before: 240, after: 200 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 26, bold: true, color: ACCENT }, paragraph: { spacing: { before: 280, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 22, bold: true }, paragraph: { spacing: { before: 200, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: {
      default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "AI Study Buddy: Technical Report  |  ", size: 16, color: "777777" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "777777" })] })] }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`Wrote ${OUT} (${buf.length.toLocaleString("en-US")} bytes, ${figureNo} figures)`);
  if (missingImages.length) {
    console.log(`Placeholders for ${missingImages.length} missing image(s):`);
    missingImages.forEach((m) => console.log(`  - ${m}`));
  }
});
