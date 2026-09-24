<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">日常开支</h1>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="产生开始"
          end-placeholder="产生结束"
          clearable
          @change="load"
        />
        <el-select
          v-model="filterDepartmentId"
          clearable
          filterable
          placeholder="报销部门"
          style="width: 140px"
          @change="onFilterDepartmentChange"
        >
          <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select
          v-model="filterEmployeeId"
          clearable
          filterable
          placeholder="报销人"
          style="width: 140px"
          @change="load"
        >
          <el-option
            v-for="e in filterEmployeeOptions"
            :key="e.id"
            :label="e.name"
            :value="e.id"
          />
        </el-select>
        <el-select
          v-model="category"
          clearable
          filterable
          allow-create
          default-first-option
          placeholder="费用类型"
          style="width: 150px"
          @focus="loadCategorySuggestions"
          @change="load"
        >
          <el-option v-for="c in categorySuggestions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="status" clearable placeholder="状态" style="width: 110px" @change="load">
          <el-option label="已入账" value="posted" />
          <el-option label="已作废" value="void" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button v-permission="'btn.daily_expenses.write'" type="primary" @click="openCreate">
          登记开支
        </el-button>
      </div>
      <div class="muted" style="margin: -6px 0 10px; font-size: 12px">
        共 {{ summary.count || 0 }} 笔 · 已入账合计 {{ formatMoney(summary.posted_total) }}
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="displayRows"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          :span-method="spanMethod"
          row-key="_key"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            column-key="registered_at"
            label="登记日期"
            :width="colWidth('registered_at', 120)"
            resizable
          >
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column
            prop="department_name"
            label="报销部门"
            :width="colWidth('department_name', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="employee_name"
            label="报销人"
            :width="colWidth('employee_name', 100)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="reason"
            label="报销事由"
            :width="colWidth('reason', 160)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            column-key="category_label"
            label="费用类型"
            :width="colWidth('category_label', 110)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.line_category_label || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="category_image"
            label="附图"
            :width="colWidth('category_image', 80)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.line_category_image_urls?.length"
                :src="row.line_category_image_urls[0]"
                :preview-src-list="row.line_category_image_urls"
                preview-teleported
                fit="cover"
                class="expense-table-thumb"
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="occurred_on"
            label="产生日期"
            :width="colWidth('occurred_on', 120)"
            resizable
          >
            <template #default="{ row }">{{ formatDate(row.line_occurred_on) }}</template>
          </el-table-column>
          <el-table-column
            column-key="description"
            label="费用说明"
            :width="colWidth('description', 160)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.line_description || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="line_amount"
            label="费用金额"
            :width="colWidth('line_amount', 110)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.line_amount) }}</template>
          </el-table-column>
          <el-table-column
            column-key="invoice"
            label="发票"
            :width="colWidth('invoice', 80)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.line_invoice_urls?.length"
                :src="row.line_invoice_urls[0]"
                :preview-src-list="row.line_invoice_urls"
                preview-teleported
                fit="cover"
                class="expense-table-thumb"
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="receipt"
            label="收据"
            :width="colWidth('receipt', 80)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.line_receipt_urls?.length"
                :src="row.line_receipt_urls[0]"
                :preview-src-list="row.line_receipt_urls"
                preview-teleported
                fit="cover"
                class="expense-table-thumb"
              />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="row.status === 'posted' ? 'success' : 'info'" size="small">
                {{ row.status === 'posted' ? '已入账' : '已作废' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="created_by_name"
            label="登记人"
            :width="colWidth('created_by_name', 100)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column column-key="actions" label="操作" width="140" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button link type="primary" @click="openDetail(row)">详情</el-button>
              <el-button
                v-if="row.status === 'posted' && canWrite"
                link
                type="danger"
                @click="voidExpense(row)"
              >
                作废
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog
      v-model="dialog"
      :title="detailMode ? '开支详情' : '登记日常开支'"
      width="640px"
      destroy-on-close
      class="expense-dialog"
    >
      <el-form label-width="96px" :disabled="detailMode">
        <el-form-item label="报销部门" required>
          <el-select
            v-model="form.department_id"
            filterable
            clearable
            placeholder="请选择"
            style="width: 100%"
            @change="onFormDepartmentChange"
          >
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="报销人" required>
          <el-select
            v-model="form.employee_id"
            filterable
            clearable
            placeholder="请选择"
            style="width: 100%"
            @change="onFormEmployeeChange"
          >
            <el-option
              v-for="e in formEmployeeOptions"
              :key="e.id"
              :label="e.name"
              :value="e.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="报销事由">
          <el-input v-model="form.reason" maxlength="255" placeholder="请填写" />
        </el-form-item>
        <el-form-item label="付款账户">
          <el-select v-model="form.fund_account" clearable placeholder="可选" style="width: 100%">
            <el-option label="银行" value="bank" />
            <el-option label="现金" value="cash" />
            <el-option label="微信" value="wechat" />
            <el-option label="支付宝" value="alipay" />
            <el-option label="其它" value="other" />
          </el-select>
        </el-form-item>

        <div
          v-for="(line, index) in form.lines"
          :key="line._key"
          class="expense-line-card"
        >
          <div class="expense-line-head">
            <strong>报销明细</strong>
            <div v-if="!detailMode" class="expense-line-actions">
              <el-button link type="primary" @click="copyLine(index)">复制</el-button>
              <el-button
                v-if="form.lines.length > 1"
                link
                type="danger"
                @click="removeLine(index)"
              >
                删除
              </el-button>
            </div>
          </div>
          <el-form-item label="费用类型" required>
            <el-select
              v-model="line.category"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="可输入或选择历史"
              style="width: 100%"
              :disabled="detailMode"
              @focus="loadCategorySuggestions"
            >
              <el-option v-for="c in categorySuggestions" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item label="附图">
            <div class="expense-attach-list">
              <div
                v-for="(url, imgIdx) in line.category_image_urls"
                :key="url"
                class="expense-attach-item"
              >
                <el-image
                  :src="url"
                  :preview-src-list="line.category_image_urls"
                  :initial-index="imgIdx"
                  preview-teleported
                  fit="cover"
                />
                <button
                  v-if="!detailMode"
                  type="button"
                  class="attach-remove"
                  title="移除"
                  @click="line.category_image_urls.splice(imgIdx, 1)"
                >
                  ×
                </button>
              </div>
              <el-upload
                v-if="!detailMode && line.category_image_urls.length < 9"
                multiple
                :show-file-list="false"
                :http-request="(opts) => uploadLinePhoto(line, 'category', opts)"
                accept="image/jpeg,image/png,image/gif,image/webp"
              >
                <el-button>{{ uploading ? '上传中…' : '添加附图' }}</el-button>
              </el-upload>
            </div>
          </el-form-item>
          <el-form-item label="产生日期" required>
            <el-date-picker
              v-model="line.occurred_on"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="请选择"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="费用金额" required>
            <el-input
              v-model="line.amount"
              placeholder="请填写"
              inputmode="decimal"
              @input="onAmountInput(line)"
            />
          </el-form-item>
          <el-form-item label="费用说明">
            <el-input
              v-model="line.description"
              type="textarea"
              :rows="3"
              maxlength="500"
              placeholder="请填写"
            />
          </el-form-item>
          <el-form-item label="发票">
            <div class="expense-attach-list">
              <div
                v-for="(url, imgIdx) in line.invoice_urls"
                :key="url"
                class="expense-attach-item"
              >
                <el-image
                  :src="url"
                  :preview-src-list="line.invoice_urls"
                  :initial-index="imgIdx"
                  preview-teleported
                  fit="cover"
                />
                <button
                  v-if="!detailMode"
                  type="button"
                  class="attach-remove"
                  title="移除"
                  @click="line.invoice_urls.splice(imgIdx, 1)"
                >
                  ×
                </button>
              </div>
              <el-upload
                v-if="!detailMode && line.invoice_urls.length < 9"
                multiple
                :show-file-list="false"
                :http-request="(opts) => uploadLinePhoto(line, 'invoice', opts)"
                accept="image/jpeg,image/png,image/gif,image/webp"
              >
                <el-button>{{ uploading ? '上传中…' : '添加发票' }}</el-button>
              </el-upload>
            </div>
          </el-form-item>
          <el-form-item label="收据">
            <div class="expense-attach-list">
              <div
                v-for="(url, imgIdx) in line.receipt_urls"
                :key="url"
                class="expense-attach-item"
              >
                <el-image
                  :src="url"
                  :preview-src-list="line.receipt_urls"
                  :initial-index="imgIdx"
                  preview-teleported
                  fit="cover"
                />
                <button
                  v-if="!detailMode"
                  type="button"
                  class="attach-remove"
                  title="移除"
                  @click="line.receipt_urls.splice(imgIdx, 1)"
                >
                  ×
                </button>
              </div>
              <el-upload
                v-if="!detailMode && line.receipt_urls.length < 9"
                multiple
                :show-file-list="false"
                :http-request="(opts) => uploadLinePhoto(line, 'receipt', opts)"
                accept="image/jpeg,image/png,image/gif,image/webp"
              >
                <el-button>{{ uploading ? '上传中…' : '添加收据' }}</el-button>
              </el-upload>
            </div>
          </el-form-item>
        </div>

        <el-button
          v-if="!detailMode"
          class="add-line-btn"
          type="primary"
          plain
          @click="addLine"
        >
          + 添加明细
        </el-button>

        <div class="expense-total">
          总费用金额 {{ formatYuan(totalAmount) }}（{{ amountCn(totalAmount) }}）
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ detailMode ? '关闭' : '取消' }}</el-button>
        <el-button v-if="!detailMode" type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const auth = useAuthStore()
const canWrite = computed(() => auth.hasPermission('btn.daily_expenses.write') || auth.isAdmin())

const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('daily-expenses-list', tableRef, {
  flexKey: 'description',
  flexDefaultMin: 160,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const now = new Date()
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`

const dateRange = ref<[string, string] | null>(null)
const filterDepartmentId = ref<number | null>(null)
const filterEmployeeId = ref<number | null>(null)
const category = ref<string | null>(null)
const status = ref<string | null>('posted')
const departments = ref<{ id: number; name: string }[]>([])
const employees = ref<{ id: number; name: string; department_id?: number | null }[]>([])
const categorySuggestions = ref<string[]>([])
const rows = ref<any[]>([])
const summary = ref<any>({})
const dialog = ref(false)
const detailMode = ref(false)
const saving = ref(false)
const uploading = ref(false)
let uploadPending = 0
let lineKeySeq = 1

/** 单头字段列索引：合并 rowspan；明细列不合并 */
const MERGE_COL_INDEXES = new Set([0, 1, 2, 3, 11, 12, 13])

const filterEmployeeOptions = computed(() => {
  if (!filterDepartmentId.value) return employees.value
  return employees.value.filter((e) => e.department_id === filterDepartmentId.value)
})

type LineForm = {
  _key: number
  category: string
  occurred_on: string
  amount: string
  description: string
  category_image_urls: string[]
  invoice_urls: string[]
  receipt_urls: string[]
}

function blankLine(): LineForm {
  return {
    _key: lineKeySeq++,
    category: '',
    occurred_on: today,
    amount: '',
    description: '',
    category_image_urls: [],
    invoice_urls: [],
    receipt_urls: [],
  }
}

const form = reactive({
  department_id: null as number | null,
  employee_id: null as number | null,
  reason: '',
  fund_account: 'cash' as string | null,
  lines: [blankLine()] as LineForm[],
})

const formEmployeeOptions = computed(() => {
  if (!form.department_id) return employees.value
  return employees.value.filter((e) => e.department_id === form.department_id)
})

const displayRows = computed(() => {
  const out: any[] = []
  for (const exp of rows.value) {
    const lines = exp.lines?.length ? exp.lines : [null]
    const lineCount = lines.length
    lines.forEach((line: any, lineIndex: number) => {
      out.push({
        ...exp,
        _key: `${exp.id}-${line?.id ?? lineIndex}`,
        _lineIndex: lineIndex,
        _lineCount: lineCount,
        line_category_label: line?.category_label || '',
        line_category_image_urls: line?.category_image_urls || [],
        line_occurred_on: line?.occurred_on || '',
        line_amount: line?.amount ?? 0,
        line_description: line?.description || '',
        line_invoice_urls: line?.invoice_urls || [],
        line_receipt_urls: line?.receipt_urls || [],
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

const totalAmount = computed(() =>
  form.lines.reduce((sum, line) => sum + (Number(line.amount) || 0), 0),
)

const CN_DIGITS = '零壹贰叁肆伍陆柒捌玖'
const CN_UNITS = ['', '拾', '佰', '仟']
const CN_SECTIONS = ['', '万', '亿']

function amountCn(value: number) {
  const money = Math.round((Number(value) || 0) * 100) / 100
  if (money === 0) return '零圆'
  const yuan = Math.floor(money)
  const fen = Math.round((money - yuan) * 100)

  function section(n: number) {
    if (!n) return ''
    let s = ''
    let zero = false
    let x = n
    for (let i = 0; i < 4 && x > 0; i++) {
      const d = x % 10
      x = Math.floor(x / 10)
      if (d === 0) {
        if (s) zero = true
      } else {
        if (zero) {
          s = CN_DIGITS[0] + s
          zero = false
        }
        s = CN_DIGITS[d] + CN_UNITS[i] + s
      }
    }
    return s
  }

  const parts: string[] = []
  if (yuan === 0) {
    parts.push('零圆')
  } else {
    const sections: string[] = []
    let n = yuan
    let si = 0
    while (n > 0) {
      const sec = n % 10000
      n = Math.floor(n / 10000)
      if (sec) sections.push(section(sec) + CN_SECTIONS[si])
      else if (sections.length) sections.push('')
      si += 1
    }
    let text = ''
    let needZero = false
    for (let i = sections.length - 1; i >= 0; i--) {
      const sec = sections[i]
      if (!sec) {
        needZero = true
        continue
      }
      if (needZero && !text.endsWith(CN_DIGITS[0])) text += CN_DIGITS[0]
      text += sec
      needZero = false
    }
    parts.push(text + '圆')
  }

  const jiao = Math.floor(fen / 10)
  const fenD = fen % 10
  if (!jiao && !fenD) {
    if (yuan > 0) parts.push('整')
  } else {
    if (jiao) parts.push(CN_DIGITS[jiao] + '角')
    else if (yuan > 0 && fenD) parts.push(CN_DIGITS[0])
    if (fenD) parts.push(CN_DIGITS[fenD] + '分')
  }
  return parts.join('')
}

function formatMoney(v: any) {
  const n = Number(v || 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function formatDate(v?: string | null) {
  if (!v) return '—'
  return String(v).slice(0, 10)
}

function formatYuan(v: any) {
  const n = Number(v || 0)
  return `${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}元`
}

function onAmountInput(line: LineForm) {
  line.amount = String(line.amount || '').replace(/[^\d.]/g, '')
}

async function loadCategorySuggestions() {
  const res: any = await http.get('/daily-expenses/category-suggestions')
  categorySuggestions.value = res.data?.items || []
}

async function onFilterDepartmentChange() {
  if (
    filterEmployeeId.value &&
    !filterEmployeeOptions.value.some((e) => e.id === filterEmployeeId.value)
  ) {
    filterEmployeeId.value = null
  }
  await load()
}

function onFormDepartmentChange() {
  if (
    form.employee_id &&
    !formEmployeeOptions.value.some((e) => e.id === form.employee_id)
  ) {
    form.employee_id = null
  }
}

function onFormEmployeeChange() {
  const emp = employees.value.find((e) => e.id === form.employee_id)
  if (emp?.department_id) {
    form.department_id = emp.department_id
  }
}

async function loadMeta() {
  const [deptRes, empRes]: any[] = await Promise.all([
    http.get('/departments'),
    http.get('/employees', { params: { page_size: 500, is_active: true } }),
  ])
  departments.value = deptRes.data?.items || []
  employees.value = empRes.data?.items || []
}

async function load() {
  const res: any = await http.get('/daily-expenses', {
    params: {
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
      department_id: filterDepartmentId.value || undefined,
      employee_id: filterEmployeeId.value || undefined,
      category: category.value || undefined,
      status: status.value || undefined,
    },
  })
  rows.value = res.data?.items || []
  summary.value = res.data?.summary || {}
}

function resetForm() {
  form.department_id = null
  form.employee_id = null
  form.reason = ''
  form.fund_account = 'cash'
  form.lines = [blankLine()]
}

function openCreate() {
  detailMode.value = false
  resetForm()
  categorySuggestions.value = []
  dialog.value = true
}

function openDetail(row: any) {
  detailMode.value = true
  form.department_id = row.department_id ?? null
  form.employee_id = row.employee_id ?? null
  form.reason = row.reason || ''
  form.fund_account = row.fund_account || null
  form.lines = (row.lines || []).map((l: any) => ({
    _key: lineKeySeq++,
    category: l.category_label || l.category || '',
    occurred_on: l.occurred_on || '',
    amount: l.amount != null ? String(l.amount) : '',
    description: l.description || '',
    category_image_urls: [...(l.category_image_urls || [])],
    invoice_urls: [...(l.invoice_urls || l.attachment_urls || [])],
    receipt_urls: [...(l.receipt_urls || [])],
  }))
  if (!form.lines.length) form.lines = [blankLine()]
  void loadCategorySuggestions()
  dialog.value = true
}

function addLine() {
  form.lines.push(blankLine())
}

function copyLine(index: number) {
  const src = form.lines[index]
  form.lines.splice(index + 1, 0, {
    _key: lineKeySeq++,
    category: src.category,
    occurred_on: src.occurred_on,
    amount: src.amount,
    description: src.description,
    category_image_urls: [...src.category_image_urls],
    invoice_urls: [...src.invoice_urls],
    receipt_urls: [...src.receipt_urls],
  })
}

function removeLine(index: number) {
  if (form.lines.length <= 1) return
  form.lines.splice(index, 1)
}

async function uploadLinePhoto(
  line: LineForm,
  kind: 'category' | 'invoice' | 'receipt',
  options: UploadRequestOptions,
) {
  const urls =
    kind === 'category'
      ? line.category_image_urls
      : kind === 'invoice'
        ? line.invoice_urls
        : line.receipt_urls
  const label = kind === 'category' ? '附图' : kind === 'invoice' ? '发票' : '收据'
  if (urls.length + uploadPending >= 9) {
    ElMessage.warning(`每条明细${label}最多 9 张`)
    options.onError?.(new Error('最多 9 张'))
    return
  }
  uploadPending += 1
  uploading.value = true
  try {
    const data = new FormData()
    data.append('file', options.file)
    const res: any = await http.post('/daily-expenses/upload', data)
    const url = res.data?.url
    if (url && !urls.includes(url)) urls.push(url)
    options.onSuccess?.(res)
  } catch (error) {
    ElMessage.error('上传失败')
    options.onError?.(error as Error)
  } finally {
    uploadPending -= 1
    uploading.value = uploadPending > 0
  }
}

async function save() {
  if (!form.department_id) {
    ElMessage.warning('请选择报销部门')
    return
  }
  if (!form.employee_id) {
    ElMessage.warning('请选择报销人')
    return
  }
  for (let i = 0; i < form.lines.length; i++) {
    const line = form.lines[i]
    if (!line.category?.trim()) {
      ElMessage.warning(`第 ${i + 1} 条明细请填写费用类型`)
      return
    }
    if (!line.occurred_on) {
      ElMessage.warning(`第 ${i + 1} 条明细请选择产生日期`)
      return
    }
    if (!(Number(line.amount) > 0)) {
      ElMessage.warning(`第 ${i + 1} 条明细请填写费用金额`)
      return
    }
  }
  saving.value = true
  try {
    await http.post('/daily-expenses', {
      department_id: form.department_id,
      employee_id: form.employee_id,
      reason: form.reason || undefined,
      fund_account: form.fund_account || undefined,
      lines: form.lines.map((line) => ({
        category: line.category.trim(),
        category_image_urls: line.category_image_urls,
        occurred_on: line.occurred_on,
        amount: Number(line.amount),
        description: line.description || undefined,
        invoice_urls: line.invoice_urls,
        receipt_urls: line.receipt_urls,
      })),
    })
    ElMessage.success('已登记')
    dialog.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function voidExpense(row: any) {
  await ElMessageBox.confirm(
    `作废 ${row.employee_name || ''} ${formatMoney(row.amount)}？`,
    '作废日常开支',
  )
  await http.post(`/daily-expenses/${row.id}/void`)
  ElMessage.success('已作废')
  await load()
}

onMounted(async () => {
  await loadMeta()
  await loadCategorySuggestions()
  await load()
})
</script>

<style scoped>
.expense-line-card {
  margin: 0 0 12px;
  padding: 12px 12px 4px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}
.expense-line-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 4px;
}
.expense-line-actions {
  display: flex;
  gap: 4px;
}
.add-line-btn {
  width: 100%;
  margin: 4px 0 12px;
}
.expense-total {
  margin-top: 4px;
  padding: 10px 4px 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.expense-attach-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.expense-attach-item {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
}
.expense-attach-item :deep(.el-image) {
  width: 100%;
  height: 100%;
}
.expense-table-thumb {
  width: 36px;
  height: 36px;
  border-radius: 4px;
  vertical-align: middle;
}
.attach-remove {
  position: absolute;
  top: 0;
  right: 0;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 0 0 0 6px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  line-height: 18px;
  cursor: pointer;
}
</style>
