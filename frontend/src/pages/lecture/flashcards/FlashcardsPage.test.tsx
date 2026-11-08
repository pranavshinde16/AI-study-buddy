import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FlashcardOut } from "@/api/types";
import { mockApi } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const lecture = {
  id: "abc", title: "Intro to Serverless", original_filename: "intro.mp3", status: "ready", progress: 100,
  stage_detail: null, error: null, duration_sec: 120, language: "English", size_bytes: 1000,
  created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
};

function card(id: string, front: string, back: string, box = 1, due = true): FlashcardOut {
  return {
    id, kind: "concept", front, back, topic: "Basics", timestamp: 12, box, due,
    due_at: "2026-11-07T10:00:00Z", last_reviewed_at: null,
  };
}

const cards = [card("c1", "What is FaaS?", "Functions as a service"), card("c2", "What is BaaS?", "Backend as a service"), card("c3", "Later card", "x", 3, false)];

function setup(deckCards: FlashcardOut[] = cards) {
  const reviews: { id: string; knew: boolean }[] = [];
  const mock = mockApi({
    "GET /auth/me": { data: fakeUser },
    "GET /lectures": { data: [lecture] },
    "GET /lectures/abc": { data: lecture },
    "GET /lectures/abc/flashcards": {
      data: { lecture_id: "abc", total: deckCards.length, due: deckCards.filter((c) => c.due).length, cards: deckCards },
    },
    "POST /flashcards/c1/review": (config) => {
      const knew = JSON.parse(config.data as string).knew as boolean;
      reviews.push({ id: "c1", knew });
      return { data: { ...cards[0], box: knew ? 2 : 1 } };
    },
    "POST /flashcards/c2/review": (config) => {
      const knew = JSON.parse(config.data as string).knew as boolean;
      reviews.push({ id: "c2", knew });
      return { data: { ...cards[1], box: knew ? 2 : 1 } };
    },
  });
  renderApp("/lectures/abc/flashcards");
  return { mock, reviews };
}

describe("FlashcardsPage", () => {
  it("shows due counts and the Leitner boxes", async () => {
    setup();
    expect(await screen.findByRole("radio", { name: "Due today (2)" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "All cards (3)" })).toBeInTheDocument();
    const boxes = screen.getByRole("list", { name: "Cards per Leitner box" });
    expect(boxes).toHaveTextContent("2Box 1");
    expect(boxes).toHaveTextContent("1Box 3");
  });

  it("flips with the keyboard, re-queues a missed card and finishes the session", async () => {
    const { reviews } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Start review" }));

    const flip = screen.getByRole("button", { name: "Show the answer" });
    expect(flip).toHaveTextContent("What is FaaS?");
    fireEvent.keyDown(window, { key: " " });
    expect(screen.getByRole("button", { name: "Show the question" })).toHaveAttribute("aria-pressed", "true");

    // ← = didn't know: the card goes to the back of the queue.
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Show the answer" })).toHaveTextContent("What is BaaS?"));
    expect(screen.getByText("Box 1 of 5")).toBeInTheDocument();

    // K = knew it.
    fireEvent.keyDown(window, { key: "k" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Show the answer" })).toHaveTextContent("What is FaaS?"));

    fireEvent.click(screen.getByRole("button", { name: /knew it/i }));
    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByText(/knew 2 · missed 1/)).toBeInTheDocument();
    expect(reviews).toEqual([
      { id: "c1", knew: false },
      { id: "c2", knew: true },
      { id: "c1", knew: true },
    ]);
  });

  it("offers to generate a deck when there is none", async () => {
    setup([]);
    expect(await screen.findByText("No flashcards yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate flashcards" })).toBeEnabled();
  });
});
