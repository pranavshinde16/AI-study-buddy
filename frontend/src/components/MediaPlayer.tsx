import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { AlertTriangle, Loader2, Play, RotateCw } from "lucide-react";

import { getMedia } from "@/api/endpoints";
import { isApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { describeError } from "@/lib/notify";
import { formatBytes, formatTimestamp } from "@/lib/format";

export interface MediaPlayerHandle {
  /** Jump to `seconds` and play. Loads the recording first if needed (a click is a request to play). */
  seek: (seconds: number) => void;
}

type State = "idle" | "loading" | "ready" | "error";

/**
 * Plays the lecture recording from GET /lectures/{id}/media. Nothing is downloaded until the
 * user presses play or clicks a timestamp; the file is fetched with the Bearer token as a blob
 * and played from an object URL (fine for short demo lectures; see docs/api.md).
 */
export const MediaPlayer = forwardRef<
  MediaPlayerHandle,
  { lectureId: string; sizeBytes?: number | null; startAt?: number | null; onTime?: (seconds: number) => void }
>(function MediaPlayer({ lectureId, sizeBytes, startAt, onTime }, ref) {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<unknown>(null);
  const [src, setSrc] = useState<{ url: string; isVideo: boolean } | null>(null);
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const pendingSeek = useRef<number | null>(startAt ?? null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setState("loading");
    setError(null);
    try {
      const blob = await getMedia(lectureId, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setSrc({ url: URL.createObjectURL(blob), isVideo: blob.type.startsWith("video/") });
      setState("ready");
    } catch (err) {
      if (isApiError(err, "CANCELLED") || ctrl.signal.aborted) return;
      setError(err);
      setState("error");
    }
  }, [lectureId]);

  // Free the blob when the source changes or the page closes; stop a download in flight.
  useEffect(() => () => {
    if (src) URL.revokeObjectURL(src.url);
  }, [src]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const playFrom = (el: HTMLMediaElement, seconds: number) => {
    el.currentTime = seconds;
    // Browsers may block play() if the user gesture expired during the download; controls still work.
    void el.play()?.catch(() => undefined);
  };

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      const el = mediaRef.current;
      if (state === "ready" && el) {
        playFrom(el, seconds);
        return;
      }
      pendingSeek.current = seconds;
      if (state !== "loading") void load();
    },
  }));

  const onLoadedMetadata = () => {
    const el = mediaRef.current;
    if (!el) return;
    playFrom(el, pendingSeek.current ?? 0);
    pendingSeek.current = null;
  };

  if (state === "ready" && src) {
    const common = {
      src: src.url,
      controls: true,
      onLoadedMetadata,
      onTimeUpdate: () => onTime?.(mediaRef.current?.currentTime ?? 0),
      className: "w-full rounded-xl",
    };
    return src.isVideo ? (
      <video ref={(el) => { mediaRef.current = el; }} {...common} className="max-h-[50vh] w-full rounded-xl bg-black" />
    ) : (
      <audio ref={(el) => { mediaRef.current = el; }} {...common} />
    );
  }

  if (state === "error") {
    const missing = isApiError(error, "MEDIA_NOT_FOUND");
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm">
        <AlertTriangle className="size-4 shrink-0 text-destructive" />
        <span className="min-w-0 flex-1">
          {missing
            ? "The recording is no longer stored on the server. The transcript still works."
            : describeError(error).description}
        </span>
        {!missing && (
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RotateCw /> Retry
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-muted/40 p-3">
      <Button onClick={() => void load()} disabled={state === "loading"} aria-label="Play recording">
        {state === "loading" ? <Loader2 className="animate-spin" /> : <Play />}
        {state === "loading" ? "Loading recording…" : "Play recording"}
      </Button>
      <span className="text-xs text-muted-foreground">
        {state === "loading"
          ? "Downloading the file before playback starts."
          : `Loads the recording${sizeBytes ? ` (${formatBytes(sizeBytes)})` : ""} only when you press play.`}
        {startAt ? ` Starts at ${formatTimestamp(startAt)}.` : ""}
      </span>
      {state === "loading" && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            abortRef.current?.abort();
            setState("idle");
          }}
        >
          Cancel
        </Button>
      )}
    </div>
  );
});
