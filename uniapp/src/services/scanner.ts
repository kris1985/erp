export type ScanKind = 'station' | 'trace' | 'flow-card' | 'carton'

export interface ScanTarget {
  kind: ScanKind
  code: string
  h5Path: string
  label: string
}

export function parseScanText(raw: string): ScanTarget | null {
  const text = String(raw || '').trim()
  if (!text) return null
  let path = text
  try {
    path = new URL(text, 'https://erp.local').pathname
  } catch {
    // 裸码继续按文本识别。
  }

  const flow = path.match(/(?:^|\/)flow-card\/(\d+)/i)
  if (flow?.[1]) return { kind: 'flow-card', code: flow[1], h5Path: `/flow-card/${flow[1]}`, label: '生产流转卡' }

  const carton = path.match(/(?:^|\/)carton-report\/([^/?#]+)/i)
  if (carton?.[1]) {
    const code = decodeURIComponent(carton[1]).toUpperCase()
    return { kind: 'carton', code, h5Path: `/carton-report/${encodeURIComponent(code)}`, label: '箱唛' }
  }

  const trace = path.match(/(?:^|\/)trace(?:-print|-report)?\/([^/?#]+)/i)
  if (trace?.[1]) {
    const code = decodeURIComponent(trace[1])
    return { kind: 'trace', code, h5Path: `/trace/${encodeURIComponent(code)}`, label: '框码/捆码' }
  }

  const station = path.match(/(?:^|\/)scan\/([^/?#]+)/i)
  if (station?.[1]) {
    const code = decodeURIComponent(station[1]).toUpperCase()
    return { kind: 'station', code, h5Path: `/scan/${encodeURIComponent(code)}`, label: '工位码' }
  }

  if (/^CTN-[A-Za-z0-9_-]+$/i.test(text)) {
    const code = text.toUpperCase()
    return { kind: 'carton', code, h5Path: `/carton-report/${encodeURIComponent(code)}`, label: '箱唛' }
  }
  if (/^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$/.test(text)) {
    const code = text.toUpperCase()
    return { kind: 'station', code, h5Path: `/scan/${encodeURIComponent(code)}`, label: '工位码' }
  }
  return null
}

export function encodeTarget(target: ScanTarget) {
  return encodeURIComponent(JSON.stringify(target))
}

export function decodeTarget(value?: string): ScanTarget | null {
  if (!value) return null
  try {
    return JSON.parse(decodeURIComponent(value)) as ScanTarget
  } catch {
    return null
  }
}
