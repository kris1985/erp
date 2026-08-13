<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

type ImAlertsConfig = {
  webhook_url: string | null
  enabled: boolean
  events: string[]
}

const EVENT_OPTIONS = [
  { value: 'shortage', label: '缺料' },
  { value: 'delivery_risk', label: '交期风险' },
  { value: 'digest', label: '进度日报' },
]

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const previewLoading = ref(false)
const testLoading = ref(false)
const previewKind = ref<'alert' | 'digest'>('alert')
const previewText = ref('')
const previewEventCount = ref<number | null>(null)
const testResult = ref<{ ok: boolean; status: number | null; error: string | null } | null>(null)

const cfg = ref<ImAlertsConfig>({ webhook_url: null, enabled: false, events: [] })

const isAdmin = computed(() => auth.role === 'admin' || auth.baseRole === 'admin')
const canTest = computed(() => !!(cfg.value.webhook_url && cfg.value.webhook_url.trim()))

function applyConfig(data: any) {
  cfg.value = {
    webhook_url: data?.webhook_url ?? null,
    enabled: !!data?.enabled,
    events: Array.isArray(data?.events) ? [...data.events] : [],
  }
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/im-alerts-settings')
    applyConfig(res.data)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res: any = await http.patch('/im-alerts-settings', { ...cfg.value })
    applyConfig(res.data)
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

async function loadPreview(kind: 'alert' | 'digest') {
  previewKind.value = kind
  previewLoading.value = true
  try {
    const res: any = await http.get('/ops/im-alerts/preview', { params: { kind } })
    const payload = res.data?.payload
    const msg = payload?.message
    previewText.value =
      msg?.markdown_v2?.content ||
      msg?.markdown?.content ||
      msg?.text?.content ||
      ''
    previewEventCount.value =
      typeof payload?.event_count === 'number' ? payload.event_count : null
  } finally {
    previewLoading.value = false
  }
}

async function testSend() {
  if (!canTest.value) return
  testLoading.value = true
  testResult.value = null
  try {
    const res: any = await http.post('/ops/im-alerts/test-send', {
      kind: previewKind.value,
      webhook_url: cfg.value.webhook_url,
    })
    const r = res.data?.result
    testResult.value = { ok: !!r?.ok, status: r?.status ?? null, error: r?.error ?? null }
    if (r?.ok) ElMessage.success('已试发，请到群里查看')
    else ElMessage.warning('试发失败：' + (r?.error || `HTTP ${r?.status ?? '?'}`))
  } finally {
    testLoading.value = false
  }
}

onMounted(async () => {
  await load()
  void loadPreview('alert')
})
</script>

<template>
  <div v-loading="loading">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">IM 预警推送</h1>
        <p class="page-desc">缺料 / 交期风险 / 进度日报推进企微钉钉群机器人；只推不改，推送失败不影响系统</p>
      </div>
    </header>

    <div class="admin-card">
      <h3 class="section-title">推送配置</h3>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">开启推送</div>
          <div class="switch-hint">关闭时仅可预览/试发，不会有任何自动推送（v1 暂无定时任务，需接后续调度器）。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="cfg.enabled" />
        <el-tag v-else :type="cfg.enabled ? 'success' : 'info'" size="small">
          {{ cfg.enabled ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="field-row">
        <div class="switch-copy">
          <div class="switch-name">Webhook 地址</div>
          <div class="switch-hint">企微/钉钉自定义群机器人 Webhook；只用最小文本消息协议，不接完整 SDK。</div>
        </div>
        <el-input
          v-if="isAdmin"
          v-model="cfg.webhook_url"
          placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
          clearable
          style="max-width: 420px"
        />
        <span v-else class="webhook-readonly">{{ cfg.webhook_url || '未配置' }}</span>
      </div>

      <div class="field-row">
        <div class="switch-copy">
          <div class="switch-name">推送内容</div>
          <div class="switch-hint">开启后按勾选类型推送；不勾选则该类型永不发。</div>
        </div>
        <el-checkbox-group v-if="isAdmin" v-model="cfg.events">
          <el-checkbox v-for="opt in EVENT_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
        <span v-else class="webhook-readonly">
          {{ cfg.events.map((e) => EVENT_OPTIONS.find((o) => o.value === e)?.label || e).join('、') || '未选择' }}
        </span>
      </div>

      <div v-if="isAdmin" class="actions">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </div>

    <div class="admin-card">
      <div class="check-head">
        <h3 class="section-title" style="margin: 0">预览 / 试发</h3>
        <el-radio-group v-model="previewKind" size="small" @change="loadPreview(previewKind)">
          <el-radio-button value="alert">预警</el-radio-button>
          <el-radio-button value="digest">进度日报</el-radio-button>
        </el-radio-group>
      </div>

      <p class="check-hint">
        预览为干跑，不会真正发送；确认内容后点「试发」推一条到上方 Webhook 地址核对格式。
      </p>

      <div v-loading="previewLoading" class="preview-box">
        <pre>{{ previewText || '（加载中…）' }}</pre>
      </div>
      <p v-if="previewEventCount !== null" class="check-hint">
        本次预警事件数：{{ previewEventCount }}
      </p>

      <div class="actions">
        <el-button :loading="previewLoading" @click="loadPreview(previewKind)">刷新预览</el-button>
        <el-button
          v-if="isAdmin"
          type="warning"
          :disabled="!canTest"
          :loading="testLoading"
          @click="testSend"
        >
          试发一条
        </el-button>
      </div>
      <p v-if="!canTest" class="check-hint">先填 Webhook 地址才能试发（可先填地址测试，测通后再保存）。</p>

      <div v-if="testResult" class="test-result" :class="{ 'is-ok': testResult.ok, 'is-bad': !testResult.ok }">
        {{ testResult.ok ? '试发成功' : '试发失败' }}
        <span v-if="testResult.status !== null">· HTTP {{ testResult.status }}</span>
        <span v-if="testResult.error">· {{ testResult.error }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-title {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 600;
}
.switch-row,
.field-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.switch-row:last-of-type,
.field-row:last-of-type {
  border-bottom: none;
}
.switch-copy {
  flex: 1;
  min-width: 0;
}
.switch-name {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}
.switch-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.55;
}
.webhook-readonly {
  font-size: 13px;
  color: var(--el-text-color-regular);
  word-break: break-all;
  max-width: 420px;
  text-align: right;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.check-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.check-hint {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.preview-box {
  margin-top: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
  min-height: 96px;
}
.preview-box pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
}
.test-result {
  margin-top: 12px;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
}
.test-result.is-ok {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
}
.test-result.is-bad {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger-dark-2);
}
.admin-card + .admin-card {
  margin-top: 12px;
}
</style>
