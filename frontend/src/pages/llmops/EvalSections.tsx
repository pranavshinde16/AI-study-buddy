/** Model registry, the golden-set comparison (cloud vs finetuned vs base), the RAG_MIN_SCORE check,
 *  the imported SciQ results and the list of eval runs. */
import { useState } from "react";
import { Boxes, GitCompareArrows, ListOrdered } from "lucide-react";

import { useEvalCompare, useEvalRuns, useModelRegistry } from "@/api/hooks";
import type { EvalCompareOut, EvalRunOut, FinetuneDetails } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import {
  compareRows,
  fmtBytes,
  fmtMs,
  fmtScore,
  formatCell,
  metric,
  NA,
  offlineRows,
  runHeadline,
  shortHash,
  splitVersion,
} from "@/lib/llmops";

import { DataTable, Empty, Loading, Section } from "./parts";

const EVAL_CMD = "python -m eval.run --set golden_v1 --lecture-id <id> --generator all";

export function ModelRegistrySection() {
  const q = useModelRegistry();
  return (
    <Section
      icon={Boxes}
      title="Model registry"
      description="What answered: the model string each provider last returned, Ollama digests, and the fine-tune's provenance from finetune/results/training.json."
      actions={
        q.data && q.data.ollama_reachable !== null ? (
          <Badge variant={q.data.ollama_reachable ? "success" : "warning"}>
            Ollama {q.data.ollama_reachable ? "reachable" : "not reachable"}
          </Badge>
        ) : null
      }
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-40" />
      ) : (
        <div className="space-y-5">
          <DataTable
            rows={[
              ...q.data.generators.map((g) => ({
                key: g.name,
                name: g.name,
                provider: g.provider,
                model: g.model,
                version: splitVersion(g.version).name,
                digest: g.digest ?? splitVersion(g.version).digest,
                extra: [
                  g.details.quantization_level,
                  g.details.parameter_size,
                  g.size_bytes ? fmtBytes(g.size_bytes) : null,
                  g.available === false ? "not installed" : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
                lastUsed: g.last_used_at,
              })),
              ...q.data.others.map((o) => ({
                key: o.name,
                name: o.name,
                provider: o.provider,
                model: o.model,
                version: o.version ?? NA,
                digest: o.revision ?? null,
                extra: o.note ?? "",
                lastUsed: o.last_used_at,
              })),
            ]}
            rowKey={(r) => r.key}
            caption="Model registry"
            minWidth="48rem"
            columns={[
              { header: "Role", cell: (r) => <span className="font-medium">{r.name}</span> },
              { header: "Provider / model", cell: (r) => `${r.provider} / ${r.model}`, className: "max-w-[16rem] break-words" },
              { header: "Reported version", cell: (r) => r.version, className: "max-w-[12rem] break-words" },
              {
                header: "Digest / revision",
                cell: (r) => (r.digest ? <code className="text-xs" title={r.digest}>{shortHash(r.digest)}</code> : NA),
              },
              { header: "Details", cell: (r) => <span className="text-xs text-muted-foreground">{r.extra || NA}</span> },
              { header: "Last used", cell: (r) => formatDateTime(r.lastUsed), className: "whitespace-nowrap text-muted-foreground" },
            ]}
          />
          <FinetuneProvenance ft={q.data.generators.find((g) => g.name === "finetuned")?.details.finetune} />
          <p className="text-xs text-muted-foreground">
            Prompt versions: {q.data.prompts.map((p) => p.tag).join(", ")}
          </p>
        </div>
      )}
    </Section>
  );
}

function FinetuneProvenance({ ft }: { ft: FinetuneDetails | undefined }) {
  if (!ft) return null;
  if (!ft.source_file) {
    return <p className="text-xs text-muted-foreground">No finetune/results/training.json found (FINETUNE_RESULTS_DIR).</p>;
  }
  const items: [string, string][] = [
    ["Base model", `${ft.base_model ?? NA} @ ${shortHash(ft.base_model_revision)}`],
    ["Dataset", `${ft.dataset ?? NA} @ ${shortHash(ft.dataset_revision)}`],
    ["Method", `${ft.method ?? NA}${ft.lora && typeof ft.lora.r === "number" ? ` (r ${ft.lora.r})` : ""}`],
    ["Training examples", ft.train_examples === null ? NA : String(ft.train_examples)],
    ["GGUF", `${ft.gguf_file ?? NA} (${fmtBytes(ft.gguf_bytes)})`],
    ["Trained", `${formatDateTime(ft.trained_at)}${ft.gpu ? ` on ${ft.gpu}` : ""}`],
    ["Hub repo", ft.hub_repo ?? "not set (FINETUNED_HUB_REPO)"],
  ];
  return (
    <div className="rounded-xl border bg-muted/30 p-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">Fine-tuned model provenance</p>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {items.map(([k, v]) => (
          <div key={k} className="flex min-w-0 gap-2">
            <dt className="shrink-0 text-muted-foreground">{k}:</dt>
            <dd className="min-w-0 break-words">
              {k === "Hub repo" && ft.hub_repo ? (
                <a href={`https://huggingface.co/${ft.hub_repo}`} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  {v}
                </a>
              ) : (
                v
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function EvalCompareSection() {
  const [set, setSet] = useState<string | null>(null);
  const q = useEvalCompare(set);
  return (
    <Section
      icon={GitCompareArrows}
      title="Golden-set evaluation: cloud vs finetuned vs base"
      description="Latest run per generator on the hand-written golden set. Faithfulness and correctness come from an LLM judge (a different model from the cloud generator)."
      actions={
        q.data && q.data.golden_sets.length > 1 ? (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Golden set</span>
            <select
              className="rounded-lg border bg-card px-2 py-1 text-sm"
              value={q.data.golden_set ?? ""}
              onChange={(e) => setSet(e.target.value)}
            >
              {q.data.golden_sets.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        ) : null
      }
    >
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-48" />
      ) : !q.data.golden_set ? (
        <Empty>
          No golden-set run yet. Write the questions in backend/eval/golden/ (see its README), then run{" "}
          <code className="text-xs">{EVAL_CMD}</code> from backend/.
        </Empty>
      ) : (
        <div className="space-y-6">
          <GeneratorCompare data={q.data} />
          <RetrievalBlock data={q.data} />
        </div>
      )}
      {q.data && q.data.offline.length > 0 && <OfflineBlock data={q.data} />}
    </Section>
  );
}

function GeneratorCompare({ data }: { data: EvalCompareOut }) {
  const runs = data.generators;
  if (runs.length === 0) return <Empty>Only the retrieval run exists for this set.</Empty>;
  const rows = compareRows(runs);
  return (
    <div>
      <p className="mb-2 text-sm">
        Set <span className="font-medium">{data.golden_set}</span>
        {runs[0].lecture_title && (
          <>
            {" "}on <span className="font-medium">{runs[0].lecture_title}</span>
          </>
        )}
        {" · judge "}
        <code className="text-xs">{String(runs[0].prompt_versions?.judge ?? "off")}</code>
      </p>
      <DataTable
        rows={rows}
        rowKey={(r) => r.label}
        caption="Generator comparison"
        minWidth="36rem"
        columns={[
          {
            header: "Metric",
            cell: (r) => (
              <span title={r.hint}>
                {r.label}
                {r.hint && <span className="block text-xs text-muted-foreground">{r.hint}</span>}
              </span>
            ),
          },
          ...runs.map((run, i) => ({
            header: run.generator,
            cell: (r: (typeof rows)[number]) => formatCell(r.values[i], r.format),
            align: "right" as const,
          })),
        ]}
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {runs
          .filter((r) => r.status !== "ok")
          .map((r) => (
            <Badge key={r.id} variant="warning">
              {r.generator}: {r.status}
              {r.error ? ` (${r.error.slice(0, 80)})` : ""}
            </Badge>
          ))}
      </div>
    </div>
  );
}

function RetrievalBlock({ data }: { data: EvalCompareOut }) {
  const r = data.retrieval;
  if (!r || !r.metrics) return null;
  const ret = (metric(r.metrics, "retrieval") ?? {}) as Record<string, number | null>;
  const hits = Object.keys(ret).filter((k) => k.startsWith("hit@"));
  const t = metric(r.metrics, "threshold") as
    | {
        threshold: number;
        by_kind: Record<string, { n: number; min?: number; median?: number; max?: number; below_threshold: number; at_or_above_threshold: number }>;
        answerable: { wrongly_refused_by_threshold?: number };
        unanswerable: { refused_by_threshold?: number; passed_to_model?: number };
        answerable_min: number | null;
        unanswerable_max: number | null;
        gap: number | null;
      }
    | undefined;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-sm font-medium">Retrieval (M6, shared by all generators)</p>
        <DataTable
          rows={[...hits, "mrr", "context_precision", "average_precision"].map((k) => ({ k, v: ret[k] ?? null }))}
          rowKey={(x) => x.k}
          caption="Retrieval metrics"
          minWidth="16rem"
          columns={[
            { header: "Metric", cell: (x) => (x.k === "mrr" ? "MRR" : x.k.replace("_", " ").replace("@", " @ ")) },
            { header: `Value (n = ${ret.n ?? NA})`, cell: (x) => fmtScore(x.v), align: "right" },
          ]}
        />
      </div>
      {t && (
        <div>
          <p className="mb-2 text-sm font-medium">RAG_MIN_SCORE check (current {t.threshold})</p>
          <DataTable
            rows={Object.entries(t.by_kind).map(([kind, d]) => ({ kind, ...d }))}
            rowKey={(x) => x.kind}
            caption="Top retrieval score per question kind"
            minWidth="24rem"
            columns={[
              { header: "Kind", cell: (x) => x.kind },
              { header: "n", cell: (x) => x.n, align: "right" },
              { header: "min", cell: (x) => fmtScore(x.min ?? null), align: "right" },
              { header: "median", cell: (x) => fmtScore(x.median ?? null), align: "right" },
              { header: "max", cell: (x) => fmtScore(x.max ?? null), align: "right" },
              { header: "below", cell: (x) => x.below_threshold, align: "right" },
            ]}
          />
          <p className="mt-2 text-xs text-muted-foreground">
            Answerable refused by the threshold alone: {t.answerable.wrongly_refused_by_threshold ?? NA}. Unanswerable:{" "}
            {t.unanswerable.refused_by_threshold ?? NA} refused by the threshold, {t.unanswerable.passed_to_model ?? NA} passed
            to the model. Lowest answerable {fmtScore(t.answerable_min)}, highest unanswerable {fmtScore(t.unanswerable_max)}.
          </p>
        </div>
      )}
    </div>
  );
}

function OfflineBlock({ data }: { data: EvalCompareOut }) {
  const rows = offlineRows(data);
  return (
    <div className="mt-6">
      <p className="mb-1 text-sm font-medium">SciQ test results from Phase 10 (imported, offline)</p>
      <p className="mb-2 text-xs text-muted-foreground">
        Copied unchanged from finetune/results/*.json: science passages, not lecture transcripts.
      </p>
      <DataTable
        rows={rows}
        rowKey={(r) => r.id}
        caption="SciQ offline results"
        minWidth="44rem"
        columns={[
          { header: "Set", cell: (r) => `${r.set}${r.backend ? ` (${r.backend})` : ""}` },
          { header: "Model", cell: (r) => r.generator },
          { header: "QA accuracy", cell: (r) => fmtScore(r.accuracy), align: "right" },
          { header: "Token F1", cell: (r) => fmtScore(r.f1), align: "right" },
          { header: "Refusal P / R", cell: (r) => `${fmtScore(r.refusalP)} / ${fmtScore(r.refusalR)}`, align: "right" },
          { header: "MCQ JSON valid", cell: (r) => fmtScore(r.mcqValid), align: "right" },
          { header: "Latency mean / p95", cell: (r) => `${fmtMs(r.latencyMean)} / ${fmtMs(r.latencyP95)}`, align: "right" },
        ]}
      />
    </div>
  );
}

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  ok: "success",
  partial: "warning",
  failed: "destructive",
  running: "secondary",
};

export function EvalRunsSection() {
  const q = useEvalRuns();
  return (
    <Section icon={ListOrdered} title="Evaluation runs" description="Every harness run and imported result, newest first.">
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isPending ? (
        <Loading h="h-32" />
      ) : q.data.length === 0 ? (
        <Empty>
          No runs yet. <code className="text-xs">python -m eval.import_offline</code> imports the Phase 10 SciQ results.
        </Empty>
      ) : (
        <DataTable<EvalRunOut>
          rows={q.data}
          rowKey={(r) => r.id}
          caption="Evaluation runs"
          minWidth="48rem"
          columns={[
            { header: "Started", cell: (r) => formatDateTime(r.started_at), className: "whitespace-nowrap text-muted-foreground" },
            { header: "Set", cell: (r) => r.golden_set },
            {
              header: "Generator",
              cell: (r) => (
                <span className="flex items-center gap-1.5">
                  {r.generator}
                  {r.source === "offline_import" && <Badge variant="secondary">offline</Badge>}
                </span>
              ),
            },
            { header: "Items", cell: (r) => r.n_items ?? NA, align: "right" },
            {
              header: "Status",
              cell: (r) => <Badge variant={STATUS_VARIANT[r.status] ?? "secondary"}>{r.status}</Badge>,
            },
            { header: "Headline", cell: (r) => <span className="text-xs text-muted-foreground">{runHeadline(r)}</span> },
          ]}
        />
      )}
    </Section>
  );
}
