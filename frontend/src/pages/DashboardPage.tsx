import { LayoutDashboard } from "lucide-react";

import { PlaceholderPage } from "@/components/PlaceholderPage";

export function DashboardPage() {
  return (
    <PlaceholderPage
      title="Dashboard"
      description="KPIs, recent lectures, weak topics and your score trend."
      phase={8}
      icon={LayoutDashboard}
    />
  );
}
