<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">报废记录</h1>
        <p class="page-desc">报废登记 · 损失分摊 · 手动生成补料单</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
          <el-input
            v-model="filters.order_no"
            clearable
            placeholder="生产单号"
            style="width: 140px"
            @change="reload"
          />
          <el-select
            v-model="filters.responsible_worker_id"
            clearable
            filterable
            placeholder="责任员工"
            style="width: 150px"
            @change="reload"
          >
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <el-select
            v-model="filters.status"
            clearable
            placeholder="状态"
            style="width: 110px"
            @change="reload"
          >
            <el-option label="待确认" value="open" />
            <el-option label="已确认" value="closed" />
          </el-select>
          <el-date-picker
            v-model="filters.date_range"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 240px"
            @change="reload"
          />
          <el-checkbox v-model="filters.pending_rework" @change="reload">未完成返修</el-checkbox>
          <el-button @click="load">刷新</el-button>
          <el-button
            type="primary"
            :disabled="!selectedRows.length"
            :loading="batchSaving"
            @click="createMergedReplenishment"
          >
            生成补料单<span v-if="selectedRows.length">（{{ selectedRows.length }}）</span>
          </el-button>
          <div class="spacer" />
          <el-button type="primary" @click="openCreate">无码登记</el-button>
        </div>

        <div ref="tableHostRef">
          <el-table
            ref="defectTableRef"
            class="defects-table"
            :data="displayRows"
            row-key="_rowKey"
            border
            show-summary
            :summary-method="tableSummaries"
            :span-method="tableSpanMethod"
            :row-class-name="tableRowClassName"
            style="width: 100%"
            :max-height="tableMaxHeight"
            @selection-change="onSelectionChange"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column type="selection" width="44" align="center" :selectable="isReplenishable" :resizable="false" />
            <el-table-column
              prop="created_at"
              label="登记时间"
              :width="colWidth('created_at', 136)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column
              prop="order_no"
              label="生产单号"
              :width="colWidth('order_no', 120)"
              resizable
              show-overflow-tooltip
            />
            <el-table-column
              prop="product_code"
              label="工厂型号"
              :width="colWidth('product_code', 110)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              column-key="product_image"
              label="图片"
              :width="colWidth('product_image', 64)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <el-image
                  v-if="row.product_image_url"
                  :src="row.product_image_url"
                  :preview-src-list="[row.product_image_url]"
                  fit="cover"
                  class="defect-product-thumb"
                  preview-teleported
                />
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column
              prop="color_name"
              label="颜色"
              :width="colWidth('color_name', 72)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.color_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="brand_name"
              label="品牌"
              :width="colWidth('brand_name', 80)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.brand_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              v-for="size in listSizeHeaders"
              :key="`size-${size}`"
              :label="size"
              align="center"
            >
              <el-table-column
                :column-key="`size_${size}_left`"
                label="左"
                :width="colWidth(`size_${size}_left`, 44)"
                align="center"
                resizable
              >
                <template #default="{ row }">
                  {{ sizeSideQty(row, size, 'left') }}
                </template>
              </el-table-column>
              <el-table-column
                :column-key="`size_${size}_right`"
                label="右"
                :width="colWidth(`size_${size}_right`, 44)"
                align="center"
                resizable
              >
                <template #default="{ row }">
                  {{ sizeSideQty(row, size, 'right') }}
                </template>
              </el-table-column>
            </el-table-column>
            <el-table-column
              prop="qty"
              label="数量"
              :width="colWidth('qty', 56)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ row.qty ?? '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="found_process_name"
              label="发现工序"
              :width="colWidth('found_process_name', 80)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ row.found_process_name || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="loss_amount"
              label="损失"
              :width="colWidth('loss_amount', 80)"
              align="right"
              resizable
            >
              <template #default="{ row }">{{ formatMoney(row.loss_amount) }}</template>
            </el-table-column>
            <el-table-column
              column-key="company_loss"
              label="公司承担"
              :width="colWidth('company_loss', 100)"
              align="right"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">{{ companyLossText(row) }}</template>
            </el-table-column>
            <el-table-column
              column-key="responsibility_workers"
              label="责任人"
              :width="colWidth('responsibility_workers', 90)"
              resizable
              show-overflow-tooltip
            >
              <template #default="{ row }">
                {{ row._responsibility.name }}
              </template>
            </el-table-column>
            <el-table-column
              column-key="responsibility_loss"
              label="分担损失"
              :width="colWidth('responsibility_loss', 90)"
              align="right"
              resizable
            >
              <template #default="{ row }">
                {{ row._responsibility.amount }}
              </template>
            </el-table-column>
            <el-table-column
              prop="status"
              label="状态"
              :width="colWidth('status', 72)"
              align="center"
              resizable
            >
              <template #default="{ row }">{{ row.status === 'closed' ? '已确认' : '待确认' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="72" align="center" fixed="right" :resizable="false">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="admin-pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            background
            layout="total, sizes, prev, pager, next"
            :total="total"
            :page-sizes="[10, 20, 50]"
            @current-change="load"
            @size-change="
              () => {
                page = 1
                load()
              }
            "
          />
        </div>
    </div>

    <el-dialog v-model="createVisible" title="无码登记报废" width="640px">
      <el-form label-width="100px">
        <el-form-item label="生产单号" required>
          <el-input v-model="form.order_no" placeholder="如 XE-20260821-0009" @change="onOrderNoChange" />
        </el-form-item>
        <el-form-item v-if="createSizeLines.length" label="码数明细" required>
          <el-table
            :data="createMatrixData"
            border
            size="small"
            class="defect-size-matrix-table"
            style="width: 100%"
          >
            <el-table-column
              v-for="line in createSizeLines"
              :key="line.key"
              :label="String(createSizeLabel(line))"
              align="center"
            >
              <el-table-column label="左" width="72" align="center">
                <template #default>
                  <el-input-number
                    v-model="line.left_qty"
                    :min="0"
                    :precision="0"
                    :controls="false"
                    class="defect-size-matrix-input"
                  />
                </template>
              </el-table-column>
              <el-table-column label="右" width="72" align="center">
                <template #default>
                  <el-input-number
                    v-model="line.right_qty"
                    :min="0"
                    :precision="0"
                    :controls="false"
                    class="defect-size-matrix-input"
                  />
                </template>
              </el-table-column>
            </el-table-column>
          </el-table>
          <div class="muted" style="margin-top: 6px">按码数填左右脚数量；只提交有数量的码。</div>
        </el-form-item>
        <el-form-item label="框码" :required="createBundlesActive">
          <el-select
            v-model="form.trace_unit_id"
            clearable
            filterable
            style="width: 100%"
            :placeholder="createBundlesActive ? '本单有进行中框码，必须选择' : '可选'"
            @change="onCreateBundleChange"
          >
            <el-option
              v-for="u in createBundles"
              :key="u.id"
              :label="`${u.code} · ${u.color_name || ''} ${u.size_value || ''} ×${u.qty} (${u.status})`"
              :value="u.id"
            />
          </el-select>
          <div v-if="createBundlesActive" class="muted" style="margin-top: 4px; color: #c45656">
            本单有进行中框码，必须选择框码
          </div>
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.defect_type" style="width: 100%">
            <el-option v-for="t in defectTypes" :key="t.code" :label="t.name" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任工序">
          <el-select
            v-model="form.responsible_process_id"
            clearable
            filterable
            style="width: 100%"
            @change="onCreateProcessChange"
          >
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createEvent">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑报废记录" width="760px">
      <el-form v-loading="editLoading" label-width="88px">
        <el-form-item label="生产单号">
          <el-input :model-value="editForm.order_no" disabled />
        </el-form-item>
        <el-form-item label="图片">
          <div class="edit-photo-list">
            <div v-for="(url, index) in editForm.photo_urls" :key="url" class="edit-photo-item">
              <el-image :src="url" :preview-src-list="editForm.photo_urls" fit="cover" />
              <button type="button" @click="editForm.photo_urls.splice(index, 1)">×</button>
            </div>
            <label class="edit-photo-add">
              <input type="file" accept="image/*" multiple @change="uploadEditPhotos" />
              <span>{{ editPhotoUploading ? '上传中…' : '+ 添加' }}</span>
            </label>
          </div>
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="editForm.brand_name" maxlength="100" />
        </el-form-item>
        <el-form-item label="发现工序" required>
          <el-select v-model="editForm.found_process_id" filterable style="width: 100%">
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="码数数量" required>
          <el-table :data="editForm.lines" border size="small" style="width: 100%">
            <el-table-column label="码数" min-width="120">
              <template #default="{ row }">
                <el-select v-model="row.size_id" filterable style="width: 100%">
                  <el-option v-for="size in editSizeOptions" :key="size.size_id" :label="size.size_value" :value="size.size_id" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="左脚" width="110" align="center">
              <template #default="{ row }"><el-input-number v-model="row.left_qty" :min="0" :precision="0" :controls="false" /></template>
            </el-table-column>
            <el-table-column label="右脚" width="110" align="center">
              <template #default="{ row }"><el-input-number v-model="row.right_qty" :min="0" :precision="0" :controls="false" /></template>
            </el-table-column>
            <el-table-column label="数量" width="70" align="center">
              <template #default="{ row }">{{ Number(row.left_qty || 0) + Number(row.right_qty || 0) }}</template>
            </el-table-column>
            <el-table-column label="损失" width="130" align="center">
              <template #default="{ row }"><el-input-number v-model="row.loss_amount" :min="0" :precision="2" :controls="false" /></template>
            </el-table-column>
          </el-table>
          <div class="edit-loss-total">总数量 {{ editTotalQty }}　总损失 {{ formatMoney(editTotalLoss) }}</div>
        </el-form-item>
        <el-form-item label="公司承担">
          <el-input-number v-model="editForm.company_amount" :min="0" :precision="2" :controls="false" />
        </el-form-item>
        <el-form-item label="责任人">
          <div class="edit-responsibilities">
            <div v-for="(item, index) in editForm.responsibilities" :key="item.key" class="edit-responsibility-row">
              <el-select v-model="item.worker_id" filterable placeholder="选择人员">
                <el-option v-for="worker in workers" :key="worker.id" :label="worker.name" :value="worker.id" />
              </el-select>
              <el-input-number v-model="item.amount" :min="0" :precision="2" :controls="false" />
              <el-button link type="danger" @click="editForm.responsibilities.splice(index, 1)">删除</el-button>
            </div>
            <el-button @click="addEditResponsibility">+ 选择责任人</el-button>
            <span :class="['edit-allocation-total', { invalid: !editAllocationBalanced }]">分摊合计 {{ formatMoney(editAllocationTotal) }}</span>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" :disabled="editLoading || editPhotoUploading" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const defectTableRef = ref<{ clearSelection?: () => void; doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend } = useTableColWidths('defects-list', defectTableRef, {
  flexKey: 'responsibility_workers',
  flexDefaultMin: 120,
  fitToContainer: true,
})

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const workers = ref<any[]>([])
const processes = ref<any[]>([])
const defectTypes = ref<{ code: string; name: string }[]>([])
const emptySummary = () => ({ total_qty: 0, total_loss_amount: 0, company_loss_amount: 0, employee_loss_amount: 0 })
const summary = ref(emptySummary())
const filters = reactive({
  order_no: '',
  responsible_worker_id: null as number | null,
  status: '',
  pending_rework: false,
  date_range: [] as string[],
})
const createVisible = ref(false)
const saving = ref(false)
const editVisible = ref(false)
const editSaving = ref(false)
const editLoading = ref(false)
const editPhotoUploading = ref(false)
const batchSaving = ref(false)
const selectedRows = ref<any[]>([])
const form = reactive({
  order_no: '',
  trace_unit_id: null as number | null,
  responsible_process_id: null as number | null,
  responsible_worker_id: null as number | null,
  note: '',
})
const editForm = reactive({
  id: 0,
  order_no: '',
  header_id: null as number | null,
  brand_name: '',
  defect_type: '',
  found_process_id: null as number | null,
  photo_urls: [] as string[],
  lines: [] as Array<{ id: number; size_id: number | null; size_value: string; left_qty: number; right_qty: number; loss_amount: number }>,
  company_amount: 0,
  responsibilities: [] as Array<{ key: number; worker_id: number | null; amount: number }>,
  note: '',
})
const editSizeOptions = ref<any[]>([])
let editResponsibilityKey = 0
const editTotalQty = computed(() => editForm.lines.reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0))
const editTotalLoss = computed(() => editForm.lines.reduce((sum, line) => sum + Number(line.loss_amount || 0), 0))
const editAllocationTotal = computed(() => Number(editForm.company_amount || 0) + editForm.responsibilities.reduce((sum, item) => sum + Number(item.amount || 0), 0))
const editAllocationBalanced = computed(() => Math.abs(editAllocationTotal.value - editTotalLoss.value) < 0.01)
type CreateSizeLine = { key: number; size_id: number | null; left_qty: number; right_qty: number }
let createSizeLineKey = 0
const createSizeLines = ref<CreateSizeLine[]>([])
const createBundles = ref<any[]>([])
const createSizes = ref<any[]>([])
const createOrderId = ref<number | null>(null)
const suggestHint = ref('')
const suggestCandidates = ref<any[]>([])
const createMatrixData = computed(() => (createSizeLines.value.length ? [{}] : []))

const createBundlesActive = computed(() =>
  createBundles.value.some((u) => u.status === 'open' || u.status === 'in_process'),
)

/** 当前列表出现的码数，用作两行表头第一行 */
const listSizeHeaders = computed(() => {
  const set = new Set<string>()
  for (const row of rows.value) {
    if (row.size_value == null || row.size_value === '') continue
    set.add(String(row.size_value))
  }
  return [...set].sort((a, b) => {
    const na = Number(a)
    const nb = Number(b)
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb
    return a.localeCompare(b, 'zh')
  })
})

const displayRows = computed(() => rows.value.flatMap((row, groupIndex) => {
  const responsibilities = responsibilityRows(row)
  return responsibilities.map((responsibility, index) => ({
    ...row,
    _rowKey: `${row.id}-${index}`,
    _responsibility: responsibility,
    _isFirst: index === 0,
    _span: responsibilities.length,
    _groupIndex: groupIndex,
  }))
}))

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 16).replace('T', ' ')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatMoney(value: number | string | null | undefined) {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '—'
  return `¥${n.toFixed(2)}`
}

function sizeSideQty(row: any, size: string, side: 'left' | 'right') {
  if (String(row.size_value ?? '') !== size) return ''
  return Number(side === 'left' ? row.left_qty || 0 : row.right_qty || 0)
}

function companyLossText(row: any) {
  const percent = Number(row.company_share_percent ?? 100)
  const amount =
    row.company_loss_amount != null
      ? Number(row.company_loss_amount)
      : (Number(row.loss_amount || 0) * percent) / 100
  if (!Number.isFinite(amount)) return '—'
  return formatMoney(amount)
}

function tableSummaries({ columns }: { columns: any[] }) {
  return columns.map((column, index) => {
    const key = column.property || column.columnKey
    if (index === 0) return '汇总'
    if (key === 'qty') return summary.value.total_qty
    if (key === 'loss_amount') return formatMoney(summary.value.total_loss_amount)
    if (key === 'company_loss') return formatMoney(summary.value.company_loss_amount)
    if (key === 'responsibility_loss') return formatMoney(summary.value.employee_loss_amount)
    return ''
  })
}

function tableSpanMethod({ row, column }: { row: any; column: any }) {
  const key = column.property || column.columnKey
  if (key === 'responsibility_workers' || key === 'responsibility_loss') return [1, 1]
  return row._isFirst ? [row._span, 1] : [0, 0]
}

function tableRowClassName({ row }: { row: any }) {
  return row._groupIndex % 2 === 1 ? 'defect-group-stripe' : ''
}

function responsibilityRows(row: any) {
  const items = (row.responsibilities || []).map((item: any) => ({
    name: item.worker_name || '员工',
    amount: formatMoney(item.deduction_amount),
  }))
  if (items.length) return items
  if (row.responsible_worker_name) {
    const amount = Number(row.employee_loss_amount ?? row.loss_amount ?? 0)
    return [{ name: row.responsible_worker_name, amount: formatMoney(amount) }]
  }
  return [{ name: '—', amount: '—' }]
}

function reload() {
  page.value = 1
  void load()
}

async function openEdit(row: any) {
  editForm.id = Number(row.id)
  editVisible.value = true
  editLoading.value = true
  try {
    const res: any = await http.get(`/defect-events/${row.id}`)
    const detail = res.data || row
    const items = detail.registration_items?.length ? detail.registration_items : [detail]
    editForm.order_no = detail.order_no || ''
    editForm.header_id = detail.header_id ? Number(detail.header_id) : null
    editForm.brand_name = detail.brand_name || ''
    editForm.found_process_id = detail.found_process_id ? Number(detail.found_process_id) : null
    editForm.photo_urls = [...(detail.photo_urls || [])]
    editForm.note = detail.note || ''
    editForm.lines = items.map((item: any) => ({
      id: Number(item.id),
      size_id: item.size_id ? Number(item.size_id) : null,
      size_value: item.size_value || '',
      left_qty: Number(item.left_qty || 0),
      right_qty: Number(item.right_qty || 0),
      loss_amount: Number(item.loss_amount || 0),
    }))
    const totalLoss = editForm.lines.reduce((sum, line) => sum + line.loss_amount, 0)
    editForm.company_amount = Number((totalLoss * Number(detail.company_share_percent ?? 100) / 100).toFixed(2))
    editForm.responsibilities = (detail.responsibilities || []).map((item: any) => ({
      key: ++editResponsibilityKey,
      worker_id: Number(item.worker_id),
      amount: Number((totalLoss * Number(item.share_percent || 0) / 100).toFixed(2)),
    }))
    editSizeOptions.value = editForm.lines.map(line => ({ size_id: line.size_id, size_value: line.size_value }))
    if (editForm.header_id) {
      const headerRes: any = await http.get(`/executions/headers/${editForm.header_id}`)
      editSizeOptions.value = headerRes.data?.size_lines || editSizeOptions.value
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载报废记录失败')
    editVisible.value = false
  } finally { editLoading.value = false }
}

function addEditResponsibility() {
  editForm.responsibilities.push({ key: ++editResponsibilityKey, worker_id: null, amount: 0 })
}

async function uploadEditPhotos(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files || [])]
  if (!files.length) return
  editPhotoUploading.value = true
  try {
    for (const file of files) {
      const data = new FormData()
      data.append('file', file)
      const res: any = await http.post('/defect-events/upload-photo', data)
      if (res.data?.url) editForm.photo_urls.push(res.data.url)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '图片上传失败')
  } finally {
    editPhotoUploading.value = false
    input.value = ''
  }
}

function editAllocationPercentages() {
  const total = Math.round(editTotalLoss.value * 100)
  if (total <= 0) return { company: 100, workers: [] as Array<{ worker_id: number; share_percent: number }> }
  const entries = [
    { type: 'company', amount: Math.round(Number(editForm.company_amount || 0) * 100), worker_id: 0 },
    ...editForm.responsibilities.map(item => ({ type: 'worker', amount: Math.round(Number(item.amount || 0) * 100), worker_id: Number(item.worker_id || 0) })),
  ]
  const raw = entries.map(entry => ({ ...entry, exact: entry.amount * 100 / total, share: Math.floor(entry.amount * 100 / total) }))
  let remaining = 100 - raw.reduce((sum, entry) => sum + entry.share, 0)
  raw.sort((a, b) => (b.exact - b.share) - (a.exact - a.share))
  for (let index = 0; index < remaining; index += 1) raw[index % raw.length].share += 1
  return {
    company: raw.find(entry => entry.type === 'company')?.share || 0,
    workers: raw.filter(entry => entry.type === 'worker' && entry.worker_id).map(entry => ({ worker_id: entry.worker_id, share_percent: entry.share })),
  }
}

async function saveEdit() {
  if (!editForm.found_process_id) {
    ElMessage.warning('请选择发现工序')
    return
  }
  if (!editForm.lines.length || editForm.lines.some(line => !line.size_id || Number(line.left_qty || 0) + Number(line.right_qty || 0) <= 0)) {
    ElMessage.warning('每个码数的左右脚合计必须大于 0')
    return
  }
  if (new Set(editForm.lines.map(line => line.size_id)).size !== editForm.lines.length) {
    ElMessage.warning('同一码数不能重复')
    return
  }
  if (!editAllocationBalanced.value) {
    ElMessage.warning('公司与责任人承担金额合计必须等于总损失')
    return
  }
  if (editForm.responsibilities.some(item => !item.worker_id)) {
    ElMessage.warning('请选择责任人')
    return
  }
  editSaving.value = true
  try {
    const allocation = editAllocationPercentages()
    await Promise.all(editForm.lines.map(line => http.patch(`/defect-events/${line.id}`, {
      brand_name: editForm.brand_name,
      found_process_id: editForm.found_process_id,
      size_id: line.size_id,
      left_qty: Number(line.left_qty || 0),
      right_qty: Number(line.right_qty || 0),
      qty: Number(line.left_qty || 0) + Number(line.right_qty || 0),
      photo_urls: editForm.photo_urls,
      loss_amount: Number(line.loss_amount || 0),
      company_share_percent: allocation.company,
      responsibilities: allocation.workers,
      note: editForm.note,
    })))
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    editSaving.value = false
  }
}

function onSelectionChange(selection: any[]) {
  selectedRows.value = [...new Map(selection.map((row) => [Number(row.id), row])).values()]
}

function isReplenishable(row: any) {
  return row._isFirst !== false && !row.material_doc_no
}

async function createMergedReplenishment() {
  if (!selectedRows.value.length) return
  const headerIds = new Set(selectedRows.value.map((row) => Number(row.header_id || 0)))
  if (headerIds.has(0)) {
    ElMessage.warning('所选不良存在未关联生产单的记录')
    return
  }
  if (headerIds.size !== 1) {
    ElMessage.warning('只能合并同一生产单的不良记录')
    return
  }
  const invalid = selectedRows.value.find((row) => !row.size_id || !row.found_process_id)
  if (invalid) {
    ElMessage.warning(`不良 #${invalid.id} 缺少码数或发现工序，无法计算补料`)
    return
  }
  await ElMessageBox.confirm(
    `将所选 ${selectedRows.value.length} 条报废记录生成一张补料单，确认继续？不会自动生成，仅本次点击创建。`,
    '生成补料单',
    { type: 'warning' },
  )
  batchSaving.value = true
  try {
    const res: any = await http.post('/defect-events/material-replenishment', {
      defect_ids: selectedRows.value.map((row) => Number(row.id)),
    })
    ElMessage.success(`补料单 ${res.data?.doc_no || ''} 已生成，可在「补料单」菜单确认过账`)
    defectTableRef.value?.clearSelection?.()
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成补料单失败')
  } finally {
    batchSaving.value = false
  }
}

async function load() {
  const res: any = await http.get('/defect-events', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      order_no: filters.order_no || undefined,
      responsible_worker_id: filters.responsible_worker_id || undefined,
      status: filters.status || undefined,
      pending_rework: filters.pending_rework || undefined,
      date_from: filters.date_range?.[0] || undefined,
      date_to: filters.date_range?.[1] || undefined,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total || 0
  summary.value = { ...emptySummary(), ...(res.data?.summary || {}) }
}

async function loadMeta() {
  const [wRes, pRes, tRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/processes'),
    http.get('/defect-types'),
  ])
  workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
  processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
  defectTypes.value = tRes.data?.items || []
}

async function loadBundlesForOrderNo(orderNo: string) {
  createBundles.value = []
  createSizes.value = []
  createOrderId.value = null
  if (!orderNo.trim()) return
  try {
    const hRes: any = await http.get('/executions', {
      params: { q: orderNo.trim(), page_size: 20 },
    })
    const header = (hRes.data?.items || []).find((x: any) => x.header_no === orderNo.trim())
    if (header?.id) {
      createOrderId.value = header.id
      const [uRes, detailRes]: any[] = await Promise.all([
        http.get(`/executions/headers/${header.id}/trace-units`),
        http.get(`/executions/headers/${header.id}`),
      ])
      createBundles.value = uRes.data?.items || []
      createSizes.value = detailRes.data?.size_lines || []
      resetCreateSizeLines()
      return
    }
    // 兼容旧订单号不良登记。
    const oRes: any = await http.get('/orders', {
      params: { order_no: orderNo.trim(), page_size: 5 },
    })
    const order = (oRes.data?.items || []).find((x: any) => x.order_no === orderNo.trim())
    if (!order) return
    createOrderId.value = order.id
    const uRes: any = await http.get(`/orders/${order.id}/trace-units`)
    createBundles.value = uRes.data?.items || []
  } catch {
    createBundles.value = []
  }
}

function createSizeLine(sizeId: number | null = null): CreateSizeLine {
  createSizeLineKey += 1
  return { key: createSizeLineKey, size_id: sizeId, left_qty: 0, right_qty: 0 }
}

function resetCreateSizeLines() {
  const defaults = createSizes.value
  createSizeLines.value = defaults.length
    ? defaults.map((size: any) => createSizeLine(Number(size.size_id)))
    : []
}

function createSizeLabel(line: CreateSizeLine) {
  const size = createSizes.value.find((item: any) => Number(item.size_id) === Number(line.size_id))
  return size?.size_value != null && size.size_value !== ''
    ? String(size.size_value)
    : line.size_id
      ? String(line.size_id)
      : '—'
}

function openCreate() {
  form.order_no = filters.order_no || ''
  form.trace_unit_id = null
  form.defect_type = defectTypes.value[0]?.code || ''
  form.responsible_process_id = null
  form.responsible_worker_id = null
  form.note = ''
  suggestHint.value = ''
  suggestCandidates.value = []
  createVisible.value = true
  void loadBundlesForOrderNo(form.order_no)
}

function onOrderNoChange() {
  form.trace_unit_id = null
  void loadBundlesForOrderNo(form.order_no)
}

async function onCreateBundleChange() {
  const unit = createBundles.value.find((item: any) => item.id === form.trace_unit_id)
  if (unit?.size_id) {
    const line = createSizeLines.value.find((row) => Number(row.size_id) === Number(unit.size_id))
    if (!line && createSizeLines.value[0]) createSizeLines.value[0].size_id = Number(unit.size_id)
  }
  await refreshSuggest()
}

async function onCreateProcessChange() {
  await refreshSuggest()
}

async function refreshSuggest() {
  suggestHint.value = ''
  suggestCandidates.value = []
  if (!form.trace_unit_id || !form.responsible_process_id) return
  try {
    const res: any = await http.get(`/trace-units/${form.trace_unit_id}/suggest-responsible`, {
      params: { process_id: form.responsible_process_id },
    })
    const d = res.data || {}
    suggestHint.value = [d.basis, d.confidence ? `置信 ${d.confidence}` : '']
      .filter(Boolean)
      .join(' · ')
    suggestCandidates.value = d.candidates || []
    if (d.worker_id && !form.responsible_worker_id) {
      form.responsible_worker_id = d.worker_id
    }
  } catch {
    /* ignore */
  }
}

async function createEvent() {
  if (!form.order_no.trim() || !form.defect_type) {
    ElMessage.warning('请填写生产单和类型')
    return
  }
  if (createBundlesActive.value && !form.trace_unit_id) {
    ElMessage.warning('本单有进行中框码，请选择框码')
    return
  }
  const sizeLines = createSizeLines.value
    .filter((line) => line.size_id && (Number(line.left_qty || 0) + Number(line.right_qty || 0)) > 0)
    .map((line) => ({
      size_id: Number(line.size_id),
      left_qty: Number(line.left_qty || 0),
      right_qty: Number(line.right_qty || 0),
    }))
  if (!sizeLines.length) {
    ElMessage.warning('请至少填写一个码数的左右脚数量')
    return
  }
  if (sizeLines.some((line) => !line.size_id)) {
    ElMessage.warning('报废登记必须选择码数')
    return
  }
  saving.value = true
  try {
    await http.post('/defect-events', {
      order_no: form.order_no.trim(),
      trace_unit_id: form.trace_unit_id || null,
      defect_type: form.defect_type,
      size_lines: sizeLines,
      responsible_process_id: form.responsible_process_id,
      responsible_worker_id: form.responsible_worker_id,
      disposition: 'scrap',
      note: form.note || null,
      auto_suggest_worker: false,
    })
    ElMessage.success('已登记')
    createVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '登记失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadMeta()
  await load()
  measureTableHeight()
})
</script>

<style scoped>
.spacer {
  flex: 1;
}
.suggest-cands {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.responsibility-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.edit-photo-list, .edit-responsibilities {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.edit-photo-item { position: relative; width: 64px; height: 64px; }
.edit-photo-item :deep(.el-image) { width: 64px; height: 64px; border-radius: 6px; }
.edit-photo-item button { position: absolute; top: -7px; right: -7px; width: 20px; height: 20px; padding: 0; border: 0; border-radius: 50%; background: #d33; color: #fff; cursor: pointer; }
.edit-photo-add { display: grid; width: 64px; height: 64px; place-items: center; border: 1px dashed var(--el-border-color); border-radius: 6px; color: var(--el-color-primary); cursor: pointer; }
.edit-photo-add input { display: none; }
.edit-loss-total { margin-top: 8px; color: var(--el-text-color-secondary); text-align: right; }
.edit-responsibilities { width: 100%; align-items: flex-start; flex-direction: column; }
.edit-responsibility-row { display: grid; width: 100%; grid-template-columns: 1fr 150px 48px; gap: 8px; }
.edit-responsibility-row :deep(.el-input-number), .edit-form :deep(.el-input-number) { width: 100%; }
.edit-allocation-total { color: var(--el-text-color-secondary); }
.edit-allocation-total.invalid { color: var(--el-color-danger); }
.edit-form {
  width: 100%;
}
.defects-table :deep(.el-table__body-wrapper) {
  overflow-x: hidden;
}
.defects-table :deep(.defect-group-stripe > td.el-table__cell) {
  background: var(--el-fill-color-lighter);
}
.defects-table :deep(.el-table__header-wrapper th.el-table__cell) {
  height: 30px;
  padding: 2px 0;
}
.defects-table :deep(.el-table__header-wrapper th.el-table__cell > .cell) {
  line-height: 20px;
}
.defects-table :deep(.el-scrollbar__bar.is-horizontal) {
  display: none;
}
.defect-product-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  display: block;
  margin: 0 auto;
}
.defect-size-matrix-table {
  width: 100%;
}
.defect-size-matrix-input {
  width: 56px;
}
.defect-size-matrix-input :deep(.el-input__wrapper) {
  padding-left: 4px;
  padding-right: 4px;
}
.defect-size-matrix-input :deep(.el-input__inner) {
  text-align: center;
}
</style>
