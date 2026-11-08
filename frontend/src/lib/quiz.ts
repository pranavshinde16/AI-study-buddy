import type { AnswerValue, QuestionOut, QuestionType } from "@/api/types";

export const LETTERS = ["A", "B", "C", "D"] as const;

export const TYPE_LABELS: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  true_false: "True / false",
  short_answer: "Short answer",
};

/** Human-readable answer: MCQ letters get their option text, booleans become True/False. */
export function formatAnswer(value: AnswerValue | undefined, question?: Pick<QuestionOut, "type" | "options">): string {
  if (value === null || value === undefined || value === "") return "No answer";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (question?.type === "mcq" && question.options) {
    const i = LETTERS.indexOf(value.trim().toUpperCase().replace(/\)$/, "") as (typeof LETTERS)[number]);
    if (i >= 0 && question.options[i] !== undefined) return `${LETTERS[i]}. ${question.options[i]}`;
  }
  return value;
}

export function isAnswered(value: AnswerValue | undefined): boolean {
  if (value === null || value === undefined) return false;
  return typeof value === "boolean" || value.trim() !== "";
}

/** The submit body: blank short answers are sent as null (the backend counts them as wrong). */
export function buildAnswers(questions: QuestionOut[], answers: Record<string, AnswerValue>): Record<string, AnswerValue> {
  const out: Record<string, AnswerValue> = {};
  for (const q of questions) {
    const v = answers[q.id];
    out[q.id] = isAnswered(v) ? (typeof v === "string" ? v.trim() : v) : null;
  }
  return out;
}
