<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

type McpKeyRow = {
  id: number
  name: string
  key_prefix: string
  scopes: string[]
  is_active: boolean
  expires_at: string | null
  last_used_at: string | null
  created_at: string | null
}

const SCOPE_OPTIONS = [
  { value: 'intake', label: '接单参谋' },
  { value: 'schedule', label: '排产参谋' },
  { value: 'supply', label: '齐套供应链' },
  { value: 'ops', label: '厂务简报' },
]

const loading = ref(false)
const creating = ref(false)
const showInactive = ref(false)
const rows = ref<McpKeyRow[]>([])
const createVisible = ref(false)
const revealedKey = ref<string | null>(null)
const revealVisible = ref(false)

const form = reactive({
  name: '外部 Agent',
  scopes: ['intake', 'schedule', 'supply', 'ops'] as string[],
})

const tableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('mcp-keys-list', tableRef, {
  flexKey: 'scopes',
  flexDefaultMin: 180,
  fitToContainer: true,
})
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()

const scopeLabel = computed(() => {
  const map = Object.fromEntries(SCOPE_OPTIONS.map((o) => [o.value, o.label]))
  return (scopes: string[]) =>
    (scopes || []).map((s) => map[s] || s).join('、') || '—'
})

function fmtTime(v: string | null) {
  if (!v) return '—'
  return v.replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/mcp-keys', {
      params: { include_inactive: showInactive.value },
    })
    rows.value = Array.isArray(res.data?.items) ? res.data.items : []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = '外部 Agent'
  form.scopes = SCOPE_OPTIONS.map((o) => o.value)
  createVisible.value = true
}

async function createKey() {
  if (!form.scopes.length) {
    ElMessage.warning('至少选择一个能力面')
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/mcp-keys', {
      name: form.name.trim() || 'MCP Key',
      scopes: form.scopes,
    })
    createVisible.value = false
    revealedKey.value = res.data?.api_key || null
    revealVisible.value = true
    ElMessage.success('已创建')
    await load()
  } finally {
    creating.value = false
  }
}

async function copyKey() {
  const text = revealedKey.value
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

async function revoke(row: McpKeyRow) {
  try {
    await ElMessageBox.confirm(
      `吊销「${row.name}」（${row.key_prefix}…）后，使用该 Key 的外部 Agent 将无法再调用。`,
      '吊销 MCP Key',
      { type: 'warning', confirmButtonText: '吊销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await http.delete(`/mcp-keys/${row.id}`)
  ElMessage.success('已吊销')
  await load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div v-loading="loading">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">MCP 密钥</h1>
        <p class="page-desc">
          给外部 AI Agent 发 Bearer Key；按能力面隔离（接单 / 排产 / 供应链 / 厂务）。只读，不落库。
        </p>
      </div>
      <div class="page-hero-actions">
        <el-checkbox v-model="showInactive" @change="load">显示已吊销</el-checkbox>
        <el-button type="primary" @click="openCreate">新建 Key</el-button>
      </div>
    </header>

    <div class="admin-card">
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="rows"
          border
          stripe
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="name"
            label="名称"
            :width="colWidth('name', 140)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="key_prefix"
            label="前缀"
            :width="colWidth('key_prefix', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <code class="key-prefix">{{ row.key_prefix }}…</code>
            </template>
          </el-table-column>
          <el-table-column
            column-key="scopes"
            label="能力面"
            :width="colWidth('scopes', 180)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              {{ scopeLabel(row.scopes) }}
            </template>
          </el-table-column>
          <el-table-column
            column-key="status"
            label="状态"
            :width="colWidth('status', 88)"
            resizable
          >
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '有效' : '已吊销' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="last_used_at"
            label="最近使用"
            :width="colWidth('last_used_at', 160)"
            resizable
          >
            <template #default="{ row }">{{ fmtTime(row.last_used_at) }}</template>
          </el-table-column>
          <el-table-column
            prop="created_at"
            label="创建时间"
            :width="colWidth('created_at', 160)"
            resizable
          >
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" width="100" fixed="right" :resizable="false">
            <template #default="{ row }">
              <el-button
                v-if="row.is_active"
                link
                type="danger"
                @click="revoke(row)"
              >
                吊销
              </el-button>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <p class="foot-hint">
        端点：<code>/mcp/intake</code> · <code>/mcp/schedule</code> · <code>/mcp/supply</code> ·
        <code>/mcp/ops</code>；请求头 <code>Authorization: Bearer mcp_…</code>
      </p>
    </div>

    <el-dialog v-model="createVisible" title="新建 MCP Key" width="480px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：合作方 Agent" />
        </el-form-item>
        <el-form-item label="能力面">
          <el-checkbox-group v-model="form.scopes">
            <el-checkbox v-for="opt in SCOPE_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
              <span class="scope-id">{{ opt.value }}</span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createKey">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="revealVisible"
      title="请立即保存 API Key"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="revealedKey = null"
    >
      <p class="reveal-warn">明文只显示这一次，关闭后无法再查看，只能吊销重建。</p>
      <div class="reveal-box">
        <code>{{ revealedKey }}</code>
      </div>
      <template #footer>
        <el-button type="primary" @click="copyKey">复制</el-button>
        <el-button @click="revealVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.page-hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.key-prefix {
  font-size: 12px;
}
.muted {
  color: var(--el-text-color-secondary);
}
.foot-hint {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.55;
}
.foot-hint code {
  font-size: 12px;
}
.scope-id {
  margin-left: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.reveal-warn {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--el-color-warning-dark-2);
}
.reveal-box {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 12px 14px;
  word-break: break-all;
}
.reveal-box code {
  font-size: 13px;
  line-height: 1.5;
}
</style>
