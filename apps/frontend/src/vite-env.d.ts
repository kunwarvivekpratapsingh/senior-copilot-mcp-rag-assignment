/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Set at build time; defaults to http://localhost:8080. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
