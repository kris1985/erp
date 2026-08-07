<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { DEFAULT_INVENTORY, normalizeInventory, type InventoryConfig } from '@/inventory/types'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('inventory-recon')
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('inventory-anomalies')
const auth = useAuthStore()
const loading = ref(false)
const reconLoading = ref(false)
const saving = ref(false)
const inv = ref<InventoryConfig>(normalizeInventory(DEFAULT_INVENTORY))
const cutoverAt = ref<string | null>(null)
const recon = ref<any>(null)
const wasIssueRequired = ref(false)
const showCheck = ref(false)

const isAdmin = computed(() => auth.role === 'admin' || auth.baseRole === 'admin')
const anomalyCount = computed(() => Number(recon.value?.summary?.anomaly_count || 0))

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/inventory-settings')
    inv.value = normalizeInventory(res.data)
    wasIssueRequired.value = inv.value.issue_required
    cutoverAt.value = res.data?.cutover_at || null
  } finally {
    loading.value = false
  }
}

async function loadReconcile() {
  reconLoading.value = true
  try {
    const res: any = await http.get('/inventory-settings/reconcile')
    recon.value = res.data
  } finally {
    reconLoading.value = false
    void nextTick(measureTableHeight)
  }
}

async function saveFlags() {
  if (inv.value.issue_required && !wasIssueRequired.value) {
    try {
      await ElMessageBox.confirm(
        '打开后：车间领料要开单；没领过的订单不能报工。平时的「发车间登记」会关掉。确定打开？',
        '打开「必须领料」',
        { type: 'warning', confirmButtonText: '确定打开', cancelButtonText: '先不打开' },
      )
    } catch {
      inv.value.issue_required = false
      return
    }
  }
  saving.value = true
  try {
    const res: any = await http.patch('/inventory-settings', {
      kit_include_unallocated_pool: inv.value.kit_include_unallocated_pool,
      auto_allocate_on_receive: inv.value.auto_allocate_on_receive,
      issue_required: inv.value.issue_required,
    })
    inv.value = normalizeInventory(res.data)
    wasIssueRequired.value = inv.value.issue_required
    ElMessage.success('已保存')
    await auth.refreshPermissions()
  } finally {
    saving.value = false
  }
}

async function markCutover() {
  try {
    await ElMessageBox.confirm(
      '只在上线核对完库存后点一次，方便以后知道哪天切到新账法。平时不用点。',
      '记录「已核对完」',
      { type: 'info', confirmButtonText: '记录一下', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const res: any = await http.patch('/inventory-settings', { mark_cutover: true })
    inv.value = normalizeInventory(res.data)
    cutoverAt.value = res.data?.cutover_at || null
    ElMessage.success('已记录')
  } finally {
    saving.value = false
  }
}

async function openCheck() {
  showCheck.value = true
  if (!recon.value) await loadReconcile()
  else void nextTick(measureTableHeight)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">库存设置</h1>
        <p class="page-desc">材料怎么进仓、怎么分给订单、要不要强制领料</p>
      </div>
    </header>

    <div class="admin-card flow">
      <h3 class="flow-title">材料怎么走</h3>
      <ol class="flow-steps">
        <li><strong>采购到货</strong> → 先记进库存池（共用仓）</li>
        <li><strong>分给订单</strong> → 订单才有料可做（可自动，也可手动）</li>
        <li><strong>发到车间</strong> → 默认随手登记；也可改成必须开领料单</li>
      </ol>
    </div>

    <div class="admin-card">
      <h3 class="section-title">常用开关</h3>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">到货后自动分给订单</div>
          <div class="switch-hint">采购单上挂了哪张订单，到货就自动记到那张单上。一般保持打开。</div>
        </div>
        <el-switch v-if="isAdmin" v-model="inv.auto_allocate_on_receive" />
        <el-tag v-else :type="inv.auto_allocate_on_receive ? 'success' : 'info'" size="small">
          {{ inv.auto_allocate_on_receive ? '开' : '关' }}
        </el-tag>
      </div>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">齐套时先算上未分出的库存</div>
          <div class="switch-hint">
            <strong>默认关（更严）</strong>：必须先分到订单，齐套才算够。
            打开：仓里未分出的料也可计入齐套（上手快，但可能虚齐套，多人抢同一池料时风险大）。
          </div>
        </div>
        <el-switch v-if="isAdmin" v-model="inv.kit_include_unallocated_pool" />
        <el-tag v-else :type="inv.kit_include_unallocated_pool ? 'warning' : 'success'" size="small">
          {{ inv.kit_include_unallocated_pool ? '含未分配池' : '仅已分到单' }}
        </el-tag>
      </div>

      <div class="switch-row">
        <div class="switch-copy">
          <div class="switch-name">必须领料才能报工</div>
          <div class="switch-hint">
            默认关：组长可直接「发车间登记」。
            <strong>严管建议打开</strong>：要走领退料单，没领过不能报工；材料成本按实发量算。
          </div>
        </div>
        <el-switch v-if="isAdmin" v-model="inv.issue_required" />
        <el-tag v-else :type="inv.issue_required ? 'warning' : 'info'" size="small">
          {{ inv.issue_required ? '开' : '关' }}
        </el-tag>
      </div>

      <div v-if="isAdmin" class="actions">
        <el-button type="primary" :loading="saving" @click="saveFlags">保存</el-button>
      </div>

      <p class="now-line">
        现在：
        齐套{{ inv.kit_include_unallocated_pool ? '含未分配池' : '仅已分到单' }}
        ·
        <template v-if="inv.issue_required">必须领料 · 成本按发料</template>
        <template v-else>可直接登记发车间 · 成本按采购到货</template>
      </p>
    </div>

    <div class="admin-card">
      <div class="check-head">
        <div>
          <h3 class="section-title" style="margin: 0">库存核对</h3>
          <p class="check-hint">怀疑账对不上、或刚上线清库存时再看。平时不用管。</p>
        </div>
        <el-button v-if="!showCheck" @click="openCheck">查看核对</el-button>
        <el-button v-else link type="primary" :loading="reconLoading" @click="loadReconcile">刷新</el-button>
      </div>

      <template v-if="showCheck && recon">
        <div class="stat-row">
          <div class="stat">
            <div class="stat-label">仓里未分出</div>
            <div class="stat-value">{{ formatNum(recon.summary?.pool_total) }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">已分给订单</div>
            <div class="stat-value">{{ formatNum(recon.summary?.occupancy_total) }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">采购在途</div>
            <div class="stat-value">{{ formatNum(recon.summary?.in_transit_total) }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">需处理</div>
            <div class="stat-value" :class="{ warn: anomalyCount > 0 }">{{ anomalyCount }}</div>
          </div>
        </div>

        <p class="check-note">
          「仓里未分出 + 已分给订单」≈ 账上该有的料。实物差了去「库存池」里调整。
        </p>

        <div ref="tableHostRef">
        <el-table
          v-loading="reconLoading"
          :data="recon.lines || []"
          size="small"
          border
          stripe
          style="width: 100%; margin-top: 12px"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column prop="supplier_product_code" label="物料" :width="colWidth('supplier_product_code', 100)" resizable />
          <el-table-column prop="supplier_product_name" label="名称" :width="colWidth('supplier_product_name', 140)" resizable />
          <el-table-column column-key="warehouse_unallocated" label="仓里未分出" :width="colWidth('warehouse_unallocated', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.pool_qty) }}</template>
          </el-table-column>
          <el-table-column column-key="allocated_to_orders" label="已分给订单" :width="colWidth('allocated_to_orders', 100)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.order_occupancy_qty) }}</template>
          </el-table-column>
          <el-table-column column-key="ledger_total" label="账上合计" :width="colWidth('ledger_total', 90)" align="right" resizable>
            <template #default="{ row }">
              <strong>{{ formatNum(row.book_total_qty) }}</strong>
            </template>
          </el-table-column>
          <el-table-column column-key="in_transit" label="在途" :width="colWidth('in_transit', 80)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.in_transit_qty) }}</template>
          </el-table-column>
        </el-table>
        </div>

        <div v-if="(recon.anomalies || []).length" style="margin-top: 16px">
          <h4 class="section-title">需要处理</h4>
          <el-table :data="recon.anomalies" size="small" border @header-dragend="onHeaderDragend1">
            <el-table-column prop="order_no" label="订单" :width="colWidth1('order_no', 100)" resizable />
            <el-table-column prop="supplier_product_code" label="物料" :width="colWidth1('supplier_product_code', 100)" resizable />
            <el-table-column prop="message" label="说明" :width="colWidth1('message', 200)" resizable />
          </el-table>
        </div>

        <div v-if="isAdmin" class="actions" style="margin-top: 16px">
          <el-button :loading="saving" @click="markCutover">
            {{ cutoverAt ? `已核对（${cutoverAt}）` : '记录：库存已核对完' }}
          </el-button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.flow {
  margin-bottom: 12px;
}
.flow-title,
.section-title {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 600;
}
.flow-steps {
  margin: 0;
  padding-left: 1.25em;
  color: var(--el-text-color-regular);
  line-height: 1.85;
  font-size: 14px;
}
.switch-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.switch-row:last-of-type {
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
.actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.now-line {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.check-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.check-hint {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.check-note {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.stat {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 18px;
  font-weight: 600;
}
.stat-value.warn {
  color: var(--el-color-danger);
}
.admin-card + .admin-card {
  margin-top: 12px;
}
@media (max-width: 720px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .switch-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
