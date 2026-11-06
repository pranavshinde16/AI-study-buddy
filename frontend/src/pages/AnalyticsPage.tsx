import { BarChart3 } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function AnalyticsPage() {
  return (
    <PlaceholderPage
      title="Analytics"
      description="Mastery by topic, quiz history, and revision done versus pending."
      phase={9}
      icon={BarChart3}
    />
  );
}
