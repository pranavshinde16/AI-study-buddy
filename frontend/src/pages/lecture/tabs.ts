import {
  BookOpenText,
  FileText,
  Layers,
  ListChecks,
  MessagesSquare,
  Network,
  type LucideIcon,
} from "lucide-react";

export interface LectureTab {
  path: string;
  label: string;
  description: string;
  /** Phase that wires this tab to real data (UI in Phase 8; mind map in Phase 9). */
  phase: number;
  icon: LucideIcon;
}

/** Workspace tabs from IMPLEMENTATION_PLAN.md §9, in display order. */
export const lectureTabs: LectureTab[] = [
  { path: "transcript", label: "Transcript", description: "Searchable, timestamped transcript with downloads.", phase: 8, icon: FileText },
  { path: "notes", label: "Summary & Notes", description: "Summary, key takeaways, definitions and topic notes.", phase: 8, icon: BookOpenText },
  { path: "quiz", label: "Quiz", description: "Generated quizzes with explanations and timestamps.", phase: 8, icon: ListChecks },
  { path: "ask", label: "Ask", description: "Questions answered only from this lecture, with sources.", phase: 8, icon: MessagesSquare },
  { path: "flashcards", label: "Flashcards", description: "Flip cards with Leitner-box review.", phase: 8, icon: Layers },
  { path: "mindmap", label: "Mind Map", description: "Concept map of the lecture's topics.", phase: 9, icon: Network },
];
