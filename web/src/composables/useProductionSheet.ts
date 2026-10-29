import { computed, type Ref } from 'vue'

type ProductionSheetOptions = {
  /** 没有分配行时，用框码上的销售来源补订单号。打印页才会传入。 */
  salesOrderNoFallback?: () => string
}

const SIZE_MATCH_KIND_LABELS = [
  { key: 'outsole', label: '大底' },
  { key: 'midsole', label: '中底' },
  { key: 'heel', label: '鞋跟' },
  { key: 'last', label: '鞋楦' },
]

function compareSizeValue(a: unknown, b: unknown) {
  return String(a || '').localeCompare(String(b || ''), 'zh-CN', { numeric: true })
}

function processSortValue(value: unknown, fallback = Number.MAX_SAFE_INTEGER) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : fallback
}

export function formatMaterialQty(value: unknown) {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return '—'
  return numberValue.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function materialProcess(material: any) {
  return material?.consume_segment_name || material?.consume_process_name || '—'
}

function customerSizeQty(row: any, size: any) {
  const allocated = row?.size_quantities?.[String(size.id)]
  const total = Number(allocated ?? size.total_qty ?? size.qty ?? 0)
  return total > 0 ? total : ''
}

function brandImageKey(line: any) {
  const name = String(line?.brand_name || '').trim()
  const urls = [...new Set((line?.brand_logo_urls || []).filter(Boolean).map((url: unknown) => String(url)))].sort()
  return `${name}\u0001${urls.join('\u0001')}`
}

function uniqueBrandImageLines(lines: any[], seen: Set<string>) {
  const result: any[] = []
  for (const line of lines || []) {
    const urls = [...new Set((line?.brand_logo_urls || []).filter(Boolean).map((url: unknown) => String(url)))]
    if (!urls.length) continue
    const next = { brand_name: String(line?.brand_name || '').trim(), brand_logo_urls: urls }
    const key = brandImageKey(next)
    if (seen.has(key)) continue
    seen.add(key)
    result.push(next)
  }
  return result
}

/** 与打印生产单同一套字段：订单配码、码数配套、物料、做货要求、工艺路线。 */
export function useProductionSheet(detail: Ref<any>, options: ProductionSheetOptions = {}) {
  const displayNo = computed(
    () => detail.value?.header_no || detail.value?.execution_no || detail.value?.order_no || '—',
  )

  const assortmentSizeLines = computed(() => {
    const lines = detail.value?.size_lines || detail.value?.items || []
    return [...lines].sort((a, b) => compareSizeValue(a?.size_value, b?.size_value))
  })

  const recutSizeLines = computed(() => {
    const recut = detail.value?.recut_detail
    if (!recut) return []
    const lines = Array.isArray(recut.size_lines) && recut.size_lines.length
      ? recut.size_lines
      : [{
          defect_event_id: recut.defect_event_id,
          size_id: recut.size_id,
          size_value: recut.size_value,
          left_qty: Number(recut.left_qty || 0),
          right_qty: Number(recut.right_qty || 0),
          qty: Number(recut.total_pieces || 0),
        }]
    return [...lines].sort((a, b) =>
      String(a.size_value || '').localeCompare(String(b.size_value || ''), 'zh-CN', { numeric: true }),
    )
  })

  const recutTotalPieces = computed(() =>
    recutSizeLines.value.reduce(
      (total, line) => total + Number(line.qty ?? (Number(line.left_qty || 0) + Number(line.right_qty || 0))),
      0,
    ),
  )

  const assortmentColumnStyle = computed(() => ({
    width: `${28 / Math.max(1, assortmentSizeLines.value.length)}%`,
  }))

  const customerLabel = computed(() => {
    const d = detail.value
    if (!d) return ''
    if (Array.isArray(d.customers) && d.customers.length) return d.customers.join(' / ')
    return d.customer_name || ''
  })

  const salesOrderLabel = computed(() => {
    const d = detail.value
    if (!d) return ''
    if (Array.isArray(d.sales_order_nos) && d.sales_order_nos.length) {
      return d.sales_order_nos.join(' / ')
    }
    return d.sales_order_no || options.salesOrderNoFallback?.() || ''
  })

  const orderSummaryRows = computed(() => {
    const rows = detail.value?.allocation_rows
    if (Array.isArray(rows) && rows.length) return rows
    return [{
      sales_order_no: salesOrderLabel.value,
      customer_name: customerLabel.value,
      fabric: detail.value?.fabric,
      lining: detail.value?.lining,
      brand_name: detail.value?.brand_name,
      brand_logo_urls: [],
      customer_sku: detail.value?.customer_sku,
      line_notes: detail.value?.line_notes,
      order_notes: detail.value?.work_requirement?.notes,
      carton_qty: detail.value?.carton_qty,
      total_qty: detail.value?.total_qty,
      delivery_date: detail.value?.delivery_date,
      size_quantities: {},
      size_matches: detail.value?.line_size_matches || {},
    }]
  })

  function sharedLineText(field: 'fabric' | 'lining') {
    const values: string[] = []
    for (const row of orderSummaryRows.value) {
      const text = String(row?.[field] || '').trim()
      if (text && !values.includes(text)) values.push(text)
    }
    return values.join('、') || '—'
  }

  const sharedFabric = computed(() => sharedLineText('fabric'))
  const sharedLining = computed(() => sharedLineText('lining'))

  const mergedOrderCount = computed(() => {
    const ids = new Set(
      orderSummaryRows.value.map((row: any) => row.sales_order_id || row.sales_order_no).filter(Boolean),
    )
    return ids.size || 1
  })

  function assortmentQty(row: any, size: any) {
    const allocated = row?.size_quantities?.[String(size.id)]
    const total = Number(allocated ?? size.total_qty ?? size.qty ?? 0)
    const cartons = Number(row?.carton_qty || 0)
    if (!cartons) return total || '—'
    return total % cartons === 0 ? total / cartons : '—'
  }

  const processes = computed(() => {
    const d = detail.value
    if (!d) return []
    if (d.is_recut && Array.isArray(d.recut_processes)) return d.recut_processes
    if (Array.isArray(d.processes) && d.processes.length) return d.processes
    if (Array.isArray(d.process_progress) && d.process_progress.length) return d.process_progress
    return []
  })

  const processRows = computed((): any[] => {
    const rows = processes.value.map((process: any, index: number) => ({
      ...process,
      segmentLabel: String(process?.segment_name || '').trim() || '未分段',
      segmentRowspan: 0,
      _index: index,
    }))
    rows.sort((a: any, b: any) => {
      const segmentDelta = processSortValue(a.segment_sort_order) - processSortValue(b.segment_sort_order)
      if (segmentDelta) return segmentDelta
      const segmentIdDelta = processSortValue(a.segment_id) - processSortValue(b.segment_id)
      if (segmentIdDelta) return segmentIdDelta
      const routeDelta = processSortValue(a.route_sort_order) - processSortValue(b.route_sort_order)
      if (routeDelta) return routeDelta
      return a._index - b._index
    })
    let index = 0
    while (index < rows.length) {
      let next = index + 1
      while (next < rows.length && rows[next].segmentLabel === rows[index].segmentLabel) next += 1
      rows[index].segmentRowspan = next - index
      index = next
    }
    return rows
  })

  const materials = computed(() =>
    detail.value?.is_recut && Array.isArray(detail.value?.recut_materials)
      ? detail.value.recut_materials
      : (Array.isArray(detail.value?.materials) ? detail.value.materials : []),
  )

  const materialSizeColumns = computed(() => {
    const present = new Set<string>()
    for (const material of materials.value) {
      const size = String(material?.size_value || '').trim()
      if (size) present.add(size)
    }
    if (!present.size) return []
    const ordered: string[] = []
    for (const line of assortmentSizeLines.value) {
      const size = String(line?.size_value || '').trim()
      if (size && present.has(size) && !ordered.includes(size)) ordered.push(size)
    }
    const rest = [...present].filter((size) => !ordered.includes(size))
    rest.sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true }))
    return [...ordered, ...rest]
  })

  const materialRows = computed(() => {
    const groups = new Map<string, any>()
    for (const material of materials.value) {
      const key = [
        material?.supplier_product_id || material?.supplier_product_code || '',
        material?.color_name || '',
        material?.pricing_unit_name || '',
        materialProcess(material),
        material?.is_customer_supplied ? '1' : '0',
      ].join('\u0001')
      let group = groups.get(key)
      if (!group) {
        group = {
          key,
          code: material?.supplier_product_code || '',
          name: material?.supplier_product_name || '',
          color: material?.color_name || '',
          unit: material?.pricing_unit_name || '',
          department: materialProcess(material) === '—' ? '' : materialProcess(material),
          customerSupplied: Boolean(material?.is_customer_supplied),
          sizeQty: {} as Record<string, number>,
          sizeUsage: {} as Record<string, number>,
          usages: [] as number[],
          totalQty: 0,
        }
        groups.set(key, group)
      }
      const qty = Number(material?.required_qty)
      const usage = Number(material?.qty_per_pair)
      if (Number.isFinite(qty)) group.totalQty += qty
      if (Number.isFinite(usage) && !group.usages.includes(usage)) group.usages.push(usage)
      const size = String(material?.size_value || '').trim()
      if (size && Number.isFinite(qty)) {
        group.sizeQty[size] = (group.sizeQty[size] || 0) + qty
        if (Number.isFinite(usage)) group.sizeUsage[size] = usage
      }
    }
    return [...groups.values()].map((group) => ({
      ...group,
      usageLabel: group.usages.length === 1 ? formatMaterialQty(group.usages[0]) : group.usages.length ? '按码' : '—',
    }))
  })

  const materialColumnCount = computed(() => 8 + materialSizeColumns.value.length)

  const sizeMatchBlocks = computed(() => {
    const blocks: any[] = []
    for (const row of orderSummaryRows.value) {
      const matches = row?.size_matches
      if (!matches || typeof matches !== 'object') continue
      const kinds = SIZE_MATCH_KIND_LABELS
        .map((kind) => ({ ...kind, map: matches[kind.key] || {} }))
        .filter((kind) => Object.keys(kind.map).length)
      if (!kinds.length) continue
      const sizes: { key: string; label: string; qty: string | number }[] = []
      for (const line of assortmentSizeLines.value) {
        const label = String(line?.size_value || '').trim()
        if (!label || sizes.some((size) => size.label === label)) continue
        const qty = customerSizeQty(row, line)
        if (qty === '') continue
        sizes.push({ key: String(line.size_id || line.id || label), label, qty })
      }
      sizes.sort((a, b) => compareSizeValue(a.label, b.label))
      blocks.push({
        key: row.sales_order_line_id || row.sales_order_no || blocks.length,
        sales_order_no: row.sales_order_no || '',
        sizes,
        kinds,
      })
    }
    return blocks.filter((block) => block.sizes.length)
  })

  const workReqs = computed(() => {
    const d = detail.value
    if (!d) return []
    if (Array.isArray(d.work_requirements) && d.work_requirements.length) return d.work_requirements
    if (d.work_requirement && Object.keys(d.work_requirement).length) return [d.work_requirement]
    return []
  })

  const workReqBlocks = computed(() => {
    const reqByKey = new Map<string, any>()
    for (const req of workReqs.value) {
      const keys = [req?.sales_order_id, req?.sales_order_no].filter((value) => value != null && value !== '')
      for (const key of keys) reqByKey.set(String(key), req)
    }
    const groups = new Map<string, any>()
    for (const row of orderSummaryRows.value) {
      const key = String(row?.sales_order_id || row?.sales_order_no || 'order')
      let block = groups.get(key)
      if (!block) {
        const req = reqByKey.get(key) || reqByKey.get(String(row?.sales_order_no || '')) || {}
        block = {
          key,
          sales_order_no: row?.sales_order_no || req.sales_order_no || '',
          notes: String(req.notes || row?.order_notes || '').trim(),
          image_url: req.image_url || '',
          lines: [] as any[],
        }
        groups.set(key, block)
      }
      const logos = Array.isArray(row?.brand_logo_urls) ? row.brand_logo_urls.filter(Boolean) : []
      block.lines.push({
        brand_name: row?.brand_name || '',
        brand_logo_urls: logos,
      })
    }
    for (const req of workReqs.value) {
      const key = String(req?.sales_order_id || req?.sales_order_no || '')
      if (!key || groups.has(key)) continue
      groups.set(key, {
        key,
        sales_order_no: req.sales_order_no || '',
        notes: String(req.notes || '').trim(),
        image_url: req.image_url || '',
        lines: [],
      })
    }
    const blocks = [...groups.values()].filter(
      (block) => block.notes || block.image_url || block.lines.some((line: any) => line.brand_logo_urls.length),
    )
    const seenBrandImages = new Set<string>()
    const shareBrandImages = mergedOrderCount.value > 1
    for (const block of blocks) {
      const seen = shareBrandImages ? seenBrandImages : new Set<string>()
      block.lines = uniqueBrandImageLines(block.lines, seen)
    }
    return blocks
  })

  function brandImageLines(block: any) {
    return (block?.lines || []).filter((line: any) => (line.brand_logo_urls || []).length)
  }

  return {
    displayNo,
    assortmentSizeLines,
    recutSizeLines,
    recutTotalPieces,
    assortmentColumnStyle,
    sharedFabric,
    sharedLining,
    assortmentQty,
    orderSummaryRows,
    processRows,
    formatMaterialQty,
    materialSizeColumns,
    materialRows,
    materialColumnCount,
    sizeMatchBlocks,
    workReqBlocks,
    brandImageLines,
  }
}
