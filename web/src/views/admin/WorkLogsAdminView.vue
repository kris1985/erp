<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">报工记录</h1>
        <p class="page-desc">审核 · 申诉 · 更正</p>
      </div>
    </header>
  <div class="admin-card">
    <div class="admin-toolbar">
      <el-select v-model="filters.worker_id" clearable placeholder="员工" style="width: 140px" @change="reloadFromFilter">
        <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <el-input v-model="filters.order_no" clearable placeholder="订单号" style="width: 140px" @change="reloadFromFilter" />
      <el-select v-model="filters.status" clearable placeholder="状态" style="width: 120px" @change="reloadFromFilter">
        <el-option label="有效" value="valid" />
        <el-option label="作废" value="void" />
        <el-option label="申诉" value="appealed" />
        <el-option label="更正" value="corrected" />
      </el-select>
      <el-button @click="load">刷新</el-button>
      <div class="spacer" />
      <el-button v-if="filters.status !== 'appealed'" @click="filters.status = 'appealed'; reloadFromFilter()">
        看待审申诉
      </el-button>
    </div>
    <el-table :data="rows" stripe border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column prop="worker_name" label="员工" width="90" />
      <el-table-column prop="order_no" label="订单" width="100" />
      <el-table-column prop="process_name" label="工序" width="90" />
      <el-table-column prop="report_type" label="类型" width="80">
        <template #default="{ row }">{{ typeLabel(row.report_type) }}</template>
      </el-table-column>
      <el-table-column label="色码" width="100">
        <template #default="{ row }">
          {{ row.color_name || '—' }} {{ row.size_value || '' }}
        </template>
      </el-table-column>
      <el-table-column prop="qualified_qty" label="合格" width="70" />
      <el-table-column prop="rework_qty" label="返修" width="70" />
      <el-table-column prop="defect_qty" label="不良" width="70" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">{{ statusLabel(row.status) }}</template>
      </el-table-column>
      <el-table-column prop="review_note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'valid'">
            <el-button link type="primary" @click="openCorrect(row)">改数</el-button>
            <el-button link type="danger" @click="voidLog(row)">作废</el-button>
          </template>
          <template v-else-if="row.status === 'appealed'">
            <el-button link type="success" @click="rejectAppeal(row)">驳回</el-button>
            <el-button link type="primary" @click="openCorrect(row)">改数</el-button>
            <el-button link type="danger" @click="voidLog(row)">作废</el-button>
          </template>
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
        @current-change="load"
        @size-change="onPageSizeChange"
      />
    </div>

    <el-dialog v-model="correctVisible" title="改数更正" width="440px">
      <p class="muted" style="margin: 0 0 12px">
        原单 #{{ correctRow?.id }} 将标记为「更正」并回滚进度，再按新数量重新入账。
        <span v-if="correctRow?.group_id">集体报工会整组一并更正。</span>
      </p>
      <el-form label-width="90px">
        <el-form-item v-if="correctRow?.report_type === 'rework'" label="返修数量">
          <el-input-number v-model="correctForm.rework_qty" :min="1" />
        </el-form-item>
        <template v-else>
          <el-form-item label="合格数量">
            <el-input-number v-model="correctForm.qualified_qty" :min="0" />
          </el-form-item>
          <el-form-item label="不良数量">
            <el-input-number v-model="correctForm.defect_qty" :min="0" />
          </el-form-item>
        </template>
        <el-form-item label="颜色">
          <el-input v-model="correctForm.color_name" placeholder="可空" />
        </el-form-item>
        <el-form-item label="尺码">
          <el-input v-model="correctForm.size_value" placeholder="可空，如 37" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="correctForm.review_note" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctVisible = false">取消</el-button>
        <el-button type="primary" :loading="correctSaving" @click="saveCorrect">确认更正</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'

const workers = ref<any[]>([])
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filters = reactive<{ worker_id?: number; order_no?: string; status?: string }>({
  status: 'valid',
})
const correctVisible = ref(false)
const correctSaving = ref(false)
const correctRow = ref<any>(null)
const correctForm = reactive({
  qualified_qty: 0,
  defect_qty: 0,
  rework_qty: 0,
  color_name: '',
  size_value: '',
  review_note: '',
})

function typeLabel(t: string) {
  return (
    ({ normal: '正常', rework: '返修', group: '集体', supplement: '补数', tail: '尾数' } as any)[t] || t
  )
}

function statusLabel(s: string) {
  return ({ valid: '有效', appealed: '申诉中', void: '已作废', corrected: '已更正' } as any)[s] || s
}

async function load() {
  const res: any = await http.get('/work-logs', {
    params: {
      worker_id: filters.worker_id || undefined,
      order_no: filters.order_no || undefined,
      status: filters.status || undefined,
      page: page.value,
      page_size: pageSize.value,
    },
  })
  rows.value = res.data.items
  total.value = res.data.total || 0
  if (!rows.value.length && page.value > 1 && total.value > 0) {
    page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
    await load()
  }
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function reloadFromFilter() {
  page.value = 1
  void load()
}

async function voidLog(row: any) {
  const tip = row.group_id
    ? `确认作废报工 #${row.id}？集体报工会整组作废，回滚工序进度且不计工资。`
    : `确认作废报工 #${row.id}？将回滚工序进度且不计工资。`
  await ElMessageBox.confirm(tip, '作废确认')
  await http.patch(`/work-logs/${row.id}`, { status: 'void', review_note: '管理端作废' })
  ElMessage.success('已作废并回滚进度')
  await load()
}

async function rejectAppeal(row: any) {
  await ElMessageBox.confirm(`驳回申诉 #${row.id}，恢复为有效并计薪？`, '驳回申诉')
  const res: any = await http.patch(`/work-logs/${row.id}`, {
    status: 'valid',
    review_note: '申诉驳回，维持原报工',
  })
  ElMessage.success(res.data?.message || '已驳回')
  await load()
}

function openCorrect(row: any) {
  correctRow.value = row
  const total =
    row.group_id && row.group_total_qty != null ? Number(row.group_total_qty) : Number(row.qualified_qty || 0)
  correctForm.qualified_qty = row.report_type === 'rework' ? 0 : total
  correctForm.defect_qty = row.defect_qty || 0
  correctForm.rework_qty = row.rework_qty || (row.report_type === 'rework' ? total : 0)
  correctForm.color_name = row.color_name || ''
  correctForm.size_value = row.size_value || ''
  correctForm.review_note = ''
  correctVisible.value = true
}

async function saveCorrect() {
  if (!correctRow.value) return
  correctSaving.value = true
  try {
    const res: any = await http.post(`/work-logs/${correctRow.value.id}/correct`, {
      qualified_qty: correctForm.qualified_qty,
      defect_qty: correctForm.defect_qty,
      rework_qty: correctForm.rework_qty,
      color_name: correctForm.color_name || null,
      size_value: correctForm.size_value || null,
      review_note: correctForm.review_note || null,
    })
    ElMessage.success(res.data?.message || '已更正')
    correctVisible.value = false
    await load()
  } finally {
    correctSaving.value = false
  }
}

onMounted(async () => {
  const w: any = await http.get('/workers', { params: { page_size: 200 } })
  workers.value = w.data.items
  await load()
})
</script>
