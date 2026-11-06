import { Gauge } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function LlmOpsPage() {
  return (
    <PlaceholderPage
      title="LLMOps"
      description="Latency, tokens, cost, errors, evaluation runs and model comparison."
      phase={11}
      icon={Gauge}
    />
  );
}
