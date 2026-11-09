/**
 * LLMOps dashboard (Phase 11). Everything shown comes from /api/llmops/*, which computes it from
 * the logs the backend writes for every model call (llm_calls, pipeline_runs, qa_logs) and from
 * eval_runs. Filters (one row, above the charts): date range, task, generator, eval traffic.
 */
import { useMemo, useState } from "react";

import { useLlmOps, useLlmOpsFilterOptions } from "@/api/hooks";
import type { LlmOpsFilters } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import { Segmented } from "@/components/Segmented";
import { formatDateTime } from "@/lib/format";
import { fmtInt, fmtMs, fmtRate, fmtUsd, presetRange, type RangePreset } from "@/lib/llmops";

import { EvalCompareSection, EvalRunsSection, ModelRegistrySection } from "./llmops/EvalSections";
import {
  ErrorsSection,
  LatencySection,
  PromptsSection,
  RefusalSection,
  TranscriptionSection,
  UsageSection,
} from "./llmops/MetricsSections";
import { Kpi } from "./llmops/parts";

const selectClass =
  "rounded-lg border bg-card px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function LlmOpsPage() {
  const [preset, setPreset] = useState<RangePreset>("all");
  const [task, setTask] = useState("");
  const [generator, setGenerator] = useState("");
  const [includeEval, setIncludeEval] = useState(false);

  const filters: LlmOpsFilters = useMemo(
    () => ({ ...presetRange(preset), task: task || null, generator: generator || null, include_eval: includeEval }),
    [preset, task, generator, includeEval],
  );
  const options = useLlmOpsFilterOptions();
  const data = useLlmOps(filters);
  const s = data.summary.data;

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">LLMOps</h1>
        <p className="text-sm text-muted-foreground">
          Latency, tokens, cost, errors and refusals from every logged model call, plus the evaluation results.
          {s?.last_call_at && <> Last call {formatDateTime(s.last_call_at)}.</>}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3" aria-label="Filters">
        <Segmented
          label="Date range (UTC)"
          value={preset}
          onChange={setPreset}
          options={[
            { value: "all", label: "All time" },
            { value: "30d", label: "30 days" },
            { value: "7d", label: "7 days" },
            { value: "today", label: "Today" },
          ]}
        />
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Task</span>
          <select className={selectClass} value={task} onChange={(e) => setTask(e.target.value)}>
            <option value="">All tasks</option>
            {(options.data?.tasks ?? []).map((t) => (
              <option key={t}>{t}</option>
            ))}
            {includeEval &&
              (options.data?.eval_tasks ?? []).map((t) => (
                <option key={t}>{t}</option>
              ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Generator</span>
          <select className={selectClass} value={generator} onChange={(e) => setGenerator(e.target.value)}>
            <option value="">All</option>
            {(options.data?.generators ?? []).map((g) => (
              <option key={g}>{g}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={includeEval} onChange={(e) => setIncludeEval(e.target.checked)} />
          Include eval traffic
        </label>
      </div>

      {data.summary.isError ? (
        <ErrorState error={data.summary.error} onRetry={() => void data.summary.refetch()} />
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <Kpi
            label="Model calls"
            loading={!s}
            value={fmtInt(s?.calls)}
            sub={s && `${fmtInt(s.questions)} questions · p50 ${fmtMs(s.qa_latency.p50_ms)}`}
          />
          <Kpi
            label="Tokens"
            loading={!s}
            value={fmtInt(s?.total_tokens)}
            sub={s && `${fmtInt(s.input_tokens)} in · ${fmtInt(s.output_tokens)} out`}
          />
          <Kpi
            label="Equivalent cost"
            loading={!s}
            value={fmtUsd(s?.equivalent_cost_usd)}
            sub={
              s &&
              `actual ${fmtUsd(s.cost_usd)} (free tier)${s.unpriced_calls ? ` · ${s.unpriced_calls} unpriced` : ""}`
            }
          />
          <Kpi
            label="Error rate"
            loading={!s}
            value={fmtRate(s?.error_rate)}
            sub={s && `${s.failed_calls} failed · JSON ${fmtRate(s.parse_failure_rate)}`}
          />
          <Kpi
            label="Real-time factor"
            loading={!s}
            value={s?.rtf_overall === null || s?.rtf_overall === undefined ? "–" : s.rtf_overall.toFixed(3)}
            sub={s && `${s.transcriptions} transcription${s.transcriptions === 1 ? "" : "s"} (M1)`}
          />
        </div>
      )}

      <LatencySection data={data} />
      <div className="grid gap-6 xl:grid-cols-2">
        <UsageSection data={data} />
        <RefusalSection data={data} />
      </div>
      <EvalCompareSection />
      <ModelRegistrySection />
      <ErrorsSection data={data} />
      <div className="grid gap-6 xl:grid-cols-2">
        <TranscriptionSection data={data} />
        <PromptsSection data={data} />
      </div>
      <EvalRunsSection />
    </section>
  );
}
