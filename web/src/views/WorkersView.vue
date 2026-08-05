<template>
  <div class="page">
    <div class="h5-filter">
      <van-icon name="search" class="h5-filter__icon" />
      <input
        v-model="keyword"
        class="h5-filter__input"
        type="text"
        inputmode="search"
        enterkeyhint="search"
        placeholder="姓名 / 手机 / 职位"
      />
      <button
        v-if="keyword"
        type="button"
        class="h5-filter__clear"
        aria-label="清除"
        @click="keyword = ''"
      >
        <van-icon name="cross" />
      </button>
    </div>
    <van-button type="primary" block round style="margin-bottom: 12px" @click="openCreate">
      新增员工
    </van-button>

    <div v-if="teamEmpty" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      尚未配置班组，请联系管理员
    </div>
    <div v-else-if="!filteredItems.length" class="h5-empty">
      <div class="h5-empty__mark">◎</div>
      {{ keyword.trim() ? '无匹配员工' : '暂无员工' }}
    </div>
    <div v-else class="worker-list">
      <article v-for="w in filteredItems" :key="w.id" class="h5-list-card worker-card">
        <div class="worker-card__main">
          <div class="worker-card__avatar">{{ (w.name || '?').slice(0, 1) }}</div>
          <div class="worker-card__info">
            <div class="worker-card__top">
              <span class="worker-card__name">{{ w.name }}</span>
              <span class="h5-pill" :class="rolePill(w.role)">{{ roleLabel(w.role) }}</span>
            </div>
            <div class="worker-card__pos">{{ w.position_name || '未设置职位' }}</div>
            <div class="worker-card__mobile muted">{{ w.mobile || '无手机号' }}</div>
          </div>
          <a
            v-if="w.mobile"
            class="worker-card__call"
            :href="`tel:${w.mobile}`"
            aria-label="拨打电话"
            @click.stop
          >
            <van-icon name="phone-o" />
          </a>
        </div>
      </article>
    </div>

    <van-popup
      v-model:show="createShow"
      position="bottom"
      round
      closeable
      teleport="body"
      :z-index="3000"
      :style="{ height: '85%' }"
    >
      <div class="worker-create">
        <div class="worker-create__title">新增员工</div>
        <div class="worker-create__body">
          <van-cell-group inset>
            <van-field v-model="form.name" label="姓名" placeholder="张三" required />
            <van-field v-model="form.mobile" label="手机" placeholder="138..." type="tel" />
            <van-field
              :model-value="positionLabel"
              is-link
              readonly
              label="职位"
              placeholder="请选择"
              @click="posPickerShow = true"
            />
            <van-field
              :model-value="roleLabel(form.role)"
              is-link
              readonly
              label="角色"
              @click="rolePickerShow = true"
            />
            <van-field
              :model-value="salaryLabel(form.salary_model)"
              is-link
              readonly
              label="计薪方式"
              @click="salaryPickerShow = true"
            />
            <van-field v-model="form.base_salary" type="number" label="底薪" placeholder="0.00" />
            <van-field v-model="form.base_quota" type="digit" label="定额" placeholder="0" />
            <van-field v-model="form.bank_account_name" label="收款户名" placeholder="默认与姓名相同" />
            <van-field v-model="form.bank_account" label="银行卡号" placeholder="银行代发用" />
            <van-field v-model="form.bank_name" label="开户行" placeholder="如 工行XX支行" />
          </van-cell-group>
        </div>
        <div class="worker-create__foot big-btn">
          <van-button type="primary" block round :loading="saving" @click="create">保存</van-button>
        </div>
      </div>
    </van-popup>

    <van-popup v-model:show="posPickerShow" position="bottom" round teleport="body" :z-index="3100">
      <van-picker
        :columns="positionColumns"
        title="选择职位"
        @confirm="onPosConfirm"
        @cancel="posPickerShow = false"
      />
    </van-popup>

    <van-popup v-model:show="rolePickerShow" position="bottom" round teleport="body" :z-index="3100">
      <van-picker
        :columns="roleColumns"
        title="选择角色"
        @confirm="onRoleConfirm"
        @cancel="rolePickerShow = false"
      />
    </van-popup>

    <van-popup v-model:show="salaryPickerShow" position="bottom" round teleport="body" :z-index="3100">
      <van-picker
        :columns="salaryColumns"
        title="计薪方式"
        @confirm="onSalaryConfirm"
        @cancel="salaryPickerShow = false"
      />
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { showToast } from 'vant'
import http from '@/api/http'

const ROLE_LABELS: Record<string, string> = {
  worker: '工人',
  leader: '组长',
}

const SALARY_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  hourly: '计时',
  fixed: '固定',
}

const items = ref<any[]>([])
const keyword = ref('')
const teamEmpty = ref(false)
const positions = ref<any[]>([])
const createShow = ref(false)
const posPickerShow = ref(false)
const rolePickerShow = ref(false)
const salaryPickerShow = ref(false)
const saving = ref(false)

const filteredItems = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter((w) => {
    const hay = [w.name, w.mobile, w.position_name, ROLE_LABELS[w.role] || w.role]
      .map((x) => String(x || '').toLowerCase())
      .join(' ')
    return hay.includes(q)
  })
})

const form = reactive({
  name: '',
  mobile: '',
  position_id: null as number | null,
  role: 'worker',
  salary_model: 'pure_piece',
  base_salary: '0',
  base_quota: '0',
  bank_account: '',
  bank_name: '',
  bank_account_name: '',
})

const roleColumns = [
  { text: '工人', value: 'worker' },
  { text: '组长', value: 'leader' },
]

const salaryColumns = [
  { text: '纯计件', value: 'pure_piece' },
  { text: '底薪+计件', value: 'base_plus_piece' },
  { text: '计时', value: 'hourly' },
  { text: '固定', value: 'fixed' },
]

const positionColumns = computed(() => [
  { text: '不设置', value: null },
  ...positions.value
    .filter((p) => p.is_active !== false)
    .map((p) => ({ text: p.name, value: p.id })),
])

const positionLabel = computed(() => {
  if (!form.position_id) return ''
  return positions.value.find((p) => p.id === form.position_id)?.name || ''
})

function roleLabel(role?: string) {
  return ROLE_LABELS[role || ''] || role || '工人'
}

function salaryLabel(model?: string) {
  return SALARY_LABELS[model || ''] || model || '纯计件'
}

function rolePill(role?: string) {
  return role === 'leader' ? 'h5-pill--warn' : 'h5-pill--mute'
}

function resetForm() {
  form.name = ''
  form.mobile = ''
  form.position_id = null
  form.role = 'worker'
  form.salary_model = 'pure_piece'
  form.base_salary = '0'
  form.base_quota = '0'
  form.bank_account = ''
  form.bank_name = ''
  form.bank_account_name = ''
}

function openCreate() {
  resetForm()
  createShow.value = true
}

function onPosConfirm({ selectedOptions }: { selectedOptions: Array<{ text: string; value: number | null }> }) {
  form.position_id = selectedOptions[0]?.value ?? null
  posPickerShow.value = false
}

function onRoleConfirm({ selectedOptions }: { selectedOptions: Array<{ text: string; value: string }> }) {
  form.role = selectedOptions[0]?.value || 'worker'
  rolePickerShow.value = false
}

function onSalaryConfirm({ selectedOptions }: { selectedOptions: Array<{ text: string; value: string }> }) {
  form.salary_model = selectedOptions[0]?.value || 'pure_piece'
  salaryPickerShow.value = false
}

async function load() {
  const [wRes, pRes]: any[] = await Promise.all([http.get('/workers'), http.get('/positions')])
  teamEmpty.value = !!wRes.data?.team_empty
  items.value = wRes.data.items || []
  positions.value = pRes.data.items || []
}

async function create() {
  if (!form.name.trim()) {
    showToast('请填写姓名')
    return
  }
  saving.value = true
  try {
    await http.post('/workers', {
      name: form.name.trim(),
      mobile: form.mobile.trim() || undefined,
      position_id: form.position_id,
      role: form.role,
      salary_model: form.salary_model,
      base_salary: Number(form.base_salary || 0),
      base_quota: Number(form.base_quota || 0),
      bank_account: form.bank_account.trim() || null,
      bank_name: form.bank_name.trim() || null,
      bank_account_name: form.bank_account_name.trim() || null,
    })
    showToast('已保存')
    createShow.value = false
    resetForm()
    await load()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.worker-list {
  display: flex;
  flex-direction: column;
}

.worker-card {
  padding: 14px;
}

.worker-card__main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.worker-card__avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: linear-gradient(145deg, #4da0ff, #005fcc);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.worker-card__info {
  flex: 1;
  min-width: 0;
}

.worker-card__top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.worker-card__name {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--ws-ink);
}

.worker-card__pos {
  margin-top: 4px;
  font-size: 13px;
  color: var(--ws-ink-secondary, #3a3a3c);
}

.worker-card__mobile {
  margin-top: 2px;
  font-size: 13px;
}

.worker-card__call {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: rgba(52, 199, 89, 0.14);
  color: #248a3d;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  text-decoration: none;
  flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
}

.worker-card__call:active {
  transform: scale(0.94);
  background: rgba(52, 199, 89, 0.22);
}
</style>

<style>
.worker-create {
  box-sizing: border-box;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f2f2f7;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.worker-create__title {
  flex-shrink: 0;
  font-size: 17px;
  font-weight: 700;
  text-align: center;
  padding: 16px 48px 12px;
  letter-spacing: -0.02em;
  background: #fff;
}

.worker-create__body {
  flex: 1;
  overflow: auto;
  padding: 12px 0 16px;
  -webkit-overflow-scrolling: touch;
}

.worker-create__foot {
  flex-shrink: 0;
  padding: 12px 16px 16px;
  background: #fff;
  border-top: 0.5px solid rgba(60, 60, 67, 0.12);
}
</style>
