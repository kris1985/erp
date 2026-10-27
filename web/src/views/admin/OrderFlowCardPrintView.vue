<template>
  <div class="print-page" :class="{ 'label-mode': mode === 'basket-labels' }">
    <div class="no-print actions">
      <button type="button" @click="doPrint">打印</button>
      <button
        v-if="mode === 'basket-labels' && !(units || []).length"
        type="button"
        @click="goCutCards"
      >
        去开裁生框码
      </button>
      <button type="button" class="ghost" @click="closeOrBack">关闭</button>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <template v-else-if="detail">
      <div v-if="detail.is_rush" class="watermark">急单</div>
      <div v-else-if="detail.status === 'cancelled'" class="watermark muted">已取消</div>

      <!-- A4 生产单：普通打印机 -->
      <div v-if="mode === 'flow-card'" class="sheet flow-card">
        <div class="flow-head">
          <div class="flow-head-text">
            <h1 class="doc-title">{{ detail.is_recut ? '生产单-补' : '生产单' }}</h1>
            <p class="doc-sub">
              {{ detail.is_recut ? '补单号' : '单号' }} {{ displayNo }}
            </p>
            <p v-if="detail.is_recut" class="recut-source-no">
              原生产单号 <strong>{{ detail.original_header_no || '—' }}</strong>
            </p>
            <p v-if="detail.is_recut" class="production-summary">
              <span>码数 <strong>{{ recutSizeLines.length }}</strong> 个</span>
            </p>
          </div>
          <div class="flow-qr-box">
            <img
              v-if="flowQrSrc"
              class="flow-qr"
              :src="flowQrSrc"
              alt="流转卡二维码"
            />
            <small>扫码报工</small>
          </div>
        </div>

        <table v-if="detail.is_recut" class="recut-summary-table">
          <tbody>
            <tr>
              <th>原生产单号</th>
              <td>{{ detail.original_header_no || '—' }}</td>
              <th>补生产单号</th>
              <td>{{ displayNo }}</td>
            </tr>
            <tr>
              <th>工厂型号</th>
              <td>{{ detail.product_code || '—' }}</td>
              <th>颜色</th>
              <td>{{ detail.color_name || '—' }}</td>
            </tr>
            <tr>
              <th>工艺起始</th>
              <td>{{ detail.recut_detail?.process_start_name || '—' }}</td>
              <th>补做到</th>
              <td>{{ detail.recut_detail?.process_end_name || '—' }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="detail.is_recut">
          <div class="section-title">报废码数</div>
          <table class="recut-size-table">
            <thead>
              <tr>
                <th
                  v-for="(line, index) in recutSizeLines"
                  :key="`size-${line.defect_event_id || line.size_id || index}`"
                  colspan="2"
                  class="recut-size-head"
                >
                  {{ line.size_value || '—' }}
                </th>
                <th rowspan="2" class="recut-total-head">数量</th>
              </tr>
              <tr>
                <template
                  v-for="(line, index) in recutSizeLines"
                  :key="`side-${line.defect_event_id || line.size_id || index}`"
                >
                  <th>左</th>
                  <th>右</th>
                </template>
              </tr>
            </thead>
            <tbody>
              <tr>
                <template
                  v-for="(line, index) in recutSizeLines"
                  :key="`qty-${line.defect_event_id || line.size_id || index}`"
                >
                  <td class="num">{{ Number(line.left_qty || 0) ? `${Number(line.left_qty)}只` : '' }}</td>
                  <td class="num">{{ Number(line.right_qty || 0) ? `${Number(line.right_qty)}只` : '' }}</td>
                </template>
                <td class="num recut-total"><strong>{{ recutTotalPieces }}只</strong></td>
              </tr>
            </tbody>
          </table>
        </template>

        <table v-else class="shared-attr-table">
          <colgroup>
            <col class="col-product" />
            <col class="col-image" />
            <col class="col-color" />
            <col class="col-fabric" />
            <col class="col-lining" />
          </colgroup>
          <thead>
            <tr>
              <th>工厂型号</th>
              <th class="image-col">图片</th>
              <th>颜色</th>
              <th>鞋面</th>
              <th>内里/垫脚</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="cell-code cell-wrap">{{ detail.product_code || '—' }}</td>
              <td class="image-col">
                <img
                  v-if="detail.product_image_url"
                  class="product-image"
                  :src="detail.product_image_url"
                  alt="产品图片"
                />
              </td>
              <td>{{ detail.color_name || '—' }}</td>
              <td class="cell-wrap">{{ sharedFabric }}</td>
              <td class="cell-wrap">{{ sharedLining }}</td>
            </tr>
          </tbody>
        </table>

        <table v-if="!detail.is_recut" class="order-summary-table">
          <colgroup>
            <col class="col-order-no" />
            <col class="col-customer" />
            <col class="col-brand" />
            <col class="col-customer-sku" />
            <col
              v-for="(size, idx) in assortmentSizeLines"
              :key="`col-${size.size_id || idx}`"
              :style="assortmentColumnStyle"
            />
            <col v-if="!assortmentSizeLines.length" :style="assortmentColumnStyle" />
            <col class="col-cartons" />
            <col class="col-total" />
            <col class="col-delivery" />
            <col class="col-notes" />
          </colgroup>
          <thead>
            <tr>
              <th rowspan="2">订单号</th>
              <th rowspan="2">客户</th>
              <th rowspan="2">品牌</th>
              <th rowspan="2">客户型号</th>
              <th :colspan="assortmentSizeLines.length || 1" class="assortment-head">配码</th>
              <th rowspan="2" class="num">箱数</th>
              <th rowspan="2" class="num">数量</th>
              <th rowspan="2">交货日期</th>
              <th rowspan="2">备注</th>
            </tr>
            <tr>
              <th
                v-for="(size, idx) in assortmentSizeLines"
                :key="size.size_id || idx"
                class="size-cell"
              >
                {{ size.size_value || '—' }}
              </th>
              <th v-if="!assortmentSizeLines.length" class="size-cell">—</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, rowIndex) in orderSummaryRows"
              :key="row.sales_order_line_id || rowIndex"
            >
              <td class="cell-code">{{ row.sales_order_no || '—' }}</td>
              <td class="cell-wrap">{{ row.customer_name || '—' }}</td>
              <td>{{ row.brand_name || '—' }}</td>
              <td>{{ row.customer_sku || '—' }}</td>
              <td
                v-for="(size, idx) in assortmentSizeLines"
                :key="size.size_id || idx"
                class="size-cell num"
              >
                {{ assortmentQty(row, size) }}
              </td>
              <td v-if="!assortmentSizeLines.length" class="size-cell">—</td>
              <td class="num">{{ row.carton_qty || '—' }}</td>
              <td class="num">{{ row.total_qty ?? 0 }}</td>
              <td class="cell-nowrap">{{ row.delivery_date || '—' }}</td>
              <td class="cell-notes">{{ row.line_notes || '—' }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="sizeMatchBlocks.length">
          <div class="section-title">码数配套</div>
          <div v-for="block in sizeMatchBlocks" :key="block.key" class="size-match-block">
            <div v-if="sizeMatchBlocks.length > 1 && block.sales_order_no" class="size-match-order">
              {{ block.sales_order_no }}
            </div>
            <table class="size-match-print">
              <colgroup>
                <col class="size-match-kind" />
                <col v-for="size in block.sizes" :key="size.key" />
              </colgroup>
              <thead>
                <tr>
                  <th class="size-match-kind">订单码数</th>
                  <th v-for="size in block.sizes" :key="size.key" class="size-cell">{{ size.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="kind in block.kinds" :key="kind.key">
                  <th class="size-match-kind">{{ kind.label }}</th>
                  <td v-for="size in block.sizes" :key="size.key" class="size-cell">
                    {{ kind.map[size.label] || size.label }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <div class="section-title">{{ detail.is_recut ? '本次补做材料' : '物料明细' }}</div>
        <table class="material-table">
          <colgroup>
            <col class="seq" />
            <col class="mat-code" />
            <col class="mat-name" />
            <col class="mat-color" />
            <col class="mat-usage-col" />
            <col v-for="size in materialSizeColumns" :key="size" />
            <col class="mat-qty" />
            <col class="mat-unit" />
            <col class="mat-dept" />
          </colgroup>
          <thead>
            <tr>
              <th class="seq" :rowspan="materialSizeColumns.length ? 2 : 1">序</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">物料编码</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">物料名称</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">颜色</th>
              <th class="num" :rowspan="materialSizeColumns.length ? 2 : 1">每双用量</th>
              <th v-if="materialSizeColumns.length" :colspan="materialSizeColumns.length">码数</th>
              <th class="num" :rowspan="materialSizeColumns.length ? 2 : 1">{{ detail.is_recut ? '本次需用' : '需求量' }}</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">单位</th>
              <th :rowspan="materialSizeColumns.length ? 2 : 1">使用部门</th>
            </tr>
            <tr v-if="materialSizeColumns.length">
              <th v-for="size in materialSizeColumns" :key="size" class="size-cell">{{ size }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(material, idx) in materialRows" :key="material.key || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td class="code-cell">{{ material.code || '—' }}</td>
              <td>
                {{ material.name || '—' }}
                <span v-if="material.customerSupplied">（客供）</span>
              </td>
              <td>{{ material.color || '—' }}</td>
              <td class="num">{{ material.usageLabel }}</td>
              <td v-for="size in materialSizeColumns" :key="size" class="size-cell num">
                <template v-if="material.sizeQty[size] != null">
                  {{ formatMaterialQty(material.sizeQty[size]) }}
                  <div v-if="material.usageLabel === '按码' && material.sizeUsage[size] != null" class="mat-usage">
                    {{ formatMaterialQty(material.sizeUsage[size]) }}/双
                  </div>
                </template>
              </td>
              <td class="num">{{ formatMaterialQty(material.totalQty) }}</td>
              <td>{{ material.unit || '—' }}</td>
              <td>{{ material.department || '—' }}</td>
            </tr>
            <tr v-if="!materialRows.length">
              <td :colspan="materialColumnCount" class="empty">（无物料明细，请先维护产品 BOM）</td>
            </tr>
          </tbody>
        </table>

        <template v-if="!detail.is_recut">
          <div class="section-title">客户做货要求</div>
          <table v-if="workReqBlocks.length" class="req-split">
            <thead>
              <tr>
                <th>做货要求</th>
                <th>品牌图片</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="block in workReqBlocks" :key="block.key">
                <td>
                  <div v-if="block.sales_order_no" class="req-head">销售单 {{ block.sales_order_no }}</div>
                  <p class="req-notes">{{ block.notes || '（未填文字要求）' }}</p>
                  <img v-if="block.image_url" class="req-img" :src="block.image_url" alt="做货要求图" />
                </td>
                <td>
                  <div v-if="!brandImageLines(block).length" class="empty-inline">—</div>
                  <div v-for="(line, lineIndex) in brandImageLines(block)" :key="lineIndex" class="req-line">
                    <div v-if="line.brand_name" class="req-brand">{{ line.brand_name }}</div>
                    <div class="req-logos">
                      <img
                        v-for="(url, logoIndex) in line.brand_logo_urls"
                        :key="`${lineIndex}-${logoIndex}`"
                        class="req-logo"
                        :src="url"
                        alt="品牌 Logo"
                      />
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-inline">本单未填做货要求</div>
        </template>

        <div class="section-title">工艺路线</div>
        <table class="process-table">
          <colgroup>
            <col class="seq" />
            <col class="process-segment" />
            <col class="process-name" />
            <col class="process-note" />
          </colgroup>
          <thead>
            <tr>
              <th class="seq">序</th>
              <th class="process-segment">工序段</th>
              <th class="process-name">工序</th>
              <th>工艺要求</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in processRows" :key="p.id || idx">
              <td class="seq">{{ idx + 1 }}</td>
              <td
                v-if="p.segmentRowspan"
                class="process-segment"
                :rowspan="p.segmentRowspan"
              >
                {{ p.segmentLabel }}
              </td>
              <td class="process-name">{{ p.label || p.process_name || '—' }}</td>
              <td>{{ p.requirement_note || '—' }}</td>
            </tr>
            <tr v-if="!processRows.length">
              <td colspan="4" class="empty">（无工序，请先在产品工艺维护后同步到生产单）</td>
            </tr>
          </tbody>
        </table>

        <p v-if="detail.is_recut" class="foot-note">
          本单仅用于补做，须按左右脚及码数生产；完成至 {{ detail.recut_detail?.process_end_name || '指定工序' }} 后并入原生产单。
        </p>
      </div>

      <!-- 框码标签：标签打印机 -->
      <div v-else class="sheet basket-labels">
        <div class="no-print label-hint">
          <p>
            框码标签 · 请选标签打印机 · 建议纸张 60×40mm（可在打印对话框调整）
          </p>
        </div>
        <div v-if="unitsLoading" class="empty">加载框码…</div>
        <div v-else-if="!basketUnits.length" class="empty-box">
          <p>尚未开裁生框。请先「开裁」生成框码后再打印。</p>
        </div>
        <div v-else class="label-stack">
          <div
            v-for="(u, idx) in basketUnits"
            :key="u.id"
            class="basket-label"
            :class="{ voided: u.status === 'scrapped' }"
          >
            <div class="bl-body">
              <div class="bl-kind">框码</div>
              <div class="bl-code">{{ u.code }}</div>
              <div class="bl-meta">
                <div>{{ detail.product_code || '—' }}</div>
                <div>{{ displayNo }}</div>
                <div>{{ [u.color_name, u.size_value].filter(Boolean).join(' / ') || '—' }}</div>
                <div>{{ u.qty }} 双</div>
                <div v-if="u.batch_no">裁批 {{ shortBatchNo(u.batch_no) }}</div>
                <div>第 {{ idx + 1 }}/{{ basketUnits.length }} 框</div>
                <div v-if="u.status === 'scrapped'" class="void-tag">已作废</div>
              </div>
            </div>
            <img
              v-if="u.status !== 'scrapped'"
              class="bl-qr"
              :src="qrUrl(u.code)"
              :alt="u.code"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'

const route = useRoute()
const router = useRouter()

const detail = ref<any>(null)
const units = ref<any[]>([])
const unitsLoading = ref(false)
const error = ref('')
const mode = ref<'flow-card' | 'basket-labels'>('flow-card')

const isHeaderPrint = computed(
  () =>
    Boolean(route.meta.executionHeader) ||
    String(route.path || '').includes('/admin/executions/print/'),
)

const displayNo = computed(
  () => detail.value?.header_no || detail.value?.execution_no || detail.value?.order_no || '—',
)

function compareSizeValue(a: unknown, b: unknown) {
  return String(a || '').localeCompare(String(b || ''), 'zh-CN', { numeric: true })
}

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

const basketUnits = computed(() =>
  (units.value || []).filter(
    (u: any) =>
      u.unit_type === 'basket' &&
      (!Number(route.query.batch_id) || Number(u.batch_id) === Number(route.query.batch_id)),
  ),
)

const processes = computed(() => {
  const d = detail.value
  if (!d) return []
  if (d.is_recut && Array.isArray(d.recut_processes)) return d.recut_processes
  if (Array.isArray(d.processes) && d.processes.length) return d.processes
  if (Array.isArray(d.process_progress) && d.process_progress.length) return d.process_progress
  return []
})

function processSortValue(value: unknown, fallback = Number.MAX_SAFE_INTEGER) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : fallback
}

const processRows = computed(() => {
  const rows = processes.value.map((process: any, index: number) => ({
    ...process,
    segmentLabel: String(process?.segment_name || '').trim() || '未分段',
    segmentRowspan: 0,
    _index: index,
  }))
  rows.sort((a, b) => {
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

function formatMaterialQty(value: unknown) {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return '—'
  return numberValue.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function materialProcess(material: any) {
  return material?.consume_segment_name || material?.consume_process_name || '—'
}

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

const SIZE_MATCH_KIND_LABELS = [
  { key: 'outsole', label: '大底' },
  { key: 'midsole', label: '中底' },
  { key: 'heel', label: '鞋跟' },
  { key: 'last', label: '鞋楦' },
]

function customerSizeQty(row: any, size: any) {
  const allocated = row?.size_quantities?.[String(size.id)]
  const total = Number(allocated ?? size.total_qty ?? size.qty ?? 0)
  return total > 0 ? total : ''
}

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

function brandImageLines(block: any) {
  return (block?.lines || []).filter((line: any) => (line.brand_logo_urls || []).length)
}

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
  return d.sales_order_no || salesOrderSummary.value || ''
})

const executionNo = computed(() => {
  if (isHeaderPrint.value) {
    return detail.value?.header_no || detail.value?.execution_no || null
  }
  const u = (units.value || []).find((x: any) => x.execution_id)
  return u?.execution_no || null
})

const salesOrderSummary = computed(() => {
  const withSrc = (units.value || []).find(
    (x: any) => Array.isArray(x.allocation_sources) && x.allocation_sources.length,
  )
  if (!withSrc) return ''
  return (withSrc.allocation_sources || [])
    .map((s: any) => s.label || `${s.sales_order_no} ${s.qty}`)
    .join(' / ')
})

const flowQrSrc = computed(() => {
  if (!isHeaderPrint.value) return ''
  const id = Number(route.params.id)
  if (!id) return ''
  return `/api/v1/executions/headers/${id}/flow-card/qr.png`
})

function qrUrl(code: string) {
  return `/api/v1/trace-units/by-code/${encodeURIComponent(code)}/qr.png`
}

function shortBatchNo(batchNo: string) {
  const tail = String(batchNo || '').split('-').pop() || ''
  return tail ? tail.padStart(3, '0') : batchNo
}

function doPrint() {
  const prevTitle = document.title
  const prevUrl = `${location.pathname}${location.search}${location.hash}`
  document.title = ''
  try {
    history.replaceState(null, '', '/')
  } catch {
    /* ignore */
  }
  let restored = false
  const restore = () => {
    if (restored) return
    restored = true
    document.title = prevTitle
    try {
      history.replaceState(null, '', prevUrl)
    } catch {
      /* ignore */
    }
  }
  window.addEventListener('afterprint', restore, { once: true })
  window.print()
}

function closeOrBack() {
  if (window.opener) window.close()
  else router.back()
}

function parseMode(raw: unknown): 'flow-card' | 'basket-labels' {
  const m = String(raw || 'flow-card')
  // 兼容旧链接
  if (m === 'main-codes' || m === 'basket-labels' || m === 'labels') return 'basket-labels'
  if (m === 'sheet' || m === 'flow-card') return 'flow-card'
  return 'flow-card'
}

function goCutCards() {
  const id = Number(route.params.id)
  if (!id) return
  if (isHeaderPrint.value) {
    window.opener?.postMessage?.({ type: 'erp-cut-cards', headerId: id }, '*')
    if (!window.opener) {
      router.push({ path: '/admin/executions', query: { header_id: String(id) } })
    }
    return
  }
  window.opener?.postMessage?.({ type: 'erp-cut-cards', orderId: id }, '*')
  if (!window.opener) {
    router.push({ path: '/admin/orders', query: { cut: String(id) } })
  }
}

async function loadUnits(id: number) {
  unitsLoading.value = true
  try {
    if (detail.value?.baskets?.length) {
      units.value = detail.value.baskets
      return
    }
    const res: any = isHeaderPrint.value
      ? await http.get(`/executions/headers/${id}/trace-units`)
      : await http.get(`/orders/${id}/trace-units`)
    units.value = res.data?.items || res.items || []
  } catch {
    units.value = []
  } finally {
    unitsLoading.value = false
  }
}

function mapHeaderDetail(h: any) {
  const sizeLines = h.size_lines || []
  const items = sizeLines.map((s: any, idx: number) => ({
    id: s.id || idx,
    color_name: h.color_name,
    size_value: s.size_value,
    qty: s.total_qty,
  }))
  return {
    ...h,
    order_no: h.header_no || h.execution_no,
    items,
    processes: h.processes || h.process_progress || [],
  }
}

async function load() {
  const id = Number(route.params.id)
  if (!id) {
    error.value = '单号无效'
    return
  }
  mode.value = parseMode(route.query.mode)
  try {
    if (isHeaderPrint.value) {
      const res: any = await http.get(`/executions/headers/${id}/flow-card`)
      detail.value = mapHeaderDetail(res.data)
      if (Array.isArray(res.data?.baskets)) {
        units.value = res.data.baskets
      }
    } else {
      const res: any = await http.get(`/orders/${id}`)
      detail.value = res.data
    }
  } catch {
    error.value = '单据不存在或无权查看'
    return
  }
  if (!units.value.length) await loadUnits(id)
  const titlePrefix = mode.value === 'flow-card'
    ? (detail.value?.is_recut ? '生产单-补' : '生产单')
    : '框码'
  document.title =
    displayNo.value && displayNo.value !== '—' ? `${titlePrefix} ${displayNo.value}` : ''
  if (mode.value === 'basket-labels' && (units.value || []).length) {
    setTimeout(() => {
      document.title = ''
      doPrint()
    }, 500)
  }
}

watch(
  () => route.query.mode,
  (m) => {
    mode.value = parseMode(m)
  },
)

onMounted(load)
</script>

<style scoped>
.print-page {
  min-height: 100vh;
  padding: 20px;
  background: #fff;
  color: #111;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  position: relative;
  overflow-x: hidden;
}
.actions {
  margin-bottom: 12px;
}
.actions button {
  margin-right: 8px;
  padding: 6px 12px;
  border: 1px solid #ccc;
  background: #0076ff;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.actions button.ghost {
  background: #fff;
  color: #333;
}
.err {
  color: #c45656;
}
.sheet {
  position: relative;
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  overflow-x: hidden;
}
.flow-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}
.flow-head-text {
  flex: 1;
}
.flow-qr-box {
  text-align: center;
  flex-shrink: 0;
}
.flow-qr {
  width: 112px;
  height: 112px;
  object-fit: contain;
  display: block;
}
.flow-qr-box small {
  display: block;
  margin-top: 2px;
  color: #555;
  font-size: 11px;
}
.doc-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin: 0;
  letter-spacing: 0.28em;
}
.doc-sub {
  text-align: center;
  margin: 6px 0 0;
  color: #555;
  font-size: 12px;
  letter-spacing: 0.08em;
}
.recut-source-no {
  margin: 5px 0 0;
  color: #111;
  font-size: 12px;
  font-weight: 500;
  text-align: center;
}
.recut-source-no strong {
  margin-left: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  margin: 10px 0 14px;
  line-height: 1.7;
}
.meta-grid strong {
  color: #555;
  font-weight: 500;
}
.section-title {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 700;
}
.production-summary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 7px 0 0;
  color: #555;
  font-size: 11px;
  font-style: normal;
}
.production-summary i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #999;
}
.production-summary strong {
  margin-left: 3px;
  color: #111;
  font-size: 11px;
}
table {
  width: 100%;
  max-width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.order-summary-table {
  margin: 10px 0 14px;
  table-layout: fixed;
  font-size: 9px;
}
.recut-summary-table {
  margin: 10px 0 14px;
  table-layout: fixed;
  font-size: 12px;
}
.recut-summary-table th {
  width: 14%;
  background: #f5f5f5;
  white-space: normal;
  overflow-wrap: anywhere;
}
.recut-summary-table td { width: 36%; }
.recut-summary-table th,
.recut-summary-table td { padding: 8px 10px; }
.recut-size-table {
  margin: 0 0 14px;
  table-layout: fixed;
  font-size: 12px;
}
.recut-size-table th {
  background: #eef3f9;
  color: #5f7089;
  font-weight: 700;
}
.recut-size-table th,
.recut-size-table td {
  height: 34px;
  padding: 7px 4px;
  text-align: center !important;
  vertical-align: middle;
}
.recut-size-table .recut-size-head {
  font-size: 13px;
}
.recut-size-table .recut-total-head,
.recut-size-table .recut-total {
  width: 9%;
}
.order-summary-table th,
.order-summary-table td {
  padding: 5px 2px;
  text-align: center !important;
  vertical-align: middle;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.order-summary-table .num {
  width: auto;
}
.shared-attr-table {
  margin: 10px 0 0;
  font-size: 12px;
}
.shared-attr-table th,
.shared-attr-table td {
  padding: 6px 8px;
  text-align: center !important;
  vertical-align: middle;
}
.shared-attr-table .col-product { width: 18%; }
.shared-attr-table .col-image { width: 22%; }
.shared-attr-table .col-color { width: 16%; }
.shared-attr-table .col-fabric { width: 22%; }
.shared-attr-table .col-lining { width: 22%; }
.shared-attr-table .product-image {
  width: 72px;
  max-width: 72px;
  height: 64px;
}
.order-summary-table .col-order-no { width: 11%; }
.order-summary-table .col-customer { width: 10%; }
.order-summary-table .col-brand { width: 8%; }
.order-summary-table .col-customer-sku { width: 10%; }
.order-summary-table .col-cartons { width: 5%; }
.order-summary-table .col-total { width: 6%; }
.order-summary-table .col-delivery { width: 8%; }
.order-summary-table .col-notes { width: 14%; }
.order-summary-table .cell-notes {
  text-align: center !important;
  white-space: pre-wrap;
}
.order-summary-table .cell-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.order-summary-table .cell-wrap {
  word-break: break-word;
}
.order-summary-table .cell-nowrap {
  white-space: normal;
  overflow-wrap: anywhere;
}
.size-match-block + .size-match-block {
  margin-top: 8px;
}
.size-match-order {
  margin: 0 0 4px;
  font-weight: 600;
}
.size-match-print {
  margin-bottom: 8px;
}
.size-match-print th,
.size-match-print td {
  text-align: center !important;
  overflow: hidden;
  overflow-wrap: anywhere;
  white-space: normal;
}
.size-match-print .size-match-kind {
  width: 64px;
  white-space: nowrap;
}
.material-table {
  font-size: 10px;
}
.material-table th,
.material-table td {
  padding: 5px 2px;
  overflow: hidden;
  overflow-wrap: anywhere;
  text-align: center !important;
}
.material-table .seq { width: 4%; }
.material-table .mat-code { width: 12%; }
.material-table .mat-name { width: 16%; }
.material-table .mat-color { width: 8%; }
.material-table .mat-usage-col { width: 8%; }
.material-table .mat-qty { width: 8%; }
.material-table .mat-unit { width: 5%; }
.material-table .mat-dept { width: 8%; }
.material-table .num {
  width: auto;
}
.material-table .mat-usage {
  color: #666;
  font-size: 9px;
  font-weight: 400;
}
.material-table tr {
  break-inside: avoid;
  page-break-inside: avoid;
}
.assortment-head {
  text-align: center !important;
}
.size-cell,
.size-cell.num {
  width: auto;
  min-width: 0;
  text-align: center !important;
  white-space: normal;
  overflow: hidden;
  overflow-wrap: anywhere;
  padding-left: 1px;
  padding-right: 1px;
}
th,
td {
  box-sizing: border-box;
  max-width: 100%;
  border: 1px solid #333;
  padding: 7px 8px;
  text-align: left;
  vertical-align: middle;
  overflow: hidden;
  overflow-wrap: anywhere;
}
th {
  background: #f3f4f6;
  font-weight: 600;
}
.seq {
  text-align: center !important;
  width: 48px;
}
.num {
  text-align: right !important;
  width: 72px;
}
.sheet .seq,
.sheet .num,
.sheet .chk,
.sheet .size-cell {
  width: auto;
  min-width: 0;
}
.size-match-print th:not(.size-match-kind),
.size-match-print td,
.material-table .size-cell,
.order-summary-table .size-cell {
  max-width: 0;
}
.image-col {
  box-sizing: border-box;
  padding: 2px !important;
  text-align: center !important;
  overflow: hidden;
}
.product-image {
  display: block;
  box-sizing: border-box;
  width: 100%;
  max-width: 40px;
  height: 36px;
  max-height: 100%;
  margin: 0 auto;
  object-fit: contain;
}
.chk {
  text-align: center !important;
  width: 56px;
  font-size: 14px;
}
.sign-cell {
  min-width: 0;
  height: 28px;
}
.code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.empty {
  text-align: center;
  color: #666;
}
.empty-inline {
  color: #666;
  padding: 8px 0;
}
.empty-box {
  border: 1px dashed #999;
  padding: 24px;
  text-align: center;
  margin: 12px 0;
}
.totals {
  margin-top: 8px;
  text-align: right;
  font-size: 13px;
}
.req-split {
  table-layout: fixed;
}
.req-split th {
  width: 50%;
}
.req-split td {
  vertical-align: top;
  width: 50%;
}
.req-split tr {
  break-inside: avoid;
  page-break-inside: avoid;
}
.req-head,
.req-brand {
  font-weight: 600;
  margin-bottom: 6px;
}
.req-line + .req-line {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #ccc;
}
.req-notes {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}
.req-logos {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}
.req-logo {
  width: 108px;
  height: 108px;
  object-fit: contain;
  border: 1px solid #ddd;
  background: #fff;
}
.req-img {
  display: block;
  margin-top: 8px;
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
}
.process-table .seq {
  width: 8%;
}
.process-table .process-segment {
  width: 16%;
  text-align: center !important;
  vertical-align: middle;
}
.process-table .process-name {
  width: 18%;
}
.process-table .process-note {
  width: 58%;
}
.foot-note {
  margin-top: 16px;
  color: #555;
  font-size: 11px;
}
.voided-row {
  opacity: 0.45;
  text-decoration: line-through;
}
.void-tag {
  color: #c45656;
  font-weight: 600;
}

/* 框码标签（标签打印机） */
.label-hint {
  margin-bottom: 12px;
  color: #555;
  font-size: 13px;
}
.label-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.basket-label {
  width: 60mm;
  min-height: 40mm;
  box-sizing: border-box;
  border: 1px solid #222;
  padding: 3mm;
  display: grid;
  grid-template-columns: 1fr 28mm;
  gap: 2mm;
  align-items: center;
  break-inside: avoid;
  page-break-inside: avoid;
  page-break-after: always;
}
.basket-label:last-child {
  page-break-after: auto;
}
.basket-label.voided {
  opacity: 0.45;
}
.bl-kind {
  font-size: 10px;
  color: #555;
  letter-spacing: 0.12em;
}
.bl-code {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
  margin: 2px 0 4px;
  word-break: break-all;
}
.bl-meta {
  font-size: 11px;
  line-height: 1.45;
  color: #222;
}
.bl-qr {
  width: 26mm;
  height: 26mm;
  object-fit: contain;
}
.watermark {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 0;
  opacity: 0.12;
  font-size: 72px;
  font-weight: 700;
  color: #c45656;
  transform: rotate(-24deg);
}
.watermark.muted {
  color: #888;
}
.sheet > * {
  position: relative;
  z-index: 1;
}

@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    padding: 0;
  }
  .print-page:not(.label-mode) {
    padding: 8mm 10mm;
  }
  .sheet {
    max-width: none;
    width: 100%;
    margin: 0 auto;
  }
  .label-mode .sheet {
    max-width: none;
  }
}
</style>

<style>
@page {
  size: A4 portrait;
  margin: 10mm 12mm;
}
body:has(.print-page) #app {
  max-width: none;
  margin: 0;
  background: #fff;
}
body:has(.print-page.label-mode) {
  margin: 0;
}
</style>
