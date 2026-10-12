<template>
  <div class="tooling-page">
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">模具</h1>
      </div>
    </header>
    <div :class="embedded ? 'inv-panel' : 'admin-card'" class="tooling-panel">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="编号 / 名称"
          style="width: 220px"
          @clear="page = 1"
          @keyup.enter="page = 1"
        />
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.shared_materials.write'" type="primary" @click="openReceive">
          到货登记
        </el-button>
        <el-button @click="openReceipts">入库记录</el-button>
      </div>
      <div class="category-filter">
        <button type="button" class="cat-chip" :class="{ active: kindFilter === '' }" @click="setKind('')">
          全部
        </button>
        <button
          v-for="kind in toolingKinds"
          :key="kind.value"
          type="button"
          class="cat-chip"
          :class="{ active: kindFilter === kind.value }"
          @click="setKind(kind.value)"
        >
          {{ kind.label }}
        </button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="pagedRows"
          row-key="row_key"
          border
          stripe
          style="width: 100%"
          v-loading="loading"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="code"
            label="编号"
            :width="colWidth('code', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="kind_label"
            label="分类"
            :width="colWidth('kind_label', 96)"
            resizable
          />
          <el-table-column
            column-key="department_name"
            prop="department_name"
            label="使用部门"
            :width="colWidth('department_name', 100)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.department_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="码数" align="center">
            <el-table-column
              v-for="s in displaySizes"
              :key="s.id"
              :column-key="`size_${s.id}`"
              :label="s.size_value"
              :width="colWidth(`size_${s.id}`, 56)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ qtyText(row, s.id) }}</template>
            </el-table-column>
          </el-table-column>
          <el-table-column
            prop="total_qty"
            label="总数"
            :width="colWidth('total_qty', 72)"
            align="right"
            resizable
          />
          <el-table-column
            prop="amount"
            label="金额"
            :width="colWidth('amount', 90)"
            align="right"
            resizable
          >
            <template #header>
              <span title="在库数量 × 最近到货单价">金额</span>
            </template>
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="72" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="openLedger(row)">流水</el-button>
            </template>
          </el-table-column>
          <template #empty>还没有模具，请先到货登记</template>
        </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="filteredRows.length"
          :page-sizes="[10, 20, 50, 100]"
        />
      </div>
    </div>

    <el-dialog v-model="receiveVisible" :title="dialogTitle" width="960px" top="6vh" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="分类" required>
          <el-radio-group v-model="receiveForm.kind" @change="onKindChange">
            <el-radio v-for="kind in toolingKinds" :key="kind.value" :value="kind.value">
              {{ kind.label }}
            </el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="供应商" required>
          <el-select
            v-model="receiveForm.supplier_id"
            filterable
            placeholder="选择供应商"
            style="width: 100%"
            popper-class="tooling-popper"
          >
            <el-option
              v-for="p in suppliers"
              :key="p.id"
              :label="p.short_name || p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="到货日期">
          <el-date-picker
            v-model="receiveForm.receipt_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="默认今天"
          />
        </el-form-item>
        <el-form-item label="送货单号">
          <el-input v-model="receiveForm.delivery_note_no" maxlength="80" placeholder="选填" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="receiveForm.notes" maxlength="255" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <div v-for="(line, index) in receiveLines" :key="line.key" class="receipt-line">
        <div class="receipt-line-head">
          <span>编号 {{ index + 1 }}</span>
          <el-button v-if="receiveLines.length > 1" link type="danger" @click="removeLine(line.key)">删除</el-button>
        </div>
        <el-form label-width="88px">
          <el-form-item label="使用部门" required>
            <el-radio-group
              v-if="departmentChoices.length"
              v-model="line.department_id"
              :disabled="knifeDieLocked"
            >
              <el-radio v-for="dept in departmentChoices" :key="dept.id" :value="dept.id">{{ dept.name }}</el-radio>
            </el-radio-group>
            <p v-else-if="knifeDieLocked" class="form-hint">刀模只能记入名称带「生产」的一级部门。</p>
            <p v-else class="form-hint">请先在员工与部门里建立名称带「开发」或「生产」的一级部门。</p>
          </el-form-item>
          <el-form-item label="编号" required>
            <el-select
              v-model="line.code"
              filterable
              allow-create
              default-first-option
              placeholder="选择已有编号，或直接填写新编号"
              style="width: 100%"
              popper-class="tooling-popper"
              @change="onLineCode(line, $event)"
            >
              <el-option v-for="row in codeOptions" :key="row.id" :label="row.code" :value="row.code" />
            </el-select>
          </el-form-item>
          <el-form-item :label="priceLabel" required>
            <el-input-number
              v-model="line.unit_price"
              :min="0"
              :precision="4"
              :step="1"
              :controls="false"
              style="width: 180px"
              placeholder="单价"
            />
          </el-form-item>
          <el-form-item label="码数" required>
            <div v-if="activeSizes.length" class="size-grid">
              <label v-for="s in activeSizes" :key="s.id" class="size-cell">
                <span>{{ s.size_value }}</span>
                <el-input-number
                  v-model="line.qty[s.id]"
                  :min="0"
                  :precision="1"
                  :step="0.5"
                  :controls="false"
                  placeholder="0"
                />
              </label>
            </div>
            <p v-if="activeSizes.length" class="form-hint">数量可以填 0.5，表示一只。</p>
            <p v-else class="form-hint">请先在基础数据里维护尺码。</p>
          </el-form-item>
          <el-form-item label="小计">
            <span>总数 {{ lineTotal(line) }}</span>
            <span class="sum-gap">金额 {{ formatMoney(lineAmount(line)) }}</span>
          </el-form-item>
        </el-form>
      </div>
      <el-button @click="addLine">添加编号</el-button>
      <p class="form-hint receive-sum">合计总数 {{ receiveTotal }}，金额 {{ formatMoney(receiveAmount) }}</p>
      <p v-if="editingReceiptId" class="form-hint">保存后按这次填写更正库存和待结算。已对账的到货不能修改。</p>
      <p v-else class="form-hint">保存后按编号计入库存，并生成该供应商的待结算明细。分类整张单相同，每个编号可以记给不同部门。不会写入物料色卡。</p>
      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReceive">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ledgerVisible" :title="ledgerTitle" width="760px">
      <el-table
        ref="ledgerTableRef"
        :data="ledgers"
        border
        style="width: 100%"
        v-loading="ledgerLoading"
        @header-dragend="onLedgerHeaderDragend"
      >
        <el-table-column prop="created_at" label="时间" :width="ledgerColWidth('created_at', 160)" resizable>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="size_value" label="码" :width="ledgerColWidth('size_value', 70)" resizable />
        <el-table-column prop="qty_delta" label="变动" :width="ledgerColWidth('qty_delta', 80)" align="right" resizable>
          <template #default="{ row }">{{ signedQty(row.qty_delta) }}</template>
        </el-table-column>
        <el-table-column prop="qty_after" label="结存" :width="ledgerColWidth('qty_after', 80)" align="right" resizable />
        <el-table-column prop="source_label" label="来源" :width="ledgerColWidth('source_label', 80)" resizable />
        <el-table-column prop="notes" label="备注" :width="ledgerColWidth('notes', 220)" show-overflow-tooltip resizable />
      </el-table>
    </el-dialog>

    <el-dialog v-model="receiptVisible" title="入库记录" width="96%" top="6vh">
      <el-table
        ref="receiptTableRef"
        class="receipt-table"
        :data="receiptTableRows"
        row-key="row_key"
        border
        style="width: 100%"
        max-height="640"
        v-loading="receiptLoading"
        :span-method="receiptSpanMethod"
        @header-dragend="onReceiptHeaderDragend"
      >
        <el-table-column prop="receipt_date" label="到货日期" :width="receiptColWidth('receipt_date', 108)" resizable />
        <el-table-column
          prop="delivery_note_no"
          label="送货单号"
          :width="receiptColWidth('delivery_note_no', 140)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.delivery_note_no || '—' }}</template>
        </el-table-column>
        <el-table-column prop="kind_label" label="分类" :width="receiptColWidth('kind_label', 72)" resizable />
        <el-table-column
          column-key="department_name"
          prop="department_name"
          label="部门"
          :width="receiptColWidth('department_name', 100)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.department_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="code" label="编号" :width="receiptColWidth('code', 110)" show-overflow-tooltip resizable />
        <el-table-column prop="supplier_name" label="供应商" :width="receiptColWidth('supplier_name', 120)" show-overflow-tooltip resizable />
        <el-table-column prop="unit_price" label="单价" :width="receiptColWidth('unit_price', 90)" align="right" resizable>
          <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column label="码数" align="center">
          <el-table-column
            v-for="s in receiptSizes"
            :key="s.id"
            :column-key="`size_${s.id}`"
            :label="s.size_value"
            :width="receiptColWidth(`size_${s.id}`, 48)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ receiptSizeQty(row, s.id) }}</template>
          </el-table-column>
        </el-table-column>
        <el-table-column prop="total_qty" label="总数" :width="receiptColWidth('total_qty', 64)" align="right" resizable />
        <el-table-column prop="amount" label="金额" :width="receiptColWidth('amount', 88)" align="right" resizable>
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="80" fixed="right" :resizable="false">
          <template #default="{ row }">
            <el-tooltip :disabled="!row.statemented" content="已对账，不能修改" placement="top">
              <span>
                <el-button
                  v-permission="'btn.shared_materials.write'"
                  link
                  type="primary"
                  :disabled="row.statemented"
                  @click="openEdit(row)"
                >
                  修改
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

defineProps<{ embedded?: boolean }>()

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const masterSizes = ref<any[]>([])
const suppliers = ref<any[]>([])
const keyword = ref('')
const kindFilter = ref('')
const toolingKinds = [
  { value: 'shoe_last', label: '楦头', unit: '双' },
  { value: 'knife_die', label: '刀模', unit: '套' },
  { value: 'sole_mold', label: '底模', unit: '套' },
  { value: 'heel_mold', label: '鞋跟模具', unit: '套' },
  { value: 'other_mold', label: '其它模具', unit: '套' },
]
const page = ref(1)
const pageSize = ref(20)

const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('tooling-warehouse', tableRef, {
  flexKey: 'code',
  flexDefaultMin: 100,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const ledgerTableRef = ref()
const { colWidth: ledgerColWidth, onHeaderDragend: onLedgerHeaderDragend } = useTableColWidths(
  'tooling-ledger',
  ledgerTableRef,
  { flexKey: 'notes', flexDefaultMin: 120 },
)
const receiptTableRef = ref()
const { colWidth: receiptColWidth, onHeaderDragend: onReceiptHeaderDragend } = useTableColWidths(
  'tooling-receipts-sizes',
  receiptTableRef,
  { flexKey: 'code', flexDefaultMin: 100 },
)

const activeSizes = computed(() =>
  masterSizes.value
    .filter((s) => s.is_active !== false)
    .slice()
    .sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || a.id - b.id),
)

const displaySizes = computed(() => {
  const map = new Map<number, any>()
  for (const s of activeSizes.value) map.set(s.id, s)
  for (const row of rows.value) {
    for (const key of Object.keys(row.sizes || {})) {
      const id = Number(key)
      if (!map.has(id)) {
        const known = masterSizes.value.find((s) => s.id === id)
        map.set(id, known || { id, size_value: key, sort_order: 9999 })
      }
    }
  }
  return [...map.values()].sort(
    (a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || a.id - b.id,
  )
})

const filteredRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return rows.value.filter((row) => {
    if (kindFilter.value && row.kind !== kindFilter.value) return false
    if (!kw) return true
    return (
      String(row.code || '').toLowerCase().includes(kw) ||
      String(row.name || '').toLowerCase().includes(kw) ||
      String(row.department_name || '').toLowerCase().includes(kw)
    )
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

function setKind(kind: string) {
  kindFilter.value = kind
  page.value = 1
}

function formatQty(value: number | string | null | undefined) {
  const n = Number(value || 0)
  if (!n) return ''
  const rounded = Math.round(n * 2) / 2
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

function isHalfQty(value: number) {
  if (!value) return true
  return Math.abs(value * 2 - Math.round(value * 2)) < 0.001
}

function qtyText(row: any, sizeId: number) {
  return formatQty(row.sizes?.[String(sizeId)])
}

function formatMoney(n: number | null | undefined) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatDateTime(v: any) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

function signedQty(n: number) {
  const text = formatQty(n)
  if (!text) return '0'
  return Number(n) > 0 ? `+${text}` : text
}

const receiptSizes = computed(() => {
  const map = new Map<number, any>()
  for (const line of receipts.value) {
    for (const size of line.sizes || []) {
      if (map.has(size.size_id)) continue
      const known = masterSizes.value.find((item) => item.id === size.size_id)
      map.set(
        size.size_id,
        known || { id: size.size_id, size_value: size.size_value, sort_order: 9999 },
      )
    }
  }
  return [...map.values()].sort(
    (a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || a.id - b.id,
  )
})

function receiptSizeQty(row: any, sizeId: number) {
  const found = (row.sizes || []).find((size: any) => size.size_id === sizeId)
  return formatQty(found?.qty)
}

const receiptSpanKeys = new Set([
  'receipt_date',
  'delivery_note_no',
  'kind_label',
  'supplier_name',
  'actions',
])

const receiptTableRows = computed(() => {
  const groups = new Map<number, any[]>()
  for (const line of receipts.value) {
    const list = groups.get(line.receipt_id) || []
    list.push(line)
    groups.set(line.receipt_id, list)
  }
  const out: any[] = []
  for (const lines of groups.values()) {
    lines.forEach((line, index) => {
      out.push({
        ...line,
        row_key: String(line.id),
        receipt_span: index === 0 ? lines.length : 0,
      })
    })
  }
  return out
})

function receiptSpanMethod({ row, column }: { row: any; column: any }) {
  const key = column?.property || column?.columnKey
  if (!receiptSpanKeys.has(key)) return { rowspan: 1, colspan: 1 }
  return row.receipt_span > 0 ? { rowspan: row.receipt_span, colspan: 1 } : { rowspan: 0, colspan: 0 }
}

function today() {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

async function load() {
  loading.value = true
  try {
    const [itemRes, sizeRes]: any[] = await Promise.all([
      http.get('/tooling/items'),
      http.get('/sizes'),
    ])
    rows.value = itemRes.data?.items || []
    masterSizes.value = sizeRes.data?.items || []
    const maxPage = Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value) || 1)
    if (page.value > maxPage) page.value = maxPage
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadSuppliers() {
  if (suppliers.value.length) return
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 500 },
  })
  suppliers.value = res.data?.items || []
}

type ReceiveLine = {
  key: number
  department_id: number | null
  code: string
  unit_price: number | null
  qty: Record<number, number | null>
}

const receiveVisible = ref(false)
const editingReceiptId = ref<number | null>(null)
const dialogTitle = computed(() => (editingReceiptId.value ? '修改到货' : '到货登记'))
const useDepartments = ref<Array<{ id: number; name: string }>>([])
const receiveLines = ref<ReceiveLine[]>([])
let lineSeq = 1
const receiveForm = reactive({
  kind: 'shoe_last',
  supplier_id: null as number | null,
  receipt_date: '',
  delivery_note_no: '',
  notes: '',
})

function blankQty() {
  const qty: Record<number, number | null> = {}
  for (const s of activeSizes.value) qty[s.id] = null
  return qty
}

const knifeDieLocked = computed(() => receiveForm.kind === 'knife_die')
const departmentChoices = computed(() => {
  if (!knifeDieLocked.value) return useDepartments.value
  return useDepartments.value.filter((dept) => dept.name.includes('生产'))
})

function productionDepartmentId() {
  const exact = useDepartments.value.find((dept) => dept.name === '生产部')
  if (exact) return exact.id
  return useDepartments.value.find((dept) => dept.name.includes('生产'))?.id ?? null
}

function applyKnifeDepartment() {
  if (!knifeDieLocked.value) return
  const id = productionDepartmentId()
  if (!id) return
  for (const line of receiveLines.value) line.department_id = id
}

function blankLine(): ReceiveLine {
  const locked = receiveForm.kind === 'knife_die' ? productionDepartmentId() : null
  const only = useDepartments.value.length === 1 ? useDepartments.value[0].id : null
  return { key: lineSeq++, department_id: locked || only, code: '', unit_price: null, qty: blankQty() }
}

const codeOptions = computed(() => rows.value.filter((row) => row.kind === receiveForm.kind))
const priceLabel = computed(() => {
  const kind = toolingKinds.find((item) => item.value === receiveForm.kind)
  return `单价/${kind?.unit || '个'}`
})

function lineTotal(line: ReceiveLine) {
  const sum = activeSizes.value.reduce((total, s) => total + Number(line.qty[s.id] || 0), 0)
  return Math.round(sum * 2) / 2
}

function lineAmount(line: ReceiveLine) {
  return lineTotal(line) * Number(line.unit_price || 0)
}

const receiveTotal = computed(() => receiveLines.value.reduce((sum, line) => sum + lineTotal(line), 0))
const receiveAmount = computed(() => receiveLines.value.reduce((sum, line) => sum + lineAmount(line), 0))

function addLine() {
  if (receiveLines.value.length >= 40) {
    ElMessage.warning('一次最多登记40个编号')
    return
  }
  receiveLines.value.push(blankLine())
}

function removeLine(key: number) {
  if (receiveLines.value.length <= 1) return
  receiveLines.value = receiveLines.value.filter((line) => line.key !== key)
}

async function openReceive() {
  editingReceiptId.value = null
  receiveForm.kind = kindFilter.value || 'shoe_last'
  receiveForm.supplier_id = null
  receiveForm.receipt_date = today()
  receiveForm.delivery_note_no = ''
  receiveForm.notes = ''
  receiveLines.value = [blankLine()]
  receiveVisible.value = true
  try {
    const [deptRes]: any[] = await Promise.all([
      http.get('/tooling/departments'),
      loadSuppliers(),
    ])
    useDepartments.value = deptRes.data?.items || []
    applyKnifeDepartment()
    if (!knifeDieLocked.value && useDepartments.value.length === 1) {
      for (const line of receiveLines.value) {
        if (!line.department_id) line.department_id = useDepartments.value[0].id
      }
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

function onKindChange() {
  applyKnifeDepartment()
  for (const line of receiveLines.value) {
    const code = String(line.code || '').trim()
    const found = rows.value.find((row) => row.code === code)
    if (found && found.kind !== receiveForm.kind) line.code = ''
  }
}

function onLineCode(line: ReceiveLine, code: string) {
  const found = rows.value.find((row) => row.code === String(code || '').trim())
  if (!found || found.kind === receiveForm.kind) return
  line.code = ''
  ElMessage.warning(`编号 ${found.code} 已是${found.kind_label || '其他分类'}`)
}

async function submitReceive() {
  if (!receiveForm.supplier_id) {
    ElMessage.warning('请选择供应商')
    return
  }
  const lines = []
  const seen = new Set<string>()
  for (const line of receiveLines.value) {
    const code = String(line.code || '').trim()
    if (!code) {
      ElMessage.warning('请填写编号')
      return
    }
    if (seen.has(code)) {
      ElMessage.warning(`编号 ${code} 在本单重复`)
      return
    }
    seen.add(code)
    if (!line.department_id) {
      ElMessage.warning(`编号 ${code} 请选择使用部门`)
      return
    }
    if (!line.unit_price || line.unit_price <= 0) {
      ElMessage.warning(`编号 ${code} 请填写单价`)
      return
    }
    const rawSizes = activeSizes.value.map((s) => ({
      size_id: s.id,
      qty: Number(line.qty[s.id] || 0),
    }))
    if (rawSizes.some((row) => row.qty > 0 && !isHalfQty(row.qty))) {
      ElMessage.warning(`编号 ${code} 的数量只能填整数或 0.5，0.5 表示一只`)
      return
    }
    const sizes = rawSizes
      .map((row) => ({ size_id: row.size_id, qty: Math.round(row.qty * 2) / 2 }))
      .filter((row) => row.qty > 0)
    if (!sizes.length) {
      ElMessage.warning(`编号 ${code} 请填写到货数量`)
      return
    }
    lines.push({
      department_id: line.department_id,
      code,
      unit_price: line.unit_price,
      sizes,
    })
  }
  const payload = {
    kind: receiveForm.kind,
    supplier_id: receiveForm.supplier_id,
    receipt_date: receiveForm.receipt_date || null,
    delivery_note_no: receiveForm.delivery_note_no.trim() || null,
    notes: receiveForm.notes.trim() || null,
    lines,
  }
  saving.value = true
  try {
    if (editingReceiptId.value) {
      await http.put(`/tooling/receipts/${editingReceiptId.value}`, payload)
      ElMessage.success('已更正到货')
    } else {
      await http.post('/tooling/receipts', payload)
      ElMessage.success('已登记到货，并计入供应商待结算')
    }
    receiveVisible.value = false
    await load()
    if (receiptVisible.value) await openReceipts()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function openEdit(row: any) {
  if (row.statemented) return
  try {
    const [deptRes, detailRes]: any[] = await Promise.all([
      http.get('/tooling/departments'),
      http.get(`/tooling/receipts/${row.receipt_id}`),
      loadSuppliers(),
    ])
    useDepartments.value = deptRes.data?.items || []
    const data = detailRes.data
    if (data.statemented) {
      ElMessage.warning('已对账，不能修改')
      return
    }
    editingReceiptId.value = row.receipt_id
    receiveForm.kind = data.kind
    receiveForm.supplier_id = data.supplier_id
    receiveForm.receipt_date = data.receipt_date || ''
    receiveForm.delivery_note_no = data.delivery_note_no || ''
    receiveForm.notes = data.notes || ''
    receiveLines.value = (data.lines || []).map((line: any) => {
      const qty = blankQty()
      for (const size of line.sizes || []) qty[size.size_id] = Number(size.qty)
      return {
        key: lineSeq++,
        department_id: line.department_id,
        code: line.code,
        unit_price: Number(line.unit_price),
        qty,
      }
    })
    if (!receiveLines.value.length) receiveLines.value = [blankLine()]
    applyKnifeDepartment()
    receiveVisible.value = true
  } catch (e: any) {
    editingReceiptId.value = null
    ElMessage.error(e?.response?.data?.detail || '到货单加载失败')
  }
}

const ledgerVisible = ref(false)
const ledgerLoading = ref(false)
const ledgers = ref<any[]>([])
const ledgerTitle = ref('流水')

async function openLedger(row: any) {
  ledgerTitle.value = `${row.kind_label || ''} ${row.code} ${row.department_name || ''} 流水`.trim()
  ledgerVisible.value = true
  ledgerLoading.value = true
  try {
    const res: any = await http.get(`/tooling/items/${row.id}/ledgers`, {
      params: { department_id: row.department_id || undefined },
    })
    ledgers.value = res.data?.items || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '流水加载失败')
  } finally {
    ledgerLoading.value = false
  }
}

const receiptVisible = ref(false)
const receiptLoading = ref(false)
const receipts = ref<any[]>([])

async function openReceipts() {
  receiptVisible.value = true
  receiptLoading.value = true
  try {
    const res: any = await http.get('/tooling/receipts')
    receipts.value = res.data?.items || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '入库记录加载失败')
  } finally {
    receiptLoading.value = false
  }
  await nextTick()
  window.dispatchEvent(new Event('resize'))
}

watch(receiptSizes, () => {
  if (!receiptVisible.value) return
  nextTick(() => window.dispatchEvent(new Event('resize')))
})

onMounted(load)
</script>

<style scoped>
.tooling-page,
.tooling-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 12px;
}
.cat-chip {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
}
.cat-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.receipt-line {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px 12px 0;
  margin-bottom: 12px;
}
.receipt-line-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
}
.receive-sum {
  margin-top: 12px;
}
.size-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 8px;
  width: 100%;
}
.size-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #606266;
}
.size-cell :deep(.el-input-number) {
  width: 100%;
}
.form-hint {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.sum-gap {
  margin-left: 16px;
}
.receipt-table :deep(td.el-table__cell) {
  vertical-align: top;
}
</style>

<style>
.tooling-popper {
  z-index: 5000 !important;
}
</style>
