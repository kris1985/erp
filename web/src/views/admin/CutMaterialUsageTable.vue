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
        prop="factory_model"
        label="工厂型号"
        :width="colWidth('factory_model', 120)"
        show-overflow-tooltip
        resizable
      />
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
        label="颜色"
        :width="colWidth('color_name', 80)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column prop="unit_name" label="单位" :width="colWidth('unit_name', 64)" resizable />
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
      <el-table-column prop="pickup_qty" label="领料数量" :width="colWidth('pickup_qty', 96)" resizable />
      <el-table-column prop="pairs" label="报工数量" :width="colWidth('pairs', 88)" resizable />
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
export type CutPickup = { qty: string; usage_per_pair: string | null }
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
  pickup_qty: string
  pairs: string
  usage_per_pair: string
  modelSpan: number
  materialSpan: number
}

const MODEL_KEYS = new Set(['factory_model', 'image'])
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

const rows = computed(() => props.models.flatMap((model) => flatten(model)))

function flatten(model: CutModel): FlatRow[] {
  const employees = model.employees.length ? model.employees : [{ id: 0, name: '—', pairs: '0' }]
  const materials = model.materials.length ? model.materials : [emptyMaterial()]
  const total = materials.length * employees.length
  const out: FlatRow[] = []
  materials.forEach((material, materialIndex) => {
    employees.forEach((employee, employeeIndex) => {
      const picked = material.pickups?.[String(employee.id)]
      out.push({
        own_product_id: model.own_product_id,
        factory_model: model.factory_model,
        image_url: model.image_url,
        supplier_product_id: material.supplier_product_id,
        on_bom: material.on_bom,
        material_code: dash(material.material_code),
        material_name: dash(material.material_name),
        material_image_url: material.image_url,
        color_name: dash(material.color_name),
        unit_name: dash(material.unit_name),
        budget_qty: qtyText(material.budget_qty),
        average_usage: qtyText(material.average_usage),
        employee_name: employee.name || '—',
        pickup_qty: picked?.qty ?? '0',
        pairs: employee.pairs || '0',
        usage_per_pair: qtyText(picked?.usage_per_pair),
        modelSpan: materialIndex === 0 && employeeIndex === 0 ? total : 0,
        materialSpan: employeeIndex === 0 ? employees.length : 0,
      })
    })
  })
  return out
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
  if (MODEL_KEYS.has(key)) {
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

function qtyText(value: string | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  return value
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
