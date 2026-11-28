/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "api": the UI calls src/api (six-schema data layer, docs/API.md). Unset or "scout": src/suva_app. */
  readonly VITE_BACKEND?: "api" | "scout" | string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
