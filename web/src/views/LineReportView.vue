<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <h1 class="page-title">线产量报工</h1>
      <p class="muted" style="margin: 0 16px 12px; font-size: 13px">
        履带/流水线按「线」报产量：组长/统计员报一次，系统按技能系数自动拆给线上成员。
      </p>

      <div v-if="error" class="card-block" style="color: #c00">{{ error }}</div>

      <template v-else>
        <van-form @submit="onSubmit">
          <van-cell-group inset>
            <!-- 线（班组） -->
            <van-field
              :model-value="teamLabel"
              is-link
              readonly
              label="线 / 班组"
              placeholder="请选择"
              required
              @click="teamPickerVisible = teams.length ? true : false"
            />
            <!-- 出勤成员 -->
            <van-field
              :model-value="memberSummary || '默认全员参与拆分'"
              is-link
              readonly
              label="出勤成员"
              placeholder="默认全员"
              :disabled="!selectedTeamId"
              @click="memberPickerVisible = true"
            />
            <!-- 执行单 -->
            <van-field
              :model-value="headerLabel"
              is-link
              readonly
              label="执行单"
              placeholder="请选择在制单"
              required
              :disabled="!selectedTeamId"
              @click="headerPickerVisible = headers.length ? true : false"
            />
            <!-- 颜色（可选） -->
            <van-field
              v-model="colorName"
              label="颜色"
              placeholder="可选，如 红"
              clearable
            />
          </van-cell-group>

          <van-cell-group inset style="margin-top: 12px">
            <van-field
              v-model="qualifiedQty"
              type="digit"
              label="合格"
              placeholder="双"
              required
            />
            <van-field
              v-model="defectQty"
              type="digit"
              label="不良"
              placeholder="0"
            />
            <van-field
              v-model="reworkQty"
              type="digit"
              label="返修"
              placeholder="0"
            />
            <van-field
              v-model="note"
              label="备注"
              placeholder="可选"
              maxlength="100"
            />
          </van-cell-group>

          <div v-if="selectedHeader" class="card-block" style="margin-top: 12px">
            <div style="display: flex; justify-content: space-between; align-items: center">
              <div style="font-weight: 600">{{ selectedHeader.header_no }}</div>
              <span class="muted">{{ selectedHeader.product_code }}</span>
            </div>
            <div class="muted">{{ selectedHeader.customer_name }}</div>
            <div class="muted" style="margin-top: 6px">
              计划 {{ selectedHeader.total_qty }} · 已完工 {{ selectedHeader.completed_qty }}
            </div>
          </div>

          <div class="big-btn" style="margin: 16px 16px 24px">
            <van-button round block type="primary" native-type="submit" :loading="submitting">
              提交线产量
            </van-button>
          </div>
        </van-form>

        <div v-if="result" class="card-block report-success">
          <div class="report-success__title">报工成功</div>
          <div class="report-success__wage">¥{{ Number(result.amount || 0).toFixed(2) }}</div>
          <div class="muted" style="margin-top: 6px">
            拆给 {{ result.work_log_count }} 名成员 · 约 ¥{{ Number(result.amount || 0).toFixed(2) }}
          </div>
          <div class="muted" style="margin-top: 8px; white-space: pre-wrap">{{ result.message }}</div>
        </div>
      </template>
    </div>

    <!-- 选出勤成员 -->
    <van-popup v-model:show="memberPickerVisible" position="bottom" round>
      <div style="padding: 12px 16px; font-weight: 600">本次参与拆分的成员</div>
      <p class="muted" style="margin: 0 16px 8px; font-size: 12px">勾掉请假/缺勤的人，未勾选者不参与本次计件拆分</p>
      <div style="padding: 0 16px 16px; max-height: 50vh; overflow-y: auto">
        <van-checkbox-group v-model="memberIds">
          <van-checkbox
            v-for="m in teamMemberOptions"
            :key="m.id"
            :name="m.id"
            shape="square"
            style="margin-bottom: 12px"
          >
            {{ m.name }}
          </van-checkbox>
        </van-checkbox-group>
      </div>
    </van-popup>

    <!-- 选线 -->
    <van-popup v-model:show="teamPickerVisible" position="bottom" round>
      <div style="padding: 12px 16px; font-weight: 600">选择线 / 班组</div>
      <van-cell-group>
        <van-cell
          v-for="t in teams"
          :key="t.id"
          clickable
          :title="t.name"
          :label="`${t.segment_name || '未挂段'} · ${t.member_count || 0} 人`"
          @click="chooseTeam(t)"
        >
          <template #right-icon><van-icon name="success" v-if="t.id === selectedTeamId" /></template>
        </van-cell>
        <van-cell v-if="!teams.length" title="暂无你带队的班组" label="请联系管理员建组并挂工序段" />
      </van-cell-group>
    </van-popup>

    <!-- 选执行单 -->
    <van-popup v-model:show="headerPickerVisible" position="bottom" round style="max-height: 80vh">
      <div style="padding: 12px 16px; font-weight: 600">选择在制执行单</div>
      <van-search
        v-model="headerKeyword"
        placeholder="搜单号/款号/客户"
        @update:model-value="loadHeaders"
      />
      <div style="overflow-y: auto; max-height: 55vh">
        <van-cell-group>
          <van-cell
            v-for="h in headers"
            :key="h.id"
            clickable
            :title="h.header_no"
            :label="`${h.product_code || ''} · ${h.customer_name || ''} · 完工 ${h.completed_qty}/${h.total_qty}`"
            @click="chooseHeader(h)"
          >
            <template #right-icon><van-icon name="success" v-if="h.id === selectedHeaderId" /></template>
          </van-cell>
          <van-cell v-if="!headers.length" title="无在制单" label="请先在后台确认生产/排产" />
        </van-cell-group>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type TeamItem = {
  id: number
  name: string
  segment_id?: number | null
  segment_name?: string | null
  member_count?: number
  members?: { id: number; name: string }[]
  leader_worker_id?: number | null
  leader_name?: string | null
}

type HeaderItem = {
  id: number
  header_no: string
  product_code?: string | null
  customer_name?: string | null
  total_qty: number
  completed_qty: number
  color_name?: string | null
  status: string
}

const auth = useAuthStore()

const error = ref('')
const teams = ref<TeamItem[]>([])
const headers = ref<HeaderItem[]>([])
const selectedTeamId = ref<number | null>(null)
const selectedHeaderId = ref<number | null>(null)
const headerKeyword = ref('')
const colorName = ref('')
const qualifiedQty = ref('')
const defectQty = ref('')
const reworkQty = ref('')
const note = ref('')
const submitting = ref(false)
const result = ref<any>(null)

const teamPickerVisible = ref(false)
const headerPickerVisible = ref(false)
const memberPickerVisible = ref(false)

const selectedTeam = computed(() => teams.value.find((t) => t.id === selectedTeamId.value) || null)
const selectedHeader = computed(() => headers.value.find((h) => h.id === selectedHeaderId.value) || null)

const memberIds = ref<number[]>([])

function memberOptionsOf(t: TeamItem | null) {
  if (!t) return []
  const map = new Map<number, { id: number; name: string }>()
  for (const m of t.members || []) map.set(m.id, { id: m.id, name: m.name })
  if (t.leader_worker_id && !map.has(t.leader_worker_id)) {
    map.set(t.leader_worker_id, { id: t.leader_worker_id, name: t.leader_name || '组长' })
  }
  return Array.from(map.values())
}

const teamMemberOptions = computed(() => memberOptionsOf(selectedTeam.value))
const memberSummary = computed(() => {
  const opts = teamMemberOptions.value
  if (!opts.length) return ''
  const sel = memberIds.value
  const names = opts.filter((m) => sel.includes(m.id)).map((m) => m.name)
  return `${sel.length}/${opts.length} 人 · ${names.join('、') || '未选'}`
})

const teamLabel = computed(() => selectedTeam.value?.name || '')
const headerLabel = computed(() => selectedHeader.value?.header_no || '')

async function loadTeams() {
  try {
    const res: any = await http.get('/teams/mine')
    const items = (res.data?.items || []) as TeamItem[]
    // 只显示挂段班组（线产量报工要求班组挂工序段）
    teams.value = items.filter((t) => t.segment_id != null)
    if (teams.value.length === 1) {
      selectedTeamId.value = teams.value[0].id
      memberIds.value = memberOptionsOf(teams.value[0]).map((m) => m.id)
      loadHeaders()
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '仅组长/统计员可报线产量，请确认你有带队的班组'
  }
}

async function loadHeaders() {
  if (!selectedTeamId.value) return
  try {
    const kw = headerKeyword.value.trim()
    const res: any = await http.get('/executions', {
      params: { status: 'in_progress', limit: 100, q: kw || undefined },
    })
    headers.value = (res.data?.items || []) as HeaderItem[]
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '加载在制单失败'
  }
}

function chooseTeam(t: TeamItem) {
  selectedTeamId.value = t.id
  selectedHeaderId.value = null
  colorName.value = ''
  teamPickerVisible.value = false
  memberIds.value = memberOptionsOf(t).map((m) => m.id)
  loadHeaders()
}

function chooseHeader(h: HeaderItem) {
  selectedHeaderId.value = h.id
  // 单色头自动带出颜色
  if (h.color_name && !colorName.value) colorName.value = h.color_name
  headerPickerVisible.value = false
}

async function doSubmit(confirmOverPlan: boolean) {
  const qty = Number(qualifiedQty.value)
  const dqty = Number(defectQty.value || 0)
  const rqty = Number(reworkQty.value || 0)
  if (!selectedTeamId.value || !selectedHeaderId.value) {
    showToast('请选择线和执行单')
    return
  }
  if (!qty && !dqty) {
    showToast('请填写合格或不良数量')
    return
  }
  submitting.value = true
  result.value = null
  try {
    const res: any = await http.post('/line-reports', {
      header_id: selectedHeaderId.value,
      team_id: selectedTeamId.value,
      qualified_qty: qty,
      defect_qty: dqty,
      rework_qty: rqty,
      defect_type: '质检不良',
      color_name: colorName.value.trim() || null,
      note: note.value.trim() || null,
      member_ids: memberIds.value,
      confirm_over_plan: confirmOverPlan,
    })
    if (res.data?.need_confirm) {
      showConfirmDialog({
        title: '将超计划',
        message: res.data.message || '本次报工将超过计划数，确认继续？',
      })
        .then(() => doSubmit(true))
        .catch(() => {})
      return
    }
    result.value = res.data
    showToast('线产量已报')
    qualifiedQty.value = ''
    defectQty.value = ''
    reworkQty.value = ''
    note.value = ''
  } finally {
    submitting.value = false
  }
}

function onSubmit() {
  doSubmit(false)
}

onMounted(loadTeams)
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
