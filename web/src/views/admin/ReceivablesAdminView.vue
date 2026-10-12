<template>
  <div>
    <el-tabs v-model="tab" class="admin-card receivables-tabs">
      <el-tab-pane label="待结算明细" name="pending">
        <div class="receivables-panel">
          <div v-if="balance" class="balance-bar">
            <span>结转余额 <strong>{{ formatMoney(balance.carry_balance) }}</strong></span>
            <span>待结算 <strong>{{ formatMoney(balance.pending_amount) }}</strong></span>
            <span>欠款 <strong>{{ formatMoney(balance.debt) }}</strong></span>
          </div>
          <div class="admin-toolbar">
            <el-select
              v-model="filters.customer_id"
              clearable
              filterable
              placeholder="全部客户"
              style="width: 140px"
              @change="loadPending"
            >
              <el-option v-for="c in customers" :key="c.id" :label="c.short_name || c.name" :value="c.id" />
            </el-select>
            <el-input v-model="filters.sales_order_no" clearable placeholder="订单号" style="width: 140px" />
            <el-input v-model="filters.shipment_no" clearable placeholder="出货/退货/复版单" style="width: 168px" />
            <el-date-picker
              v-model="filters.dateRange"
              class="pending-date"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="日期起"
              end-placeholder="日期止"
              unlink-panels
              clearable
              @change="loadPending"
            />
            <div class="spacer" />
            <span v-if="selected.length" class="selection-total">
              已选 {{ selected.length }} 行
              <strong>¥{{ formatMoney(generateAmount) }}</strong>
            </span>
            <el-tooltip :content="generateHint" :disabled="canGenerate" placement="top">
              <span class="generate-wrap">
                <el-button
                  v-permission="'btn.payments.write'"
                  type="primary"
                  :disabled="!canGenerate"
                  @click="openGenerate"
                >
                  生成对账单
                </el-button>
              </span>
            </el-tooltip>
          </div>
          <div ref="tableHostRef">
            <el-table
              ref="pendingTableRef"
              :data="rows"
              row-key="row_key"
              border
              show-summary
              :summary-method="pendingSummary"
              :max-height="tableMaxHeight"
              @selection-change="onSelect"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column type="selection" width="42" />
              <el-table-column prop="biz_date" label="日期" :width="colWidth('biz_date', 110)" resizable />
              <el-table-column prop="shipment_no" label="出货单号" :width="colWidth('shipment_no', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="return_no" label="退货单号" :width="colWidth('return_no', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="delivery_no" label="复版送货单" :width="colWidth('delivery_no', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="sales_order_no" label="订单号" :width="colWidth('sales_order_no', 140)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.row_type === 'return' ? '' : row.sales_order_no }}</template>
              </el-table-column>
              <el-table-column prop="customer_name" label="客户" :width="colWidth('customer_name', 110)" show-overflow-tooltip resizable />
              <el-table-column prop="ordered_at" label="下单日期" :width="colWidth('ordered_at', 110)" resizable />
              <el-table-column prop="factory_model" label="工厂型号" :width="colWidth('factory_model', 120)" show-overflow-tooltip resizable />
              <el-table-column column-key="image_url" label="图片" :width="colWidth('image_url', 72)" align="center" resizable>
                <template #default="{ row }">
                  <el-image
                    v-if="row.image_url"
                    :src="row.image_url"
                    fit="cover"
                    style="width: 36px; height: 36px; border-radius: 4px"
                    :preview-src-list="[row.image_url]"
                    preview-teleported
                  />
                </template>
              </el-table-column>
              <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 80)" show-overflow-tooltip resizable />
              <el-table-column prop="brand_name" label="品牌" :width="colWidth('brand_name', 100)" show-overflow-tooltip resizable />
              <el-table-column prop="customer_sku" label="客户型号" :width="colWidth('customer_sku', 120)" show-overflow-tooltip resizable />
              <el-table-column prop="qty" label="数量" :width="colWidth('qty', 80)" align="right" resizable>
                <template #default="{ row }">
                  <span :class="{ 'is-neg': Number(row.qty) < 0 }">{{ row.qty == null ? '' : formatNum(row.qty) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="unit_price" label="单价" :width="colWidth('unit_price', 90)" align="right" resizable>
                <template #default="{ row }">{{ row.unit_price == null ? '' : formatMoney(row.unit_price) }}</template>
              </el-table-column>
              <el-table-column prop="amount" label="总价" :width="colWidth('amount', 110)" align="right" resizable>
                <template #default="{ row }">
                  <span :class="{ 'is-neg': Number(row.amount) < 0 }">{{ formatMoney(row.amount) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="对账单" name="statements">
        <div class="receivables-panel">
          <div v-if="balance" class="balance-bar">
            <span>结转余额 <strong>{{ formatMoney(balance.carry_balance) }}</strong></span>
            <span>待结算 <strong>{{ formatMoney(balance.pending_amount) }}</strong></span>
            <span>欠款 <strong>{{ formatMoney(balance.debt) }}</strong></span>
          </div>
          <div class="admin-toolbar">
            <el-select
              v-model="filters.customer_id"
              clearable
              filterable
              placeholder="全部客户"
              style="width: 180px"
              @change="loadAll"
            >
              <el-option v-for="c in customers" :key="c.id" :label="c.short_name || c.name" :value="c.id" />
            </el-select>
          </div>
          <div ref="statementHostRef">
            <el-table
              ref="statementTableRef"
              :data="visibleStatements"
              border
              show-summary
              :summary-method="statementSummary"
              :max-height="statementMaxHeight"
              @header-dragend="onStatementHeaderDragend"
            >
              <el-table-column prop="statement_date" label="对账日期" :width="statementColWidth('statement_date', 110)" resizable />
              <el-table-column prop="statement_no" label="对账单号" :width="statementColWidth('statement_no', 160)" show-overflow-tooltip resizable />
              <el-table-column prop="partner_name" label="客户" :width="statementColWidth('partner_name', 120)" show-overflow-tooltip resizable />
              <el-table-column label="对账金额" align="center">
                <el-table-column prop="opening_balance" label="上期余款" :width="statementColWidth('opening_balance', 110)" resizable>
                  <template #default="{ row }">{{ formatMoney(row.opening_balance) }}</template>
                </el-table-column>
                <el-table-column prop="current_amount" label="本期账单" :width="statementColWidth('current_amount', 110)" resizable>
                  <template #default="{ row }">{{ formatMoney(row.current_amount) }}</template>
                </el-table-column>
                <el-table-column column-key="statement_total" label="共计" :width="statementColWidth('statement_total', 110)" resizable>
                  <template #default="{ row }">{{ formatMoney(statementTotal(row)) }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column prop="settled_amount" label="已收款" :width="statementColWidth('settled_amount', 110)" resizable>
                <template #default="{ row }">{{ formatMoney(row.settled_amount) }}</template>
              </el-table-column>
              <el-table-column prop="unpaid_amount" label="余款" :width="statementColWidth('unpaid_amount', 180)" resizable>
                <template #default="{ row }">
                  <div>{{ formatMoney(endingUnpaid(row)) }}</div>
                  <div v-if="row.carried_to_no && actualUnpaid(row) === 0" class="carry-to">累计到 {{ row.carried_to_no }}</div>
                </template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="380" fixed="right" :resizable="false">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openStatement(row)">明细</el-button>
                  <el-button link type="primary" @click="openPrint(row)">导出</el-button>
                  <el-button v-if="row.can_receive" v-permission="'btn.payments.write'" link type="primary" @click="openReceive(row)">收款</el-button>
                  <el-button link type="primary" @click="openPayments(row)">收款记录</el-button>
                  <el-button v-if="hasHistory(row)" link type="primary" @click="openHistory(row)">历史对账单</el-button>
                  <el-button v-if="row.can_void" v-permission="'btn.payments.write'" link type="danger" @click="voidStatement(row)">作废</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="historyVisible" :title="`历史对账单 · ${historyCustomerName}`" width="1180px" @opened="relayoutHistoryTable">
      <el-table
        ref="historyTableRef"
        :data="historyRows"
        border
        empty-text="没有历史对账单"
        @header-dragend="onHistoryHeaderDragend"
      >
        <el-table-column prop="statement_date" label="对账日期" :width="historyColWidth('statement_date', 110)" resizable />
        <el-table-column prop="statement_no" label="对账单号" :width="historyColWidth('statement_no', 168)" show-overflow-tooltip resizable />
        <el-table-column prop="partner_name" label="客户" :width="historyColWidth('partner_name', 120)" show-overflow-tooltip resizable />
        <el-table-column label="对账金额" align="center">
          <el-table-column prop="opening_balance" label="上期余款" :width="historyColWidth('opening_balance', 110)" resizable>
            <template #default="{ row }">{{ formatMoney(row.opening_balance) }}</template>
          </el-table-column>
          <el-table-column prop="current_amount" label="本期账单" :width="historyColWidth('current_amount', 110)" resizable>
            <template #default="{ row }">{{ formatMoney(row.current_amount) }}</template>
          </el-table-column>
          <el-table-column column-key="statement_total" label="共计" :width="historyColWidth('statement_total', 110)" resizable>
            <template #default="{ row }">{{ formatMoney(statementTotal(row)) }}</template>
          </el-table-column>
        </el-table-column>
        <el-table-column prop="settled_amount" label="已收款" :width="historyColWidth('settled_amount', 110)" resizable>
          <template #default="{ row }">{{ formatMoney(row.settled_amount) }}</template>
        </el-table-column>
        <el-table-column prop="unpaid_amount" label="余款" :width="historyColWidth('unpaid_amount', 180)" resizable>
          <template #default="{ row }">
            <div>{{ formatMoney(actualUnpaid(row)) }}</div>
            <div v-if="carryLabel(row)" class="carry-to">{{ carryLabel(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="220" fixed="right" :resizable="false">
          <template #default="{ row }">
            <el-button link type="primary" @click="openStatement(row)">明细</el-button>
            <el-button link type="primary" @click="openPrint(row)">导出</el-button>
            <el-button link type="primary" @click="openPayments(row)">收款记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="generateVisible" title="生成对账单" width="460px">
      <el-form label-width="90px">
        <el-form-item label="客户">{{ generateCustomerName }}</el-form-item>
        <el-form-item label="本期应收">{{ formatMoney(generateAmount) }}</el-form-item>
        <el-form-item label="对账单号" required>
          <el-input v-model="generateForm.statement_no" maxlength="50" placeholder="手动填写" />
        </el-form-item>
        <el-form-item label="对账日期" required>
          <el-date-picker v-model="generateForm.statement_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generateVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="submitGenerate">确认生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="对账单明细" width="92%" top="6vh">
      <el-table
        v-if="activeStatement"
        :data="detailRows"
        border
        max-height="70vh"
        show-summary
        :summary-method="detailSummary"
      >
        <el-table-column prop="biz_date" label="日期" width="110">
          <template #default="{ row }">{{ row.biz_date || '' }}</template>
        </el-table-column>
        <el-table-column prop="shipment_no" label="出货单号" width="140" show-overflow-tooltip />
        <el-table-column prop="return_no" label="退货单号" width="140" show-overflow-tooltip />
        <el-table-column prop="delivery_no" label="复版单号" width="140" show-overflow-tooltip />
        <el-table-column prop="sales_order_no" label="订单号" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.return_no ? '' : row.sales_order_no }}</template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" width="110" show-overflow-tooltip />
        <el-table-column prop="ordered_at" label="下单日期" width="110" />
        <el-table-column prop="factory_model" label="工厂型号" width="120" show-overflow-tooltip />
        <el-table-column label="图片" width="72" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              fit="cover"
              style="width: 36px; height: 36px; border-radius: 4px"
              :preview-src-list="[row.image_url]"
              preview-teleported
            />
          </template>
        </el-table-column>
        <el-table-column prop="color_name" label="颜色" width="80" show-overflow-tooltip />
        <el-table-column prop="brand_name" label="品牌" width="100" show-overflow-tooltip />
        <el-table-column prop="customer_sku" label="客户型号" width="120" show-overflow-tooltip />
        <el-table-column prop="qty" label="数量" width="80" align="right">
          <template #default="{ row }">
            <span :class="{ 'is-neg': Number(row.qty) < 0 }">{{ row.qty == null ? '' : formatNum(row.qty) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit_price" label="单价" width="90" align="right">
          <template #default="{ row }">{{ row.unit_price == null ? '' : formatMoney(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column prop="amount" label="总价" width="110" align="right">
          <template #default="{ row }">
            <span :class="{ 'is-neg': Number(row.amount) < 0 }">{{ formatMoney(row.amount) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="payLogVisible" title="收款记录" width="820px">
      <el-table :data="activeStatement?.payments || []" border empty-text="暂无收款">
        <el-table-column prop="payment_date" label="收款日期" width="120" />
        <el-table-column prop="amount" label="金额" width="120" align="right">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="方式" width="90">
          <template #default="{ row }">{{ payMethodLabel(row.method) }}</template>
        </el-table-column>
        <el-table-column prop="voucher_no" label="凭证号" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.voucher_no || '—' }}</template>
        </el-table-column>
        <el-table-column prop="notes" label="备注" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.notes || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              v-if="activeStatement?.is_latest"
              v-permission="'btn.payments.write'"
              link
              type="danger"
              @click="voidPayment(row)"
            >作废</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="payVisible" title="对账单收款" width="460px">
      <el-form label-width="90px">
        <el-form-item label="未收">{{ formatMoney(payForm.unpaid) }}</el-form-item>
        <el-form-item label="收款日期">
          <el-date-picker v-model="payForm.payment_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="payForm.amount" :min="0.01" :max="payForm.unpaid" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="方式">
          <el-select v-model="payForm.method" style="width: 100%">
            <el-option label="银行" value="bank" />
            <el-option label="现金" value="cash" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="凭证号"><el-input v-model="payForm.voucher_no" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="payForm.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="payVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReceive">确认收款</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const router = useRouter()
const tab = ref<'pending' | 'statements'>('pending')
const customers = ref<any[]>([])
const rows = ref<any[]>([])
const statements = ref<any[]>([])
const selected = ref<any[]>([])
const balance = ref<any>(null)
const detailVisible = ref(false)
const payVisible = ref(false)
const payLogVisible = ref(false)
const historyVisible = ref(false)
const historyCustomerId = ref<number | null>(null)
const historyCustomerName = ref('')
const generateVisible = ref(false)
const generating = ref(false)
const activeStatement = ref<any>(null)
const filters = reactive({
  customer_id: undefined as number | undefined,
  sales_order_no: '',
  shipment_no: '',
  dateRange: [] as string[],
})
const generateForm = reactive({
  statement_no: '',
  statement_date: '',
})
const payForm = reactive({
  statement_id: 0,
  unpaid: 0,
  amount: 0,
  payment_date: '',
  method: 'bank',
  voucher_no: '',
  notes: '',
})

const pendingTableRef = ref()
const statementTableRef = ref()
const historyTableRef = ref()
const { colWidth, onHeaderDragend } = useTableColWidths('receivables-pending', pendingTableRef, {
  flexKey: 'factory_model',
  flexDefaultMin: 100,
  fitToContainer: true,
})
const { colWidth: statementColWidth, onHeaderDragend: onStatementHeaderDragend } = useTableColWidths(
  'receivables-statements',
  statementTableRef,
  { flexKey: 'partner_name', flexDefaultMin: 100, fitToContainer: true },
)
const {
  colWidth: historyColWidth,
  onHeaderDragend: onHistoryHeaderDragend,
  relayoutTable: relayoutHistoryTable,
} = useTableColWidths('receivables-statement-history', historyTableRef, { fitToContainer: true })
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()
const { tableHostRef: statementHostRef, tableMaxHeight: statementMaxHeight } = useTableMaxHeight()

function formatMoney(v: any) {
  const n = Number(v || 0)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function formatNum(v: any) {
  const n = Number(v || 0)
  return Number.isInteger(n) ? String(n) : String(n)
}
function endingUnpaid(row: any) {
  return row.unpaid_amount
}
function actualUnpaid(row: any) {
  const amount = Number(row.opening_balance || 0) + Number(row.current_amount || 0) - Number(row.settled_amount || 0)
  return Math.round(amount * 100) / 100
}
function statementTotal(row: any) {
  return Number(row.opening_balance || 0) + Number(row.current_amount || 0)
}
function carryTarget(row: any) {
  const group = statements.value
    .filter((item) => item.partner_id === row.partner_id)
    .sort((a, b) => a.id - b.id)
  const index = group.findIndex((item) => item.id === row.id)
  if (index < 0 || index >= group.length - 1) return ''
  return group[index + 1].statement_no
}
function carryLabel(row: any) {
  const target = carryTarget(row)
  if (!target) return ''
  return actualUnpaid(row) === 0 ? `累计到 ${target}` : `已转入 ${target}`
}
let syncingSelection = false
function onSelect(list: any[]) {
  if (syncingSelection) return
  const prevKeys = new Set(selected.value.map((row) => row.row_key))
  const nextKeys = new Set(list.map((row) => row.row_key))
  const added = list.filter((row) => !prevKeys.has(row.row_key))
  const removed = selected.value.filter((row) => !nextKeys.has(row.row_key))
  const touched = new Set<number>()
  for (const row of [...added, ...removed]) {
    if (row.row_type === 'sample_remake' && row.sample_remake_id) touched.add(row.sample_remake_id)
  }
  if (!touched.size) {
    selected.value = list
    return
  }
  const keep = new Set(nextKeys)
  for (const remakeId of touched) {
    const selectAll = added.some((row) => row.sample_remake_id === remakeId)
      && !removed.some((row) => row.sample_remake_id === remakeId)
    for (const sibling of rows.value.filter((row) => row.sample_remake_id === remakeId)) {
      if (selectAll) keep.add(sibling.row_key)
      else keep.delete(sibling.row_key)
    }
  }
  const next = rows.value.filter((row) => keep.has(row.row_key))
  selected.value = next
  const unchanged = next.length === list.length && next.every((row) => nextKeys.has(row.row_key))
  if (unchanged) return
  syncingSelection = true
  const table = pendingTableRef.value
  table?.clearSelection?.()
  for (const row of next) table?.toggleRowSelection?.(row, true)
  void nextTick(() => {
    syncingSelection = false
  })
}
function pendingSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(row.amount || 0), 0)
  const qty = data.reduce((sum, row) => sum + Number(row.qty || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 1) return '合计'
    if (col.property === 'qty') return formatNum(qty)
    if (col.property === 'amount') return formatMoney(total)
    return ''
  })
}
const selectedCustomerIds = computed(() => [
  ...new Set(selected.value.map((row) => row.customer_id).filter((id) => id != null)),
])
const canGenerate = computed(() => selected.value.length > 0 && selectedCustomerIds.value.length === 1)
const generateHint = computed(() => {
  if (!selected.value.length) return '请先勾选待结算明细'
  if (selectedCustomerIds.value.length > 1) return '一次只能勾选同一客户'
  return ''
})
const visibleStatements = computed(() => statements.value.filter((row) => row.is_latest))
const historyRows = computed(() =>
  statements.value.filter(
    (row) => row.partner_id === historyCustomerId.value && !row.is_latest && row.status !== 'void',
  ),
)
const generateCustomerName = computed(() => selected.value[0]?.customer_name || '')
const generateAmount = computed(() => selected.value.reduce((sum, row) => sum + Number(row.amount || 0), 0))
const detailRows = computed(() => {
  const statement = activeStatement.value
  if (!statement) return []
  return (statement.lines || []).map((line: any) => {
    const item = (line.customer_items || [])[0] || {}
    const amount = Number(line.debit_amount || 0) - Number(line.credit_amount || 0)
    const isOpening = line.source_type === 'opening_balance'
    const isReturn = line.source_type === 'after_sales_return'
    const isRemake = line.source_type === 'sample_remake'
    return {
      biz_date: item.biz_date || item.ship_date || (isOpening ? null : line.business_date),
      shipment_no: isReturn || isRemake ? '' : (item.shipment_no || (isOpening ? '' : line.document_no)),
      return_no: item.return_no || (isReturn ? line.document_no : ''),
      delivery_no: item.delivery_no || (isRemake ? line.document_no : ''),
      sales_order_no: isOpening ? '上期余额' : item.sales_order_no,
      customer_name: statement.partner_name,
      ordered_at: item.ordered_at || '',
      factory_model: item.factory_model || item.product_code,
      image_url: item.image_url,
      color_name: item.color_name,
      brand_name: item.brand_name,
      customer_sku: item.customer_sku,
      qty: item.qty,
      unit_price: item.unit_price,
      amount,
    }
  })
})
function detailSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(row.amount || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    if (col.property === 'amount') return formatMoney(total)
    return ''
  })
}
function statementSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(endingUnpaid(row) || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    if (col.property === 'unpaid_amount') return formatMoney(total)
    return ''
  })
}

async function loadCustomers() {
  const res: any = await http.get('/partners', { params: { role: 'customer_brand', page: 1, page_size: 500 } })
  customers.value = res.data?.items || res.data || []
}

async function loadPending() {
  const res: any = await http.get('/receivables/pending-lines', {
    params: {
      customer_id: filters.customer_id || undefined,
      sales_order_no: filters.sales_order_no.trim() || undefined,
      shipment_no: filters.shipment_no.trim() || undefined,
      date_from: filters.dateRange?.[0] || undefined,
      date_to: filters.dateRange?.[1] || undefined,
    },
  })
  rows.value = res.data?.items || []
  balance.value = filters.customer_id ? res.data?.balance : null
  selected.value = []
}

let pendingSearchTimer = 0
watch(
  () => [filters.sales_order_no, filters.shipment_no],
  () => {
    window.clearTimeout(pendingSearchTimer)
    pendingSearchTimer = window.setTimeout(() => {
      void loadPending()
    }, 300)
  },
)

async function loadStatements() {
  const res: any = await http.get('/receivables/sales-statements', {
    params: { customer_id: filters.customer_id || undefined },
  })
  statements.value = res.data || []
  if (filters.customer_id) {
    const pending: any = await http.get('/receivables/pending-lines', {
      params: { customer_id: filters.customer_id },
    })
    balance.value = pending.data?.balance || null
  } else {
    balance.value = null
  }
}

function loadAll() {
  void loadPending()
  void loadStatements()
}

function payMethodLabel(method: string) {
  if (method === 'bank') return '银行'
  if (method === 'cash') return '现金'
  return '其他'
}
function openGenerate() {
  if (!canGenerate.value) return
  generateForm.statement_no = ''
  generateForm.statement_date = new Date().toISOString().slice(0, 10)
  generateVisible.value = true
}
async function submitGenerate() {
  const customerId = selectedCustomerIds.value[0]
  const statementNo = generateForm.statement_no.trim()
  if (!customerId) {
    ElMessage.warning(generateHint.value || '请先勾选待结算明细')
    return
  }
  if (!statementNo) {
    ElMessage.warning('请填写对账单号')
    return
  }
  if (!generateForm.statement_date) {
    ElMessage.warning('请选择对账日期')
    return
  }
  generating.value = true
  try {
    await http.post('/receivables/sales-statements', {
      customer_id: customerId,
      receivable_ids: selected.value
        .filter((row) => row.row_type !== 'return' && row.row_type !== 'sample_remake' && row.receivable_id)
        .map((row) => row.receivable_id),
      return_ids: selected.value.filter((row) => row.row_type === 'return' && row.return_id).map((row) => row.return_id),
      sample_remake_ids: [...new Set(
        selected.value
          .filter((row) => row.row_type === 'sample_remake' && row.sample_remake_id)
          .map((row) => row.sample_remake_id),
      )],
      statement_no: statementNo,
      statement_date: generateForm.statement_date,
    })
    ElMessage.success('已生成对账单')
    generateVisible.value = false
    tab.value = 'statements'
    await loadAll()
  } finally {
    generating.value = false
  }
}

function openStatement(row: any) {
  activeStatement.value = row
  detailVisible.value = true
}
function openPayments(row: any) {
  activeStatement.value = row
  payLogVisible.value = true
}
function hasHistory(row: any) {
  return statements.value.some(
    (item) => item.partner_id === row.partner_id && item.id !== row.id && item.status !== 'void',
  )
}
function openHistory(row: any) {
  historyCustomerId.value = row.partner_id
  historyCustomerName.value = row.partner_name || ''
  historyVisible.value = true
}
function openPrint(row: any) {
  void router.push(`/admin/account-statements/print/${row.id}`)
}
function openReceive(row: any) {
  payForm.statement_id = row.id
  payForm.unpaid = Number(row.unpaid_amount || 0)
  payForm.amount = payForm.unpaid
  payForm.payment_date = new Date().toISOString().slice(0, 10)
  payForm.method = 'bank'
  payForm.voucher_no = ''
  payForm.notes = ''
  payVisible.value = true
}
async function submitReceive() {
  await http.post(`/receivables/sales-statements/${payForm.statement_id}/receive`, {
    amount: payForm.amount,
    payment_date: payForm.payment_date,
    method: payForm.method,
    voucher_no: payForm.voucher_no || undefined,
    notes: payForm.notes || undefined,
  })
  ElMessage.success('已收款')
  payVisible.value = false
  await loadAll()
}
async function voidStatement(row: any) {
  await ElMessageBox.confirm('作废后明细回到待结算', '作废对账单')
  await http.post(`/receivables/sales-statements/${row.id}/void`)
  ElMessage.success('已作废')
  await loadAll()
}
async function voidPayment(pay: any) {
  await ElMessageBox.confirm('作废后金额加回这张对账单的未收', '作废收款')
  await http.post(`/payments/${pay.id}/void`)
  ElMessage.success('已作废收款')
  payLogVisible.value = false
  await loadAll()
}

onMounted(async () => {
  await loadCustomers()
  await loadAll()
})
</script>

<style scoped>
.receivables-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.receivables-panel {
  padding: 12px 0 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.balance-bar {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
}
.generate-wrap {
  display: inline-block;
}
.selection-total {
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.selection-total strong {
  margin-left: 8px;
  color: var(--el-color-primary);
  font-size: 16px;
}
.receivables-panel :deep(.el-table-column--selection .cell) {
  justify-content: center;
}
.receivables-panel :deep(.pending-date.el-date-editor) {
  --el-date-editor-width: 210px;
  width: 210px !important;
  max-width: 210px;
  flex: 0 0 210px;
}
.carry-to {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.is-neg {
  color: var(--el-color-danger);
}
</style>
