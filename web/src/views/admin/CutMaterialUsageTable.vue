<template>
  <div class="cut-usage-table">
    <el-table
      ref="tableRef"
      :data="rows"
      border
      style="width: 100%"
      :span-method="spanMethod"
      @header-dragend="onHeaderDragend"
    >
      <el-table-column
        column-key="image"
        label="图片"
        :width="colWidth('image', 72)"
        align="center"
        class-name="mat-image-col"
        header-class-name="mat-image-col"
        resizable
      >
        <template #default="{ row }">
          <el-image
            v-if="row.image_url"
            :src="row.image_url"
            :preview-src-list="[row.image_url]"
            fit="contain"
            class="product-thumb"
            preview-teleported
          />
          <span v-else class="muted mat-image-empty"></span>
        </template>
      </el-table-column>
      <el-table-column
        prop="factory_model"
        label="工厂型号"
        :width="colWidth('factory_model', 120)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column
        column-key="order_color_name"
        prop="order_color_name"
        label="颜色"
        :width="colWidth('order_color_name', 72)"
        show-overflow-tooltip
        resizable
      >
        <template #default="{ row }">{{ dash(row.order_color_name) }}</template>
      </el-table-column>
      <el-table-column
        column-key="material_image"
        label="物料图片"
        :width="colWidth('material_image', 72)"
        align="center"
        class-name="mat-image-col"
        header-class-name="mat-image-col"
        resizable
      >
        <template #default="{ row }">
          <el-image
            v-if="row.material_image_url"
            :src="row.material_image_url"
            :preview-src-list="[row.material_image_url]"
            fit="contain"
            class="product-thumb"
            preview-teleported
          />
          <span v-else class="muted mat-image-empty"></span>
        </template>
      </el-table-column>
      <el-table-column
        prop="material_code"
        label="物料编号"
        :width="colWidth('material_code', 120)"
        show-overflow-tooltip
        resizable
      >
        <template #default="{ row }">{{ dash(row.material_code) }}</template>
      </el-table-column>
      <el-table-column
        prop="material_name"
        label="名称"
        :width="colWidth('material_name', 140)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column
        prop="color_name"
        label="物料颜色"
        :width="colWidth('color_name', 96)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column prop="unit_name" label="用量单位" :width="colWidth('unit_name', 96)" resizable>
        <template #default="{ row }">{{ usageUnit(row.unit_name) }}</template>
      </el-table-column>
      <el-table-column prop="budget_qty" label="预算用量" :width="colWidth('budget_qty', 96)" resizable />
      <el-table-column
        prop="average_usage"
        label="实际平均用量"
        :width="colWidth('average_usage', 168)"
        align="center"
        resizable
      >
        <template #default="{ row }">
          <div v-if="row.materialSpan !== 0" class="cut-usage-average">
            <span>{{ row.average_usage }}</span>
            <div v-if="row.supplier_product_id" class="cut-usage-average-actions">
              <el-tooltip
                v-if="row.on_bom && row.average_usage !== '—'"
                content="应用到产品开发-物料明细-用量"
                placement="top"
                :show-after="200"
              >
                <el-button
                  link
                  type="primary"
                  size="small"
                  :loading="applyingKey === usageKey(row)"
                  @click="applyAverage(row)"
                >
                  应用
                </el-button>
              </el-tooltip>
              <el-popover
                v-if="historyOf(row).items.length"
                placement="bottom-end"
                :width="360"
                trigger="click"
                @show="loadHistory(row)"
              >
                <template #reference>
                  <el-button link type="primary" size="small">历史</el-button>
                </template>
                <div v-loading="historyOf(row).loading" class="cut-usage-history">
                  <div v-if="!historyOf(row).items.length" class="cut-usage-history-empty">暂无用量变更记录</div>
                  <button
                    v-for="item in historyOf(row).items"
                    :key="item.id"
                    type="button"
                    class="cut-usage-history-item"
                    @click="restoreHistory(row, item)"
                  >
                    <span>{{ historyChangeText(row, item) }}</span>
                    <span class="cut-usage-history-meta">
                      <template v-if="sourceLabel(item.source)">{{ sourceLabel(item.source) }} · </template>
                      {{ item.changed_by_name || '—' }}
                      <template v-if="item.changed_at"> · {{ formatHistoryTime(item.changed_at) }}</template>
                    </span>
                  </button>
                </div>
              </el-popover>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="employee_name"
        label="员工"
        :width="colWidth('employee_name', 88)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column
        prop="consumed_qty"
        label="消耗物料/报工数量"
        :width="colWidth('consumed_qty', 188)"
        resizable
      >
        <template #default="{ row }">
          <el-popover
            v-if="row.records.length"
            trigger="hover"
            placement="left"
            :width="980"
            :show-after="200"
          >
            <table class="cut-usage-records">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>类型</th>
                  <th>生产单</th>
                  <th>领料</th>
                  <th>上次剩余</th>
                  <th>退仓库数量</th>
                  <th>车间剩余</th>
                  <th>消耗物料</th>
                  <th>报工数量</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="record in recordsDesc(row)" :key="record.event_key || record.work_log_id">
                  <td>{{ record.reported_at }}</td>
                  <td>{{ kindLabel(record.kind) }}</td>
                  <td>{{ record.header_no }}</td>
                  <td>{{ recordText(record.issued_qty) }}</td>
                  <td>{{ recordText(record.opening_qty) }}</td>
                  <td>{{ recordText(record.return_qty) }}</td>
                  <td>{{ recordText(record.remain_qty) }}</td>
                  <td>{{ recordText(record.consumed_qty) }}</td>
                  <td>{{ recordText(record.pairs) }}</td>
                </tr>
              </tbody>
            </table>
            <template #reference>
              <button type="button" class="cut-usage-pop">{{ consumedCell(row) }}</button>
            </template>
          </el-popover>
          <span v-else>{{ consumedCell(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="usage_per_pair" label="每双用量" :width="colWidth('usage_per_pair', 96)" resizable />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'

export type CutEmployee = { id: number; name: string; pairs: string }
export type CutReportRecord = {
  kind: 'issue' | 'return' | 'report'
  event_key: string
  work_log_id: number
  reported_at: string
  sort_at: string
  header_no: string
  issued_qty: string | null
  opening_qty: string | null
  return_qty: string | null
  remain_qty: string | null
  consumed_qty: string | null
  pairs: string | null
}
export type CutPickup = {
  issued_qty: string
  return_qty: string
  consumed_qty: string
  usage_per_pair: string | null
  records: CutReportRecord[]
}
export type CutMaterial = {
  supplier_product_id: number | null
  material_code: string | null
  material_name: string | null
  image_url: string | null
  color_name: string | null
  unit_name: string | null
  on_bom: boolean
  budget_qty: string | null
  average_usage: string | null
  pickups: Record<string, CutPickup>
}
export type CutModel = {
  own_product_id: number
  factory_model: string
  order_color_name: string | null
  image_url: string | null
  total_pairs: string
  employees: CutEmployee[]
  materials: CutMaterial[]
}

const props = defineProps<{
  models: CutModel[]
  dateFrom?: string
  dateTo?: string
}>()
const emit = defineEmits<{ applied: [] }>()

type FlatRow = {
  own_product_id: number
  factory_model: string
  order_color_name: string | null
  image_url: string | null
  supplier_product_id: number | null
  on_bom: boolean
  material_code: string
  material_name: string
  material_image_url: string | null
  color_name: string
  unit_name: string
  budget_qty: string
  average_usage: string
  employee_name: string
  issued_qty: string
  return_qty: string
  consumed_qty: string
  pairs: string
  usage_per_pair: string
  records: CutReportRecord[]
  productSpan: number
  modelSpan: number
  materialSpan: number
}

const PRODUCT_KEYS = new Set(['factory_model', 'image'])
const COLOR_KEYS = new Set(['order_color_name'])
const MATERIAL_KEYS = new Set([
  'material_image',
  'material_code',
  'material_name',
  'color_name',
  'unit_name',
  'budget_qty',
  'average_usage',
])

const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('business-report-cut-usage', tableRef, {
  flexKey: 'material_name',
  flexDefaultMin: 100,
  fitToContainer: true,
})

const rows = computed(() => mergeSameProduct(props.models.flatMap((model) => flatten(model))))

function pickedEmployees(material: CutMaterial, employees: CutEmployee[]): CutEmployee[] {
  const moved = employees.filter((employee) => {
    const picked = material.pickups?.[String(employee.id)]
    if (!picked) return false
    if (Number(picked.issued_qty) > 0 || Number(picked.return_qty) > 0) return true
    return (picked.records || []).some((row) => row.kind === 'issue' || row.kind === 'return')
  })
  return moved.length ? moved : [{ id: 0, name: '—', pairs: '0' }]
}

function flatten(model: CutModel): FlatRow[] {
  const employees = model.employees.length ? model.employees : [{ id: 0, name: '—', pairs: '0' }]
  const materials = model.materials.length ? model.materials : [emptyMaterial()]
  const groups = materials.map((material) => ({
    material,
    employees: pickedEmployees(material, employees),
  }))
  const total = groups.reduce((sum, group) => sum + group.employees.length, 0)
  const out: FlatRow[] = []
  let firstModelRow = true
  groups.forEach((group) => {
    group.employees.forEach((employee, employeeIndex) => {
      const picked = group.material.pickups?.[String(employee.id)]
      out.push({
        own_product_id: model.own_product_id,
        factory_model: model.factory_model,
        order_color_name: model.order_color_name,
        image_url: model.image_url,
        supplier_product_id: group.material.supplier_product_id,
        on_bom: group.material.on_bom,
        material_code: dash(group.material.material_code),
        material_name: dash(group.material.material_name),
        material_image_url: group.material.image_url,
        color_name: dash(group.material.color_name),
        unit_name: dash(group.material.unit_name),
        budget_qty: qtyText(group.material.budget_qty),
        average_usage: qtyText(group.material.average_usage),
        employee_name: employee.name || '—',
        issued_qty: picked?.issued_qty ?? '0',
        return_qty: picked?.return_qty ?? '0',
        consumed_qty: picked?.consumed_qty ?? '0',
        pairs: employee.pairs || '0',
        usage_per_pair: qtyText(picked?.usage_per_pair),
        records: picked?.records || [],
        productSpan: 0,
        modelSpan: firstModelRow ? total : 0,
        materialSpan: employeeIndex === 0 ? group.employees.length : 0,
      })
      firstModelRow = false
    })
  })
  return out
}

function mergeSameProduct(flat: FlatRow[]): FlatRow[] {
  let index = 0
  while (index < flat.length) {
    const mark = `${flat[index].factory_model}\0${flat[index].image_url || ''}`
    let end = index + 1
    while (end < flat.length && `${flat[end].factory_model}\0${flat[end].image_url || ''}` === mark) end += 1
    flat[index].productSpan = end - index
    for (let cursor = index + 1; cursor < end; cursor += 1) flat[cursor].productSpan = 0
    index = end
  }
  return flat
}

function emptyMaterial(): CutMaterial {
  return {
    supplier_product_id: null,
    material_code: null,
    material_name: null,
    image_url: null,
    color_name: null,
    unit_name: null,
    on_bom: false,
    budget_qty: null,
    average_usage: null,
    pickups: {},
  }
}

function colKey(column: { property?: string; columnKey?: string }) {
  return String(column.property || column.columnKey || '')
}

function spanMethod({
  row,
  column,
}: {
  row: FlatRow
  column: { property?: string; columnKey?: string }
}) {
  const key = colKey(column)
  if (PRODUCT_KEYS.has(key)) {
    return row.productSpan > 0 ? { rowspan: row.productSpan, colspan: 1 } : { rowspan: 0, colspan: 0 }
  }
  if (COLOR_KEYS.has(key)) {
    return row.modelSpan > 0 ? { rowspan: row.modelSpan, colspan: 1 } : { rowspan: 0, colspan: 0 }
  }
  if (MATERIAL_KEYS.has(key)) {
    return row.materialSpan > 0
      ? { rowspan: row.materialSpan, colspan: 1 }
      : { rowspan: 0, colspan: 0 }
  }
  return { rowspan: 1, colspan: 1 }
}

function dash(value: string | null | undefined) {
  return value ? value : '—'
}

function usageUnit(value: string | null | undefined) {
  if (!value || value === '—') return '—'
  return value.endsWith('/双') ? value : `${value}/双`
}

function qtyText(value: string | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  return value
}

function consumedCell(row: FlatRow) {
  const unit = row.unit_name && row.unit_name !== '—' ? row.unit_name : ''
  return `${row.consumed_qty}${unit}/${row.pairs}双`
}

function kindLabel(kind: string) {
  if (kind === 'issue') return '领料'
  if (kind === 'return') return '退料'
  return '报工'
}

function recordText(value: string | null | undefined) {
  return value == null || value === '' ? '—' : value
}

function recordsDesc(row: FlatRow) {
  return [...row.records].sort(
    (a, b) => (b.sort_at || b.reported_at).localeCompare(a.sort_at || a.reported_at) || b.work_log_id - a.work_log_id,
  )
}

type UsageHistoryItem = {
  id: number
  old_qty: string | number | null
  new_qty: string | number
  source: string
  changed_by_name?: string | null
  changed_at?: string | null
}

const applyingKey = ref('')
const historyMap = ref<Record<string, { loading: boolean; items: UsageHistoryItem[] }>>({})
let historyLoadGen = 0

function usageKey(row: FlatRow) {
  return `${row.own_product_id}:${row.supplier_product_id}`
}

function historyOf(row: FlatRow) {
  return historyMap.value[usageKey(row)] || { loading: false, items: [] }
}

function sourceLabel(source: string) {
  if (source === 'cut_average') return ''
  if (source === 'product_create') return '产品创建'
  if (source === 'history_restore') return '历史回填'
  return '产品保存'
}

function formatQty(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return String(Number(n.toFixed(4)))
}

function qtyWithUnit(row: FlatRow, value: string | number | null | undefined) {
  const text = formatQty(value)
  const unit = row.unit_name && row.unit_name !== '—' ? `${row.unit_name}/双` : ''
  return unit && text !== '—' ? `${text} ${unit}` : text
}

function historyChangeText(row: FlatRow, item: UsageHistoryItem) {
  const next = qtyWithUnit(row, item.new_qty)
  if (item.old_qty == null || item.old_qty === '') return `改成 ${next}`
  return `由 ${qtyWithUnit(row, item.old_qty)} 改成 ${next}`
}

function formatHistoryTime(value?: string | null) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function loadHistory(row: FlatRow, gen = historyLoadGen) {
  if (!row.supplier_product_id) return
  const key = usageKey(row)
  const productId = row.own_product_id
  const supplierId = row.supplier_product_id
  historyMap.value[key] = { loading: true, items: historyOf(row).items }
  try {
    const res: any = await http.get('/own-products/material-usage-history', {
      params: {
        own_product_id: productId,
        supplier_product_id: supplierId,
        limit: 30,
      },
    })
    if (gen !== historyLoadGen) return
    historyMap.value[key] = { loading: false, items: res.data?.items || [] }
  } catch {
    if (gen !== historyLoadGen) return
    historyMap.value[key] = { loading: false, items: [] }
  }
}

watch(
  () => props.models,
  (models) => {
    const gen = ++historyLoadGen
    const seen = new Set<string>()
    for (const model of models || []) {
      for (const material of model.materials || []) {
        if (!model.own_product_id || !material.supplier_product_id) continue
        const key = `${model.own_product_id}:${material.supplier_product_id}`
        if (seen.has(key)) continue
        seen.add(key)
        void loadHistory(
          {
            own_product_id: model.own_product_id,
            supplier_product_id: material.supplier_product_id,
          } as FlatRow,
          gen,
        )
      }
    }
  },
  { immediate: true },
)

async function applyAverage(row: FlatRow) {
  if (!row.supplier_product_id || row.average_usage === '—') return
  try {
    const unit = row.unit_name && row.unit_name !== '—' ? `${row.unit_name}/双` : ''
    const from = unit && row.budget_qty !== '—' ? `${row.budget_qty}${unit}` : row.budget_qty
    const to = unit && row.average_usage !== '—' ? `${row.average_usage} ${unit}` : row.average_usage
    await ElMessageBox.confirm(
      `把「${row.material_name}」的用量由 ${from} 改成 ${to}`,
      '应用到产品开发--物料明细--用量',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const key = usageKey(row)
  applyingKey.value = key
  try {
    const res: any = await http.post('/business-report/cut-material-usage/apply', {
      own_product_id: row.own_product_id,
      supplier_product_id: row.supplier_product_id,
      date_from: props.dateFrom || null,
      date_to: props.dateTo || null,
    })
    if (res.data?.changed) ElMessage.success(`产品用量已改为 ${res.data.qty}`)
    else ElMessage.info('产品用量已经是这个数')
    emit('applied')
  } catch {
    // 请求错误已由拦截器提示
  } finally {
    applyingKey.value = ''
  }
}

async function restoreHistory(row: FlatRow, item: UsageHistoryItem) {
  try {
    await ElMessageBox.confirm(
      `把「${row.material_name}」的产品用量改回 ${formatQty(item.new_qty)}？`,
      '回填历史用量',
      { type: 'warning', confirmButtonText: '覆盖', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res: any = await http.post('/business-report/cut-material-usage/restore', {
      history_id: item.id,
    })
    if (res.data?.changed) ElMessage.success(`产品用量已改为 ${res.data.qty}`)
    else ElMessage.info('产品用量已经是这个数')
    emit('applied')
  } catch {
    // 请求错误已由拦截器提示
  }
}
</script>

<style scoped>
.cut-usage-table {
  margin-bottom: 16px;
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
.cut-usage-average {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  line-height: 1.4;
}
.cut-usage-average-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 2px 8px;
}
.cut-usage-pop {
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  color: var(--el-color-primary);
  cursor: pointer;
}
.cut-usage-history {
  max-height: 280px;
  overflow: auto;
}
.cut-usage-history-empty {
  padding: 8px 0;
  color: #94a3b8;
}
.cut-usage-history-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 8px 6px;
  border: none;
  border-bottom: 1px solid #eef2f7;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.cut-usage-history-item:last-child {
  border-bottom: none;
}
.cut-usage-history-item:hover {
  background: #f5f9ff;
}
.cut-usage-history-meta {
  color: #94a3b8;
  font-size: 12px;
}
</style>

<style>
.cut-usage-records {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.4;
}
.cut-usage-records th,
.cut-usage-records td {
  padding: 6px 8px;
  border-bottom: 1px solid #ebeef5;
  text-align: right;
  white-space: nowrap;
}
.cut-usage-records th:first-child,
.cut-usage-records td:first-child,
.cut-usage-records th:nth-child(2),
.cut-usage-records td:nth-child(2),
.cut-usage-records th:nth-child(3),
.cut-usage-records td:nth-child(3) {
  text-align: left;
}
.cut-usage-records th {
  color: #606266;
  font-weight: 600;
  background: #fafafa;
}
</style>
