import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import type { InternalAxiosRequestConfig } from "axios";
import { describe, expect, it } from "vitest";

import { errorBody, mockApi } from "@/test/mockApi";
import { fakeUser, renderApp } from "@/test/render";

const base = {
  "GET /auth/me": { data: fakeUser },
  "GET /lectures": { data: [] },
};

function chooseFile(file: File) {
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });
}

describe("UploadPage", () => {
  it("rejects unsupported and oversized files before uploading", async () => {
    const mock = mockApi(base);
    renderApp("/upload");
    await screen.findByRole("heading", { name: "Upload lecture" });

    chooseFile(new File(["x"], "notes.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't supported");
    expect(screen.getByRole("button", { name: /upload and process/i })).toBeDisabled();

    const big = new File(["x"], "huge.mp3", { type: "audio/mpeg" });
    Object.defineProperty(big, "size", { value: 501 * 1024 * 1024 });
    chooseFile(big);
    expect(screen.getByRole("alert")).toHaveTextContent("the limit is 500 MB");

    chooseFile(new File([], "empty.wav", { type: "audio/wav" }));
    expect(screen.getByRole("alert")).toHaveTextContent("is empty");
    expect(mock.calls.some((c) => c.url === "/lectures/upload")).toBe(false);
  });

  it("shows upload progress, then opens the processing page", async () => {
    let finish: (() => void) | undefined;
    let uploadConfig: InternalAxiosRequestConfig | undefined;
    mockApi({
      ...base,
      "POST /lectures/upload": (config) =>
        new Promise((resolve) => {
          uploadConfig = config;
          finish = () =>
            resolve({
              status: 202,
              data: { lecture_id: "l9", title: "My talk", status: "uploaded", status_url: "/api/lectures/l9/status" },
            });
        }),
      "GET /lectures/l9": {
        data: {
          id: "l9", title: "My talk", original_filename: "talk.mp3", status: "uploaded", progress: 0,
          stage_detail: null, error: null, duration_sec: 12, language: null, size_bytes: 3,
          created_at: "2026-11-07T10:00:00Z", updated_at: "2026-11-07T10:00:00Z",
        },
      },
      "GET /lectures/l9/status": { data: { status: "transcribing", progress: 40, stage_detail: "chunk 1 of 2", error: null } },
    });
    const { router } = renderApp("/upload");
    await screen.findByRole("heading", { name: "Upload lecture" });

    chooseFile(new File(["abc"], "talk.mp3", { type: "audio/mpeg" }));
    expect(screen.getByText("talk.mp3")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Title (optional)"), { target: { value: "My talk" } });
    fireEvent.click(screen.getByRole("button", { name: /upload and process/i }));

    await waitFor(() => expect(uploadConfig).toBeDefined());
    act(() => uploadConfig!.onUploadProgress?.({ loaded: 40, total: 100, bytes: 40, lengthComputable: true }));
    const bar = screen.getByRole("progressbar", { name: "Upload progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "40");
    expect((uploadConfig!.data as FormData).get("title")).toBe("My talk");

    await act(async () => finish!());
    await waitFor(() => expect(router.state.location.pathname).toBe("/lectures/l9/processing"));
    expect(await screen.findByText("chunk 1 of 2")).toBeInTheDocument();
  });

  it("shows the backend's error when the server rejects the file", async () => {
    mockApi({
      ...base,
      "POST /lectures/upload": {
        status: 415,
        data: errorBody("UNSUPPORTED_MEDIA_TYPE", "The file has no readable audio track."),
      },
    });
    renderApp("/upload");
    await screen.findByRole("heading", { name: "Upload lecture" });
    chooseFile(new File(["abc"], "fake.mp3", { type: "audio/mpeg" }));
    fireEvent.click(screen.getByRole("button", { name: /upload and process/i }));
    // Error toast built from the envelope.
    expect(await screen.findByText("Unsupported file")).toBeInTheDocument();
    expect(screen.getByText("The file has no readable audio track.")).toBeInTheDocument();
  });
});
