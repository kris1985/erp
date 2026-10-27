<template>
  <app-nav-bar />
  <view class="page h5-exp" :class="{ 'h5-exp--form': mode !== 'list' }">
    <template v-if="mode === 'list'">
      <view class="h5-exp-tabs">
        <text v-for="tab in statusTabs" :key="tab.value" :class="{ on: status === tab.value }" @click="setStatus(tab.value)">{{ tab.label }}</text>
        <text class="h5-exp-filter-btn" :class="{ on: filtersOpen || hasFilter }" @click="filtersOpen = !filtersOpen">筛选</text>
      </view>

      <view v-if="filtersOpen" class="card h5-exp-filters">
        <view class="h5-exp-filter-row">
          <picker mode="date" :value="dateFrom || today" @change="onDateFrom">
            <text :class="{ muted: !dateFrom }">{{ dateFrom || '开始日期' }}</text>
          </picker>
          <text class="h5-exp-gap">至</text>
          <picker mode="date" :value="dateTo || today" @change="onDateTo">
            <text :class="{ muted: !dateTo }">{{ dateTo || '结束日期' }}</text>
          </picker>
        </view>
        <view class="h5-exp-filter-row">
          <text :class="{ muted: !filterDepartmentId }" @click="openPicker('filter-dept')">{{ filterDepartmentName }}</text>
          <text :class="{ muted: !category }" @click="openPicker('filter-cat')">{{ category || '费用类型' }}</text>
        </view>
        <text v-if="hasFilter" class="h5-exp-clear" @click="clearFilters">清除筛选</text>
      </view>

      <view class="h5-exp-sum">
        <text>{{ summaryLabel }}</text>
        <strong>¥{{ money(summaryAmount) }}</strong>
        <text>{{ summary.count || 0 }} 笔</text>
      </view>

      <view v-if="loading" class="h5-home-empty">加载中…</view>
      <view v-else-if="!rows.length" class="h5-home-empty">还没有报销。提交后由财务付款入账。</view>
      <view v-else class="h5-exp-list">
        <view v-for="row in rows" :key="row.id" class="card h5-exp-slip" @click="openDetail(row)">
          <view class="h5-exp-slip__top">
            <view class="h5-exp-slip__copy">
              <strong>{{ slipTitle(row) }}</strong>
              <text>{{ slipMeta(row) }}</text>
              <text v-if="showOwner(row)">{{ row.employee_name }}</text>
            </view>
            <view class="h5-exp-slip__amt">
              <strong>¥{{ money(row.amount) }}</strong>
              <text :class="['h5-defect-status', row.status]">{{ statusText(row.status) }}</text>
            </view>
          </view>
          <view v-if="slipPhotos(row).length" class="h5-exp-slip__photos">
            <image
              v-for="url in slipPhotos(row)"
              :key="url"
              :src="displayImageUrl(url)"
              mode="aspectFill"
              @click.stop="preview(slipPhotos(row, false), url)"
            />
          </view>
          <view class="h5-exp-slip__foot">
            <text>{{ formatDate(row.created_at) }} 提交</text>
            <button v-if="canVoidRow(row)" @click.stop="voidExpense(row)">作废</button>
          </view>
        </view>
      </view>

      <view v-if="canApply" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" @click="openCreate">申请报销</button>
      </view>
    </template>

    <template v-else>
      <view class="card h5-exp-head">
        <view class="h5-exp-row" @click="openBearDepartment">
          <text>费用承担部门</text>
          <strong :class="{ need: !form.department_id }">{{ form.department_id || detailMode ? bearDepartment : '请选择' }}</strong>
          <text v-if="!detailMode" class="h5-exp-chev">›</text>
        </view>
        <view v-if="!detailMode || form.reason" class="h5-exp-row">
          <text>事由</text>
          <input :value="form.reason" :disabled="detailMode" maxlength="255" placeholder="可留空" @input="onReason" />
        </view>
      </view>

      <view v-for="(line, index) in form.lines" :key="line.key" class="card h5-exp-line">
        <view v-if="form.lines.length > 1" class="h5-exp-line__head">
          <strong>第 {{ index + 1 }} 笔</strong>
          <text v-if="!detailMode" class="danger" @click="removeLine(index)">删除</text>
        </view>

        <view class="h5-exp-amount">
          <text>金额</text>
          <view v-if="detailMode" class="h5-exp-amount__value">¥{{ money(line.amount) }}</view>
          <view v-else class="h5-exp-amount__input">
            <text>¥</text>
            <input :value="line.amount" type="digit" placeholder="0.00" @input="onAmount(line, $event)" />
          </view>
        </view>

        <text class="h5-exp-label">费用类型</text>
        <view v-if="detailMode" class="h5-exp-cat">{{ line.category || '—' }}</view>
        <view v-else class="h5-exp-chips">
          <text
            v-for="name in quickCategories(line)"
            :key="name"
            :class="{ on: line.category === name }"
            @click="pickCategory(line, name)"
          >{{ name }}</text>
          <text :class="{ on: line.category && !quickCategories(line).includes(line.category) }" @click="openPicker('form-cat', index)">
            {{ line.category && !quickCategories(line).includes(line.category) ? line.category : '更多类型' }}
          </text>
        </view>

        <picker v-if="!detailMode" mode="date" :value="line.occurred_on || today" @change="onLineDate(line, $event)">
          <view class="h5-exp-row h5-exp-row--inset">
            <text>发生日期</text>
            <strong>{{ friendlyDate(line.occurred_on) }}</strong>
            <text class="h5-exp-chev">›</text>
          </view>
        </picker>
        <view v-else class="h5-exp-row h5-exp-row--inset">
          <text>发生日期</text>
          <strong>{{ friendlyDate(line.occurred_on) }}</strong>
        </view>

        <view v-if="!detailMode || line.description" class="h5-exp-note">
          <input v-if="!detailMode" :value="line.description" maxlength="500" placeholder="补充说明，可留空" @input="onDescription(line, $event)" />
          <text v-else>{{ line.description }}</text>
        </view>

        <view class="h5-exp-shots">
          <view v-for="slot in photoSlots(line)" :key="slot.kind" class="h5-exp-shot">
            <view v-if="slot.urls.length" class="h5-exp-shot__photos">
              <view v-for="(url, imgIdx) in slot.urls" :key="url" class="h5-exp-shot__item">
                <image :src="displayImageUrl(url)" mode="aspectFill" @click="preview(slot.urls, url)" />
                <text v-if="!detailMode" @click.stop="slot.urls.splice(imgIdx, 1)">×</text>
              </view>
            </view>
            <view v-if="!detailMode && slot.urls.length < 9" class="h5-exp-shot__add" @click="choosePhotos(line, slot.kind)">
              <strong>{{ slot.urls.length ? `继续添加${slot.label}` : `添加${slot.label}` }}</strong>
            </view>
            <view v-else-if="!slot.urls.length" class="h5-exp-shot__add h5-exp-shot__add--empty">
              <strong>无{{ slot.label }}</strong>
            </view>
          </view>
        </view>
      </view>

      <view v-if="!detailMode" class="h5-exp-add" @click="addLine">再记一笔</view>

      <view class="cut-sticky-bar h5-exp-paybar">
        <text v-if="!detailMode && submitHint" class="h5-exp-pay__hint">{{ submitHint }}</text>
        <view class="h5-exp-pay">
          <view v-if="totalAmount > 0" class="h5-exp-pay__sum">
            <text>合计</text>
            <strong>¥{{ money(totalAmount) }}</strong>
            <text>{{ amountCn(totalAmount) }}</text>
          </view>
          <button v-if="detailMode && canVoidCurrent" class="h5-exp-void" @click="voidCurrent">作废</button>
          <button v-if="detailMode" class="primary-button cut-sticky-button" @click="closeForm">关闭</button>
          <button v-else class="primary-button cut-sticky-button" :loading="saving" :disabled="saving || uploading" @click="save">{{ hasEntered ? '提交报销' : '申请报销' }}</button>
        </view>
      </view>
    </template>

    <view v-if="picker" class="h5-exp-mask" @click="closePicker">
      <view class="h5-exp-sheet" @click.stop>
        <view class="h5-exp-sheet__head">
          <strong>{{ pickerTitle }}</strong>
          <text @click="closePicker">关闭</text>
        </view>
        <input class="h5-exp-sheet__search" :value="picker.keyword" placeholder="搜索" @input="onPickerKeyword" />
        <view v-if="picker.kind.startsWith('filter')" class="h5-exp-option" @click="choosePicker(null)">不限</view>
        <view v-if="!pickerOptions.length" class="h5-exp-sheet__empty">没有匹配项</view>
        <scroll-view v-else scroll-y class="h5-exp-sheet__list">
          <view v-for="option in pickerOptions" :key="String(option.id)" class="h5-exp-option" @click="choosePicker(option)">
            {{ option.label }}
          </view>
        </scroll-view>
        <view v-if="picker.kind === 'form-cat'" class="h5-exp-sheet__create">
          <input :value="customCategory" maxlength="100" placeholder="新建费用类型" @input="onCustomCategory" />
          <text @click="confirmCustomCategory">确定</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onBackPress, onShow } from '@dcloudio/uni-app'
import { get, post, uploadFile } from '../../services/http'
import { getProfile, getToken, setSession, type UserProfile } from '../../services/storage'

type LineForm = {
  key: number
  category: string
  occurred_on: string
  amount: string
  description: string
  category_image_urls: string[]
  invoice_urls: string[]
  receipt_urls: string[]
}
type PhotoKind = 'category' | 'invoice' | 'receipt'
type PickerKind = 'filter-dept' | 'filter-cat' | 'form-dept' | 'form-cat'
type PickerState = { kind: PickerKind; lineIndex?: number; keyword: string }
type Named = { id: number; name: string }

const statusTabs = [
  { label: '待付款', value: 'pending' },
  { label: '已入账', value: 'posted' },
  { label: '已作废', value: 'void' },
  { label: '全部', value: '' },
]
const now = new Date()
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
const profile = ref<UserProfile | null>(getProfile())
const mode = ref<'list' | 'form'>('list')
const detailMode = ref(false)
const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const filtersOpen = ref(false)
const rows = ref<any[]>([])
const summary = ref<any>({})
const departments = ref<Named[]>([])
const categorySuggestions = ref<string[]>([])
const dateFrom = ref('')
const dateTo = ref('')
const filterDepartmentId = ref<number | null>(null)
const category = ref('')
const status = ref('pending')
const picker = ref<PickerState | null>(null)
const customCategory = ref('')
const editingId = ref<number | null>(null)
const editingStatus = ref('')
const editingEmployeeId = ref<number | null>(null)
const editingCreatedBy = ref<number | null>(null)
const detailDepartmentName = ref('')
let lineKey = 1

const canWrite = computed(() => (profile.value?.permissions || []).includes('btn.daily_expenses.write') || profile.value?.role === 'admin')
const canApply = computed(() => (profile.value?.featurePermissions || []).includes('expense') || (profile.value?.permissions || []).includes('menu.daily_expenses') || canWrite.value)
const canView = canApply
const bearDepartment = computed(() => {
  if (form.department_id) {
    return departments.value.find(item => item.id === form.department_id)?.name || detailDepartmentName.value || '请选择'
  }
  return detailMode.value ? (detailDepartmentName.value || '—') : '请选择'
})
const hasEntered = computed(() => {
  if (form.department_id || form.reason.trim()) return true
  return form.lines.some(line => Boolean(
    line.category.trim()
    || String(line.amount || '').trim()
    || line.description.trim()
    || line.category_image_urls.length
    || line.invoice_urls.length
    || line.receipt_urls.length
  ))
})
const submitHint = computed(() => {
  if (detailMode.value) return ''
  if (!form.department_id) return '先选择费用承担部门'
  for (let index = 0; index < form.lines.length; index++) {
    const line = form.lines[index]
    const prefix = form.lines.length > 1 ? `第 ${index + 1} 笔：` : ''
    if (!line.category.trim()) return `${prefix}选择费用类型`
    if (!(Number(line.amount) > 0)) return `${prefix}填写金额`
  }
  if (uploading.value) return '照片上传中'
  return ''
})
const canVoidCurrent = computed(() => canVoidRow({
  status: editingStatus.value,
  employee_id: editingEmployeeId.value,
  created_by: editingCreatedBy.value,
}))
function canVoidRow(row: { status?: string, employee_id?: number | null, created_by?: number | null }) {
  if (!row || row.status === 'void') return false
  if (canWrite.value) return true
  if (!canApply.value || row.status !== 'pending') return false
  const me = profile.value?.id
  return row.employee_id === me || row.created_by === me
}
const filterDepartmentName = computed(() => departments.value.find(item => item.id === filterDepartmentId.value)?.name || '费用承担部门')
const hasFilter = computed(() => Boolean(dateFrom.value || dateTo.value || filterDepartmentId.value || category.value))
const summaryLabel = computed(() => status.value === 'pending' ? '待付款' : status.value === 'void' ? '已作废' : '已入账')
const summaryAmount = computed(() => {
  if (status.value === 'posted' || status.value === '') return summary.value.posted_total
  return rows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0)
})
const totalAmount = computed(() => form.lines.reduce((sum, line) => sum + (Number(line.amount) || 0), 0))
const pickerTitle = computed(() => {
  const kind = picker.value?.kind
  if (kind === 'filter-dept' || kind === 'form-dept') return '费用承担部门'
  return '费用类型'
})
const pickerOptions = computed(() => {
  const current = picker.value
  if (!current) return []
  const keyword = current.keyword.trim()
  const match = (label: string) => !keyword || label.includes(keyword)
  if (current.kind === 'filter-dept' || current.kind === 'form-dept') {
    return departments.value.filter(item => match(item.name)).map(item => ({ id: item.id, label: item.name }))
  }
  const line = current.lineIndex == null ? null : form.lines[current.lineIndex]
  const items = categorySuggestions.value.slice()
  if (line?.category && !items.includes(line.category)) items.unshift(line.category)
  return items.filter(match).map(item => ({ id: item, label: item }))
})

function blankLine(): LineForm {
  return {
    key: lineKey++,
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
  lines: [blankLine()] as LineForm[],
})

const money = (value: unknown) => Number(value || 0).toFixed(2)
function statusText(value?: string) {
  if (value === 'pending') return '待付款'
  if (value === 'posted') return '已入账'
  return '已作废'
}
const formatDate = (value?: string | null) => (value ? String(value).slice(0, 10) : '—')
function friendlyDate(value?: string) {
  if (!value) return '请选择'
  if (value === today) return '今天'
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  if (year === now.getFullYear()) return `${month}月${day}日`
  return `${year}年${month}月${day}日`
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function preview(urls: string[], current?: string) {
  const resolved = (urls || []).map(displayImageUrl).filter(Boolean)
  if (!resolved.length) return
  uni.previewImage({ urls: resolved, current: current ? displayImageUrl(current) : resolved[0] })
}
function linePhotoGroups(line: any) {
  return [
    { label: '附图', urls: line.category_image_urls || [] },
    { label: '发票', urls: line.invoice_urls || [] },
    { label: '收据', urls: line.receipt_urls || [] },
  ].filter(group => group.urls.length)
}
function slipLabels(row: any) {
  return [...new Set((row.lines || []).map((line: any) => line.category_label || line.category).filter(Boolean))] as string[]
}
function slipTitle(row: any) {
  const reason = String(row.reason || '').trim()
  if (reason) return reason
  const labels = slipLabels(row)
  if (labels.length > 1) return `${labels[0]} 等 ${labels.length} 项`
  return labels[0] || '报销'
}
function slipMeta(row: any) {
  const date = formatDate(row.lines?.[0]?.occurred_on || row.expense_date || row.created_at)
  const reason = String(row.reason || '').trim()
  if (!reason) return date
  const labels = slipLabels(row)
  const kind = labels.length > 1 ? `${labels[0]} 等 ${labels.length} 项` : (labels[0] || '')
  return [kind, date].filter(Boolean).join(' · ')
}
function slipPhotos(row: any, limit = true) {
  const urls: string[] = []
  for (const line of row.lines || []) {
    for (const group of linePhotoGroups(line)) urls.push(...group.urls)
  }
  return limit ? urls.slice(0, 4) : urls
}
function showOwner(row: any) {
  return Boolean(row.employee_id && row.employee_id !== profile.value?.id)
}
function photoSlots(line: LineForm) {
  return [
    { kind: 'category' as PhotoKind, label: '附图', urls: line.category_image_urls },
    { kind: 'invoice' as PhotoKind, label: '发票', urls: line.invoice_urls },
    { kind: 'receipt' as PhotoKind, label: '收据', urls: line.receipt_urls },
  ]
}
function quickCategories(_line: LineForm) {
  return categorySuggestions.value.slice(0, 6)
}
function pickCategory(line: LineForm, name: string) {
  line.category = name
}
function inputValue(event: any) {
  return String(event?.detail?.value ?? event?.target?.value ?? '')
}

const CN_DIGITS = '零壹贰叁肆伍陆柒捌玖'
const CN_UNITS = ['', '拾', '佰', '仟']
const CN_SECTIONS = ['', '万', '亿']
function amountCn(value: number) {
  const moneyValue = Math.round((Number(value) || 0) * 100) / 100
  if (moneyValue === 0) return '零圆'
  const yuan = Math.floor(moneyValue)
  const fen = Math.round((moneyValue - yuan) * 100)
  function section(n: number) {
    if (!n) return ''
    let text = ''
    let zero = false
    let current = n
    for (let i = 0; i < 4 && current > 0; i++) {
      const digit = current % 10
      current = Math.floor(current / 10)
      if (digit === 0) {
        if (text) zero = true
      } else {
        if (zero) {
          text = CN_DIGITS[0] + text
          zero = false
        }
        text = CN_DIGITS[digit] + CN_UNITS[i] + text
      }
    }
    return text
  }
  const parts: string[] = []
  if (yuan === 0) parts.push('零圆')
  else {
    const sections: string[] = []
    let rest = yuan
    let index = 0
    while (rest > 0) {
      const chunk = rest % 10000
      rest = Math.floor(rest / 10000)
      sections.push(chunk ? section(chunk) + CN_SECTIONS[index] : '')
      index += 1
    }
    let text = ''
    let needZero = false
    for (let i = sections.length - 1; i >= 0; i--) {
      if (!sections[i]) {
        needZero = true
        continue
      }
      if (needZero && !text.endsWith(CN_DIGITS[0])) text += CN_DIGITS[0]
      text += sections[i]
      needZero = false
    }
    parts.push(`${text}圆`)
  }
  const jiao = Math.floor(fen / 10)
  const fenDigit = fen % 10
  if (!jiao && !fenDigit) {
    if (yuan > 0) parts.push('整')
  } else {
    if (jiao) parts.push(CN_DIGITS[jiao] + '角')
    else if (yuan > 0 && fenDigit) parts.push(CN_DIGITS[0])
    if (fenDigit) parts.push(CN_DIGITS[fenDigit] + '分')
  }
  return parts.join('')
}

function setStatus(next: string) {
  status.value = next
  load()
}
function onDateFrom(event: any) {
  dateFrom.value = inputValue(event)
  load()
}
function onDateTo(event: any) {
  dateTo.value = inputValue(event)
  load()
}
function clearFilters() {
  dateFrom.value = ''
  dateTo.value = ''
  filterDepartmentId.value = null
  category.value = ''
  load()
}
function syncTitle() {
  const title = mode.value === 'list' ? '报销' : detailMode.value ? '报销详情' : '报销申请'
  uni.setNavigationBarTitle({ title })
}
function closePicker() {
  picker.value = null
}
function closeForm() {
  mode.value = 'list'
  closePicker()
  syncTitle()
}
function applySelf() {
  form.employee_id = profile.value?.id ?? null
  form.department_id = null
}
function openBearDepartment() {
  if (detailMode.value) return
  openPicker('form-dept')
}
function resetForm() {
  applySelf()
  form.reason = ''
  form.lines = [blankLine()]
  detailDepartmentName.value = ''
}
function openCreate() {
  detailMode.value = false
  editingId.value = null
  editingStatus.value = ''
  editingEmployeeId.value = null
  editingCreatedBy.value = null
  resetForm()
  mode.value = 'form'
  syncTitle()
}
function openDetail(row: any) {
  detailMode.value = true
  editingId.value = row.id
  editingStatus.value = row.status || ''
  editingEmployeeId.value = row.employee_id ?? null
  editingCreatedBy.value = row.created_by ?? null
  detailDepartmentName.value = row.department_name || ''
  form.department_id = row.department_id ?? null
  form.employee_id = row.employee_id ?? null
  form.reason = row.reason || ''
  form.lines = (row.lines || []).map((line: any) => ({
    key: lineKey++,
    category: line.category_label || line.category || '',
    occurred_on: line.occurred_on || '',
    amount: line.amount != null ? String(line.amount) : '',
    description: line.description || '',
    category_image_urls: [...(line.category_image_urls || [])],
    invoice_urls: [...(line.invoice_urls || line.attachment_urls || [])],
    receipt_urls: [...(line.receipt_urls || [])],
  }))
  if (!form.lines.length) form.lines = [blankLine()]
  mode.value = 'form'
  syncTitle()
}
function addLine() {
  form.lines.push(blankLine())
}
function removeLine(index: number) {
  if (form.lines.length <= 1) return
  form.lines.splice(index, 1)
}
function onReason(event: any) {
  form.reason = inputValue(event)
}
function onAmount(line: LineForm, event: any) {
  line.amount = inputValue(event).replace(/[^\d.]/g, '')
}
function onDescription(line: LineForm, event: any) {
  line.description = inputValue(event)
}
function onLineDate(line: LineForm, event: any) {
  line.occurred_on = inputValue(event)
}
function rememberCategory(value: string) {
  const text = value.trim()
  if (text && !categorySuggestions.value.includes(text)) categorySuggestions.value = [...categorySuggestions.value, text]
}
function openPicker(kind: PickerKind, lineIndex?: number) {
  if (detailMode.value && kind.startsWith('form')) return
  picker.value = { kind, lineIndex, keyword: '' }
  customCategory.value = ''
}
function onPickerKeyword(event: any) {
  if (picker.value) picker.value.keyword = inputValue(event)
}
function onCustomCategory(event: any) {
  customCategory.value = inputValue(event)
}
function choosePicker(option: { id: number | string; label: string } | null) {
  const current = picker.value
  if (!current) return
  if (current.kind === 'filter-dept') {
    filterDepartmentId.value = option ? Number(option.id) : null
    load()
  } else if (current.kind === 'filter-cat') {
    category.value = option ? option.label : ''
    load()
  } else if (current.kind === 'form-dept') {
    form.department_id = option ? Number(option.id) : null
  } else if (current.kind === 'form-cat' && current.lineIndex != null && option) {
    form.lines[current.lineIndex].category = option.label
    rememberCategory(option.label)
  }
  closePicker()
}
function confirmCustomCategory() {
  const text = customCategory.value.trim()
  const index = picker.value?.lineIndex
  if (!text || index == null) return uni.showToast({ title: '请填写费用类型', icon: 'none' })
  if (text.length > 100) return uni.showToast({ title: '费用类型不能超过 100 字', icon: 'none' })
  form.lines[index].category = text
  rememberCategory(text)
  closePicker()
}
async function choosePhotos(line: LineForm, kind: PhotoKind) {
  const urls = kind === 'category' ? line.category_image_urls : kind === 'invoice' ? line.invoice_urls : line.receipt_urls
  const label = kind === 'category' ? '附图' : kind === 'invoice' ? '发票' : '收据'
  if (uploading.value) return
  if (urls.length >= 9) return uni.showToast({ title: `每条明细${label}最多 9 张`, icon: 'none' })
  try {
    const result = await uni.chooseImage({
      count: Math.min(9 - urls.length, 9),
      sizeType: ['compressed'],
      sourceType: ['camera', 'album'],
    })
    uploading.value = true
    for (const path of result?.tempFilePaths || []) {
      if (urls.length >= 9) break
      const uploaded: any = await uploadFile('/daily-expenses/upload', path)
      const url = uploaded?.url
      if (url && !urls.includes(url)) urls.push(url)
    }
  } catch (error: any) {
    const message = String(error?.errMsg || error?.message || '')
    if (!/cancel/i.test(message)) uni.showToast({ title: error?.message || '上传失败', icon: 'none' })
  } finally {
    uploading.value = false
  }
}
async function ensureSelf() {
  try {
    const me: any = await get('/auth/me')
    const cached = getProfile()
    const token = getToken()
    if (!cached || !token) return
    const next: UserProfile = {
      ...cached,
      id: Number(me?.id || cached.id),
      displayName: me?.display_name || me?.name || cached.displayName,
      departmentId: me?.department_id ?? null,
      departmentName: me?.department_name || '',
    }
    setSession(token, next)
    profile.value = next
  } catch {
    profile.value = getProfile()
  }
}
async function loadMeta() {
  const [departmentResult, categoryResult]: any[] = await Promise.all([
    get('/departments'),
    get('/daily-expenses/category-suggestions'),
  ])
  departments.value = departmentResult?.items || []
  categorySuggestions.value = categoryResult?.items || []
}
async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {}
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    if (filterDepartmentId.value) params.department_id = filterDepartmentId.value
    if (category.value) params.category = category.value
    if (status.value) params.status = status.value
    const result: any = await get('/daily-expenses', params)
    rows.value = result?.items || []
    summary.value = result?.summary || {}
  } catch (error: any) {
    uni.showToast({ title: error?.message || '报销加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}
async function save() {
  const employeeId = profile.value?.id
  const departmentId = form.department_id
  if (!employeeId) return uni.showToast({ title: '请重新登录后再提交', icon: 'none' })
  if (!departmentId) return uni.showToast({ title: '请选择费用承担部门', icon: 'none' })
  for (let index = 0; index < form.lines.length; index++) {
    const line = form.lines[index]
    const cat = line.category.trim()
    if (!cat) return uni.showToast({ title: `第 ${index + 1} 条明细请选择费用类型`, icon: 'none' })
    if (cat.length > 100) return uni.showToast({ title: `第 ${index + 1} 条明细费用类型过长`, icon: 'none' })
    line.category = cat
    if (!line.occurred_on) return uni.showToast({ title: `第 ${index + 1} 条明细请选择产生日期`, icon: 'none' })
    if (!(Number(line.amount) > 0)) return uni.showToast({ title: `第 ${index + 1} 条明细请填写费用金额`, icon: 'none' })
  }
  saving.value = true
  try {
    await post('/daily-expenses', {
      department_id: departmentId,
      employee_id: employeeId,
      await_payment: true,
      reason: form.reason || undefined,
      lines: form.lines.map(line => ({
        category: line.category.trim(),
        category_image_urls: line.category_image_urls,
        occurred_on: line.occurred_on,
        amount: Number(line.amount),
        description: line.description || undefined,
        invoice_urls: line.invoice_urls,
        receipt_urls: line.receipt_urls,
      })),
    })
    uni.showToast({ title: '已提交，待财务付款', icon: 'none' })
    status.value = 'pending'
    closeForm()
    await load()
  } catch (error: any) {
    uni.showToast({ title: error?.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}
function voidExpense(row: any) {
  uni.showModal({
    title: '作废报销',
    content: `作废 ¥${money(row.amount)}？`,
    success: async result => {
      if (!result.confirm) return
      try {
        await post(`/daily-expenses/${row.id}/void`, {})
        uni.showToast({ title: '已作废', icon: 'none' })
        if (editingId.value === row.id) closeForm()
        await load()
      } catch (error: any) {
        uni.showToast({ title: error?.message || '作废失败', icon: 'none' })
      }
    },
  })
}
function voidCurrent() {
  const row = rows.value.find(item => item.id === editingId.value)
  if (row) voidExpense(row)
}
onBackPress(() => {
  if (picker.value) {
    closePicker()
    return true
  }
  if (mode.value !== 'list') {
    closeForm()
    return true
  }
  return false
})
onShow(async () => {
  profile.value = getProfile()
  syncTitle()
  if (!canView.value) {
    uni.showToast({ title: '没有报销权限', icon: 'none' })
    setTimeout(() => uni.navigateBack(), 500)
    return
  }
  await ensureSelf()
  if (mode.value !== 'list') return
  try { await loadMeta() } catch (error: any) {
    uni.showToast({ title: error?.message || '基础资料加载失败', icon: 'none' })
  }
  await load()
})
</script>
