<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">缺料汇总</h1>
        <p class="page-desc">待采购缺口 · 按供应商合并生成采购草稿</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="订单/物料/供应商"
          style="width: 200px"
          @clear="load"
          @keyup.enter="load"
        />
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          placeholder="供应商"
          style="width: 180px"
          @change="load"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-checkbox v-model="filters.rush_only" @change="load">仅插单</el-checkbox>
        <el-checkbox v-model="filters.hidePurchased" @change="load">隐藏已采购</el-checkbox>
        <span class="shared-switch">
          <el-switch v-model="includeShared" active-text="齐套计入库存池" @change="load" />
          <el-tooltip placement="bottom" :show-after="200">
            <template #content>
              <div class="tip-block">
                <div>算缺口/齐套时，是否把库存池按急单/交期拆分承诺计入各单（同一池不会被多单重复占满）。</div>
                <div>· 开：缺口 = 需求 − 本单已到 − 本单池承诺</div>
                <div>· 关：缺口 = 需求 − 本单已到（不看池）</div>
                <div>待购还会再扣「草稿 + 已下单在途」，避免重复勾选。</div>
              </div>
            </template>
            <button type="button" class="help-q" aria-label="说明">?</button>
          </el-tooltip>
        </span>
        <div class="spacer" />
        <el-button @click="load" :loading="loading">查询</el-button>
        <el-button type="primary" :disabled="!selected.length" @click="createPo">生成采购草稿</el-button>
      </div>
      <el-table
        ref="tableRef"
        :data="rows"
        stripe
        border
        style="width: 100%"
        row-key="id"
        @selection-change="(v: any[]) => (selected = v)"
      >
        <el-table-column type="selection" width="48" align="center" :selectable="canSelect" />
        <el-table-column label="图片" width="80" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              fit="contain"
              class="mat-thumb"
              preview-teleported
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="订单" min-width="140" align="left">
          <template #default="{ row }">
            {{ row.order_no }}
            <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 6px">插单</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="partner_name" label="供应商" min-width="120" align="left">
          <template #default="{ row }">{{ row.partner_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料编码" min-width="120" align="left" />
        <el-table-column prop="supplier_product_name" label="物料" min-width="160" align="left" />
        <el-table-column label="采购状态" min-width="110" align="left">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.purchase_status)" size="small" effect="plain">
              {{ row.purchase_status_label || '待采购' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="required_qty" label="需求" min-width="80" align="right" header-align="right" />
        <el-table-column prop="arrived_qty" label="已到" min-width="70" align="right" header-align="right" />
        <el-table-column label="草稿" min-width="70" align="right" header-align="right">
          <template #default="{ row }">{{ formatNum(row.draft_qty) }}</template>
        </el-table-column>
        <el-table-column label="在途" min-width="70" align="right" header-align="right">
          <template #default="{ row }">{{ formatNum(row.in_transit_qty) }}</template>
        </el-table-column>
        <el-table-column prop="shared_qty" label="池承诺" min-width="90" align="right" header-align="right" />
        <el-table-column prop="pool_qty" label="池余额" min-width="90" align="right" header-align="right" />
        <el-table-column prop="shortage_qty" label="缺口" min-width="80" align="right" header-align="right" />
        <el-table-column label="待购" min-width="80" align="right" header-align="right">
          <template #default="{ row }">
            <strong :class="{ muted: Number(row.to_buy_qty) <= 0 }">{{ formatNum(row.to_buy_qty) }}</strong>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

const rows = ref<any[]>([])
const selected = ref<any[]>([])
const suppliers = ref<any[]>([])
const loading = ref(false)
const includeShared = ref(true)
const tableRef = ref()
const filters = reactive({
  keyword: '',
  partner_id: null as number | null,
  rush_only: false,
  hidePurchased: true,
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function canSelect(row: any) {
  return Number(row.to_buy_qty) > 0
}

function statusTagType(status: string) {
  if (status === 'ordered') return 'success'
  if (status === 'draft') return 'warning'
  if (status === 'partial') return 'info'
  return 'danger'
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', { params: { role: 'supplier', active_only: true } })
  suppliers.value = res.data?.items || []
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/material-shortages', {
      params: {
        include_shared: includeShared.value,
        keyword: filters.keyword || undefined,
        partner_id: filters.partner_id || undefined,
        rush_only: filters.rush_only || undefined,
        hide_purchased: filters.hidePurchased,
      },
    })
    rows.value = res.data || []
    selected.value = []
  } finally {
    loading.value = false
  }
}

async function createPo() {
  const picks = selected.value.filter((r) => Number(r.to_buy_qty) > 0)
  if (!picks.length) {
    ElMessage.warning('请选择仍有待购数量的行')
    return
  }
  const res: any = await http.post('/purchase-orders/from-shortages', {
    requirement_ids: picks.map((r) => r.id),
    include_shared: includeShared.value,
  })
  const created = res.data || []
  if (!created.length) {
    ElMessage.warning('没有可生成的采购（可能已有草稿或已下单）')
  } else {
    ElMessage.success(`已生成 ${created.length} 张采购草稿`)
  }
  await load()
}

onMounted(async () => {
  await loadSuppliers()
  await load()
})
</script>

<style scoped>
.mat-thumb {
  width: 48px;
  height: 48px;
  border-radius: 6px;
  background: #f8fafc;
  display: block;
  margin: 0 auto;
}
.mat-thumb :deep(.el-image__inner) {
  object-fit: contain;
}
.shared-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.help-q {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid #cbd5e1;
  border-radius: 50%;
  background: #fff;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  cursor: help;
}
.help-q:hover {
  border-color: #0076ff;
  color: #0076ff;
}
.tip-block {
  max-width: 280px;
  line-height: 1.55;
  font-size: 12px;
}
.tip-block div + div {
  margin-top: 4px;
}
.muted {
  color: #94a3b8;
  font-weight: 400;
}
</style>
