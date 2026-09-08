export type ScanKind = 'station' | 'trace' | 'flow-card' | 'carton' | 'basket' | 'subcontract'

export interface ScanTarget {
  kind: ScanKind
  code: string
  h5Path: string
  label: string
  segmentCode?: 'cut' | 'stitch' | 'forming'
}

export function parseScanText(raw: string): ScanTarget | null {
  const text = String(raw || '').trim()
  if (!text) return null
  let path = text
  let segmentCode: 'cut' | 'stitch' | 'forming' | undefined
  try {
    const url = new URL(text, 'https://erp.local')
    path = url.pathname
    const segment = url.searchParams.get('segment')
    if (segment === 'cut' || segment === 'stitch' || segment === 'forming') segmentCode = segment
  } catch {
    // 裸码继续按文本识别。
  }

  const stitchFlow = path.match(/(?:^|\/)stitch-card\/(\d+)/i)
  if (stitchFlow?.[1]) return { kind: 'flow-card', code: stitchFlow[1], h5Path: `/stitch-card/${stitchFlow[1]}`, label: '针车任务单', segmentCode: 'stitch' }

  const formingFlow = path.match(/(?:^|\/)forming-card\/(\d+)/i)
  if (formingFlow?.[1]) return { kind: 'flow-card', code: formingFlow[1], h5Path: `/forming-card/${formingFlow[1]}`, label: '成型任务单', segmentCode: 'forming' }

  const flow = path.match(/(?:^|\/)flow-card\/(\d+)/i)
  if (flow?.[1]) return { kind: 'flow-card', code: flow[1], h5Path: `/flow-card/${flow[1]}`, label: '生产流转卡', segmentCode }

  const subcontract = path.match(/(?:^|\/)subcontract-(?:acceptance|receive)\/(\d+)/i)
  if (subcontract?.[1]) return { kind: 'subcontract', code: subcontract[1], h5Path: `/subcontract-acceptance/${subcontract[1]}`, label: '外发验收' }

  const basket = path.match(/(?:^|\/)basket\/([^/?#]+)/i)
  if (basket?.[1]) {
    const code = decodeURIComponent(basket[1]).toUpperCase()
    return { kind: 'basket', code, h5Path: `/basket/${encodeURIComponent(code)}`, label: '永久框码' }
  }

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

export function appPageForTarget(target: ScanTarget) {
  if (target.kind === 'subcontract') {
    return `/pages/subcontract-acceptance/index?id=${encodeURIComponent(target.code)}`
  }
  return `/pages/report/index?target=${encodeTarget(target)}`
}

export function decodeTarget(value?: string): ScanTarget | null {
  if (!value) return null
  try {
    return JSON.parse(decodeURIComponent(value)) as ScanTarget
  } catch {
    return null
  }
}
