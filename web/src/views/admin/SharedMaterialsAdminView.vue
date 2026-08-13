<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">库存池</h1>
        <p class="page-desc">
          现存量 = 可用 + 占用（厂内实物）· 在途单独列示 · 点「流水」看出入记录
        </p>
      </div>
    </header>
    <div :class="embedded ? 'inv-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="编号 / 名称 / 颜色 / 尺码 / 供应商"
          style="width: 280px"
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
            label="物料图片"
            :width="colWidth('image', 72)"
            align="center"
            header-align="center"
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
            label="物料编号"
            :width="colWidth('supplier_product_code', 120)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="名称"
            :width="colWidth('supplier_product_name', 140)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="category_name"
            label="分类"
            :width="colWidth('category_name', 110)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.category_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="color_name"
            label="颜色"
            :width="colWidth('color_name', 90)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="size_value"
            label="尺码"
            :width="colWidth('size_value', 72)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="unit_price"
            label="单价"
            :width="colWidth('unit_price', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column
            prop="pricing_unit_name"
            label="计价单位"
            :width="colWidth('pricing_unit_name', 90)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="partner_name"
            label="供应商"
            :width="colWidth('partner_name', 130)"
            align="center"
            header-align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.partner_name || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="on_hand"
            :width="colWidth('on_hand', 100)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                现存量
                <el-tooltip
                  content="现存量 = 可用 + 占用，即厂内实物；不含采购在途"
                  placement="top"
                >
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <strong>{{ formatNum(onHandQty(row)) }}</strong>
            </template>
          </el-table-column>
          <el-table-column
            column-key="allocated"
            :width="colWidth('allocated', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                占用
                <el-tooltip content="已分到执行单但还未领料的数量" placement="top">
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-popover
                v-if="Number(row.occupied_qty) > 0"
                placement="bottom"
                :width="700"
                trigger="hover"
                :show-after="180"
                popper-class="pool-detail-popper"
                @show="loadOccupancy(row)"
              >
                <template #reference>
                  <span class="qty-hover warn">{{ formatNum(row.occupied_qty) }}</span>
                </template>
                <div v-loading="detailLoadingKey === detailKey(row, 'occ')" class="pool-detail-panel">
                  <div class="pool-detail-title">占用明细</div>
                  <el-table
                    class="pool-detail-table"
                    :data="occupancyCache[detailKey(row, 'occ')] || []"
                    size="small"
                    border
                    stripe
                    max-height="260"
                    empty-text="暂无占用"
                  >
                    <el-table-column
                      prop="sales_order_no"
                      label="销售单"
                      min-width="100"
                      align="center"
                      show-overflow-tooltip
                    >
                      <template #default="{ row: r }">{{ r.sales_order_no || '—' }}</template>
                    </el-table-column>
                    <el-table-column
                      prop="customer_name"
                      label="客户名称"
                      min-width="88"
                      align="center"
                      show-overflow-tooltip
                    />
                    <el-table-column
                      column-key="image"
                      label="物料图片"
                      width="60"
                      align="center"
                    >
                      <template #default="{ row: r }">
                        <el-image
                          v-if="r.image_url"
                          :src="r.image_url"
                          :preview-src-list="[r.image_url]"
                          preview-teleported
                          fit="contain"
                          class="occ-thumb"
                        />
                        <span v-else class="muted">—</span>
                      </template>
                    </el-table-column>
                    <el-table-column
                      prop="supplier_product_code"
                      label="物料编号"
                      min-width="100"
                      align="center"
                      show-overflow-tooltip
                    >
                      <template #default="{ row: r }">{{ r.supplier_product_code || '—' }}</template>
                    </el-table-column>
                    <el-table-column prop="occupied_qty" label="占用数量" width="72" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.occupied_qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="delivery_date" label="交货日期" width="100" align="center">
                      <template #default="{ row: r }">{{ r.delivery_date || '—' }}</template>
                    </el-table-column>
                    <el-table-column
                      prop="order_no"
                      label="执行单"
                      min-width="100"
                      align="center"
                      show-overflow-tooltip
                    >
                      <template #default="{ row: r }">{{ r.header_no || r.order_no || '—' }}</template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-popover>
              <span v-else>{{ formatNum(row.occupied_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="pool_balance"
            :width="colWidth('pool_balance', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                可用
                <el-tooltip content="现存量 − 占用" placement="top">
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              {{ formatNum(row.pool_qty ?? row.qty) }}
            </template>
          </el-table-column>
          <el-table-column
            column-key="in_transit"
            :width="colWidth('in_transit', 88)"
            align="center"
            header-align="center"
            resizable
          >
            <template #header>
              <span class="col-h">
                在途
                <el-tooltip
                  content="采购已下单/在运/部分到货的未收量；不计入现存量"
                  placement="top"
                >
                  <el-icon class="col-h-tip" @click.stop><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-popover
                v-if="Number(row.in_transit_qty) > 0"
                placement="bottom"
                :width="620"
                trigger="hover"
                :show-after="180"
                popper-class="pool-detail-popper"
                @show="loadInTransit(row)"
              >
                <template #reference>
                  <span class="qty-hover warn">{{ formatNum(row.in_transit_qty) }}</span>
                </template>
                <div v-loading="detailLoadingKey === detailKey(row, 'tr')" class="pool-detail-panel">
                  <div class="pool-detail-title">在途采购明细</div>
                  <el-table
                    :data="inTransitCache[detailKey(row, 'tr')] || []"
                    size="small"
                    border
                    stripe
                    max-height="260"
                    empty-text="暂无在途"
                  >
                    <el-table-column prop="po_no" label="采购单号" min-width="110" show-overflow-tooltip />
                    <el-table-column prop="supplier_name" label="供应商" min-width="100" show-overflow-tooltip />
                    <el-table-column prop="status_label" label="状态" width="88" align="center" />
                    <el-table-column prop="qty" label="采购量" width="72" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="received_qty" label="已收" width="64" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.received_qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="open_qty" label="在途" width="64" align="center">
                      <template #default="{ row: r }">{{ formatNum(r.open_qty) }}</template>
                    </el-table-column>
                    <el-table-column prop="expected_date" label="协商交货日期" width="120" align="center">
                      <template #default="{ row: r }">{{ r.expected_date || '—' }}</template>
                    </el-table-column>
                    <el-table-column prop="order_no" label="关联执行单" min-width="100" show-overflow-tooltip>
                      <template #default="{ row: r }">{{ r.header_no || r.order_no || '—' }}</template>
                    </el-table-column>
                  </el-table>
                </div>
              </el-popover>
              <span v-else>{{ formatNum(row.in_transit_qty) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actions"
            label="操作"
            width="140"
            align="center"
            header-align="center"
            fixed="right"
            :resizable="false"
          >
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

    <el-drawer
      v-model="ledgerVisible"
      class="ledger-drawer"
      :title="ledgerTitle"
      size="900px"
      destroy-on-close
    >
      <div class="ledger-drawer-body">
        <el-table
          v-loading="ledgerLoading"
          :data="pagedLedgers"
          stripe
          border
          size="small"
          empty-text="暂无出入记录"
          height="100%"
          @header-dragend="onHeaderDragend1"
        >
          <el-table-column column-key="time" label="时间" :width="colWidth1('time', 160)" resizable>
            <template #default="{ row }">
              {{ String(row.created_at || '').replace('T', ' ').slice(0, 19) || '—' }}
            </template>
          </el-table-column>
          <el-table-column column-key="type" label="类型" :width="colWidth1('type', 110)" resizable>
            <template #default="{ row }">
              <el-tag size="small" :type="ledgerTagType(row.ledger_type)" effect="plain">
                {{ row.ledger_type_label || row.ledger_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            column-key="size_value"
            label="尺码"
            :width="colWidth1('size_value', 72)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 90)" align="center" resizable>
            <template #default="{ row }">
              <span :class="Number(row.qty_delta) >= 0 ? 'in' : 'out'">
                {{ Number(row.qty_delta) >= 0 ? '+' : '' }}{{ formatNum(row.qty_delta) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="balance_after"
            label="余额后"
            :width="colWidth1('balance_after', 88)"
            align="center"
            resizable
          >
            <template #default="{ row }">{{ formatNum(row.balance_after) }}</template>
          </el-table-column>
          <el-table-column column-key="order" label="执行单" :width="colWidth1('order', 120)" resizable>
            <template #default="{ row }">{{ row.header_no || row.order_no || '—' }}</template>
          </el-table-column>
          <el-table-column
            column-key="note"
            prop="note"
            label="备注"
            :min-width="colWidth1('note', 160)"
            show-overflow-tooltip
            resizable
          />
        </el-table>
        <div class="ledger-pagination">
          <el-pagination
            v-model:current-page="ledgerPage"
            v-model:page-size="ledgerPageSize"
            background
            small
            layout="total, sizes, prev, pager, next"
            :total="ledgers.length"
            :page-sizes="[20, 50, 100]"
            @size-change="onLedgerPageSizeChange"
          />
        </div>
      </div>
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
import { QuestionFilled } from '@element-plus/icons-vue'
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
const { colWidth, onHeaderDragend } = useTableColWidths('shared-materials-list', tableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 140,
  fitToContainer: true,
})
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
const ledgerPage = ref(1)
const ledgerPageSize = ref(20)
const productOptions = ref<any[]>([])
const productLoading = ref(false)
const occupancyCache = reactive<Record<string, any[]>>({})
const inTransitCache = reactive<Record<string, any[]>>({})
const detailLoadingKey = ref('')
const form = reactive({
  supplier_product_id: null as number | null,
  size_id: null as number | null,
  qty_delta: 0,
  unit_cost: undefined as number | undefined,
  note: '',
})

const activeCategories = computed(() => categories.value.filter((c) => c.is_active !== false))

function detailKey(row: any, kind: 'occ' | 'tr') {
  return `${kind}:${row.supplier_product_id}:${row.size_id ?? 'n'}`
}

async function loadOccupancy(row: any) {
  const key = detailKey(row, 'occ')
  if (occupancyCache[key]) return
  detailLoadingKey.value = key
  try {
    const res: any = await http.get('/shared-materials/occupancy', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id ?? undefined,
      },
    })
    occupancyCache[key] = res.data?.items || []
  } catch {
    occupancyCache[key] = []
  } finally {
    if (detailLoadingKey.value === key) detailLoadingKey.value = ''
  }
}

async function loadInTransit(row: any) {
  const key = detailKey(row, 'tr')
  if (inTransitCache[key]) return
  detailLoadingKey.value = key
  try {
    const res: any = await http.get('/shared-materials/in-transit', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id ?? undefined,
      },
    })
    inTransitCache[key] = res.data?.items || []
  } catch {
    inTransitCache[key] = []
  } finally {
    if (detailLoadingKey.value === key) detailLoadingKey.value = ''
  }
}

const filteredRows = computed(() => {
  let list = rows.value
  if (categoryFilter.value != null) {
    list = list.filter((r) => Number(r.category_id) === Number(categoryFilter.value))
  }
  const q = keyword.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((r) => {
    const hay = [
      r.supplier_product_code,
      r.supplier_product_name,
      r.category_name,
      r.color_name,
      r.size_value,
      r.pricing_unit_name,
      r.partner_name,
    ]
      .map((x) => String(x || ''))
      .join(' ')
      .toLowerCase()
    return hay.includes(q)
  })
})

const filteredTotal = computed(() => filteredRows.value.length)

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

const pagedLedgers = computed(() => {
  const start = (ledgerPage.value - 1) * ledgerPageSize.value
  return ledgers.value.slice(start, start + ledgerPageSize.value)
})

function onLedgerPageSizeChange() {
  ledgerPage.value = 1
}

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function onHandQty(row: any) {
  if (row.on_hand_qty != null && row.on_hand_qty !== '') return row.on_hand_qty
  return Number(row.pool_qty ?? row.qty ?? 0) + Number(row.occupied_qty || 0)
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
    for (const k of Object.keys(occupancyCache)) delete occupancyCache[k]
    for (const k of Object.keys(inTransitCache)) delete inTransitCache[k]
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
  ledgerPage.value = 1
  ledgers.value = []
  try {
    const res: any = await http.get('/shared-materials/ledgers', {
      params: {
        supplier_product_id: row.supplier_product_id,
        size_id: row.size_id || undefined,
        limit: 500,
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
.col-h {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  line-height: 1.2;
}
.col-h-tip {
  font-size: 14px;
  color: #909399;
  cursor: help;
  vertical-align: middle;
}
.col-h-tip:hover {
  color: var(--el-color-primary);
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
.qty-hover {
  cursor: pointer;
  border-bottom: 1px dashed currentColor;
}
.in {
  color: var(--el-color-success);
  font-weight: 600;
}
.out {
  color: var(--el-color-danger);
  font-weight: 600;
}
.ledger-drawer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 12px;
}
.ledger-drawer-body > .el-table {
  flex: 1;
  min-height: 0;
}
.ledger-pagination {
  flex: none;
  display: flex;
  justify-content: flex-end;
}
</style>

<style>
.ledger-drawer.el-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding-bottom: 16px;
  box-sizing: border-box;
}
.pool-detail-popper.el-popover {
  padding: 10px 12px;
  box-sizing: border-box;
}
.pool-detail-panel {
  width: 100%;
  overflow-x: hidden;
}
.pool-detail-panel .pool-detail-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.pool-detail-popper .pool-detail-table.el-table,
.pool-detail-popper .pool-detail-table .el-table__inner-wrapper,
.pool-detail-popper .pool-detail-table .el-table__header,
.pool-detail-popper .pool-detail-table .el-table__body {
  width: 100% !important;
}
.pool-detail-popper .el-table__body-wrapper,
.pool-detail-popper .el-table__header-wrapper {
  overflow-x: hidden !important;
}
.pool-detail-popper .occ-thumb {
  width: 40px;
  height: 40px;
  display: block;
  margin: 0 auto;
  border-radius: 4px;
}
.pool-detail-popper .occ-thumb .el-image__inner {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
