<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Delete,
  EditPen,
  Plus,
  Promotion,
  RefreshRight,
  WarningFilled,
} from '@element-plus/icons-vue'
import http from '@/api/http'
import AssistantChart, { type ChartSpec } from '@/components/assistant/AssistantChart.vue'
import { useAuthStore } from '@/stores/auth'
import { renderMarkdown } from '@/utils/markdown'

type ChatMsg = {
  role: 'user' | 'assistant'
  content: string
  tools?: { name?: string; content?: string }[]
  charts?: ChartSpec[]
  streaming?: boolean
}

type Conversation = {
  id: string
  title: string
  created_at?: string
  updated_at?: string
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const agentEnabled = ref(false)
const agentModel = ref('')
const agentReason = ref('')
const loadingList = ref(false)
const loadingThread = ref(false)
const sending = ref(false)

const conversations = ref<Conversation[]>([])
const activeId = ref<string | null>(null)
const messages = ref<ChatMsg[]>([])
const input = ref('')
const search = ref('')
const composerRef = ref<HTMLTextAreaElement | null>(null)
const threadEndRef = ref<HTMLElement | null>(null)

const suggestionGroups = [
  {
    title: '生产进度',
    items: [
      '今日各工序产量多少？合格和不良各多少？',
      '在制订单整体进度怎样？哪些单最落后？',
      '列出延期风险和急单，按交期紧迫排序',
      '当前工序瓶颈在哪里？剩余量最大的是哪几道？',
    ],
  },
  {
    title: '排产负荷',
    items: [
      '这周各工序日负荷会不会爆？哪天最紧？',
      '未来 14 天成型/针车负荷走势如何？',
      '帮我评估：如果插入一笔急单，对现有排产冲击大吗？',
      '按交期倒排，哪些单建议优先排？',
    ],
  },
  {
    title: '缺料采购',
    items: [
      '缺料最急的是哪些？分别影响哪些订单？',
      '只看急单相关的缺料清单',
      '在途采购有没有逾期或即将到期？',
      '库存池余额偏低、占用偏高的材料有哪些？',
    ],
  },
  {
    title: '经营财务',
    items: [
      '本月回款多少？按客户和按日怎么分布？',
      '未结应收还有多少？主要欠款客户是谁？',
      '本月利润概况：收入、成本、毛利各多少？',
      '本月经营 KPI 一览，和关键风险点',
    ],
  },
]

const filteredConversations = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return conversations.value
  return conversations.value.filter((c) => (c.title || '').toLowerCase().includes(q))
})

const activeTitle = computed(() => {
  if (!activeId.value) return '新对话'
  return conversations.value.find((c) => c.id === activeId.value)?.title || '对话'
})

function formatTime(v?: string) {
  if (!v) return ''
  const s = String(v).replace('T', ' ')
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s.slice(0, 16)
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function scrollToBottom(smooth = false) {
  await nextTick()
  threadEndRef.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
}

async function loadStatus() {
  try {
    const res: any = await http.get('/schedule/agent/status')
    agentEnabled.value = !!res.data?.enabled
    agentModel.value = res.data?.model || ''
    agentReason.value = res.data?.reason || ''
  } catch {
    agentEnabled.value = false
    agentReason.value = '无法连接军师服务'
  }
}

async function loadConversations() {
  loadingList.value = true
  try {
    const res: any = await http.get('/schedule/agent/conversations')
    conversations.value = res.data?.items || []
  } catch {
    conversations.value = []
  } finally {
    loadingList.value = false
  }
}

async function openConversation(id: string) {
  if (!id || sending.value) return
  activeId.value = id
  loadingThread.value = true
  messages.value = []
  try {
    const res: any = await http.get(`/schedule/agent/conversations/${id}`)
    messages.value = (res.data?.messages || []).map((m: any) => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content || '',
      tools: m.tools || [],
      charts: Array.isArray(m.charts) ? m.charts : [],
    }))
    if (route.query.c !== id) {
      await router.replace({ query: { ...route.query, c: id } })
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载对话失败')
    activeId.value = null
  } finally {
    loadingThread.value = false
    await scrollToBottom()
  }
}

function startNewChat() {
  activeId.value = null
  messages.value = []
  input.value = ''
  router.replace({ query: { ...route.query, c: undefined } })
  nextTick(() => composerRef.value?.focus())
}

async function sendMessage(text?: string) {
  const content = (text ?? input.value).trim()
  if (!content || sending.value) return
  if (!agentEnabled.value) {
    ElMessage.warning(agentReason.value || '军师未启用')
    return
  }

  messages.value.push({ role: 'user', content })
  if (!text) input.value = ''
  nextTick(() => {
    if (composerRef.value) {
      composerRef.value.style.height = 'auto'
    }
  })
  sending.value = true
  const assistantIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '', tools: [], charts: [], streaming: true })
  await scrollToBottom(true)

  try {
    const res = await fetch('/api/v1/schedule/agent/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
      },
      body: JSON.stringify({
        message: content,
        conversation_id: activeId.value || undefined,
      }),
    })
    if (!res.ok || !res.body) {
      const errText = await res.text().catch(() => '')
      let detail = errText
      try {
        const j = JSON.parse(errText)
        detail = typeof j.detail === 'string' ? j.detail : j.detail?.message || errText
      } catch {
        /* keep */
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let sawDone = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const lines = part.split('\n')
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const payload = trimmed.slice(5).trim()
          if (!payload || payload === '[DONE]') continue
          let ev: any
          try {
            ev = JSON.parse(payload)
          } catch {
            continue
          }
          const row = messages.value[assistantIdx]
          if (!row || row.role !== 'assistant') continue

          if (ev.type === 'meta') {
            if (ev.conversation_id) {
              activeId.value = ev.conversation_id
              if (route.query.c !== ev.conversation_id) {
                await router.replace({ query: { ...route.query, c: ev.conversation_id } })
              }
            }
          } else if (ev.type === 'token' && ev.text) {
            row.content += String(ev.text)
            await scrollToBottom()
          } else if (ev.type === 'tool') {
            row.tools = [...(row.tools || []), { name: ev.name, content: ev.content }]
          } else if (ev.type === 'chart' && ev.chart) {
            const next = [...(row.charts || []), ev.chart as ChartSpec]
            row.charts = next.slice(-6)
            await scrollToBottom()
          } else if (ev.type === 'done') {
            sawDone = true
            row.streaming = false
            if (ev.reply && !row.content.trim()) row.content = String(ev.reply)
            if (Array.isArray(ev.tool_traces) && ev.tool_traces.length) {
              row.tools = ev.tool_traces
            }
            if (Array.isArray(ev.charts) && ev.charts.length) {
              row.charts = ev.charts.slice(-6)
            }
            if (ev.conversation_id) activeId.value = ev.conversation_id
            await loadConversations()
          } else if (ev.type === 'error') {
            row.streaming = false
            row.content = row.content || String(ev.message || '发送失败')
            ElMessage.error(String(ev.message || '军师错误'))
          }
        }
      }
    }

    const row = messages.value[assistantIdx]
    if (row) {
      row.streaming = false
      if (!row.content.trim()) {
        row.content = sawDone ? '（空回复）' : '连接已断开，请重试'
      }
    }
    await loadConversations()
  } catch (e: any) {
    const row = messages.value[assistantIdx]
    const msg = e?.message || '发送失败，请重试'
    if (row && row.role === 'assistant') {
      row.streaming = false
      row.content = row.content || msg
    } else {
      messages.value.push({ role: 'assistant', content: msg })
    }
    ElMessage.error(msg)
  } finally {
    sending.value = false
    await scrollToBottom(true)
    composerRef.value?.focus()
  }
}

function onComposerKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendMessage()
  }
}

function autoGrow() {
  const el = composerRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

async function renameConversation(c: Conversation) {
  try {
    const { value } = await ElMessageBox.prompt('修改对话标题', '重命名', {
      inputValue: c.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '标题不能为空',
    })
    await http.patch(`/schedule/agent/conversations/${c.id}`, { title: String(value).trim() })
    await loadConversations()
  } catch {
    /* cancel */
  }
}

async function removeConversation(c: Conversation) {
  try {
    await ElMessageBox.confirm(`删除对话「${c.title}」？此操作不可恢复。`, '删除对话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await http.delete(`/schedule/agent/conversations/${c.id}`)
    if (activeId.value === c.id) startNewChat()
    await loadConversations()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  }
}

watch(
  () => route.query.c,
  (c) => {
    const id = typeof c === 'string' ? c : ''
    if (id && id !== activeId.value) void openConversation(id)
  },
)

onMounted(async () => {
  await Promise.all([loadStatus(), loadConversations()])
  const c = typeof route.query.c === 'string' ? route.query.c : ''
  if (c) await openConversation(c)
  else nextTick(() => composerRef.value?.focus())
})
</script>

<template>
  <div class="sa-shell">
    <aside class="sa-sidebar">
      <div class="sa-sidebar-head">
        <div class="sa-brand">
          <span class="sa-brand-mark"><el-icon :size="18"><ChatDotRound /></el-icon></span>
          <div class="sa-brand-copy">
            <div class="sa-brand-title">车间军师</div>
            <div class="sa-brand-sub">参谋排产 · 经营问数</div>
          </div>
        </div>
        <button type="button" class="sa-new-btn" @click="startNewChat">
          <el-icon><Plus /></el-icon>
          新对话
        </button>
        <el-input
          v-model="search"
          clearable
          size="small"
          placeholder="搜索对话"
          class="sa-search"
        />
      </div>

      <div v-loading="loadingList" class="sa-conv-list">
        <button
          v-for="c in filteredConversations"
          :key="c.id"
          type="button"
          class="sa-conv-item"
          :class="{ 'is-active': c.id === activeId }"
          @click="openConversation(c.id)"
        >
          <div class="sa-conv-main">
            <div class="sa-conv-title">{{ c.title }}</div>
            <div class="sa-conv-time">{{ formatTime(c.updated_at) }}</div>
          </div>
          <div class="sa-conv-actions" @click.stop>
            <button type="button" class="sa-icon-btn" title="重命名" @click="renameConversation(c)">
              <el-icon><EditPen /></el-icon>
            </button>
            <button type="button" class="sa-icon-btn is-danger" title="删除" @click="removeConversation(c)">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </button>
        <div v-if="!loadingList && !filteredConversations.length" class="sa-conv-empty">
          {{ search ? '无匹配对话' : '还没有对话，点上方开始' }}
        </div>
      </div>

      <div class="sa-sidebar-foot">
        <RouterLink class="sa-foot-link" to="/admin/schedule">← 返回排产</RouterLink>
      </div>
    </aside>

    <section class="sa-main">
      <header class="sa-main-head">
        <div class="sa-main-title-wrap">
          <h1 class="sa-main-title">{{ activeTitle }}</h1>
          <div class="sa-main-meta">
            <span v-if="agentEnabled" class="sa-pill">{{ agentModel || 'deepseek-chat' }}</span>
            <span v-else class="sa-pill is-warn">未启用</span>
            <span class="sa-hint">方案需人工确认后才落库</span>
          </div>
        </div>
        <div class="sa-main-actions">
          <el-button :icon="RefreshRight" text @click="loadConversations">刷新</el-button>
          <el-button :icon="Plus" @click="startNewChat">新对话</el-button>
        </div>
      </header>

      <div v-if="!agentEnabled" class="sa-banner">
        <el-icon class="sa-banner-icon"><WarningFilled /></el-icon>
        <div>
          <strong>军师暂不可用</strong>
          <p>{{ agentReason || '请配置 DEEPSEEK_API_KEY 并开启 SCHEDULE_AGENT_ENABLED。' }}</p>
          <p>规则引擎「智能方案」仍可在排产页独立使用。</p>
        </div>
      </div>

      <div v-loading="loadingThread" class="sa-thread">
        <div v-if="!messages.length && !sending" class="sa-empty">
          <div class="sa-empty-mark"><el-icon :size="36"><ChatDotRound /></el-icon></div>
          <h2>车间经营一问即得</h2>
          <p>
            覆盖排产负荷、在制进度、缺料采购、库存池与应收回款。结论基于系统指标与规则引擎，确认前不会改动现场数据。
          </p>
          <div class="sa-suggest-groups">
            <section
              v-for="g in suggestionGroups"
              :key="g.title"
              class="sa-suggest-group"
            >
              <h3 class="sa-suggest-group-title">{{ g.title }}</h3>
              <div class="sa-suggests">
                <button
                  v-for="s in g.items"
                  :key="s"
                  type="button"
                  class="sa-suggest"
                  :disabled="!agentEnabled || sending"
                  @click="sendMessage(s)"
                >
                  {{ s }}
                </button>
              </div>
            </section>
          </div>
        </div>

        <template v-else>
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="sa-msg"
            :class="m.role"
          >
            <div v-if="m.role === 'assistant'" class="sa-avatar" aria-hidden="true">助</div>
            <div class="sa-bubble-wrap">
              <div
                v-if="m.role === 'assistant'"
                class="sa-bubble sa-md"
                :class="{ 'is-streaming': m.streaming }"
              >
                <div v-if="m.content" v-html="renderMarkdown(m.content)" />
                <div v-else-if="m.streaming" class="sa-bubble is-typing inline">
                  <span /><span /><span />
                </div>
              </div>
              <div v-else class="sa-bubble">{{ m.content }}</div>
              <div v-if="m.role === 'assistant' && m.charts?.length" class="sa-charts">
                <AssistantChart
                  v-for="(c, ci) in m.charts"
                  :key="`${c.metric_id || 'chart'}-${ci}`"
                  :spec="c"
                />
              </div>
              <div v-if="m.tools?.length" class="sa-tools">
                <span v-for="(t, ti) in m.tools" :key="ti" class="sa-tool-chip">
                  {{ t.name || 'tool' }}
                </span>
              </div>
            </div>
            <div v-if="m.role === 'user'" class="sa-avatar is-user" aria-hidden="true">我</div>
          </div>
        </template>
        <div ref="threadEndRef" />
      </div>

      <footer class="sa-composer">
        <div class="sa-composer-box">
          <textarea
            ref="composerRef"
            v-model="input"
            class="sa-textarea"
            rows="1"
            placeholder="问排产、产量、缺料、库存、应收回款或利润… Enter 发送，Shift+Enter 换行"
            :disabled="!agentEnabled || sending"
            @input="autoGrow"
            @keydown="onComposerKeydown"
          />
          <button
            type="button"
            class="sa-send"
            :disabled="!agentEnabled || sending || !input.trim()"
            @click="sendMessage()"
          >
            <el-icon :size="18"><Promotion /></el-icon>
          </button>
        </div>
        <div class="sa-composer-note">
          DeepSeek 仅作编排与解释；排产走规则引擎，问数走指标白名单。关闭 AI 不影响排产页「智能方案」。
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.sa-shell {
  --sa-bg: #f4f6f9;
  --sa-panel: #ffffff;
  --sa-line: #e6ebf2;
  --sa-text: #0f172a;
  --sa-muted: #64748b;
  --sa-accent: #0076ff;
  --sa-accent-soft: #e8f3ff;
  --sa-sidebar: #f7f8fb;
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--sa-bg);
  color: var(--sa-text);
  overflow: hidden;
}

.sa-sidebar {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-sidebar);
  border-right: 1px solid var(--sa-line);
  min-height: 0;
}

.sa-sidebar-head {
  padding: 16px 14px 12px;
  border-bottom: 1px solid var(--sa-line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sa-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sa-brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(145deg, #0076ff, #005fcc);
  color: #fff;
  box-shadow: 0 6px 16px rgba(0, 118, 255, 0.25);
}

.sa-brand-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.sa-brand-sub {
  font-size: 11px;
  color: var(--sa-muted);
  margin-top: 1px;
}

.sa-new-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  border-radius: 10px;
  border: 1px solid #cfe2ff;
  background: var(--sa-panel);
  color: var(--sa-accent);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.12s ease;
}

.sa-new-btn:hover {
  background: var(--sa-accent-soft);
  border-color: #9ec5ff;
}

.sa-new-btn:active {
  transform: translateY(1px);
}

.sa-search :deep(.el-input__wrapper) {
  border-radius: 9px;
  box-shadow: 0 0 0 1px var(--sa-line) inset;
  background: #fff;
}

.sa-conv-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px;
}

.sa-conv-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  text-align: left;
  border: 0;
  background: transparent;
  border-radius: 10px;
  padding: 10px 10px;
  cursor: pointer;
  color: inherit;
  transition: background 0.12s ease;
}

.sa-conv-item:hover {
  background: rgba(15, 23, 42, 0.04);
}

.sa-conv-item.is-active {
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 0 0 1px var(--sa-line);
}

.sa-conv-main {
  flex: 1;
  min-width: 0;
}

.sa-conv-title {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sa-conv-time {
  margin-top: 3px;
  font-size: 11px;
  color: var(--sa-muted);
}

.sa-conv-actions {
  display: none;
  gap: 2px;
}

.sa-conv-item:hover .sa-conv-actions,
.sa-conv-item.is-active .sa-conv-actions {
  display: inline-flex;
}

.sa-icon-btn {
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--sa-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.sa-icon-btn:hover {
  background: #eef2f7;
  color: var(--sa-text);
}

.sa-icon-btn.is-danger:hover {
  background: #fee2e2;
  color: #dc2626;
}

.sa-conv-empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--sa-muted);
  font-size: 12px;
}

.sa-sidebar-foot {
  padding: 10px 14px 14px;
  border-top: 1px solid var(--sa-line);
}

.sa-foot-link {
  font-size: 12px;
  color: var(--sa-muted);
  text-decoration: none;
}

.sa-foot-link:hover {
  color: var(--sa-accent);
}

.sa-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-panel);
}

.sa-main-head {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--sa-line);
}

.sa-main-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.3;
}

.sa-main-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.sa-pill {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--sa-accent-soft);
  color: #005fcc;
  font-size: 11px;
  font-weight: 600;
}

.sa-pill.is-warn {
  background: #fff7ed;
  color: #c2410c;
}

.sa-hint {
  font-size: 12px;
  color: var(--sa-muted);
}

.sa-banner {
  display: flex;
  gap: 10px;
  margin: 12px 22px 0;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  font-size: 13px;
  line-height: 1.5;
}

.sa-banner p {
  margin: 2px 0 0;
}

.sa-banner-icon {
  margin-top: 2px;
  flex-shrink: 0;
}

.sa-thread {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 20px 22px 8px;
}

.sa-empty {
  max-width: 920px;
  margin: 4vh auto 24px;
  text-align: center;
}

.sa-empty-mark {
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(145deg, #0076ff, #0ea5e9);
  box-shadow: 0 12px 28px rgba(0, 118, 255, 0.28);
}

.sa-empty h2 {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.sa-empty > p {
  margin: 0 auto 22px;
  max-width: 560px;
  color: var(--sa-muted);
  font-size: 13px;
  line-height: 1.6;
}

.sa-suggest-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  text-align: left;
}

.sa-suggest-group {
  border: 1px solid var(--sa-line);
  border-radius: 14px;
  background: #fff;
  padding: 12px 12px 10px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.sa-suggest-group-title {
  margin: 0 0 8px;
  padding: 0 4px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #64748b;
}

.sa-suggests {
  display: grid;
  gap: 8px;
}

.sa-suggest {
  text-align: left;
  border: 1px solid transparent;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--sa-text);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.12s ease;
}

.sa-suggest:hover:not(:disabled) {
  border-color: #b3d4ff;
  background: var(--sa-accent-soft);
  transform: translateY(-1px);
}

.sa-suggest:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .sa-suggest-groups {
    grid-template-columns: 1fr;
  }
}

.sa-msg {
  display: flex;
  gap: 10px;
  width: 100%;
  max-width: 920px;
  margin: 0 auto 16px;
  align-items: flex-start;
  box-sizing: border-box;
}

.sa-msg.user {
  justify-content: flex-end;
}

.sa-msg.assistant {
  width: 100%;
}

.sa-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  background: #e2e8f0;
  color: #334155;
}

.sa-avatar.is-user {
  background: var(--sa-accent);
  color: #fff;
}

.sa-bubble-wrap {
  min-width: 0;
}

.sa-msg.assistant .sa-bubble-wrap {
  flex: 1;
  width: 100%;
  max-width: none;
}

.sa-msg.user .sa-bubble-wrap {
  max-width: min(680px, calc(100% - 84px));
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.sa-bubble {
  padding: 11px 14px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f1f5f9;
  color: var(--sa-text);
}

.sa-bubble.sa-md {
  white-space: normal;
  width: 100%;
  box-sizing: border-box;
}

.sa-bubble.sa-md :deep(p) {
  margin: 0 0 0.65em;
}

.sa-bubble.sa-md :deep(p:last-child) {
  margin-bottom: 0;
}

.sa-bubble.sa-md :deep(ul),
.sa-bubble.sa-md :deep(ol) {
  margin: 0.4em 0 0.7em;
  padding-left: 1.35em;
}

.sa-bubble.sa-md :deep(li) {
  margin: 0.2em 0;
}

.sa-bubble.sa-md :deep(strong) {
  font-weight: 700;
}

.sa-bubble.sa-md :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.9em;
  background: rgba(15, 23, 42, 0.06);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}

.sa-bubble.sa-md :deep(pre) {
  margin: 0.6em 0;
  padding: 10px 12px;
  overflow: auto;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
}

.sa-bubble.sa-md :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}

.sa-bubble.sa-md :deep(table) {
  display: table;
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin: 0.7em 0;
  font-size: 13px;
}

.sa-bubble.sa-md :deep(thead),
.sa-bubble.sa-md :deep(tbody),
.sa-bubble.sa-md :deep(tr) {
  width: 100%;
}

.sa-bubble.sa-md :deep(th),
.sa-bubble.sa-md :deep(td) {
  border: 1px solid #d8dee9;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.sa-bubble.sa-md :deep(th) {
  background: #eef3f9;
  font-weight: 700;
  white-space: normal;
}

.sa-bubble.sa-md :deep(tr:nth-child(even) td) {
  background: #fafbfd;
}

.sa-bubble.sa-md :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.2em 0 0.2em 0.9em;
  border-left: 3px solid #93c5fd;
  color: #475569;
}

.sa-bubble.sa-md.is-streaming {
  min-width: 48px;
}

.sa-bubble.is-typing.inline {
  display: inline-flex;
  background: transparent;
  padding: 4px 0;
}

.sa-msg.user .sa-bubble {
  background: var(--sa-accent);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.sa-msg.assistant .sa-bubble {
  border-bottom-left-radius: 4px;
}

.sa-bubble.is-typing {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  min-width: 52px;
  padding: 14px 16px;
}

.sa-bubble.is-typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #94a3b8;
  animation: sa-bounce 1.1s infinite ease-in-out;
}

.sa-bubble.is-typing span:nth-child(2) {
  animation-delay: 0.15s;
}

.sa-bubble.is-typing span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes sa-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.45;
  }
  40% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.sa-charts {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
  width: 100%;
}

.sa-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.sa-tool-chip {
  font-size: 11px;
  color: var(--sa-muted);
  background: #f8fafc;
  border: 1px solid var(--sa-line);
  border-radius: 999px;
  padding: 2px 8px;
}

.sa-composer {
  flex-shrink: 0;
  padding: 10px 22px 16px;
  border-top: 1px solid transparent;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), #fff 28%);
}

.sa-composer-box {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--sa-line);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 28px rgba(15, 23, 42, 0.06);
}

.sa-textarea {
  flex: 1;
  min-height: 44px;
  max-height: 160px;
  resize: none;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: var(--sa-text);
  background: transparent;
  padding: 8px 4px;
}

.sa-textarea:disabled {
  opacity: 0.6;
}

.sa-send {
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 12px;
  background: var(--sa-accent);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease, opacity 0.15s ease;
}

.sa-send:hover:not(:disabled) {
  background: #005fcc;
}

.sa-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.sa-composer-note {
  max-width: 860px;
  margin: 8px auto 0;
  font-size: 11px;
  color: var(--sa-muted);
  text-align: center;
  line-height: 1.4;
}

@media (max-width: 900px) {
  .sa-sidebar {
    width: 220px;
  }
  .sa-main-head,
  .sa-thread,
  .sa-composer {
    padding-left: 14px;
    padding-right: 14px;
  }
}

@media (max-width: 720px) {
  .sa-shell {
    flex-direction: column;
  }
  .sa-sidebar {
    width: 100%;
    height: 38vh;
    border-right: 0;
    border-bottom: 1px solid var(--sa-line);
  }
}
</style>
