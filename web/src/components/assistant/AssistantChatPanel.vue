<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowDown, ArrowRight, CollectionTag, MagicStick, Promotion } from '@element-plus/icons-vue'
import AssistantChart, { type ChartSpec } from '@/components/assistant/AssistantChart.vue'
import PresentationSpecView, { type PresentationSpec } from '@/components/assistant/PresentationSpecView.vue'
import { renderMarkdown } from '@/utils/markdown'

export type AssistantChatMsg = {
  role: 'user' | 'assistant'
  content: string
  tools?: { name?: string; content?: string }[]
  charts?: ChartSpec[]
  evidence?: AssistantEvidence[]
  activity?: { label: string; status?: string }[]
  agents?: AssistantAgentActivity[]
  todos?: (AssistantAction | string)[]
  detail?: { available?: boolean; kind?: 'deterministic' | 'summary'; content?: string }
  presentation?: AssistantPresentation
  trust?: 'verified' | 'estimated' | 'none' | string
  fastPath?: { decision: Record<string, unknown>; trust_metrics?: Record<string, unknown> }
  fastPathObservation?: Record<string, unknown>
  fastPathRejection?: Record<string, unknown>
  streaming?: boolean
}

export type AssistantAgentActivity = {
  id: string
  name: string
  description?: string
  task: string
  last_update?: string
  status: 'running' | 'done' | 'pending' | 'error' | string
}

export type AssistantPresentation = {
  type: 'metric_snapshot'
  title: string
  items: { label: string; value: string | number; unit?: string }[]
} | {
  type: 'period_comparison'
  title: string
  label: string
  current: { label: string; value: string | number; unit?: string }
  previous: { label: string; value: string | number; unit?: string }
  delta: string | number
  rate?: string | number | null
} | {
  type: 'ranking'
  title: string
  items: { label: string; value: string | number; unit?: string }[]
} | {
  type: 'time_series'
  title: string
  items: { label: string; value: string | number; unit?: string }[]
} | {
  type: 'exception_list'
  title: string
  items: { label: string; value: string | number; unit?: string; detail?: string }[]
} | {
  type: 'composition'
  title: string
  items: { label: string; value: string | number; share: string | number; unit?: string }[]
} | {
  type: 'data_table'
  title: string
  columns: string[]
  keys: string[]
  rows: Record<string, string | number | null>[]
} | {
  type: 'table'
  title?: string
  columns: string[]
  rows: string[][]
} | {
  type: 'attribution_analysis'
  title: string
  items: { label: string; value: string | number; unit?: string }[]
}

export type AssistantAction = {
  type: 'ai_followup' | 'navigate_form' | 'create_draft' | 'offline_task' | 'await_input'
  title: string
  owner_role?: string | null
  completion_signal?: string | null
  target_path?: string | null
  followup_prompt?: string | null
}

export type AssistantEvidence = {
  id: string
  source: string
  status: string
  facts: string[]
  as_of?: string
  queried_at?: string
}

/** 协议型展示（后端 Presentation Spec，schema_version=1.0）走组件注册表。 */
function isProtocolPresentation(p: AssistantPresentation | undefined): p is PresentationSpec {
  return !!p && (p as { schema_version?: string }).schema_version === '1.0'
}

const props = withDefaults(
  defineProps<{
    messages: AssistantChatMsg[]
    modelValue?: string
    sending?: boolean
    disabled?: boolean
    compact?: boolean
    placeholder?: string
    note?: string
    loading?: boolean
  }>(),
  {
    modelValue: '',
    sending: false,
    disabled: false,
    compact: false,
    placeholder: '直接提问… Enter 发送，Shift+Enter 换行',
    note: '',
    loading: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
  send: []
  action: [text: string]
}>()

const composerRef = ref<HTMLTextAreaElement | null>(null)
const threadEndRef = ref<HTMLElement | null>(null)
const copiedAction = ref('')

const input = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})

const isHome = computed(() => !props.messages.length && !props.sending && !props.loading)

async function scrollToBottom(smooth = false) {
  await nextTick()
  threadEndRef.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end' })
}

function autoGrow() {
  const el = composerRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, props.compact ? 120 : 160)}px`
}

function onComposerKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (!props.disabled && input.value.trim()) emit('send')
  }
}

function onSend() {
  if (!props.disabled && input.value.trim()) emit('send')
}

function actionMeta(todo: AssistantAction | string): AssistantAction {
  if (typeof todo === 'string') return { type: 'ai_followup', title: todo, followup_prompt: todo }
  return todo
}

/** 工具结果一句话摘要：不展开原始 JSON，避免过程折叠变成原始数据堆。 */
function toolSummary(content: string): string {
  const text = String(content ?? '').trim()
  if (!text) return '已执行'
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object') {
      const candidate = (parsed as Record<string, unknown>).summary
        ?? (parsed as Record<string, unknown>).message
        ?? (parsed as Record<string, unknown>).title
        ?? (parsed as Record<string, unknown>).error
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim()
      const keys = Object.keys(parsed)
      if (keys.length <= 3) return keys.join('、')
    }
  } catch {
    // 非 JSON：直接截断显示
  }
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}

function onTodoClick(todo: AssistantAction | string) {
  const action = actionMeta(todo)
  if (!props.disabled && action.type === 'ai_followup') emit('action', action.followup_prompt || action.title)
}

async function copyOfflineTask(todo: AssistantAction | string) {
  const action = actionMeta(todo)
  const note = [action.title, action.owner_role ? `负责人：${action.owner_role}` : '', action.completion_signal ? `完成条件：${action.completion_signal}` : ''].filter(Boolean).join('\n')
  try {
    await navigator.clipboard?.writeText(note)
    copiedAction.value = action.title
  } catch {
    copiedAction.value = action.title
  }
}

watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.content, props.sending],
  () => {
    void scrollToBottom()
  },
)

watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    autoGrow()
  },
)

defineExpose({ scrollToBottom, focusComposer: () => composerRef.value?.focus() })
</script>

<template>
  <div
    class="sa-chat-panel"
    :class="{ 'is-compact': compact, 'is-home': isHome }"
  >
    <div v-if="$slots.header" class="sa-chat-header">
      <slot name="header" />
    </div>

    <div v-if="$slots.banner" class="sa-chat-banner">
      <slot name="banner" />
    </div>

    <div v-loading="loading" class="sa-thread" :class="{ 'is-home': isHome }">
      <slot v-if="isHome" name="empty" />
      <template v-else>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="sa-msg"
          :class="m.role"
        >
          <div class="sa-bubble-wrap">
            <div v-if="m.role === 'assistant' && m.activity?.length" class="sa-agent-stream" aria-label="军师推理过程">
              <div
                v-for="(a, ai) in m.activity"
                :key="ai"
                class="sa-agent-event"
                :class="{ 'is-done': a.status === 'done' }"
              >
                <i :class="{ 'is-done': a.status === 'done' }" />
                {{ a.label }}
              </div>
            </div>
            <section v-if="m.role === 'assistant' && m.streaming && m.agents?.some(agent => agent.status !== 'done')" class="sa-agent-cards" aria-label="军师协作进度">
              <div class="sa-agent-cards-head">正在协作的军师</div>
              <div v-for="agent in m.agents.filter(agent => agent.status !== 'done')" :key="agent.id" class="sa-agent-card" :class="`is-${agent.status}`">
                <i class="sa-agent-state" />
                <div>
                  <strong>{{ agent.name }}</strong>
                  <p>{{ agent.task }}</p>
                  <small v-if="agent.last_update">{{ agent.last_update }}</small>
                </div>
                <em>{{ agent.status === 'done' ? '已完成' : agent.status === 'pending' ? '等待中' : '处理中' }}</em>
              </div>
            </section>
            <div
              v-if="m.role === 'assistant'"
              class="sa-bubble sa-md"
              :class="{ 'is-streaming': m.streaming }"
            >
              <template v-if="isProtocolPresentation(m.presentation)">
                <PresentationSpecView :spec="m.presentation" :reply="m.content" />
              </template>
              <template v-else-if="m.presentation?.type === 'metric_snapshot'">
                <section class="sa-metric-snapshot" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head">
                    <el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span>
                  </div>
                  <dl class="sa-snapshot-grid">
                    <div v-for="item in m.presentation.items" :key="item.label" class="sa-snapshot-item">
                      <dt>{{ item.label }}</dt>
                      <dd>{{ item.value }}<small>{{ item.unit }}</small></dd>
                    </div>
                  </dl>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'period_comparison'">
                <section class="sa-period-comparison" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <div class="sa-period-values">
                    <div><span>{{ m.presentation.current.label }}</span><strong>{{ m.presentation.current.value }}<small>{{ m.presentation.current.unit }}</small></strong></div>
                    <div><span>{{ m.presentation.previous.label }}</span><strong>{{ m.presentation.previous.value }}<small>{{ m.presentation.previous.unit }}</small></strong></div>
                    <div class="sa-period-delta" :class="{ 'is-down': Number(m.presentation.delta) < 0 }">
                      <span>变化</span><strong>{{ Number(m.presentation.delta) > 0 ? '+' : '' }}{{ m.presentation.delta }}<small>元{{ m.presentation.rate != null ? ` · ${Number(m.presentation.rate) > 0 ? '+' : ''}${m.presentation.rate}%` : '' }}</small></strong>
                    </div>
                  </div>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'ranking'">
                <section class="sa-ranking" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <ol>
                    <li v-for="(item, index) in m.presentation.items" :key="item.label">
                      <i>{{ index + 1 }}</i><span>{{ item.label }}</span><strong>{{ item.value }}<small>{{ item.unit }}</small></strong>
                    </li>
                  </ol>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'time_series'">
                <section class="sa-ranking" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <ol>
                    <li v-for="item in m.presentation.items" :key="item.label">
                      <i>·</i><span>{{ item.label }}</span><strong>{{ item.value }}<small>{{ item.unit }}</small></strong>
                    </li>
                  </ol>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'exception_list'">
                <section class="sa-ranking" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <ol>
                    <li v-for="item in m.presentation.items" :key="item.label">
                      <i>!</i><span>{{ item.label }}<small v-if="item.detail"> · {{ item.detail }}</small></span><strong>{{ item.value }}<small>{{ item.unit }}</small></strong>
                    </li>
                  </ol>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'composition'">
                <section class="sa-composition" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <div v-for="item in m.presentation.items" :key="item.label" class="sa-composition-row">
                    <span>{{ item.label }}</span><div><i :style="{ width: `${Math.min(100, Number(item.share))}%` }" /></div><strong>{{ item.share }}% · {{ item.value }}{{ item.unit }}</strong>
                  </div>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'data_table'">
                <section class="sa-data-table" :aria-label="m.presentation.title">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title }}</span></div>
                  <div class="sa-table-scroll"><table><thead><tr><th v-for="column in m.presentation.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(item, index) in m.presentation.rows" :key="index"><td v-for="key in m.presentation.keys" :key="key">{{ item[key] ?? '-' }}</td></tr></tbody></table></div>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'table'">
                <section class="sa-data-table" :aria-label="m.presentation.title || '客户销售额排行'">
                  <div class="sa-snapshot-head"><el-icon><MagicStick /></el-icon><span>{{ m.presentation.title || '客户销售额排行' }}</span></div>
                  <div class="sa-table-scroll"><table><thead><tr><th v-for="column in m.presentation.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in m.presentation.rows" :key="index"><td v-for="(cell, j) in row" :key="j">{{ cell }}</td></tr></tbody></table></div>
                </section>
              </template>
              <template v-else-if="m.presentation?.type === 'attribution_analysis'">
                <details class="sa-attribution"><summary>{{ m.presentation.title }}</summary><ol><li v-for="item in m.presentation.items" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}{{ item.unit }}</strong></li></ol></details>
              </template>
              <template v-else-if="m.content && !(m.charts?.length)">
                <!-- 有图表卡片时不渲染正文总结（图+分析说明已覆盖，避免冗余）；
                     无卡片场景（决策/接单/纯文本）保留正文结论 -->
                <div class="sa-conclusion-label">
                  <el-icon><MagicStick /></el-icon><span>结论</span>
                  <span v-if="m.trust === 'verified'" class="sa-trust-badge is-verified">已核验</span>
                  <span v-else-if="m.trust === 'estimated'" class="sa-trust-badge is-estimated">估算</span>
                </div>
                <div class="sa-decision-content" v-html="renderMarkdown(m.content)" />
              </template>
              <div v-else-if="m.streaming" class="sa-bubble is-typing inline">
                <span /><span /><span />
              </div>
            </div>
            <div v-else class="sa-bubble">{{ m.content }}</div>
            <div v-if="m.role === 'assistant' && !m.streaming && (m.fastPath || m.fastPathObservation)" class="sa-fast-path" :class="{ 'is-active': !!m.fastPath }">
              <template v-if="m.fastPath">
                <span class="sa-fp-badge is-active">确定性链路</span>
                <span class="sa-fp-route">数值与结论均已通过校验，可追溯</span>
              </template>
              <template v-else-if="m.fastPathObservation">
                <span class="sa-fp-badge is-observation">观测</span>
                <span class="sa-fp-route">该问题可走确定性链路，当前为观测模式</span>
              </template>
            </div>
            <div
              v-if="m.role === 'assistant' && !m.streaming && m.charts?.length"
              class="sa-charts"
            >
              <AssistantChart
                v-for="(c, ci) in m.charts"
                :key="`${c.metric_id || 'chart'}-${ci}`"
                :spec="c"
              />
            </div>
            <!-- 分析说明：紧跟卡片，不折叠（结论+原因+已核验事实直接可见）；
                 有卡片时不渲染正文总结，无卡片时正文结论先行 -->
            <section
              v-if="m.role === 'assistant' && !m.streaming && m.detail?.kind === 'summary' && m.detail.content"
              class="sa-analysis-open"
              aria-label="分析说明"
            >
              <div class="sa-analysis-head">
                <span class="sa-analysis-label">分析说明</span>
                <span v-if="m.trust === 'verified'" class="sa-trust-badge is-verified">已核验</span>
                <span v-else-if="m.trust === 'estimated'" class="sa-trust-badge is-estimated">估算</span>
              </div>
              <div class="sa-detail-content" v-html="renderMarkdown(m.detail.content)" />
            </section>
            <div v-if="m.role === 'assistant' && !m.streaming && m.todos?.length" class="sa-todo-stream">
              <strong><i />建议动作</strong>
              <div v-for="todo in m.todos" :key="typeof todo === 'string' ? todo : todo.title" class="sa-action-row">
                <span><el-icon class="sa-action-arrow"><ArrowRight /></el-icon>{{ actionMeta(todo).title }}</span>
                <button
                  v-if="actionMeta(todo).type === 'ai_followup'"
                  type="button"
                  :disabled="disabled"
                  @click="onTodoClick(todo)"
                ><b>继续分析</b></button>
                <a
                  v-else-if="actionMeta(todo).type === 'navigate_form' && actionMeta(todo).target_path"
                  :href="actionMeta(todo).target_path || undefined"
                ><b>去处理</b></a>
                <button
                  v-else-if="actionMeta(todo).type === 'offline_task'"
                  type="button"
                  @click="copyOfflineTask(todo)"
                ><b>{{ copiedAction === actionMeta(todo).title ? '已复制待办' : '复制待办' }}</b></button>
                <em v-else>{{ actionMeta(todo).type === 'await_input' ? '等待回填' : '需人工确认' }}</em>
              </div>
            </div>
            <details
              v-if="m.role === 'assistant' && !m.streaming && m.evidence?.length"
              class="sa-evidence-fold"
            >
              <summary>
                <el-icon><CollectionTag /></el-icon><span>依据</span><em>{{ m.evidence.length }} 个来源</em>
                <el-icon class="sa-evidence-chevron"><ArrowDown /></el-icon>
              </summary>
              <div class="sa-evidence-list">
                <article v-for="e in m.evidence" :key="e.id" class="sa-evidence-card">
                  <div class="sa-evidence-head">
                    <strong>{{ e.id }} · {{ e.source }}</strong>
                    <span :class="{ 'is-muted': e.status !== '已核验' }">{{ e.status }}</span>
                  </div>
                  <div v-if="e.as_of || e.queried_at" class="sa-evidence-time">
                    {{ e.as_of ? `数据截至：${e.as_of}` : `查询时间：${String(e.queried_at).replace('T', ' ')}` }}
                  </div>
                </article>
              </div>
            </details>
            <!-- 数据依据（fast path 确定性说明）：维持折叠 -->
            <details
              v-if="m.role === 'assistant' && !m.streaming && m.detail?.kind === 'deterministic' && m.detail.content"
              class="sa-detail-fold"
            >
              <summary>数据依据</summary>
              <div class="sa-detail-content" v-html="renderMarkdown(m.detail.content)" />
            </details>
          </div>
        </div>
      </template>
      <div ref="threadEndRef" />
    </div>

    <footer class="sa-composer" :class="{ 'is-home': isHome }">
      <div class="sa-composer-box">
        <textarea
          ref="composerRef"
          v-model="input"
          class="sa-textarea"
          rows="1"
          :placeholder="placeholder"
          :disabled="disabled"
          @input="autoGrow"
          @keydown="onComposerKeydown"
        />
        <button
          type="button"
          class="sa-send"
          :disabled="disabled || !input.trim()"
          @click="onSend"
        >
          <el-icon :size="compact ? 16 : 18"><Promotion /></el-icon>
        </button>
      </div>
      <div v-if="note" class="sa-composer-note">{{ note }}</div>
      <slot name="composer-extra" />
    </footer>
  </div>
</template>

<style scoped>
.sa-chat-panel {
  --ds-bg: #f3f6fa;
  --ds-panel: #ffffff;
  --ds-line: #e6ebf2;
  --ds-text: #0f172a;
  --ds-muted: #64748b;
  --ds-accent: #0076ff;
  --ds-accent-soft: #e8f3ff;
  --ds-font-sans: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Noto Sans SC', 'Helvetica Neue', sans-serif;
  --ds-font-num: 'DM Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'PingFang SC', sans-serif;
  font-family: var(--ds-font-sans);
  font-size: 16px;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--ds-panel);
  color: var(--ds-text);
  overflow: hidden;
  container-type: inline-size;
  container-name: sa-chat;
}

.sa-chat-banner {
  flex-shrink: 0;
}

.sa-chat-header {
  flex-shrink: 0;
}

.sa-thread {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 22px 8px;
  -webkit-overflow-scrolling: touch;
}

.sa-thread.is-home {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding-top: 40px;
  padding-bottom: 20px;
  background:
    radial-gradient(720px 280px at 50% 0%, rgba(0, 118, 255, 0.08), transparent 60%);
}

.sa-msg {
  display: flex;
  gap: 10px;
  width: 100%;
  max-width: min(920px, 100%);
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

.sa-bubble-wrap {
  min-width: 0;
}

.sa-msg.assistant .sa-bubble-wrap {
  flex: 1;
  width: 100%;
  max-width: none;
  box-sizing: border-box;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid #e6ebf2;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.025);
}

.sa-msg.user .sa-bubble-wrap {
  max-width: min(64%, 620px);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.sa-bubble {
  padding: 11px 14px;
  border-radius: 14px;
  font-size: 15px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f1f5f9;
  color: var(--ds-text);
}

.sa-bubble.sa-md {
  white-space: normal;
  width: 100%;
  box-sizing: border-box;
  /* 长文/表格回复：贴画布，避免灰底套白卡片 */
  background: transparent;
  padding: 2px 1px 3px;
  border-radius: 0;
}

.sa-bubble.sa-md :deep(p) {
  margin: 0 0 0.65em;
}

.sa-conclusion-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 0 0 7px;
  color: #64748b;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: .02em;
}

.sa-conclusion-label .el-icon { color: #0076ff; }

.sa-trust-badge {
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11.5px;
  font-weight: 650;
  letter-spacing: 0;
  white-space: nowrap;
}

.sa-trust-badge.is-verified {
  background: #d9efe1;
  color: #2f6b4c;
}

.sa-trust-badge.is-estimated {
  background: #fef3c7;
  color: #b45309;
}

/* A metric snapshot is a measurement strip, not another nested "card". */
.sa-metric-snapshot { padding: 2px 1px 5px; }
.sa-snapshot-head { display: flex; align-items: center; gap: 6px; margin-bottom: 12px; color: #334155; font-size: 14px; font-weight: 650; }
.sa-snapshot-head .el-icon { color: #0076ff; }
.sa-snapshot-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; border-top: 1px solid #e6ebf2; border-bottom: 1px solid #e6ebf2; }
.sa-snapshot-item { min-width: 0; padding: 12px 14px 13px; }
.sa-snapshot-item + .sa-snapshot-item { border-left: 1px solid #e6ebf2; }
.sa-snapshot-item dt { margin: 0 0 6px; color: #64748b; font-size: 12.5px; line-height: 1.35; }
.sa-snapshot-item dd { margin: 0; color: #0f172a; font-family: var(--ds-font-num); font-size: clamp(20px, 3.1cqw, 27px); font-weight: 650; line-height: 1.15; letter-spacing: -0.035em; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sa-snapshot-item dd small { margin-left: 3px; color: #64748b; font-size: 12.5px; font-weight: 500; letter-spacing: 0; }
.sa-period-comparison { padding: 2px 1px 5px; }
.sa-period-values { display: grid; grid-template-columns: 1fr 1fr 1.1fr; border-top: 1px solid #e6ebf2; border-bottom: 1px solid #e6ebf2; }
.sa-period-values > div { min-width: 0; padding: 12px 14px 13px; }
.sa-period-values > div + div { border-left: 1px solid #e6ebf2; }
.sa-period-values span { display: block; margin-bottom: 6px; color: #64748b; font-size: 12.5px; line-height: 1.35; }
.sa-period-values strong { display: block; color: #0f172a; font-family: var(--ds-font-num); font-size: clamp(18px, 2.7cqw, 24px); font-weight: 650; line-height: 1.15; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sa-period-values small { margin-left: 3px; color: #64748b; font-size: 12.5px; font-weight: 500; letter-spacing: 0; }
.sa-period-delta strong { color: #1fa971; font-family: var(--ds-font-num); }
.sa-period-delta.is-down strong { color: #e5484d; }
.sa-ranking { padding: 2px 1px 5px; }
.sa-ranking ol { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; border-top: 1px solid #e6ebf2; border-bottom: 1px solid #e6ebf2; }
.sa-ranking li { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 8px; min-height: 40px; padding: 0 12px; border-bottom: 1px solid #eef2f7; }
.sa-ranking li:last-child { border-bottom: 0; }
.sa-ranking i { color: #94a3b8; font-size: 12.5px; font-style: normal; font-variant-numeric: tabular-nums; }
.sa-ranking li:nth-child(-n+3) i { color: #0076ff; font-weight: 700; }
.sa-ranking span { overflow: hidden; color: #334155; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.sa-ranking strong { color: #0f172a; font-family: var(--ds-font-num); font-size: 15px; font-weight: 650; font-variant-numeric: tabular-nums; }
.sa-ranking small { margin-left: 3px; color: #64748b; font-size: 12px; font-weight: 500; }
.sa-composition { padding: 2px 1px 5px; }
.sa-composition-row { display: grid; grid-template-columns: 38px minmax(64px, 1fr) auto; align-items: center; gap: 9px; min-height: 34px; color: #475569; font-size: 14px; }
.sa-composition-row > div { overflow: hidden; height: 7px; border-radius: 999px; background: #e6ebf2; }
.sa-composition-row i { display: block; height: 100%; min-width: 2px; border-radius: inherit; background: #0076ff; }
.sa-composition-row:nth-child(3) i { background: #1fa971; }.sa-composition-row:nth-child(4) i { background: #d97706; }
.sa-composition-row strong { color: #334155; font-size: 12.5px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sa-data-table { padding: 2px 1px 5px; }.sa-table-scroll { overflow-x: auto; border: 1px solid #e6ebf2; border-radius: 8px; }.sa-data-table table { width: 100%; min-width: 520px; border-collapse: collapse; font-size: 13px; }.sa-data-table th { padding: 8px 10px; background: #f1f5f9; border-bottom: 1px solid #e6ebf2; color: #64748b; font-weight: 600; text-align: left; white-space: nowrap; }.sa-data-table td { padding: 8px 10px; border-top: 1px solid #e6ebf2; color: #334155; font-family: var(--ds-font-num); font-variant-numeric: tabular-nums; white-space: nowrap; }
.sa-attribution { margin-top: 8px; color: #64748b; font-size: 12.5px; }.sa-attribution summary { cursor: pointer; }.sa-attribution ol { margin: 8px 0 0; padding: 0; list-style: none; border-top: 1px solid #eef2f7; }.sa-attribution li { display: flex; justify-content: space-between; padding: 7px 2px; border-bottom: 1px solid #eef2f7; }.sa-attribution strong { color: #334155; font-variant-numeric: tabular-nums; }

/* 车间决策单：第一行只负责给出裁决，正文随后解释。 */
.sa-decision-content :deep(p:first-child) {
  margin: 0 0 10px;
  color: #0f172a;
  font-size: 17px;
  line-height: 1.6;
  letter-spacing: -0.01em;
}

.sa-decision-content :deep(p:first-child strong) {
  display: block;
}

.sa-decision-content :deep(p:nth-child(2)) {
  max-width: 920px;
  color: #475569;
  font-size: 16px;
  font-weight: 400;
  line-height: 1.6;
}

.sa-decision-content :deep(p:has(> strong:only-child)) {
  display: flex;
  align-items: center;
  margin: 15px 0 7px;
  color: #1e293b;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.sa-bubble.sa-md :deep(p:last-child) {
  margin-bottom: 0;
}

.sa-bubble.sa-md :deep(ul),
.sa-bubble.sa-md :deep(ol) {
  margin: 0.45em 0 0.2em;
  padding-left: 1.15em;
}

.sa-bubble.sa-md :deep(li) {
  margin: 0.32em 0;
  padding-left: 0.15em;
  color: #334155;
  font-size: 15px;
  line-height: 1.6;
}

.sa-bubble.sa-md :deep(li::marker) {
  color: #94a3b8;
}

.sa-bubble.sa-md :deep(strong) {
  font-weight: 700;
}

.sa-bubble.sa-md :deep(.sa-entity) {
  display: inline;
  padding: 0;
  background: transparent;
  color: #0f172a;
  font-size: inherit;
  font-weight: 600;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

.sa-bubble.sa-md :deep(.sa-entity-date) {
  background: transparent;
  color: #0f172a;
}

.sa-bubble.sa-md :deep(.sa-entity-risk) {
  background: transparent;
  color: #e5484d;
  font-weight: 700;
}

.sa-bubble.sa-md :deep(.sa-entity-warn) {
  background: transparent;
  color: #d97706;
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

/* —— Markdown 表格：卡片式数据表 —— */
.sa-bubble.sa-md :deep(.sa-md-table) {
  margin: 0.75em 0;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  background: #fff;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 0 0 1px rgba(255, 255, 255, 0.8) inset;
  overflow: hidden;
}

.sa-bubble.sa-md :deep(.sa-md-table-scroll) {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  max-width: 100%;
}

.sa-bubble.sa-md :deep(table) {
  display: table;
  width: 100%;
  min-width: 100%;
  max-width: none;
  table-layout: auto;
  border-collapse: separate;
  border-spacing: 0;
  margin: 0;
  font-size: 13.5px;
  line-height: 1.45;
  color: var(--ds-text);
}

.sa-bubble.sa-md :deep(thead) {
  background: #f1f5f9;
}

.sa-bubble.sa-md :deep(th) {
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid #e2e8f0;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.04em;
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
}

.sa-bubble.sa-md :deep(td) {
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  color: #0f172a;
  text-align: left;
  vertical-align: middle;
  word-break: break-word;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}

.sa-bubble.sa-md :deep(tbody tr:nth-child(even) td) {
  background: #f8fafc;
}

.sa-bubble.sa-md :deep(tbody tr:last-child td) {
  border-bottom: 0;
}

.sa-bubble.sa-md :deep(tbody tr:hover td) {
  background: #f5f9ff;
}

.sa-bubble.sa-md :deep(th:first-child),
.sa-bubble.sa-md :deep(td:first-child) {
  padding-left: 14px;
  font-weight: 550;
  color: #334155;
}

.sa-bubble.sa-md :deep(th:last-child),
.sa-bubble.sa-md :deep(td:last-child) {
  padding-right: 14px;
}

.sa-bubble.sa-md :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.35em 0 0.35em 0.85em;
  border-left: 3px solid #b3d4ff;
  color: #475569;
}

.sa-bubble.sa-md.is-streaming {
  min-width: 48px;
}

.sa-evidence-fold,
.sa-detail-fold {
  margin-top: 11px;
  color: #64748b;
  font-size: 12.5px;
}

.sa-detail-fold summary,
.sa-evidence-fold summary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  user-select: none;
  color: #64748b;
  transition: color 0.15s ease;
}

.sa-analysis-open {
  margin-top: 11px;
}

.sa-analysis-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 7px;
  color: #64748b;
  font-size: 12.5px;
}

.sa-analysis-label {
  font-weight: 600;
  letter-spacing: .02em;
}

.sa-detail-fold summary:hover,
.sa-evidence-fold summary:hover { color: #0076ff; }
.sa-detail-content { margin-top: 8px; padding: 11px 12px; border: 1px solid #e6ebf2; border-radius: 9px; background: #fff; color: #475569; font-size: 15px; line-height: 1.6; }

.sa-agent-stream { margin: -1px 0 12px; padding: 6px 9px; border-left: 2px solid #b3d4ff; background: transparent; color: #64748b; font-size: 12.5px; }
.sa-agent-stream-title { margin-bottom: 4px; color: #334155; font-weight: 650; }
.sa-agent-event { display: flex; align-items: center; gap: 7px; padding: 2px 0; }
.sa-agent-event i { width: 7px; height: 7px; border-radius: 50%; background: #4da0ff; box-shadow: none; animation: none; }
.sa-agent-event i.is-done { background: #1fa971; box-shadow: none; animation: none; }
.sa-agent-cards { display: grid; gap: 7px; margin: 0 0 12px; padding: 10px; border: 1px solid #dbe7f5; border-radius: 10px; background: #f5f9ff; }
.sa-agent-cards-head { color: #475569; font-size: 12.5px; font-weight: 650; }
.sa-agent-card { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: start; gap: 8px; padding: 7px 8px; border-radius: 7px; background: #fff; color: #475569; }
.sa-agent-state { width: 7px; height: 7px; margin-top: 5px; border-radius: 50%; background: #4da0ff; animation: sa-pulse 1.25s ease-in-out infinite; }
.sa-agent-card strong { color: #334155; font-size: 14px; }
.sa-agent-card p { margin: 2px 0 0; overflow: hidden; color: #64748b; font-size: 13px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.sa-agent-card small { display: block; margin-top: 3px; overflow: hidden; color: #94a3b8; font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.sa-agent-card em { padding-top: 2px; color: #64748b; font-size: 12.5px; font-style: normal; white-space: nowrap; }
.sa-agent-card.is-done .sa-agent-state { background: #1fa971; animation: none; }
.sa-agent-card.is-done em { color: #15803d; }
.sa-todo-stream { max-width: 100%; display: grid; gap: 2px; margin-top: 14px; padding: 10px; border: 1px solid #e6ebf2; border-radius: 10px; background: #f8fafc; color: #334155; font-size: 14px; box-sizing: border-box; }
.sa-fast-path { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; color: #64748b; font-size: 12.5px; line-height: 1.5; }
.sa-fast-path.is-active { border-color: #cfe6d8; background: #f2faf5; color: #3b7a57; }
.sa-fp-badge { padding: 1px 7px; border-radius: 10px; background: #e2e8f0; color: #475569; font-weight: 600; letter-spacing: 0; white-space: nowrap; }
.sa-fp-badge.is-active { background: #d9efe1; color: #2f6b4c; }
.sa-fp-badge.is-observation { background: #eef2f7; color: #64748b; }
.sa-fp-route { white-space: nowrap; }
.sa-todo-stream strong { display: flex; align-items: center; gap: 6px; padding: 1px 4px 5px; color: #334155; font-size: 14px; letter-spacing: 0; }
.sa-todo-stream strong i { display: inline-block; width: 5px; height: 5px; border: 0; border-radius: 50%; background: #64748b; }
.sa-action-row { display: flex; align-items: center; gap: 10px; min-height: 29px; padding: 5px 7px; border-radius: 6px; }
.sa-action-row:hover { background: #f1f5f9; }
.sa-action-row > span { display: flex; align-items: center; flex: 1; color: #475569; line-height: 1.6; }
.sa-action-arrow { flex-shrink: 0; margin-right: 6px; color: #94a3b8; font-size: 15px; }
.sa-action-row button,
.sa-action-row a,
.sa-action-row em { flex-shrink: 0; padding: 0; border: 0; border-radius: 0; color: #64748b; background: transparent; font: inherit; font-size: 12.5px; font-style: normal; font-weight: 500; line-height: 1.4; text-decoration: none; }
.sa-action-row button { cursor: pointer; }
.sa-action-row button:hover:not(:disabled),
.sa-action-row a:hover { color: #0076ff; }
.sa-action-row button:focus-visible,
.sa-action-row a:focus-visible { outline: 2px solid #0076ff; outline-offset: 1px; }
.sa-action-row button:disabled { cursor: not-allowed; opacity: .6; }
.sa-action-row em { color: #94a3b8; }
@keyframes sa-pulse { 50% { transform: scale(.72); opacity: .55; } }

.sa-evidence-fold summary {
  padding: 3px 0;
  color: #64748b;
}

.sa-evidence-fold summary em {
  padding-left: 6px;
  border-left: 1px solid #e2e8f0;
  color: #64748b;
  font-style: normal;
  font-variant-numeric: tabular-nums;
}

.sa-evidence-chevron { margin-left: 1px; color: #94a3b8; font-size: 12.5px; transition: transform .15s ease; }
.sa-evidence-fold[open] .sa-evidence-chevron { transform: rotate(180deg); }

.sa-detail-fold summary::-webkit-details-marker,
.sa-evidence-fold summary::-webkit-details-marker {
  display: none;
}

.sa-detail-fold summary::before {
  content: '';
  width: 0;
  height: 0;
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 5px solid currentColor;
  transition: transform .15s ease;
}

.sa-detail-fold[open] summary::before { transform: rotate(90deg); }

.sa-evidence-list {
  display: grid;
  gap: 7px;
  margin-top: 8px;
}

.sa-evidence-card {
  padding: 10px 11px;
  border: 1px solid #d9e8f7;
  border-radius: 10px;
  background: #f8fbff;
}

.sa-evidence-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #1e3a5f;
}

.sa-evidence-head span { color: #16794b; }
.sa-evidence-head span.is-muted { color: #a16207; }
.sa-evidence-facts { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.sa-evidence-facts span { padding: 3px 7px; border-radius: 5px; background: #e8f3ff; color: #334155; }
.sa-evidence-time { margin-top: 6px; color: #64748b; }
.sa-tool-summary { margin-top: 6px; color: #475569; font-size: 13px; line-height: 1.5; }
.sa-tools-fold .sa-evidence-head strong { font-family: var(--ds-font-num); font-size: 13px; }

.sa-bubble.is-typing.inline {
  display: inline-flex;
  background: transparent;
  padding: 4px 0;
}

.sa-msg.user .sa-bubble {
  background: linear-gradient(135deg, #0076ff 0%, #4da0ff 100%);
  color: #fff;
  padding: 11px 13px;
  border-radius: 16px 16px 4px 16px;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.5;
  box-shadow: 0 8px 18px rgba(0, 118, 255, 0.26);
}

.sa-msg.assistant .sa-bubble {
  border-bottom-left-radius: 4px;
}

.sa-msg.assistant .sa-bubble.sa-md {
  border-radius: 0;
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
  gap: 8px;
  margin-top: 6px;
  width: 100%;
}

.sa-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.sa-tools-fold {
  margin-top: 10px;
  border-top: 1px dashed #eef2f7;
  padding-top: 8px;
}

.sa-tools-fold > summary {
  list-style: none;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sa-tools-fold > summary::-webkit-details-marker {
  display: none;
}

.sa-tools-fold > summary::before {
  content: '';
  width: 0;
  height: 0;
  border-left: 4px solid #94a3b8;
  border-top: 3px solid transparent;
  border-bottom: 3px solid transparent;
  transition: transform 0.12s ease;
}

.sa-tools-fold[open] > summary::before {
  transform: rotate(90deg);
}

.sa-tools-fold[open] .sa-tools {
  margin-top: 8px;
}

.sa-tool-chip {
  font-size: 12px;
  color: var(--ds-muted);
  background: #f8fafc;
  border: 1px solid var(--ds-line);
  border-radius: 6px;
  padding: 2px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* 急单徽章 / 风险条 */
.sa-bubble.sa-md :deep(.sa-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 7px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
  line-height: 1;
  letter-spacing: 0.02em;
}

.sa-bubble.sa-md :deep(.sa-badge-rush) {
  background: #fff1f2;
  color: #e11d48;
  border: 1px solid #fecdd3;
}

.sa-bubble.sa-md :deep(.sa-badge-muted) {
  background: #f8fafc;
  color: #94a3b8;
  border: 1px solid #e2e8f0;
  font-weight: 500;
}

.sa-bubble.sa-md :deep(ul:has(.sa-risk-item)),
.sa-bubble.sa-md :deep(ol:has(.sa-risk-item)) {
  list-style: none;
  padding-left: 0;
  margin: 0.5em 0 0.75em;
}

.sa-bubble.sa-md :deep(.sa-risk-item) {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 0 8px;
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid #eef2f7;
  background: #fff;
  border-left-width: 3px;
  line-height: 1.5;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-late) {
  border-left-color: #f43f5e;
  background: #fff8f8;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-tight) {
  border-left-color: #f59e0b;
  background: #fffbeb;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-kit),
.sa-bubble.sa-md :deep(.sa-risk-item.is-cap) {
  border-left-color: #f97316;
  background: #fff7ed;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-pay) {
  border-left-color: #64748b;
  background: #f8fafc;
}

.sa-bubble.sa-md :deep(.sa-risk-tag) {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 650;
  color: #475569;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 5px;
  padding: 2px 7px;
  margin-top: 1px;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-late .sa-risk-tag) {
  color: #e11d48;
  background: #ffe4e6;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-tight .sa-risk-tag) {
  color: #b45309;
  background: #fef3c7;
}

.sa-bubble.sa-md :deep(.sa-risk-item.is-kit .sa-risk-tag),
.sa-bubble.sa-md :deep(.sa-risk-item.is-cap .sa-risk-tag) {
  color: #c2410c;
  background: #ffedd5;
}

.sa-bubble.sa-md :deep(.sa-risk-body) {
  flex: 1;
  min-width: 0;
  color: #334155;
  font-size: 14px;
}

.sa-composer {
  flex-shrink: 0;
  padding: 10px 22px 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), #fff 28%);
}

.sa-composer.is-home {
  background: transparent;
  padding-top: 4px;
}

.sa-composer.is-home .sa-composer-box {
  max-width: 720px;
  border-radius: 18px;
  border-color: #b3d4ff;
  box-shadow: 0 12px 36px rgba(0, 118, 255, 0.12);
}

.sa-composer-box {
  width: 100%;
  max-width: min(860px, 100%);
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--ds-line);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 8px 28px rgba(15, 23, 42, 0.06);
  box-sizing: border-box;
}

.sa-textarea {
  flex: 1;
  min-width: 0;
  min-height: 44px;
  max-height: 160px;
  resize: none;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 15px;
  line-height: 1.5;
  color: var(--ds-text);
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
  background: linear-gradient(135deg, #0076ff 0%, #4da0ff 100%);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: pointer;
  flex-shrink: 0;
  box-shadow: 0 6px 14px rgba(0, 118, 255, 0.3);
  transition: filter 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
}

.sa-send:hover:not(:disabled) {
  filter: brightness(1.06);
  box-shadow: 0 8px 18px rgba(0, 118, 255, 0.36);
}

.sa-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.sa-composer-note {
  max-width: min(860px, 100%);
  margin: 8px auto 0;
  font-size: 12px;
  color: var(--ds-muted);
  text-align: center;
  line-height: 1.4;
}

/* compact：抽屉 / 窄窗 */
.sa-chat-panel.is-compact .sa-thread {
  padding: 12px 14px 6px;
}

.sa-chat-panel.is-compact .sa-msg {
  margin-bottom: 12px;
}

.sa-chat-panel.is-compact .sa-bubble {
  padding: 9px 12px;
  font-size: 14px;
  border-radius: 12px;
}

.sa-chat-panel.is-compact .sa-msg.assistant .sa-bubble-wrap {
  padding: 10px 11px 11px 12px;
  border-radius: 10px;
}

.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(.sa-md-table) {
  margin: 0.55em 0;
  border-radius: 10px;
}

.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(table) {
  font-size: 13px;
}

.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(th),
.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(td) {
  padding: 7px 10px;
}

.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(th:first-child),
.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(td:first-child) {
  padding-left: 11px;
}

.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(th:last-child),
.sa-chat-panel.is-compact .sa-bubble.sa-md :deep(td:last-child) {
  padding-right: 11px;
}

.sa-chat-panel.is-compact .sa-composer {
  padding: 8px 12px 12px;
}

.sa-chat-panel.is-compact .sa-composer-box {
  padding: 8px 10px;
  border-radius: 14px;
  gap: 8px;
}

.sa-chat-panel.is-compact .sa-textarea {
  min-height: 36px;
  max-height: 120px;
  font-size: 14px;
  padding: 6px 2px;
}

.sa-chat-panel.is-compact .sa-send {
  width: 36px;
  height: 36px;
  border-radius: 10px;
}

.sa-chat-panel.is-compact .sa-composer-note {
  font-size: 11px;
  margin-top: 6px;
}

@container sa-chat (max-width: 420px) {
  .sa-thread {
    padding-left: 10px;
    padding-right: 10px;
  }
  .sa-composer {
    padding-left: 10px;
    padding-right: 10px;
  }
  .sa-bubble.sa-md :deep(.sa-md-table) {
    border-radius: 10px;
  }
  .sa-bubble.sa-md :deep(table) {
    font-size: 12.5px;
  }
  .sa-bubble.sa-md :deep(th),
  .sa-bubble.sa-md :deep(td) {
    padding: 7px 8px;
  }
  .sa-snapshot-grid { grid-template-columns: 1fr; }
  .sa-snapshot-item + .sa-snapshot-item { border-top: 1px solid #e6ebf2; border-left: 0; }
  .sa-period-values { grid-template-columns: 1fr; }
  .sa-period-values > div + div { border-top: 1px solid #e6ebf2; border-left: 0; }
}

@media (max-width: 720px) {
  .sa-thread {
    padding-left: 12px;
    padding-right: 12px;
  }
  .sa-composer {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
