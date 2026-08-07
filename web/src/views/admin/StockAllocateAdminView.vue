<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('stock-allocate-list')
const auth = useAuthStore()
const loading = ref(false)
const keyword = ref('')
const rows = ref<any[]>([])

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/stock-allocate/candidates', {
      params: { keyword: keyword.value || undefined },
    })
    rows.value = res.data || []
  } finally {
    loading.value = false
    void nextTick(measureTableHeight)
  }
}

async function doAllocate(row: any) {
  if (!auth.hasPermission('btn.stock_allocate.write') && auth.role !== 'admin') {
    ElMessage.warning('无锁料权限')
    return
  }
  const max = Number(row.allocatable_qty) || 0
  if (max <= 0) {
    ElMessage.warning('池中可锁数量为 0')
    return
  }
  const { value } = await ElMessageBox.prompt(
    `从库存池锁料到订单 ${row.order_no}（最多 ${formatNum(max)}）`,
    '锁料到订单',
    {
      inputValue: String(max),
      inputPattern: /^\d+(\.\d+)?$/,
      inputErrorMessage: '请输入数量',
    },
  )
  const qty = Number(value)
  if (!(qty > 0)) return
  await http.post(`/orders/${row.order_id}/materials/${row.id}/allocate`, { qty })
  ElMessage.success('已锁料')
  load()
}

async function doDeallocate(row: any) {
  if (!auth.hasPermission('btn.stock_allocate.write') && auth.role !== 'admin') {
    ElMessage.warning('无回收权限')
    return
  }
  const max = Number(row.reusable_qty) || 0
  if (max <= 0) {
    ElMessage.warning('无可回收占用')
    return
  }
  const { value } = await ElMessageBox.prompt(
    `将订单 ${row.order_no} 未发占用收回库存池（最多 ${formatNum(max)}）`,
    '回收到池',
    {
      inputValue: String(max),
      inputPattern: /^\d+(\.\d+)?$/,
      inputErrorMessage: '请输入数量',
    },
  )
  const qty = Number(value)
  if (!(qty > 0)) return
  await http.post(`/orders/${row.order_id}/materials/${row.id}/deallocate`, { qty })
  ElMessage.success('已回收')
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">锁料（高级）</h1>
        <p class="page-desc">
          仅在多单抢料、先锁后发时使用。日常请走「领料/退料」：确认即归属并发到车间。
        </p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="订单号 / 物料"
          style="width: 220px"
          @keyup.enter="load"
        />
        <el-button type="primary" @click="load">查询</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table v-loading="loading" :data="rows" stripe border style="width: 100%" :max-height="tableMaxHeight" @header-dragend="onHeaderDragend">
        <el-table-column column-key="order" label="订单" :width="colWidth('order', 120)" resizable>
          <template #default="{ row }">
            <span>{{ row.order_no }}</span>
            <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 6px">急</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料" :width="colWidth('supplier_product_code', 100)" resizable />
        <el-table-column prop="supplier_product_name" label="名称" :width="colWidth('supplier_product_name', 140)" resizable />
        <el-table-column column-key="required" label="需求" :width="colWidth('required', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.required_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="allocated" label="已占用" :width="colWidth('allocated', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.arrived_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="shortage" label="缺口" :width="colWidth('shortage', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.need_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="pool_balance" label="池余额" :width="colWidth('pool_balance', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.pool_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="lockable" label="可锁" :width="colWidth('lockable', 70)" align="right" resizable>
          <template #default="{ row }">
            <strong>{{ formatNum(row.allocatable_qty) }}</strong>
          </template>
        </el-table-column>
        <el-table-column column-key="reclaimable" label="可回收" :width="colWidth('reclaimable', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.reusable_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 160)" resizable>
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :disabled="!(Number(row.allocatable_qty) > 0)"
              @click="doAllocate(row)"
            >
              锁料
            </el-button>
            <el-button
              link
              size="small"
              :disabled="!(Number(row.reusable_qty) > 0)"
              @click="doDeallocate(row)"
            >
              回收
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>
  </div>
</template>
