<template>
  <div class="ops-page">
    <header class="admin-content-head">
      <h1 class="admin-content-title">App 版本</h1>
    </header>
    <div class="admin-content">
      <div class="admin-card" v-loading="loading">
        <el-radio-group v-model="platform" class="release-switch">
          <el-radio-button value="android">Android</el-radio-button>
          <el-radio-button value="ios">iOS</el-radio-button>
        </el-radio-group>

        <section v-for="kind in kinds" :key="kind" class="release-block">
          <h2>{{ kindTitle(kind) }}</h2>
          <el-form label-width="120px" class="release-form">
            <el-form-item label="版本名" required>
              <el-input v-model="formOf(kind).version_name" maxlength="32" placeholder="如 1.0.1" />
            </el-form-item>
            <el-form-item label="版本号" required>
              <el-input v-model="formOf(kind).version_code" maxlength="10" :placeholder="codePlaceholder(kind)" />
            </el-form-item>
            <el-form-item label="下载地址" :required="formOf(kind).is_published">
              <el-input v-model="formOf(kind).download_url" maxlength="500" :placeholder="urlPlaceholder(kind)" />
            </el-form-item>
            <el-form-item v-if="kind === 'wgt'" label="最低壳版本">
              <el-input v-model="formOf(kind).min_native_version_code" maxlength="10" placeholder="如 100，低于它的手机先更新整包" />
            </el-form-item>
            <el-form-item label="更新说明">
              <el-input v-model="formOf(kind).notes" type="textarea" :rows="2" maxlength="500" placeholder="手机更新弹窗里展示" />
            </el-form-item>
            <el-form-item label="强制更新">
              <el-switch v-model="formOf(kind).force_update" />
            </el-form-item>
            <el-form-item label="向手机发布">
              <el-switch v-model="formOf(kind).is_published" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingKey === kind" @click="save(kind)">保存</el-button>
            </el-form-item>
          </el-form>
          <p class="ops-hint">{{ hint(kind) }}</p>
        </section>
      </div>

      <div class="admin-card">
        <div class="admin-toolbar">
          <span class="release-history-title">{{ platform === 'android' ? 'Android' : 'iOS' }} 发布记录</span>
          <el-button :loading="loading" @click="load">刷新</el-button>
        </div>
        <el-table :data="historyRows" stripe border style="width: 100%">
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ row.kind === 'wgt' ? '热更新' : '整包' }}</template>
          </el-table-column>
          <el-table-column prop="version_name" label="版本名" width="110" />
          <el-table-column prop="version_code" label="版本号" width="90" align="right" />
          <el-table-column label="最低壳版本" width="110" align="right">
            <template #default="{ row }">{{ row.min_native_version_code || '—' }}</template>
          </el-table-column>
          <el-table-column label="强制" width="70">
            <template #default="{ row }">{{ row.force_update ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row)">{{ statusLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="published_at" label="发布时间" width="160" />
          <el-table-column prop="notes" label="说明" min-width="160" show-overflow-tooltip />
          <el-table-column prop="download_url" label="地址" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="removeRow(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="editVisible" :title="editTitle" width="560px" destroy-on-close>
      <el-form label-width="120px">
        <el-form-item label="版本名" required>
          <el-input v-model="editForm.version_name" maxlength="32" placeholder="如 1.0.1" />
        </el-form-item>
        <el-form-item label="版本号" required>
          <el-input v-model="editForm.version_code" maxlength="10" placeholder="如 101" />
        </el-form-item>
        <el-form-item label="下载地址" :required="editForm.is_published">
          <el-input v-model="editForm.download_url" maxlength="500" :placeholder="urlPlaceholder(editingKind)" />
        </el-form-item>
        <el-form-item v-if="editingKind === 'wgt'" label="最低壳版本">
          <el-input v-model="editForm.min_native_version_code" maxlength="10" placeholder="如 100，低于它的手机先更新整包" />
        </el-form-item>
        <el-form-item label="更新说明">
          <el-input v-model="editForm.notes" type="textarea" :rows="2" maxlength="500" placeholder="手机更新弹窗里展示" />
        </el-form-item>
        <el-form-item label="强制更新">
          <el-switch v-model="editForm.force_update" />
        </el-form-item>
        <el-form-item label="向手机发布">
          <el-switch v-model="editForm.is_published" />
        </el-form-item>
        <el-form-item label="当前版本">
          <el-switch v-model="editForm.is_current" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import opsHttp from '@/api/opsHttp'

type Platform = 'android' | 'ios'
type Kind = 'native' | 'wgt'

type ReleaseRow = {
  id: number
  platform: Platform
  kind: Kind
  version_name: string
  version_code: number
  download_url: string
  notes: string
  force_update: boolean
  is_published: boolean
  is_current: boolean
  min_native_version_code: number | null
  published_at: string | null
}

type ReleaseForm = {
  version_name: string
  version_code: string
  download_url: string
  notes: string
  force_update: boolean
  is_published: boolean
  is_current: boolean
  min_native_version_code: string
}

const kinds: Kind[] = ['native', 'wgt']
const loading = ref(false)
const savingKey = ref('')
const editVisible = ref(false)
const editSaving = ref(false)
const editing = ref<ReleaseRow | null>(null)
const platform = ref<Platform>('android')
const history = reactive<Record<Platform, Record<Kind, ReleaseRow[]>>>({
  android: { native: [], wgt: [] },
  ios: { native: [], wgt: [] },
})

function emptyForm(): ReleaseForm {
  return {
    version_name: '',
    version_code: '',
    download_url: '',
    notes: '',
    force_update: false,
    is_published: true,
    is_current: true,
    min_native_version_code: '',
  }
}

const editForm = reactive<ReleaseForm>(emptyForm())

const forms = reactive<Record<Platform, Record<Kind, ReleaseForm>>>({
  android: { native: emptyForm(), wgt: emptyForm() },
  ios: { native: emptyForm(), wgt: emptyForm() },
})

const historyRows = computed(() => [
  ...history[platform.value].native,
  ...history[platform.value].wgt,
])

const editingKind = computed<Kind>(() => editing.value?.kind || 'native')
const editTitle = computed(() => {
  const row = editing.value
  if (!row) return '编辑发布记录'
  const kind = row.kind === 'wgt' ? '热更新' : '整包'
  return `编辑 ${row.platform === 'ios' ? 'iOS' : 'Android'} ${kind} ${row.version_name}`
})

function formOf(kind: Kind) {
  return forms[platform.value][kind]
}

function kindTitle(kind: Kind) {
  if (kind === 'wgt') return '热更新'
  return platform.value === 'ios' ? '整包（打开链接）' : '整包'
}

function codePlaceholder(kind: Kind) {
  if (kind === 'wgt') return 'wgt 的 versionCode，如 102'
  return 'manifest.json 的 versionCode，如 101'
}

function urlPlaceholder(kind: Kind) {
  if (platform.value === 'ios' && kind === 'native') return 'TestFlight、App Store 或企业分发链接'
  if (kind === 'wgt') return 'https://tyulan.cn/download/铁玉兰管家.wgt'
  return 'https://tyulan.cn/download/铁玉兰管家.apk'
}

function hint(kind: Kind) {
  if (kind === 'wgt') {
    return '热更新只换页面和脚本。在 HBuilderX 用「发行 → 原生 App-制作移动App资源升级包」打出 wgt。权限、原生模块、图标变了必须发整包。最低壳版本留空则不限制；填了之后，手机上的整包版本号更低时会先提示整包更新。'
  }
  if (platform.value === 'ios') {
    return 'iOS 不能在 App 里安装 ipa。这里填 TestFlight、App Store 或企业分发地址，手机点更新后打开该链接。版本号仍要比已安装的壳版本大。'
  }
  return 'Android 整包是正式 APK，版本号要比手机里已安装的 versionCode 大，并且必须用同一签名。标准调试基座不会检查更新。'
}

function statusLabel(row: ReleaseRow) {
  if (!row.is_current) return '历史'
  return row.is_published ? '当前发布' : '未发布'
}

function statusType(row: ReleaseRow) {
  if (!row.is_current) return 'info'
  return row.is_published ? 'success' : 'warning'
}

function fillForm(kind: Kind, row: ReleaseRow | null, target: Platform) {
  const form = forms[target][kind]
  form.version_name = row?.version_name || ''
  form.version_code = row ? String(row.version_code) : ''
  form.download_url = row?.download_url || ''
  form.notes = row?.notes || ''
  form.force_update = Boolean(row?.force_update)
  form.is_published = row ? row.is_published : true
  form.min_native_version_code = row?.min_native_version_code ? String(row.min_native_version_code) : ''
}

async function load() {
  loading.value = true
  try {
    const res: any = await opsHttp.get('/operators/app-releases')
    const data = res.data || {}
    for (const name of ['android', 'ios'] as Platform[]) {
      for (const kind of kinds) {
        const bucket = data[name]?.[kind] || {}
        history[name][kind] = bucket.history || []
        fillForm(kind, bucket.current || null, name)
      }
    }
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    loading.value = false
  }
}

function releasePayload(kind: Kind, targetPlatform: Platform, form: ReleaseForm) {
  const versionCode = Number(form.version_code.trim())
  const minNativeText = form.min_native_version_code.trim()
  const minNative = minNativeText ? Number(minNativeText) : null
  if (!form.version_name.trim()) return '请填写版本名'
  if (!Number.isInteger(versionCode) || versionCode < 1) return '版本号须为大于 0 的整数'
  if (kind === 'wgt' && minNativeText && (!Number.isInteger(minNative) || (minNative ?? 0) < 1)) {
    return '最低壳版本须为大于 0 的整数'
  }
  const url = form.download_url.trim()
  if (form.is_published) {
    const iosLink = targetPlatform === 'ios' && kind === 'native'
    const ok = iosLink ? /^(https?|itms-apps|itms-services):\/\//i.test(url) : /^https?:\/\//i.test(url)
    if (!ok) return iosLink ? '请填写 https、itms-apps 或 itms-services 链接' : '请填写 http 或 https 下载地址'
  }
  return {
    version_name: form.version_name.trim(),
    version_code: versionCode,
    download_url: url,
    notes: form.notes.trim(),
    force_update: form.force_update,
    is_published: form.is_published,
    min_native_version_code: kind === 'wgt' ? minNative : null,
  }
}

async function save(kind: Kind) {
  const form = formOf(kind)
  const payload = releasePayload(kind, platform.value, form)
  if (typeof payload === 'string') {
    ElMessage.warning(payload)
    return
  }
  savingKey.value = kind
  try {
    await opsHttp.put('/operators/app-releases', {
      platform: platform.value,
      kind,
      ...payload,
    })
    ElMessage.success('已保存')
    await load()
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    savingKey.value = ''
  }
}

function openEdit(row: ReleaseRow) {
  editing.value = row
  editForm.version_name = row.version_name
  editForm.version_code = String(row.version_code)
  editForm.download_url = row.download_url || ''
  editForm.notes = row.notes || ''
  editForm.force_update = Boolean(row.force_update)
  editForm.is_published = row.is_published
  editForm.is_current = row.is_current
  editForm.min_native_version_code = row.min_native_version_code ? String(row.min_native_version_code) : ''
  editVisible.value = true
}

async function submitEdit() {
  const row = editing.value
  if (!row) return
  const payload = releasePayload(row.kind, row.platform, editForm)
  if (typeof payload === 'string') {
    ElMessage.warning(payload)
    return
  }
  editSaving.value = true
  try {
    await opsHttp.put(`/operators/app-releases/${row.id}`, {
      ...payload,
      is_current: editForm.is_current,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    editSaving.value = false
  }
}

async function removeRow(row: ReleaseRow) {
  const currentHint = row.is_current ? '这是当前版本，删除后手机不再按这条检查更新。' : '删除后不能恢复。'
  try {
    await ElMessageBox.confirm(
      `删除 ${row.version_name}（${row.version_code}）？${currentHint}`,
      '删除发布记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await opsHttp.delete(`/operators/app-releases/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch {
    // 错误由 opsHttp 提示
  }
}

onMounted(load)
</script>

<style scoped>
.release-switch {
  margin-bottom: 8px;
}

.release-block + .release-block {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #e5e7eb;
}

.release-block h2 {
  margin: 12px 0;
  font-size: 15px;
  font-weight: 650;
}

.release-form {
  max-width: 760px;
}

.release-history-title {
  font-weight: 650;
}

.ops-hint {
  margin: 0 0 8px;
  color: var(--ws-muted, #64748b);
  font-size: 12px;
  line-height: 1.6;
}

.admin-card + .admin-card {
  margin-top: 16px;
}
</style>
