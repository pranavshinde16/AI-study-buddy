"""LLMOps dashboard routes (/api/llmops/*, Phase 11). HTTP only: the numbers are computed in
services/llmops.py, services/model_registry.py and services/evaluation/queries.py.

Metrics are system-wide (every user's calls), for any logged-in user: this is a single-team
demo deployment. Filters: date_from / date_to (UTC days, inclusive), task, generator.
"""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Generators, ModelRegistry, Pricing
from app.core.errors import AppError
from app.schemas.errors import error_responses
from app.schemas.llmops import (
    ErrorsOut,
    EvalCompareOut,
    EvalRunDetailOut,
    EvalRunOut,
    FilterOptionsOut,
    ModelRegistryOut,
    PromptMetricsOut,
    QALatencyOut,
    RefusalsOut,
    SummaryOut,
    TaskLatencyOut,
    TranscriptionOut,
    UsageRowOut,
)
from app.services.evaluation import queries as eval_queries
from app.services.llmops import LlmOpsMetrics, MetricFilter

router = APIRouter(prefix="/llmops", tags=["llmops"])

_ERR = error_responses(401, 422)


class InvalidRangeError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


def _filter(date_from: date | None, date_to: date | None, task: str | None, generator: str | None,
            include_eval: bool) -> MetricFilter:
    if date_from and date_to and date_from > date_to:
        raise InvalidRangeError("date_from is after date_to", details={"date_from": str(date_from),
                                                                         "date_to": str(date_to)})
    return MetricFilter(date_from=date_from, date_to=date_to, task=task or None, generator=generator or None,
                        include_eval=include_eval)


DateFrom = Annotated[date | None, Query(description="First UTC day (inclusive), YYYY-MM-DD")]
DateTo = Annotated[date | None, Query(description="Last UTC day (inclusive), YYYY-MM-DD")]
Task = Annotated[str | None, Query(description="llm_calls task, e.g. summary, quiz, rag_answer")]
Gen = Annotated[str | None, Query(description="Answer generator (cloud | finetuned | base | ...)")]
IncludeEval = Annotated[bool, Query(description="Include eval-harness traffic (tasks eval_*)")]


@router.get("/summary", response_model=SummaryOut, summary="KPI cards: calls, tokens, cost, error rate, RTF",
            responses=_ERR)
def summary(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators, date_from: DateFrom = None,
            date_to: DateTo = None, task: Task = None, generator: Gen = None, include_eval: IncludeEval = False):
    f = _filter(date_from, date_to, task, generator, include_eval)
    return LlmOpsMetrics(db, pricing, generators).summary(f)


@router.get("/filters", response_model=FilterOptionsOut, summary="Values available for the filters",
            responses=error_responses(401))
def filters(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators):
    return LlmOpsMetrics(db, pricing, generators).filter_options()


@router.get("/latency", response_model=list[TaskLatencyOut],
            summary="M2/M3: p50/p95 latency of successful requests per task and model", responses=_ERR)
def latency(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators, date_from: DateFrom = None,
            date_to: DateTo = None, task: Task = None, generator: Gen = None, include_eval: IncludeEval = False):
    return LlmOpsMetrics(db, pricing, generators).latency_by_task(
        _filter(date_from, date_to, task, generator, include_eval))


@router.get("/qa-latency", response_model=list[QALatencyOut],
            summary="M4: end-to-end /ask and /chat latency per generator (qa_logs)", responses=_ERR)
def qa_latency(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators,
               date_from: DateFrom = None, date_to: DateTo = None, generator: Gen = None):
    return LlmOpsMetrics(db, pricing, generators).qa_latency(_filter(date_from, date_to, None, generator, False))


@router.get("/usage", response_model=list[UsageRowOut],
            summary="M5: tokens, actual cost and equivalent cost per task, lecture or day", responses=_ERR)
def usage(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators,
          group: Annotated[Literal["task", "lecture", "day"], Query()] = "task", date_from: DateFrom = None,
          date_to: DateTo = None, task: Task = None, generator: Gen = None, include_eval: IncludeEval = False):
    return LlmOpsMetrics(db, pricing, generators).usage(
        _filter(date_from, date_to, task, generator, include_eval), group)


@router.get("/transcription", response_model=TranscriptionOut,
            summary="M1: transcription time and real-time factor per lecture", responses=_ERR)
def transcription(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators,
                  date_from: DateFrom = None, date_to: DateTo = None):
    return LlmOpsMetrics(db, pricing, generators).transcription(_filter(date_from, date_to, None, None, False))


@router.get("/errors", response_model=ErrorsOut,
            summary="Error rate and JSON parse-failure rate per task, plus the latest failures", responses=_ERR)
def errors(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators, date_from: DateFrom = None,
           date_to: DateTo = None, task: Task = None, generator: Gen = None, include_eval: IncludeEval = False):
    return LlmOpsMetrics(db, pricing, generators).errors(_filter(date_from, date_to, task, generator, include_eval))


@router.get("/refusals", response_model=list[RefusalsOut],
            summary="Refusals per generator, split by layer: threshold vs model (qa_logs)", responses=_ERR)
def refusals(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators,
             date_from: DateFrom = None, date_to: DateTo = None, generator: Gen = None):
    return LlmOpsMetrics(db, pricing, generators).refusals(_filter(date_from, date_to, None, generator, False))


@router.get("/prompts", response_model=list[PromptMetricsOut],
            summary="Metrics per prompt version (latency, failures, tokens)", responses=_ERR)
def prompts(user: CurrentUser, db: DbSession, pricing: Pricing, generators: Generators, date_from: DateFrom = None,
            date_to: DateTo = None, task: Task = None, generator: Gen = None, include_eval: IncludeEval = False):
    return LlmOpsMetrics(db, pricing, generators).prompts(_filter(date_from, date_to, task, generator, include_eval))


@router.get("/models", response_model=ModelRegistryOut,
            summary="Model registry: generators (with Ollama digests), ASR, embedding, judge, prompt versions",
            responses=error_responses(401))
def models(user: CurrentUser, db: DbSession, registry: ModelRegistry):
    return registry.registry(db)


@router.get("/eval/runs", response_model=list[EvalRunOut], summary="Evaluation runs, newest first",
            responses=error_responses(401))
def eval_runs(user: CurrentUser, db: DbSession, limit: Annotated[int, Query(ge=1, le=500)] = 100):
    return eval_queries.list_runs(db, limit)


@router.get("/eval/runs/{run_id}", response_model=EvalRunDetailOut, summary="One evaluation run with its items",
            responses=error_responses(401, 404))
def eval_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return eval_queries.get_run(db, run_id)


@router.get("/eval/compare", response_model=EvalCompareOut,
            summary="cloud vs finetuned vs base on a golden set, plus the imported SciQ (offline) runs",
            responses=error_responses(401))
def eval_compare(user: CurrentUser, db: DbSession, golden_set: Annotated[str | None, Query()] = None):
    return eval_queries.compare(db, golden_set)
