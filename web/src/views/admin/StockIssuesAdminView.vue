<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const canWrite = computed(
  () => auth.role === 'admin' || auth.hasPermission('btn.stock_issues.write'),
)

const orderKeyword = ref('')
const orderOptions = ref<any[]>([])
const selectedOrderId = ref<number | null>(null)
const candidates = ref<any[]>([])
const docs = ref<any[]>([])
const loading = ref(false)
const docsLoading = ref(false)
const posting = ref(false)
const qtyDraft = ref<Record<number, string>>({})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

async function searchOrders(q: string) {
  orderKeyword.value = q
  const res: any = await http.get('/orders', {
    params: { page: 1, page_size: 20, q: q || undefined },
  })
  orderOptions.value = res.data?.items || res.data || []
}

async function loadCandidates() {
  if (!selectedOrderId.value) {
    candidates.value = []
    return
  }
  loading.value = true
  try {
    const res: any = await http.get('/stock-issues/candidates', {
      params: { order_id: selectedOrderId.value },
    })
    candidates.value = res.data || []
    const draft: Record<number, string> = {}
    for (const row of candidates.value) {
      const issuable = Number(row.issuable_qty) || 0
      draft[row.id] = issuable > 0 ? String(issuable) : ''
    }
    qtyDraft.value = draft
  } finally {
    loading.value = false
  }
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const res: any = await http.get('/stock-issues', {
      params: { order_id: selectedOrderId.value || undefined },
    })
    docs.value = res.data || []
  } finally {
    docsLoading.value = false
  }
}

async function postDoc(docType: 'issue' | 'return_mat') {
  if (!canWrite.value) {
    ElMessage.warning('无开单权限')
    return
  }
  if (!selectedOrderId.value) {
    ElMessage.warning('请先选择订单')
    return
  }
  const lines: { requirement_id: number; qty: number }[] = []
  for (const row of candidates.value) {
    const raw = qtyDraft.value[row.id]
    if (raw === undefined || raw === '') continue
    const qty = Number(raw)
    if (!(qty > 0)) continue
    const max =
      docType === 'issue' ? Number(row.issuable_qty) || 0 : Number(row.returnable_qty) || 0
    if (qty > max) {
      ElMessage.warning(
        `${row.supplier_product_code} 超过可${docType === 'issue' ? '领' : '退'} ${formatNum(max)}`,
      )
      return
    }
    lines.push({ requirement_id: row.id, qty })
  }
  if (!lines.length) {
    ElMessage.warning('请填写数量')
    return
  }
  const label = docType === 'issue' ? '领料' : '退料'
  await ElMessageBox.confirm(`确认过账${label}单（${lines.length} 行）？`, label, {
    type: 'warning',
  })
  posting.value = true
  try {
    await http.post('/stock-issues', {
      doc_type: docType,
      order_id: selectedOrderId.value,
      lines,
    })
    ElMessage.success(`${label}单已过账`)
    await Promise.all([loadCandidates(), loadDocs()])
  } finally {
    posting.value = false
  }
}

watch(selectedOrderId, () => {
  loadCandidates()
  loadDocs()
})

onMounted(async () => {
  await searchOrders('')
  const oid = Number(route.query.order_id)
  if (oid > 0) {
    selectedOrderId.value = oid
    if (!orderOptions.value.some((o) => o.id === oid)) {
      try {
        const res: any = await http.get(`/orders/${oid}`)
        if (res.data) orderOptions.value = [res.data, ...orderOptions.value]
      } catch {
        /* ignore */
      }
    }
  } else {
    await loadDocs()
  }
})
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">领退料单</h1>
        <p class="page-desc">
          强制领料：从订单占用中领出发车间；退料减已发并回库存池 · 开裁前须已领
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
          placeholder="选择订单"
          style="width: 280px"
          :remote-method="searchOrders"
          @focus="searchOrders(orderKeyword)"
        >
          <el-option
            v-for="o in orderOptions"
            :key="o.id"
            :label="`${o.order_no} · ${o.customer_name || ''}`"
            :value="o.id"
          />
        </el-select>
        <el-button type="primary" :disabled="!selectedOrderId" :loading="loading" @click="loadCandidates">
          刷新可领
        </el-button>
        <el-button
          type="success"
          :disabled="!selectedOrderId || !canWrite"
          :loading="posting"
          @click="postDoc('issue')"
        >
          过账领料
        </el-button>
        <el-button
          :disabled="!selectedOrderId || !canWrite"
          :loading="posting"
          @click="postDoc('return_mat')"
        >
          过账退料
        </el-button>
      </div>

      <el-table v-loading="loading" :data="candidates" stripe border style="width: 100%" empty-text="请选择订单">
        <el-table-column prop="supplier_product_code" label="物料" min-width="100" />
        <el-table-column prop="supplier_product_name" label="名称" min-width="140" />
        <el-table-column label="需求" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.required_qty) }}</template>
        </el-table-column>
        <el-table-column label="已占用" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.arrived_qty) }}</template>
        </el-table-column>
        <el-table-column label="已发" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.issued_qty) }}</template>
        </el-table-column>
        <el-table-column label="可领" min-width="70" align="right">
          <template #default="{ row }">
            <strong>{{ formatNum(row.issuable_qty) }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="可退" min-width="70" align="right">
          <template #default="{ row }">{{ formatNum(row.returnable_qty) }}</template>
        </el-table-column>
        <el-table-column label="本次数量" min-width="120">
          <template #default="{ row }">
            <el-input v-model="qtyDraft[row.id]" size="small" placeholder="数量" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="admin-card" style="margin-top: 16px">
      <div class="admin-toolbar">
        <span style="font-weight: 600">最近单据</span>
        <el-button link type="primary" :loading="docsLoading" @click="loadDocs">刷新</el-button>
      </div>
      <el-table v-loading="docsLoading" :data="docs" stripe border style="width: 100%" empty-text="暂无单据">
        <el-table-column prop="doc_no" label="单号" min-width="120" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.doc_type === 'issue' ? 'success' : 'warning'" size="small">
              {{ row.doc_type === 'issue' ? '领料' : '退料' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="订单" min-width="110" />
        <el-table-column label="行数" width="70" align="right">
          <template #default="{ row }">{{ (row.lines || []).length }}</template>
        </el-table-column>
        <el-table-column label="过账时间" min-width="160">
          <template #default="{ row }">{{ row.posted_at || row.created_at || '—' }}</template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="120" show-overflow-tooltip />
      </el-table>
    </div>
  </div>
</template>
