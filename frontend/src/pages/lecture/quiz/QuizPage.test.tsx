import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorBody, mockApi } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const lecture = {
  id: "abc", title: "Intro to Serverless", original_filename: "intro.mp3", status: "ready", progress: 100,
  stage_detail: null, error: null, duration_sec: 120, language: "English", size_bytes: 1000,
  created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
};
const base = {
  "GET /auth/me": { data: fakeUser },
  "GET /lectures": { data: [lecture] },
  "GET /lectures/abc": { data: lecture },
  "GET /lectures/abc/quizzes": { data: [] },
};
const quiz = {
  quiz_id: "qz1", lecture_id: "abc", difficulty: "medium", created_at: "2026-11-07T10:00:00Z", attempts: 0,
  meta: { requested: 2, generated: 2, invalid_reasons: {} },
  questions: [
    { id: "q1", type: "mcq", difficulty: "medium", topic: "Basics", question: "Which one is FaaS?", options: ["Lambda", "Postgres", "Redis", "S3"] },
    { id: "q2", type: "true_false", difficulty: "medium", topic: "Basics", question: "Servers disappear.", options: null },
  ],
};

describe("QuizPage", () => {
  it("asks for notes first when they don't exist", async () => {
    mockApi({ ...base, "GET /lectures/abc/notes": { status: 409, data: errorBody("NOTES_NOT_GENERATED", "Generate notes first") } });
    renderApp("/lectures/abc/quiz");
    expect(await screen.findByText("Quizzes need the lecture's notes first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Summary & Notes" })).toHaveAttribute("href", "/lectures/abc/notes");
  });

  it("runs setup → questions → results without showing the adaptive toggle", async () => {
    const mock = mockApi({
      ...base,
      "GET /lectures/abc/notes": { data: { lecture_id: "abc", topics: [{ title: "Basics", start: 0, end: 60, notes_md: "", key_points: [] }], meta: {} } },
      "POST /lectures/abc/generate-quiz": { status: 201, data: quiz },
      "POST /quizzes/qz1/submit": {
        data: {
          attempt_id: "a1", quiz_id: "qz1", score: 1, total: 2, percent: 50,
          results: [
            { id: "q1", type: "mcq", topic: "Basics", question: "Which one is FaaS?", your_answer: "A", correct: true, score: 1, correct_answer: "A", explanation: "Lambda runs functions.", timestamp: 65, graded_by: "rule", feedback: null },
            { id: "q2", type: "true_false", topic: "Basics", question: "Servers disappear.", your_answer: null, correct: false, score: 0, correct_answer: false, explanation: "Servers still exist.", timestamp: 30, graded_by: "rule", feedback: null },
          ],
          topics: [{ topic: "Basics", correct: 1, total: 2, mastery: 0.5 }],
          weak_topics: ["Basics"],
          suggested_next_difficulty: "medium",
        },
      },
    });
    renderApp("/lectures/abc/quiz");
    expect(await screen.findByText("New quiz")).toBeInTheDocument();
    expect(screen.queryByText(/Adaptive/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Basics" })); // topic filter
    fireEvent.click(screen.getByRole("button", { name: /generate quiz/i }));
    expect(await screen.findByText("Which one is FaaS?")).toBeInTheDocument();
    const gen = JSON.parse(mock.calls.find((c) => c.url === "/lectures/abc/generate-quiz")!.data as string);
    expect(gen).toMatchObject({ num_questions: 10, difficulty: "medium", topics: ["Basics"], adaptive: false });

    fireEvent.click(screen.getByRole("radio", { name: /Lambda/ }));
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();
    expect(screen.getByText(/1 unanswered question will count as wrong/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));

    expect(await screen.findByText("50%")).toBeInTheDocument();
    const sub = JSON.parse(mock.calls.find((c) => c.url === "/quizzes/qz1/submit")!.data as string);
    expect(sub).toEqual({ answers: { q1: "A", q2: null } });
    const answers = screen.getByText("Answers and explanations").closest("div")!.parentElement!;
    expect(within(answers).getByText("A. Lambda")).toBeInTheDocument();
    expect(within(answers).getByText("Servers still exist.")).toBeInTheDocument();
    expect(within(answers).getByRole("link", { name: "Play from 01:05" })).toHaveAttribute("href", "/lectures/abc/transcript?t=65");
  });
});
