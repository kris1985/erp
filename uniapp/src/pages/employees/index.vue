<template>
  <app-nav-bar />
  <view class="page h5-emp" :class="{ 'h5-emp--dock': showDock }">
    <view v-if="!canSee" class="h5-emp-empty">没有员工管理权限</view>

    <template v-else-if="mode === 'list'">
      <view class="card h5-emp-search">
        <input :value="keyword" confirm-type="search" placeholder="搜姓名、手机" @input="onKeyword" @confirm="reload" />
        <text v-if="keyword" @click="clearKeyword">清除</text>
      </view>
      <scroll-view class="h5-emp-tabs" scroll-x :show-scrollbar="false">
        <text :class="{ on: !departmentId }" @click="pickDepartment(null)">全部</text>
        <text
          v-for="item in departmentTree"
          :key="item.id"
          :class="{ on: departmentId === item.id }"
          @click="pickDepartment(item.id)"
        >{{ item.name }}</text>
        <text :class="{ on: showLeft }" @click="toggleLeft">{{ showLeft ? '含离职' : '只看在职' }}</text>
      </scroll-view>

      <view v-if="!rows.length && !loading" class="h5-emp-empty">{{ keyword ? '没有匹配的员工' : '还没有员工' }}</view>
      <view v-for="row in rows" :key="row.id" class="card h5-emp-card" @click="openDetail(row)">
        <image v-if="row.photo_url" class="h5-emp-avatar" :src="displayImageUrl(row.photo_url)" mode="aspectFill" />
        <view v-else class="h5-emp-avatar h5-emp-avatar--empty">{{ initial(row.name) }}</view>
        <view class="h5-emp-card__main">
          <view class="h5-emp-card__title">
            <text class="h5-emp-name">{{ row.name }}</text>
            <text v-if="row.is_active === false" class="h5-emp-tag">离职</text>
          </view>
          <text class="h5-emp-meta">{{ summary(row) }}</text>
        </view>
        <view v-if="phoneOf(row)" class="h5-emp-call" @click.stop="callPhone(row.mobile)">打电话</view>
      </view>
      <view v-if="loadingMore" class="h5-emp-more">加载中…</view>
    </template>

    <template v-else-if="mode === 'detail' && current">
      <view class="card h5-emp-hero">
        <image v-if="current.photo_url" class="h5-emp-photo" :src="displayImageUrl(current.photo_url)" mode="aspectFill" @click="previewImage(current.photo_url)" />
        <view v-else class="h5-emp-photo h5-emp-avatar--empty">{{ initial(current.name) }}</view>
        <text class="h5-emp-name">{{ current.name }}</text>
        <text class="h5-emp-meta">{{ current.is_active === false ? '离职' : '在职' }} · {{ summary(current) }}</text>
      </view>
      <view class="card h5-emp-sheet">
        <view class="h5-emp-line"><text>手机</text><text>{{ current.mobile || '—' }}</text></view>
        <view class="h5-emp-line"><text>入职</text><text>{{ current.hire_date || '—' }}</text></view>
        <view v-if="current.leave_date" class="h5-emp-line"><text>离职</text><text>{{ current.leave_date }}</text></view>
        <view class="h5-emp-line"><text>身份证</text><text>{{ current.identity_card_no || '—' }}</text></view>
        <view class="h5-emp-line">
          <text>人像面</text>
          <text v-if="current.id_card_front_url" class="h5-emp-link" @click="previewIdCards(current.id_card_front_url)">查看</text>
          <text v-else>—</text>
        </view>
        <view class="h5-emp-line">
          <text>国徽面</text>
          <text v-if="current.id_card_back_url" class="h5-emp-link" @click="previewIdCards(current.id_card_back_url)">查看</text>
          <text v-else>—</text>
        </view>
        <view class="h5-emp-line"><text>紧急联系人</text><text>{{ emergencyText(current) }}</text></view>
        <view class="h5-emp-line"><text>部门</text><text>{{ current.department_name || '—' }}</text></view>
        <view class="h5-emp-line"><text>职务</text><text>{{ current.job_title_name || '—' }}</text></view>
        <view class="h5-emp-line"><text>工序</text><text>{{ (current.process_names || []).join('、') || '—' }}</text></view>
        <view class="h5-emp-line"><text>角色</text><text>{{ (current.role_names || []).join('、') || '生产员工' }}</text></view>
      </view>
      <view class="card h5-emp-sheet">
        <view class="h5-emp-line"><text>计薪</text><text>{{ salaryLabel(current.salary_model) }}</text></view>
        <view v-if="current.salary_model !== 'pure_piece'" class="h5-emp-line">
          <text>{{ current.salary_model === 'guaranteed_piece' ? '保底' : '底薪' }}</text>
          <text>{{ money(current.base_salary) }}</text>
        </view>
        <view v-if="current.salary_model === 'fixed'" class="h5-emp-line"><text>加班费/小时</text><text>{{ money(current.overtime_hourly_rate) }}</text></view>
        <view class="h5-emp-line"><text>餐补/天</text><text>{{ money(current.meal_allowance_daily) }}</text></view>
        <view class="h5-emp-line"><text>住宿补/天</text><text>{{ money(current.housing_allowance_daily) }}</text></view>
        <view class="h5-emp-line"><text>其它补/天</text><text>{{ money(current.other_allowance_daily) }}</text></view>
        <view class="h5-emp-line"><text>累计工资</text><text>{{ money(current.cumulative_wage) }}</text></view>
        <view class="h5-emp-line"><text>累计损失</text><text>{{ money(current.cumulative_loss) }}</text></view>
      </view>
      <view v-if="canWrite" class="card h5-emp-sheet">
        <view class="h5-emp-action" @click="current.is_active === false ? restore() : openLeave()">
          {{ current.is_active === false ? '复职' : '办理离职' }}
        </view>
        <view v-if="current.has_account" class="h5-emp-action" @click="resetPassword">重置密码</view>
      </view>
    </template>

    <template v-else-if="mode === 'form'">
      <view class="card h5-emp-sheet">
        <view class="h5-emp-photo-row">
          <image v-if="form.photo_url" class="h5-emp-photo" :src="displayImageUrl(form.photo_url)" mode="aspectFill" @click="previewImage(form.photo_url)" />
          <view v-else class="h5-emp-photo h5-emp-avatar--empty">{{ initial(form.name) || '照' }}</view>
          <view class="h5-emp-photo-ops">
            <text>照片选填</text>
            <!-- 拍照和相册都走系统选择器，H5、小程序、App 共用。 -->
            <view>
              <text @click="choosePhoto('camera', 'photo_url')">拍照</text>
              <text @click="choosePhoto('album', 'photo_url')">相册</text>
              <text v-if="form.photo_url" class="danger" @click="form.photo_url = ''">去掉</text>
            </view>
            <text v-if="photoUploadField === 'photo_url'" class="h5-emp-meta">上传中…</text>
          </view>
        </view>
        <text class="h5-emp-section">必填</text>
        <view class="h5-emp-field">
          <text class="h5-emp-label">姓名<text class="req">*</text></text>
          <input v-model="form.name" class="h5-emp-input" placeholder="请填写姓名" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">手机<text class="req">*</text></text>
          <input v-model="form.mobile" class="h5-emp-input" type="number" maxlength="20" placeholder="请填写手机号" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">入职日期<text class="req">*</text></text>
          <picker mode="date" :value="form.hire_date" @change="form.hire_date = $event.detail.value">
            <view class="h5-emp-pick" :class="{ 'is-empty': !form.hire_date }">
              <text>{{ form.hire_date || '选择入职日期' }}</text>
              <text class="h5-emp-pick__chev">›</text>
            </view>
          </picker>
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">部门<text class="req">*</text></text>
          <view class="h5-emp-pick" :class="{ 'is-empty': form.department_id == null }" @click="openChooser('department')">
            <text>{{ departmentName(form.department_id) || '请选择部门' }}</text>
            <text class="h5-emp-pick__chev">›</text>
          </view>
        </view>
        <text class="h5-emp-section">其他资料</text>
        <template v-if="form.id && form.is_active === false">
          <view class="h5-emp-field">
            <text class="h5-emp-label">离职日期<text class="req">*</text></text>
            <picker mode="date" :value="form.leave_date" @change="form.leave_date = $event.detail.value">
              <view class="h5-emp-pick" :class="{ 'is-empty': !form.leave_date }">
                <text>{{ form.leave_date || '选择离职日期' }}</text>
                <text class="h5-emp-pick__chev">›</text>
              </view>
            </picker>
          </view>
        </template>
        <view class="h5-emp-field">
          <text class="h5-emp-label">身份证号</text>
          <input v-model="form.identity_card_no" class="h5-emp-input" maxlength="32" placeholder="选填" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">身份证照片</text>
          <view class="h5-emp-idcard">
            <image
              v-if="form.id_card_front_url"
              class="h5-emp-idcard__img"
              :src="displayImageUrl(form.id_card_front_url)"
              mode="aspectFill"
              @click="previewIdCards(form.id_card_front_url)"
            />
            <view v-else class="h5-emp-idcard__empty">人像面</view>
            <view class="h5-emp-photo-ops">
              <text>人像面，选填</text>
              <!-- 拍照优先；相册作为补拍。系统选择器覆盖 H5、小程序、App。 -->
              <view>
                <text @click="choosePhoto('camera', 'id_card_front_url')">拍照</text>
                <text @click="choosePhoto('album', 'id_card_front_url')">相册</text>
                <text v-if="form.id_card_front_url" class="danger" @click="form.id_card_front_url = ''">去掉</text>
              </view>
              <text v-if="photoUploadField === 'id_card_front_url'" class="h5-emp-meta">上传中…</text>
            </view>
          </view>
          <view class="h5-emp-idcard">
            <image
              v-if="form.id_card_back_url"
              class="h5-emp-idcard__img"
              :src="displayImageUrl(form.id_card_back_url)"
              mode="aspectFill"
              @click="previewIdCards(form.id_card_back_url)"
            />
            <view v-else class="h5-emp-idcard__empty">国徽面</view>
            <view class="h5-emp-photo-ops">
              <text>国徽面，选填</text>
              <view>
                <text @click="choosePhoto('camera', 'id_card_back_url')">拍照</text>
                <text @click="choosePhoto('album', 'id_card_back_url')">相册</text>
                <text v-if="form.id_card_back_url" class="danger" @click="form.id_card_back_url = ''">去掉</text>
              </view>
              <text v-if="photoUploadField === 'id_card_back_url'" class="h5-emp-meta">上传中…</text>
            </view>
          </view>
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">紧急联系人</text>
          <input v-model="form.emergency_contact" class="h5-emp-input" maxlength="50" placeholder="选填" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">紧急联系电话</text>
          <input v-model="form.emergency_phone" class="h5-emp-input" type="number" maxlength="20" placeholder="选填" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">职务</text>
          <view class="h5-emp-pick" :class="{ 'is-empty': form.job_title_id == null }" @click="openChooser('job')">
            <text>{{ jobName(form.job_title_id) || '可不选' }}</text>
            <text class="h5-emp-pick__chev">›</text>
          </view>
        </view>
        <view v-if="formSegmentId != null" class="h5-emp-field">
          <text class="h5-emp-label">工序</text>
          <view class="h5-emp-pick" :class="{ 'is-empty': !processText }" @click="openChooser('process')">
            <text>{{ processText || '可不选' }}</text>
            <text class="h5-emp-pick__chev">›</text>
          </view>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'salary'">
      <view class="card h5-emp-sheet">
        <view class="h5-emp-field">
          <text class="h5-emp-label">计薪方式</text>
          <view class="h5-emp-chips">
            <text
              v-for="item in salaryModels"
              :key="item.value"
              :class="{ on: salary.salary_model === item.value }"
              @click="salary.salary_model = item.value"
            >{{ item.label }}</text>
          </view>
        </view>
        <view v-if="salary.salary_model !== 'pure_piece'" class="h5-emp-field">
          <text class="h5-emp-label">{{ salary.salary_model === 'guaranteed_piece' ? '保底金额' : '底薪' }}</text>
          <input v-model="salary.base_salary" class="h5-emp-input" type="digit" placeholder="0" placeholder-style="color:#8b93a7" />
        </view>
        <template v-if="salary.salary_model === 'fixed'">
          <view class="h5-emp-field">
            <text class="h5-emp-label">每小时加班费</text>
            <input v-model="salary.overtime_hourly_rate" class="h5-emp-input" type="digit" placeholder="0" placeholder-style="color:#8b93a7" />
            <text class="h5-emp-hint">已设加班时间段时按打卡时长计算，未设时按每天超过 8 小时。</text>
          </view>
        </template>
        <view class="h5-emp-field">
          <text class="h5-emp-label">餐费补贴（元/天）</text>
          <input v-model="salary.meal_allowance_daily" class="h5-emp-input" type="digit" placeholder="按出勤天数" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">住宿补贴（元/天）</text>
          <input v-model="salary.housing_allowance_daily" class="h5-emp-input" type="digit" placeholder="按出勤天数" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">其它补贴（元/天）</text>
          <input v-model="salary.other_allowance_daily" class="h5-emp-input" type="digit" placeholder="按出勤天数" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">收款户名</text>
          <input v-model="salary.bank_account_name" class="h5-emp-input" placeholder="默认与姓名相同" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">银行卡号</text>
          <input v-model="salary.bank_account" class="h5-emp-input" placeholder="选填" placeholder-style="color:#8b93a7" />
        </view>
        <view class="h5-emp-field">
          <text class="h5-emp-label">开户行</text>
          <input v-model="salary.bank_name" class="h5-emp-input" placeholder="如 工行XX支行" placeholder-style="color:#8b93a7" />
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'leave' && current">
      <view class="card h5-emp-sheet">
        <text class="h5-emp-hint">为「{{ current.name }}」办理离职。离职后不计入部门人数，且不能登录。</text>
        <view class="h5-emp-field">
          <text class="h5-emp-label">离职日期<text class="req">*</text></text>
          <picker mode="date" :value="leaveDate" @change="leaveDate = $event.detail.value">
            <view class="h5-emp-pick" :class="{ 'is-empty': !leaveDate }">
              <text>{{ leaveDate || '选择离职日期' }}</text>
              <text class="h5-emp-pick__chev">›</text>
            </view>
          </picker>
        </view>
      </view>
    </template>

    <template v-else-if="mode === 'chooser'">
      <view class="card h5-emp-search">
        <input v-model="chooserQuery" class="h5-emp-input" placeholder="搜索" placeholder-style="color:#8b93a7" />
      </view>
      <view v-if="chooserKind === 'job'" class="card h5-emp-option" @click="applyChooser(null)">不指定</view>
      <view
        v-for="item in chooserItems"
        :key="item.id"
        class="card h5-emp-option"
        :style="{ paddingLeft: (24 + item.depth * 28) + 'rpx' }"
        @click="toggleChooser(item)"
      >
        <text>{{ item.name }}</text>
        <text v-if="chooserKind === 'process' && form.process_ids.includes(item.id)" class="on">已选</text>
      </view>
      <view v-if="!chooserItems.length" class="h5-emp-empty">没有匹配项</view>
      <view v-if="canWrite && chooserKind !== 'process'" class="card h5-emp-sheet">
        <text class="h5-emp-label">{{ chooserKind === 'department' ? '新建部门' : '新建职务' }}</text>
        <input v-model="createName" class="h5-emp-input" :placeholder="chooserKind === 'department' ? '部门名称' : '职务名称'" placeholder-style="color:#8b93a7" />
        <view class="h5-emp-action" @click="createMaster">保存并选中</view>
      </view>
    </template>

    <view v-if="showDock" class="cut-sticky-bar h5-emp-dock">
      <button v-if="mode === 'list'" class="primary-button h5-emp-primary" @click="openCreate">新增员工</button>
      <template v-else-if="mode === 'detail'">
        <button class="h5-emp-ghost" @click="openForm(current)">编辑档案</button>
        <button class="primary-button h5-emp-primary" @click="openSalary">薪资档案</button>
      </template>
      <button v-else-if="mode === 'chooser' && chooserKind === 'process'" class="primary-button h5-emp-primary" @click="mode = 'form'">完成</button>
      <button v-else class="primary-button h5-emp-primary" :disabled="saving || photoUploading" @click="saveCurrent">
        {{ saving ? '保存中…' : mode === 'leave' ? '确认离职' : '保存' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onBackPress, onPullDownRefresh, onReachBottom, onShow, onUnload } from '@dcloudio/uni-app'
import { get, patch, post, uploadFile } from '../../services/http'
import { setPageBackHandler } from '../../services/page-title'
import { getProfile } from '../../services/storage'

type Mode = 'list' | 'detail' | 'form' | 'salary' | 'leave' | 'chooser'
type ChooserKind = 'department' | 'job' | 'process'

const profile = ref(getProfile())
const features = computed(() => profile.value?.featurePermissions || [])
const canSee = computed(() => features.value.includes('workers') || features.value.includes('workers_write'))
const canWrite = computed(() => features.value.includes('workers_write'))

const mode = ref<Mode>('list')
const keyword = ref('')
const departmentId = ref<number | null>(null)
const showLeft = ref(false)
const rows = ref<any[]>([])
const current = ref<any>(null)
const departments = ref<any[]>([])
const jobs = ref<any[]>([])
const processes = ref<any[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const saving = ref(false)
const photoUploading = ref(false)
const photoUploadField = ref('')
const page = ref(1)
const chooserKind = ref<ChooserKind>('department')
const chooserQuery = ref('')
const createName = ref('')
const leaveDate = ref('')
let listFinished = false
let listSeq = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null

const form = reactive<any>(emptyForm())
const salary = reactive<any>(emptySalary())

const departmentTree = computed(() => flattenDepartments(departments.value))
const formSegmentId = computed(() => departmentTree.value.find(item => item.id === form.department_id)?.segmentId ?? null)
const processChoices = computed(() => {
  const segmentId = formSegmentId.value
  if (segmentId == null) return []
  const selected = new Set(form.process_ids || [])
  return processes.value.filter(item => Number(item.segment_id) === Number(segmentId) && (item.is_active || selected.has(item.id)))
})
const processText = computed(() => {
  const names = processChoices.value.filter(item => form.process_ids.includes(item.id)).map(item => item.name)
  return names.join('、')
})
const chooserItems = computed(() => {
  const q = chooserQuery.value.trim().toLowerCase()
  const source = chooserKind.value === 'department'
    ? departmentTree.value
    : chooserKind.value === 'job'
      ? jobs.value.filter(item => item.is_active !== false).map((item: any) => ({ id: item.id, name: item.name, depth: 0 }))
      : processChoices.value.map((item: any) => ({ id: item.id, name: item.name, depth: 0 }))
  return source.filter(item => !q || String(item.name || '').toLowerCase().includes(q))
})
const salaryModels = computed(() => {
  const items = [
    { value: 'pure_piece', label: '纯计件' },
    { value: 'guaranteed_piece', label: '保底+计件' },
    { value: 'fixed', label: '底薪' },
  ]
  if (salary.salary_model === 'base_plus_piece') items.splice(1, 0, { value: 'base_plus_piece', label: '底薪+计件' })
  return items
})
const showDock = computed(() => {
  if (!canSee.value) return false
  if (mode.value === 'list' || mode.value === 'detail') return canWrite.value
  if (mode.value === 'chooser') return chooserKind.value === 'process'
  return canWrite.value
})

function emptyForm() {
  return {
    id: null as number | null,
    name: '',
    mobile: '',
    hire_date: todayIso(),
    leave_date: '',
    is_active: true,
    identity_card_no: '',
    id_card_front_url: '',
    id_card_back_url: '',
    emergency_contact: '',
    emergency_phone: '',
    photo_url: '',
    department_id: null as number | null,
    job_title_id: null as number | null,
    process_ids: [] as number[],
  }
}
function emptySalary() {
  return {
    salary_model: 'pure_piece',
    base_salary: '0',
    overtime_hourly_rate: '0',
    meal_allowance_daily: '0',
    housing_allowance_daily: '0',
    other_allowance_daily: '0',
    bank_account_name: '',
    bank_account: '',
    bank_name: '',
  }
}
function todayIso() {
  const day = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}
function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}
function ask(title: string, content: string) {
  return new Promise<boolean>(resolve => {
    uni.showModal({ title, content, success: result => resolve(!!result.confirm) })
  })
}
function money(value: unknown) {
  return `¥${Number(value || 0).toFixed(2)}`
}
function salaryLabel(value: string) {
  return ({ pure_piece: '纯计件', guaranteed_piece: '保底+计件', fixed: '底薪', hourly: '底薪', base_plus_piece: '底薪+计件' } as Record<string, string>)[value] || value || '纯计件'
}
function initial(name: unknown) {
  return String(name || '').trim().slice(0, 1) || '人'
}
function phoneOf(row: any) {
  const phone = String(row?.mobile || '').replace(/[^\d+]/g, '')
  return phone.length >= 5 ? phone : ''
}
function summary(row: any) {
  return [row.department_name, row.job_title_name, ...(row.process_names || []).slice(0, 2)].filter(Boolean).join(' · ') || '未分配部门'
}
function emergencyText(row: any) {
  return [row.emergency_contact, row.emergency_phone].filter(Boolean).join(' ') || '—'
}
function displayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
function previewImage(url: string) {
  const resolved = displayImageUrl(url)
  if (resolved) uni.previewImage({ urls: [resolved], current: resolved })
}
function callPhone(raw: unknown) {
  const phone = phoneOf({ mobile: raw })
  if (!phone) {
    toast('没有可拨打的电话')
    return
  }
  uni.makePhoneCall({
    phoneNumber: phone,
    fail(error) {
      if (!String((error as { errMsg?: string })?.errMsg || '').includes('cancel')) toast('无法拨打电话')
    },
  })
}
function flattenDepartments(items: any[]) {
  const active = items.filter(item => item.is_active !== false)
  const children = new Map<number | null, any[]>()
  for (const item of active) {
    const key = item.parent_id ?? null
    children.set(key, [...(children.get(key) || []), item])
  }
  const out: { id: number; name: string; depth: number; segmentId: number | null }[] = []
  const seen = new Set<number>()
  const walk = (parent: number | null, depth: number) => {
    for (const item of children.get(parent) || []) {
      if (seen.has(item.id)) continue
      seen.add(item.id)
      out.push({
        id: item.id,
        name: item.name,
        depth,
        segmentId: item.process_segment_id == null ? null : Number(item.process_segment_id),
      })
      walk(item.id, depth + 1)
    }
  }
  walk(null, 0)
  for (const item of active) {
    if (!seen.has(item.id)) out.push({ id: item.id, name: item.name, depth: 0, segmentId: item.process_segment_id ?? null })
  }
  return out
}
function departmentName(id: number | null) {
  return departmentTree.value.find(item => item.id === id)?.name || ''
}
function jobName(id: number | null) {
  return jobs.value.find(item => item.id === id)?.name || ''
}
function pruneProcesses() {
  const allowed = new Set(processChoices.value.map(item => item.id))
  form.process_ids = (form.process_ids || []).filter((id: number) => allowed.has(id))
}
function syncTitle() {
  const titles: Record<Mode, string> = {
    list: '员工管理',
    detail: current.value?.name || '员工',
    form: form.id ? '编辑员工' : '新增员工',
    salary: '薪资档案',
    leave: '办理离职',
    chooser: chooserKind.value === 'department' ? '选择部门' : chooserKind.value === 'job' ? '选择职务' : '选择工序',
  }
  uni.setNavigationBarTitle({ title: titles[mode.value] })
}

async function loadMeta() {
  const [departmentRes, jobRes, processRes]: any[] = await Promise.all([
    get('/departments'),
    get('/job-titles', { active_only: true }),
    get('/processes', { page_size: 500 }),
  ])
  departments.value = departmentRes?.items || []
  jobs.value = jobRes?.items || []
  processes.value = processRes?.items || []
}
async function loadList(reset = false) {
  if (!canSee.value) return
  if (!reset && (loading.value || loadingMore.value || listFinished)) return
  const seq = ++listSeq
  if (reset) {
    page.value = 1
    listFinished = false
    loading.value = true
  } else {
    loadingMore.value = true
    page.value += 1
  }
  try {
    const result: any = await get('/employees', {
      keyword: keyword.value.trim() || undefined,
      department_id: departmentId.value || undefined,
      is_active: showLeft.value ? undefined : true,
      page: page.value,
      page_size: 30,
    })
    if (seq !== listSeq) return
    const items = result?.items || []
    rows.value = reset ? items : rows.value.concat(items)
    listFinished = rows.value.length >= Number(result?.total || 0) || items.length < 30
  } catch (error: any) {
    if (!reset) page.value = Math.max(1, page.value - 1)
    toast(error?.message || '加载失败')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
    }
    uni.stopPullDownRefresh()
  }
}
function reload() {
  void loadList(true)
}
function onKeyword(event: any) {
  keyword.value = String(event?.detail?.value || '')
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => loadList(true), 300)
}
function clearKeyword() {
  keyword.value = ''
  reload()
}
function pickDepartment(id: number | null) {
  departmentId.value = id
  reload()
}
function toggleLeft() {
  showLeft.value = !showLeft.value
  reload()
}
function openDetail(row: any) {
  current.value = row
  mode.value = 'detail'
}
function openCreate() {
  Object.assign(form, emptyForm(), {
    department_id: departmentId.value,
    hire_date: todayIso(),
  })
  pruneProcesses()
  mode.value = 'form'
}
function openForm(row: any) {
  Object.assign(form, emptyForm(), {
    id: row.id,
    name: row.name || '',
    mobile: row.mobile || '',
    hire_date: row.hire_date || todayIso(),
    leave_date: row.leave_date || '',
    is_active: row.is_active !== false,
    identity_card_no: row.identity_card_no || '',
    id_card_front_url: row.id_card_front_url || '',
    id_card_back_url: row.id_card_back_url || '',
    emergency_contact: row.emergency_contact || '',
    emergency_phone: row.emergency_phone || '',
    photo_url: row.photo_url || '',
    department_id: row.department_id ?? null,
    job_title_id: row.job_title_id ?? null,
    process_ids: Array.isArray(row.process_ids) ? [...row.process_ids] : [],
  })
  pruneProcesses()
  mode.value = 'form'
}
function openLeave() {
  leaveDate.value = current.value?.leave_date || todayIso()
  mode.value = 'leave'
}
function openSalary() {
  const row = current.value || {}
  Object.assign(salary, emptySalary(), {
    salary_model: row.salary_model === 'hourly' ? 'fixed' : (row.salary_model || 'pure_piece'),
    base_salary: String(row.base_salary || 0),
    overtime_hourly_rate: String(row.overtime_hourly_rate || 0),
    meal_allowance_daily: String(row.meal_allowance_daily || 0),
    housing_allowance_daily: String(row.housing_allowance_daily || 0),
    other_allowance_daily: String(row.other_allowance_daily || 0),
    bank_account_name: row.bank_account_name || '',
    bank_account: row.bank_account || '',
    bank_name: row.bank_name || '',
  })
  mode.value = 'salary'
}
function openChooser(kind: ChooserKind) {
  chooserKind.value = kind
  chooserQuery.value = ''
  createName.value = ''
  mode.value = 'chooser'
}
function applyChooser(id: number | null) {
  if (chooserKind.value === 'department') {
    form.department_id = id
    pruneProcesses()
  } else if (chooserKind.value === 'job') {
    form.job_title_id = id
  }
  mode.value = 'form'
}
function toggleChooser(item: { id: number }) {
  if (chooserKind.value !== 'process') {
    applyChooser(item.id)
    return
  }
  const ids = new Set(form.process_ids || [])
  if (ids.has(item.id)) ids.delete(item.id)
  else ids.add(item.id)
  form.process_ids = [...ids]
}
function previewIdCards(currentUrl: string) {
  const urls = [form.id_card_front_url, form.id_card_back_url, current.value?.id_card_front_url, current.value?.id_card_back_url]
    .map(item => displayImageUrl(item))
    .filter((item, index, list) => item && list.indexOf(item) === index)
  const currentResolved = displayImageUrl(currentUrl)
  if (currentResolved) uni.previewImage({ urls: urls.length ? urls : [currentResolved], current: currentResolved })
}
function choosePhoto(source: 'camera' | 'album', field: 'photo_url' | 'id_card_front_url' | 'id_card_back_url') {
  if (photoUploading.value) return
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: [source],
    success: async result => {
      const filePath = result.tempFilePaths?.[0]
      if (!filePath) return
      photoUploading.value = true
      photoUploadField.value = field
      try {
        const uploaded: any = await uploadFile('/employees/upload-photo', filePath)
        if (uploaded?.url) form[field] = uploaded.url
      } catch (error: any) {
        toast(error?.message || (field === 'photo_url' ? '照片上传失败' : '身份证照片上传失败'))
      } finally {
        photoUploading.value = false
        photoUploadField.value = ''
      }
    },
  })
}
async function createMaster() {
  const name = createName.value.trim()
  if (!name) {
    toast(chooserKind.value === 'department' ? '请填写部门名称' : '请填写职务名称')
    return
  }
  try {
    if (chooserKind.value === 'department') {
      const created: any = await post('/departments', { name })
      await loadMeta()
      applyChooser(created.id)
      return
    }
    const created: any = await post('/job-titles', { name })
    await loadMeta()
    applyChooser(created.id)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  }
}
async function saveForm() {
  if (!form.name.trim()) {
    toast('请填写姓名')
    return
  }
  const mobile = String(form.mobile || '').trim()
  if (!mobile) {
    toast('请填写手机号')
    return
  }
  if (form.department_id == null) {
    toast('请选择部门')
    return
  }
  if (!form.hire_date) {
    toast('请选择入职日期')
    return
  }
  if (form.id && form.is_active === false) {
    if (!form.leave_date) {
      toast('请选择离职日期')
      return
    }
    if (form.leave_date < form.hire_date) {
      toast('离职日期不能早于入职日期')
      return
    }
  }
  pruneProcesses()
  const payload: any = {
    name: form.name.trim(),
    mobile,
    hire_date: form.hire_date,
    identity_card_no: form.identity_card_no || null,
    id_card_front_url: form.id_card_front_url || null,
    id_card_back_url: form.id_card_back_url || null,
    emergency_contact: form.emergency_contact || null,
    emergency_phone: form.emergency_phone || null,
    photo_url: form.photo_url || null,
    department_id: form.department_id,
    job_title_id: form.job_title_id,
    process_ids: form.process_ids || [],
  }
  if (form.id && form.is_active === false) payload.leave_date = form.leave_date
  saving.value = true
  try {
    const saved: any = form.id ? await patch(`/employees/${form.id}`, payload) : await post('/employees', payload)
    current.value = saved
    toast('已保存')
    mode.value = 'detail'
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function saveSalary() {
  if (!current.value?.id) return
  saving.value = true
  try {
    const model = salary.salary_model
    const saved: any = await patch(`/employees/${current.value.id}`, {
      salary_model: model,
      base_salary: model === 'pure_piece' ? 0 : Number(salary.base_salary || 0),
      overtime_hourly_rate: model === 'fixed' ? Number(salary.overtime_hourly_rate || 0) : 0,
      meal_allowance_daily: Number(salary.meal_allowance_daily || 0),
      housing_allowance_daily: Number(salary.housing_allowance_daily || 0),
      other_allowance_daily: Number(salary.other_allowance_daily || 0),
      bank_account_name: salary.bank_account_name || null,
      bank_account: salary.bank_account || null,
      bank_name: salary.bank_name || null,
    })
    current.value = saved
    toast('薪资档案已保存')
    mode.value = 'detail'
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function confirmLeave() {
  if (!current.value?.id) return
  if (current.value.id === profile.value?.id) {
    toast('不能为自己办理离职')
    return
  }
  if (!leaveDate.value) {
    toast('请选择离职日期')
    return
  }
  if (current.value.hire_date && leaveDate.value < current.value.hire_date) {
    toast('离职日期不能早于入职日期')
    return
  }
  saving.value = true
  try {
    const saved: any = await patch(`/employees/${current.value.id}`, { is_active: false, leave_date: leaveDate.value })
    current.value = saved
    toast('已离职')
    mode.value = 'detail'
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '办理失败')
  } finally {
    saving.value = false
  }
}
async function restore() {
  if (!current.value?.id) return
  if (!await ask('复职', `让「${current.value.name}」恢复在职？`)) return
  try {
    const saved: any = await patch(`/employees/${current.value.id}`, { is_active: true })
    current.value = saved
    toast('已复职')
    await loadList(true)
  } catch (error: any) {
    toast(error?.message || '复职失败')
  }
}
async function resetPassword() {
  if (!current.value?.id) return
  if (!await ask('重置密码', `把「${current.value.name}」的密码重置为系统默认密码？下次登录需要修改。`)) return
  try {
    await patch(`/employees/${current.value.id}`, { reset_password: true })
    toast('密码已重置')
  } catch (error: any) {
    toast(error?.message || '重置失败')
  }
}
function saveCurrent() {
  if (mode.value === 'form') void saveForm()
  else if (mode.value === 'salary') void saveSalary()
  else if (mode.value === 'leave') void confirmLeave()
}
function goBack() {
  if (mode.value === 'chooser') {
    mode.value = 'form'
    return
  }
  if (mode.value === 'form') {
    mode.value = form.id ? 'detail' : 'list'
    return
  }
  if (mode.value === 'salary' || mode.value === 'leave') {
    mode.value = 'detail'
    return
  }
  mode.value = 'list'
}
function handleBack() {
  if (mode.value === 'list') return false
  goBack()
  return true
}

watch(mode, syncTitle)
watch(() => current.value?.name, () => {
  if (mode.value === 'detail') syncTitle()
})

onBackPress(() => handleBack())
onPullDownRefresh(() => {
  if (mode.value === 'list') void loadList(true)
  else uni.stopPullDownRefresh()
})
onReachBottom(() => {
  if (mode.value === 'list') void loadList(false)
})
onShow(() => {
  profile.value = getProfile()
  setPageBackHandler('pages/employees/index', handleBack)
  syncTitle()
  if (!canSee.value) {
    toast('没有员工管理权限')
    setTimeout(() => uni.navigateBack(), 400)
    return
  }
  void loadMeta().catch(() => {})
  if (mode.value === 'list') void loadList(true)
})
onUnload(() => {
  setPageBackHandler('pages/employees/index', null)
})
</script>

<style scoped>
.h5-emp--dock { padding-bottom: calc(180rpx + env(safe-area-inset-bottom)); }
.h5-emp-empty, .h5-emp-more { padding: 80rpx 0; color: #414755; font-size: 26rpx; text-align: center; }
.h5-emp-more { padding: 12rpx 0 24rpx; }
.h5-emp-search, .h5-emp-card, .h5-emp-hero, .h5-emp-sheet, .h5-emp-option { margin-bottom: 16rpx; }
.h5-emp-search { display: flex; align-items: center; gap: 16rpx; padding: 8rpx 8rpx 8rpx 24rpx; }
.h5-emp-search input { flex: 1; height: 72rpx; min-width: 0; color: #181b23; font-size: 28rpx; }
.h5-emp-search text, .h5-emp-photo-ops text, .h5-emp-action { color: #0057c2; font-size: 28rpx; }
.h5-emp-tabs { width: 100%; margin: 0 0 12rpx; white-space: nowrap; }
.h5-emp-tabs text, .h5-emp-chips text {
  display: inline-flex;
  align-items: center;
  height: 60rpx;
  margin-right: 12rpx;
  padding: 0 22rpx;
  border-radius: 999rpx;
  background: #fff;
  color: #414755;
  font-size: 24rpx;
}
.h5-emp-tabs text.on, .h5-emp-chips text.on, .h5-emp-option .on { background: rgba(0, 87, 194, 0.12); color: #0057c2; font-weight: 700; }
.h5-emp-card, .h5-emp-hero { display: flex; align-items: center; gap: 16rpx; padding: 20rpx 24rpx; }
.h5-emp-hero { flex-direction: column; align-items: flex-start; }
.h5-emp-card__main { flex: 1; min-width: 0; }
.h5-emp-card__title { display: flex; align-items: center; gap: 12rpx; }
.h5-emp-name { color: #181b23; font-size: 32rpx; font-weight: 750; }
.h5-emp-meta, .h5-emp-hint { display: block; margin-top: 8rpx; color: #414755; font-size: 24rpx; line-height: 1.5; }
.h5-emp-tag { padding: 2rpx 12rpx; border-radius: 999rpx; background: #eceff3; color: #414755; font-size: 22rpx; }
.h5-emp-avatar, .h5-emp-photo {
  flex: none;
  width: 88rpx;
  height: 88rpx;
  border-radius: 44rpx;
  background: #e7eef8;
}
.h5-emp-photo { width: 144rpx; height: 144rpx; border-radius: 24rpx; }
.h5-emp-avatar--empty { display: flex; align-items: center; justify-content: center; color: #0057c2; font-size: 34rpx; font-weight: 750; }
.h5-emp-call {
  flex: none;
  padding: 14rpx 18rpx;
  border-radius: 999rpx;
  background: #0057c2;
  color: #fff;
  font-size: 24rpx;
}
.h5-emp-sheet { padding: 8rpx 24rpx 28rpx; }
.h5-emp-line, .h5-emp-option, .h5-emp-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24rpx;
  min-height: 88rpx;
  border-bottom: 1rpx solid rgba(60, 60, 67, 0.08);
}
.h5-emp-line text:first-child { flex: none; color: #414755; font-size: 26rpx; }
.h5-emp-line text:last-child { color: #181b23; font-size: 28rpx; text-align: right; }
.h5-emp-line text.h5-emp-link { color: #0057c2; font-weight: 700; }
.h5-emp-idcard { display: flex; align-items: center; gap: 20rpx; margin-top: 16rpx; }
.h5-emp-idcard + .h5-emp-idcard { margin-top: 20rpx; }
.h5-emp-idcard__img,
.h5-emp-idcard__empty {
  flex: none;
  width: 240rpx;
  height: 152rpx;
  border-radius: 16rpx;
  background: #e7eef8;
}
.h5-emp-idcard__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2rpx dashed #c5d0e0;
  color: #8b93a7;
  font-size: 24rpx;
}
.h5-emp-option { padding: 0 24rpx; color: #181b23; font-size: 30rpx; }
.h5-emp-action { justify-content: center; }
.h5-emp-section {
  display: block;
  margin: 28rpx 0 4rpx;
  color: #181b23;
  font-size: 28rpx;
  font-weight: 750;
}
.h5-emp-field { margin-top: 20rpx; }
.h5-emp-field picker { display: block; width: 100%; }
.h5-emp-label { display: block; margin: 0 0 10rpx; color: #414755; font-size: 26rpx; font-weight: 650; }
.h5-emp-label .req { margin-left: 4rpx; color: #ba1a1a; }
.h5-emp-input,
.h5-emp-pick {
  box-sizing: border-box;
  width: 100%;
  height: 88rpx;
  padding: 0 24rpx;
  border: 2rpx solid #c5d0e0;
  border-radius: 16rpx;
  background: #f4f7fb;
  color: #181b23;
  font-size: 30rpx;
  line-height: 84rpx;
}
.h5-emp-pick {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.h5-emp-pick text:first-child {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.h5-emp-pick.is-empty { color: #8b93a7; }
.h5-emp-pick__chev { flex: none; color: #0057c2; font-size: 40rpx; line-height: 1; }
.h5-emp-search input.h5-emp-input { flex: 1; margin: 8rpx 0; }
.h5-emp-photo-row { display: flex; align-items: center; gap: 20rpx; padding: 16rpx 0; }
.h5-emp-photo-ops view { display: flex; gap: 24rpx; margin-top: 12rpx; }
.h5-emp-photo-ops .danger, .h5-emp-action.danger { color: #ba1a1a; }
.h5-emp-chips { display: flex; flex-wrap: wrap; gap: 12rpx; margin-top: 12rpx; }
.h5-emp-chips text { margin-right: 0; }
.h5-emp-dock { display: flex; gap: 16rpx; }
.h5-emp-primary,
.h5-emp-ghost {
  flex: 1;
  width: auto;
  height: 84rpx;
  margin: 0;
  border: 0;
  border-radius: 16rpx;
  font-size: 28rpx;
  font-weight: 750;
  line-height: 84rpx;
}
.h5-emp-primary::after,
.h5-emp-ghost::after { border: 0; }
.h5-emp-primary[disabled] { background: #8eb6e8; color: rgba(255, 255, 255, 0.9); }
.h5-emp-ghost { background: #fff; color: #0057c2; }
</style>
