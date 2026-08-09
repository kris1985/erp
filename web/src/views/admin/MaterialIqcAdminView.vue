<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">来料 IQC</h1>
        <p class="page-desc">到货待检 · 合格/让步后入池 · 不合格不占齐套</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-select v-model="statusFilter" style="width: 140px" @change="load">
          <el-option label="待检" value="pending" />
          <el-option label="合格" value="passed" />
          <el-option label="让步接收" value="conceded" />
          <el-option label="不合格" value="failed" />
          <el-option label="全部" value="" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
      </div>
      <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无 IQC 记录">
        <el-table-column prop="po_no" label="采购单" min-width="120" />
        <el-table-column prop="supplier_product_code" label="物料" min-width="110" />
        <el-table-column prop="supplier_product_name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="size_value" label="尺码" width="72" />
        <el-table-column prop="qty" label="数量" width="88" align="right" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="登记时间" width="160" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button link type="success" @click="decide(row, 'pass')">合格</el-button>
              <el-button link type="warning" @click="decide(row, 'concede')">让步</el-button>
              <el-button link type="danger" @click="decide(row, 'fail')">不合格</el-button>
            </template>
            <span v-else class="muted">{{ row.note || '—' }}</span>
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

const loading = ref(false)
const rows = ref<any[]>([])
const statusFilter = ref('pending')

function statusLabel(s: string) {
  return (
    (
      {
        pending: '待检',
        passed: '合格',
        failed: '不合格',
        conceded: '让步接收',
      } as Record<string, string>
    )[s] || s
  )
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/material-iqc', {
      params: { status: statusFilter.value || undefined, limit: 100 },
    })
    rows.value = Array.isArray(res.data) ? res.data : []
  } finally {
    loading.value = false
  }
}

async function decide(row: any, decision: string) {
  const labels: Record<string, string> = {
    pass: '合格入池',
    concede: '让步接收并入池',
    fail: '判不合格（不入池）',
  }
  try {
    const { value } = await ElMessageBox.prompt(
      `确认对 ${row.supplier_product_code || ''} × ${row.qty} ${labels[decision]}？可选填备注`,
      '来料 IQC',
      { confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '备注（可选）' },
    )
    await http.post(`/material-iqc/${row.id}/decide`, { decision, note: value || undefined })
    ElMessage.success('已判定')
    await load()
  } catch (e: any) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) return
    ElMessage.error(e?.response?.data?.detail || e?.message || '判定失败')
  }
}

onMounted(load)
</script>

<style scoped>
.muted {
  color: #94a3b8;
}
</style>
