import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const lecture = {
  id: "abc", title: "Intro to Serverless", original_filename: "intro.mp3", status: "ready", progress: 100,
  stage_detail: null, error: null, duration_sec: 291.8, language: "English", size_bytes: 1000,
  created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
};

describe("app shell routes", () => {
  it("sends logged-out visitors to /login and remembers the page", async () => {
    const { router } = renderApp("/upload", { loggedIn: false });
    expect(await screen.findByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe("?next=%2Fupload");
  });

  it("renders the sidebar, the user and recent lectures at /", async () => {
    mockApi({ "GET /auth/me": { data: fakeUser }, "GET /lectures": { data: [lecture] } });
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const label of ["Dashboard", "Upload lecture", "Analytics", "LLMOps"]) expect(nav).toHaveTextContent(label);
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Intro to Serverless" })).toHaveAttribute("href", "/lectures/abc");
    expect(await screen.findByText("Ada")).toBeInTheDocument();
  });

  it("redirects a lecture to its transcript tab and shows all six tabs", async () => {
    mockApi({
      "GET /auth/me": { data: fakeUser },
      "GET /lectures": { data: [lecture] },
      "GET /lectures/abc": { data: lecture },
      "GET /lectures/abc/transcript": {
        data: { lecture_id: "abc", duration_sec: 291.8, language: "English", segments: [{ id: 0, start: 0, end: 2.3, text: "Hello class" }] },
      },
    });
    const { router } = renderApp("/lectures/abc");
    expect(await screen.findByRole("heading", { level: 1, name: "Intro to Serverless" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/lectures/abc/transcript");
    const tabs = screen.getByRole("navigation", { name: "Lecture tabs" });
    for (const label of ["Transcript", "Summary & Notes", "Quiz", "Ask", "Flashcards", "Mind Map"]) {
      expect(tabs).toHaveTextContent(label);
    }
    expect(await screen.findByText("Hello class")).toBeInTheDocument();
  });

  it("renders auth pages outside the shell", () => {
    renderApp("/login", { loggedIn: false });
    expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("shows a 404 for unknown routes", () => {
    mockApi({ "GET /auth/me": { data: fakeUser }, "GET /lectures": { data: [] } });
    renderApp("/nope");
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
