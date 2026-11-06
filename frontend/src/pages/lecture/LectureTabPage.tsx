import { PlaceholderPage } from "@/components/PlaceholderPage";
import type { LectureTab } from "./tabs";

/** Placeholder content for one workspace tab. Replaced by real feature pages in Phase 8/9. */
export function LectureTabPage({ tab }: { tab: LectureTab }) {
  return <PlaceholderPage title={tab.label} description={tab.description} phase={tab.phase} icon={tab.icon} />;
}
