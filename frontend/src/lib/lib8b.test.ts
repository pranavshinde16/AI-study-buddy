import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/client";
import type { ChatResponse, DeckOut, FlashcardOut, LectureOut, QuestionOut } from "@/api/types";
import { appendTurn, chatErrorText, refusalText, splitCitations } from "./chat";
import { buildAnswers, formatAnswer } from "./quiz";
import { averageBest, boxDistribution, flattenQuizzes, revisionRows, totalDue } from "./stats";

const mcq: QuestionOut = { id: "q1", type: "mcq", difficulty: "easy", topic: null, question: "?", options: ["Red", "Blue", "Green", "Pink"] };

describe("quiz helpers", () => {
  it("formats answers for people", () => {
    expect(formatAnswer("B", mcq)).toBe("B. Blue");
    expect(formatAnswer("b)", mcq)).toBe("B. Blue");
    expect(formatAnswer(true)).toBe("True");
    expect(formatAnswer(null)).toBe("No answer");
    expect(formatAnswer("free text")).toBe("free text");
  });
  it("sends blank answers as null and trims text", () => {
    const qs: QuestionOut[] = [mcq, { ...mcq, id: "q2", type: "short_answer", options: null }, { ...mcq, id: "q3", type: "true_false", options: null }];
    expect(buildAnswers(qs, { q1: "A", q2: "  an answer ", q3: false })).toEqual({ q1: "A", q2: "an answer", q3: false });
    expect(buildAnswers(qs, { q2: "   " })).toEqual({ q1: null, q2: null, q3: null });
  });
});

describe("chat helpers", () => {
  it("splits citations", () => {
    expect(splitCitations("BaaS [C1] and FaaS [C2].")).toEqual([
      { text: "BaaS ", citation: false },
      { text: "[C1]", citation: true },
      { text: " and FaaS ", citation: false },
      { text: "[C2]", citation: true },
      { text: ".", citation: false },
    ]);
  });
  it("explains refusal reasons", () => {
    expect(refusalText("below_threshold")).toMatch(/similar enough/);
    expect(refusalText("not_in_chunks")).toMatch(/don't contain the answer/);
    expect(refusalText(null)).toMatch(/doesn't cover/);
  });
  it("words MODEL_UNAVAILABLE for the fine-tuned model", () => {
    const err = new ApiError({ status: 503, code: "MODEL_UNAVAILABLE", message: "Ollama is not running" });
    expect(chatErrorText(err, "finetuned").title).toBe("Fine-tuned model not available yet");
    expect(chatErrorText(err, "cloud").title).toBe("Model not available");
    const rl = new ApiError({ status: 429, code: "RATE_LIMITED", message: "x", retryAfter: 20 });
    expect(chatErrorText(rl, "cloud").description).toMatch(/wait 20 s/);
  });
  it("appends a live turn to the cached history", () => {
    const res = {
      session_id: "s1", message_id: "m1", question: "Q?", answer: "A [C1]", answerable: false, sources: [],
      rewritten_question: null, meta: { refusal_reason: "not_in_chunks" },
    } as unknown as ChatResponse;
    const h = appendTurn(undefined, "l1", res, "cloud", "2026-11-07T10:00:00Z");
    expect(h.title).toBe("Q?");
    expect(h.messages.map((m) => [m.role, m.content, m.refusal_reason])).toEqual([
      ["user", "Q?", null],
      ["assistant", "A [C1]", "not_in_chunks"],
    ]);
    expect(appendTurn(h, "l1", { ...res, message_id: "m2" }, "cloud").messages).toHaveLength(4);
  });
});

describe("dashboard stats", () => {
  const lec = (id: string, title: string) => ({ id, title }) as LectureOut;
  const card = (box: number, due: boolean, reviewed: boolean) =>
    ({ id: `${box}${due}${reviewed}`, box, due, last_reviewed_at: reviewed ? "2026-11-07T00:00:00Z" : null }) as FlashcardOut;

  it("flattens quizzes oldest first and averages only taken quizzes", () => {
    const pts = flattenQuizzes(
      [lec("a", "A"), lec("b", "B")],
      [
        [{ quiz_id: "q2", difficulty: "easy", num_questions: 5, created_at: "2026-11-05T00:00:00Z", attempts: 1, best_percent: 80 }],
        [
          { quiz_id: "q1", difficulty: null, num_questions: 3, created_at: "2026-11-01T00:00:00Z", attempts: 2, best_percent: 40 },
          { quiz_id: "q3", difficulty: null, num_questions: 3, created_at: "2026-11-06T00:00:00Z", attempts: 0, best_percent: null },
        ],
      ],
    );
    expect(pts.map((p) => [p.quizId, p.lectureTitle])).toEqual([["q1", "B"], ["q2", "A"], ["q3", "B"]]);
    expect(averageBest(pts)).toBe(60);
    expect(averageBest([])).toBeNull();
  });

  it("counts due cards, revision and Leitner boxes", () => {
    const d1 = { total: 3, due: 2, cards: [card(1, true, false), card(1, true, true), card(3, false, true)] } as DeckOut;
    expect(totalDue([d1, undefined])).toBe(2);
    expect(revisionRows([lec("a", "A"), lec("b", "B")], [d1, { total: 0, due: 0, cards: [] } as unknown as DeckOut])).toEqual([
      { lectureId: "a", lectureTitle: "A", total: 3, reviewed: 2, dueNow: 2 },
    ]);
    expect(boxDistribution([d1]).map((b) => b.cards)).toEqual([2, 0, 1, 0, 0]);
  });
});
