/// <reference types="@dcloudio/types" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, any>
  export default component
}

declare const plus: {
  runtime: {
    openURL(url: string): void
  }
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_H5_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
