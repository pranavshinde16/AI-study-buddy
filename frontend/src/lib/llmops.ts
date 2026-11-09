/**
 * Pure helpers for the LLMOps page (Phase 11): formatting, date presets, chart rows and the
 * eval comparison table. Every value comes from the /api/llmops responses; nothing is invented.
 */
import type {
  EvalCompareOut,
  EvalMetrics,
  EvalRunOut,
  LlmOpsFilters,
  QALatencyOut,
  RefusalsOut,
  TaskLatencyOut,
  UsageRowOut,
} from "@/api/types";

// ------------------------------------------------------------------ formatting
export const NA = "–";

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return NA;
  if (ms >= 10_000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

export function fmtRate(r: number | null | undefined, digits = 1): string {
  return r === null || r === undefined ? NA : `${(r * 100).toFixed(digits)}%`;
}

export function fmtScore(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined ? NA : String(Number(v.toFixed(digits)));
}

export function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined) return NA;
  if (v === 0) return "$0";
  return v < 0.01 ? `$${v.toFixed(5)}` : `$${v.toFixed(4)}`;
}

export function fmtInt(v: number | null | undefined): string {
  return v === null || v === undefined ? NA : v.toLocaleString("en-US");
}

export function fmtBytes(b: number | null | undefined): string {
  if (b === null || b === undefined) return NA;
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${b} B`;
}

export function shortHash(h: string | null | undefined, n = 12): string {
  if (!h) return NA;
  return h.replace(/^sha256:/, "").slice(0, n);
}

/** "study-buddy-qwen@sha256:abc…" -> { name, digest } */
export function splitVersion(v: string | null | undefined): { name: string; digest: string | null } {
  if (!v) return { name: NA, digest: null };
  const [name, digest] = v.split("@sha256:");
  return { name, digest: digest ?? null };
}

// ------------------------------------------------------------------ date presets
export type RangePreset = "all" | "today" | "7d" | "30d";

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** UTC days, inclusive, matching the backend's filter. */
export function presetRange(preset: RangePreset, now: Date = new Date()): Pick<LlmOpsFilters, "date_from" | "date_to"> {
  if (preset === "all") return { date_from: null, date_to: null };
  const days = preset === "today" ? 0 : preset === "7d" ? 6 : 29;
  const from = new Date(now.getTime() - days * 86_400_000);
  return { date_from: isoDay(from), date_to: isoDay(now) };
}

// ------------------------------------------------------------------ chart rows
export interface LatencyRow {
  label: string;
  p50: number;
  p95: number;
  n: number;
  [k: string]: string | number;
}

/** One bar pair per task (llm_calls). A task served by several models gets "task · model". */
export function taskLatencyRows(rows: TaskLatencyOut[]): LatencyRow[] {
  const perTask = new Map<string, number>();
  rows.forEach((r) => perTask.set(r.task, (perTask.get(r.task) ?? 0) + 1));
  return rows
    .filter((r) => r.p50_ms !== null && r.p95_ms !== null)
    .map((r) => ({
      label: (perTask.get(r.task) ?? 0) > 1 ? `${r.task} · ${r.model.split("/").pop()}` : r.task,
      p50: r.p50_ms as number,
      p95: r.p95_ms as number,
      n: r.n,
    }));
}

export function qaLatencyRows(rows: QALatencyOut[]): LatencyRow[] {
  return rows
    .filter((r) => r.p50_ms !== null && r.p95_ms !== null)
    .map((r) => ({ label: r.generator, p50: r.p50_ms as number, p95: r.p95_ms as number, n: r.n }));
}

export interface RefusalRow {
  label: string;
  answered: number;
  threshold: number;
  model: number;
  [k: string]: string | number;
}

export function refusalRows(rows: RefusalsOut[]): RefusalRow[] {
  return rows.map((r) => ({
    label: r.generator,
    answered: r.answered,
    threshold: r.below_threshold,
    model: r.not_in_chunks,
  }));
}

export interface TokenRow {
  label: string;
  input: number;
  output: number;
  [k: string]: string | number;
}

/** Rows with tokens only (embedding / ASR calls report none and would be empty bars). */
export function tokenRows(rows: UsageRowOut[]): TokenRow[] {
  return rows
    .filter((r) => r.total_tokens > 0)
    .map((r) => ({ label: r.label, input: r.input_tokens, output: r.output_tokens }));
}

// ------------------------------------------------------------------ eval metrics
/** Safe nested read of eval metrics_json: get(m, "refusal", "unanswerable", "by_model"). */
export function metric(m: EvalMetrics | null | undefined, ...path: string[]): unknown {
  let v: unknown = m;
  for (const p of path) {
    if (v === null || typeof v !== "object") return undefined;
    v = (v as Record<string, unknown>)[p];
  }
  return v;
}

export function num(m: EvalMetrics | null | undefined, ...path: string[]): number | null {
  const v = metric(m, ...path);
  return typeof v === "number" ? v : null;
}

export type CellFormat = "rate" | "score" | "ms" | "int" | "text";

export interface CompareRow {
  label: string;
  hint?: string;
  format: CellFormat;
  values: (number | string | null)[];
}

/** cloud vs finetuned vs base on the golden set (one column per latest generator run). */
export function compareRows(runs: EvalRunOut[]): CompareRow[] {
  const col = (f: (r: EvalRunOut) => number | string | null) => runs.map(f);
  const n = (...p: string[]) => col((r) => num(r.metrics, ...p));
  return [
    { label: "Model", format: "text", values: col((r) => splitVersion(r.model).name) },
    { label: "Questions", format: "int", values: n("n") },
    {
      label: "Refusal accuracy (M8)",
      hint: "Unanswerable questions that were refused",
      format: "rate",
      values: n("refusal_accuracy"),
    },
    { label: "· refused by threshold", format: "int", values: n("refusal", "unanswerable", "by_threshold") },
    { label: "· refused by model", format: "int", values: n("refusal", "unanswerable", "by_model") },
    {
      label: "False refusals",
      hint: "Answerable questions that were refused",
      format: "int",
      values: n("refusal", "false_refusals", "refused"),
    },
    { label: "Decision accuracy", hint: "Answer vs refuse, all questions", format: "rate", values: n("decision_accuracy") },
    {
      label: "Faithfulness (M7)",
      hint: "Supported claims ÷ claims, answered questions (LLM judge)",
      format: "score",
      values: n("faithfulness"),
    },
    { label: "Hallucination rate", hint: "Judged answers with faithfulness < 1", format: "rate", values: n("hallucination_rate") },
    { label: "Correctness (answered)", hint: "Judge score vs reference answer", format: "score", values: n("correctness_answered") },
    {
      label: "Correctness (all answerable)",
      hint: "A refused answerable question counts as 0",
      format: "score",
      values: n("correctness_all_answerable"),
    },
    { label: "Latency p50", format: "ms", values: n("latency", "p50_ms") },
    { label: "Latency p95", format: "ms", values: n("latency", "p95_ms") },
  ];
}

export function formatCell(v: number | string | null, format: CellFormat): string {
  if (v === null || v === undefined) return NA;
  if (typeof v === "string") return v;
  switch (format) {
    case "rate":
      return fmtRate(v);
    case "score":
      return fmtScore(v);
    case "ms":
      return fmtMs(v);
    case "int":
      return fmtInt(v);
    default:
      return String(v);
  }
}

/** Offline SciQ (Phase 10) rows: what eval_hf.json / eval_ollama_subset50.json report. */
export function offlineRows(c: EvalCompareOut | undefined) {
  return (c?.offline ?? []).map((r) => ({
    id: r.id,
    set: r.golden_set,
    generator: r.generator,
    n: r.n_items,
    backend: typeof r.config?.backend === "string" ? (r.config.backend as string) : null,
    accuracy: num(r.metrics, "gqa", "accuracy"),
    f1: num(r.metrics, "gqa", "token_f1"),
    refusalP: num(r.metrics, "refusal", "precision"),
    refusalR: num(r.metrics, "refusal", "recall"),
    mcqValid: num(r.metrics, "mcq", "json_valid_rate"),
    latencyMean: num(r.metrics, "latency_ms", "mean"),
    latencyP95: num(r.metrics, "latency_ms", "p95"),
  }));
}

/** One-line headline of a run for the runs table. */
export function runHeadline(r: EvalRunOut): string {
  const m = r.metrics;
  if (!m) return r.error ?? NA;
  if (r.source === "offline_import") {
    return `QA accuracy ${fmtScore(num(m, "gqa", "accuracy"))} · refusal F1 ${fmtScore(num(m, "refusal", "f1"))}`;
  }
  if (r.generator === "retrieval") {
    return `MRR ${fmtScore(num(m, "retrieval", "mrr"))} · context precision ${fmtScore(num(m, "retrieval", "context_precision"))}`;
  }
  return `refusal acc. ${fmtRate(num(m, "refusal_accuracy"))} · faithfulness ${fmtScore(num(m, "faithfulness"))}`;
}
