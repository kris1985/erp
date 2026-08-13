<template>
  <div class="h5-shell">
  <div class="page page--solo">
    <h1 class="page-title">扫码报工</h1>
    <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>
    <template v-else-if="station">
      <div class="card-block">
        <div style="font-weight: 600">{{ station.name }}</div>
        <div class="muted">编码 {{ station.code }} · 工序 {{ station.process_name }}</div>
        <div v-if="station.location" class="muted">{{ station.location }}</div>
        <div class="muted" style="margin-top: 8px; font-size: 12px">
          有货上主码时请扫捆标「报本工序」；本页工位仅锁定工序或无卡时兜底选单。
        </div>
      </div>

      <div v-if="!auth.token || auth.actor !== 'worker'" class="card-block">
        <p class="muted">请先用员工账号登录后再报工</p>
        <van-button type="primary" block round @click="goLogin">去登录</van-button>
      </div>

      <template v-else>
        <div v-if="candidatesLoading" class="card-block muted">加载可报任务…</div>

        <template v-else>
          <div v-if="selected" class="card-block">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
              <div style="flex: 1; min-width: 0">
                <div style="font-weight: 600">任务 {{ selected.order_no }}</div>
                <div class="muted">{{ selected.customer_name }}</div>
                <div class="muted">
                  {{ selected.completed_qty }}/{{ selected.plan_qty }}
                  <template v-if="selected.remaining_quota != null">
                    · 剩余配额 {{ selected.remaining_quota }}
                  </template>
                </div>
              </div>
              <ProgressRing
                :completed="selected.completed_qty"
                :plan="selected.plan_qty"
                :size="64"
                label="本工序"
              />
              <van-button
                v-if="candidates.length > 1"
                size="small"
                plain
                type="primary"
                @click="orderPickerVisible = true"
              >
                更换
              </van-button>
            </div>
          </div>

          <div v-else class="card-block">
            <p class="muted" style="margin: 0">
              暂无可报任务（未派工或配额已满）。请联系主管派工/改配额，或手动输入单号
            </p>
          </div>

          <van-form @submit="onSubmit">
            <van-cell-group inset>
              <van-field
                v-if="manualMode || !selected"
                v-model="manualOrderNo"
                label="单号"
                placeholder="如 EX-…"
                required
              />

              <!-- 唯一色码：静默默认，仅展示只读摘要 -->
              <van-cell v-if="skuMode === 'single'" title="色码" :value="skuSummary" />

              <!-- 多色码：点选，默认上次 -->
              <template v-else-if="skuMode === 'multi'">
                <van-field
                  :model-value="skuSummary || '请选择色码'"
                  is-link
                  readonly
                  label="色码"
                  placeholder="选择颜色尺码"
                  required
                  @click="skuPickerVisible = true"
                />
              </template>

              <!-- 无明细 / 手动单：自由填写 -->
              <template v-else>
                <van-field v-model="colorName" label="颜色" placeholder="可选，如 红" />
                <van-field v-model="sizeValue" label="尺码" placeholder="可选，如 37" />
              </template>

              <van-field v-model="qty" type="digit" label="数量" placeholder="双" required />
              <van-field
                :model-value="reportTypeLabel"
                is-link
                readonly
                label="类型"
                @click="typePickerVisible = true"
              />
            </van-cell-group>

            <div style="margin: 8px 20px">
              <van-button
                v-if="candidates.length && !manualMode"
                size="small"
                type="primary"
                plain
                hairline
                @click="enableManual"
              >
                找不到？输入单号
              </van-button>
              <van-button
                v-else-if="manualMode && candidates.length"
                size="small"
                plain
                hairline
                @click="disableManual"
              >
                返回已派工单
              </van-button>
            </div>

            <div class="big-btn" style="margin: 16px 16px 24px">
              <van-button round block type="primary" native-type="submit" :loading="loading">
                提交报工
              </van-button>
            </div>

            <div v-if="lastReport" class="card-block report-success">
              <div class="report-success__title">报工成功</div>
              <div class="report-success__wage">
                暂估 ¥{{ Number(lastReport.amount || 0).toFixed(2) }}
              </div>
              <div class="muted" style="margin-top: 6px">
                单价 ¥{{ Number(lastReport.unit_price || 0).toFixed(3) }}
                · {{ lastReport.process_name }}
                ·
                <template v-if="lastReport.report_type === 'rework'">
                  返修 {{ lastReport.rework_qty }}
                </template>
                <template v-else>合格 {{ lastReport.qualified_qty }}</template>
              </div>
              <div class="muted" style="margin-top: 8px; white-space: pre-wrap">{{ lastReport.message }}</div>
              <van-button
                v-if="lastReport.print_trace_label && lastReport.trace_code"
                style="margin-top: 12px"
                block
                round
                type="primary"
                plain
                @click="$router.push(`/trace-print/${lastReport.trace_code}`)"
              >
                打印捆标 {{ lastReport.trace_code }}
              </van-button>
              <van-button
                v-else-if="lastReport.trace_code"
                style="margin-top: 12px"
                block
                round
                plain
                @click="$router.push(`/trace/${lastReport.trace_code}`)"
              >
                查看捆标 {{ lastReport.trace_code }}
              </van-button>
            </div>
          </van-form>
        </template>
      </template>
    </template>

    <van-popup v-model:show="orderPickerVisible" position="bottom" round>
      <div style="padding: 12px 16px; font-weight: 600">选择任务</div>
      <van-radio-group v-model="selectedOrderNo">
        <van-cell-group>
          <van-cell
            v-for="c in candidates"
            :key="c.header_id ? `h${c.header_id}` : c.order_id"
            clickable
            :title="c.order_no"
            :label="`${c.customer_name} · ${c.completed_qty}/${c.plan_qty}`"
            @click="chooseCandidate(c)"
          >
            <template #right-icon>
              <van-radio :name="c.order_no" />
            </template>
          </van-cell>
        </van-cell-group>
      </van-radio-group>
    </van-popup>

    <van-popup v-model:show="skuPickerVisible" position="bottom" round>
      <div style="padding: 12px 16px; font-weight: 600">选择色码</div>
      <van-radio-group :model-value="skuKey">
        <van-cell-group>
          <van-cell
            v-for="sku in skuOptions"
            :key="skuKeyOf(sku)"
            clickable
            :title="formatSku(sku)"
            :label="sku.qty ? `计划 ${sku.qty}` : undefined"
            @click="chooseSku(sku)"
          >
            <template #right-icon>
              <van-radio :name="skuKeyOf(sku)" />
            </template>
          </van-cell>
        </van-cell-group>
      </van-radio-group>
    </van-popup>

    <van-popup v-model:show="typePickerVisible" position="bottom" round>
      <div style="padding: 12px 16px; font-weight: 600">报工类型</div>
      <van-radio-group v-model="reportType">
        <van-cell-group>
          <van-cell
            v-for="t in reportTypes"
            :key="t.value"
            clickable
            :title="t.label"
            :label="t.hint"
            @click="reportType = t.value; typePickerVisible = false"
          >
            <template #right-icon>
              <van-radio :name="t.value" />
            </template>
          </van-cell>
        </van-cell-group>
      </van-radio-group>
    </van-popup>
  </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import axios from 'axios'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import ProgressRing from '@/components/ProgressRing.vue'

type Sku = {
  color_id?: number | null
  color_name?: string | null
  size_id?: number | null
  size_value?: string | null
  qty?: number
}

type Candidate = {
  order_id?: number | null
  header_id?: number | null
  order_no: string
  customer_name?: string | null
  plan_qty: number
  completed_qty: number
  status: string
  process_status: string
  remaining_quota?: number | null
  last_reported_at?: string | null
  items?: Sku[]
  last_color_name?: string | null
  last_size_value?: string | null
}

const SKU_STORAGE_PREFIX = 'scan_sku:'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const station = ref<any>(null)
const error = ref('')
const candidates = ref<Candidate[]>([])
const candidatesLoading = ref(false)
const selectedOrderNo = ref('')
const manualMode = ref(false)
const manualOrderNo = ref('')
const colorName = ref('')
const sizeValue = ref('')
const qty = ref('')
const loading = ref(false)
const lastReport = ref<any>(null)
const orderPickerVisible = ref(false)
const skuPickerVisible = ref(false)
const typePickerVisible = ref(false)
const reportType = ref('normal')
const reportTypes = [
  { value: 'normal', label: '正常', hint: '常规计件' },
  { value: 'rework', label: '返修', hint: '按返修单价' },
  { value: 'supplement', label: '补数', hint: '按补数单价计入进度' },
  { value: 'tail', label: '尾数', hint: '按尾数单价计入进度' },
]

const reportTypeLabel = computed(
  () => reportTypes.find((t) => t.value === reportType.value)?.label || '正常',
)

const selected = computed(() => candidates.value.find((c) => c.order_no === selectedOrderNo.value) || null)

const skuOptions = computed<Sku[]>(() => {
  if (manualMode.value || !selected.value) return []
  return selected.value.items || []
})

const skuMode = computed<'single' | 'multi' | 'free'>(() => {
  if (manualMode.value || !selected.value) return 'free'
  const n = skuOptions.value.length
  if (n === 1) return 'single'
  if (n > 1) return 'multi'
  return 'free'
})

const skuKey = computed(() => `${colorName.value || ''}|${sizeValue.value || ''}`)

const skuSummary = computed(() => {
  if (!colorName.value && !sizeValue.value) return ''
  return [colorName.value, sizeValue.value].filter(Boolean).join(' / ')
})

function skuKeyOf(sku: Sku) {
  return `${sku.color_name || ''}|${sku.size_value || ''}`
}

function formatSku(sku: Sku) {
  return [sku.color_name, sku.size_value].filter(Boolean).join(' / ') || '未命名'
}

function storageKey(id: number | string) {
  return `${SKU_STORAGE_PREFIX}${id}`
}

function candidateStorageId(c: Candidate) {
  return c.order_id ?? (c.header_id != null ? `h${c.header_id}` : c.order_no)
}

function readStoredSku(id: number | string): { color_name: string; size_value: string } | null {
  try {
    const raw = localStorage.getItem(storageKey(id))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && (parsed.color_name || parsed.size_value)) return parsed
  } catch {
    /* ignore */
  }
  return null
}

function writeStoredSku(id: number | string, color: string, size: string) {
  try {
    localStorage.setItem(storageKey(id), JSON.stringify({ color_name: color, size_value: size }))
  } catch {
    /* ignore */
  }
}

function applySkuDefaults(c: Candidate | null) {
  if (!c) {
    colorName.value = ''
    sizeValue.value = ''
    return
  }
  const items = c.items || []
  if (items.length === 1) {
    colorName.value = items[0].color_name || ''
    sizeValue.value = items[0].size_value || ''
    return
  }
  if (items.length > 1) {
    const stored = readStoredSku(candidateStorageId(c))
    const candidatesSku = [
      stored,
      c.last_color_name || c.last_size_value
        ? { color_name: c.last_color_name || '', size_value: c.last_size_value || '' }
        : null,
    ].filter(Boolean) as { color_name: string; size_value: string }[]

    for (const pref of candidatesSku) {
      const hit = items.find(
        (it) => (it.color_name || '') === pref.color_name && (it.size_value || '') === pref.size_value,
      )
      if (hit) {
        colorName.value = hit.color_name || ''
        sizeValue.value = hit.size_value || ''
        return
      }
    }
    // 无历史：不强制第一项，留空让用户点选
    colorName.value = ''
    sizeValue.value = ''
    return
  }
  colorName.value = ''
  sizeValue.value = ''
}

function goLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

function chooseCandidate(c: Candidate) {
  selectedOrderNo.value = c.order_no
  manualMode.value = false
  orderPickerVisible.value = false
  applySkuDefaults(c)
}

function chooseSku(sku: Sku) {
  colorName.value = sku.color_name || ''
  sizeValue.value = sku.size_value || ''
  skuPickerVisible.value = false
}

function enableManual() {
  manualMode.value = true
  manualOrderNo.value = selectedOrderNo.value || ''
  colorName.value = ''
  sizeValue.value = ''
}

function disableManual() {
  manualMode.value = false
  if (!selectedOrderNo.value && candidates.value.length) {
    selectedOrderNo.value = candidates.value[0].order_no
  }
  applySkuDefaults(selected.value)
}

async function loadStation() {
  const code = String(route.params.code || '')
  const res = await axios.get(`/api/v1/stations/by-code/${encodeURIComponent(code)}`)
  if (!res.data?.ok) {
    error.value = res.data?.error?.message || '工位不存在'
    return
  }
  station.value = res.data.data
  if (station.value?.code) {
    localStorage.setItem('erp_station_code', station.value.code)
  }
}

async function loadCandidates() {
  if (!auth.token || auth.actor !== 'worker' || !station.value) return
  candidatesLoading.value = true
  try {
    const res: any = await http.get(
      `/stations/by-code/${encodeURIComponent(station.value.code)}/report-candidates`,
    )
    const data = res.data || {}
    candidates.value = data.items || []
    selectedOrderNo.value = data.default_order_no || candidates.value[0]?.order_no || ''
    manualMode.value = candidates.value.length === 0
    applySkuDefaults(selected.value)
  } finally {
    candidatesLoading.value = false
  }
}

onMounted(async () => {
  try {
    await loadStation()
    await loadCandidates()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '工位不存在或已停用'
  }
})

watch(
  () => [auth.token, auth.actor],
  () => {
    if (auth.token && auth.actor === 'worker' && station.value) {
      loadCandidates()
    }
  },
)

watch(selectedOrderNo, () => {
  if (!manualMode.value) applySkuDefaults(selected.value)
})

async function onSubmit() {
  if (!station.value || !auth.workerId) return
  const orderNo = manualMode.value || !selected.value ? manualOrderNo.value.trim() : selectedOrderNo.value
  const n = Number(qty.value)
  if (!orderNo || !n) {
    showToast('请选择/填写单号并填写数量')
    return
  }
  if (skuMode.value === 'multi' && !colorName.value && !sizeValue.value) {
    showToast('请选择色码')
    skuPickerVisible.value = true
    return
  }
  loading.value = true
  lastReport.value = null
  try {
    const res: any = await http.post('/reports', {
      worker_id: auth.workerId,
      order_no: orderNo,
      process_name: station.value.process_name,
      color_name: colorName.value || null,
      size_value: sizeValue.value || null,
      qualified_qty: n,
      source: 'qrcode',
      station_id: station.value.id,
      confirm_over_plan: true,
      report_type: reportType.value,
    })
    if (res.data?.need_confirm) {
      lastReport.value = { message: res.data.message, amount: 0, unit_price: 0 }
      showToast('需确认超额')
      return
    }
    if (selected.value && (colorName.value || sizeValue.value)) {
      writeStoredSku(candidateStorageId(selected.value), colorName.value, sizeValue.value)
    }
    lastReport.value = res.data
    showToast(`报工成功 · 暂估 ¥${Number(res.data.amount || 0).toFixed(2)}`)
    qty.value = ''
    await loadCandidates()
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.report-success {
  background: rgba(52, 199, 89, 0.1);
  box-shadow: none;
}
.report-success__title {
  font-weight: 600;
  color: #248a3d;
}
.report-success__wage {
  margin-top: 8px;
  font-family: var(--ws-font-num);
  font-size: 32px;
  font-weight: 700;
  color: var(--ws-primary);
  letter-spacing: -0.03em;
}
</style>
