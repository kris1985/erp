<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type FgStockRow = {
  id: number
  own_product_id: number
  product_code: string | null
  color_id: number | null
  color_name: string | null
  size_id: number
  size_value: string | null
  qty: number
  updated_at: string | null
}

type FgLedgerRow = {
  id: number
  direction: string
  qty: number
  ref_type: string | null
  note: string | null
  trace_unit_code: string | null
  execution_no: string | null
  created_at: string | null
}

const loading = ref(false)
const rows = ref<FgStockRow[]>([])
const keyword = ref('')
const onlyPositive = ref(true)

const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('fg-stocks-list', tableRef, {
  product_code: 140,
  color_name: 100,
  size_value: 80,
  qty: 90,
  updated_at: 170,
  actions: 90,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const totalQty = computed(() => rows.value.reduce((s, r) => s + (Number(r.qty) || 0), 0))

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/fg-stocks', {
      params: {
        q: keyword.value.trim() || undefined,
        only_positive: onlyPositive.value,
        limit: 500,
      },
    })
    rows.value = res.data?.items || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function search() {
  void load()
}

const ledgerVisible = ref(false)
const ledgerLoading = ref(false)
const ledgerRows = ref<FgLedgerRow[]>([])
const ledgerTitle = ref('成品流水')

async function openLedgers(row: FgStockRow) {
  ledgerTitle.value = `流水 · ${row.product_code || row.own_product_id} / ${row.color_name || '-'} / ${row.size_value || '-'}`
  ledgerVisible.value = true
  ledgerLoading.value = true
  ledgerRows.value = []
  try {
    const res: any = await http.get(`/fg-stocks/${row.id}/ledgers`, { params: { limit: 200 } })
    ledgerRows.value = res.data?.items || []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载流水失败')
  } finally {
    ledgerLoading.value = false
  }
}

function directionLabel(d: string) {
  if (d === 'in') return '入库'
  if (d === 'out') return '出库'
  if (d === 'adjust') return '调整'
  return d
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">成品仓</h1>
        <p class="page-desc">款+色+码结存 · 筐完工入库增加 · 出货/直发扣减 · 点「流水」看出入记录</p>
      </div>
    </header>

    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="货号 / 颜色 / 尺码"
          style="width: 240px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-checkbox v-model="onlyPositive" @change="search">仅有库存</el-checkbox>
        <div class="spacer" />
        <span class="muted summary">结存合计 {{ totalQty }} 双 / {{ rows.length }} SKU</span>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="load">刷新</el-button>
      </div>

      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          border
          size="small"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="product_code"
            label="货号"
            :width="colWidth('product_code', 140)"
            resizable
          />
          <el-table-column
            prop="color_name"
            label="颜色"
            :width="colWidth('color_name', 100)"
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="size_value"
            label="尺码"
            :width="colWidth('size_value', 80)"
            align="center"
            resizable
          />
          <el-table-column
            prop="qty"
            label="结存"
            :width="colWidth('qty', 90)"
            align="right"
            resizable
          />
          <el-table-column
            prop="updated_at"
            label="更新时间"
            :width="colWidth('updated_at', 170)"
            resizable
          />
          <el-table-column
            label="操作"
            :width="colWidth('actions', 90)"
            fixed="right"
            resizable
          >
            <template #default="{ row }">
              <el-button link type="primary" @click="openLedgers(row)">流水</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-drawer v-model="ledgerVisible" :title="ledgerTitle" size="560px">
      <el-table v-loading="ledgerLoading" :data="ledgerRows" stripe border size="small">
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="方向" width="72" align="center">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'in' ? 'success' : row.direction === 'out' ? 'warning' : 'info'" size="small">
              {{ directionLabel(row.direction) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="qty" label="数量" width="72" align="right" />
        <el-table-column prop="trace_unit_code" label="筐码" min-width="110">
          <template #default="{ row }">{{ row.trace_unit_code || '—' }}</template>
        </el-table-column>
        <el-table-column prop="execution_no" label="执行单" min-width="120">
          <template #default="{ row }">{{ row.execution_no || '—' }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140">
          <template #default="{ row }">{{ row.note || row.ref_type || '—' }}</template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<style scoped>
.admin-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}
.spacer {
  flex: 1;
}
.summary {
  font-size: 13px;
}
.muted {
  color: var(--el-text-color-secondary);
}
</style>
