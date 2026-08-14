<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">备库采购</h1>
        <p class="page-desc">安全库存 − 可用池/在途/草稿 · 辅料与订单无关</p>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="物料/供应商"
          style="width: 200px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.partner_id"
          clearable
          filterable
          placeholder="供应商"
          style="width: 180px"
          @change="search"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-checkbox v-model="filters.below_only" @change="search">仅低于安全库存</el-checkbox>
        <div class="spacer" />
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :disabled="!selected.length" :loading="creating" @click="createPo">
          去买料
        </el-button>
      </div>
      <p class="view-hint muted">
        辅料：线、胶水、小五金、打包材料等与订单无关。在供应商产品里填了安全库存才会出现。
      </p>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          border
          row-key="supplier_product_id"
          :max-height="tableMaxHeight"
          @selection-change="(v: any[]) => (selected = v)"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            type="selection"
            :width="colWidth('selection', 48)"
            align="center"
            :selectable="(row: any) => Boolean(row.can_create_draft)"
          />
          <el-table-column
            prop="supplier_product_code"
            label="物料编号"
            :width="colWidth('supplier_product_code', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="物料名称"
            :width="colWidth('supplier_product_name', 160)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="partner_name"
            label="供应商"
            :width="colWidth('partner_name', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="min_stock_qty"
            label="安全库存"
            :width="colWidth('min_stock_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.min_stock_qty) }}</template>
          </el-table-column>
          <el-table-column
            prop="free_pool_qty"
            label="可用池"
            :width="colWidth('free_pool_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.free_pool_qty) }}</template>
          </el-table-column>
          <el-table-column
            prop="in_transit_qty"
            label="在途"
            :width="colWidth('in_transit_qty', 80)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.in_transit_qty) }}</template>
          </el-table-column>
          <el-table-column
            prop="draft_qty"
            label="备库草稿"
            :width="colWidth('draft_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.draft_qty) }}</template>
          </el-table-column>
          <el-table-column
            prop="buy_qty"
            label="建议采购"
            :width="colWidth('buy_qty', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <strong>{{ formatNum(row.buy_qty) }}</strong>
            </template>
          </el-table-column>
          <el-table-column
            prop="unit_price"
            label="单价"
            :width="colWidth('unit_price', 88)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const props = withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  { embedded: false },
)

const route = useRoute()
const router = useRouter()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'stock-replenish-list',
  tableRef,
  {
    flexKey: 'supplier_product_name',
    flexDefaultMin: 160,
    fitToContainer: true,
  },
)
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

const loading = ref(false)
const creating = ref(false)
const rows = ref<any[]>([])
const selected = ref<any[]>([])
const suppliers = ref<any[]>([])
const filters = reactive({
  keyword: '',
  partner_id: null as number | null,
  below_only: true,
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/stock-replenishment', {
      params: {
        keyword: filters.keyword || undefined,
        partner_id: filters.partner_id || undefined,
        below_only: filters.below_only,
        include_shared: true,
      },
    })
    rows.value = res.data?.items || []
    selected.value = []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载备库建议失败')
    rows.value = []
  } finally {
    loading.value = false
    await nextTick()
    measureTableHeight()
    relayoutTable?.()
  }
}

function search() {
  void load()
}

async function createPo() {
  const picks = selected.value.filter((r) => r.can_create_draft)
  if (!picks.length) {
    ElMessage.warning('请选择有建议采购量的物料')
    return
  }
  try {
    await ElMessageBox.confirm(
      `按安全库存缺口买 ${picks.length} 项？\n不挂销售单，到料进共享池。`,
      '去买料',
      { type: 'warning' },
    )
  } catch {
    return
  }
  creating.value = true
  try {
    const res: any = await http.post('/purchase-orders/from-stock-replenishment', {
      supplier_product_ids: picks.map((r) => r.supplier_product_id),
      include_shared: true,
    })
    const created = res.data || []
    ElMessage.success(created.length ? `已开 ${created.length} 张备库草稿，还没发给供应商` : '已处理')
    selected.value = []
    await load()
    await router.replace({
      path: '/admin/purchase',
      query: { tab: 'orders', refresh: String(Date.now()) },
    })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成失败')
  } finally {
    creating.value = false
  }
}

watch(
  () => [String(route.query.tab || ''), String(route.query.source || '')],
  ([tab, source], prev) => {
    if (!props.embedded) return
    if (tab === prev?.[0] && source === prev?.[1]) return
    if ((tab === 'buy' && source === 'stock') || tab === 'stock' || tab === 'replenish') void load()
  },
)

onMounted(async () => {
  await loadSuppliers()
  await load()
})
</script>

<style scoped>
.view-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.4;
}
.purchase-panel {
  min-width: 0;
}
.spacer {
  flex: 1;
}
</style>
