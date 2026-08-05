<template>
  <div class="page">
    <div class="page-title">捆标追溯</div>
    <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
    <template v-else-if="unit">
      <div class="card-block">
        <div style="font-weight: 700; font-size: 18px">{{ unit.code }}</div>
        <div class="muted" style="margin-top: 4px">
          {{ unit.unit_type === 'bundle' ? '捆标' : '单双' }} · {{ statusLabel(unit.status) }} ·
          {{ unit.qty }} 双
        </div>
        <div style="margin-top: 10px; font-weight: 600">订单 {{ unit.order_no }}</div>
        <div class="muted">{{ unit.customer_name || '—' }} · 款 {{ unit.product_code || '—' }}</div>
        <div class="muted">
          色码 {{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }}
        </div>
        <div class="muted">
          创建人 {{ unit.created_by_worker_name || '—' }}
          <span v-if="unit.current_process_name"> · 当前工序 {{ unit.current_process_name }}</span>
        </div>
      </div>

      <div class="card-block" style="display: flex; gap: 10px; flex-wrap: wrap">
        <van-button type="primary" round block style="flex: 1" @click="goReport">本捆报工</van-button>
        <van-button type="warning" plain round block style="flex: 1" @click="showDefect = true">
          登记不良
        </van-button>
        <van-button plain round block style="flex: 1" @click="goPrint">打印捆标</van-button>
      </div>

      <div class="card-block">
        <div style="font-weight: 600; margin-bottom: 8px">过站历程</div>
        <div v-if="!(unit.logs || []).length" class="muted">暂无记录</div>
        <div v-for="lg in unit.logs || []" :key="lg.id" class="log-row">
          <div>
            <b>{{ actionLabel(lg.action) }}</b>
            <span v-if="lg.process_name"> · {{ lg.process_name }}</span>
            <span v-if="lg.worker_name"> · {{ lg.worker_name }}</span>
            <span v-if="lg.qty"> · {{ lg.qty }}</span>
          </div>
          <div class="muted" style="font-size: 12px">
            {{ formatTime(lg.created_at) }}
            <span v-if="lg.note"> · {{ lg.note }}</span>
          </div>
        </div>
      </div>

      <div v-if="(unit.defects || []).length" class="card-block">
        <div style="font-weight: 600; margin-bottom: 8px">不良记录</div>
        <div v-for="d in unit.defects" :key="d.id" class="log-row">
          <div>
            <b>{{ d.defect_type_name }}</b> × {{ d.qty }}
            <span v-if="d.responsible_process_name"> · 责 {{ d.responsible_process_name }}</span>
            <span v-if="d.responsible_worker_name"> / {{ d.responsible_worker_name }}</span>
          </div>
          <div class="muted" style="font-size: 12px">{{ formatTime(d.created_at) }}</div>
        </div>
      </div>
    </template>

    <van-popup v-model:show="showDefect" position="bottom" round :style="{ maxHeight: '85%' }">
      <div style="padding: 16px">
        <div style="font-weight: 600; margin-bottom: 12px">登记不良</div>
        <van-form @submit="submitDefect">
          <van-cell-group inset>
            <van-field
              :model-value="defectTypeLabel"
              is-link
              readonly
              label="类型"
              placeholder="选择缺陷类型"
              required
              @click="typePicker = true"
            />
            <van-field v-model="defectQty" type="digit" label="数量" required />
            <van-field
              :model-value="foundProcessLabel"
              is-link
              readonly
              label="发现工序"
              placeholder="可选"
              @click="foundPicker = true"
            />
            <van-field
              :model-value="respProcessLabel"
              is-link
              readonly
              label="责任工序"
              placeholder="可选"
              @click="respPicker = true"
            />
            <van-field
              :model-value="respWorkerLabel"
              is-link
              readonly
              label="责任人"
              placeholder="可选，集体工序可空"
              @click="workerPicker = true"
            />
            <van-field
              :model-value="dispositionLabel"
              is-link
              readonly
              label="处置"
              @click="dispPicker = true"
            />
            <van-field v-model="defectNote" label="备注" placeholder="可选" />
          </van-cell-group>
          <div style="margin: 16px">
            <van-button round block type="primary" native-type="submit" :loading="defectLoading">
              提交
            </van-button>
          </div>
        </van-form>
      </div>
    </van-popup>

    <van-popup v-model:show="typePicker" position="bottom" round>
      <van-picker
        :columns="defectTypes.map((t) => ({ text: t.name, value: t.code }))"
        @confirm="onPickType"
        @cancel="typePicker = false"
      />
    </van-popup>
    <van-popup v-model:show="foundPicker" position="bottom" round>
      <van-picker
        :columns="processColumns"
        @confirm="onPickFound"
        @cancel="foundPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="respPicker" position="bottom" round>
      <van-picker
        :columns="processColumns"
        @confirm="onPickResp"
        @cancel="respPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="workerPicker" position="bottom" round>
      <van-picker
        :columns="workerColumns"
        @confirm="onPickWorker"
        @cancel="workerPicker = false"
      />
    </van-popup>
    <van-popup v-model:show="dispPicker" position="bottom" round>
      <van-picker
        :columns="dispositions"
        @confirm="onPickDisp"
        @cancel="dispPicker = false"
      />
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import axios from 'axios'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const unit = ref<any>(null)
const error = ref('')
const showDefect = ref(false)
const defectLoading = ref(false)
const defectTypes = ref<{ code: string; name: string }[]>([])
const processes = ref<any[]>([])
const workers = ref<any[]>([])

const defectType = ref('')
const defectQty = ref('1')
const foundProcessId = ref<number | null>(null)
const respProcessId = ref<number | null>(null)
const respWorkerId = ref<number | null>(null)
const disposition = ref('rework')
const defectNote = ref('')

const typePicker = ref(false)
const foundPicker = ref(false)
const respPicker = ref(false)
const workerPicker = ref(false)
const dispPicker = ref(false)

const dispositions = [
  { text: '返修', value: 'rework' },
  { text: '报废', value: 'scrap' },
  { text: '让步接收', value: 'concession' },
]

const defectTypeLabel = computed(
  () => defectTypes.value.find((t) => t.code === defectType.value)?.name || '',
)
const foundProcessLabel = computed(() => {
  const fromUnit = (unit.value?.order_processes || []).find(
    (p: any) => p.process_id === foundProcessId.value,
  )
  if (fromUnit) return fromUnit.process_name
  return processes.value.find((p) => p.id === foundProcessId.value)?.name || ''
})
const respProcessLabel = computed(() => {
  const fromUnit = (unit.value?.order_processes || []).find(
    (p: any) => p.process_id === respProcessId.value,
  )
  if (fromUnit) return fromUnit.process_name
  return processes.value.find((p) => p.id === respProcessId.value)?.name || ''
})
const respWorkerLabel = computed(() => {
  if (respWorkerId.value == null) return ''
  return workers.value.find((w) => w.id === respWorkerId.value)?.name || ''
})
const dispositionLabel = computed(
  () => dispositions.find((d) => d.value === disposition.value)?.text || '返修',
)

const processColumns = computed(() => {
  const fromUnit = (unit.value?.order_processes || []).map((p: any) => ({
    text: p.process_name,
    value: p.process_id,
  }))
  if (fromUnit.length) return [{ text: '不选', value: 0 }, ...fromUnit]
  return [
    { text: '不选', value: 0 },
    ...processes.value.map((p) => ({ text: p.name, value: p.id })),
  ]
})
const workerColumns = computed(() => [
  { text: '不指定（仅记工序）', value: 0 },
  ...workers.value.map((w) => ({ text: w.name, value: w.id })),
])

function statusLabel(s: string) {
  const map: Record<string, string> = {
    open: '待流转',
    in_process: '流转中',
    done: '完成',
    scrapped: '报废',
    split: '已拆分',
  }
  return map[s] || s
}

function actionLabel(a: string) {
  const map: Record<string, string> = {
    create: '打捆',
    report: '报工',
    inspect: '质检',
    split: '拆分',
    transfer: '转移',
  }
  return map[a] || a
}

function formatTime(v?: string | null) {
  if (!v) return ''
  return String(v).replace('T', ' ').slice(0, 19)
}

async function loadUnit() {
  const code = String(route.params.code || '')
  const res = await axios.get(`/api/v1/trace-units/by-code/${encodeURIComponent(code)}`)
  if (!res.data?.ok) {
    error.value = res.data?.error?.message || '捆标不存在'
    return
  }
  unit.value = res.data.data
}

async function loadMeta() {
  try {
    const typesRes: any = await axios.get('/api/v1/defect-types')
    defectTypes.value = typesRes.data?.data?.items || []
  } catch {
    defectTypes.value = []
  }
  if (!auth.token) return
  try {
    if (auth.actor !== 'worker') {
      const [pRes, wRes]: any[] = await Promise.all([
        http.get('/processes'),
        http.get('/workers', { params: { page_size: 200 } }),
      ])
      processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
      workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
    } else {
      // 员工端：用公开流程尽量少；从 masters 可能无权限，用简单列表接口
      try {
        const pRes: any = await http.get('/processes')
        processes.value = (pRes.data?.items || pRes.data || []).filter((x: any) => x.is_active !== false)
      } catch {
        processes.value = []
      }
      try {
        const wRes: any = await http.get('/workers', { params: { page_size: 200 } })
        workers.value = (wRes.data?.items || []).filter((x: any) => x.is_active !== false)
      } catch {
        workers.value = []
      }
    }
  } catch {
    /* ignore */
  }
}

function goLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

function goReport() {
  if (!unit.value) return
  if (!auth.token || auth.actor !== 'worker') {
    goLogin()
    return
  }
  router.push({
    path: '/trace-report',
    query: {
      code: unit.value.code,
      order_no: unit.value.order_no,
      color_name: unit.value.color_name || '',
      size_value: unit.value.size_value || '',
      qty: String(unit.value.qty || ''),
      process_name: unit.value.current_process_name || '',
      trace_unit_id: String(unit.value.id),
    },
  })
}

function goPrint() {
  if (!unit.value) return
  router.push({ path: `/trace-print/${unit.value.code}` })
}

function onPickType({ selectedOptions }: any) {
  defectType.value = selectedOptions[0]?.value || ''
  typePicker.value = false
}
function onPickFound({ selectedOptions }: any) {
  const v = selectedOptions[0]?.value
  foundProcessId.value = v ? Number(v) : null
  foundPicker.value = false
}
async function onPickResp({ selectedOptions }: any) {
  const v = selectedOptions[0]?.value
  respProcessId.value = v ? Number(v) : null
  respPicker.value = false
  if (respProcessId.value && unit.value && auth.token) {
    try {
      const res: any = await http.get(`/trace-units/${unit.value.id}/suggest-responsible`, {
        params: { process_id: respProcessId.value },
      })
      if (res.data?.worker_id) {
        respWorkerId.value = res.data.worker_id
        showToast(`已建议责任人：${res.data.worker_name || ''}`)
      }
    } catch {
      /* ignore */
    }
  }
}
function onPickWorker({ selectedOptions }: any) {
  const v = selectedOptions[0]?.value
  respWorkerId.value = v ? Number(v) : null
  workerPicker.value = false
}
function onPickDisp({ selectedOptions }: any) {
  disposition.value = selectedOptions[0]?.value || 'rework'
  dispPicker.value = false
}

async function submitDefect() {
  if (!unit.value) return
  if (!auth.token) {
    goLogin()
    return
  }
  if (!defectType.value) {
    showToast('请选择缺陷类型')
    return
  }
  const n = Number(defectQty.value)
  if (!n) {
    showToast('请填写数量')
    return
  }
  defectLoading.value = true
  try {
    await http.post('/defect-events', {
      defect_type: defectType.value,
      qty: n,
      trace_unit_id: unit.value.id,
      found_process_id: foundProcessId.value || null,
      responsible_process_id: respProcessId.value || null,
      responsible_worker_id: respWorkerId.value || null,
      disposition: disposition.value,
      note: defectNote.value || null,
    })
    showToast('不良已登记')
    showDefect.value = false
    await loadUnit()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '登记失败')
  } finally {
    defectLoading.value = false
  }
}

onMounted(async () => {
  try {
    await loadUnit()
    await loadMeta()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '捆标不存在'
  }
})

watch(
  () => route.params.code,
  () => {
    loadUnit().catch(() => {})
  },
)
</script>

<style scoped>
.log-row {
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}
.log-row:last-child {
  border-bottom: none;
}
</style>
