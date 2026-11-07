/** Save a Blob as a file through a temporary <a download> link. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function saveText(text: string, filename: string, type = "text/markdown;charset=utf-8"): void {
  saveBlob(new Blob([text], { type }), filename);
}

/** File-system-safe name from a lecture title. */
export function safeFilename(title: string, ext: string): string {
  const base = title.replace(/[^A-Za-z0-9 ._-]+/g, "").trim().replace(/\s+/g, "_") || "lecture";
  return `${base.slice(0, 80)}.${ext}`;
}
