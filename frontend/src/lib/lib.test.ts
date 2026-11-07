import { describe, expect, it } from "vitest";

import type { SummaryResponse } from "@/api/types";
import { checkLectureFile } from "./fileCheck";
import { formatDuration, formatTimestamp } from "./format";
import { stepModel } from "./processing";
import { safeNext } from "./safeNext";
import { summaryToMarkdown } from "./summaryMarkdown";
import { segmentAt, splitForHighlight } from "./transcript";
import { validateNewPassword } from "./validation";

describe("format", () => {
  it("formats timestamps and durations", () => {
    expect(formatTimestamp(0)).toBe("00:00");
    expect(formatTimestamp(75.9)).toBe("01:15");
    expect(formatTimestamp(3725)).toBe("1:02:05");
    expect(formatDuration(291.8)).toBe("4 min 52 s");
    expect(formatDuration(null)).toBe("–");
  });
});

describe("transcript helpers", () => {
  const segs = [
    { id: 0, start: 0, end: 2, text: "a" },
    { id: 1, start: 2, end: 5, text: "b" },
    { id: 2, start: 10, end: 12, text: "c" },
  ];
  it("finds the segment playing at a time", () => {
    expect(segmentAt(segs, 0)).toBe(0);
    expect(segmentAt(segs, 3)).toBe(1);
    expect(segmentAt(segs, 7)).toBe(1); // gap: keep the last started segment
    expect(segmentAt(segs, 11)).toBe(2);
    expect(segmentAt([], 1)).toBeNull();
  });
  it("splits text for highlighting, case-insensitively and with regex characters escaped", () => {
    expect(splitForHighlight("Big O and big data", "big")).toEqual([
      { text: "Big", match: true },
      { text: " O and ", match: false },
      { text: "big", match: true },
      { text: " data", match: false },
    ]);
    expect(splitForHighlight("cost (USD)", "(usd)")).toEqual([
      { text: "cost ", match: false },
      { text: "(USD)", match: true },
    ]);
    expect(splitForHighlight("x", "")).toEqual([{ text: "x", match: false }]);
  });
});

describe("processing stepper model", () => {
  const s = (status: string, progress = 0, error: string | null = null) =>
    ({ status, progress, error, stage_detail: null }) as Parameters<typeof stepModel>[0];
  it("maps statuses to steps", () => {
    expect(stepModel(s("uploaded"))).toEqual({ current: 0, failed: false });
    expect(stepModel(s("transcribing", 40))).toEqual({ current: 2, failed: false });
    expect(stepModel(s("generating", 85))).toEqual({ current: 4, failed: false });
    expect(stepModel(s("ready", 100))).toEqual({ current: 6, failed: false });
  });
  it("places failures on the stage that failed", () => {
    expect(stepModel(s("failed", 5, "ffmpeg error"))).toEqual({ current: 1, failed: true });
    expect(stepModel(s("failed", 40, "rate limit"))).toEqual({ current: 2, failed: true });
    expect(stepModel(s("transcribed", 100, "summary failed"))).toEqual({ current: 4, failed: true });
  });
});

describe("safeNext", () => {
  it("only allows same-app paths", () => {
    expect(safeNext("/lectures/1/notes?x=1")).toBe("/lectures/1/notes?x=1");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("/login")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});

describe("validation and file checks", () => {
  it("mirrors the backend password rules", () => {
    expect(validateNewPassword("short")).toMatch(/at least 8/);
    expect(validateNewPassword("long-enough")).toBeNull();
    expect(validateNewPassword("é".repeat(40))).toMatch(/72 bytes/); // 40 chars, 80 bytes
  });
  it("accepts only lecture media types", () => {
    expect(checkLectureFile(new File(["x"], "a.M4A"))).toBeNull();
    expect(checkLectureFile(new File(["x"], "a.mov"))).toMatch(/isn't supported/);
    expect(checkLectureFile(new File(["x"], "noext"))).toMatch(/isn't supported/);
  });
});

describe("summaryToMarkdown", () => {
  it("exports every section from the API response", () => {
    const s: SummaryResponse = {
      lecture_id: "l1",
      summary: "Serverless explained.",
      key_takeaways: ["BaaS and FaaS"],
      definitions: [
        { term: "FaaS", definition: "Functions as a service", timestamp: 49 },
        { term: "BaaS", definition: "Backend as a service", timestamp: null },
      ],
      topics: [{ title: "Intro", start: 0, end: 168, notes_md: "- point", key_points: ["kp"] }],
      revision_notes_md: "- revise",
      meta: {} as SummaryResponse["meta"],
      cached: true,
    };
    const md = summaryToMarkdown("Week 1", s);
    expect(md).toContain("# Week 1");
    expect(md).toContain("- **FaaS**: Functions as a service _(at 00:49)_");
    expect(md).toContain("- **BaaS**: Backend as a service\n");
    expect(md).toContain("### Intro (00:00–02:48)");
    expect(md).toContain("## Revision notes\n\n- revise");
    expect(md.endsWith("\n")).toBe(true);
  });
});
