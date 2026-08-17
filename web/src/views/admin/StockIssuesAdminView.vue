<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const props = withDefaults(
  defineProps<{
    /** 嵌在「库存」页 Tab 内时隐藏独立页头/方向 Tab */
    embedded?: boolean
    /** 固定方向：入库 / 出库 */
    fixedDirection?: 'in' | 'out'
  }>(),
  { embedded: false, fixedDirection: undefined },
)

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths(
  props.fixedDirection ? `stock-issues-list-${props.fixedDirection}` : 'stock-issues-list',
  tableRef,
)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('stock-issues-lines')
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const canConfirm = computed(
  () =>
    auth.role === 'admin' ||
    auth.hasPermission('btn.stock_issues.confirm') ||
    auth.hasPermission('btn.stock_issues.write'),
)
const canVoid = computed(
  () =>
    auth.role === 'admin' ||
    auth.hasPermission('btn.stock_issues.submit') ||
    auth.hasPermission('btn.stock_issues.confirm') ||
    auth.hasPermission('btn.stock_issues.write'),
)

/** 全部 | 入库 | 出库（有 fixedDirection 时锁定） */
const directionTab = ref<'all' | 'in' | 'out'>(props.fixedDirection || 'all')
const docs = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const docsLoading = ref(false)
const actionId = ref<number | null>(null)
const keyword = ref('')
const docType = ref('')
const statusFilter = ref(props.fixedDirection === 'out' ? '' : 'pending')
const orderKeyword = ref('')
const orderOptions = ref<any[]>([])
const selectedOrderId = ref<number | null>(null)
const selectedHeaderId = ref<number | null>(null)

const detailVisible = ref(false)
const detailDoc = ref<any | null>(null)

const showDirectionTabs = computed(() => !props.embedded && !props.fixedDirection)
const showDirectionCol = computed(() => !props.fixedDirection)

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatTime(v: any) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function docDirection(row: any): 'in' | 'out' {
  if (!row) return 'out'
  if (row.doc_type === 'return_mat' || row.direction === 'in') return 'in'
  return 'out'
}

function directionLabel(row: any) {
  return docDirection(row) === 'in' ? '入库' : '出库'
}

function bizTypeLabel(row: any) {
  if (!row) return '—'
  if (row.doc_type === 'issue') {
    const kind = row.issue_kind
    return kind ? `领料出库·${kind}` : '领料出库'
  }
  if (row.doc_type === 'return_mat') return '退料入库'
  if (row.doc_type === 'purchase_in') return '采购入库'
  return row.doc_type || '—'
}

function confirmActionLabel(row: any) {
  return docDirection(row) === 'in' ? '确认入库' : '确认出库'
}

function statusLabel(s: string) {
  if (s === 'posted') return '已过账'
  if (s === 'pending') return '待确认'
  if (s === 'void') return '已作废'
  return s || '—'
}

function statusTagType(s: string) {
  if (s === 'posted') return 'success'
  if (s === 'pending') return 'warning'
  return 'info'
}

function resolvedDocTypeParam(): string | undefined {
  const dir = props.fixedDirection || directionTab.value
  if (dir === 'in') return 'return_mat'
  if (dir === 'out') return 'issue'
  return docType.value || undefined
}

async function searchOrders(q: string) {
  orderKeyword.value = q
  const res: any = await http.get('/executions', {
    params: { limit: 20, q: q || undefined },
  })
  orderOptions.value = res.data?.items || res.data || []
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const res: any = await http.get('/stock-issues', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        order_id: selectedOrderId.value || undefined,
        header_id: selectedHeaderId.value || undefined,
        doc_type: resolvedDocTypeParam(),
        status: statusFilter.value || undefined,
      },
    })
    const payload = res.data
    let list = payload?.items || (Array.isArray(payload) ? payload : [])
    const q = keyword.value.trim().toLowerCase()
    if (q) {
      list = list.filter((d: any) => {
        const hay = [d.doc_no, d.header_no, d.order_no, d.notes, d.issue_kind, bizTypeLabel(d)].join(' ').toLowerCase()
        return hay.includes(q)
      })
    }
    docs.value = list
    total.value = payload?.total ?? list.length
  } finally {
    docsLoading.value = false
    void nextTick(measureTableHeight)
  }
}

function search() {
  page.value = 1
  void loadDocs()
}

function onDirectionTabChange() {
  docType.value = ''
  page.value = 1
  void loadDocs()
}

function onPageSizeChange() {
  page.value = 1
  void loadDocs()
}

function openDetail(row: any) {
  detailDoc.value = row
  detailVisible.value = true
}

function openOrder(row: any, e?: Event) {
  e?.stopPropagation?.()
  if (row.header_id) {
    router.push({ path: '/admin/executions', query: { open: String(row.header_id) } })
    return
  }
  if (!row.order_id) return
  router.push({ path: '/admin/executions', query: { shop_order_id: String(row.order_id) } })
}

async function confirmDoc(row: any, e?: Event) {
  e?.stopPropagation?.()
  const label = confirmActionLabel(row)
  await ElMessageBox.confirm(`确认过账 ${row.doc_no}？过账后将更新库存。`, label, { type: 'warning' })
  actionId.value = row.id
  try {
    const res: any = await http.post(`/stock-issues/${row.id}/confirm`)
    ElMessage.success(`${label}成功`)
    if (detailDoc.value?.id === row.id) detailDoc.value = res.data
    await loadDocs()
  } finally {
    actionId.value = null
  }
}

async function voidDoc(row: any, e?: Event) {
  e?.stopPropagation?.()
  await ElMessageBox.confirm(`作废 ${row.doc_no}？作废后可重新提报。`, '作废', { type: 'warning' })
  actionId.value = row.id
  try {
    const res: any = await http.post(`/stock-issues/${row.id}/void`)
    ElMessage.success('已作废')
    if (detailDoc.value?.id === row.id) detailDoc.value = res.data
    await loadDocs()
  } finally {
    actionId.value = null
  }
}

onMounted(async () => {
  if (props.fixedDirection) {
    directionTab.value = props.fixedDirection
  }
  await searchOrders('')
  const hid = Number(route.query.header_id)
  if (hid > 0) selectedHeaderId.value = hid
  const oid = Number(route.query.order_id)
  if (oid > 0) selectedOrderId.value = oid
  const st = String(route.query.status || '')
  if (st) statusFilter.value = st
  if (!props.fixedDirection) {
    const dir = String(route.query.direction || '')
    if (dir === 'in' || dir === 'out') directionTab.value = dir
    const dt = String(route.query.doc_type || '')
    if (dt === 'issue' || dt === 'return_mat') {
      docType.value = dt
      directionTab.value = dt === 'return_mat' ? 'in' : 'out'
    }
  }
  await loadDocs()
})
</script>

<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">出入库单</h1>
        <p class="page-desc">
          领料确认生成出库单，退料确认生成入库单；仓管在此过账。默认看「待确认」。
        </p>
      </div>
    </header>

    <div :class="embedded ? 'inv-panel' : 'admin-card'">
      <el-tabs
        v-if="showDirectionTabs"
        v-model="directionTab"
        class="stock-dir-tabs"
        @tab-change="onDirectionTabChange"
      >
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="入库" name="in" />
        <el-tab-pane label="出库" name="out" />
      </el-tabs>

      <div class="admin-toolbar">
        <el-select
          v-model="selectedHeaderId"
          filterable
          remote
          clearable
          placeholder="按生产单筛选"
          style="width: 240px"
          :remote-method="searchOrders"
          @change="search"
          @focus="searchOrders(orderKeyword)"
        >
          <el-option
            v-for="o in orderOptions"
            :key="o.id"
            :label="`${o.header_no || o.execution_no} · ${o.product_code || ''}`"
            :value="o.id"
          />
        </el-select>
        <el-select
          v-if="directionTab === 'all' && !fixedDirection"
          v-model="docType"
          clearable
          placeholder="类型"
          style="width: 130px"
          @change="search"
        >
          <el-option label="领料出库" value="issue" />
          <el-option label="退料入库" value="return_mat" />
        </el-select>
        <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 120px" @change="search">
          <el-option label="待确认" value="pending" />
          <el-option label="已过账" value="posted" />
          <el-option label="已作废" value="void" />
        </el-select>
        <el-input
          v-model="keyword"
          clearable
          placeholder="单号 / 备注"
          style="width: 180px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-button type="primary" :loading="docsLoading" @click="search">查询</el-button>
      </div>

      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="docsLoading"
          :data="docs"
          stripe
          border
          style="width: 100%"
          :max-height="tableMaxHeight"
          empty-text="暂无单据"
          class="docs-table"
          @row-click="openDetail"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column prop="doc_no" label="单号" :width="colWidth('doc_no', 120)" resizable />
          <el-table-column
            v-if="showDirectionCol"
            column-key="direction"
            label="方向"
            :width="colWidth('direction', 72)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-tag :type="docDirection(row) === 'in' ? 'warning' : 'success'" size="small" effect="plain">
                {{ directionLabel(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="type" label="类型" :width="colWidth('type', 140)" resizable>
            <template #default="{ row }">
              {{ bizTypeLabel(row) }}
            </template>
          </el-table-column>
          <el-table-column column-key="status" label="状态" :width="colWidth('status', 90)" resizable>
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small" effect="plain">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column column-key="order" label="生产单" :width="colWidth('order', 120)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click="openOrder(row, $event)">{{ row.header_no || row.order_no || '—' }}</el-button>
            </template>
          </el-table-column>
          <el-table-column column-key="过账_提报" label="过账/提报" :width="colWidth('过账_提报', 160)" resizable>
            <template #default="{ row }">{{ formatTime(row.posted_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column
            prop="notes"
            label="原因/备注"
            :min-width="flexColMinWidth('notes', 140)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 180)" resizable>
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openDetail(row)">明细</el-button>
              <el-button
                v-if="row.status === 'pending' && canConfirm"
                link
                type="success"
                :loading="actionId === row.id"
                @click="confirmDoc(row, $event)"
              >
                {{ confirmActionLabel(row) }}
              </el-button>
              <el-button
                v-if="row.status === 'pending' && canVoid"
                link
                type="danger"
                :loading="actionId === row.id"
                @click="voidDoc(row, $event)"
              >
                作废
              </el-button>
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
          :page-sizes="[10, 20, 50, 100]"
          @current-change="loadDocs"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="detailDoc ? `${bizTypeLabel(detailDoc)} · ${detailDoc.doc_no}` : '单据明细'"
      width="720px"
      destroy-on-close
    >
      <template v-if="detailDoc">
        <div class="detail-meta">
          <div v-if="showDirectionCol">
            <span class="meta-label">方向</span>
            <el-tag :type="docDirection(detailDoc) === 'in' ? 'warning' : 'success'" size="small" effect="plain">
              {{ directionLabel(detailDoc) }}
            </el-tag>
          </div>
          <div>
            <span class="meta-label">状态</span>
            <el-tag :type="statusTagType(detailDoc.status)" size="small" effect="plain">
              {{ statusLabel(detailDoc.status) }}
            </el-tag>
          </div>
          <div>
            <span class="meta-label">关联订单</span>
            <el-button link type="primary" @click="openOrder(detailDoc)">{{ detailDoc.order_no || '—' }}</el-button>
          </div>
          <div>
            <span class="meta-label">时间</span>{{ formatTime(detailDoc.posted_at || detailDoc.created_at) }}
          </div>
          <div v-if="detailDoc.notes"><span class="meta-label">备注</span>{{ detailDoc.notes }}</div>
        </div>
        <el-table
          :data="detailDoc.lines || []"
          stripe
          border
          size="small"
          empty-text="无明细"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column column-key="image" label="图" :width="colWidth1('image', 64)" align="center" resizable>
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                preview-teleported
                fit="cover"
                class="doc-thumb"
              />
              <span v-else class="doc-thumb doc-thumb-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="supplier_product_code"
            label="编码"
            :width="colWidth1('supplier_product_code', 120)"
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="名称"
            :width="colWidth1('supplier_product_name', 160)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button
          v-if="detailDoc?.status === 'pending' && canConfirm"
          type="primary"
          :loading="actionId === detailDoc?.id"
          @click="confirmDoc(detailDoc!)"
        >
          {{ confirmActionLabel(detailDoc) }}
        </el-button>
        <el-button
          v-if="detailDoc?.status === 'pending' && canVoid"
          :loading="actionId === detailDoc?.id"
          @click="voidDoc(detailDoc!)"
        >
          作废
        </el-button>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.inv-panel {
  min-width: 0;
}
.stock-dir-tabs {
  margin: 0 0 4px;
}
.stock-dir-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.docs-table :deep(.el-table__row) {
  cursor: pointer;
}
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.meta-label {
  color: var(--el-text-color-secondary);
  margin-right: 8px;
}
.doc-thumb {
  width: 36px;
  height: 36px;
  border-radius: 4px;
  display: inline-block;
  vertical-align: middle;
  background: #f8fafc;
}
.doc-thumb-empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 11px;
}
</style>
