import { PlaceholderPage } from "@/components/PlaceholderPage";
import type { LectureTab } from "./tabs";

/** "Coming soon" content for a workspace tab that a later phase builds (the Mind Map, Phase 9). */
export function LectureTabPage({ tab, planned }: { tab: LectureTab; planned?: string[] }) {
  return (
    <PlaceholderPage
      embedded
      title={tab.label}
      description={tab.description}
      phase={tab.phase}
      icon={tab.icon}
      planned={planned}
    />
  );
}
