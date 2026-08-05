<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

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

const docs = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const docsLoading = ref(false)
const actionId = ref<number | null>(null)
const keyword = ref('')
const docType = ref('')
const statusFilter = ref('pending')
const orderKeyword = ref('')
const orderOptions = ref<any[]>([])
const selectedOrderId = ref<number | null>(null)

const detailVisible = ref(false)
const detailDoc = ref<any | null>(null)

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatTime(v: any) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

function docTypeLabel(row: any) {
  if (!row) return '—'
  return row.doc_type === 'issue' ? row.issue_kind || '领料' : '退料'
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

async function searchOrders(q: string) {
  orderKeyword.value = q
  const res: any = await http.get('/orders', {
    params: { page: 1, page_size: 20, q: q || undefined },
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
        doc_type: docType.value || undefined,
        status: statusFilter.value || undefined,
      },
    })
    const payload = res.data
    let list = payload?.items || (Array.isArray(payload) ? payload : [])
    const q = keyword.value.trim().toLowerCase()
    if (q) {
      list = list.filter((d: any) => {
        const hay = [d.doc_no, d.order_no, d.notes, d.issue_kind].join(' ').toLowerCase()
        return hay.includes(q)
      })
    }
    docs.value = list
    total.value = payload?.total ?? list.length
  } finally {
    docsLoading.value = false
  }
}

function search() {
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
  if (!row.order_id) return
  router.push({ path: '/admin/orders', query: { open: String(row.order_id) } })
}

async function confirmDoc(row: any, e?: Event) {
  e?.stopPropagation?.()
  const label = row.doc_type === 'issue' ? '确认发料' : '确认退料'
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
  await searchOrders('')
  const oid = Number(route.query.order_id)
  if (oid > 0) selectedOrderId.value = oid
  const st = String(route.query.status || '')
  if (st) statusFilter.value = st
  await loadDocs()
})
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">领退料记录</h1>
        <p class="page-desc">
          车间在订单用料里提报；仓管在此确认过账。默认看「待确认」。
        </p>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select
          v-model="selectedOrderId"
          filterable
          remote
          clearable
          placeholder="按订单筛选"
          style="width: 240px"
          :remote-method="searchOrders"
          @change="search"
          @focus="searchOrders(orderKeyword)"
        >
          <el-option
            v-for="o in orderOptions"
            :key="o.id"
            :label="`${o.order_no} · ${o.customer_name || ''}`"
            :value="o.id"
          />
        </el-select>
        <el-select v-model="docType" clearable placeholder="类型" style="width: 110px" @change="search">
          <el-option label="领料" value="issue" />
          <el-option label="退料" value="return_mat" />
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

      <el-table
        v-loading="docsLoading"
        :data="docs"
        stripe
        border
        style="width: 100%"
        empty-text="暂无单据"
        class="docs-table"
        @row-click="openDetail"
      >
        <el-table-column prop="doc_no" label="单号" min-width="120" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.doc_type === 'issue' ? 'success' : 'warning'" size="small">
              {{ docTypeLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="订单" min-width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="openOrder(row, $event)">{{ row.order_no || '—' }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="过账/提报" min-width="160">
          <template #default="{ row }">{{ formatTime(row.posted_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="notes" label="原因/备注" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">明细</el-button>
            <el-button
              v-if="row.status === 'pending' && canConfirm"
              link
              type="success"
              :loading="actionId === row.id"
              @click="confirmDoc(row, $event)"
            >
              {{ row.doc_type === 'issue' ? '确认发料' : '确认退料' }}
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
      :title="detailDoc ? `${docTypeLabel(detailDoc)} · ${detailDoc.doc_no}` : '单据明细'"
      width="720px"
      destroy-on-close
    >
      <template v-if="detailDoc">
        <div class="detail-meta">
          <div>
            <span class="meta-label">状态</span>
            <el-tag :type="statusTagType(detailDoc.status)" size="small" effect="plain">
              {{ statusLabel(detailDoc.status) }}
            </el-tag>
          </div>
          <div>
            <span class="meta-label">订单</span>
            <el-button link type="primary" @click="openOrder(detailDoc)">{{ detailDoc.order_no || '—' }}</el-button>
          </div>
          <div>
            <span class="meta-label">时间</span>{{ formatTime(detailDoc.posted_at || detailDoc.created_at) }}
          </div>
          <div v-if="detailDoc.notes"><span class="meta-label">备注</span>{{ detailDoc.notes }}</div>
        </div>
        <el-table :data="detailDoc.lines || []" stripe border size="small" empty-text="无明细">
          <el-table-column label="图" width="64" align="center">
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
          <el-table-column prop="supplier_product_code" label="编码" min-width="120" />
          <el-table-column prop="supplier_product_name" label="名称" min-width="160" show-overflow-tooltip />
          <el-table-column label="数量" width="100" align="right">
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
          {{ detailDoc?.doc_type === 'issue' ? '确认发料' : '确认退料' }}
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
