<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">库存池</h1>
        <p class="page-desc">
          池余额 = 未锁给订单 · 已占用 = 已分单未发出 · 在途 = 采购未收量 · 点「流水」看出入记录
        </p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="物料编码 / 名称"
          style="width: 220px"
          @clear="load"
          @keyup.enter="load"
        />
        <el-button type="primary" @click="openAdjust()">调整库存</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="filteredRows" stripe border style="width: 100%" v-loading="loading">
        <el-table-column label="图片" width="72" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              preview-teleported
              fit="cover"
              class="product-thumb"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料编码" min-width="120" />
        <el-table-column prop="supplier_product_name" label="物料名称" min-width="160" />
        <el-table-column label="池余额" min-width="90" align="right">
          <template #default="{ row }">
            <strong>{{ formatNum(row.pool_qty ?? row.qty) }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="已占用" min-width="90" align="right">
          <template #default="{ row }">
            <span :class="{ warn: Number(row.occupied_qty) > 0 }">{{ formatNum(row.occupied_qty) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="在途" min-width="90" align="right">
          <template #default="{ row }">
            <span :class="{ warn: Number(row.in_transit_qty) > 0 }">{{ formatNum(row.in_transit_qty) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_unit_cost" label="均价" min-width="80" align="right">
          <template #default="{ row }">{{ formatNum(row.avg_unit_cost) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openLedger(row)">流水</el-button>
            <el-button link size="small" @click="openAdjust(row)">调整</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="ledgerVisible" :title="ledgerTitle" size="560px" destroy-on-close>
      <el-table v-loading="ledgerLoading" :data="ledgers" stripe border size="small" empty-text="暂无出入记录">
        <el-table-column label="时间" min-width="140">
          <template #default="{ row }">
            {{ String(row.created_at || '').replace('T', ' ').slice(0, 19) || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="类型" min-width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="ledgerTagType(row.ledger_type)" effect="plain">
              {{ row.ledger_type_label || row.ledger_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数量" min-width="90" align="right">
          <template #default="{ row }">
            <span :class="Number(row.qty_delta) >= 0 ? 'in' : 'out'">
              {{ Number(row.qty_delta) >= 0 ? '+' : '' }}{{ formatNum(row.qty_delta) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="余额后" min-width="80" align="right">
          <template #default="{ row }">{{ formatNum(row.balance_after) }}</template>
        </el-table-column>
        <el-table-column label="订单" min-width="100">
          <template #default="{ row }">{{ row.order_no || '—' }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
      </el-table>
    </el-drawer>

    <el-dialog v-model="adjustVisible" title="调整库存池" width="440px">
      <el-form label-width="100px">
        <el-form-item label="物料">
          <el-select
            v-model="form.supplier_product_id"
            filterable
            remote
            clearable
            placeholder="搜索物料"
            style="width: 100%"
            :remote-method="searchProducts"
            :loading="productLoading"
          >
            <el-option
              v-for="p in productOptions"
              :key="p.id"
              :label="`${p.product_code} · ${p.name || ''}`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="增减数量">
          <el-input-number v-model="form.qty_delta" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单价(入库)">
          <el-input-number v-model="form.unit_cost" :min="0" :step="0.01" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注" required>
          <el-input v-model="form.note" placeholder="盘盈/盘亏原因（必填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" @click="doAdjust">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const loading = ref(false)
const keyword = ref('')
const adjustVisible = ref(false)
const ledgerVisible = ref(false)
const ledgerLoading = ref(false)
const ledgers = ref<any[]>([])
const ledgerTitle = ref('出入流水')
const productOptions = ref<any[]>([])
const productLoading = ref(false)
const form = reactive({
  supplier_product_id: null as number | null,
  qty_delta: 0,
  unit_cost: undefined as number | undefined,
  note: '',
})

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => {
    const hay = `${r.supplier_product_code || ''} ${r.supplier_product_name || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function ledgerTagType(t: string) {
  if (t === 'unallocated_receive' || t === 'receive_surplus' || t === 'release_from_order') return 'success'
  if (t === 'allocate_to_order' || t === 'issue_to_order') return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/shared-materials')
    rows.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function searchProducts(q: string) {
  productLoading.value = true
  try {
    const res: any = await http.get('/supplier-products', {
      params: { page: 1, page_size: 30, keyword: q || undefined, active_only: true },
    })
    productOptions.value = res.data?.items || res.data || []
  } finally {
    productLoading.value = false
  }
}

function openAdjust(row?: any) {
  form.supplier_product_id = row?.supplier_product_id || null
  form.qty_delta = 0
  form.unit_cost = undefined
  form.note = ''
  if (row) {
    productOptions.value = [
      {
        id: row.supplier_product_id,
        product_code: row.supplier_product_code,
        name: row.supplier_product_name,
      },
    ]
  } else {
    searchProducts('')
  }
  adjustVisible.value = true
}

async function openLedger(row: any) {
  ledgerTitle.value = `流水 · ${row.supplier_product_code || ''} ${row.supplier_product_name || ''}`
  ledgerVisible.value = true
  ledgerLoading.value = true
  try {
    const res: any = await http.get('/shared-materials/ledgers', {
      params: { supplier_product_id: row.supplier_product_id, limit: 200 },
    })
    ledgers.value = res.data || []
  } finally {
    ledgerLoading.value = false
  }
}

async function doAdjust() {
  if (!form.supplier_product_id) {
    ElMessage.warning('请选择物料')
    return
  }
  if (!form.qty_delta) {
    ElMessage.warning('请填写增减数量')
    return
  }
  const note = (form.note || '').trim()
  if (!note) {
    ElMessage.warning('请填写备注')
    return
  }
  await http.post('/shared-materials/adjust', {
    supplier_product_id: form.supplier_product_id,
    qty_delta: form.qty_delta,
    unit_cost: form.unit_cost,
    note,
  })
  ElMessage.success('已调整')
  adjustVisible.value = false
  load()
}

onMounted(load)
</script>

<style scoped>
.product-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  border-radius: 4px;
}
.muted {
  color: var(--el-text-color-secondary);
}
.warn {
  color: var(--el-color-warning);
  font-weight: 600;
}
.in {
  color: var(--el-color-success);
  font-weight: 600;
}
.out {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
