import { describe, expect, it } from "vitest";

import type { EvalCompareOut, EvalRunOut, RefusalsOut, TaskLatencyOut, UsageRowOut } from "@/api/types";
import { filterParams } from "@/api/endpoints";

import {
  compareRows,
  fmtBytes,
  fmtMs,
  fmtRate,
  fmtScore,
  fmtUsd,
  formatCell,
  metric,
  num,
  offlineRows,
  presetRange,
  qaLatencyRows,
  refusalRows,
  runHeadline,
  shortHash,
  splitVersion,
  taskLatencyRows,
  tokenRows,
} from "./llmops";

const lat = (task: string, model: string, p50: number | null, p95: number | null): TaskLatencyOut => ({
  task,
  provider: "groq",
  model,
  n: 3,
  p50_ms: p50,
  p95_ms: p95,
  mean_ms: p50,
});

function run(generator: string, metrics: Record<string, unknown> | null, extra: Partial<EvalRunOut> = {}): EvalRunOut {
  return {
    id: generator,
    golden_set: "golden_v1",
    generator,
    model: `${generator}-model@sha256:abc`,
    source: "harness",
    lecture_id: null,
    lecture_title: "Lecture",
    n_items: 30,
    status: "ok",
    error: null,
    started_at: "2026-11-09T10:00:00Z",
    finished_at: null,
    prompt_versions: null,
    config: null,
    metrics,
    ...extra,
  };
}

describe("formatting", () => {
  it("formats latency, rates, scores, money and sizes", () => {
    expect(fmtMs(null)).toBe("–");
    expect(fmtMs(432.4)).toBe("432 ms");
    expect(fmtMs(1234)).toBe("1.23 s");
    expect(fmtMs(18977)).toBe("19.0 s");
    expect(fmtRate(0.1234)).toBe("12.3%");
    expect(fmtScore(0.83333)).toBe("0.833");
    expect(fmtUsd(0)).toBe("$0");
    expect(fmtUsd(0.00514)).toBe("$0.00514");
    expect(fmtBytes(1107404864)).toBe("1.03 GB");
    expect(shortHash(`sha256:${"a".repeat(64)}`)).toBe("aaaaaaaaaaaa");
    expect(splitVersion("study-buddy-qwen@sha256:abc")).toEqual({ name: "study-buddy-qwen", digest: "abc" });
    expect(formatCell(null, "rate")).toBe("–");
    expect(formatCell("x", "rate")).toBe("x");
  });
});

describe("filters", () => {
  it("builds UTC day ranges", () => {
    const now = new Date("2026-11-09T12:00:00Z");
    expect(presetRange("all", now)).toEqual({ date_from: null, date_to: null });
    expect(presetRange("today", now)).toEqual({ date_from: "2026-11-09", date_to: "2026-11-09" });
    expect(presetRange("7d", now)).toEqual({ date_from: "2026-11-03", date_to: "2026-11-09" });
  });

  it("sends only the filters that are set", () => {
    expect(filterParams({ date_from: null, task: "", generator: "cloud", include_eval: false })).toEqual({
      generator: "cloud",
    });
    expect(filterParams({ include_eval: true, task: "quiz" })).toEqual({ include_eval: true, task: "quiz" });
  });
});

describe("chart rows", () => {
  it("labels a task by model only when several models serve it, and skips empty stats", () => {
    const rows = taskLatencyRows([
      lat("summary", "openai/gpt-oss-120b", 1000, 3000),
      lat("rag_answer", "openai/gpt-oss-120b", 600, 900),
      lat("rag_answer", "study-buddy-qwen", 9000, 15000),
      lat("quiz", "x", null, null),
    ]);
    expect(rows.map((r) => r.label)).toEqual(["summary", "rag_answer · gpt-oss-120b", "rag_answer · study-buddy-qwen"]);
  });

  it("maps refusals, QA latency and tokens", () => {
    const r: RefusalsOut = {
      generator: "cloud",
      questions: 4,
      answered: 2,
      below_threshold: 1,
      not_in_chunks: 1,
      errors: 0,
      refused: 2,
      refusal_rate: 0.5,
      threshold_share_of_refusals: 0.5,
    };
    expect(refusalRows([r])).toEqual([{ label: "cloud", answered: 2, threshold: 1, model: 1 }]);
    const stats = { n: 0, p50_ms: null, p95_ms: null, mean_ms: null };
    expect(
      qaLatencyRows([
        { generator: "cloud", n: 2, p50_ms: 500, p95_ms: 800, mean_ms: 600, answered: stats, refused_by_model: stats, refused_by_threshold: stats, retrieval: stats },
      ]),
    ).toEqual([{ label: "cloud", p50: 500, p95: 800, n: 2 }]);
    const usage = (key: string, inp: number, out: number): UsageRowOut => ({
      key,
      label: key,
      calls: 1,
      input_tokens: inp,
      output_tokens: out,
      total_tokens: inp + out,
      cost_usd: 0,
      cost_unknown_calls: 0,
      equivalent_cost_usd: 0,
      unpriced_calls: 0,
    });
    expect(tokenRows([usage("summary", 10, 5), usage("rag_query", 0, 0)])).toEqual([
      { label: "summary", input: 10, output: 5 },
    ]);
  });
});

describe("eval metrics", () => {
  const cloud = run("cloud", {
    n: 30,
    refusal_accuracy: 0.9,
    refusal: { unanswerable: { by_threshold: 6, by_model: 3 }, false_refusals: { refused: 1 } },
    faithfulness: 0.95,
    latency: { p50_ms: 700, p95_ms: 1500 },
  });
  const base = run("base", null);

  it("reads nested values safely", () => {
    expect(num(cloud.metrics, "refusal", "unanswerable", "by_model")).toBe(3);
    expect(num(cloud.metrics, "refusal", "missing", "x")).toBeNull();
    expect(metric(null, "a")).toBeUndefined();
  });

  it("builds one column per generator, with n/a for missing metrics", () => {
    const rows = compareRows([cloud, base]);
    const byLabel = Object.fromEntries(rows.map((r) => [r.label, r.values]));
    expect(byLabel["Model"]).toEqual(["cloud-model", "base-model"]);
    expect(byLabel["Refusal accuracy (M8)"]).toEqual([0.9, null]);
    expect(byLabel["· refused by model"]).toEqual([3, null]);
    expect(byLabel["Latency p95"]).toEqual([1500, null]);
  });

  it("summarises runs by kind", () => {
    expect(runHeadline(cloud)).toContain("90.0%");
    expect(runHeadline(run("retrieval", { retrieval: { mrr: 0.8, context_precision: 0.4 } }))).toBe(
      "MRR 0.8 · context precision 0.4",
    );
    expect(runHeadline(run("x", null, { error: "MODEL_UNAVAILABLE" }))).toBe("MODEL_UNAVAILABLE");
    const off = run("finetuned", { gqa: { accuracy: 0.9093 }, refusal: { f1: 0.93 } }, { source: "offline_import" });
    expect(runHeadline(off)).toBe("QA accuracy 0.909 · refusal F1 0.93");
  });

  it("maps offline SciQ runs", () => {
    const c: EvalCompareOut = {
      golden_set: null,
      golden_sets: [],
      retrieval: null,
      generators: [],
      offline: [
        run("finetuned", { gqa: { accuracy: 0.9, token_f1: 0.8 }, latency_ms: { mean: 800, p95: 1100 } }, {
          source: "offline_import",
          golden_set: "sciq_test_500",
          config: { backend: "hf" },
        }),
      ],
    };
    const [r] = offlineRows(c);
    expect(r).toMatchObject({ set: "sciq_test_500", backend: "hf", accuracy: 0.9, f1: 0.8, latencyP95: 1100 });
    expect(offlineRows(undefined)).toEqual([]);
  });
});
