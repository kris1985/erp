<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">质量不良</h1>
        <p class="page-desc">不良事件 · 责任追溯</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.order_no"
          clearable
          placeholder="订单号"
          style="width: 140px"
          @change="reload"
        />
        <el-select
          v-model="filters.responsible_worker_id"
          clearable
          filterable
          placeholder="责任人"
          style="width: 140px"
          @change="reload"
        >
          <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
        <el-select
          v-model="filters.defect_type"
          clearable
          placeholder="类型"
          style="width: 120px"
          @change="reload"
        >
          <el-option
            v-for="t in defectTypes"
            :key="t.code"
            :label="t.name"
            :value="t.code"
          />
        </el-select>
        <el-select
          v-model="filters.status"
          clearable
          placeholder="状态"
          style="width: 110px"
          @change="reload"
        >
          <el-option label="开放" value="open" />
          <el-option label="已关闭" value="closed" />
        </el-select>
        <el-button @click="load">刷新</el-button>
        <div class="spacer" />
        <el-button type="primary" @click="openCreate">无码登记</el-button>
      </div>

      <div v-if="summaryText" class="muted" style="margin-bottom: 12px">{{ summaryText }}</div>

      <el-table :data="rows" stripe border>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="order_no" label="订单" width="100" />
        <el-table-column prop="trace_code" label="捆标" width="120" />
        <el-table-column label="色码" width="100">
          <template #default="{ row }">
            {{ row.color_name || '—' }} {{ row.size_value || '' }}
          </template>
        </el-table-column>
        <el-table-column prop="defect_type_name" label="类型" width="90" />
        <el-table-column prop="qty" label="数量" width="70" />
        <el-table-column prop="responsible_process_name" label="责任工序" width="100" />
        <el-table-column prop="responsible_worker_name" label="责任人" width="90" />
        <el-table-column prop="disposition" label="处置" width="90">
          <template #default="{ row }">{{ dispLabel(row.disposition) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">{{ row.status === 'closed' ? '已关闭' : '开放' }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'closed'"
              link
              type="primary"
              @click="closeEvent(row)"
            >
              关闭
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
          :page-sizes="[10, 20, 50]"
          @current-change="load"
          @size-change="() => { page = 1; load() }"
        />
      </div>
    </div>

    <el-dialog v-model="createVisible" title="无码登记不良" width="480px">
      <el-form label-width="100px">
        <el-form-item label="订单号" required>
          <el-input v-model="form.order_no" placeholder="如 230711" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.defect_type" style="width: 100%">
            <el-option v-for="t in defectTypes" :key="t.code" :label="t.name" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" required>
          <el-input-number v-model="form.qty" :min="1" />
        </el-form-item>
        <el-form-item label="责任工序">
          <el-select v-model="form.responsible_process_id" clearable filterable style="width: 100%">
            <el-option v-for="p in processes" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任人">
          <el-select v-model="form.responsible_worker_id" clearable filterable style="width: 100%">
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <div class="muted" style="margin-top: 4px">集体工序可只选工序、不指定人</div>
        </el-form-item>
        <el-form-item label="处置">
          <el-select v-model="form.disposition" style="width: 100%">
            <el-option label="返修" value="rework" />
            <el-option label="报废" value="scrap" />
            <el-option label="让步接收" value="concession" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createEvent">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const workers = ref<any[]>([])
const processes = ref<any[]>([])
const defectTypes = ref<{ code: string; name: string }[]>([])
const summary = ref<{ by_worker: any[]; by_type: any[] }>({ by_worker: [], by_type: [] })
const filters = reactive({
  order_no: '',
  responsible_worker_id: null as number | null,
  defect_type: '',
  status: '',
})
const createVisible = ref(false)
const saving = ref(false)
const form = reactive({
  order_no: '',
  defect_type: '',
  qty: 1,
  responsible_process_id: null as number | null,
  responsible_worker_id: null as number | null,
  disposition: 'rework',
  note: '',
})

const summaryText = computed(() => {
  const parts: string[] = []
  if (summary.value.by_type?.length) {
    parts.push(
      '类型：' + summary.value.by_type.slice(0, 4).map((x) => `${x.name}${x.qty}`).join('、'),
    )
  }
  if (summary.value.by_worker?.length) {
    parts.push(
      '责任人：' +
        summary.value.by_worker.slice(0, 4).map((x) => `${x.name}${x.qty}`).join('、'),
    )
  }
  return parts.join(' · ')
})

function formatTime(v?: string) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : ''
}

function dispLabel(d: string) {
  const map: Record<string, string> = { rework: '返修', scrap: '报废', concession: '让步' }
  return map[d] || d
}

function reload() {
  page.value = 1
  void load()
}

async function load() {
  const res: any = await http.get('/defect-events', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      order_no: filters.order_no || undefined,
      responsible_worker_id: filters.responsible_worker_id || undefined,
      defect_type: filters.defect_type || undefined,
      status: filters.status || undefined,
    },
  })
  rows.value = res.data?.items || []
  total.value = res.data?.total || 0
  summary.value = res.data?.summary || { by_worker: [], by_type: [] }
}

async function loadMeta() {
  const [wRes, pRes, tRes]: any[] = await Promise.all([
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/processes'),
    http.get('/defect-types'),
  ])
  workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
  processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
  defectTypes.value = tRes.data?.items || []
}

function openCreate() {
  form.order_no = filters.order_no || ''
  form.defect_type = defectTypes.value[0]?.code || ''
  form.qty = 1
  form.responsible_process_id = null
  form.responsible_worker_id = null
  form.disposition = 'rework'
  form.note = ''
  createVisible.value = true
}

async function createEvent() {
  if (!form.order_no.trim() || !form.defect_type || !form.qty) {
    ElMessage.warning('请填写订单、类型和数量')
    return
  }
  saving.value = true
  try {
    await http.post('/defect-events', {
      order_no: form.order_no.trim(),
      defect_type: form.defect_type,
      qty: form.qty,
      responsible_process_id: form.responsible_process_id,
      responsible_worker_id: form.responsible_worker_id,
      disposition: form.disposition,
      note: form.note || null,
      auto_suggest_worker: false,
    })
    ElMessage.success('已登记')
    createVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function closeEvent(row: any) {
  await ElMessageBox.confirm(`关闭不良 #${row.id}？`, '确认')
  await http.patch(`/defect-events/${row.id}`, { status: 'closed' })
  ElMessage.success('已关闭')
  await load()
}

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>
