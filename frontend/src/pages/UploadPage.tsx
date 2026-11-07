import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileAudio, FileVideo, Loader2, UploadCloud, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { uploadLecture } from "@/api/endpoints";
import { keys } from "@/api/hooks";
import { FormField } from "@/components/FormField";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { config } from "@/config";
import { checkLectureFile } from "@/lib/fileCheck";
import { formatBytes } from "@/lib/format";
import { notifySuccess } from "@/lib/notify";
import { cn } from "@/lib/utils";

const ACCEPT = ".mp3,.wav,.mp4,.m4a,audio/mpeg,audio/wav,audio/mp4,video/mp4";

export function UploadPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);

  const upload = useMutation({
    mutationFn: (f: File) => {
      abortRef.current = new AbortController();
      return uploadLecture(f, { title, signal: abortRef.current.signal, onProgress: setProgress });
    },
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: keys.lectures });
      notifySuccess("Upload complete", `"${res.title}" is being processed.`);
      navigate(`/lectures/${res.lecture_id}/processing`);
    },
    onSettled: () => {
      abortRef.current = null;
    },
  });

  function pick(f: File | undefined | null) {
    if (!f) return;
    upload.reset();
    setProgress(0);
    const err = checkLectureFile(f);
    setFileError(err);
    setFile(err ? null : f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (upload.isPending) return;
    pick(e.dataTransfer.files?.[0]);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (file) upload.mutate(file);
  }

  function clearFile() {
    setFile(null);
    setFileError(null);
    upload.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  const pct = Math.round(progress * 100);
  const FileIcon = file?.name.toLowerCase().endsWith(".mp4") ? FileVideo : FileAudio;

  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Upload lecture</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          MP3, WAV, MP4 or M4A, up to {config.maxUploadMb} MB. Transcription starts as soon as the upload finishes.
        </p>
      </header>

      <Card>
        <CardContent className="space-y-5 pt-6">
          <form className="space-y-5" onSubmit={onSubmit}>
            <div
              role="button"
              tabIndex={0}
              aria-label="Choose a lecture file or drop it here"
              aria-disabled={upload.isPending}
              onClick={() => !upload.isPending && inputRef.current?.click()}
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && !upload.isPending) {
                  e.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "flex cursor-pointer flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                dragging ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-accent/40",
                upload.isPending && "cursor-not-allowed opacity-60",
              )}
            >
              <div className="flex size-14 items-center justify-center rounded-full bg-accent text-accent-foreground">
                <UploadCloud className="size-7" />
              </div>
              <div>
                <p className="font-medium">{dragging ? "Drop to select" : "Drag and drop your recording"}</p>
                <p className="text-sm text-muted-foreground">or click to browse</p>
              </div>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                data-testid="file-input"
                tabIndex={-1}
                onChange={(e) => pick(e.target.files?.[0])}
              />
            </div>

            {fileError && (
              <p role="alert" className="rounded-xl bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {fileError}
              </p>
            )}

            {file && (
              <div className="flex items-center gap-3 rounded-xl border bg-muted/40 p-3">
                <FileIcon className="size-8 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{formatBytes(file.size)}</p>
                </div>
                {!upload.isPending && (
                  <Button type="button" variant="ghost" size="icon" aria-label="Remove file" onClick={clearFile}>
                    <X />
                  </Button>
                )}
              </div>
            )}

            <FormField
              id="title"
              label="Title (optional)"
              placeholder="Built from the file name if left empty"
              maxLength={300}
              value={title}
              disabled={upload.isPending}
              onChange={(e) => setTitle(e.target.value)}
            />

            {upload.isPending && (
              <div className="space-y-2" aria-live="polite">
                <div className="flex justify-between text-sm">
                  <span>{pct < 100 ? "Uploading…" : "Checking the file on the server…"}</span>
                  <span className="tabular-nums text-muted-foreground">{pct}%</span>
                </div>
                <Progress value={pct} label="Upload progress" />
              </div>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              {upload.isPending && (
                <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>
                  Cancel
                </Button>
              )}
              <Button type="submit" disabled={!file || upload.isPending}>
                {upload.isPending ? <Loader2 className="animate-spin" /> : <UploadCloud />}
                Upload and process
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </section>
  );
}
