<template>
  <div>
    <el-tabs v-model="tab" class="admin-card payables-tabs">
      <el-tab-pane label="待结算明细" name="pending">
        <div class="payables-panel">
          <div v-if="balance" class="balance-bar">
            <span>结转余额 <strong>{{ formatMoney(balance.carry_balance) }}</strong></span>
            <span>待结算 <strong>{{ formatMoney(balance.pending_amount) }}</strong></span>
            <span>欠款 <strong>{{ formatMoney(balance.debt) }}</strong></span>
          </div>
          <div class="admin-toolbar">
            <el-select
              v-model="filters.supplier_id"
              clearable
              filterable
              placeholder="全部供应商"
              style="width: 140px"
              @change="loadPending"
            >
              <el-option v-for="c in suppliers" :key="c.id" :label="c.short_name || c.name" :value="c.id" />
            </el-select>
            <el-input
              v-model="filters.po_no"
              clearable
              placeholder="采购单"
              style="width: 140px"
            />
            <el-input
              v-model="filters.delivery_note_no"
              clearable
              placeholder="送货单"
              style="width: 140px"
            />
            <el-input
              v-model="filters.item_code"
              clearable
              placeholder="物料编号"
              style="width: 140px"
            />
            <el-date-picker
              v-model="filters.dateRange"
              class="pending-date"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="收货起"
              end-placeholder="收货止"
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
                  v-permission="'btn.supplier_payments.write'"
                  type="primary"
                  :disabled="!canGenerate"
                  @click="openGenerate"
                >
                  生成对账单
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="voidReturnHint" :disabled="canVoidReturns" placement="top">
              <span class="generate-wrap">
                <el-button
                  v-permission="'btn.supplier_payments.write'"
                  :disabled="!canVoidReturns"
                  @click="voidReturns"
                >
                  作废退货
                </el-button>
              </span>
            </el-tooltip>
          </div>
          <div ref="tableHostRef">
            <el-table
              ref="pendingTableRef"
              :data="rows"
              border
              show-summary
              :summary-method="pendingSummary"
              :span-method="spanMethod"
              :max-height="tableMaxHeight"
              @selection-change="onSelect"
              @header-dragend="onHeaderDragend"
            >
              <el-table-column type="selection" width="42" align="center" :resizable="false" />
              <el-table-column prop="received_at" label="收货时间" :width="colWidth('received_at', 150)" resizable>
                <template #default="{ row }">{{ formatDateTime(row.received_at || row.payable_date) }}</template>
              </el-table-column>
              <el-table-column prop="delivery_note_no" label="送货单号" :width="colWidth('delivery_note_no', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="po_no" label="采购单号" :width="colWidth('po_no', 120)" show-overflow-tooltip resizable />
              <el-table-column prop="supplier_name" label="供应商" :width="colWidth('supplier_name', 110)" show-overflow-tooltip resizable />
              <el-table-column prop="ordered_at" label="下单时间" :width="colWidth('ordered_at', 150)" resizable>
                <template #default="{ row }">{{ row.source_type === 'purchase_return' ? '' : formatDateTime(row.ordered_at) }}</template>
              </el-table-column>
              <el-table-column column-key="image" label="物料图片" :width="colWidth('image', 72)" align="center" resizable>
                <template #default="{ row }">
                  <el-image
                    v-if="row.image_url"
                    :src="row.image_url"
                    fit="cover"
                    style="width: 36px; height: 36px; border-radius: 4px"
                    :preview-src-list="[row.image_url]"
                    preview-teleported
                  />
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column prop="item_code" label="物料编号" :width="colWidth('item_code', 110)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.item_code || '—' }}</template>
              </el-table-column>
              <el-table-column prop="item_name" label="名称" :width="colWidth('item_name', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 80)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.color_name || '—' }}</template>
              </el-table-column>
              <el-table-column prop="size_value" label="尺码" :width="colWidth('size_value', 70)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.size_value || '—' }}</template>
              </el-table-column>
              <el-table-column prop="unit_name" label="计件单位" :width="colWidth('unit_name', 80)" show-overflow-tooltip resizable>
                <template #default="{ row }">{{ row.unit_name || '—' }}</template>
              </el-table-column>
              <el-table-column prop="unit_price" label="单价" :width="colWidth('unit_price', 90)" align="right" resizable>
                <template #default="{ row }">{{ row.unit_price == null ? '—' : formatMoney(row.unit_price) }}</template>
              </el-table-column>
              <el-table-column prop="order_qty" label="数量" :width="colWidth('order_qty', 80)" align="right" resizable>
                <template #default="{ row }">{{ row.source_type === 'purchase_return' ? '' : (row.order_qty == null ? '—' : formatNum(row.order_qty)) }}</template>
              </el-table-column>
              <el-table-column prop="qty" label="到货数量" :width="colWidth('qty', 90)" align="right" resizable>
                <template #default="{ row }">{{ row.qty == null ? '—' : formatNum(row.qty) }}</template>
              </el-table-column>
              <el-table-column prop="amount" label="金额" :width="colWidth('amount', 100)" align="right" resizable>
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="对账单" name="statements">
        <div class="payables-panel">
          <div v-if="balance" class="balance-bar">
            <span>结转余额 <strong>{{ formatMoney(balance.carry_balance) }}</strong></span>
            <span>待结算 <strong>{{ formatMoney(balance.pending_amount) }}</strong></span>
            <span>欠款 <strong>{{ formatMoney(balance.debt) }}</strong></span>
          </div>
          <div class="admin-toolbar">
            <el-select
              v-model="filters.supplier_id"
              clearable
              filterable
              placeholder="全部供应商"
              style="width: 180px"
              @change="loadAll"
            >
              <el-option v-for="c in suppliers" :key="c.id" :label="c.short_name || c.name" :value="c.id" />
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
              <el-table-column prop="partner_name" label="供应商" :width="statementColWidth('partner_name', 120)" show-overflow-tooltip resizable />
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
              <el-table-column prop="settled_amount" label="已付款" :width="statementColWidth('settled_amount', 110)" resizable>
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
                  <el-button v-if="row.can_pay" v-permission="'btn.supplier_payments.write'" link type="primary" @click="openPay(row)">付款</el-button>
                  <el-button link type="primary" @click="openPayments(row)">付款记录</el-button>
                  <el-button v-if="hasHistory(row)" link type="primary" @click="openHistory(row)">历史对账单</el-button>
                  <el-button v-if="row.can_void" v-permission="'btn.supplier_payments.write'" link type="danger" @click="voidStatement(row)">作废</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="historyVisible" :title="`历史对账单 · ${historySupplierName}`" width="1180px" @opened="relayoutHistoryTable">
      <el-table
        ref="historyTableRef"
        :data="historyRows"
        border
        empty-text="没有历史对账单"
        @header-dragend="onHistoryHeaderDragend"
      >
        <el-table-column prop="statement_date" label="对账日期" :width="historyColWidth('statement_date', 110)" resizable />
        <el-table-column prop="statement_no" label="对账单号" :width="historyColWidth('statement_no', 168)" show-overflow-tooltip resizable />
        <el-table-column prop="partner_name" label="供应商" :width="historyColWidth('partner_name', 120)" show-overflow-tooltip resizable />
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
        <el-table-column prop="settled_amount" label="已付款" :width="historyColWidth('settled_amount', 110)" resizable>
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
            <el-button link type="primary" @click="openPayments(row)">付款记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="generateVisible" title="生成对账单" width="460px">
      <el-form label-width="90px">
        <el-form-item label="供应商">{{ generateSupplierName }}</el-form-item>
        <el-form-item label="本期应付">{{ formatMoney(generateAmount) }}</el-form-item>
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
        :span-method="detailSpanMethod"
      >
        <el-table-column prop="received_at" label="收货时间" width="150">
          <template #default="{ row }">{{ row.received_at ? formatDateTime(row.received_at) : '' }}</template>
        </el-table-column>
        <el-table-column prop="delivery_note_no" label="送货单号" width="140" show-overflow-tooltip />
        <el-table-column prop="po_no" label="采购单号" width="130" show-overflow-tooltip />
        <el-table-column prop="supplier_name" label="供应商" width="110" show-overflow-tooltip />
        <el-table-column prop="ordered_at" label="下单时间" width="150">
          <template #default="{ row }">{{ row.ordered_at ? formatDateTime(row.ordered_at) : '' }}</template>
        </el-table-column>
        <el-table-column label="物料图片" width="72" align="center">
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
        <el-table-column prop="item_code" label="物料编号" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.item_code || '' }}</template>
        </el-table-column>
        <el-table-column prop="item_name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="color_name" label="颜色" width="80" show-overflow-tooltip />
        <el-table-column prop="size_value" label="尺码" width="70" show-overflow-tooltip />
        <el-table-column prop="unit_name" label="计件单位" width="80" show-overflow-tooltip />
        <el-table-column prop="unit_price" label="单价" width="90" align="right">
          <template #default="{ row }">{{ row.unit_price == null ? '' : formatMoney(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column prop="order_qty" label="数量" width="80" align="right">
          <template #default="{ row }">{{ row.order_qty == null ? '' : formatNum(row.order_qty) }}</template>
        </el-table-column>
        <el-table-column prop="qty" label="到货数量" width="90" align="right">
          <template #default="{ row }">{{ row.qty == null ? '' : formatNum(row.qty) }}</template>
        </el-table-column>
        <el-table-column prop="amount" label="金额" width="110" align="right">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="payLogVisible" title="付款记录" width="820px">
      <el-table :data="activeStatement?.payments || []" border empty-text="暂无付款">
        <el-table-column prop="payment_date" label="付款日期" width="120" />
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
              v-permission="'btn.supplier_payments.write'"
              link
              type="danger"
              @click="voidPayment(row)"
            >作废</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="payVisible" title="对账单付款" width="460px">
      <el-form label-width="90px">
        <el-form-item label="未付">{{ formatMoney(payForm.unpaid) }}</el-form-item>
        <el-form-item label="付款日期">
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
        <el-button type="primary" @click="submitPay">确认付款</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const router = useRouter()
const tab = ref<'pending' | 'statements'>('pending')
const suppliers = ref<any[]>([])
const rows = ref<any[]>([])
const statements = ref<any[]>([])
const selected = ref<any[]>([])
const balance = ref<any>(null)
const detailVisible = ref(false)
const payVisible = ref(false)
const payLogVisible = ref(false)
const historyVisible = ref(false)
const historySupplierId = ref<number | null>(null)
const historySupplierName = ref('')
const generateVisible = ref(false)
const generating = ref(false)
const activeStatement = ref<any>(null)
const filters = reactive({
  supplier_id: undefined as number | undefined,
  po_no: '',
  delivery_note_no: '',
  item_code: '',
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
const { colWidth, onHeaderDragend } = useTableColWidths('payables-pending', pendingTableRef, {
  flexKey: 'item_name',
  flexDefaultMin: 120,
  fitToContainer: true,
})
const { colWidth: statementColWidth, onHeaderDragend: onStatementHeaderDragend } = useTableColWidths(
  'payables-statements',
  statementTableRef,
  { flexKey: 'partner_name', flexDefaultMin: 100, fitToContainer: true },
)
const {
  colWidth: historyColWidth,
  onHeaderDragend: onHistoryHeaderDragend,
  relayoutTable: relayoutHistoryTable,
} = useTableColWidths('payables-statement-history', historyTableRef, { fitToContainer: true })
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
function statementTotal(row: any) {
  return Number(row.opening_balance || 0) + Number(row.current_amount || 0)
}
function formatDateTime(v: any) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}
function spanMethod({ rowIndex, columnIndex }: { rowIndex: number; columnIndex: number }) {
  if (columnIndex < 1 || columnIndex > 5) return { rowspan: 1, colspan: 1 }
  const current = rows.value[rowIndex]
  const prev = rows.value[rowIndex - 1]
  if (prev && prev.payable_id === current.payable_id) return { rowspan: 0, colspan: 0 }
  let span = 1
  for (let i = rowIndex + 1; i < rows.value.length; i += 1) {
    if (rows.value[i].payable_id !== current.payable_id) break
    span += 1
  }
  return { rowspan: span, colspan: 1 }
}
function onSelect(list: any[]) {
  selected.value = list
}
function statementSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(endingUnpaid(row) || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    if (col.property === 'unpaid_amount') return formatMoney(total)
    return ''
  })
}
function pendingSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(row.amount || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 1) return '合计'
    if (col.property === 'amount') return formatMoney(total)
    return ''
  })
}
const selectedSupplierIds = computed(() => [
  ...new Set(selected.value.map((row) => row.supplier_id).filter((id) => id != null)),
])
const canGenerate = computed(() => selected.value.length > 0 && selectedSupplierIds.value.length === 1)
const canVoidReturns = computed(
  () => selected.value.length > 0 && selected.value.every((row) => row.source_type === 'purchase_return'),
)
const voidReturnHint = computed(() => {
  if (!selected.value.length) return '请先勾选退货明细'
  if (!canVoidReturns.value) return '只能作废退货行'
  return ''
})
const generateHint = computed(() => {
  if (!selected.value.length) return '请先勾选待结算明细'
  if (selectedSupplierIds.value.length > 1) return '一次只能勾选同一供应商'
  return ''
})
const visibleStatements = computed(() => statements.value.filter((row) => row.is_latest))
const historyRows = computed(() =>
  statements.value.filter(
    (row) =>
      row.partner_id === historySupplierId.value
      && !row.is_latest
      && row.status !== 'void',
  ),
)
const generateSupplierName = computed(() => selected.value[0]?.supplier_name || '')
const generateAmount = computed(() =>
  selected.value.reduce((sum, row) => sum + Number(row.amount || 0), 0),
)
const detailRows = computed(() => {
  const statement = activeStatement.value
  if (!statement) return []
  return (statement.lines || []).map((line: any) => {
    const item = (line.supplier_items || [])[0] || {}
    return {
      payable_id: item.payable_id,
      received_at: item.received_at || (line.source_type === 'opening_balance' ? null : line.business_date),
      delivery_note_no: item.delivery_note_no,
      po_no: item.source_document_no || line.document_no,
      supplier_name: statement.partner_name,
      ordered_at: item.ordered_at,
      image_url: item.image_url,
      item_code: item.item_code,
      item_name: item.item_name || line.description,
      color_name: item.color_name,
      size_value: item.size_value,
      unit_name: item.unit_name,
      unit_price: item.unit_price,
      order_qty: item.order_qty,
      qty: item.qty,
      amount: Number(line.debit_amount || 0) - Number(line.credit_amount || 0),
    }
  })
})

function detailSpanMethod({ rowIndex, columnIndex }: { rowIndex: number; columnIndex: number }) {
  if (columnIndex > 4) return { rowspan: 1, colspan: 1 }
  const data = detailRows.value
  const current = data[rowIndex]
  if (!current?.payable_id) return { rowspan: 1, colspan: 1 }
  const prev = data[rowIndex - 1]
  if (prev && prev.payable_id === current.payable_id) return { rowspan: 0, colspan: 0 }
  let span = 1
  for (let i = rowIndex + 1; i < data.length; i += 1) {
    if (data[i].payable_id !== current.payable_id) break
    span += 1
  }
  return { rowspan: span, colspan: 1 }
}
function detailSummary({ columns, data }: { columns: any[]; data: any[] }) {
  const total = data.reduce((sum, row) => sum + Number(row.amount || 0), 0)
  return columns.map((col: any, index: number) => {
    if (index === 0) return '合计'
    if (col.property === 'amount') return formatMoney(total)
    return ''
  })
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', { params: { role: 'material_supplier', page: 1, page_size: 500 } })
  suppliers.value = res.data?.items || res.data || []
}

async function loadPending() {
  const res: any = await http.get('/payables/pending-lines', {
    params: {
      supplier_id: filters.supplier_id || undefined,
      po_no: filters.po_no.trim() || undefined,
      delivery_note_no: filters.delivery_note_no.trim() || undefined,
      item_code: filters.item_code.trim() || undefined,
      date_from: filters.dateRange?.[0] || undefined,
      date_to: filters.dateRange?.[1] || undefined,
    },
  })
  rows.value = res.data?.items || []
  balance.value = filters.supplier_id ? res.data?.balance : null
  selected.value = []
}

let pendingSearchTimer = 0
watch(
  () => [filters.po_no, filters.delivery_note_no, filters.item_code],
  () => {
    window.clearTimeout(pendingSearchTimer)
    pendingSearchTimer = window.setTimeout(() => {
      void loadPending()
    }, 300)
  },
)

async function loadStatements() {
  const res: any = await http.get('/payables/purchase-statements', {
    params: { supplier_id: filters.supplier_id || undefined },
  })
  statements.value = res.data || []
  if (filters.supplier_id) {
    const pending: any = await http.get('/payables/pending-lines', {
      params: { supplier_id: filters.supplier_id },
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
  const supplierId = selectedSupplierIds.value[0]
  const statementNo = generateForm.statement_no.trim()
  if (!supplierId) {
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
    await postStatement(supplierId, selected.value, statementNo, generateForm.statement_date)
    generateVisible.value = false
  } finally {
    generating.value = false
  }
}

async function voidReturns() {
  if (!canVoidReturns.value) return
  await ElMessageBox.confirm('作废后库存加回，这些待结算行会消失', '作废退货')
  const lineIds = selected.value.map((row) => row.line_id)
  await http.post('/payables/purchase-returns/void', { line_ids: lineIds })
  ElMessage.success('已作废退货')
  await loadPending()
}

async function postStatement(supplierId: number, picked: any[], statementNo: string, statementDate: string) {
  const lineIds = picked.filter((row) => row.row_type === 'line').map((row) => row.line_id)
  const remainderIds = picked.filter((row) => row.row_type === 'remainder').map((row) => row.payable_id)
  await http.post('/payables/purchase-statements', {
    supplier_id: supplierId,
    line_ids: lineIds,
    remainder_payable_ids: remainderIds,
    statement_no: statementNo,
    statement_date: statementDate,
  })
  ElMessage.success('已生成对账单')
  tab.value = 'statements'
  await loadAll()
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
    (item) =>
      item.partner_id === row.partner_id
      && item.id !== row.id
      && item.status !== 'void',
  )
}
function openHistory(row: any) {
  historySupplierId.value = row.partner_id
  historySupplierName.value = row.partner_name || ''
  historyVisible.value = true
}
function openPrint(row: any) {
  void router.push(`/admin/account-statements/print/${row.id}`)
}
function openPay(row: any) {
  payForm.statement_id = row.id
  payForm.unpaid = Number(row.unpaid_amount || 0)
  payForm.amount = payForm.unpaid
  payForm.payment_date = new Date().toISOString().slice(0, 10)
  payForm.method = 'bank'
  payForm.voucher_no = ''
  payForm.notes = ''
  payVisible.value = true
}
async function submitPay() {
  await http.post(`/payables/purchase-statements/${payForm.statement_id}/pay`, {
    amount: payForm.amount,
    payment_date: payForm.payment_date,
    method: payForm.method,
    voucher_no: payForm.voucher_no || undefined,
    notes: payForm.notes || undefined,
  })
  ElMessage.success('已付款')
  payVisible.value = false
  await loadAll()
}
async function voidStatement(row: any) {
  await ElMessageBox.confirm('作废后明细回到待结算', '作废对账单')
  await http.post(`/payables/purchase-statements/${row.id}/void`)
  ElMessage.success('已作废')
  await loadAll()
}
async function voidPayment(pay: any) {
  await ElMessageBox.confirm('作废后金额加回这张对账单的未付', '作废付款')
  await http.post(`/supplier-payments/${pay.id}/void`)
  ElMessage.success('已作废付款')
  payLogVisible.value = false
  await loadAll()
}

onMounted(async () => {
  await loadSuppliers()
  await loadAll()
})
</script>

<style scoped>
.payables-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.payables-panel {
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
.payables-panel :deep(.el-table-column--selection .cell) {
  justify-content: center;
}
.payables-panel :deep(.pending-date.el-date-editor) {
  --el-date-editor-width: 210px;
  width: 210px !important;
  max-width: 210px;
  flex: 0 0 210px;
}
.carry-to {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
</style>
