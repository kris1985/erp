<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">客供收货台</h1>
        <p class="page-desc">登记客户来料 · 看欠数 · 催客户（占齐套、不计成本）</p>
      </div>
    </header>
    <div class="admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="filters.order_no"
          clearable
          placeholder="执行单号"
          style="width: 160px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="filters.chase_status"
          clearable
          placeholder="催办状态"
          style="width: 120px"
          @change="search"
        >
          <el-option label="待催" value="open" />
          <el-option label="已催" value="chased" />
          <el-option label="已清" value="cleared" />
        </el-select>
        <el-checkbox v-model="filters.owed_only" @change="search">仅欠数</el-checkbox>
        <div class="spacer" />
        <el-button :loading="loading" @click="search">查询</el-button>
      </div>
      <div ref="tableHostRef">
        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          border
          :max-height="tableMaxHeight"
          @header-dragend="onHeaderDragend"
        >
          <el-table-column
            prop="order_no"
            label="执行单"
            :width="colWidth('order_no', 130)"
            resizable
          >
            <template #default="{ row }">
              {{ row.header_no || row.order_no }}
              <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 4px">急</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 120)"
            resizable
          />
          <el-table-column
            prop="product_code"
            label="货号"
            :width="colWidth('product_code', 90)"
            resizable
          />
          <el-table-column
            prop="supplier_product_code"
            label="物料"
            :width="colWidth('supplier_product_code', 110)"
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="名称"
            :min-width="colWidth('supplier_product_name', 120)"
            resizable
          />
          <el-table-column
            prop="size_value"
            label="码"
            :width="colWidth('size_value', 60)"
            resizable
          >
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column
            prop="required_qty"
            label="需求"
            :width="colWidth('required_qty', 80)"
            align="right"
            resizable
          />
          <el-table-column
            prop="arrived_qty"
            label="已到"
            :width="colWidth('arrived_qty', 80)"
            align="right"
            resizable
          />
          <el-table-column
            prop="owed_qty"
            label="欠数"
            :width="colWidth('owed_qty', 80)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <span :class="{ 'is-owed': Number(row.owed_qty) > 0 }">{{ row.owed_qty }}</span>
            </template>
          </el-table-column>
          <el-table-column
            column-key="chase"
            label="催办"
            :width="colWidth('chase', 80)"
            resizable
          >
            <template #default="{ row }">
              <el-tag size="small" :type="chaseTagType(row.customer_chase_status)">
                {{ chaseLabel(row.customer_chase_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actions"
            label="操作"
            width="220"
            fixed="right"
            :resizable="false"
          >
            <template #default="{ row }">
              <el-button link type="primary" @click="openReceive(row)">登记到货</el-button>
              <el-button
                v-if="row.customer_chase_status !== 'cleared'"
                link
                type="warning"
                @click="doChase(row)"
              >
                催客户
              </el-button>
              <el-button link type="primary" @click="openReceipts(row)">流水</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          layout="total, prev, pager, next"
          :total="total"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </div>

    <el-dialog v-model="receiveVisible" title="登记客供到货" width="420px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="物料">
          {{ receiveRow?.supplier_product_code }} {{ receiveRow?.supplier_product_name }}
        </el-form-item>
        <el-form-item label="欠数">{{ receiveRow?.owed_qty }}</el-form-item>
        <el-form-item label="本次到货" required>
          <el-input-number v-model="receiveQty" :min="0.0001" :precision="4" :step="1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="receiveNote" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReceive">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="receiptsVisible" title="客供到货流水" width="560px" destroy-on-close>
      <el-table :data="receipts" size="small" border stripe>
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="qty" label="数量" width="100" align="right" />
        <el-table-column prop="note" label="备注" min-width="160">
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const tableRef = ref<{ doLayout?: () => void } | null>(null)
const tableHostRef = ref<HTMLElement | null>(null)
const { colWidth, onHeaderDragend } = useTableColWidths('admin-customer-supply', tableRef)
const { tableMaxHeight } = useTableMaxHeight(tableHostRef)

const loading = ref(false)
const saving = ref(false)
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({
  order_no: '',
  chase_status: '' as string,
  owed_only: true,
})

const receiveVisible = ref(false)
const receiveRow = ref<any>(null)
const receiveQty = ref(1)
const receiveNote = ref('')
const receiptsVisible = ref(false)
const receipts = ref<any[]>([])

function chaseLabel(s: string) {
  if (s === 'chased') return '已催'
  if (s === 'cleared') return '已清'
  return '待催'
}
function chaseTagType(s: string) {
  if (s === 'chased') return 'warning'
  if (s === 'cleared') return 'success'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const res: any = await http.get('/customer-supply', {
      params: {
        order_no: filters.order_no || undefined,
        chase_status: filters.chase_status || undefined,
        owed_only: filters.owed_only,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    rows.value = res.data?.items || []
    total.value = res.data?.total || 0
    await nextTick()
    tableRef.value?.doLayout?.()
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function openReceive(row: any) {
  receiveRow.value = row
  const owed = Number(row.owed_qty || 0)
  receiveQty.value = owed > 0 ? owed : 1
  receiveNote.value = ''
  receiveVisible.value = true
}

async function submitReceive() {
  if (!receiveRow.value) return
  if (!receiveQty.value || receiveQty.value <= 0) {
    ElMessage.warning('请输入到货数量')
    return
  }
  saving.value = true
  try {
    await http.post(`/customer-supply/${receiveRow.value.id}/receive`, {
      qty: receiveQty.value,
      note: receiveNote.value || null,
    })
    ElMessage.success('已登记到货')
    receiveVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function doChase(row: any) {
  const { value } = await ElMessageBox.prompt('催办备注（可选）', '催客户', {
    confirmButtonText: '标记已催',
    cancelButtonText: '取消',
    inputPlaceholder: '如：已微信跟客户催大底',
    inputValue: row.customer_chase_note || '',
  }).catch(() => ({ value: null as string | null }))
  if (value === null) return
  await http.post(`/customer-supply/${row.id}/chase`, {
    status: 'chased',
    note: value || null,
  })
  ElMessage.success('已标记催办')
  await load()
}

async function openReceipts(row: any) {
  const res: any = await http.get(`/customer-supply/${row.id}/receipts`)
  receipts.value = res.data?.items || []
  receiptsVisible.value = true
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.spacer {
  flex: 1;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.is-owed {
  color: #c45656;
  font-weight: 600;
}
</style>
