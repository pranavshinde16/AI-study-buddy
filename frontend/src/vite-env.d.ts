/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Upload limit in MB shown in the browser (keep equal to the backend's MAX_UPLOAD_MB). */
  readonly VITE_MAX_UPLOAD_MB?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
