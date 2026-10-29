<template>
  <div class="sample-remakes-page">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">复版记录</h1>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="单号 / 客户 / 品牌 / 型号"
          style="width: 240px"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-select
          v-model="filters.customer_id"
          clearable
          filterable
          placeholder="客户"
          style="width: 180px"
          @change="reload"
        >
          <el-option v-for="item in customers" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-date-picker
          v-model="filters.dates"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 220px; flex: 0 0 220px"
          @change="reload"
        />
        <div class="spacer" />
        <el-button v-permission="'btn.sample_remakes.write'" type="primary" @click="openCreate">新增</el-button>
      </div>

      <div ref="tableHostRef" class="admin-table-host">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="displayRows"
          border
          stripe
          row-key="_key"
          style="width: 100%"
          :max-height="tableMaxHeight"
          :span-method="spanMethod"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="remake_date"
            label="日期"
            :width="colWidth('remake_date', 108)"
            resizable
          />
          <el-table-column
            prop="delivery_no"
            label="送货单号"
            :width="colWidth('delivery_no', 140)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            column-key="brand"
            label="品牌"
            :width="colWidth('brand', 100)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.line_brand || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="factory_model"
            label="工厂型号"
            :width="colWidth('factory_model', 120)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.line_factory_model || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="image"
            label="图片"
            :width="colWidth('image', 70)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.line_image_url"
                :src="row.line_image_url"
                :preview-src-list="[row.line_image_url]"
                preview-teleported
                fit="cover"
                class="table-thumb"
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="color"
            label="颜色"
            :width="colWidth('color', 80)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.line_color || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="qty"
            label="数量"
            :width="colWidth('qty', 72)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ row.line_qty }}</template>
          </el-table-column>
          <el-table-column
            column-key="unit_price"
            label="样品单价"
            :width="colWidth('unit_price', 96)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ money(row.line_unit_price) }}</template>
          </el-table-column>
          <el-table-column
            column-key="total_price"
            label="总价"
            :width="colWidth('total_price', 96)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ money(row.line_total_price) }}</template>
          </el-table-column>
          <el-table-column
            column-key="total_amount"
            label="合计"
            :width="colWidth('total_amount', 96)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ money(row.total_amount) }}</template>
          </el-table-column>
          <el-table-column
            prop="courier_company"
            label="快递公司"
            :width="colWidth('courier_company', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.courier_company || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="tracking_no"
            label="快递单号"
            :width="colWidth('tracking_no', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.tracking_no || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="300" fixed="right" align="center" :resizable="false">
            <template #default="{ row }">
              <div class="row-actions">
                <el-tooltip :disabled="!row.statement_id" content="已对账，作废对账单后才能修改" placement="top">
                  <span>
                    <el-button
                      v-permission="'btn.sample_remakes.write'"
                      link
                      type="primary"
                      :disabled="!!row.statement_id"
                      @click="openEdit(row)"
                    >修改</el-button>
                  </span>
                </el-tooltip>
                <el-tooltip :disabled="!row.statement_id" content="已对账，作废对账单后才能删除" placement="top">
                  <span>
                    <el-button
                      v-permission="'btn.sample_remakes.write'"
                      link
                      type="danger"
                      :disabled="!!row.statement_id"
                      @click="remove(row)"
                    >删除</el-button>
                  </span>
                </el-tooltip>
                <el-button link type="primary" @click="printRow(row, 'quote')">打印报价单</el-button>
                <el-button link type="primary" @click="printRow(row, 'delivery')">打印送货单</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.page_size"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="load"
          @size-change="reload"
        />
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '修改复版记录' : '新增复版记录'"
      width="980px"
      destroy-on-close
      append-to-body
    >
      <el-form label-width="88px" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="日期" required>
            <el-date-picker v-model="form.remake_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="送货单号">
            <el-input v-model="form.delivery_no" placeholder="留空自动生成" />
          </el-form-item>
          <el-form-item label="快递公司">
            <el-input v-model="form.courier_company" />
          </el-form-item>
          <el-form-item label="快递单号">
            <el-input v-model="form.tracking_no" />
          </el-form-item>
          <el-form-item label="客户" required>
            <el-select v-model="form.customer_id" filterable placeholder="选择客户" style="width: 100%">
              <el-option v-for="item in customers" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>

        <div class="line-toolbar">
          <span>样品明细</span>
          <el-button link type="primary" @click="addLine">添加一行</el-button>
        </div>
        <el-table
          ref="lineTableRef"
          :data="form.lines"
          border
          size="small"
          row-key="_key"
          style="width: 100%"
          :span-method="lineSpanMethod"
          @header-dragend="onLineHeaderDragend"
        >
          <el-table-column column-key="brand" label="品牌" :width="lineColWidth('brand', 120)" resizable>
            <template #default="{ row }">
              <el-input v-model="row.brand" placeholder="品牌" @change="onBrandChange(row)" />
            </template>
          </el-table-column>
          <el-table-column column-key="factory_model" label="工厂型号" :width="lineColWidth('factory_model', 150)" resizable>
            <template #default="{ row }">
              <el-select
                v-model="row.factory_model"
                filterable
                remote
                allow-create
                default-first-option
                placeholder="选择或输入"
                style="width: 100%"
                :remote-method="searchProducts"
                @change="onFactoryModelChange(row)"
              >
                <el-option
                  v-for="item in productOptions"
                  :key="item.id || item.product_code"
                  :label="item.product_code"
                  :value="item.product_code"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column column-key="image" label="图片" :width="lineColWidth('image', 88)" align="center" resizable>
            <template #default="{ row }">
              <div class="line-image">
                <el-image
                  v-if="row.image_url"
                  :src="row.image_url"
                  :preview-src-list="[row.image_url]"
                  preview-teleported
                  fit="cover"
                  class="table-thumb"
                />
                <el-upload
                  :show-file-list="false"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  :http-request="(opts) => uploadImage(row, opts)"
                >
                  <el-button link type="primary">{{ row.image_url ? '更换' : '上传' }}</el-button>
                </el-upload>
              </div>
            </template>
          </el-table-column>
          <el-table-column column-key="color" label="颜色" :width="lineColWidth('color', 110)" resizable>
            <template #default="{ row }">
              <el-select
                v-model="row.color"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="颜色"
                style="width: 100%"
              >
                <el-option v-for="name in row.colorOptions" :key="name" :label="name" :value="name" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="lineColWidth('qty', 110)" resizable>
            <template #default="{ row }">
              <el-input-number v-model="row.qty" :min="1" :precision="0" controls-position="right" style="width: 100%" />
            </template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="样品单价" :width="lineColWidth('unit_price', 120)" resizable>
            <template #default="{ row }">
              <el-input-number
                v-model="row.unit_price"
                :min="0"
                :precision="2"
                controls-position="right"
                style="width: 100%"
              />
            </template>
          </el-table-column>
          <el-table-column column-key="total_price" label="总价" :width="lineColWidth('total_price', 90)" align="right" resizable>
            <template #default="{ row }">{{ money(lineTotal(row)) }}</template>
          </el-table-column>
          <el-table-column column-key="total_amount" label="合计" :width="lineColWidth('total_amount', 90)" align="right" resizable>
            <template #default>{{ money(formTotal) }}</template>
          </el-table-column>
          <el-table-column label="" width="64" align="center" :resizable="false">
            <template #default="{ $index }">
              <el-button link type="danger" :disabled="form.lines.length <= 1" @click="form.lines.splice($index, 1)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type ProductOption = {
  id: number
  product_code: string
  image_url?: string
  quote_price?: number | null
  colors?: { name?: string }[]
  brand_quotes?: { brand_name?: string; quote_price?: number | null }[]
}

type LineForm = {
  _key: number
  brand: string
  own_product_id: number | null
  factory_model: string
  image_url: string
  color: string
  qty: number
  unit_price: number
  colorOptions: string[]
}

const MERGE_COL_INDEXES = new Set([0, 1, 2, 10, 11, 12, 13])

const tableRef = ref()
const lineTableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('sample-remakes-list', tableRef, {
  flexKey: 'factory_model',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const { colWidth: lineColWidth, onHeaderDragend: onLineHeaderDragend } = useTableColWidths(
  'sample-remakes-form-lines',
  lineTableRef,
)
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const total = ref(0)
const customers = ref<{ id: number; name: string }[]>([])
const productOptions = ref<ProductOption[]>([])
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
let lineKeySeq = 1

const filters = reactive({
  keyword: '',
  customer_id: null as number | null,
  dates: null as [string, string] | null,
  page: 1,
  page_size: 20,
})

function today() {
  return new Date().toLocaleDateString('sv-SE')
}

function blankLine(): LineForm {
  return {
    _key: lineKeySeq++,
    brand: '',
    own_product_id: null,
    factory_model: '',
    image_url: '',
    color: '',
    qty: 1,
    unit_price: 0,
    colorOptions: [],
  }
}

const form = reactive({
  remake_date: today(),
  delivery_no: '',
  courier_company: '',
  tracking_no: '',
  customer_id: null as number | null,
  lines: [blankLine()] as LineForm[],
})

const displayRows = computed(() => {
  const out: any[] = []
  for (const row of rows.value) {
    const lines = row.lines?.length ? row.lines : [null]
    lines.forEach((line: any, lineIndex: number) => {
      out.push({
        ...row,
        _key: `${row.id}-${line?.id ?? lineIndex}`,
        _lineIndex: lineIndex,
        _lineCount: lines.length,
        line_brand: line?.brand || '',
        line_factory_model: line?.factory_model || '',
        line_image_url: line?.image_url || '',
        line_color: line?.color || '',
        line_qty: line?.qty ?? '',
        line_unit_price: line?.unit_price ?? 0,
        line_total_price: line?.total_price ?? 0,
      })
    })
  }
  return out
})

function spanMethod({ row, columnIndex }: { row: any; columnIndex: number }) {
  if (!MERGE_COL_INDEXES.has(columnIndex)) return [1, 1]
  if (row._lineIndex === 0) return [row._lineCount || 1, 1]
  return [0, 0]
}

function lineSpanMethod({ rowIndex, columnIndex }: { rowIndex: number; columnIndex: number }) {
  if (columnIndex !== 7) return [1, 1]
  if (rowIndex === 0) return [form.lines.length || 1, 1]
  return [0, 0]
}

function money(value: unknown) {
  return Number(value || 0).toFixed(2)
}

function lineTotal(line: LineForm) {
  return (Number(line.qty) || 0) * (Number(line.unit_price) || 0)
}

const formTotal = computed(() => form.lines.reduce((sum, line) => sum + lineTotal(line), 0))

function resetForm() {
  editingId.value = null
  form.remake_date = today()
  form.delivery_no = ''
  form.courier_company = ''
  form.tracking_no = ''
  form.customer_id = null
  form.lines = [blankLine()]
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
  void searchProducts('')
}

function openEdit(row: any) {
  const source = rows.value.find((item) => item.id === row.id) || row
  editingId.value = source.id
  form.remake_date = source.remake_date
  form.delivery_no = source.delivery_no || ''
  form.courier_company = source.courier_company || ''
  form.tracking_no = source.tracking_no || ''
  form.customer_id = source.customer_id
  form.lines = (source.lines || []).map((line: any) => ({
    _key: lineKeySeq++,
    brand: line.brand || '',
    own_product_id: line.own_product_id ?? null,
    factory_model: line.factory_model || '',
    image_url: line.image_url || '',
    color: line.color || '',
    qty: Number(line.qty) || 1,
    unit_price: Number(line.unit_price) || 0,
    colorOptions: line.color ? [line.color] : [],
  }))
  if (!form.lines.length) form.lines = [blankLine()]
  productOptions.value = form.lines
    .filter((line) => line.factory_model)
    .map((line) => ({
      id: line.own_product_id || 0,
      product_code: line.factory_model,
      image_url: line.image_url,
    }))
  dialogVisible.value = true
}

function addLine() {
  form.lines.push(blankLine())
}

function applyProduct(line: LineForm, product: ProductOption | undefined) {
  if (!product) {
    line.own_product_id = null
    return
  }
  line.own_product_id = product.id || null
  line.image_url = product.image_url || line.image_url
  line.colorOptions = (product.colors || []).map((item) => item.name || '').filter(Boolean)
  if (!line.color && line.colorOptions.length === 1) line.color = line.colorOptions[0]
  fillPrice(line, product)
}

function fillPrice(line: LineForm, product?: ProductOption) {
  const matched = product?.brand_quotes?.find((item) => item.brand_name === line.brand)
  const price = matched?.quote_price ?? product?.quote_price
  if (price != null) line.unit_price = Number(price) || 0
}

function onFactoryModelChange(line: LineForm) {
  const product = productOptions.value.find((item) => item.product_code === line.factory_model)
  applyProduct(line, product)
}

function onBrandChange(line: LineForm) {
  const product = productOptions.value.find((item) => item.id === line.own_product_id)
  if (product) fillPrice(line, product)
}

async function searchProducts(keyword: string) {
  const res: any = await http.get('/own-products', {
    params: { keyword: keyword || undefined, active_only: true, page_size: 50 },
  })
  const items: ProductOption[] = res.data?.items || []
  const seen = new Set(items.map((item) => item.product_code))
  for (const current of productOptions.value) {
    if (current.product_code && !seen.has(current.product_code)) items.push(current)
  }
  productOptions.value = items
}

async function uploadImage(line: LineForm, options: UploadRequestOptions) {
  try {
    const data = new FormData()
    data.append('file', options.file)
    const res: any = await http.post('/sample-remakes/upload', data)
    line.image_url = res.data?.url || ''
    options.onSuccess?.(res)
  } catch (error) {
    options.onError?.(error as Error)
  }
}

async function loadCustomers() {
  const res: any = await http.get('/partners', {
    params: { role: 'customer', active_only: true, page_size: 200 },
  })
  customers.value = res.data?.items || []
}

async function load() {
  loading.value = true
  try {
    const [dateFrom, dateTo] = filters.dates || []
    const res: any = await http.get('/sample-remakes', {
      params: {
        keyword: filters.keyword || undefined,
        customer_id: filters.customer_id || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page: filters.page,
        page_size: filters.page_size,
      },
    })
    rows.value = res.data?.items || []
    total.value = Number(res.data?.total || 0)
  } finally {
    loading.value = false
  }
}

function reload() {
  filters.page = 1
  void load()
}

async function save() {
  if (!form.remake_date) {
    ElMessage.warning('请选择日期')
    return
  }
  if (!form.customer_id) {
    ElMessage.warning('请选择客户')
    return
  }
  if (form.lines.some((line) => !line.factory_model.trim())) {
    ElMessage.warning('请填写工厂型号')
    return
  }
  saving.value = true
  try {
    const payload = {
      remake_date: form.remake_date,
      delivery_no: form.delivery_no.trim() || null,
      courier_company: form.courier_company.trim() || null,
      tracking_no: form.tracking_no.trim() || null,
      customer_id: form.customer_id,
      lines: form.lines.map((line) => ({
        brand: line.brand.trim(),
        own_product_id: line.own_product_id,
        factory_model: line.factory_model.trim(),
        image_url: line.image_url || null,
        color: line.color.trim(),
        qty: Number(line.qty) || 0,
        unit_price: Number(line.unit_price) || 0,
      })),
    }
    if (editingId.value) await http.put(`/sample-remakes/${editingId.value}`, payload)
    else await http.post('/sample-remakes', payload)
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  await ElMessageBox.confirm(`确定删除送货单 ${row.delivery_no}？`, '删除', { type: 'warning' })
  await http.delete(`/sample-remakes/${row.id}`)
  ElMessage.success('已删除')
  await load()
}

function printRow(row: any, doc: 'delivery' | 'quote') {
  window.open(`${window.location.origin}/admin/sample-remakes/print/${row.id}?doc=${doc}`, '_blank')
}

onMounted(() => {
  void loadCustomers()
  void load()
})
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}
.line-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 8px;
  font-weight: 600;
}
.line-image {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.table-thumb {
  width: 42px;
  height: 42px;
  border-radius: 6px;
}
.muted {
  color: var(--el-text-color-placeholder);
}
.row-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  white-space: nowrap;
}
.row-actions :deep(.el-button) {
  margin-left: 0;
}
</style>
