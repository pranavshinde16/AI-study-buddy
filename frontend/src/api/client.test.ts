import { AxiosError } from "axios";
import { describe, expect, it, vi } from "vitest";

import { errorBody, mockApi } from "@/test/mockApi";
import { getToken, setToken } from "./auth";
import { ApiError, setUnauthorizedHandler } from "./client";
import * as ep from "./endpoints";

describe("api client", () => {
  it("sends the Bearer token and returns typed data", async () => {
    setToken("abc.def", 60);
    const mock = mockApi({
      "GET /lectures": { data: [{ id: "l1", title: "Week 1" }] },
    });
    const lectures = await ep.listLectures();
    expect(lectures[0].title).toBe("Week 1");
    expect(mock.calls[0].headers.get("Authorization")).toBe("Bearer abc.def");
  });

  it("sends no Authorization header when logged out", async () => {
    const mock = mockApi({ "POST /auth/register": { status: 201, data: { id: "u1" } } });
    await ep.register({ email: "a@b.co", password: "long-enough" });
    expect(mock.calls[0].headers.get("Authorization")).toBeUndefined();
  });

  it("turns the error envelope into an ApiError with code, message, details and Retry-After", async () => {
    mockApi({
      "POST /lectures/l1/summarize": {
        status: 429,
        data: errorBody("RATE_LIMITED", "Groq is rate limiting", { provider: "groq" }),
        headers: { "retry-after": "12" },
      },
    });
    const err = await ep.summarize("l1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 429,
      code: "RATE_LIMITED",
      message: "Groq is rate limiting",
      details: { provider: "groq" },
      retryAfter: 12,
    });
  });

  it("reads the envelope from a Blob body (downloads and media)", async () => {
    const body = new Blob([JSON.stringify(errorBody("MEDIA_NOT_FOUND", "gone"))], { type: "application/json" });
    mockApi({ "GET /lectures/l1/media": { status: 404, data: body } });
    await expect(ep.getMedia("l1")).rejects.toMatchObject({ status: 404, code: "MEDIA_NOT_FOUND", message: "gone" });
  });

  it("handles non-envelope errors and network failures", async () => {
    mockApi({ "GET /lectures/x": { status: 500, data: "<html>oops</html>" } });
    await expect(ep.getLecture("x")).rejects.toMatchObject({ status: 500, code: "HTTP_ERROR" });

    // Vite's proxy answers a bare 502 when the backend isn't running (ECONNREFUSED).
    mockApi({ "POST /auth/register": { status: 502, data: "" } });
    await expect(ep.register({ email: "a@b.co", password: "long-enough" })).rejects.toMatchObject({
      status: 502,
      code: "BACKEND_UNREACHABLE",
    });
    // A real backend 503 keeps its own code.
    mockApi({ "GET /lectures/z": { status: 503, data: errorBody("MODEL_UNAVAILABLE", "Ollama is not running") } });
    await expect(ep.getLecture("z")).rejects.toMatchObject({ code: "MODEL_UNAVAILABLE" });

    mockApi({
      "GET /lectures/y": (config) => {
        throw new AxiosError("Network Error", AxiosError.ERR_NETWORK, config);
      },
    });
    await expect(ep.getLecture("y")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });

  it("on 401 clears the token and calls the unauthorized handler once", async () => {
    setToken("expired", 60);
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockApi({
      "GET /auth/me": { status: 401, data: errorBody("TOKEN_EXPIRED", "Token expired") },
      "GET /lectures": { status: 401, data: errorBody("TOKEN_EXPIRED", "Token expired") },
    });

    await expect(ep.getMe()).rejects.toMatchObject({ code: "TOKEN_EXPIRED" });
    await expect(ep.listLectures()).rejects.toMatchObject({ code: "TOKEN_EXPIRED" });
    expect(getToken()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("a wrong password on login is not treated as an expired session", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockApi({ "POST /auth/login": { status: 401, data: errorBody("INVALID_CREDENTIALS", "Invalid email or password") } });
    await expect(ep.login({ email: "a@b.co", password: "nope" })).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("drops an expired token instead of sending it", async () => {
    setToken("old", -1);
    expect(getToken()).toBeNull();
  });

  it("downloads use the file name from Content-Disposition", async () => {
    const mock = mockApi({
      "GET /lectures/l1/transcript/download": {
        data: new Blob(["1\n00:00:00,000 --> 00:00:01,000\nhi\n"]),
        headers: { "content-disposition": 'attachment; filename="Week_1.srt"' },
      },
    });
    const file = await ep.downloadTranscript("l1", "srt");
    expect(file.filename).toBe("Week_1.srt");
    expect(mock.calls[0].params).toEqual({ format: "srt" });
    expect(mock.calls[0].responseType).toBe("blob");
  });

  it("upload sends multipart form data and reports progress", async () => {
    const progress: number[] = [];
    const mock = mockApi({
      "POST /lectures/upload": (config) => {
        config.onUploadProgress?.({ loaded: 50, total: 100, bytes: 50, lengthComputable: true });
        config.onUploadProgress?.({ loaded: 100, total: 100, bytes: 50, lengthComputable: true });
        return { status: 202, data: { lecture_id: "l9", title: "T", status: "uploaded", status_url: "/api/lectures/l9/status" } };
      },
    });
    const file = new File(["abc"], "talk.mp3", { type: "audio/mpeg" });
    const res = await ep.uploadLecture(file, { title: " My talk ", onProgress: (f) => progress.push(f) });
    expect(res.lecture_id).toBe("l9");
    expect(progress).toEqual([0.5, 1]);
    const form = mock.calls[0].data as FormData;
    expect((form.get("file") as File).name).toBe("talk.mp3");
    expect(form.get("title")).toBe("My talk");
  });
});
