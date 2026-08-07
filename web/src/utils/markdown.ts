import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({
  gfm: true,
  breaks: true,
})

/** 将 Markdown 渲染为可安全注入的 HTML（支持 GFM 表格）。 */
export function renderMarkdown(src: string): string {
  const raw = marked.parse(src || '', { async: false }) as string
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
  })
}
