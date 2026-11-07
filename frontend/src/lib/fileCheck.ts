import { config } from "@/config";
import { formatBytes } from "./format";

/** Quick browser-side checks before uploading. The backend repeats them and also runs ffprobe. */
export function checkLectureFile(file: File, maxMb = config.maxUploadMb): string | null {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  if (!(config.allowedExtensions as readonly string[]).includes(ext)) {
    return `"${file.name}" isn't supported. Upload an MP3, WAV, MP4 or M4A file.`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > maxMb * 1024 * 1024) {
    return `"${file.name}" is ${formatBytes(file.size)}; the limit is ${maxMb} MB.`;
  }
  return null;
}
