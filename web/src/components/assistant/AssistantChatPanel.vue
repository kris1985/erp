<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Promotion } from '@element-plus/icons-vue'
import AssistantChart, { type ChartSpec } from '@/components/assistant/AssistantChart.vue'
import { renderMarkdown } from '@/utils/markdown'

export type AssistantChatMsg = {
  role: 'user' | 'assistant'
  content: string
  tools?: { name?: string; content?: string }[]
  charts?: ChartSpec[]
  streaming?: boolean
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
}>()

const composerRef = ref<HTMLTextAreaElement | null>(null)
const threadEndRef = ref<HTMLElement | null>(null)

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
            <details
              v-if="m.role === 'assistant' && !m.streaming && m.tools?.length"
              class="sa-tools-fold"
            >
              <summary>调用了 {{ m.tools.length }} 个工具</summary>
              <div class="sa-tools">
                <span v-for="(t, ti) in m.tools" :key="ti" class="sa-tool-chip">
                  {{ t.name || 'tool' }}
                </span>
              </div>
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
  --sa-bg: #f3f6fa;
  --sa-panel: #ffffff;
  --sa-line: #e6ebf2;
  --sa-text: #0f172a;
  --sa-muted: #64748b;
  --sa-accent: #0076ff;
  --sa-accent-soft: #e8f3ff;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-panel);
  color: var(--sa-text);
  overflow: hidden;
  container-type: inline-size;
  container-name: sa-chat;
}

.sa-chat-banner {
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
  padding-top: 28px;
  padding-bottom: 12px;
  background:
    radial-gradient(720px 280px at 50% 0%, rgba(0, 118, 255, 0.07), transparent 60%);
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
  padding: 12px 14px 14px;
  border-radius: 12px;
  border: 1px solid #eef2f7;
  background: #fff;
}

.sa-msg.user .sa-bubble-wrap {
  max-width: min(680px, 100%);
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
  /* 长文/表格回复：贴画布，避免灰底套白卡片 */
  background: transparent;
  padding: 2px 2px 4px;
  border-radius: 0;
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

/* —— Markdown 表格：卡片式数据表 —— */
.sa-bubble.sa-md :deep(.sa-md-table) {
  margin: 0.75em 0;
  border: 1px solid #e4eaf2;
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
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--sa-text);
}

.sa-bubble.sa-md :deep(thead) {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

.sa-bubble.sa-md :deep(th) {
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid #e2e8f0;
  background: transparent;
  color: #64748b;
  font-size: 11px;
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
  border-top: 1px dashed #e8eef5;
  padding-top: 8px;
}

.sa-tools-fold > summary {
  list-style: none;
  cursor: pointer;
  user-select: none;
  font-size: 11px;
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
  font-size: 11px;
  color: var(--sa-muted);
  background: #f8fafc;
  border: 1px solid var(--sa-line);
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
  font-size: 11px;
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
  font-size: 11px;
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
  font-size: 13px;
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
  border-color: #d7e6fa;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.08);
}

.sa-composer-box {
  width: 100%;
  max-width: min(860px, 100%);
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--sa-line);
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
  max-width: min(860px, 100%);
  margin: 8px auto 0;
  font-size: 11px;
  color: var(--sa-muted);
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
  font-size: 13px;
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
  font-size: 12px;
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
  font-size: 13px;
  padding: 6px 2px;
}

.sa-chat-panel.is-compact .sa-send {
  width: 36px;
  height: 36px;
  border-radius: 10px;
}

.sa-chat-panel.is-compact .sa-composer-note {
  font-size: 10px;
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
    font-size: 11.5px;
  }
  .sa-bubble.sa-md :deep(th),
  .sa-bubble.sa-md :deep(td) {
    padding: 7px 8px;
  }
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
