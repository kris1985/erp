<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowRight,
  ChatDotRound,
  Delete,
  EditPen,
  Plus,
  WarningFilled,
} from '@element-plus/icons-vue'
import http from '@/api/http'
import AssistantChatPanel, {
  type AssistantChatMsg,
} from '@/components/assistant/AssistantChatPanel.vue'
import { type ChartSpec } from '@/components/assistant/AssistantChart.vue'
import { useAuthStore } from '@/stores/auth'

type ChatMsg = AssistantChatMsg

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
const chatPanelRef = ref<InstanceType<typeof AssistantChatPanel> | null>(null)

const SIDEBAR_KEY = 'ws_sa_sidebar_collapsed'
const sidebarCollapsed = ref(false)

function loadSidebarPref() {
  try {
    sidebarCollapsed.value = localStorage.getItem(SIDEBAR_KEY) === '1'
  } catch {
    sidebarCollapsed.value = false
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try {
    localStorage.setItem(SIDEBAR_KEY, sidebarCollapsed.value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

const TODAY_3_PROMPT =
  '按「今日行动」给我今日 3 件事：只讲最优先的 3 条，每条引用证据与单号；说明建议操作。若有产能校准建议可写入长期记忆。交期/负荷项可接着给排产方案建议（提醒我人工确认）。答复只用中文，不要甩英文指标名。'

/** 排产页未勾选：基于待排池现状给下一步 */
const POOL_NEXT_PROMPT =
  '你从「排产」入口进来。请先用 get_schedule_pool 查看当前待排池（齐套、急单、交期），必要时再查齐套可排产（query_metric analytics.kit_ready）和近两周负荷（get_daily_load）；然后：' +
  '① 用池数据总结：可立刻排 / 半齐套 / 等料各多少，点出优先单号与原因；' +
  '② 给出明确下一步（先催哪类料 / 先对哪些单出方案 / 是否要看合批）；' +
  '③ 对可排的优先单调用 generate_schedule_proposals，对比方案的延期与负荷含义，提醒我人工确认后才能落库。' +
  '禁止编造池里没有的单号或数量。答复只用中文。'

function selectedOrdersPrompt(orderIds: number[]) {
  return (
    `请针对生产单 id=${orderIds.join(',')} 做排产参谋：` +
    `先对照 get_schedule_pool / 齐套状态，说明哪些可立刻排、哪些等料；` +
    `给出可确认的排产方案建议（可用 generate_schedule_proposals），提醒我人工确认后落库。答复只用中文。`
  )
}

const suggestionGroups = [
  {
    key: 'diagnosis',
    title: '经营诊断',
    items: [
      { label: '今日 3 件事', prompt: TODAY_3_PROMPT },
      { label: '哪些单能排哪些等料', prompt: '做一次齐套可排产诊断：哪些急单/风险单已齐套可以立刻排，哪些半齐套可先开工，哪些等料不能空排。可排的请给出排产方案建议（提醒人工确认）。' },
      { label: '本周车间简报', prompt: '给我一份本周车间经营简报，重点看交期、齐套、负荷、缺料和质量，并附今日行动清单。' },
      { label: '交期与瓶颈诊断', prompt: '做一次交期与在制诊断：哪些单有风险，瓶颈在哪。' },
      { label: '产能负荷会不会爆', prompt: '分析未来两周产能负荷，有没有超产能，产能参数是否失真。' },
      { label: '本月经营健康度', prompt: '做一次经营财务诊断：毛利、亏损单、回款和应收。' },
    ],
  },
  {
    key: 'quality_loss',
    title: '质量损耗',
    items: [
      {
        label: '今日抽检盯哪几款',
        prompt:
          '查「质量预警」（近 14 天）：按严重度列出最多 3 条款×工序突增；说明今日该抽检哪几款哪道工序。答复只用中文，不要甩英文指标名。禁止编造未返回的款号或不良率。',
      },
      {
        label: '质量突增 vs 整体不良',
        prompt:
          '先查「质量预警」，再查「质量热点」：对比「款×工序突增」与「整体工序不良热点」差在哪；最多给 3 条可执行抽检建议。答复只用中文。禁止编造工具未返回的数字。',
      },
      {
        label: '今日有没有损耗超标',
        prompt:
          '只查「今日行动」：若其中有损耗超标项，引用证据与涉及单说明超标物料，并给处理建议；若没有则明确说「今日行动里没有损耗超标项」。答复只用中文，不要编造领料数量。',
      },
      {
        label: '方案对比延期与负荷峰',
        prompt:
          '先看齐套可排有哪些，再给出 2–3 套排产方案；对比各方案延期单数与负荷峰（超产能天数），用人话讲取舍，并提醒我在排产页人工确认后才能落库。答复只用中文。',
      },
    ],
  },
  {
    key: 'production',
    title: '生产进度',
    items: [
      { label: '今日各工序产量', prompt: '今日各工序产量多少？合格和不良各多少？' },
      { label: '在制单谁最落后', prompt: '在制订单整体进度怎样？哪些单最落后？' },
      { label: '延期风险与急单', prompt: '列出延期风险和急单，按交期紧迫排序' },
      { label: '当前工序瓶颈', prompt: '当前工序瓶颈在哪里？剩余量最大的是哪几道？' },
    ],
  },
  {
    key: 'schedule',
    title: '排产负荷',
    items: [
      { label: '本周负荷会不会爆', prompt: '这周各工序日负荷会不会爆？哪天最紧？' },
      { label: '未来 14 天负荷走势', prompt: '未来 14 天成型/针车负荷走势如何？' },
      { label: '插急单冲击评估', prompt: '帮我评估：如果插入一笔急单，对现有排产冲击大吗？' },
      { label: '按交期优先排谁', prompt: '按交期倒排，哪些单建议优先排？' },
    ],
  },
  {
    key: 'materials',
    title: '缺料采购',
    items: [
      { label: '最急缺料清单', prompt: '缺料最急的是哪些？分别影响哪些订单？' },
      { label: '急单相关缺料', prompt: '只看急单相关的缺料清单' },
      { label: '采购是否逾期', prompt: '在途采购有没有逾期或即将到期？' },
      { label: '库存池异常', prompt: '库存池余额偏低、占用偏高的材料有哪些？' },
    ],
  },
  {
    key: 'finance',
    title: '经营财务',
    items: [
      { label: '本月回款分布', prompt: '本月回款多少？按客户和按日怎么分布？' },
      { label: '未结应收客户', prompt: '未结应收还有多少？主要欠款客户是谁？' },
      { label: '本月利润概况', prompt: '本月利润概况：收入、成本、毛利各多少？' },
      { label: '经营 KPI 风险', prompt: '本月经营 KPI 一览，和关键风险点' },
    ],
  },
]

const activeSuggestKey = ref(suggestionGroups[0].key)

const activeSuggestGroup = computed(
  () => suggestionGroups.find((g) => g.key === activeSuggestKey.value) || suggestionGroups[0],
)

const homeGreeting = computed(() => {
  const h = new Date().getHours()
  if (h < 11) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const filteredConversations = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return conversations.value
  return conversations.value.filter((c) => (c.title || '').toLowerCase().includes(q))
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
  await chatPanelRef.value?.scrollToBottom(smooth)
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
    messages.value = []
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
  nextTick(() => chatPanelRef.value?.focusComposer())
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
    const pendingCharts: ChartSpec[] = []
    const pendingTools: { name?: string; content?: string }[] = []

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
            // 流式期间先缓存，避免工具标签打断阅读
            pendingTools.push({ name: ev.name, content: ev.content })
          } else if (ev.type === 'chart' && ev.chart) {
            // 流式期间先缓存，等正文结束后再出图
            pendingCharts.push(ev.chart as ChartSpec)
          } else if (ev.type === 'done') {
            sawDone = true
            if (ev.reply && !row.content.trim()) row.content = String(ev.reply)
            if (Array.isArray(ev.tool_traces) && ev.tool_traces.length) {
              row.tools = ev.tool_traces
            } else if (pendingTools.length) {
              row.tools = pendingTools.slice(-8)
            }
            const finalCharts = Array.isArray(ev.charts) && ev.charts.length
              ? (ev.charts as ChartSpec[])
              : pendingCharts
            row.charts = finalCharts.slice(-6)
            row.streaming = false
            if (ev.conversation_id) activeId.value = ev.conversation_id
            await loadConversations()
            await scrollToBottom(true)
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
      if (!row.charts?.length && pendingCharts.length) {
        row.charts = pendingCharts.slice(-6)
      }
      if (!row.tools?.length && pendingTools.length) {
        row.tools = pendingTools.slice(-8)
      }
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
    chatPanelRef.value?.focusComposer()
  }
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

async function consumeDeepLinkAsk() {
  if (activeId.value || messages.value.length || sending.value) return
  const ask = typeof route.query.ask === 'string' ? route.query.ask : ''
  const rawQ = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  const orderIds = String(route.query.order_ids || '')
    .split(',')
    .map((x) => Number(x.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)

  let prompt = ''
  if (rawQ) {
    prompt = rawQ
  } else if (ask === 'selected' || (ask === 'schedule' && orderIds.length)) {
    prompt = orderIds.length ? selectedOrdersPrompt(orderIds) : POOL_NEXT_PROMPT
  } else if (ask === 'pool' || ask === 'schedule') {
    prompt = POOL_NEXT_PROMPT
  } else if (ask === 'today' || ask === '1') {
    prompt = TODAY_3_PROMPT
  }
  if (!prompt) return

  // 清掉一次性深链参数，避免刷新重复自动提问
  const nextQuery: Record<string, any> = { ...route.query }
  delete nextQuery.ask
  delete nextQuery.q
  delete nextQuery.order_ids
  await router.replace({ query: nextQuery })
  await nextTick()
  await sendMessage(prompt)
}

onMounted(async () => {
  loadSidebarPref()
  await Promise.all([loadStatus(), loadConversations()])
  const c = typeof route.query.c === 'string' ? route.query.c : ''
  if (c) {
    await openConversation(c)
  } else {
    await nextTick()
    chatPanelRef.value?.focusComposer()
    await consumeDeepLinkAsk()
  }
})
</script>

<template>
  <div class="sa-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed }">
    <aside class="sa-sidebar">
      <div class="sa-sidebar-head">
        <div class="sa-brand-row">
          <div v-if="!sidebarCollapsed" class="sa-brand">
            <span class="sa-brand-mark" aria-hidden="true">
              <el-icon :size="18"><ChatDotRound /></el-icon>
            </span>
            <div class="sa-brand-copy">
              <div class="sa-brand-title">车间军师</div>
              <div class="sa-brand-sub">参谋排产 · 经营问数</div>
            </div>
          </div>
          <button
            type="button"
            class="sa-rail-btn sa-collapse-btn"
            :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
            @click="toggleSidebar"
          >
            <svg
              class="sa-sidebar-icon"
              viewBox="0 0 24 24"
              width="18"
              height="18"
              aria-hidden="true"
            >
              <rect
                x="3.5"
                y="4.5"
                width="17"
                height="15"
                rx="2.5"
                fill="none"
                stroke="currentColor"
                stroke-width="1.7"
              />
              <path
                d="M9 4.5v15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.7"
              />
            </svg>
          </button>
        </div>

        <button
          v-if="!sidebarCollapsed"
          type="button"
          class="sa-new-btn"
          title="开启新对话"
          @click="startNewChat"
        >
          <el-icon :size="16"><Plus /></el-icon>
          <span class="sa-new-label">开启新对话</span>
        </button>

        <el-input
          v-if="!sidebarCollapsed"
          v-model="search"
          clearable
          placeholder="搜索对话"
          class="sa-search"
        />
      </div>

      <div v-if="!sidebarCollapsed" v-loading="loadingList" class="sa-conv-list">
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
    </aside>

    <section class="sa-main">
      <AssistantChatPanel
        ref="chatPanelRef"
        v-model="input"
        :messages="messages"
        :sending="sending"
        :disabled="!agentEnabled || sending"
        :loading="loadingThread"
        placeholder="直接提问，或点选上方预设… Enter 发送，Shift+Enter 换行"
        note="军师只做参谋：排产走规则引擎，问数走指标白名单；关闭 AI 不影响排产页「智能方案」。"
        @send="sendMessage()"
      >
        <template #banner>
          <div v-if="!agentEnabled" class="sa-banner">
            <el-icon class="sa-banner-icon"><WarningFilled /></el-icon>
            <div>
              <strong>军师暂不可用</strong>
              <p>{{ agentReason || '请配置 DEEPSEEK_API_KEY 并开启 SCHEDULE_AGENT_ENABLED。' }}</p>
              <p>规则引擎「智能方案」仍可在排产页独立使用。</p>
            </div>
          </div>
        </template>
        <template #empty>
          <div class="sa-empty">
            <div class="sa-empty-hero">
              <div class="sa-empty-mark" aria-hidden="true">
                <el-icon :size="28"><ChatDotRound /></el-icon>
              </div>
              <p class="sa-empty-kicker">{{ homeGreeting }}</p>
              <h2>车间军师</h2>
              <p class="sa-empty-lead">选一个方向开始，或直接在下方输入问题。</p>
            </div>

            <div class="sa-suggest-panel">
              <div class="sa-suggest-tabs" role="tablist" aria-label="提问方向">
                <button
                  v-for="g in suggestionGroups"
                  :key="g.key"
                  type="button"
                  role="tab"
                  class="sa-suggest-tab"
                  :class="{ 'is-active': g.key === activeSuggestKey }"
                  :aria-selected="g.key === activeSuggestKey"
                  @click="activeSuggestKey = g.key"
                >
                  {{ g.title }}
                </button>
              </div>
              <div class="sa-suggests" role="tabpanel">
                <button
                  v-for="s in activeSuggestGroup.items"
                  :key="s.prompt"
                  type="button"
                  class="sa-suggest"
                  :disabled="!agentEnabled || sending"
                  @click="sendMessage(s.prompt)"
                >
                  <span class="sa-suggest-text">{{ s.label }}</span>
                  <el-icon class="sa-suggest-arrow"><ArrowRight /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </template>
      </AssistantChatPanel>
    </section>
  </div>
</template>

<style scoped>
.sa-shell {
  --sa-bg: #f3f6fa;
  --sa-panel: #ffffff;
  --sa-line: #e6ebf2;
  --sa-text: #0f172a;
  --sa-muted: #64748b;
  --sa-accent: #0076ff;
  --sa-accent-soft: #e8f3ff;
  --sa-sidebar: #f8fafc;
  display: flex;
  height: 100%;
  min-height: 0;
  background:
    radial-gradient(900px 420px at 70% -10%, rgba(0, 118, 255, 0.08), transparent 55%),
    var(--sa-bg);
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
  transition: width 0.2s ease;
  overflow: hidden;
}

.sa-shell.is-sidebar-collapsed .sa-sidebar {
  width: 64px;
}

.sa-sidebar-head {
  padding: 14px 12px 12px;
  border-bottom: 1px solid var(--sa-line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sa-brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
}

.sa-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.sa-brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  background: linear-gradient(145deg, #0076ff, #0ea5e9);
  color: #fff;
  box-shadow: 0 8px 18px rgba(0, 118, 255, 0.28);
}

.sa-brand-copy {
  min-width: 0;
}

.sa-brand-title {
  font-size: 15px;
  font-weight: 750;
  letter-spacing: -0.01em;
  white-space: nowrap;
}

.sa-brand-sub {
  font-size: 11px;
  color: var(--sa-muted);
  margin-top: 2px;
  white-space: nowrap;
}

.sa-rail-btn {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--sa-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease, color 0.15s ease;
}

.sa-rail-btn:hover {
  background: rgba(15, 23, 42, 0.06);
  color: var(--sa-text);
}

.sa-sidebar-icon {
  display: block;
}

.sa-shell.is-sidebar-collapsed .sa-sidebar-head {
  align-items: center;
  padding: 12px 8px;
  border-bottom: 0;
  gap: 8px;
}

.sa-shell.is-sidebar-collapsed .sa-brand-row {
  justify-content: center;
  min-height: auto;
}

.sa-shell.is-sidebar-collapsed .sa-collapse-btn {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: var(--sa-text);
}

.sa-shell.is-sidebar-collapsed .sa-collapse-btn:hover {
  background: rgba(15, 23, 42, 0.06);
}

.sa-new-btn {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px dashed #c9d5e5;
  background: #fff;
  color: var(--sa-text);
  font-size: 13px;
  font-weight: 550;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  box-shadow: none;
}

.sa-new-btn .el-icon {
  color: var(--sa-muted);
  transition: color 0.15s ease;
  flex-shrink: 0;
}

.sa-new-btn:hover {
  border-color: #9ec5ff;
  border-style: solid;
  background: var(--sa-accent-soft);
  color: #005fcc;
}

.sa-new-btn:hover .el-icon {
  color: var(--sa-accent);
}

.sa-new-btn:active {
  transform: none;
  background: #dcecff;
}

.sa-shell.is-sidebar-collapsed .sa-new-btn {
  width: 40px;
  height: 40px;
  padding: 0;
  margin: 0 auto;
  justify-content: center;
  border-style: solid;
  border-color: var(--sa-line);
}

.sa-search :deep(.el-input__wrapper) {
  min-height: 40px;
  padding: 4px 14px;
  border-radius: 12px;
  box-shadow: 0 0 0 1px var(--sa-line) inset;
  background: #fff;
  font-size: 14px;
}

.sa-search :deep(.el-input__inner) {
  height: 32px;
  line-height: 32px;
  font-size: 14px;
}

.sa-search :deep(.el-input__prefix),
.sa-search :deep(.el-input__suffix) {
  font-size: 16px;
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
  font-weight: 400;
  color: #0d0d0d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sa-conv-item:hover .sa-conv-title {
  color: #0d0d0d;
}

.sa-conv-item.is-active .sa-conv-title {
  color: #0f172a;
  font-weight: 600;
}

.sa-conv-time {
  margin-top: 3px;
  font-size: 11px;
  color: #94a3b8;
  font-weight: 400;
}

.sa-conv-item.is-active .sa-conv-time {
  color: #64748b;
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

.sa-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-panel);
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

.sa-empty {
  max-width: 640px;
  margin: 0 auto 18px;
  text-align: center;
}

.sa-empty-hero {
  margin: 0 auto 22px;
  padding: 8px 12px 0;
}

.sa-empty-mark {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(145deg, #0076ff, #0ea5e9);
  box-shadow: 0 14px 30px rgba(0, 118, 255, 0.28);
}

.sa-empty-kicker {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--sa-muted);
}

.sa-empty h2 {
  margin: 0 0 10px;
  font-size: 32px;
  font-weight: 750;
  letter-spacing: -0.035em;
  line-height: 1.15;
}

.sa-empty-lead {
  margin: 0 auto;
  max-width: 420px;
  color: var(--sa-muted);
  font-size: 14px;
  line-height: 1.6;
}

.sa-suggest-panel {
  text-align: left;
  border: 1px solid var(--sa-line);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.sa-suggest-tabs {
  display: flex;
  gap: 4px;
  padding: 10px;
  background: #f5f8fc;
  border-bottom: 1px solid var(--sa-line);
  overflow-x: auto;
}

.sa-suggest-tab {
  flex: 1;
  min-width: 0;
  height: 36px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--sa-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  padding: 0 10px;
  transition: background 0.15s ease, color 0.15s ease;
}

.sa-suggest-tab:hover {
  color: var(--sa-text);
  background: rgba(255, 255, 255, 0.7);
}

.sa-suggest-tab.is-active {
  background: #fff;
  color: var(--sa-accent);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.sa-suggests {
  display: grid;
  gap: 8px;
  padding: 12px;
}

.sa-suggest {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: #f5f8fc;
  border-radius: 12px;
  padding: 13px 14px;
  font-size: 14px;
  line-height: 1.4;
  color: var(--sa-text);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.12s ease, box-shadow 0.15s ease;
}

.sa-suggest-text {
  flex: 1;
  min-width: 0;
  font-weight: 550;
}

.sa-suggest-arrow {
  flex-shrink: 0;
  color: #94a3b8;
  transition: color 0.15s ease, transform 0.15s ease;
}

.sa-suggest:hover:not(:disabled) {
  border-color: #b3d4ff;
  background: var(--sa-accent-soft);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
}

.sa-suggest:hover:not(:disabled) .sa-suggest-arrow {
  color: var(--sa-accent);
  transform: translateX(2px);
}

.sa-suggest:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .sa-empty h2 {
    font-size: 26px;
  }

  .sa-suggest-tab {
    flex: 0 0 auto;
  }
}

@media (max-width: 900px) {
  .sa-sidebar {
    width: 240px;
  }
  .sa-shell.is-sidebar-collapsed .sa-sidebar {
    width: 64px;
  }
}

@media (max-width: 720px) {
  .sa-shell {
    flex-direction: column;
  }
  .sa-shell.is-sidebar-collapsed {
    flex-direction: row;
  }
  .sa-sidebar {
    width: 100%;
    height: 38vh;
    border-right: 0;
    border-bottom: 1px solid var(--sa-line);
  }
  .sa-shell.is-sidebar-collapsed .sa-sidebar {
    width: 64px;
    height: 100%;
    border-right: 1px solid var(--sa-line);
    border-bottom: 0;
  }
}
</style>
