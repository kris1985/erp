<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">库存池</h1>
        <p class="page-desc">
          池余额 = 未锁给订单 · 已占用 = 已分单未发出 · 在途 = 采购未收量 · 点「流水」看出入记录
        </p>
      </div>
    </header>
    <div :class="embedded ? 'inv-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="物料编码 / 名称"
          style="width: 220px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-button type="primary" @click="openAdjust()">调整库存</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="category-filter">
        <button
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === null }"
          @click="setCategoryFilter(null)"
        >
          全部
        </button>
        <button
          v-for="c in activeCategories"
          :key="c.id"
          type="button"
          class="cat-chip"
          :class="{ active: categoryFilter === c.id }"
          @click="setCategoryFilter(c.id)"
        >
          {{ c.name }}
        </button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          :data="pagedRows"
          stripe
          border
          v-loading="loading"
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            column-key="image"
            label="图片"
            :width="colWidth('image', 72)"
            align="center"
            class-name="mat-image-col"
            header-class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <el-image
                v-if="row.image_url"
                :src="row.image_url"
                :preview-src-list="[row.image_url]"
                preview-teleported
                fit="contain"
                class="product-thumb"
              />
              <span v-else class="muted mat-image-empty"></span>
            </template>
          </el-table-column>
          <el-table-column
            prop="supplier_product_code"
            label="物料编码"
            :width="colWidth('supplier_product_code', 120)"
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="物料名称"
            :width="colWidth('supplier_product_name', 160)"
            resizable
          />
          <el-table-column column-key="size_value" label="尺码" :width="colWidth('size_value', 72)" align="center" resizable>
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="pool_balance"
            label="池余额"
            :width="colWidth('pool_balance', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <strong>{{ formatNum(row.pool_qty ?? row.qty) }}</strong>
            </template>
          </el-table-column>
          <el-table-column
            column-key="allocated"
            label="已占用"
            :width="colWidth('allocated', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span :class="{ warn: Number(row.occupied_qty) > 0 }">{{ formatNum(row.occupied_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="in_transit"
            label="在途"
            :width="colWidth('in_transit', 90)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span :class="{ warn: Number(row.in_transit_qty) > 0 }">{{ formatNum(row.in_transit_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="avg_unit_cost"
            label="均价"
            :min-width="flexColMinWidth('avg_unit_cost', 80)"
            align="right"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.avg_unit_cost) }}</template>
          </el-table-column>
          <el-table-column column-key="actions" label="操作" :width="colWidth('actions', 160)" align="center" resizable>
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openLedger(row)">流水</el-button>
              <el-button link size="small" @click="openAdjust(row)">调整</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="filteredTotal"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="onPageChange"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-drawer v-model="ledgerVisible" :title="ledgerTitle" size="560px" destroy-on-close>
      <el-table
        v-loading="ledgerLoading"
        :data="ledgers"
        stripe
        border
        size="small"
        empty-text="暂无出入记录"
        @header-dragend="onHeaderDragend1"
      >
        <el-table-column column-key="time" label="时间" :width="colWidth1('time', 140)" resizable>
          <template #default="{ row }">
            {{ String(row.created_at || '').replace('T', ' ').slice(0, 19) || '—' }}
          </template>
        </el-table-column>
        <el-table-column column-key="type" label="类型" :width="colWidth1('type', 100)" resizable>
          <template #default="{ row }">
            <el-tag size="small" :type="ledgerTagType(row.ledger_type)" effect="plain">
              {{ row.ledger_type_label || row.ledger_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column column-key="size_value" label="尺码" :width="colWidth1('size_value', 64)" align="center" resizable>
          <template #default="{ row }">{{ row.size_value || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 90)" align="right" resizable>
          <template #default="{ row }">
            <span :class="Number(row.qty_delta) >= 0 ? 'in' : 'out'">
              {{ Number(row.qty_delta) >= 0 ? '+' : '' }}{{ formatNum(row.qty_delta) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column
          column-key="balance_after"
          label="余额后"
          :width="colWidth1('balance_after', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatNum(row.balance_after) }}</template>
        </el-table-column>
        <el-table-column column-key="order" label="订单" :width="colWidth1('order', 100)" resizable>
          <template #default="{ row }">{{ row.order_no || '—' }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" :width="colWidth1('note', 140)" show-overflow-tooltip resizable />
      </el-table>
    </el-drawer>

    <el-dialog v-model="adjustVisible" title="调整库存池" width="440px">
      <el-form label-width="100px">
        <el-form-item label="物料">
          <el-select
            v-model="form.supplier_product_id"
            filterable
            remote
            clearable
            placeholder="搜索物料"
            style="width: 100%"
            :remote-method="searchProducts"
            :loading="productLoading"
          >
            <el-option
              v-for="p in productOptions"
              :key="p.id"
              :label="`${p.product_code} · ${p.name || ''}`"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="尺码">
          <el-select
            v-model="form.size_id"
            clearable
            filterable
            placeholder="未按码留空"
            style="width: 100%"
          >
            <el-option v-for="s in sizes" :key="s.id" :label="s.size_value" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="增减数量">
          <el-input-number v-model="form.qty_delta" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单价(入库)">
          <el-input-number v-model="form.unit_cost" :min="0" :step="0.01" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注" required>
          <el-input v-model="form.note" placeholder="盘盈/盘亏原因（必填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustVisible = false">取消</el-button>
        <el-button type="primary" @click="doAdjust">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

withDefaults(
  defineProps<{
    /** 嵌在「库存」页 Tab 内时隐藏独立页头/卡片壳 */
    embedded?: boolean
  }>(),
  { embedded: false },
)

const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const tableRef = ref<{ doLayout?: () => void } | null>(null)
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('shared-materials-list', tableRef)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('shared-materials-ledger')
const rows = ref<any[]>([])
const categories = ref<any[]>([])
const sizes = ref<any[]>([])
const loading = ref(false)
const keyword = ref('')
const categoryFilter = ref<number | null>(null)
const page = ref(1)
const pageSize = ref(20)
const adjustVisible = ref(false)
const ledgerVisible = ref(false)
const ledgerLoading = ref(false)
const ledgers = ref<any[]>([])
const ledgerTitle = ref('出入流水')
const productOptions = ref<any[]>([])
const productLoading = ref(false)
const form = reactive({
  supplier_product_id: null as number | null,
  size_id: null as number | null,
  qty_delta: 0,
  unit_cost: undefined as number | undefined,
  note: '',
})

const activeCategories = computed(() => categories.value.filter((c) => c.is_active !== false))

const filteredRows = computed(() => {
  let list = rows.value
  if (categoryFilter.value != null) {
    list = list.filter((r) => Number(r.category_id) === Number(categoryFilter.value))
  }
  const q = keyword.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((r) => {
    const hay = `${r.supplier_product_code || ''} ${r.supplier_product_name || ''} ${r.size_value || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

const filteredTotal = computed(() => filteredRows.value.length)

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function ledgerTagType(t: string) {
  if (t === 'unallocated_receive' || t === 'receive_surplus' || t === 'release_from_order') return 'success'
  if (t === 'allocate_to_order' || t === 'issue_to_order') return 'warning'
  return 'info'
}

function setCategoryFilter(id: number | null) {
  categoryFilter.value = id
  page.value = 1
  void nextTick(measureTableHeight)
}

function onPageChange() {
  void nextTick(measureTableHeight)
}

function onPageSizeChange() {
  page.value = 1
  void nextTick(measureTableHeight)
}

function search() {
  page.value = 1
  void nextTick(measureTableHeight)
}

async function loadCategories() {
  const res: any = await http.get('/material-categories')
  categories.value = res.data?.items || res.data || []
}

async function loadSizes() {
  const res: any = await http.get('/sizes')
  sizes.value = res.data?.items || res.data || []
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/shared-materials')
    rows.value = res.data || []
  } finally {
    loading.value = false
    const maxPage = Math.max(1, Math.ceil(filteredTotal.value / pageSize.value) || 1)
    if (page.value > maxPage) page.value = maxPage
    void nextTick(measureTableHeight)
  }
}

async function searchProducts(q: string) {
  productLoading.value = true
  try {
    const res: any = await http.get('/supplier-products', {
      params: { page: 1, page_size: 30, keyword: q || undefined, active_only: true },
    })
    productOptions.value = res.data?.items || res.data || []
  } finally {
    productLoading.value = false
  }
}

function openAdjust(row?: any) {
  form.supplier_product_id = row?.supplier_product_id || null
  form.size_id = row?.size_id ?? null
  form.qty_delta = 0
  form.unit_cost = undefined
  form.note = ''
  if (row) {
    productOptions.value = [
      {
        id: row.supplier_product_id,
        product_code: row.supplier_product_code,
        name: row.supplier_product_name,
      },
    ]
  } else {
    searchProducts('')
  }
  adjustVisible.value = true
}

async function openLedger(row: any) {
  const sizePart = row.size_value ? ` · ${row.size_value}` : ''
  ledgerTitle.value = `流水 · ${row.supplier_product_code || ''} ${row.supplier_product_name || ''}${sizePart}`
  ledgerVisible.value = true
  ledgerLoading.value = true
  try {
    const res: any = await http.get('/shared-materials/ledgers', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id || undefined,
        limit: 200,
      },
    })
    ledgers.value = res.data || []
  } finally {
    ledgerLoading.value = false
  }
}

async function doAdjust() {
  if (!form.supplier_product_id) {
    ElMessage.warning('请选择物料')
    return
  }
  if (!form.qty_delta) {
    ElMessage.warning('请填写增减数量')
    return
  }
  const note = (form.note || '').trim()
  if (!note) {
    ElMessage.warning('请填写备注')
    return
  }
  await http.post('/shared-materials/adjust', {
    supplier_product_id: form.supplier_product_id,
    size_id: form.size_id || null,
    qty_delta: form.qty_delta,
    unit_cost: form.unit_cost,
    note,
  })
  ElMessage.success('已调整')
  adjustVisible.value = false
  load()
}

onMounted(async () => {
  await Promise.all([loadCategories(), loadSizes()])
  await load()
})
</script>

<style scoped>
.inv-panel {
  min-width: 0;
}
.category-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.cat-chip {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
}
.cat-chip:hover:not(:disabled) {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.cat-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.cat-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.product-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  display: block;
  margin: 0;
  border-radius: 4px;
}
.product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
:deep(td.mat-image-col) {
  padding: 2px !important;
}
:deep(th.mat-image-col) {
  padding: 8px 2px !important;
}
:deep(td.mat-image-col .cell) {
  padding: 2px !important;
  line-height: 0;
  width: 100%;
}
:deep(th.mat-image-col .cell) {
  padding: 0 2px !important;
}
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.muted {
  color: var(--el-text-color-secondary);
}
.warn {
  color: var(--el-color-warning);
  font-weight: 600;
}
.in {
  color: var(--el-color-success);
  font-weight: 600;
}
.out {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
