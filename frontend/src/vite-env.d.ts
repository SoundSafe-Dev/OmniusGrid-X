/// <reference types="vite/client" />

// Typed Vite env so `import.meta.env.VITE_*` typechecks across the app
// (was absent on this branch, so every import.meta.env use errored under tsc).
interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_WS_URL?: string
  readonly VITE_USE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
