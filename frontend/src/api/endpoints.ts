/**
 * One typed function per backend route (docs/api.md). Pages use these through the hooks in
 * hooks.ts; nothing else calls axios directly.
 */
import type { AxiosProgressEvent } from "axios";

import { api } from "./client";
import type {
  AskResponse,
  ChatHistoryOut,
  ChatRequest,
  ChatResponse,
  ChatSessionOut,
  DeckOut,
  FlashcardOut,
  GenerateQuizRequest,
  GeneratorOut,
  QuizOut,
  QuizSummaryOut,
  SubmitQuizRequest,
  SubmitQuizResponse,
  LectureOut,
  LectureStatusOut,
  LoginRequest,
  NotesResponse,
  RegisterRequest,
  SummaryResponse,
  TokenResponse,
  TranscriptFormat,
  TranscriptOut,
  UploadResponse,
  UserOut,
} from "./types";

/** A downloaded file plus the name the backend suggested in Content-Disposition. */
export interface DownloadedFile {
  blob: Blob;
  filename: string | null;
}

export function filenameFromDisposition(header: string | undefined | null): string | null {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) return decodeURIComponent(star[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}

// ------------------------------------------------------------------ auth
export async function register(body: RegisterRequest): Promise<UserOut> {
  return (await api.post<UserOut>("/auth/register", body)).data;
}

export async function login(body: LoginRequest): Promise<TokenResponse> {
  return (await api.post<TokenResponse>("/auth/login", body, { skipAuthRedirect: true })).data;
}

export async function getMe(): Promise<UserOut> {
  return (await api.get<UserOut>("/auth/me")).data;
}

// ------------------------------------------------------------------ lectures
export async function uploadLecture(
  file: File,
  opts: { title?: string; signal?: AbortSignal; onProgress?: (fraction: number) => void } = {},
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  if (opts.title?.trim()) form.append("title", opts.title.trim());
  const res = await api.post<UploadResponse>("/lectures/upload", form, {
    signal: opts.signal,
    onUploadProgress: (e: AxiosProgressEvent) => {
      if (opts.onProgress && e.total) opts.onProgress(Math.min(1, e.loaded / e.total));
    },
  });
  return res.data;
}

export async function listLectures(): Promise<LectureOut[]> {
  return (await api.get<LectureOut[]>("/lectures")).data;
}

export async function getLecture(id: string): Promise<LectureOut> {
  return (await api.get<LectureOut>(`/lectures/${id}`)).data;
}

export async function getLectureStatus(id: string): Promise<LectureStatusOut> {
  return (await api.get<LectureStatusOut>(`/lectures/${id}/status`)).data;
}

export async function deleteLecture(id: string): Promise<void> {
  await api.delete(`/lectures/${id}`);
}

// ------------------------------------------------------------------ transcript + media
export async function getTranscript(id: string): Promise<TranscriptOut> {
  return (await api.get<TranscriptOut>(`/lectures/${id}/transcript`)).data;
}

export async function downloadTranscript(id: string, format: TranscriptFormat): Promise<DownloadedFile> {
  const res = await api.get<Blob>(`/lectures/${id}/transcript/download`, {
    params: { format },
    responseType: "blob",
  });
  return { blob: res.data, filename: filenameFromDisposition(res.headers["content-disposition"] as string) };
}

/** The original recording as a blob (needs the Bearer header, so it can't be a plain <audio src>). */
export async function getMedia(id: string, signal?: AbortSignal): Promise<Blob> {
  return (await api.get<Blob>(`/lectures/${id}/media`, { responseType: "blob", signal })).data;
}

// ------------------------------------------------------------------ summary + notes
/** Cached → instant. Otherwise runs the LLM synchronously (can take minutes on the free tier). */
export async function summarize(id: string, regenerate = false): Promise<SummaryResponse> {
  return (await api.post<SummaryResponse>(`/lectures/${id}/summarize`, { regenerate })).data;
}

export async function getNotes(id: string): Promise<NotesResponse> {
  return (await api.get<NotesResponse>(`/lectures/${id}/notes`)).data;
}

// ------------------------------------------------------------------ quizzes
/** Generates a new quiz (LLM call; answers are hidden until submit). */
export async function generateQuiz(id: string, body: GenerateQuizRequest): Promise<QuizOut> {
  return (await api.post<QuizOut>(`/lectures/${id}/generate-quiz`, body)).data;
}

export async function listQuizzes(id: string): Promise<QuizSummaryOut[]> {
  return (await api.get<QuizSummaryOut[]>(`/lectures/${id}/quizzes`)).data;
}

export async function getQuiz(quizId: string): Promise<QuizOut> {
  return (await api.get<QuizOut>(`/quizzes/${quizId}`)).data;
}

/** Grades the answers (short answers use the LLM judge, so this can be slow on the free tier). */
export async function submitQuiz(quizId: string, body: SubmitQuizRequest): Promise<SubmitQuizResponse> {
  return (await api.post<SubmitQuizResponse>(`/quizzes/${quizId}/submit`, body)).data;
}

// ------------------------------------------------------------------ flashcards
/** Returns the stored deck (cached) or generates one; `regenerate` replaces it and resets progress. */
export async function generateDeck(id: string, regenerate = false): Promise<DeckOut> {
  return (await api.post<DeckOut>(`/lectures/${id}/flashcards`, { regenerate })).data;
}

export async function getDeck(id: string, dueOnly = false): Promise<DeckOut> {
  return (await api.get<DeckOut>(`/lectures/${id}/flashcards`, { params: { due: dueOnly } })).data;
}

export async function reviewCard(cardId: string, knew: boolean): Promise<FlashcardOut> {
  return (await api.post<FlashcardOut>(`/flashcards/${cardId}/review`, { knew })).data;
}

// ------------------------------------------------------------------ ask / chat
export async function ask(id: string, question: string, model: string): Promise<AskResponse> {
  return (await api.post<AskResponse>(`/lectures/${id}/ask`, { question, model })).data;
}

export async function sendChat(id: string, body: ChatRequest): Promise<ChatResponse> {
  return (await api.post<ChatResponse>(`/lectures/${id}/chat`, body)).data;
}

export async function listChatSessions(id: string): Promise<ChatSessionOut[]> {
  return (await api.get<ChatSessionOut[]>(`/lectures/${id}/chat`)).data;
}

export async function getChatHistory(id: string, sessionId: string): Promise<ChatHistoryOut> {
  return (await api.get<ChatHistoryOut>(`/lectures/${id}/chat/${sessionId}`)).data;
}

export async function listModels(): Promise<GeneratorOut[]> {
  return (await api.get<GeneratorOut[]>("/models")).data;
}
