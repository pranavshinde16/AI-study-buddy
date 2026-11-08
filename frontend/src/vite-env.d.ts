/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Upload limit in MB shown in the browser (keep equal to the backend's MAX_UPLOAD_MB). */
  readonly VITE_MAX_UPLOAD_MB?: string;
  /** Keep equal to the backend's QUIZ_MAX_QUESTIONS. */
  readonly VITE_QUIZ_MAX_QUESTIONS?: string;
  /** Keep equal to the backend's RAG_MAX_QUESTION_CHARS. */
  readonly VITE_RAG_MAX_QUESTION_CHARS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
