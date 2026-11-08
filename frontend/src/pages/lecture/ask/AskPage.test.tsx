import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorBody, mockApi, type MockHandler } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const lecture = {
  id: "abc", title: "Intro to Serverless", original_filename: "intro.mp3", status: "ready", progress: 100,
  stage_detail: null, error: null, duration_sec: 120, language: "English", size_bytes: 1000,
  created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
};
const models = [
  { name: "cloud", provider: "groq", model: "openai/gpt-oss-120b", description: "Groq free tier" },
  { name: "finetuned", provider: "ollama", model: "study-buddy-qwen", description: "Fine-tuned SLM" },
];
const meta = {
  generator: "cloud", provider: "groq", model: "openai/gpt-oss-120b", prompt_version: "rag_answer@v1",
  rewritten_question: null, refusal_reason: null, top_score: 0.79, scores: [0.79], min_score: 0.5, top_k: 5,
  retrieval_ms: 20, latency_ms: 900, llm_calls: 1, input_tokens: 0, output_tokens: 0, citations_dropped: [],
  citation_check: "ok", indexed_now: false, chunks: 4,
};

function setup(chat: MockHandler, extra: Record<string, MockHandler> = {}) {
  return mockApi({
    "GET /auth/me": { data: fakeUser },
    "GET /lectures": { data: [lecture] },
    "GET /lectures/abc": { data: lecture },
    "GET /lectures/abc/chat": { data: [] },
    "GET /models": { data: models },
    "POST /lectures/abc/chat": chat,
    ...extra,
  });
}

async function ask(text: string) {
  const box = await screen.findByRole("textbox", { name: "Your question" });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

describe("AskPage", () => {
  afterEach(() => vi.useRealTimers());

  it("loads models from /models and shows answers with source chips", async () => {
    const mock = setup({
      data: {
        answer: "Two types: BaaS and FaaS [C1].", answerable: true, meta,
        sources: [{ chunk_id: "C1", chunk_idx: 0, start: 0, end: 86.4, excerpt: "BaaS and FaaS…", score: 0.79, cited: true }],
        session_id: "s1", message_id: "m1", question: "What are the two types?", rewritten_question: null,
      },
    });
    renderApp("/lectures/abc/ask");
    const select = await screen.findByRole("combobox", { name: "Model" });
    await waitFor(() => expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["cloud (groq)", "finetuned (ollama)"]));

    await ask("What are the two types?");
    const chip = await screen.findByRole("link", { name: /Source C1: 00:00 to 01:26/ });
    expect(chip).toHaveAttribute("href", "/lectures/abc/transcript?t=0");
    expect(screen.getByText("What are the two types?")).toBeInTheDocument();
    const body = JSON.parse(mock.calls.find((c) => c.url === "/lectures/abc/chat" && c.method === "post")!.data as string);
    expect(body).toEqual({ message: "What are the two types?", session_id: null, model: "cloud" });
  });

  it("shows the 'not in lecture' badge with the refusal reason", async () => {
    setup({
      data: {
        answer: "This isn't covered in the lecture. The closest parts of the lecture are at 00:00–01:26.",
        answerable: false, meta: { ...meta, refusal_reason: "below_threshold" },
        sources: [{ chunk_id: "C1", chunk_idx: 0, start: 0, end: 86.4, excerpt: "…", score: 0.3, cited: false }],
        session_id: "s1", message_id: "m1", question: "Who won the World Cup?", rewritten_question: null,
      },
    });
    renderApp("/lectures/abc/ask");
    await ask("Who won the World Cup?");
    expect(await screen.findByText("Not in lecture")).toBeInTheDocument();
    expect(screen.getByText(/similar enough to the question/)).toBeInTheDocument();
    expect(screen.getByText("Closest parts of the lecture")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Closest part C1/ })).toBeInTheDocument();
  });

  it("says the fine-tuned model isn't available on 503 MODEL_UNAVAILABLE and keeps the question", async () => {
    setup({ status: 503, data: errorBody("MODEL_UNAVAILABLE", "Ollama is not running or not reachable") });
    renderApp("/lectures/abc/ask");
    const select = await screen.findByRole("combobox", { name: "Model" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
    fireEvent.change(select, { target: { value: "finetuned" } });
    await ask("What is FaaS?");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Fine-tuned model not available yet");
    expect(alert).toHaveTextContent("Ollama is not running");
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("What is FaaS?");

    fireEvent.click(within(alert).getByRole("button", { name: "Switch to cloud" }));
    expect(select).toHaveValue("cloud");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the free-tier waiting message while a request is slow", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setup(() => new Promise(() => undefined)); // never answers
    renderApp("/lectures/abc/ask");
    await ask("Slow question?");
    expect(await screen.findByText("Searching the lecture…")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting for the free-tier rate limit/)).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(8_100));
    expect(await screen.findByText(/Waiting for the free-tier rate limit/)).toBeInTheDocument();
  });

  it("reopens a session with the stored refusal reason", async () => {
    setup(
      { data: {} },
      {
        "GET /lectures/abc/chat": { data: [{ session_id: "s9", title: "Old chat", created_at: "2026-11-07T09:00:00Z", messages: 2 }] },
        "GET /lectures/abc/chat/s9": {
          data: {
            session_id: "s9", lecture_id: "abc", title: "Old chat", created_at: "2026-11-07T09:00:00Z",
            messages: [
              { id: "u1", role: "user", content: "TCP vs UDP?", sources: [], answerable: null, refusal_reason: null, model: null, created_at: "2026-11-07T09:00:00Z" },
              { id: "a1", role: "assistant", content: "This isn't covered in the lecture.", sources: [], answerable: false, refusal_reason: "not_in_chunks", model: "cloud:openai/gpt-oss-120b", created_at: "2026-11-07T09:00:01Z" },
            ],
          },
        },
      },
    );
    renderApp("/lectures/abc/ask");
    fireEvent.click(await screen.findByRole("button", { name: /Old chat/ }));
    expect(await screen.findByText("TCP vs UDP?")).toBeInTheDocument();
    expect(screen.getByText("Not in lecture")).toBeInTheDocument();
    expect(screen.getByText(/don't contain the answer/)).toBeInTheDocument();
  });
});
