<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">应收 / 客户欠款</h1>
        <p class="page-desc">出货挂账 · 账龄 · 调账</p>
      </div>
    </header>
    <div class="admin-card" style="margin-bottom: 16px">
      <div style="font-weight: 600; margin-bottom: 8px">客户汇总</div>
      <el-table :data="summary" stripe border size="small" style="width: 100%">
        <el-table-column prop="customer_name" label="客户" min-width="140" />
        <el-table-column prop="balance" label="未收" min-width="100" />
        <el-table-column label="0-30天" min-width="90">
          <template #default="{ row }">{{ row.aging?.['0-30'] }}</template>
        </el-table-column>
        <el-table-column label="31-60天" min-width="90">
          <template #default="{ row }">{{ row.aging?.['31-60'] }}</template>
        </el-table-column>
        <el-table-column label="60+天" min-width="90">
          <template #default="{ row }">{{ row.aging?.['60+'] }}</template>
        </el-table-column>
      </el-table>
    </div>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-button @click="load">刷新</el-button>
      </div>
      <el-table :data="rows" stripe border style="width: 100%">
        <el-table-column prop="receivable_date" label="日期" min-width="110" />
        <el-table-column prop="customer_name" label="客户" min-width="120" />
        <el-table-column prop="order_id" label="订单ID" min-width="90" />
        <el-table-column prop="amount" label="应收" min-width="90" />
        <el-table-column prop="adjustment" label="调账" min-width="80" />
        <el-table-column prop="received_amount" label="已收" min-width="90" />
        <el-table-column prop="balance" label="未收" min-width="90" />
        <el-table-column label="账龄" min-width="90">
          <template #default="{ row }">{{ ageBucketLabel(row.age_bucket) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">{{ arStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'void' && row.status !== 'settled'"
              link
              type="primary"
              @click="adjust(row)"
            >调账</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const summary = ref<any[]>([])

const AR_STATUS: Record<string, string> = {
  open: '未收',
  partial: '部分已收',
  settled: '已结清',
  void: '已作废',
}

function arStatusLabel(s: string) {
  return AR_STATUS[s] || s || '—'
}

function ageBucketLabel(s: string) {
  if (s === '0-30') return '0–30天'
  if (s === '31-60') return '31–60天'
  if (s === '60+') return '60天以上'
  return s || '—'
}

async function load() {
  const [a, b]: any[] = await Promise.all([
    http.get('/receivables'),
    http.get('/receivables/customer-summary'),
  ])
  rows.value = a.data || []
  summary.value = b.data || []
}

async function adjust(row: any) {
  const { value } = await ElMessageBox.prompt('调账金额（可为负，如折让）', '应收调账', {
    inputValue: '0',
  })
  await http.post(`/receivables/${row.id}/adjust`, { adjustment_delta: Number(value) })
  ElMessage.success('已调账')
  load()
}

onMounted(load)
</script>
