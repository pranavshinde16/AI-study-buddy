import { describe, expect, it } from "vitest";

import { errorBody, mockApi } from "@/test/mockApi";
import * as ep from "./endpoints";

describe("8b endpoints", () => {
  it("generate-quiz and submit send the documented bodies", async () => {
    const mock = mockApi({
      "POST /lectures/l1/generate-quiz": { status: 201, data: { quiz_id: "q1", questions: [] } },
      "POST /quizzes/q1/submit": { data: { attempt_id: "a1", percent: 50 } },
    });
    await ep.generateQuiz("l1", { num_questions: 5, types: ["mcq"], difficulty: "easy", topics: null, adaptive: false });
    await ep.submitQuiz("q1", { answers: { q1: "B", q2: true, q3: null } });
    expect(JSON.parse(mock.calls[0].data as string)).toEqual({
      num_questions: 5, types: ["mcq"], difficulty: "easy", topics: null, adaptive: false,
    });
    expect(JSON.parse(mock.calls[1].data as string)).toEqual({ answers: { q1: "B", q2: true, q3: null } });
  });

  it("flashcards: due filter as a query param, regenerate flag and review body", async () => {
    const mock = mockApi({
      "GET /lectures/l1/flashcards": { data: { lecture_id: "l1", total: 0, due: 0, cards: [] } },
      "POST /lectures/l1/flashcards": { data: { lecture_id: "l1", total: 0, due: 0, cards: [], cached: true } },
      "POST /flashcards/c1/review": { data: { id: "c1", box: 2 } },
    });
    await ep.getDeck("l1", true);
    await ep.generateDeck("l1", true);
    await ep.reviewCard("c1", false);
    expect(mock.calls[0].params).toEqual({ due: true });
    expect(JSON.parse(mock.calls[1].data as string)).toEqual({ regenerate: true });
    expect(JSON.parse(mock.calls[2].data as string)).toEqual({ knew: false });
  });

  it("chat sends session id and model; MODEL_UNAVAILABLE keeps its code", async () => {
    const mock = mockApi({
      "POST /lectures/l1/chat": (config) =>
        JSON.parse(config.data as string).model === "finetuned"
          ? { status: 503, data: errorBody("MODEL_UNAVAILABLE", "Ollama is not running") }
          : { data: { session_id: "s1", answer: "ok" } },
    });
    await ep.sendChat("l1", { message: "hi", session_id: null, model: "cloud" });
    expect(JSON.parse(mock.calls[0].data as string)).toEqual({ message: "hi", session_id: null, model: "cloud" });
    await expect(ep.sendChat("l1", { message: "hi", session_id: "s1", model: "finetuned" })).rejects.toMatchObject({
      status: 503,
      code: "MODEL_UNAVAILABLE",
    });
  });
});
