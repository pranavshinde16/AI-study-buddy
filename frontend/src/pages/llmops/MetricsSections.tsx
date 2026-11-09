/** Live-traffic metrics: latency (M2-M4), tokens & cost (M5), refusals, transcription (M1), errors, prompts. */
import { useState } from "react";
import { AlertTriangle, Coins, FileCode2, Mic, ShieldQuestion, Timer } from "lucide-react";

import type { useLlmOps } from "@/api/hooks";
import type { UsageGroup, UsageRowOut } from "@/api/types";
import { MultiBarChart } from "@/components/charts/charts";
import { ErrorState } from "@/components/ErrorState";
import { Segmented } from "@/components/Segmented";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, formatDuration } from "@/lib/format";
import {
  fmtInt,
  fmtMs,
  fmtRate,
  fmtUsd,
  qaLatencyRows,
  refusalRows,
  taskLatencyRows,
  tokenRows,
} from "@/lib/llmops";

import { DataTable, Empty, Loading, Section, TableToggle } from "./parts";

type Data = ReturnType<typeof useLlmOps>;

const LATENCY_SERIES = [
  { key: "p50", label: "p50 (median)" },
  { key: "p95", label: "p95" },
];

export function LatencySection({ data }: { data: Data }) {
  const [view, setView] = useState<"task" | "generator">("task");
  const q = view === "task" ? data.latency : data.qaLatency;
  const rows = view === "task" ? taskLatencyRows(data.latency.data ?? []) : qaLatencyRows(data.qaLatency.data ?? []);
  return (
    <Section
      icon={Timer}
      title="Latency"
      description={
        view === "task"
          ? "M2–M3: successful model requests per task (llm_calls). Embedding tasks are local and fast."
          : "M4: end to end per question, including retrieval and refusals (qa_logs)."
      }
      actions={
        <Segmented
          label="Latency view"
          value={view}
          onChange={setView}
          options={[
            { value: "task", label: "By task" },
            { value: "generator", label: "By generator" },
          ]}
        />
      }
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No successful requests in this range.</Empty>
      ) : (
        <>
          <MultiBarChart
            data={rows}
            xKey="label"
            series={LATENCY_SERIES}
            format={fmtMs}
            ariaLabel={`Latency p50 and p95 ${view === "task" ? "per task" : "per generator"}: ${rows
              .map((r) => `${r.label} ${fmtMs(r.p50)} / ${fmtMs(r.p95)}`)
              .join(", ")}`}
          />
          <TableToggle>
            <DataTable
              rows={rows}
              rowKey={(r) => r.label}
              caption="Latency"
              columns={[
                { header: view === "task" ? "Task" : "Generator", cell: (r) => r.label },
                { header: "n", cell: (r) => r.n, align: "right" },
                { header: "p50", cell: (r) => fmtMs(r.p50), align: "right" },
                { header: "p95", cell: (r) => fmtMs(r.p95), align: "right" },
              ]}
            />
          </TableToggle>
          {view === "generator" && data.qaLatency.data && data.qaLatency.data.length > 0 && (
            <div className="mt-4">
              <DataTable
                rows={data.qaLatency.data}
                rowKey={(r) => r.generator}
                caption="End-to-end latency split"
                columns={[
                  { header: "Generator", cell: (r) => r.generator },
                  { header: "Answered p50", cell: (r) => fmtMs(r.answered.p50_ms), align: "right" },
                  { header: "Model refusal p50", cell: (r) => fmtMs(r.refused_by_model.p50_ms), align: "right" },
                  { header: "Threshold refusal p50", cell: (r) => fmtMs(r.refused_by_threshold.p50_ms), align: "right" },
                  { header: "Retrieval p50", cell: (r) => fmtMs(r.retrieval.p50_ms), align: "right" },
                ]}
              />
            </div>
          )}
        </>
      )}
    </Section>
  );
}

const TOKEN_SERIES = [
  { key: "input", label: "Input tokens" },
  { key: "output", label: "Output tokens" },
];

export function UsageSection({ data }: { data: Data }) {
  const [group, setGroup] = useState<UsageGroup>("task");
  const q = group === "task" ? data.usageTask : group === "day" ? data.usageDay : data.usageLecture;
  const rows: UsageRowOut[] = q.data ?? [];
  const chart = tokenRows(rows);
  return (
    <Section
      icon={Coins}
      title="Tokens and cost"
      description="M5. Actual cost is $0 on the free tier; equivalent cost uses the reference prices in config/pricing.yaml. A model without a listed price is counted as unpriced, never guessed."
      actions={
        <Segmented
          label="Group usage by"
          value={group}
          onChange={setGroup}
          options={[
            { value: "task", label: "Task" },
            { value: "day", label: "Day" },
            { value: "lecture", label: "Lecture" },
          ]}
        />
      }
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No model calls in this range.</Empty>
      ) : (
        <>
          {chart.length > 0 ? (
            <MultiBarChart
              data={chart}
              xKey="label"
              series={TOKEN_SERIES}
              stacked
              format={(v) => fmtInt(Math.round(v))}
              ariaLabel={`Tokens per ${group}: ${chart.map((r) => `${r.label} ${r.input} in, ${r.output} out`).join("; ")}`}
            />
          ) : (
            <Empty>These calls report no token counts (embeddings, speech recognition).</Empty>
          )}
          <div className="mt-4">
            <DataTable
              rows={rows}
              rowKey={(r) => r.key}
              caption="Tokens and cost"
              minWidth="40rem"
              columns={[
                { header: group === "task" ? "Task" : group === "day" ? "Day (UTC)" : "Lecture", cell: (r) => r.label },
                { header: "Calls", cell: (r) => fmtInt(r.calls), align: "right" },
                { header: "Tokens in", cell: (r) => fmtInt(r.input_tokens), align: "right" },
                { header: "Tokens out", cell: (r) => fmtInt(r.output_tokens), align: "right" },
                { header: "Actual", cell: (r) => fmtUsd(r.cost_usd), align: "right" },
                {
                  header: "Equivalent",
                  cell: (r) => (
                    <>
                      {fmtUsd(r.equivalent_cost_usd)}
                      {r.unpriced_calls > 0 && (
                        <span className="block text-xs text-muted-foreground">{r.unpriced_calls} unpriced</span>
                      )}
                    </>
                  ),
                  align: "right",
                },
              ]}
            />
          </div>
        </>
      )}
    </Section>
  );
}

const REFUSAL_SERIES = [
  { key: "answered", label: "Answered" },
  { key: "threshold", label: "Refused: threshold" },
  { key: "model", label: "Refused: model" },
];

export function RefusalSection({ data }: { data: Data }) {
  const q = data.refusals;
  const rows = refusalRows(q.data ?? []);
  return (
    <Section
      icon={ShieldQuestion}
      title="Answers and refusals"
      description="Per generator, from /ask and /chat. Threshold = best score below RAG_MIN_SCORE (no LLM call); model = the model said the chunks don't answer it."
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No questions in this range.</Empty>
      ) : (
        <>
          <MultiBarChart
            data={rows}
            xKey="label"
            series={REFUSAL_SERIES}
            stacked
            ariaLabel={`Questions per generator: ${rows
              .map((r) => `${r.label} ${r.answered} answered, ${r.threshold} refused by threshold, ${r.model} by model`)
              .join("; ")}`}
          />
          <TableToggle>
            <DataTable
              rows={q.data ?? []}
              rowKey={(r) => r.generator}
              caption="Refusals per generator"
              columns={[
                { header: "Generator", cell: (r) => r.generator },
                { header: "Questions", cell: (r) => r.questions, align: "right" },
                { header: "Answered", cell: (r) => r.answered, align: "right" },
                { header: "Threshold", cell: (r) => r.below_threshold, align: "right" },
                { header: "Model", cell: (r) => r.not_in_chunks, align: "right" },
                { header: "Errors", cell: (r) => r.errors, align: "right" },
                { header: "Refusal rate", cell: (r) => fmtRate(r.refusal_rate), align: "right" },
              ]}
            />
          </TableToggle>
        </>
      )}
    </Section>
  );
}

export function TranscriptionSection({ data }: { data: Data }) {
  const q = data.transcription;
  return (
    <Section
      icon={Mic}
      title="Transcription speed"
      description="M1: real-time factor = processing time ÷ audio length of the transcribing stage (below 1 = faster than real time)."
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-24" />
      ) : !q.data || q.data.n === 0 ? (
        <Empty>No transcriptions in this range.</Empty>
      ) : (
        <DataTable
          rows={q.data.runs}
          rowKey={(r) => `${r.lecture_id}-${r.started_at}`}
          caption="Transcription runs"
          columns={[
            { header: "Lecture", cell: (r) => r.title ?? r.lecture_id, className: "max-w-[14rem] truncate" },
            { header: "Audio", cell: (r) => formatDuration(r.audio_sec), align: "right" },
            { header: "Processing", cell: (r) => `${r.processing_sec.toFixed(1)} s`, align: "right" },
            { header: "RTF", cell: (r) => r.rtf.toFixed(3), align: "right" },
            { header: "When", cell: (r) => formatDateTime(r.started_at), className: "whitespace-nowrap text-muted-foreground" },
          ]}
        />
      )}
    </Section>
  );
}

export function ErrorsSection({ data }: { data: Data }) {
  const q = data.errors;
  return (
    <Section
      icon={AlertTriangle}
      title="Errors and JSON failures"
      description="Failed = error, unavailable, rate limited or not configured. A JSON failure triggers one repair request; 'after repair' means the user got LLM_OUTPUT_INVALID."
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-32" />
      ) : !q.data || q.data.requests === 0 ? (
        <Empty>No model calls in this range.</Empty>
      ) : (
        <div className="space-y-5">
          <DataTable
            rows={q.data.by_task}
            rowKey={(r) => r.task}
            caption="Errors per task"
            minWidth="40rem"
            columns={[
              { header: "Task", cell: (r) => r.task },
              { header: "Requests", cell: (r) => r.requests, align: "right" },
              { header: "Failed", cell: (r) => r.failed, align: "right" },
              { header: "Error rate", cell: (r) => fmtRate(r.error_rate), align: "right" },
              { header: "Rate limited", cell: (r) => r.rate_limited, align: "right" },
              { header: "JSON invalid", cell: (r) => r.json_invalid, align: "right" },
              { header: "Parse-fail rate", cell: (r) => fmtRate(r.parse_failure_rate), align: "right" },
              { header: "After repair", cell: (r) => r.repair_failed, align: "right" },
            ]}
          />
          {q.data.recent.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">Latest failures</p>
              <DataTable
                rows={q.data.recent}
                rowKey={(r, i) => `${r.ts}-${i}`}
                caption="Latest failures"
                minWidth="44rem"
                columns={[
                  { header: "When", cell: (r) => formatDateTime(r.ts), className: "whitespace-nowrap text-muted-foreground" },
                  { header: "Task", cell: (r) => r.task },
                  { header: "Model", cell: (r) => `${r.provider} / ${r.model}`, className: "max-w-[12rem] truncate" },
                  {
                    header: "Status",
                    cell: (r) => (
                      <Badge variant={r.status === "json_invalid" ? "warning" : "destructive"}>
                        <AlertTriangle aria-hidden="true" /> {r.status}
                      </Badge>
                    ),
                  },
                  {
                    header: "Message",
                    cell: (r) => (
                      <span className="line-clamp-2 text-xs text-muted-foreground" title={r.error_message ?? ""}>
                        {r.error_type ? `${r.error_type}: ` : ""}
                        {r.error_message ?? "–"}
                      </span>
                    ),
                  },
                ]}
              />
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

export function PromptsSection({ data }: { data: Data }) {
  const q = data.prompts;
  return (
    <Section icon={FileCode2} title="Prompt versions" description="Every call logs its prompt id@version, so versions can be compared.">
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-32" />
      ) : !q.data || q.data.length === 0 ? (
        <Empty>No prompt calls in this range.</Empty>
      ) : (
        <DataTable
          rows={q.data}
          rowKey={(r) => `${r.prompt_version}-${r.task}`}
          caption="Metrics per prompt version"
          minWidth="44rem"
          columns={[
            { header: "Prompt", cell: (r) => <code className="text-xs">{r.prompt_version}</code> },
            { header: "Task", cell: (r) => r.task },
            { header: "Requests", cell: (r) => r.requests, align: "right" },
            { header: "p50", cell: (r) => fmtMs(r.p50_ms), align: "right" },
            { header: "p95", cell: (r) => fmtMs(r.p95_ms), align: "right" },
            { header: "Error rate", cell: (r) => fmtRate(r.error_rate), align: "right" },
            { header: "Parse-fail", cell: (r) => fmtRate(r.parse_failure_rate), align: "right" },
            {
              header: "Tokens in / out",
              cell: (r) =>
                `${r.mean_input_tokens === null ? "–" : Math.round(r.mean_input_tokens)} / ${
                  r.mean_output_tokens === null ? "–" : Math.round(r.mean_output_tokens)
                }`,
              align: "right",
            },
          ]}
        />
      )}
    </Section>
  );
}
