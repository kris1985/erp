<template>
  <app-nav-bar />
  <view class="page h5-prog" :class="{ 'h5-prog--sub': mode === 'detail' }">
    <template v-if="mode === 'list'">
      <view class="card h5-prog-search">
        <input :value="keyword" confirm-type="search" placeholder="搜生产单号、客户、型号" @input="onKeyword" @confirm="reload" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>
      <scroll-view class="h5-prog-tabs" scroll-x :show-scrollbar="false">
        <text v-for="item in statuses" :key="item.value" :class="{ on: status === item.value }" @click="selectStatus(item.value)">{{ item.label }}</text>
      </scroll-view>

      <view v-if="loading && !rows.length" class="h5-prog-empty">正在加载生产进度…</view>
      <view v-else-if="!rows.length" class="h5-prog-empty">{{ keyword ? '没有匹配的生产单' : '没有生产单' }}</view>
      <view v-for="row in rows" :key="row.id" class="card h5-prog-card" @click="openFlow(row)">
        <view class="h5-prog-card__row">
          <image v-if="row.product_image_url" class="h5-prog-thumb" :src="displayImageUrl(row.product_image_url)" mode="aspectFill" />
          <view v-else class="h5-prog-thumb h5-prog-thumb--empty">款</view>
          <view class="h5-prog-card__main">
            <view class="h5-prog-card__top">
              <strong>{{ row.header_no }}</strong>
              <view class="h5-prog-card__badges">
                <text v-if="row.warehouse_status" :class="['h5-chip', warehouseClass(row.warehouse_status)]">{{ row.warehouse_status }}</text>
                <text :class="['h5-prog-status', `is-${row.status}`]">{{ statusLabel(row.status) }}</text>
              </view>
            </view>
            <text class="h5-prog-meta">{{ row.customer_name }}</text>
            <text class="h5-prog-meta">{{ row.product_code || '—' }}<text v-if="row.color_name"> · {{ row.color_name }}</text></text>
            <view v-if="row.is_rush || showRiskLabel(row)" class="h5-prog-tags">
              <text v-if="row.is_rush" class="h5-chip h5-chip--bad">急单</text>
              <text v-if="showRiskLabel(row)" class="h5-chip h5-chip--warn">{{ row.risk_label }}</text>
            </view>
          </view>
        </view>
        <view class="h5-prog-stats">
          <view><text>数量</text><strong>{{ row.total_qty || 0 }}</strong></view>
          <view><text>已出货</text><strong>{{ row.shipped_qty || 0 }}</strong></view>
          <view><text>交货日期</text><strong>{{ dateText(row.delivery_date) }}</strong></view>
          <view><text>预计交货日期</text><strong>{{ dateText(row.projected_finish) }}</strong></view>
        </view>
        <view class="h5-prog-segs">
          <view v-for="(segment, index) in segmentBars(row)" :key="`${row.id}-${segment.id}-${index}`" class="h5-prog-seg" :class="{ current: segment.current, done: segment.doneAll }">
            <text class="h5-prog-seg__name">{{ segment.name }}</text>
            <view class="h5-prog-seg__meter">
              <text class="h5-prog-seg__done">{{ pairText(segment.done) }}</text>
              <view class="h5-prog-seg__track"><view :style="{ width: `${segment.percent}%` }" /></view>
              <text class="h5-prog-seg__plan">{{ pairText(segment.plan) }}</text>
            </view>
          </view>
          <text v-if="!segmentBars(row).length" class="h5-prog-seg__empty">还没有工序段</text>
        </view>
      </view>
      <view v-if="rows.length" class="h5-prog-more">{{ finished ? `共 ${total} 单` : loadingMore ? '加载中…' : '上拉加载更多' }}</view>
    </template>

    <template v-else-if="current">
      <view class="card h5-sheet-hero">
        <view class="h5-sheet-hero__top">
          <image v-if="current.product_image_url" :src="displayImageUrl(current.product_image_url)" mode="aspectFill" @click="previewImage(current.product_image_url)" />
          <view v-else class="h5-sheet-hero__empty">款</view>
          <view class="h5-sheet-hero__copy">
            <text class="h5-sheet-kicker">{{ current.is_recut ? '生产单-补' : '生产单' }}</text>
            <strong>{{ sheetNo }}</strong>
            <text v-if="current.is_recut">原单 {{ current.original_header_no || '—' }}</text>
            <text v-else>{{ customerLabel || '未填客户' }}</text>
          </view>
        </view>
        <view class="h5-prog-stats">
          <view><text>{{ current.is_recut ? '码数' : '订单数' }}</text><strong>{{ current.is_recut ? recutSizeLines.length : orderCount }}</strong></view>
          <view><text>{{ current.is_recut ? '补做' : '合计' }}</text><strong>{{ current.is_recut ? `${recutTotalPieces} 只` : `${current.total_qty || 0} 双` }}</strong></view>
          <view><text>计划完成</text><strong>{{ dateText(current.delivery_date) }}</strong></view>
        </view>
      </view>

      <view v-if="current.is_recut" class="card h5-sheet-block">
        <view class="h5-sheet-facts">
          <view><text>工厂型号</text><strong>{{ current.product_code || '—' }}</strong></view>
          <view><text>颜色</text><strong>{{ current.color_name || '—' }}</strong></view>
          <view><text>工艺起始</text><strong>{{ current.recut_detail?.process_start_name || '—' }}</strong></view>
          <view><text>补做到</text><strong>{{ current.recut_detail?.process_end_name || '—' }}</strong></view>
        </view>
        <text class="h5-sheet-label">报废码数</text>
        <view v-if="!recutSizeLines.length" class="h5-sheet-empty">没有码数</view>
        <view v-for="(line, index) in recutSizeLines" :key="line.defect_event_id || line.size_id || index" class="h5-sheet-sizepair">
          <strong>{{ line.size_value || '—' }}</strong>
          <text>左 {{ Number(line.left_qty || 0) ? `${Number(line.left_qty)}只` : '—' }}</text>
          <text>右 {{ Number(line.right_qty || 0) ? `${Number(line.right_qty)}只` : '—' }}</text>
        </view>
      </view>

      <view v-else class="card h5-sheet-block">
        <view class="h5-sheet-facts">
          <view><text>工厂型号</text><strong>{{ current.product_code || '—' }}</strong></view>
          <view><text>颜色</text><strong>{{ current.color_name || '—' }}</strong></view>
          <view><text>鞋面</text><strong>{{ sharedFabric }}</strong></view>
          <view><text>内里/垫脚</text><strong>{{ sharedLining }}</strong></view>
        </view>
      </view>

      <template v-if="!current.is_recut">
        <text class="h5-prog-section">订单配码</text>
        <view v-for="(row, rowIndex) in orderRows" :key="row.sales_order_line_id || rowIndex" class="card h5-sheet-block">
          <view class="h5-sheet-order__head">
            <strong>{{ row.sales_order_no || '—' }}</strong>
            <text>{{ row.total_qty ?? 0 }} 双</text>
          </view>
          <view class="h5-sheet-facts">
            <view><text>客户</text><strong>{{ row.customer_name || '—' }}</strong></view>
            <view><text>品牌</text><strong>{{ row.brand_name || '—' }}</strong></view>
            <view><text>客户型号</text><strong>{{ row.customer_sku || '—' }}</strong></view>
            <view><text>箱数</text><strong>{{ row.carton_qty || '—' }}</strong></view>
            <view><text>交货日期</text><strong>{{ dateText(row.delivery_date) }}</strong></view>
          </view>
          <text class="h5-sheet-label">每箱配码</text>
          <scroll-view class="h5-sheet-sizes" scroll-x :show-scrollbar="false">
            <view v-for="(size, index) in sizeLines" :key="size.size_id || size.id || index" class="h5-sheet-size">
              <text>{{ size.size_value || '—' }}</text>
              <strong>{{ assortmentText(row, size) }}</strong>
            </view>
            <view v-if="!sizeLines.length" class="h5-sheet-size"><text>—</text><strong>—</strong></view>
          </scroll-view>
        </view>
      </template>

      <template v-if="sizeMatchBlocks.length">
        <text class="h5-prog-section">码数配套</text>
        <view v-for="block in sizeMatchBlocks" :key="block.key" class="card h5-sheet-block">
          <text v-if="sizeMatchBlocks.length > 1 && block.sales_order_no" class="h5-sheet-label">{{ block.sales_order_no }}</text>
          <view v-for="kind in block.kinds" :key="kind.key" class="h5-sheet-match">
            <text>{{ kind.label }}</text>
            <view class="h5-sheet-match__chips">
              <text v-for="size in block.sizes" :key="size.key">{{ size.label }} → {{ kind.map[size.label] || size.label }}</text>
            </view>
          </view>
        </view>
      </template>

      <text class="h5-prog-section">{{ current.is_recut ? '本次补做材料' : '物料明细' }}</text>
      <view v-if="!materialRows.length" class="card h5-sheet-block"><text class="h5-sheet-empty">暂无物料明细</text></view>
      <view v-for="(material, index) in materialRows" :key="material.key || index" class="card h5-sheet-block h5-sheet-mat">
        <view class="h5-sheet-order__head">
          <strong>{{ material.code || '未编码' }}</strong>
          <text>{{ qtyText(material.totalQty) }} {{ material.unit || '' }}</text>
        </view>
        <text class="h5-sheet-mat__name">{{ material.name || '—' }}<text v-if="material.customerSupplied"> · 客供</text></text>
        <view class="h5-sheet-facts">
          <view><text>颜色</text><strong>{{ material.color || '—' }}</strong></view>
          <view><text>每双用量</text><strong>{{ material.usageLabel }}</strong></view>
          <view><text>使用部门</text><strong>{{ material.department || '—' }}</strong></view>
        </view>
        <view v-if="materialSizeColumns.length" class="h5-sheet-match__chips">
          <text v-for="size in materialSizeColumns" :key="size">{{ size }} {{ material.sizeQty[size] == null ? '—' : qtyText(material.sizeQty[size]) }}</text>
        </view>
      </view>

      <template v-if="!current.is_recut">
        <text class="h5-prog-section">客户做货要求</text>
        <view v-if="!workReqBlocks.length" class="card h5-sheet-block"><text class="h5-sheet-empty">未填做货要求</text></view>
        <view v-for="block in workReqBlocks" :key="block.key" class="card h5-sheet-block">
          <text v-if="block.sales_order_no" class="h5-sheet-label">销售单 {{ block.sales_order_no }}</text>
          <text class="h5-sheet-note">{{ block.notes || '未填文字要求' }}</text>
          <image v-if="block.image_url" class="h5-sheet-photo" :src="displayImageUrl(block.image_url)" mode="aspectFill" @click="previewImage(block.image_url)" />
          <template v-for="(line, lineIndex) in block.lines" :key="lineIndex">
            <view v-if="line.brand_name || line.brand_logo_urls.length || line.notes" class="h5-sheet-req">
              <text v-if="line.brand_name" class="h5-sheet-req__brand">{{ line.brand_name }}</text>
              <scroll-view v-if="line.brand_logo_urls.length" class="h5-sheet-logos" scroll-x :show-scrollbar="false">
                <image v-for="(url, logoIndex) in line.brand_logo_urls" :key="`${lineIndex}-${logoIndex}`" :src="displayImageUrl(url)" mode="aspectFill" @click="previewImage(url)" />
              </scroll-view>
              <text v-if="line.notes" class="h5-sheet-note">{{ line.notes }}</text>
            </view>
          </template>
        </view>
      </template>

      <text class="h5-prog-section">工艺路线</text>
      <view v-if="!processGroups.length" class="card h5-sheet-block"><text class="h5-sheet-empty">暂无工序</text></view>
      <view v-for="(group, groupIndex) in processGroups" :key="`${group.name}-${groupIndex}`" class="card h5-sheet-block">
        <text class="h5-sheet-seg">{{ group.name }}</text>
        <view v-for="(row, index) in group.rows" :key="row.id || index" class="h5-sheet-step">
          <strong>{{ row.label || row.process_name || '工序' }}</strong>
          <text v-if="row.notes || row.remark || row.requirement_note">{{ row.notes || row.remark || row.requirement_note }}</text>
        </view>
      </view>
      <text class="h5-sheet-foot">{{ current.is_recut ? `本单只用于补做，按左右脚和码数生产，完成到${current.recut_detail?.process_end_name || '指定工序'}后并入原生产单。` : '裁断、成型扫本单二维码报工；针车扫框码；包装扫箱唛。' }}</text>
    </template>
    <view v-else class="h5-prog-empty">正在读取生产单…</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onBackPress, onLoad, onPullDownRefresh, onReachBottom, onShow } from '@dcloudio/uni-app'
import { get } from '../../services/http'
import { appPageForTarget } from '../../services/scanner'

const statuses = [
  { value: 'active', label: '未完成' },
  { value: 'confirmed', label: '待生产' },
  { value: 'production', label: '生产中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
  { value: 'all', label: '全部' },
]
const statusText: Record<string, string> = {
  draft: '草稿',
  confirmed: '待生产',
  cut: '生产中',
  in_progress: '生产中',
  completed: '已完成',
  cancelled: '已取消',
}

const mode = ref<'list' | 'detail'>('list')
const openedFromLink = ref(false)
const status = ref('active')
const keyword = ref('')
const rows = ref<any[]>([])
const current = ref<any>(null)
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const finished = ref(false)
let listSeq = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null

function countsOnRoute(proc: any) {
  const routeIds = new Set((proc?.route_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean))
  if (proc?.route_department_shared || !routeIds.size) return true
  const assigned = (proc?.assigned_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean)
  if (!assigned.length) return true
  return assigned.some((id: number) => routeIds.has(id))
}
function bottleneck(procs: any[]) {
  const effective = procs.filter(row => Number(row?.plan_qty || 0) > 0)
  if (!effective.length) return null
  const plan = Math.max(...effective.map(row => Math.max(0, Number(row.plan_qty || 0))))
  if (!plan) return null
  const rate = Math.min(...effective.map(row => {
    const itemPlan = Number(row.plan_qty || 0)
    const completed = Math.max(0, Number(row.completed_qty || 0))
    return Math.min(1, completed / itemPlan)
  }))
  return { plan, done: Math.round((Math.min(plan, plan * rate) + Number.EPSILON) * 100) / 100 }
}
function segmentBars(row: any) {
  const build = (filterRoute: boolean) => {
    const groups: { id: string; name: string; rows: any[] }[] = []
    for (const proc of row?.processes || []) {
      if (filterRoute && !countsOnRoute(proc)) continue
      const id = String(proc.segment_id ?? 'unlabeled')
      const name = proc.segment_name || '未分段'
      const last = groups[groups.length - 1]
      if (!last || last.id !== id) groups.push({ id, name, rows: [proc] })
      else last.rows.push(proc)
    }
    return groups.map(group => {
      const stage = bottleneck(group.rows)
      const plan = stage?.plan || 0
      const done = stage?.done || 0
      return {
        ...group,
        plan,
        done,
        percent: plan ? Math.min(100, Math.round(done / plan * 100)) : 0,
        current: group.rows.some(item => item.is_current),
        doneAll: plan > 0 && done >= plan,
      }
    })
  }
  const filtered = build(true)
  return filtered.length ? filtered : build(false)
}
function compareSize(a: unknown, b: unknown) {
  return String(a || '').localeCompare(String(b || ''), 'zh-CN', { numeric: true })
}
function qtyText(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const text = String(Math.round(number * 10000) / 10000)
  return text.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
}
const sheetNo = computed(() => current.value?.header_no || current.value?.execution_no || current.value?.order_no || '—')
const sizeLines = computed(() => {
  const lines = current.value?.size_lines || current.value?.items || []
  return [...lines].sort((a: any, b: any) => compareSize(a?.size_value, b?.size_value))
})
const recutSizeLines = computed(() => {
  const recut = current.value?.recut_detail
  if (!recut) return []
  const lines = Array.isArray(recut.size_lines) && recut.size_lines.length ? recut.size_lines : [recut]
  return [...lines].sort((a: any, b: any) => compareSize(a?.size_value, b?.size_value))
})
const recutTotalPieces = computed(() => recutSizeLines.value.reduce((sum: number, line: any) => sum + Number(line.qty ?? (Number(line.left_qty || 0) + Number(line.right_qty || 0))), 0))
const customerLabel = computed(() => {
  const row = current.value
  if (!row) return ''
  if (Array.isArray(row.customers) && row.customers.length) return row.customers.join(' / ')
  return row.customer_name || ''
})
const salesOrderLabel = computed(() => {
  const row = current.value
  if (!row) return ''
  if (Array.isArray(row.sales_order_nos) && row.sales_order_nos.length) return row.sales_order_nos.join(' / ')
  return row.sales_order_no || ''
})
const orderRows = computed(() => {
  const rows = current.value?.allocation_rows
  if (Array.isArray(rows) && rows.length) return rows
  if (!current.value) return []
  return [{
    sales_order_no: salesOrderLabel.value,
    customer_name: customerLabel.value,
    fabric: current.value.fabric,
    lining: current.value.lining,
    brand_name: current.value.brand_name,
    brand_logo_urls: [],
    customer_sku: current.value.customer_sku,
    order_notes: current.value.work_requirement?.notes,
    carton_qty: current.value.carton_qty,
    total_qty: current.value.total_qty,
    delivery_date: current.value.delivery_date,
    size_quantities: {},
    size_matches: current.value.line_size_matches || {},
  }]
})
const orderCount = computed(() => {
  const ids = new Set(orderRows.value.map((row: any) => row.sales_order_id || row.sales_order_no).filter(Boolean))
  return ids.size || (orderRows.value.length ? 1 : 0)
})
function sharedText(field: 'fabric' | 'lining') {
  const values: string[] = []
  for (const row of orderRows.value) {
    const text = String(row?.[field] || '').trim()
    if (text && !values.includes(text)) values.push(text)
  }
  return values.join('、') || '—'
}
const sharedFabric = computed(() => sharedText('fabric'))
const sharedLining = computed(() => sharedText('lining'))
function assortmentText(row: any, size: any) {
  const allocated = row?.size_quantities?.[String(size.id)]
  const total = Number(allocated ?? size.total_qty ?? size.qty ?? 0)
  const cartons = Number(row?.carton_qty || 0)
  if (!Number.isFinite(total) || total <= 0) return '—'
  if (!cartons) return qtyText(total)
  return total % cartons === 0 ? qtyText(total / cartons) : '—'
}
const sizeMatchKinds = [
  { key: 'outsole', label: '大底' },
  { key: 'midsole', label: '中底' },
  { key: 'heel', label: '鞋跟' },
  { key: 'last', label: '鞋楦' },
]
const sizeMatchBlocks = computed(() => {
  const blocks: any[] = []
  for (const row of orderRows.value) {
    const matches = row?.size_matches
    if (!matches || typeof matches !== 'object') continue
    const kinds = sizeMatchKinds.map(kind => ({ ...kind, map: matches[kind.key] || {} })).filter(kind => Object.keys(kind.map).length)
    if (!kinds.length) continue
    const sizes: { key: string; label: string }[] = []
    for (const line of sizeLines.value) {
      const label = String(line?.size_value || '').trim()
      if (!label || sizes.some(size => size.label === label)) continue
      const allocated = row?.size_quantities?.[String(line.id)]
      const total = Number(allocated ?? line.total_qty ?? line.qty ?? 0)
      if (!(total > 0)) continue
      sizes.push({ key: String(line.size_id || line.id || label), label })
    }
    sizes.sort((a, b) => compareSize(a.label, b.label))
    if (!sizes.length) continue
    blocks.push({ key: row.sales_order_line_id || row.sales_order_no || blocks.length, sales_order_no: row.sales_order_no || '', sizes, kinds })
  }
  return blocks
})
const sourceMaterials = computed(() => current.value?.is_recut && Array.isArray(current.value?.recut_materials) ? current.value.recut_materials : (current.value?.materials || []))
const materialSizeColumns = computed(() => {
  const present = new Set<string>()
  for (const material of sourceMaterials.value) {
    const size = String(material?.size_value || '').trim()
    if (size) present.add(size)
  }
  const ordered: string[] = []
  for (const line of sizeLines.value) {
    const size = String(line?.size_value || '').trim()
    if (size && present.has(size) && !ordered.includes(size)) ordered.push(size)
  }
  const rest = [...present].filter(size => !ordered.includes(size))
  rest.sort((a, b) => compareSize(a, b))
  return [...ordered, ...rest]
})
const materialRows = computed(() => {
  const groups = new Map<string, any>()
  for (const material of sourceMaterials.value) {
    const department = material?.consume_segment_name || material?.consume_process_name || ''
    const key = [material?.supplier_product_id || material?.supplier_product_code || '', material?.color_name || '', material?.pricing_unit_name || '', department, material?.is_customer_supplied ? '1' : '0'].join('\u0001')
    let group = groups.get(key)
    if (!group) {
      group = { key, code: material?.supplier_product_code || '', name: material?.supplier_product_name || '', color: material?.color_name || '', unit: material?.pricing_unit_name || '', department, customerSupplied: Boolean(material?.is_customer_supplied), sizeQty: {} as Record<string, number>, usages: [] as number[], totalQty: 0 }
      groups.set(key, group)
    }
    const qty = Number(material?.required_qty)
    const usage = Number(material?.qty_per_pair)
    if (Number.isFinite(qty)) group.totalQty += qty
    if (Number.isFinite(usage) && !group.usages.includes(usage)) group.usages.push(usage)
    const size = String(material?.size_value || '').trim()
    if (size && Number.isFinite(qty)) group.sizeQty[size] = (group.sizeQty[size] || 0) + qty
  }
  return [...groups.values()].map(group => ({
    ...group,
    usageLabel: group.usages.length === 1 ? qtyText(group.usages[0]) : group.usages.length ? '按码' : '—',
  }))
})
const workReqBlocks = computed(() => {
  const reqs = Array.isArray(current.value?.work_requirements) && current.value.work_requirements.length
    ? current.value.work_requirements
    : (current.value?.work_requirement && Object.keys(current.value.work_requirement).length ? [current.value.work_requirement] : [])
  const reqByKey = new Map<string, any>()
  for (const req of reqs) {
    for (const key of [req?.sales_order_id, req?.sales_order_no].filter((value: unknown) => value != null && value !== '')) reqByKey.set(String(key), req)
  }
  const groups = new Map<string, any>()
  for (const row of orderRows.value) {
    const key = String(row?.sales_order_id || row?.sales_order_no || 'order')
    let block = groups.get(key)
    if (!block) {
      const req = reqByKey.get(key) || reqByKey.get(String(row?.sales_order_no || '')) || {}
      block = { key, sales_order_no: row?.sales_order_no || req.sales_order_no || '', notes: String(req.notes || row?.order_notes || '').trim(), image_url: req.image_url || '', lines: [] as any[] }
      groups.set(key, block)
    }
    block.lines.push({
      brand_name: row?.brand_name || '',
      brand_logo_urls: Array.isArray(row?.brand_logo_urls) ? row.brand_logo_urls.filter(Boolean) : [],
      notes: String(row?.line_notes || '').trim(),
    })
  }
  return [...groups.values()].filter(block => block.notes || block.image_url || block.lines.some((line: any) => line.brand_name || line.brand_logo_urls.length || line.notes))
})
const processGroups = computed(() => {
  const source = current.value?.is_recut && Array.isArray(current.value?.recut_processes) ? current.value.recut_processes : (current.value?.processes || [])
  const groups: { name: string; rows: any[] }[] = []
  for (const row of source) {
    const name = String(row?.segment_name || '').trim() || '未分段'
    const last = groups[groups.length - 1]
    if (!last || last.name !== name) groups.push({ name, rows: [row] })
    else last.rows.push(row)
  }
  return groups
})

function showRiskLabel(row: any) {
  const label = String(row?.risk_label || '')
  return !!label && label !== '必延期'
}
function warehouseClass(value: string) {
  if (value === '齐套') return 'h5-chip--ok'
  if (value === '待买') return 'h5-chip--warn'
  return 'h5-chip--bad'
}
function statusLabel(value: string) {
  return statusText[value] || value || '—'
}
function dateText(value?: string) {
  const text = String(value || '').slice(0, 10)
  if (!text) return '未定'
  const parts = text.split('-')
  if (parts.length < 3) return text
  return `${Number(parts[1])}月${Number(parts[2])}日`
}
function pairText(value: unknown) {
  const number = Number(value || 0)
  return Number.isInteger(number) ? String(number) : String(Math.round(number * 10) / 10)
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
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}

async function loadList(reset = false) {
  if (!reset && (loading.value || loadingMore.value || finished.value)) return
  const seq = ++listSeq
  if (reset) {
    page.value = 1
    finished.value = false
    loading.value = true
  } else {
    loadingMore.value = true
    page.value += 1
  }
  try {
    const query: Record<string, unknown> = { status: status.value, page: page.value, page_size: 20 }
    const q = keyword.value.trim()
    if (q) query.q = q
    const result: any = await get('/executions/mobile', query)
    if (seq !== listSeq) return
    const items = result?.items || []
    rows.value = reset ? items : rows.value.concat(items)
    total.value = Number(result?.total || 0)
    finished.value = rows.value.length >= total.value || items.length < 20
  } catch (error: any) {
    if (!reset) page.value = Math.max(1, page.value - 1)
    toast(error?.message || '生产进度加载失败')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
    }
    uni.stopPullDownRefresh()
  }
}
function reload() {
  loadList(true)
}
function selectStatus(value: string) {
  if (status.value === value) return
  status.value = value
  rows.value = []
  loadList(true)
}
function onKeyword(event: any) {
  keyword.value = String(event?.detail?.value || '')
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadList(true), 300)
}
function clearKeyword() {
  keyword.value = ''
  loadList(true)
}
function openFlow(row: any) {
  uni.navigateTo({
    url: appPageForTarget({
      kind: 'flow-card',
      code: String(row.id),
      h5Path: `/flow-card/${row.id}`,
      label: '生产流转卡',
    }),
  })
}
async function loadLinkedDetail(headerId: number) {
  try {
    const row: any = await get(`/executions/headers/${headerId}/flow-card`)
    if (!row?.header_id && !row?.id) {
      toast('生产单不存在')
      if (openedFromLink.value) uni.navigateBack()
      return
    }
    current.value = row
    mode.value = 'detail'
    uni.setNavigationBarTitle({ title: row.header_no || '生产单' })
  } catch (error: any) {
    toast(error?.message || '生产单加载失败')
    if (openedFromLink.value && !current.value) uni.navigateBack()
  }
}

onBackPress(() => {
  if (openedFromLink.value || mode.value !== 'detail') return false
  mode.value = 'list'
  uni.setNavigationBarTitle({ title: '生产进度' })
  return true
})
onPullDownRefresh(() => {
  if (mode.value === 'detail') {
    const headerId = Number(current.value?.header_id || current.value?.id || 0)
    if (!headerId) {
      uni.stopPullDownRefresh()
      return
    }
    loadLinkedDetail(headerId).finally(() => uni.stopPullDownRefresh())
    return
  }
  loadList(true)
})
onReachBottom(() => {
  if (mode.value === 'list') loadList(false)
})
onLoad((query) => {
  const headerId = Number(query?.header_id || 0)
  if (!headerId) return
  openedFromLink.value = true
  mode.value = 'detail'
  loadLinkedDetail(headerId)
})
onShow(() => {
  if (mode.value === 'list') loadList(true)
})
</script>

<style scoped>
.h5-prog--sub { padding-bottom: 48rpx; }
.h5-prog-empty,
.h5-prog-more { padding: 36rpx 0 48rpx; color: #727786; font-size: 24rpx; text-align: center; }
.h5-prog-search { display: flex; align-items: center; gap: 16rpx; margin-bottom: 18rpx; padding: 6rpx 8rpx 6rpx 28rpx; }
.h5-prog-search input { flex: 1; height: 76rpx; color: #181b23; font-size: 28rpx; }
.h5-prog-search text { padding-right: 16rpx; color: #0057c2; font-size: 26rpx; }
.h5-prog-tabs { width: 100%; margin-bottom: 18rpx; white-space: nowrap; }
.h5-prog-tabs text { display: inline-flex; align-items: center; height: 56rpx; margin-right: 12rpx; padding: 0 22rpx; border-radius: 999rpx; background: #fff; color: #414755; font-size: 24rpx; }
.h5-prog-tabs text.on { background: #0057c2; color: #fff; font-weight: 700; }
.h5-prog-card,
.h5-prog-hero { margin-bottom: 18rpx; padding: 22rpx 22rpx 18rpx; }
.h5-prog-card__row { display: flex; gap: 18rpx; }
.h5-prog-thumb,
.h5-prog-hero image,
.h5-prog-hero__empty { flex: none; width: 120rpx; height: 120rpx; border-radius: 22rpx; background: #f5f7fa; }
.h5-prog-thumb--empty,
.h5-prog-hero__empty { display: flex; align-items: center; justify-content: center; color: #727786; font-size: 28rpx; font-weight: 750; }
.h5-prog-card__main,
.h5-prog-hero__copy { flex: 1; min-width: 0; }
.h5-prog-card__top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-prog-card__badges { display: flex; flex: none; align-items: center; gap: 8rpx; }
.h5-prog-card__top strong,
.h5-prog-hero__copy strong { overflow: hidden; color: #181b23; font-size: 28rpx; font-weight: 750; letter-spacing: 0.4rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-status { flex: none; padding: 4rpx 12rpx; border-radius: 999rpx; background: rgba(0, 87, 194, 0.1); color: #0057c2; font-size: 20rpx; font-weight: 700; }
.h5-prog-status.is-completed { background: rgba(38, 109, 0, 0.1); color: #266d00; }
.h5-prog-status.is-cancelled { background: #e0e2ed; color: #727786; }
.h5-prog-meta { display: block; margin-top: 6rpx; overflow: hidden; color: #414755; font-size: 24rpx; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-hero__copy { display: flex; flex-direction: column; align-items: flex-start; }
.h5-prog-hero__copy .h5-prog-card__top { align-self: stretch; width: 100%; }
.h5-prog-hero__copy > text { margin-top: 6rpx; color: #414755; font-size: 24rpx; }
.h5-prog-tags { display: flex; flex-wrap: wrap; gap: 8rpx; margin-top: 12rpx; }
.h5-chip { padding: 2rpx 12rpx; border-radius: 999rpx; font-size: 20rpx; font-weight: 700; line-height: 1.6; }
.h5-chip--ok { background: rgba(38, 109, 0, 0.1); color: #266d00; }
.h5-chip--warn { background: rgba(125, 84, 0, 0.1); color: #7d5400; }
.h5-chip--bad { background: rgba(186, 26, 26, 0.1); color: #ba1a1a; }
.h5-prog-stats { display: flex; margin-top: 18rpx; padding-top: 16rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-stats view { flex: 1; min-width: 0; }
.h5-prog-stats view + view { padding-left: 16rpx; border-left: 1rpx solid #e0e2ed; }
.h5-prog-stats text { display: block; color: #727786; font-size: 20rpx; }
.h5-prog-stats strong { display: block; margin-top: 4rpx; overflow: hidden; color: #181b23; font-size: 26rpx; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.h5-prog-segs { display: flex; gap: 10rpx; width: 100%; margin-top: 16rpx; }
.h5-prog-seg { display: flex; flex: 1; align-items: center; justify-content: center; gap: 6rpx; min-width: 0; padding: 18rpx 8rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-prog-seg.current { background: rgba(0, 87, 194, 0.08); }
.h5-prog-seg.done { background: rgba(38, 109, 0, 0.08); }
.h5-prog-seg__name { color: #414755; font-size: 22rpx; font-weight: 650; line-height: 1.15; letter-spacing: 2rpx; writing-mode: vertical-rl; text-orientation: upright; }
.h5-prog-seg.current .h5-prog-seg__name,
.h5-prog-seg.current .h5-prog-seg__done,
.h5-prog-seg.current .h5-prog-seg__plan { color: #0057c2; }
.h5-prog-seg.done .h5-prog-seg__name,
.h5-prog-seg.done .h5-prog-seg__done,
.h5-prog-seg.done .h5-prog-seg__plan { color: #266d00; }
.h5-prog-seg__meter { display: flex; flex: 1; flex-direction: column; align-items: center; min-width: 0; }
.h5-prog-seg__done,
.h5-prog-seg__plan { color: #181b23; font-size: 30rpx; font-weight: 750; line-height: 1.1; }
.h5-prog-seg__track { width: 100%; height: 4rpx; margin: 8rpx 0; overflow: hidden; border-radius: 999rpx; background: #e0e2ed; }
.h5-prog-seg__track view { height: 100%; border-radius: inherit; background: #8eb6e8; }
.h5-prog-seg.current .h5-prog-seg__track view { background: #0057c2; }
.h5-prog-seg.done .h5-prog-seg__track view,
.h5-prog-segment.done .h5-prog-seg__track view { background: #266d00; }
.h5-prog-seg__track--wide { width: auto; height: 8rpx; margin: 0 0 8rpx; background: #e0e2ed; }
.h5-prog-segment.current .h5-prog-seg__track view { background: #0057c2; }
.h5-prog-seg__empty { color: #727786; font-size: 22rpx; }
.h5-prog-section { display: block; margin: 10rpx 8rpx 12rpx; color: #727786; font-size: 22rpx; font-weight: 700; letter-spacing: 2rpx; }
.h5-prog-segment { margin-bottom: 14rpx; padding: 8rpx 22rpx 12rpx; border-left: 8rpx solid #e0e2ed; }
.h5-prog-links { margin-bottom: 14rpx; padding: 4rpx 22rpx; }
.h5-prog-segment.current { border-left-color: #0057c2; }
.h5-prog-segment.done { border-left-color: #266d00; }
.h5-prog-segment__head,
.h5-prog-step,
.h5-prog-link { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.h5-prog-segment__head { min-height: 68rpx; }
.h5-prog-segment__head strong { color: #181b23; font-size: 28rpx; }
.h5-prog-segment__head text { color: #414755; font-size: 24rpx; font-weight: 650; }
.h5-prog-step { min-height: 76rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-step view { display: flex; flex-direction: column; }
.h5-prog-step strong { color: #181b23; font-size: 26rpx; font-weight: 650; }
.h5-prog-step view text,
.h5-prog-step > text,
.h5-prog-link text { color: #727786; font-size: 22rpx; }
.h5-prog-step.current strong,
.h5-prog-step.current > text { color: #0057c2; }
.h5-prog-step.done strong { color: #266d00; }
.h5-prog-link { min-height: 96rpx; border-top: 1rpx solid #e0e2ed; }
.h5-prog-link:first-child { border-top: 0; }
.h5-prog-link strong { display: block; color: #181b23; font-size: 30rpx; }
.h5-prog-link__go { color: #0057c2; font-size: 36rpx; }
.h5-sheet-hero,
.h5-sheet-block { margin-bottom: 14rpx; padding: 8rpx 22rpx 18rpx; }
.h5-sheet-hero { padding-top: 22rpx; }
.h5-sheet-hero__top { display: flex; gap: 18rpx; }
.h5-sheet-hero image,
.h5-sheet-hero__empty { flex: none; width: 132rpx; height: 132rpx; border-radius: 22rpx; background: #f5f7fa; }
.h5-sheet-hero__empty { display: flex; align-items: center; justify-content: center; color: #727786; font-size: 28rpx; font-weight: 750; }
.h5-sheet-hero__copy { display: flex; flex: 1; flex-direction: column; justify-content: center; min-width: 0; }
.h5-sheet-kicker { color: #0057c2; font-size: 22rpx; font-weight: 700; }
.h5-sheet-hero__copy strong { margin-top: 6rpx; color: #181b23; font-size: 34rpx; font-weight: 750; }
.h5-sheet-hero__copy > text:last-child { margin-top: 6rpx; color: #414755; font-size: 24rpx; }
.h5-sheet-facts { display: flex; flex-wrap: wrap; }
.h5-sheet-facts view { width: 50%; padding: 14rpx 12rpx 0 0; box-sizing: border-box; }
.h5-sheet-facts text,
.h5-sheet-label { display: block; color: #727786; font-size: 22rpx; }
.h5-sheet-facts strong { display: block; margin-top: 4rpx; color: #181b23; font-size: 28rpx; font-weight: 650; word-break: break-all; }
.h5-sheet-label { margin-top: 18rpx; }
.h5-sheet-order__head,
.h5-sheet-sizepair { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; min-height: 72rpx; }
.h5-sheet-order__head strong,
.h5-sheet-sizepair strong { color: #181b23; font-size: 30rpx; }
.h5-sheet-order__head text,
.h5-sheet-sizepair text { color: #0057c2; font-size: 26rpx; font-weight: 700; }
.h5-sheet-sizes { width: 100%; margin-top: 12rpx; white-space: nowrap; }
.h5-sheet-size { display: inline-flex; flex-direction: column; align-items: center; min-width: 88rpx; margin-right: 12rpx; padding: 12rpx 16rpx; border-radius: 16rpx; background: #f4f7fb; }
.h5-sheet-size text { color: #727786; font-size: 22rpx; }
.h5-sheet-size strong { margin-top: 4rpx; color: #132033; font-size: 30rpx; }
.h5-sheet-match { padding-top: 16rpx; }
.h5-sheet-match > text,
.h5-sheet-seg { display: block; color: #0b3f8a; font-size: 28rpx; font-weight: 750; }
.h5-sheet-match__chips { display: flex; flex-wrap: wrap; gap: 10rpx; margin-top: 10rpx; }
.h5-sheet-match__chips text { padding: 8rpx 14rpx; border-radius: 999rpx; background: #f4f7fb; color: #132033; font-size: 22rpx; }
.h5-sheet-mat__name,
.h5-sheet-note { display: block; margin-top: 8rpx; color: #414755; font-size: 26rpx; line-height: 1.5; }
.h5-sheet-empty { display: block; padding: 20rpx 0; color: #727786; font-size: 24rpx; }
.h5-sheet-photo,
.h5-sheet-logos image { width: 160rpx; height: 160rpx; margin-top: 12rpx; border-radius: 16rpx; background: #f5f7fa; }
.h5-sheet-logos { width: 100%; margin-top: 8rpx; white-space: nowrap; }
.h5-sheet-logos image { display: inline-block; margin-right: 12rpx; }
.h5-sheet-req { margin-top: 16rpx; padding-top: 12rpx; border-top: 1rpx solid #e0e2ed; }
.h5-sheet-req__brand { display: block; color: #181b23; font-size: 26rpx; font-weight: 700; }
.h5-sheet-step { padding: 16rpx 0; border-top: 1rpx solid #e3edf7; }
.h5-sheet-step strong { display: block; color: #181b23; font-size: 28rpx; }
.h5-sheet-step text { display: block; margin-top: 6rpx; color: #667386; font-size: 24rpx; line-height: 1.45; }
.h5-sheet-foot { display: block; padding: 8rpx 8rpx 28rpx; color: #727786; font-size: 22rpx; line-height: 1.5; }
</style>
