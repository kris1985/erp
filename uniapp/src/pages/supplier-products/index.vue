<template>
  <view class="page h5-sw" :class="{ 'h5-sw--sub': mode !== 'list' }">
    <view v-if="!canSee" class="h5-home-empty">没有物料色卡权限</view>

    <template v-else-if="mode === 'list'">
      <view class="card h5-sw-search">
        <input :value="keyword" confirm-type="search" placeholder="搜名称、编号、供应商、颜色" @input="onKeyword" @confirm="reload" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>

      <scroll-view class="h5-sw-cats" scroll-x :show-scrollbar="false">
        <text :class="{ on: !categoryId }" @click="setCategory(null)">全部</text>
        <text v-for="item in categories" :key="item.id" :class="{ on: categoryId === item.id }" @click="setCategory(item.id)">{{ item.name }}</text>
      </scroll-view>

      <view class="h5-sw-filters">
        <text v-for="tab in approvalTabs" :key="tab.value" :class="{ on: approval === tab.value }" @click="setApproval(tab.value)">{{ tab.label }}</text>
        <text class="h5-sw-filters__supplier" :class="{ on: !!partnerId }" @click="openSheet('supplier-filter')">{{ supplierFilterLabel }}</text>
      </view>

      <view v-if="loading && !rows.length" class="h5-home-empty">加载中…</view>
      <view v-else-if="!rows.length" class="h5-home-empty">没有匹配的色卡</view>
      <view v-else class="h5-sw-list">
        <view
          v-for="row in rows"
          :key="row.id"
          class="card h5-sw-card"
          :class="{ 'is-picked': !!picked[row.id], 'is-locked': selecting && row.approval_status !== 'approved' }"
          @click="onCard(row)"
        >
          <view v-if="selecting" class="h5-sw-check" :class="{ on: !!picked[row.id] }" />
          <image v-if="row.image_url" class="h5-sw-thumb" :src="displayImageUrl(row.image_url)" mode="aspectFill" @click.stop="previewImage(row.image_url)" />
          <view v-else class="h5-sw-thumb">{{ swatchText(row) }}</view>
          <view class="h5-sw-card__body">
            <view class="h5-sw-card__top">
              <strong>{{ row.name || row.product_code }}</strong>
              <text>¥{{ priceText(row.unit_price) }}</text>
            </view>
            <text class="h5-sw-card__meta">{{ cardMeta(row) }}</text>
            <view class="h5-sw-card__foot">
              <text>{{ row.partner_name || '未填供应商' }}</text>
              <text :class="['h5-defect-status', row.approval_status === 'pending' ? 'pending' : 'confirmed']">{{ approvalText(row) }}</text>
            </view>
          </view>
        </view>
        <view class="h5-sw-more">{{ finished ? `共 ${total} 条` : loadingMore ? '加载中…' : '上拉加载更多' }}</view>
      </view>

      <view v-if="selecting" class="cut-sticky-bar h5-sw-bar">
        <button class="h5-sw-ghost" @click="cancelSelect">取消</button>
        <button class="primary-button h5-sw-primary" :disabled="!pickedCount" @click="openBuy">填写数量{{ pickedCount ? ` · ${pickedCount}` : '' }}</button>
      </view>
      <view v-else class="cut-sticky-bar h5-sw-bar">
        <button v-if="canBuy" class="h5-sw-ghost" @click="startSelect">批量购买</button>
        <button v-if="canWrite" class="primary-button h5-sw-primary" @click="openCreate">新增物料</button>
      </view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <text class="h5-sw-back" @click="backToList">‹ 返回列表</text>
      <view class="card h5-sw-hero">
        <image v-if="current.image_url" :src="displayImageUrl(current.image_url)" mode="aspectFill" @click="previewImage(current.image_url)" />
        <view v-else class="h5-sw-hero__empty">{{ swatchText(current) }}</view>
        <view class="h5-sw-hero__copy">
          <strong>{{ current.name || '未命名' }}</strong>
          <text>{{ current.product_code }}</text>
          <text :class="['h5-defect-status', current.approval_status === 'pending' ? 'pending' : 'confirmed']">{{ approvalText(current) }}</text>
        </view>
      </view>
      <view class="card h5-sw-facts">
        <view class="h5-sw-fact"><text>分类</text><strong>{{ current.category_name || '—' }}</strong></view>
        <view class="h5-sw-fact"><text>颜色</text><strong>{{ current.color_name || '—' }}</strong></view>
        <view class="h5-sw-fact"><text>单价</text><strong>¥{{ priceText(current.unit_price) }}<text v-if="current.pricing_unit_name"> / {{ current.pricing_unit_name }}</text></strong></view>
        <view class="h5-sw-fact" @click="openSupplier"><text>供应商</text><strong>{{ current.partner_name || '—' }}</strong><text class="h5-sw-chev">›</text></view>
        <view class="h5-sw-fact"><text>录入</text><strong>{{ timeText(current.created_at) }}</strong></view>
      </view>

      <view v-if="current.price_histories?.length" class="card h5-sw-history">
        <text class="h5-sw-history__title">单价变更</text>
        <view v-for="item in current.price_histories" :key="item.id" class="h5-sw-history__line">
          <text>{{ timeText(item.changed_at) }} · {{ item.changed_by_name || '—' }}</text>
          <strong>¥{{ priceText(item.old_price) }} → ¥{{ priceText(item.new_price) }}</strong>
        </view>
      </view>
      <view v-if="current.supplier_histories?.length" class="card h5-sw-history">
        <text class="h5-sw-history__title">供应商变更</text>
        <view v-for="item in current.supplier_histories" :key="item.id" class="h5-sw-history__line">
          <text>{{ timeText(item.changed_at) }} · {{ item.changed_by_name || '—' }}</text>
          <strong>{{ item.old_partner_name || '—' }} → {{ item.new_partner_name || '—' }}</strong>
        </view>
      </view>

      <view class="cut-sticky-bar h5-sw-bar">
        <button v-if="canApproveCurrent" class="h5-sw-ghost h5-sw-ghost--ok" @click="approveCurrent">审批</button>
        <button v-if="canEditCurrent" class="h5-sw-ghost" @click="openEdit(current)">编辑</button>
        <button class="h5-sw-ghost" @click="openLabel(current)">标签</button>
        <button v-if="canDeleteCurrent" class="h5-sw-ghost h5-sw-ghost--danger" @click="removeCurrent">删除</button>
      </view>
    </template>

    <template v-else-if="mode === 'form'">
      <view class="card h5-sw-form">
        <view v-if="form.image_url" class="h5-sw-photo">
          <image :src="displayImageUrl(form.image_url)" mode="aspectFill" @click="previewImage(form.image_url)" />
          <text v-if="!uploading" class="h5-sw-photo__clear" @click.stop="form.image_url = ''">清除</text>
        </view>
        <view class="h5-sw-photo-actions">
          <button :disabled="uploading" @click="choosePhoto('camera')">{{ uploading ? '上传中…' : '拍照' }}</button>
          <button :disabled="uploading" @click="choosePhoto('album')">从相册选择</button>
        </view>
        <view class="h5-sw-field">
          <text>物料编号</text>
          <input :value="form.product_code" maxlength="50" placeholder="如 SP-001" @input="onFormText('product_code', $event)" />
        </view>
        <view class="h5-sw-field">
          <text>名称</text>
          <input :value="form.name" maxlength="100" placeholder="物料名称" @input="onFormText('name', $event)" />
        </view>
        <view class="h5-sw-field" @click="openSheet('category')">
          <text>分类</text>
          <strong :class="{ need: !form.category_id }">{{ optionName(categories, form.category_id) || '选填' }}</strong>
          <text class="h5-sw-chev">›</text>
        </view>
        <view class="h5-sw-field" @click="openSheet('color')">
          <text>颜色</text>
          <strong :class="{ need: !form.color_id }">{{ optionName(colors, form.color_id) || '选填' }}</strong>
          <text class="h5-sw-chev">›</text>
        </view>
        <view class="h5-sw-field">
          <text>单价</text>
          <input :value="form.unit_price" type="digit" placeholder="0.00" @input="onFormText('unit_price', $event)" />
        </view>
        <view class="h5-sw-field" @click="openSheet('unit')">
          <text>计价单位</text>
          <strong :class="{ need: !form.pricing_unit_id }">{{ optionName(units, form.pricing_unit_id) || '选填' }}</strong>
          <text class="h5-sw-chev">›</text>
        </view>
        <view class="h5-sw-field" @click="openSheet('supplier')">
          <text>供应商</text>
          <strong :class="{ need: !form.partner_id }">{{ optionName(suppliers, form.partner_id) || '请选择' }}</strong>
          <text class="h5-sw-chev">›</text>
        </view>
        <text v-if="!form.id && !canApprove" class="h5-sw-note">保存后进入待审批，通过后才能被选用和购买。</text>
        <text v-else-if="!form.id && canApprove" class="h5-sw-note">你有审批权，保存后直接通过。</text>
      </view>
      <view class="cut-sticky-bar h5-sw-bar">
        <button class="h5-sw-ghost" @click="cancelForm">取消</button>
        <button class="primary-button h5-sw-primary" :loading="saving" @click="saveForm()">保存</button>
      </view>
    </template>

    <template v-else-if="mode === 'buy'">
      <text class="h5-sw-back" @click="mode = 'list'">‹ 返回勾选</text>
      <text class="h5-sw-note h5-sw-note--page">按供应商拆成采购草稿。鞋底、垫脚可改成按码数，入库进对应码。</text>
      <view v-for="line in buyLines" :key="line.supplier_product_id" class="card h5-sw-buy">
        <view class="h5-sw-buy__head">
          <view>
            <strong>{{ line.product_code }}</strong>
            <text>{{ line.name || '—' }} · {{ line.partner_name || '—' }}</text>
          </view>
          <text class="danger" @click="removeBuyLine(line.supplier_product_id)">移除</text>
        </view>
        <view class="h5-sw-buy__switch">
          <text :class="{ on: !line.by_size }" @click="line.by_size = false">按总量</text>
          <text :class="{ on: line.by_size }" @click="line.by_size = true">按码数</text>
        </view>
        <view v-if="!line.by_size" class="h5-sw-buy__qty">
          <input :value="line.qty" type="digit" placeholder="数量" @input="onBuyQty(line, $event)" />
          <text>{{ line.pricing_unit_name || '单位' }}</text>
        </view>
        <view v-else class="h5-sw-sizes">
          <view v-for="size in line.sizeQtys" :key="size.size_id" class="h5-sw-size">
            <text>{{ size.size_value }}</text>
            <input :value="size.qty" type="number" placeholder="0" @input="onSizeQty(size, $event)" />
          </view>
          <text v-if="!line.sizeQtys.length" class="h5-sw-note">暂无启用码数</text>
        </view>
      </view>
      <view class="cut-sticky-bar h5-sw-bar">
        <view class="h5-sw-buy__sum"><text>{{ buySupplierCount }} 家供应商</text><strong>约 ¥{{ priceText(buyEstimate) }}</strong></view>
        <button class="primary-button h5-sw-primary" :loading="buying" :disabled="!buyLines.length" @click="submitBuy">生成采购草稿</button>
      </view>
    </template>

    <view v-if="sheet" class="h5-sw-mask" @click="closeSheet">
      <view class="h5-sw-sheet" @click.stop>
        <view class="h5-sw-sheet__head">
          <text>{{ sheetTitle }}</text>
          <text @click="closeSheet">关闭</text>
        </view>
        <input v-if="sheet !== 'segment'" class="h5-sw-sheet__search" :value="sheetQuery" placeholder="搜索" @input="onSheetQuery" />
        <view v-if="sheetCanCreate" class="h5-sw-create">
          <input :value="createName" :placeholder="createPlaceholder" maxlength="40" @input="onCreateName" />
          <text @click="createMaster">添加</text>
        </view>
        <view v-if="sheet === 'category'" class="h5-sw-segment" @click="openSegmentSheet">
          <text>默认消耗工序段</text>
          <strong>{{ segmentName }}</strong>
        </view>
        <scroll-view scroll-y class="h5-sw-sheet__list">
          <view v-for="option in sheetOptions" :key="option.key" class="h5-sw-option" @click="pickOption(option)">
            <text>{{ option.label }}</text>
            <text v-if="option.picked">已选</text>
          </view>
          <view v-if="!sheetOptions.length" class="h5-sw-sheet__empty">没有可选项</view>
        </scroll-view>
      </view>
    </view>

    <view v-if="supplierOpen" class="h5-sw-mask" @click="supplierOpen = false">
      <view class="h5-sw-sheet" @click.stop>
        <view class="h5-sw-sheet__head">
          <text>{{ supplierDetail?.name || '供应商' }}</text>
          <text @click="supplierOpen = false">关闭</text>
        </view>
        <view v-if="supplierLoading" class="h5-sw-sheet__empty">加载中…</view>
        <view v-else-if="supplierDetail" class="h5-sw-supplier">
          <text v-if="supplierDetail.address">{{ supplierDetail.address }}</text>
          <text v-if="!supplierContacts.length && !supplierDetail.address">还没有联系人和地址</text>
          <view v-for="person in supplierContacts" :key="person.id" class="h5-sw-supplier__person">
            <strong>{{ person.name }}{{ person.is_primary ? ' · 主要' : '' }}</strong>
            <text>{{ [person.title, person.mobile, person.wechat].filter(Boolean).join(' · ') || '无电话' }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { onBackPress, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { del, get, patch, post, uploadFile } from '../../services/http'
import { getProfile } from '../../services/storage'

type SheetKind = 'supplier-filter' | 'category' | 'color' | 'unit' | 'supplier' | 'segment'
type Named = { id: number; name: string; is_active?: boolean }
type BuySize = { size_id: number; size_value: string; qty: string }
type BuyLine = {
  supplier_product_id: number
  product_code: string
  name: string
  partner_name: string
  unit_price: number | null
  pricing_unit_name: string
  by_size: boolean
  qty: string
  sizeQtys: BuySize[]
}

const profile = ref(getProfile())
const mode = ref<'list' | 'detail' | 'form' | 'buy'>('list')
const keyword = ref('')
const categoryId = ref<number | null>(null)
const partnerId = ref<number | null>(null)
const approval = ref('')
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const selecting = ref(false)
const picked = ref<Record<number, any>>({})
const current = ref<any>(null)
const suppliers = ref<Named[]>([])
const categories = ref<Named[]>([])
const colors = ref<Named[]>([])
const units = ref<Named[]>([])
const segments = ref<Named[]>([])
const sizes = ref<any[]>([])
const sheet = ref<SheetKind | null>(null)
const sheetQuery = ref('')
const createName = ref('')
const newSegmentId = ref<number | null>(null)
const saving = ref(false)
const uploading = ref(false)
const buying = ref(false)
const buyLines = ref<BuyLine[]>([])
const supplierOpen = ref(false)
const supplierLoading = ref(false)
const supplierDetail = ref<any>(null)
const form = reactive({
  id: null as number | null,
  product_code: '',
  name: '',
  category_id: null as number | null,
  color_id: null as number | null,
  pricing_unit_id: null as number | null,
  partner_id: null as number | null,
  unit_price: '',
  image_url: '',
})

const approvalTabs = [
  { label: '全部', value: '' },
  { label: '待审批', value: 'pending' },
  { label: '已通过', value: 'approved' },
]
let keywordTimer: ReturnType<typeof setTimeout> | null = null
let listSeq = 0
let mastersLoaded = false
let listLoaded = false

const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.some(code => ['supplier_products', 'supplier_products_write', 'supplier_products_approve'].includes(code)))
const canWrite = computed(() => features.value.includes('supplier_products_write'))
const canApprove = computed(() => features.value.includes('supplier_products_approve'))
const canBuy = computed(() => ['admin', 'manager', 'leader'].includes(profile.value?.role || ''))
const pickedCount = computed(() => Object.keys(picked.value).length)
const finished = computed(() => rows.value.length >= total.value && total.value > 0)
const supplierFilterLabel = computed(() => suppliers.value.find(item => item.id === partnerId.value)?.name || '供应商')
const activeSizes = computed(() => sizes.value.filter(item => item.is_active !== false).sort((a, b) => String(a.size_value).localeCompare(String(b.size_value), 'zh-CN', { numeric: true })))
const buySupplierCount = computed(() => new Set(buyLines.value.map(line => line.partner_name).filter(Boolean)).size)
const buyEstimate = computed(() => buyLines.value.reduce((sum, line) => sum + Number(line.unit_price || 0) * lineQty(line), 0))
const canApproveCurrent = computed(() => canApprove.value && current.value?.approval_status === 'pending')
const canEditCurrent = computed(() => {
  const row = current.value
  if (!row?.id) return false
  if (row.approval_status === 'approved') return canApprove.value
  return canWrite.value || canApprove.value
})
const canDeleteCurrent = computed(() => canWrite.value && current.value?.approval_status !== 'approved')
const supplierContacts = computed(() => (supplierDetail.value?.contacts || []).filter((item: any) => item.is_active !== false))
const sheetTitle = computed(() => ({
  'supplier-filter': '供应商',
  category: '分类',
  color: '颜色',
  unit: '计价单位',
  supplier: '供应商',
  segment: '默认消耗工序段',
}[sheet.value || 'category']))
const sheetCanCreate = computed(() => ['category', 'color', 'unit', 'supplier'].includes(sheet.value || ''))
const createPlaceholder = computed(() => ({ category: '新分类，如皮料', color: '新颜色，如卡其', unit: '新单位，如码', supplier: '新供应商名称' }[sheet.value || ''] || '名称'))
const segmentName = computed(() => segments.value.find(item => item.id === newSegmentId.value)?.name || '未标注')
const sheetOptions = computed(() => {
  const query = sheetQuery.value.trim().toLowerCase()
  const match = (label: string) => !query || label.toLowerCase().includes(query)
  if (sheet.value === 'supplier-filter') {
    return [{ key: 'all', id: null, label: '全部供应商', picked: !partnerId.value }].concat(
      suppliers.value.filter(item => match(item.name)).map(item => ({ key: String(item.id), id: item.id, label: item.name, picked: partnerId.value === item.id })),
    )
  }
  if (sheet.value === 'segment') {
    return [{ key: 'none', id: null, label: '未标注（算首段）', picked: !newSegmentId.value }].concat(
      segments.value.filter(item => match(item.name)).map(item => ({ key: String(item.id), id: item.id, label: item.name, picked: newSegmentId.value === item.id })),
    )
  }
  const source = sheet.value === 'category' ? categories.value : sheet.value === 'color' ? colors.value : sheet.value === 'unit' ? units.value : suppliers.value
  const selected = sheet.value === 'category' ? form.category_id : sheet.value === 'color' ? form.color_id : sheet.value === 'unit' ? form.pricing_unit_id : form.partner_id
  const options = source.filter(item => match(item.name)).map(item => ({ key: String(item.id), id: item.id, label: item.name, picked: selected === item.id }))
  if (sheet.value === 'supplier') return options
  return [{ key: 'none', id: null, label: '不选', picked: !selected }].concat(options)
})

function inputValue(event: any) {
  return String(event?.detail?.value ?? event?.target?.value ?? '')
}
function priceText(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isNaN(number) ? '—' : number.toFixed(2)
}
function timeText(value?: string) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}
function approvalText(row: any) {
  return row?.approval_status === 'pending' ? '待审批' : '已通过'
}
function swatchText(row: any) {
  return String(row?.color_name || row?.name || row?.product_code || '料').trim().slice(0, 1)
}
function cardMeta(row: any) {
  return [row.product_code, row.color_name, row.category_name, row.pricing_unit_name].filter(Boolean).join(' · ')
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function optionName(list: Named[], id: number | null) {
  return list.find(item => item.id === id)?.name || ''
}
function activeNamed(items: any[]) {
  return (items || []).filter(item => item?.is_active !== false && item?.id)
}
function ask(title: string, content: string) {
  return new Promise<boolean>(resolve => {
    uni.showModal({ title, content, success: result => resolve(!!result.confirm) })
  })
}
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}

async function loadMasters() {
  const [supplierRes, colorRes, categoryRes, unitRes, segmentRes, sizeRes]: any[] = await Promise.all([
    get('/partners', { role: 'supplier', active_only: true, page: 1, page_size: 500 }),
    get('/colors'),
    get('/material-categories', { active_only: true }),
    get('/pricing-units', { active_only: true }),
    get('/process-segments', { active_only: true }).catch(() => ({ items: [] })),
    get('/sizes'),
  ])
  suppliers.value = activeNamed(supplierRes?.items || [])
  colors.value = activeNamed(colorRes?.items || [])
  categories.value = activeNamed(categoryRes?.items || [])
  units.value = activeNamed(unitRes?.items || [])
  segments.value = activeNamed(segmentRes?.items || [])
  sizes.value = sizeRes?.items || []
  mastersLoaded = true
}

async function loadList(reset = false) {
  if (!canSee.value) return
  if (!reset && (loading.value || loadingMore.value || (listLoaded && rows.value.length >= total.value))) return
  const seq = reset ? ++listSeq : listSeq
  if (reset) {
    page.value = 1
    loading.value = true
  } else {
    loadingMore.value = true
  }
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: 20, sort_by: 'created_at', sort_order: 'desc' }
    const text = keyword.value.trim()
    if (text) params.keyword = text
    if (categoryId.value) params.category_id = categoryId.value
    if (partnerId.value) params.partner_id = partnerId.value
    if (approval.value) params.approval_status = approval.value
    const result: any = await get('/supplier-products', params)
    if (seq !== listSeq) return
    const items = result?.items || []
    rows.value = reset ? items : rows.value.concat(items)
    total.value = Number(result?.total || 0)
    listLoaded = true
    if (items.length) page.value += 1
  } catch (error: any) {
    if (seq === listSeq) toast(error?.message || '色卡加载失败')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
      uni.stopPullDownRefresh()
    }
  }
}

function reload() {
  void loadList(true)
}
function onKeyword(event: any) {
  keyword.value = inputValue(event)
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(reload, 300)
}
function clearKeyword() {
  keyword.value = ''
  reload()
}
function setCategory(id: number | null) {
  categoryId.value = id
  reload()
}
function setApproval(value: string) {
  approval.value = value
  reload()
}
function onCard(row: any) {
  if (selecting.value) {
    if (row.approval_status !== 'approved') {
      toast('未审批通过，不能购买')
      return
    }
    const next = { ...picked.value }
    if (next[row.id]) delete next[row.id]
    else next[row.id] = row
    picked.value = next
    return
  }
  current.value = row
  mode.value = 'detail'
}
function backToList() {
  mode.value = 'list'
  current.value = null
}
function startSelect() {
  selecting.value = true
  picked.value = {}
}
function cancelSelect() {
  selecting.value = false
  picked.value = {}
}

function blankForm() {
  form.id = null
  form.product_code = ''
  form.name = ''
  form.category_id = categoryId.value
  form.color_id = null
  form.pricing_unit_id = null
  form.partner_id = partnerId.value
  form.unit_price = ''
  form.image_url = ''
}
function rememberOption(list: Named[], id: number | null, name?: string) {
  if (!id || list.some(item => item.id === id)) return
  list.push({ id, name: name || `#${id}` })
}
function openCreate() {
  if (!canWrite.value) return
  blankForm()
  mode.value = 'form'
}
function openEdit(row: any) {
  if (row.approval_status === 'approved' && !canApprove.value) {
    toast('已审批通过，不能修改')
    return
  }
  rememberOption(categories.value, row.category_id, row.category_name)
  rememberOption(colors.value, row.color_id, row.color_name)
  rememberOption(units.value, row.pricing_unit_id, row.pricing_unit_name)
  rememberOption(suppliers.value, row.partner_id, row.partner_name)
  form.id = row.id
  form.product_code = row.product_code || ''
  form.name = row.name || ''
  form.category_id = row.category_id ?? null
  form.color_id = row.color_id ?? null
  form.pricing_unit_id = row.pricing_unit_id ?? null
  form.partner_id = row.partner_id ?? null
  form.unit_price = row.unit_price == null ? '' : String(row.unit_price)
  form.image_url = row.image_url || ''
  mode.value = 'form'
}
function cancelForm() {
  mode.value = current.value?.id === form.id && form.id ? 'detail' : 'list'
}
function onFormText(key: 'product_code' | 'name' | 'unit_price', event: any) {
  form[key] = inputValue(event)
}
function choosePhoto(source: 'camera' | 'album') {
  if (uploading.value) return
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: [source],
    success: async result => {
      const filePath = result.tempFilePaths?.[0]
      if (!filePath) return
      uploading.value = true
      try {
        const uploaded: any = await uploadFile('/supplier-products/upload', filePath)
        form.image_url = uploaded?.url || ''
        toast('图片已上传')
      } catch (error: any) {
        toast(error?.message || '图片上传失败')
      } finally {
        uploading.value = false
      }
    },
  })
}

function payload(confirmDuplicate = false) {
  const price = form.unit_price.trim()
  return {
    product_code: form.product_code.trim(),
    name: form.name.trim() || null,
    category_id: form.category_id || null,
    color_id: form.color_id || null,
    pricing_unit_id: form.pricing_unit_id || null,
    partner_id: form.partner_id,
    unit_price: price === '' ? null : Number(price),
    image_url: form.image_url || null,
    confirm_duplicate: confirmDuplicate,
  }
}
async function saveForm() {
  if (!form.product_code.trim()) {
    toast('请填写物料编号')
    return
  }
  if (!form.partner_id) {
    toast('请选择供应商')
    return
  }
  let confirmDuplicate = false
  saving.value = true
  try {
    let saved: any = null
    for (;;) {
      try {
        saved = form.id
          ? await patch(`/supplier-products/${form.id}`, payload(confirmDuplicate))
          : await post('/supplier-products', payload(confirmDuplicate))
        break
      } catch (error: any) {
        const duplicate = !confirmDuplicate && (error?.statusCode === 409 || String(error?.message || '').includes('已存在'))
        if (!duplicate) {
          toast(error?.message || '保存失败')
          return
        }
        saving.value = false
        const agreed = await ask('编号重复', error?.message || `编号「${form.product_code.trim()}」已存在，确认仍要保存？`)
        if (!agreed) return
        confirmDuplicate = true
        saving.value = true
      }
    }
    toast(saved?.approval_status === 'pending' ? '已保存，审批通过后才能使用' : '已保存')
    current.value = { ...(current.value || {}), ...saved }
    mode.value = 'list'
    await loadList(true)
  } finally {
    saving.value = false
  }
}

async function approveCurrent() {
  const row = current.value
  if (!row?.id) return
  if (!(await ask('审批色卡', `通过「${row.product_code}」？通过后才能被选用。`))) return
  try {
    const saved: any = await post(`/supplier-products/${row.id}/approve`, {})
    current.value = { ...row, ...saved, approval_status: 'approved' }
    toast('已审批通过')
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '审批失败')
  }
}
async function removeCurrent() {
  const row = current.value
  if (!row?.id) return
  if (!(await ask('删除物料', `删除「${row.product_code}」？`))) return
  try {
    await del(`/supplier-products/${row.id}`)
    toast('已删除')
    backToList()
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '删除失败')
  }
}
function openLabel(row: any) {
  const code = encodeURIComponent(String(row?.product_code || ''))
  if (!code) return
  uni.navigateTo({ url: `/pages/material-label/index?code=${code}` })
}
async function openSupplier() {
  const id = current.value?.partner_id
  if (!id) return
  supplierOpen.value = true
  supplierLoading.value = true
  supplierDetail.value = null
  try {
    supplierDetail.value = await get(`/partners/${id}`)
  } catch (error: any) {
    toast(error?.message || '供应商加载失败')
    supplierOpen.value = false
  } finally {
    supplierLoading.value = false
  }
}

function openSheet(kind: SheetKind) {
  sheet.value = kind
  sheetQuery.value = ''
  createName.value = ''
}
function openSegmentSheet() {
  sheetQuery.value = ''
  sheet.value = 'segment'
}
function closeSheet() {
  sheet.value = null
}
function onSheetQuery(event: any) {
  sheetQuery.value = inputValue(event)
}
function onCreateName(event: any) {
  createName.value = inputValue(event)
}
function pickOption(option: { id: number | null }) {
  if (sheet.value === 'supplier-filter') {
    partnerId.value = option.id
    closeSheet()
    reload()
    return
  }
  if (sheet.value === 'segment') {
    newSegmentId.value = option.id
    sheet.value = 'category'
    return
  }
  if (sheet.value === 'category') form.category_id = option.id
  else if (sheet.value === 'color') form.color_id = option.id
  else if (sheet.value === 'unit') form.pricing_unit_id = option.id
  else if (sheet.value === 'supplier') form.partner_id = option.id
  closeSheet()
}
async function createMaster() {
  const name = createName.value.trim()
  if (!name) {
    toast('请填写名称')
    return
  }
  try {
    if (sheet.value === 'category') {
      const created: any = await post('/material-categories', {
        name,
        sort_order: categories.value.length,
        is_active: true,
        default_consume_segment_id: newSegmentId.value,
      })
      if (!categories.value.some(item => item.id === created.id)) categories.value.push(created)
      form.category_id = created.id
      newSegmentId.value = null
    } else if (sheet.value === 'color') {
      const created: any = await post('/colors', { name })
      if (!colors.value.some(item => item.id === created.id)) colors.value.push(created)
      form.color_id = created.id
    } else if (sheet.value === 'unit') {
      const created: any = await post('/pricing-units', { name, sort_order: units.value.length, is_active: true })
      if (!units.value.some(item => item.id === created.id)) units.value.push(created)
      form.pricing_unit_id = created.id
    } else if (sheet.value === 'supplier') {
      const created: any = await post('/partners', { name, is_supplier: true, is_customer: false, is_brand: false, is_subcontractor: false })
      if (!suppliers.value.some(item => item.id === created.id)) suppliers.value.push(created)
      form.partner_id = created.id
    }
    createName.value = ''
    closeSheet()
    toast(`已添加「${name}」`)
  } catch (error: any) {
    toast(error?.message || '添加失败')
  }
}

function lineQty(line: BuyLine) {
  if (!line.by_size) return Number(line.qty || 0)
  return line.sizeQtys.reduce((sum, size) => sum + Number(size.qty || 0), 0)
}
function openBuy() {
  const selected = Object.values(picked.value)
  if (!selected.length) {
    toast('请先勾选已通过的色卡')
    return
  }
  buyLines.value = selected.map(row => ({
    supplier_product_id: row.id,
    product_code: row.product_code,
    name: row.name || '',
    partner_name: row.partner_name || '',
    unit_price: row.unit_price == null ? null : Number(row.unit_price),
    pricing_unit_name: row.pricing_unit_name || '',
    by_size: false,
    qty: '',
    sizeQtys: activeSizes.value.map(size => ({ size_id: size.id, size_value: size.size_value, qty: '' })),
  }))
  mode.value = 'buy'
}
function removeBuyLine(id: number) {
  buyLines.value = buyLines.value.filter(line => line.supplier_product_id !== id)
  const next = { ...picked.value }
  delete next[id]
  picked.value = next
  if (!buyLines.value.length) mode.value = 'list'
}
function onBuyQty(line: BuyLine, event: any) {
  line.qty = inputValue(event)
}
function onSizeQty(size: BuySize, event: any) {
  size.qty = inputValue(event)
}
async function submitBuy() {
  const lines: { supplier_product_id: number; qty: number; size_id?: number }[] = []
  for (const line of buyLines.value) {
    if (line.by_size) {
      for (const size of line.sizeQtys) {
        const qty = Number(size.qty || 0)
        if (qty > 0) lines.push({ supplier_product_id: line.supplier_product_id, qty, size_id: size.size_id })
      }
    } else if (Number(line.qty || 0) > 0) {
      lines.push({ supplier_product_id: line.supplier_product_id, qty: Number(line.qty) })
    }
  }
  if (!lines.length) {
    toast('请填写采购数量')
    return
  }
  buying.value = true
  try {
    const created: any[] = await post('/purchase-orders/from-catalog', { lines })
    const nos = (created || []).map(item => item.po_no).filter(Boolean)
    toast(nos.length ? `已生成 ${nos.length} 张采购草稿` : '已生成采购草稿')
    cancelSelect()
    mode.value = 'list'
  } catch (error: any) {
    toast(error?.message || '生成失败')
  } finally {
    buying.value = false
  }
}

onBackPress(() => {
  if (mode.value !== 'form') return false
  cancelForm()
  return true
})
onReachBottom(() => {
  if (mode.value === 'list') void loadList(false)
})
onPullDownRefresh(() => {
  if (mode.value === 'list') void loadList(true)
  else uni.stopPullDownRefresh()
})
onShow(async () => {
  profile.value = getProfile()
  if (!canSee.value) return
  if (!mastersLoaded) {
    try { await loadMasters() } catch (error: any) { toast(error?.message || '基础资料加载失败') }
  }
  if (mode.value === 'list' && !rows.value.length) void loadList(true)
})
</script>

<style scoped lang="scss">
.h5-sw-search,
.h5-sw-card,
.h5-sw-hero,
.h5-sw-facts,
.h5-sw-history,
.h5-sw-form,
.h5-sw-buy {
  margin-bottom: 16rpx;
}
.h5-sw-search {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 8rpx 8rpx 8rpx 24rpx;
}
.h5-sw-search input,
.h5-sw-field input,
.h5-sw-sheet__search,
.h5-sw-create input,
.h5-sw-buy__qty input,
.h5-sw-size input {
  min-width: 0;
  height: 72rpx;
  color: #181b23;
  font-size: 28rpx;
}
.h5-sw-search input { flex: 1; }
.h5-sw-search > text,
.h5-sw-sheet__head text:last-child,
.h5-sw-create > text,
.h5-sw-back,
.danger { color: #0057c2; font-size: 26rpx; }
.danger { color: #ba1a1a; }
.h5-sw-back { display: block; margin: 4rpx 0 16rpx; font-size: 28rpx; font-weight: 700; }
.h5-sw-cats { width: 100%; margin: 8rpx 0 12rpx; white-space: nowrap; }
.h5-sw-cats text,
.h5-sw-filters text,
.h5-sw-buy__switch text {
  display: inline-flex;
  align-items: center;
  height: 60rpx;
  margin-right: 12rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: #fff;
  color: #414755;
  font-size: 24rpx;
}
.h5-sw-cats text.on,
.h5-sw-filters text.on,
.h5-sw-buy__switch text.on { background: rgba(0, 87, 194, 0.12); color: #0057c2; font-weight: 700; }
.h5-sw-filters { display: flex; align-items: center; margin-bottom: 16rpx; overflow: hidden; }
.h5-sw-filters__supplier { max-width: 220rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h5-sw-card { display: flex; gap: 16rpx; padding: 18rpx; }
.h5-sw-card.is-picked { box-shadow: inset 0 0 0 2rpx #0057c2; }
.h5-sw-card.is-locked { opacity: 0.45; }
.h5-sw-check { width: 32rpx; height: 32rpx; margin-top: 28rpx; border: 2rpx solid #c1c6d7; border-radius: 50%; }
.h5-sw-check.on { border-color: #0057c2; background: #0057c2; box-shadow: inset 0 0 0 6rpx #fff; }
.h5-sw-thumb { display: flex; flex: 0 0 112rpx; align-items: center; justify-content: center; width: 112rpx; height: 112rpx; border-radius: 20rpx; background: #f5f7fa; color: #414755; font-size: 36rpx; font-weight: 750; }
.h5-sw-card__body { flex: 1; min-width: 0; }
.h5-sw-card__top,
.h5-sw-card__foot,
.h5-sw-fact,
.h5-sw-field,
.h5-sw-buy__head,
.h5-sw-history__line { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-sw-card__top strong,
.h5-sw-hero__copy strong,
.h5-sw-buy__head strong { overflow: hidden; color: #181b23; font-size: 30rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-sw-card__top > text { flex-shrink: 0; color: #181b23; font-size: 28rpx; font-weight: 750; }
.h5-sw-card__meta,
.h5-sw-card__foot,
.h5-sw-hero__copy text,
.h5-sw-buy__head text,
.h5-sw-history__line text { color: #414755; font-size: 22rpx; }
.h5-sw-card__meta { display: block; margin: 8rpx 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h5-sw-more,
.h5-sw-note,
.h5-sw-sheet__empty { color: #414755; font-size: 24rpx; text-align: center; }
.h5-sw-more { padding: 12rpx 0 24rpx; }
.h5-sw-note { display: block; padding: 8rpx 8rpx 20rpx; text-align: left; }
.h5-sw-note--page { margin-bottom: 12rpx; }
.h5-sw-hero { display: flex; gap: 20rpx; padding: 20rpx; }
.h5-sw-hero image,
.h5-sw-hero__empty,
.h5-sw-photo image { width: 180rpx; height: 180rpx; border-radius: 24rpx; background: #f5f7fa; }
.h5-sw-hero__empty,
.h5-sw-photo { display: flex; align-items: center; justify-content: center; color: #414755; }
.h5-sw-hero__copy { display: flex; flex: 1; flex-direction: column; align-items: flex-start; gap: 10rpx; min-width: 0; }
.h5-sw-facts,
.h5-sw-history,
.h5-sw-form,
.h5-sw-buy,
.h5-sw-supplier { padding: 8rpx 24rpx; }
.h5-sw-fact,
.h5-sw-field { min-height: 88rpx; border-bottom: 1rpx solid #e0e2ed; }
.h5-sw-fact:last-child,
.h5-sw-field:last-of-type { border-bottom: 0; }
.h5-sw-fact text,
.h5-sw-field > text:first-child { flex: 0 0 140rpx; color: #414755; font-size: 26rpx; }
.h5-sw-fact strong,
.h5-sw-field strong,
.h5-sw-field input { flex: 1; color: #181b23; font-size: 28rpx; font-weight: 650; text-align: right; }
.h5-sw-field strong.need,
.h5-sw-chev { color: #727786; font-weight: 500; }
.h5-sw-history__title { display: block; padding: 18rpx 0 8rpx; color: #181b23; font-size: 26rpx; font-weight: 750; }
.h5-sw-history__line { padding: 14rpx 0; border-top: 1rpx solid #e0e2ed; }
.h5-sw-history__line strong { color: #181b23; font-size: 24rpx; text-align: right; }
.h5-sw-photo { position: relative; height: 220rpx; margin: 20rpx 0 0; border-radius: 24rpx; background: #f5f7fa; }
.h5-sw-photo image { width: 100%; height: 220rpx; }
.h5-sw-photo__clear { position: absolute; top: 12rpx; right: 12rpx; padding: 8rpx 16rpx; border-radius: 999rpx; background: rgba(255, 255, 255, 0.92); }
.h5-sw-photo-actions { display: flex; gap: 12rpx; margin: 20rpx 0 8rpx; }
.h5-sw-photo-actions button { flex: 1; height: 80rpx; margin: 0; border: 0; border-radius: 16rpx; background: #f5f7fa; color: #181b23; font-size: 28rpx; font-weight: 700; line-height: 80rpx; }
.h5-sw-photo-actions button::after { border: 0; }
.h5-sw-photo-actions button[disabled] { color: #727786; }
.h5-sw-bar { display: flex; align-items: center; gap: 12rpx; }
.h5-sw-ghost,
.h5-sw-primary { flex: 1; height: 84rpx; margin: 0; border-radius: 16rpx; font-size: 28rpx; font-weight: 750; line-height: 84rpx; }
.h5-sw-ghost { border: 0; background: #f5f7fa; color: #181b23; }
.h5-sw-ghost--ok { color: #266d00; }
.h5-sw-ghost--danger { color: #ba1a1a; }
.h5-sw-ghost::after,
.h5-sw-primary::after { border: 0; }
.h5-sw-primary { margin-top: 0; }
.h5-sw-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.9); }
.h5-sw-mask { position: fixed; z-index: 80; inset: 0; background: rgba(24, 27, 35, 0.38); }
.h5-sw-sheet { position: absolute; right: 0; bottom: 0; left: 0; max-height: 78vh; padding: 12rpx 28rpx calc(24rpx + env(safe-area-inset-bottom)); border-radius: 28rpx 28rpx 0 0; background: #fff; }
.h5-sw-sheet__head { display: flex; align-items: center; justify-content: space-between; height: 80rpx; color: #181b23; font-size: 30rpx; font-weight: 750; }
.h5-sw-sheet__search,
.h5-sw-create input { box-sizing: border-box; width: 100%; padding: 0 20rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-sw-create { display: flex; gap: 12rpx; align-items: center; margin-top: 12rpx; }
.h5-sw-create input { flex: 1; }
.h5-sw-create > text { flex: 0 0 auto; font-weight: 750; }
.h5-sw-segment { display: flex; align-items: center; justify-content: space-between; min-height: 72rpx; margin-top: 8rpx; color: #414755; font-size: 24rpx; }
.h5-sw-segment strong { color: #181b23; font-weight: 650; }
.h5-sw-sheet__list { max-height: 52vh; margin-top: 8rpx; }
.h5-sw-option { display: flex; align-items: center; justify-content: space-between; min-height: 84rpx; border-bottom: 1rpx solid #e0e2ed; color: #181b23; font-size: 28rpx; }
.h5-sw-option text:last-child { color: #0057c2; font-size: 22rpx; }
.h5-sw-buy__head { padding-top: 16rpx; }
.h5-sw-buy__head text,
.h5-sw-supplier text { display: block; margin-top: 6rpx; color: #414755; font-size: 22rpx; }
.h5-sw-buy__switch { display: flex; margin: 16rpx 0; }
.h5-sw-buy__qty { display: flex; align-items: center; gap: 12rpx; margin-bottom: 16rpx; }
.h5-sw-buy__qty input,
.h5-sw-size input { flex: 1; padding: 0 16rpx; border-radius: 14rpx; background: #f5f7fa; text-align: right; }
.h5-sw-sizes { display: flex; flex-wrap: wrap; gap: 12rpx; padding-bottom: 16rpx; }
.h5-sw-size { width: calc((100% - 36rpx) / 4); }
.h5-sw-size text { display: block; margin-bottom: 6rpx; color: #414755; font-size: 22rpx; text-align: center; }
.h5-sw-buy__sum { flex: 0 0 210rpx; }
.h5-sw-buy__sum text { display: block; color: #414755; font-size: 20rpx; }
.h5-sw-buy__sum strong { color: #181b23; font-size: 28rpx; }
.h5-sw-supplier { padding-top: 12rpx; padding-bottom: 28rpx; }
.h5-sw-supplier__person { padding: 16rpx 0; border-top: 1rpx solid #e0e2ed; }
.h5-sw-supplier__person strong { color: #181b23; font-size: 28rpx; }
.h5-sw--sub { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
</style>
