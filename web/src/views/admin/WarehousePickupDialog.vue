<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="1120px"
    destroy-on-close
    :close-on-click-modal="slip?.status !== 'signed'"
    @closed="onClosed"
  >
    <div class="wh-steps">
      <span :class="{ on: step === 1 }">{{ isProduction ? '1. 填物料和数量' : '1. 填写数量' }}</span>
      <span :class="{ on: step === 2 }">2. 手机扫码确认</span>
    </div>

    <template v-if="step === 1 && !isProduction">
      <el-table
        v-if="devLines.length"
        ref="devTableRef"
        :data="devLines"
        border
        size="small"
        style="width: 100%"
        @header-dragend="onDevHeaderDragend"
      >
        <el-table-column
          column-key="image"
          label="物料图片"
          :width="devColWidth('image', 72)"
          align="center"
          header-align="center"
          class-name="mat-image-col"
          header-class-name="mat-image-col"
          resizable
        >
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              preview-teleported
              fit="contain"
              class="product-thumb"
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="material_code"
          label="物料编号"
          :width="devColWidth('material_code', 120)"
          align="center"
          header-align="center"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="material_name"
          label="名称"
          :width="devColWidth('material_name', 140)"
          align="center"
          header-align="center"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          column-key="color_name"
          label="颜色"
          :width="devColWidth('color_name', 80)"
          align="center"
          header-align="center"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="size_value"
          label="尺码"
          :width="devColWidth('size_value', 72)"
          align="center"
          header-align="center"
          resizable
        >
          <template #default="{ row }">{{ row.size_value || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="partner_name"
          label="供应商"
          :width="devColWidth('partner_name', 130)"
          align="center"
          header-align="center"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.partner_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="stock_qty"
          :label="isReturn ? '可退' : '可用'"
          :width="devColWidth('stock_qty', 80)"
          align="center"
          header-align="center"
          resizable
        >
          <template #default="{ row }">{{ row.stock_qty }}</template>
        </el-table-column>
        <el-table-column column-key="qty" label="数量" :width="devColWidth('qty', 168)" align="center" resizable>
          <template #default="{ row }">
            <div class="wh-qty">
              <el-input-number
                v-model="row.qty"
                :min="0"
                :max="Number(row.stock_qty) || 0"
                :step="1"
                controls-position="right"
              />
              <span class="wh-unit">{{ row.unit_name || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="" width="56" align="center">
          <template #default="{ $index }">
            <el-button link type="danger" @click="devLines.splice($index, 1)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p v-else class="wh-empty">请先在物料仓勾选物料。</p>
    </template>

    <template v-else-if="step === 1">
      <div class="wh-order">
        <el-select
          v-model="headerNo"
          class="wh-order-select"
          popper-class="wh-order-popper"
          filterable
          remote
          clearable
          reserve-keyword
          placeholder="输入生产单号或款号"
          :remote-method="searchHeaders"
          :loading="searching"
          @change="onHeaderChange"
          @focus="searchHeaders(headerNo)"
        >
          <el-option
            v-for="row in headerOptions"
            :key="row.header_id"
            :label="headerLabel(row)"
            :value="row.header_no"
          />
        </el-select>
      </div>
      <p v-if="productionHeader" class="wh-order-meta">
        {{ productionHeader.header_no }} · {{ productionHeader.total_qty }} 双
      </p>
      <el-table
        v-if="productionLines.length"
        ref="prodTableRef"
        class="wh-prod-table"
        :data="productionLines"
        border
        size="small"
        style="width: 100%"
        :span-method="prodSpanMethod"
        @header-dragend="onProdHeaderDragend"
      >
        <el-table-column
          column-key="image"
          label="物料图片"
          :width="prodColWidth('image', 72)"
          align="center"
          header-align="center"
          class-name="mat-image-col"
          header-class-name="mat-image-col"
          resizable
        >
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              preview-teleported
              fit="contain"
              class="product-thumb"
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="material_code"
          label="物料编号"
          :width="prodColWidth('material_code', 120)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="material_name"
          label="名称"
          :width="prodColWidth('material_name', 140)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="color_name"
          label="颜色"
          :width="prodColWidth('color_name', 72)"
          align="center"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          prop="partner_name"
          label="供应商"
          :width="prodColWidth('partner_name', 120)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.partner_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="单位" width="52" align="center">
          <template #default="{ row }">{{ row.unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          v-for="size in productionSizeColumns"
          :key="size"
          :column-key="`size_${size}`"
          :label="size"
          :width="prodSizeColWidth"
          align="center"
        >
          <template #default="{ row }">
            <div v-if="!rowHasSize(row)" class="qty-stack qty-stack-plain">
              <div>{{ row.required_qty }}</div>
              <el-input-number
                v-model="row.qty"
                :min="0"
                :max="isReturn ? Number(row.returnable_qty) || 0 : undefined"
                :step="1"
                :controls="false"
                size="small"
                class="qty-input"
                :class="{ 'is-over': overStock(row) }"
              />
              <div v-if="overStock(row)" class="qty-over">超过现存量 {{ row.max_issue_qty }}</div>
            </div>
            <div v-else-if="sizePart(row, size)" class="qty-stack">
              <div>{{ sizePart(row, size).required_qty }}</div>
              <el-input-number
                v-model="sizePart(row, size).qty"
                :min="0"
                :max="isReturn ? Number(sizePart(row, size).returnable_qty) || 0 : undefined"
                :step="1"
                :controls="false"
                size="small"
                class="qty-input"
                :class="{ 'is-over': overStock(sizePart(row, size)) }"
              />
              <div v-if="overStock(sizePart(row, size))" class="qty-over">超过现存量 {{ sizePart(row, size).max_issue_qty }}</div>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!productionSizeColumns.length" label="" width="96" align="center">
          <template #default="{ row }">
            <div class="qty-stack qty-stack-plain">
              <div>{{ row.required_qty }}</div>
              <el-input-number
                v-model="row.qty"
                :min="0"
                :max="isReturn ? Number(row.returnable_qty) || 0 : undefined"
                :step="1"
                :controls="false"
                size="small"
                class="qty-input"
                :class="{ 'is-over': overStock(row) }"
              />
              <div v-if="overStock(row)" class="qty-over">超过现存量 {{ row.max_issue_qty }}</div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <p v-else-if="productionHeader" class="wh-empty">{{ isReturn ? '这张生产单没有可退物料' : '这张生产单没有可领物料' }}</p>
      <p v-else-if="previewing" class="wh-empty">正在读取物料…</p>
      <p v-else class="wh-empty">选择生产单后，用料会直接列在这里。</p>
    </template>

    <template v-else-if="slip?.status === 'signed'">
      <div class="wh-done">
        <el-result
          icon="success"
          title="确认成功"
          :sub-title="isReturn ? `${slip.picker_name || '退料人'} 已确认退料，库存已回` : `${slip.picker_name || '领料人'} 已确认领料，库存已出`"
        >
          <template #extra>
            <p class="wh-order-meta">{{ slip.doc_no }} · {{ slip.kind_label }}</p>
          </template>
        </el-result>
      </div>
    </template>

    <template v-else>
      <p class="wh-confirm-hint">
        {{ isReturn ? '请退料人用手机扫描二维码确认。确认后这里会自动入库。' : '请领料人用手机扫描二维码确认。确认后这里会自动出库。' }}
      </p>
      <p v-if="slip" class="wh-order-meta">{{ slip.doc_no }} · {{ slip.kind_label }}</p>
      <img v-if="slip?.qr_png" class="wh-qr" :src="slip.qr_png" alt="领料确认二维码" />
      <p class="wh-empty">等待领料人扫码确认…</p>
    </template>

    <template #footer>
      <el-button :type="slip?.status === 'signed' ? 'primary' : 'default'" @click="visible = false">
        {{ step === 2 ? '关闭' : '取消' }}
      </el-button>
      <el-button v-if="step === 1" type="primary" :loading="submitting" :disabled="!readyCount || productionOverStock" @click="issueQr">
        生成确认码{{ readyCount ? ` · ${readyCount} 种` : '' }}
      </el-button>
    </template>
  </el-dialog>

  <el-drawer v-model="historyVisible" title="领退记录" size="720px" @open="loadHistory">
    <el-table
      ref="historyTableRef"
      v-loading="historyLoading"
      :data="history"
      border
      size="small"
      style="width: 100%"
      empty-text="暂无已确认的领退记录"
      @header-dragend="onHistoryHeaderDragend"
      @row-click="openHistoryRow"
    >
      <el-table-column column-key="signed_at" label="时间" :width="historyColWidth('signed_at', 160)" resizable>
        <template #default="{ row }">{{ formatTime(row.signed_at || row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="kind_label" label="类型" :width="historyColWidth('kind_label', 120)" show-overflow-tooltip resizable />
      <el-table-column prop="header_no" label="生产单" :width="historyColWidth('header_no', 120)" show-overflow-tooltip resizable>
        <template #default="{ row }">{{ row.header_no || '—' }}</template>
      </el-table-column>
      <el-table-column prop="picker_name" label="领/退料人" :width="historyColWidth('picker_name', 120)" show-overflow-tooltip resizable>
        <template #default="{ row }">{{ row.picker_name || '—' }}</template>
      </el-table-column>
      <el-table-column column-key="line_count" label="物料" :width="historyColWidth('line_count', 72)" align="right" resizable>
        <template #default="{ row }">
          <el-tooltip placement="top" :show-after="200" :disabled="!(row.lines || []).length">
            <template #content>
              <div class="wh-history-tip">
                <div v-for="line in row.lines || []" :key="line.id">
                  {{ line.material_name }}<template v-if="line.material_code"> {{ line.material_code }}</template><template v-if="line.size_value"> · {{ line.size_value }}</template> × {{ line.qty }}{{ line.unit_name || '' }}
                </div>
              </div>
            </template>
            <span class="wh-history-qty">{{ row.line_count }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
  </el-drawer>

  <el-dialog v-model="detailVisible" :title="detail?.doc_no || '领料单'" width="560px">
    <template v-if="detail">
      <p class="wh-order-meta">{{ detail.kind_label }} · {{ String(detail.kind || '').includes('return') ? '退料人' : '领料人' }} {{ detail.picker_name || '—' }}{{ detail.header_no ? ` · ${detail.header_no}` : '' }}</p>
      <div class="wh-lines">
        <div v-for="line in detail.lines || []" :key="line.id" class="wh-line">
          <div>
            <strong>{{ line.material_name }}</strong>
            <span>{{ line.material_code }}{{ line.size_value ? ` · ${line.size_value}` : '' }}</span>
          </div>
          <strong>{{ line.qty }}{{ line.unit_name || '' }}</strong>
        </div>
      </div>
      <img v-if="detail.signature_data" class="wh-sign-img" :src="detail.signature_data" alt="领料人签字" />
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'

const emit = defineEmits<{ posted: [] }>()

const visible = ref(false)
type PickupKind = 'dev' | 'aux' | 'production' | 'dev_return' | 'aux_return' | 'production_return'

const KIND_TITLES: Record<PickupKind, string> = {
  dev: '开发部领料',
  aux: '生产领辅料耗材',
  production: '生产领主料',
  dev_return: '开发部退料',
  aux_return: '生产退辅料',
  production_return: '生产退主料',
}

const kind = ref<PickupKind>('dev')
const step = ref<1 | 2>(1)
const submitting = ref(false)

const devLines = ref<any[]>([])

const headerNo = ref('')
const previewing = ref(false)
const searching = ref(false)
const headerOptions = ref<any[]>([])
let headerSearchTimer = 0
const productionHeader = ref<any | null>(null)
const productionLines = ref<any[]>([])

const slip = ref<any | null>(null)
let pollTimer = 0

const historyVisible = ref(false)
const historyLoading = ref(false)
const history = ref<any[]>([])
const detailVisible = ref(false)
const detail = ref<any | null>(null)

const devTableRef = ref<{ doLayout?: () => void } | null>(null)
const prodTableRef = ref<{ doLayout?: () => void } | null>(null)
const historyTableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth: devColWidth, onHeaderDragend: onDevHeaderDragend } = useTableColWidths(
  'warehouse-pickup-dev',
  devTableRef,
  { flexKey: 'material_name', flexDefaultMin: 100, fitToContainer: true },
)
const { colWidth: prodColWidth, onHeaderDragend: onProdHeaderDragend } = useTableColWidths(
  'warehouse-pickup-production',
  prodTableRef,
  { flexKey: 'material_name', flexDefaultMin: 120, fitToContainer: true },
)
const { colWidth: historyColWidth, onHeaderDragend: onHistoryHeaderDragend } = useTableColWidths(
  'warehouse-pickup-history',
  historyTableRef,
  { flexKey: 'picker_name', flexDefaultMin: 80, fitToContainer: true },
)

const title = computed(() => KIND_TITLES[kind.value])
const isProduction = computed(() => kind.value === 'production' || kind.value === 'production_return')
const isReturn = computed(() => kind.value.endsWith('_return'))
const readyCount = computed(() => {
  if (isProduction.value) {
    return productionLines.value.filter((line) => sizeParts(line).some((part) => Number(part.qty) > 0)).length
  }
  return draftPayload().length
})
const productionOverStock = computed(() => {
  if (!isProduction.value || isReturn.value) return false
  return productionLines.value.some((line) => sizeParts(line).some((part) => overStock(part)))
})

function formatTime(value: string) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

function resetForm() {
  step.value = 1
  devLines.value = []
  headerNo.value = ''
  headerOptions.value = []
  window.clearTimeout(headerSearchTimer)
  productionHeader.value = null
  productionLines.value = []
  slip.value = null
  stopPoll()
}

function open(next: 'production' | 'production_return') {
  kind.value = next
  resetForm()
  visible.value = true
}

function fillPoolLines(rows: any[]) {
  devLines.value = rows.map((row) => ({
    supplier_product_id: row.supplier_product_id,
    size_id: row.size_id ?? null,
    material_name: row.supplier_product_name || row.supplier_product_code,
    material_code: row.supplier_product_code,
    color_name: row.color_name || '',
    size_value: row.size_value || '',
    unit_name: row.pricing_unit_name || '',
    image_url: row.image_url || '',
    partner_name: row.partner_name || '',
    stock_qty: row.pool_qty ?? row.qty ?? 0,
    qty: undefined,
  }))
  visible.value = true
}

function openDev(rows: any[]) {
  kind.value = 'dev'
  resetForm()
  fillPoolLines(rows)
}

function openAux(rows: any[]) {
  kind.value = 'aux'
  resetForm()
  fillPoolLines(rows)
}

function returnableKey(row: { supplier_product_id: number; size_id?: number | null }) {
  return `${row.supplier_product_id}:${row.size_id ?? ''}`
}

async function openPoolReturn(next: 'dev_return' | 'aux_return', rows: any[]) {
  const res: any = await http.post('/warehouse-pickups/returnable', {
    kind: next,
    lines: rows.map((row) => ({
      supplier_product_id: row.supplier_product_id,
      size_id: row.size_id ?? undefined,
    })),
  })
  const caps = new Map<string, string>()
  for (const line of res.data?.lines || []) caps.set(returnableKey(line), String(line.returnable_qty ?? '0'))
  if (rows.length && [...caps.values()].every((qty) => Number(qty) <= 0)) {
    ElMessage.warning('这些物料没有可退数量')
  }
  kind.value = next
  resetForm()
  fillPoolLines(
    rows.map((row) => ({
      ...row,
      pool_qty: caps.get(returnableKey(row)) ?? '0',
    })),
  )
}

function openDevReturn(rows: any[]) {
  return openPoolReturn('dev_return', rows)
}

function openAuxReturn(rows: any[]) {
  return openPoolReturn('aux_return', rows)
}

function openHistory() {
  historyVisible.value = true
}

defineExpose({ open, openDev, openAux, openDevReturn, openAuxReturn, openHistory })

function headerLabel(row: any) {
  const parts = [row.header_no]
  if (row.product_code) parts.push(row.product_code)
  if (row.color_name) parts.push(row.color_name)
  parts.push(`${row.total_qty ?? 0} 双`)
  return parts.join(' · ')
}

function searchHeaders(keyword: string) {
  window.clearTimeout(headerSearchTimer)
  headerSearchTimer = window.setTimeout(() => void runHeaderSearch(keyword), 200)
}

async function runHeaderSearch(keyword: string) {
  searching.value = true
  try {
    const res: any = await http.get('/warehouse-pickups/production-options', {
      params: { q: (keyword || '').trim() },
      silent: true,
    })
    const items = res.data?.items || []
    const selected = headerOptions.value.find((row) => row.header_no === headerNo.value)
    headerOptions.value = items
    if (selected && !items.some((row: any) => row.header_no === selected.header_no)) {
      headerOptions.value = [selected, ...items]
    }
  } catch {
    headerOptions.value = []
  } finally {
    searching.value = false
  }
}

async function onHeaderChange(no: string) {
  productionHeader.value = null
  productionLines.value = []
  if (!no) return
  await loadProduction()
}

async function loadProduction() {
  const text = headerNo.value.trim()
  if (!text) return
  previewing.value = true
  try {
    const res: any = await http.get('/warehouse-pickups/production', { params: { header_no: text } })
    const data = res.data || {}
    if (data.ambiguous) {
      productionHeader.value = null
      productionLines.value = []
      return
    }
    productionHeader.value = data
    productionLines.value = (data.lines || []).map((line: any) => ({
      ...line,
      qty: undefined,
      parts: Array.isArray(line.parts) ? line.parts.map((part: any) => ({ ...part, qty: undefined })) : line.parts,
    }))
  } finally {
    previewing.value = false
  }
}

function isMultiSize(row: any) {
  return Array.isArray(row?.parts) && row.parts.length > 1
}

function rowHasSize(row: any) {
  return isMultiSize(row) || Boolean(row?.size_value)
}

function sizeParts(row: any) {
  return isMultiSize(row) ? row.parts : [row]
}

function sizePart(row: any, size: string) {
  if (isMultiSize(row)) return row.parts.find((part: any) => part.size_value === size) || null
  return row?.size_value === size ? row : null
}

function stockQty(value: unknown) {
  const n = Number(value)
  return Number.isFinite(n) ? Math.round(n * 10000) / 10000 : 0
}

function overStock(part: any) {
  if (isReturn.value || !part) return false
  const qty = stockQty(part.qty)
  return qty > 0 && qty > stockQty(part.max_issue_qty)
}

const productionSizeColumns = computed(() => {
  const seen = new Map<string, number>()
  for (const line of productionLines.value) {
    const parts = isMultiSize(line) ? line.parts : line.size_value ? [line] : []
    for (const part of parts) {
      const size = String(part.size_value || '')
      if (!size || seen.has(size)) continue
      const matched = size.match(/\d+(?:\.\d+)?/)
      seen.set(size, matched ? Number(matched[0]) : 999999)
    }
  }
  return [...seen.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})

const prodSizeColWidth = computed(() => {
  const count = productionSizeColumns.value.length
  if (!count) return 72
  const fixed = 72 + 120 + 140 + 72 + 120 + 52 + 48
  const room = Math.max(count * 64, 1040 - fixed)
  return Math.max(64, Math.floor(room / count))
})

function prodSpanMethod({ row, column }: { row: any; column: { columnKey?: string } }) {
  const key = String(column.columnKey || '')
  const sizes = productionSizeColumns.value
  if (!key.startsWith('size_') || rowHasSize(row) || !sizes.length) return [1, 1]
  if (key !== `size_${sizes[0]}`) return [0, 0]
  return [1, sizes.length]
}

function draftPayload() {
  if (!isProduction.value) {
    return devLines.value
      .filter((line) => Number(line.qty) > 0)
      .map((line) => ({
        supplier_product_id: line.supplier_product_id,
        size_id: line.size_id || undefined,
        qty: line.qty,
      }))
  }
  const out: { requirement_id: number; qty: number }[] = []
  for (const line of productionLines.value) {
    for (const part of sizeParts(line)) {
      if (Number(part.qty) > 0) out.push({ requirement_id: part.requirement_id, qty: part.qty })
    }
  }
  return out
}

function stopPoll() {
  window.clearInterval(pollTimer)
  pollTimer = 0
}

function startPoll(id: number) {
  stopPoll()
  pollTimer = window.setInterval(() => void pollSigned(id), 2000)
}

async function pollSigned(id: number) {
  try {
    const res: any = await http.get(`/warehouse-pickups/${id}`, { silent: true })
    const data = res.data
    if (data?.status === 'signed') {
      stopPoll()
      slip.value = { ...slip.value, ...data }
      emit('posted')
    } else if (data?.status === 'cancelled') {
      stopPoll()
      visible.value = false
    }
  } catch {
    /* 轮询失败时下一轮再试 */
  }
}

async function issueQr() {
  if (!readyCount.value || submitting.value || productionOverStock.value) {
    if (productionOverStock.value) ElMessage.warning('输入数量超过现存量，不能提交')
    return
  }
  submitting.value = true
  try {
    const res: any = await http.post('/warehouse-pickups', {
      kind: kind.value,
      header_no: isProduction.value ? productionHeader.value?.header_no : undefined,
      origin: window.location.origin,
      lines: draftPayload(),
    })
    slip.value = res.data
    step.value = 2
    startPoll(res.data.id)
  } finally {
    submitting.value = false
  }
}

function onClosed() {
  const pendingId = slip.value?.status === 'pending' ? slip.value.id : 0
  stopPoll()
  if (pendingId) void abandonPending(pendingId)
}

async function abandonPending(id: number) {
  try {
    await http.post(`/warehouse-pickups/${id}/cancel`)
  } catch {
    /* 已经确认或已经作废时不用再处理 */
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res: any = await http.get('/warehouse-pickups', { params: { page_size: 50, status: 'signed' } })
    history.value = res.data?.items || []
  } finally {
    historyLoading.value = false
  }
}

async function openHistoryRow(row: any) {
  const res: any = await http.get(`/warehouse-pickups/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
}

onBeforeUnmount(() => {
  stopPoll()
  window.clearTimeout(headerSearchTimer)
})
</script>

<style scoped>
.wh-history-qty {
  cursor: default;
  border-bottom: 1px dashed var(--el-text-color-secondary);
}
.wh-history-tip {
  line-height: 1.6;
}
.wh-steps {
  display: flex;
  gap: 16px;
  margin-bottom: 14px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.wh-steps .on {
  color: var(--el-color-primary);
  font-weight: 600;
}
.wh-order {
  margin-bottom: 12px;
}
.wh-order-select {
  width: 420px;
  max-width: 100%;
}
.wh-lines {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.wh-line {
  display: flex;
  align-items: center;
  gap: 12px;
}
.wh-line > div:first-child {
  flex: 1;
  min-width: 0;
}
.qty-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.35;
  gap: 2px;
}
.qty-input {
  width: 100%;
}
.wh-prod-table :deep(.el-input-number) {
  width: 100%;
  min-width: 0;
}
.wh-prod-table :deep(.el-input-number .el-input__wrapper) {
  min-width: 0;
  padding-left: 4px;
  padding-right: 4px;
}
.qty-stack-plain :deep(.el-input-number) {
  width: 96px;
  max-width: 100%;
}
.qty-over {
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.2;
}
.qty-input.is-over :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.wh-line span,
.wh-empty,
.wh-order-meta,
.wh-confirm-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.wh-line strong,
.wh-line > div:first-child span {
  display: block;
}
.wh-empty {
  margin: 12px 0 0;
}
.wh-qty {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 6px;
}
.wh-qty :deep(.el-input-number) {
  width: 108px;
}
.wh-qty .wh-unit,
.wh-line .wh-unit {
  display: inline;
  color: var(--el-text-color-primary);
  font-size: 13px;
  white-space: nowrap;
}
.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
:deep(td.mat-image-col) {
  padding: 2px !important;
}
:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}
:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}
:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.muted {
  color: var(--el-text-color-secondary);
}
.wh-qr {
  display: block;
  width: 240px;
  height: 240px;
  margin: 8px auto 0;
}
.wh-done :deep(.el-result) {
  padding: 8px 0 0;
}
.wh-sign-img {
  display: block;
  width: 100%;
  margin-top: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
}
</style>

<style>
.wh-order-popper .el-select-dropdown__wrap {
  max-height: 180px;
}
</style>
