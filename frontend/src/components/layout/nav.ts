import { BarChart3, Gauge, LayoutDashboard, Upload, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** Top-level sidebar links. Lecture pages are reached from a lecture, not the sidebar. */
export const mainNav: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload lecture", icon: Upload },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/llmops", label: "LLMOps", icon: Gauge },
];
