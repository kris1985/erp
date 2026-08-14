import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({
  gfm: true,
  breaks: true,
})

const RISK_TAGS: { label: string; cls: string }[] = [
  { label: '预计逾期', cls: 'is-late' },
  { label: '交期偏紧', cls: 'is-tight' },
  { label: '缺料卡住', cls: 'is-kit' },
  { label: '产能不足', cls: 'is-cap' },
  { label: '回款风险高', cls: 'is-pay' },
  { label: '回款需关注', cls: 'is-pay' },
]

function wrapMarkdownTables(html: string): string {
  return html.replace(/<table\b[\s\S]*?<\/table>/gi, (table) => {
    return `<div class="sa-md-table"><div class="sa-md-table-scroll">${table}</div></div>`
  })
}

/** 表格里的「急」统一成警示徽章；去掉 ✅ 等通过语义 */
function enhanceRushCells(html: string): string {
  return html.replace(/<td\b([^>]*)>([\s\S]*?)<\/td>/gi, (_m, attrs: string, inner: string) => {
    const text = inner.replace(/<[^>]+>/g, '').replace(/\s+/g, '').trim()
    const normalized = text.replace(/[✅✔☑✓✔️]/g, '')
    if (normalized === '急' || normalized === '急单' || normalized === '是急') {
      return `<td${attrs}><span class="sa-badge sa-badge-rush">急</span></td>`
    }
    if (normalized === '否' || normalized === '否急' || normalized === '-' || normalized === '—') {
      return `<td${attrs}><span class="sa-badge sa-badge-muted">—</span></td>`
    }
    // 单元格里夹着 ✅急
    if (/[✅✔☑✓]/.test(inner) && /急/.test(inner) && inner.length < 40) {
      return `<td${attrs}><span class="sa-badge sa-badge-rush">急</span></td>`
    }
    return `<td${attrs}>${inner}</td>`
  })
}

/** 风险列表项加语义条 */
function enhanceRiskItems(html: string): string {
  return html.replace(/<li\b([^>]*)>([\s\S]*?)<\/li>/gi, (full, attrs: string, inner: string) => {
    const plain = inner.replace(/<[^>]+>/g, '').trim()
    for (const { label, cls } of RISK_TAGS) {
      if (plain.startsWith(label) || plain.includes(`【${label}】`) || plain.startsWith(`**${label}`)) {
        const cleaned = inner
          .replace(new RegExp(`^\\s*(?:<p>)?(?:【)?(?:<strong>)?${label}(?:</strong>)?(?:】)?[：:\\s]*`), '')
          .replace(new RegExp(`^\\s*${label}[：:\\s]*`), '')
        return (
          `<li class="sa-risk-item ${cls}"${attrs}>` +
          `<span class="sa-risk-tag">${label}</span>` +
          `<span class="sa-risk-body">${cleaned || inner}</span>` +
          `</li>`
        )
      }
    }
    return full
  })
}

/** 决策摘要中的订单、物料与日期用低干扰标签标出，便于车间现场扫读。 */
function emphasizeDecisionEntities(html: string): string {
  const host = document.createElement('div')
  host.innerHTML = html
  const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)

  const entityPattern = /\b\d{6}\b|\b\d{1,2}\/\d{1,2}\b|\b\d+(?:\.\d+)?%|已逾期|逾期|挤爆|超产能|产能不足|缺料|(?:头层牛皮|头层牛革|\S{1,6}(?:牛皮|羊皮|猪皮|皮革|面料|里料|辅料))/g
  for (const node of nodes) {
    const parent = node.parentElement
    if (!parent || parent.closest('code, pre, table, mark')) continue
    const text = node.data
    const matches = [...text.matchAll(entityPattern)]
    if (!matches.length) continue
    const fragment = document.createDocumentFragment()
    let offset = 0
    for (const match of matches) {
      const index = match.index ?? 0
      if (index > offset) fragment.append(text.slice(offset, index))
      const mark = document.createElement('mark')
      const value = match[0]
      const isRisk = /^(?:\d+(?:\.\d+)?%|已逾期|逾期|挤爆|超产能)$/.test(value)
      const isWarn = /^(?:产能不足|缺料)$/.test(value)
      mark.className = [
        'sa-entity',
        value.includes('/') ? 'sa-entity-date' : '',
        isRisk ? 'sa-entity-risk' : '',
        isWarn ? 'sa-entity-warn' : '',
      ].filter(Boolean).join(' ')
      mark.textContent = match[0]
      fragment.append(mark)
      offset = index + match[0].length
    }
    if (offset < text.length) fragment.append(text.slice(offset))
    node.replaceWith(fragment)
  }
  return host.innerHTML
}

/** 将 Markdown 渲染为可安全注入的 HTML（支持 GFM 表格）。 */
export function renderMarkdown(src: string): string {
  const raw = marked.parse(src || '', { async: false }) as string
  let html = wrapMarkdownTables(raw)
  html = enhanceRushCells(html)
  html = enhanceRiskItems(html)
  html = emphasizeDecisionEntities(html)
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['class'],
  })
}
