/// <reference types="@dcloudio/types" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, any>
  export default component
}

declare const plus: {
  os: { name: string }
  navigator: {
    setFullscreen(hidden: boolean): void
  }
  runtime: {
    appid: string
    version: string
    versionCode: string | number
    openURL(url: string): void
    restart(): void
    getProperty(
      appid: string,
      success: (info: { version?: string; versionCode?: string | number }) => void,
      fail?: (err: { message?: string }) => void,
    ): void
    install(
      path: string,
      options: { force?: boolean },
      success?: () => void,
      fail?: (err: { message?: string }) => void,
    ): void
  }
  downloader: {
    createDownload(
      url: string,
      options: { filename?: string },
      callback: (download: { filename?: string }, status: number) => void,
    ): {
      start(): void
      addEventListener(
        name: string,
        callback: (task: { downloadedSize?: number; totalSize?: number }) => void,
      ): void
    }
  }
  nativeUI: {
    showWaiting(title: string): { setTitle(title: string): void; close(): void }
    alert(message: string, callback?: () => void, title?: string, button?: string): void
    confirm(
      message: string,
      callback: (event: { index: number }) => void,
      title?: string,
      buttons?: string[],
    ): void
  }
  io: {
    resolveLocalFileSystemURL(
      url: string,
      success: (entry: { remove: (ok: () => void, err?: () => void) => void }) => void,
      fail: () => void,
    ): void
  }
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_H5_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
