import { Gauge } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function LlmOpsPage() {
  return (
    <PlaceholderPage
      title="LLMOps"
      description="Every model call is already logged (llm_calls, pipeline_runs, qa_logs). The dashboard that reads those logs is built in Phase 11."
      phase={11}
      icon={Gauge}
      planned={[
        "Metric cards for the 8 tracked metrics",
        "Latency by task",
        "Token usage and cost",
        "Error log table",
        "Evaluation runs",
        "Base vs fine-tuned comparison",
      ]}
    />
  );
}
