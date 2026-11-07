import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const lecture = {
  id: "abc", title: "Intro to Serverless", original_filename: "intro.mp3", status: "ready", progress: 100,
  stage_detail: null, error: null, duration_sec: 120, language: "English", size_bytes: 2048,
  created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
};
const transcript = {
  lecture_id: "abc",
  duration_sec: 120,
  language: "English",
  segments: [
    { id: 0, start: 0, end: 4, text: "Welcome to serverless computing." },
    { id: 1, start: 4, end: 9, text: "There are two types: BaaS and FaaS." },
    { id: 2, start: 65, end: 70, text: "Functions run on demand." },
  ],
};

function routes() {
  return {
    "GET /auth/me": { data: fakeUser },
    "GET /lectures": { data: [lecture] },
    "GET /lectures/abc": { data: lecture },
    "GET /lectures/abc/transcript": { data: transcript },
    "GET /lectures/abc/media": { data: new Blob(["ID3"], { type: "audio/mpeg" }) },
  };
}

describe("TranscriptPage", () => {
  beforeEach(() => {
    // jsdom has no object URLs.
    URL.createObjectURL = vi.fn(() => "blob:fake");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("searches segments and highlights matches", async () => {
    mockApi(routes());
    renderApp("/lectures/abc/transcript");
    const list = await screen.findByRole("list", { name: "Transcript segments" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search the transcript" }), { target: { value: "faas" } });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(list.querySelector("mark")).toHaveTextContent("FaaS");
    expect(screen.getByText(/1 match$/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "kubernetes" } });
    expect(screen.getByText('No segments match "kubernetes"')).toBeInTheDocument();
  });

  it("does not download the recording until a timestamp or play is clicked", async () => {
    const mock = mockApi(routes());
    renderApp("/lectures/abc/transcript");
    await screen.findByText("Functions run on demand.");
    expect(screen.getByText(/only when you press play/)).toBeInTheDocument();
    expect(mock.calls.some((c) => c.url === "/lectures/abc/media")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Play from 01:05" }));
    await waitFor(() => expect(document.querySelector("audio")).toHaveAttribute("src", "blob:fake"));
    const mediaCalls = mock.calls.filter((c) => c.url === "/lectures/abc/media");
    expect(mediaCalls).toHaveLength(1);
    expect(mediaCalls[0].responseType).toBe("blob");
    expect(mediaCalls[0].headers.get("Authorization")).toBe("Bearer test-token");
  });

  it("highlights the segment from a ?t= link", async () => {
    mockApi(routes());
    renderApp("/lectures/abc/transcript?t=6");
    const item = (await screen.findByText("There are two types: BaaS and FaaS.")).closest("li");
    expect(item).toHaveAttribute("aria-current", "true");
    expect(screen.getByText(/Starts at 00:06/)).toBeInTheDocument();
  });
});
