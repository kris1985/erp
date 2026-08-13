<template>
  <div>
    <header v-if="!embedded" class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">采购单</h1>
        <p class="page-desc">下单 · 发货 · 到货登记</p>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-select v-model="status" clearable placeholder="状态" style="width: 140px" @change="search">
          <el-option label="待下单" value="draft" />
          <el-option label="已下单" value="ordered" />
          <el-option label="部分到货" value="partial_received" />
          <el-option label="已到齐" value="received" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-select v-model="alertFilter" clearable placeholder="交期告警" style="width: 140px" @change="search">
          <el-option label="逾期未到" value="overdue" />
          <el-option label="即将到期" value="due_soon" />
        </el-select>
        <el-tag v-if="overdueCount" type="danger" effect="plain">逾期 {{ overdueCount }}</el-tag>
        <el-tag v-if="dueSoonCount" type="warning" effect="plain">即将到期 {{ dueSoonCount }}</el-tag>
        <el-button @click="load">刷新</el-button>
      </div>
      <div ref="tableHostRef">
      <el-table
        ref="tableRef"
        class="po-grouped-table"
        :data="displayRows"
        border
        style="width: 100%"
        row-key="_key"
        :max-height="tableMaxHeight"
        :span-method="groupSpanMethod"
        :row-class-name="groupRowClassName"
        @header-dragend="onHeaderDragend"
      >
        <el-table-column prop="po_no" label="采购单号" :width="colWidth('po_no', 130)" resizable>
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">{{ row.po_no }}</el-button>
          </template>
        </el-table-column>
        <el-table-column
          prop="partner_name"
          label="供应商"
          :width="colWidth('partner_name', 120)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column column-key="ordered_at" label="下单时间" :width="colWidth('ordered_at', 136)" resizable>
          <template #default="{ row }">{{ formatDateTime(row.ordered_at) }}</template>
        </el-table-column>
        <el-table-column
          column-key="image"
          label="物料图片"
          :width="colWidth('image', 72)"
          align="center"
          class-name="mat-image-col"
          header-class-name="mat-image-col"
          resizable
        >
          <template #default="{ row }">
            <el-image
              v-if="row._line?.image_url"
              :src="row._line.image_url"
              :preview-src-list="[row._line.image_url]"
              fit="contain"
              class="product-thumb"
              preview-teleported
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="supplier_product_code"
          label="物料编号"
          :width="colWidth('supplier_product_code', 110)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row._line?.supplier_product_code || '—' }}</template>
        </el-table-column>
        <el-table-column
          prop="supplier_product_name"
          label="名称"
          :width="colWidth('supplier_product_name', 140)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row._line?.supplier_product_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="color_name" label="颜色" :width="colWidth('color_name', 72)" align="center" resizable>
          <template #default="{ row }">{{ row._line?.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="unit" label="计价单位" :width="colWidth('unit', 80)" align="center" resizable>
          <template #default="{ row }">{{ row._line?.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="unit_price" label="单价" :width="colWidth('unit_price', 72)" align="right" resizable>
          <template #default="{ row }">{{ row._line ? formatMoney(row._line.unit_price) : '—' }}</template>
        </el-table-column>
        <el-table-column column-key="qty" label="数量" :width="colWidth('qty', 72)" align="right" resizable>
          <template #default="{ row }">{{ row._line ? formatNum(row._line.qty) : '—' }}</template>
        </el-table-column>
        <el-table-column column-key="arrived" label="已到" :width="colWidth('arrived', 64)" align="right" resizable>
          <template #default="{ row }">{{ row._line ? formatNum(row._line.received_qty) : '—' }}</template>
        </el-table-column>
        <el-table-column column-key="amount" label="金额" :width="colWidth('amount', 88)" align="right" resizable>
          <template #default="{ row }">
            <template v-if="row._line">¥{{ formatMoney(row._line.amount) }}</template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column
          column-key="summary_total_amount"
          label="总金额"
          :width="colWidth('summary_total_amount', 100)"
          align="right"
          resizable
        >
          <template #default="{ row }">
            <strong>¥{{ formatMoney(row.summary_total_amount) }}</strong>
          </template>
        </el-table-column>
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 88)" resizable>
          <template #default="{ row }">{{ poStatusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="220" :resizable="false">
          <template #default="{ row }">
            <el-button link @click="exportDoc(row)">导出</el-button>
            <el-button link type="primary" plain @click="printPo(row)">打印</el-button>
            <el-button v-if="row.status === 'draft'" link type="primary" @click="openSubmit(row)">下单</el-button>
            <el-button
              v-if="['ordered', 'shipped', 'partial_received'].includes(row.status)"
              link
              @click="openReceive(row)"
            >到货</el-button>
            <el-button v-if="row.status === 'draft'" link type="danger" @click="cancel(row)">取消</el-button>
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
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-drawer v-model="detailVisible" :title="detail?.po_no" size="720px">
      <template v-if="detail">
        <div class="detail-actions">
          <el-button @click="exportDoc()">导出</el-button>
          <el-button type="primary" plain @click="printPo()">打印</el-button>
          <el-button
            v-if="detail.status === 'draft'"
            type="primary"
            @click="openSubmit(detail)"
          >下单</el-button>
        </div>
        <el-descriptions :column="1" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="买方">{{ detail.buyer_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ detail.partner_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ poStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="下单时间">{{ formatDateTime(detail.ordered_at) }}</el-descriptions-item>
          <el-descriptions-item label="交期告警">
            <el-tag v-if="detail.delivery_alert === 'overdue'" type="danger" size="small">
              {{ detail.delivery_alert_label }}
            </el-tag>
            <el-tag v-else-if="detail.delivery_alert === 'due_soon'" type="warning" size="small">
              {{ detail.delivery_alert_label }}
            </el-tag>
            <span v-else class="muted">正常</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-form label-width="100px" style="margin-bottom: 16px">
          <el-form-item label="协商交货日期">
            <el-date-picker
              v-model="detail.expected_date"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="账期(天)">
            <el-input-number
              :model-value="detail.payment_term_days ?? undefined"
              :min="0"
              :max="365"
              controls-position="right"
              style="width: 160px"
              @update:model-value="(v: number | undefined) => (detail.payment_term_days = v ?? null)"
            />
            <span class="muted" style="margin-left: 8px">
              空=用供应商默认（{{ detail.supplier_payment_term_days ?? 0 }}天）· 当前生效
              {{ effectivePoTerm(detail) }}天
            </span>
            <el-button link type="primary" style="margin-left: 8px" @click="detail.payment_term_days = null">
              用默认
            </el-button>
          </el-form-item>
          <el-form-item label="物流公司">
            <el-input v-model="detail.logistics_company" />
          </el-form-item>
          <el-form-item label="运单号">
            <el-input v-model="detail.tracking_no" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="detail.notes" type="textarea" />
          </el-form-item>
          <el-button type="primary" @click="saveMeta">保存</el-button>
        </el-form>

        <div class="section-head">
          <strong>采购汇总</strong>
          <span class="muted">
            按物料合计 · 金额 ¥{{ formatMoney(detail.summary_total_amount) }}
          </span>
        </div>
        <el-table :data="detail.summary_lines || []" border size="small" style="width: 100%; margin-bottom: 16px" @header-dragend="onHeaderDragend1">
          <el-table-column column-key="image" label="图片" :width="colWidth1('image', 70)" align="center" resizable>
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
          <el-table-column prop="supplier_product_code" label="物料编码" :width="colWidth1('supplier_product_code', 110)" resizable />
          <el-table-column prop="supplier_product_name" label="名称" :width="colWidth1('supplier_product_name', 120)" resizable>
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit" label="单位" :width="colWidth1('unit', 70)" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
          <el-table-column column-key="arrived" label="已到" :width="colWidth1('arrived', 70)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="单价" :width="colWidth1('unit_price', 120)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number
                v-if="detail.status === 'draft'"
                :model-value="Number(row.unit_price || 0)"
                :min="0"
                :precision="2"
                :step="0.01"
                :controls="false"
                size="small"
                style="width: 100px"
                @change="(v: number) => onSummaryPrice(row, v)"
              />
              <span v-else>{{ formatMoney(row.unit_price) }}</span>
              <div v-if="row.price_mixed" class="text-warn" style="font-size: 12px">分订单单价不一致</div>
            </template>
          </el-table-column>
          <el-table-column column-key="amount" label="金额" :width="colWidth1('amount', 90)" align="right" resizable>
            <template #default="{ row }">¥{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column column-key="last_price" label="最近成交价" :width="colWidth1('last_price', 90)" align="right" resizable>
            <template #default="{ row }">
              {{ row.last_purchase_price != null ? formatMoney(row.last_purchase_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>

        <div class="section-head">
          <strong>分订单明细</strong>
          <span class="muted">到货回写用 · 不合并</span>
        </div>
        <el-table :data="detail.lines" border size="small" style="width: 100%" @header-dragend="onHeaderDragend2">
          <el-table-column prop="supplier_product_code" label="物料" :width="colWidth2('supplier_product_code', 100)" resizable />
          <el-table-column column-key="size_value" label="尺码" :width="colWidth2('size_value', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column prop="order_no" label="执行单" :width="colWidth2('order_no', 90)" resizable />
          <el-table-column column-key="unit" label="单位" :width="colWidth2('unit', 70)" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth2('qty', 70)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
          <el-table-column column-key="arrived" label="已到" :width="colWidth2('arrived', 70)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="单价" :width="colWidth2('unit_price', 80)" align="right" resizable>
            <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column column-key="last_price" label="最近成交价" :width="colWidth2('last_price', 100)" align="right" resizable>
            <template #default="{ row }">
              {{ row.last_purchase_price != null ? formatMoney(row.last_purchase_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>

    <el-dialog
      v-model="submitVisible"
      :title="submitDraft ? `确认下单 · ${submitDraft.po_no}` : '确认下单'"
      width="820px"
      destroy-on-close
      class="po-submit-dialog"
    >
      <template v-if="submitDraft">
        <div class="submit-meta">
          <div class="submit-meta-main">
            <div class="submit-meta-label">供应商</div>
            <div class="submit-meta-partner">{{ submitDraft.partner_name || '—' }}</div>
            <p v-if="submitDraft.notes" class="submit-meta-notes">{{ submitDraft.notes }}</p>
          </div>
          <div class="submit-meta-date">
            <div class="submit-meta-label">协商交货日期 <span class="req">*</span></div>
            <el-date-picker
              v-model="submitDraft.expected_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="必填"
              size="default"
              style="width: 168px"
            />
          </div>
        </div>

        <div class="section-head">
          <strong>采购明细（可改价）</strong>
          <span class="muted">改价后按物料同步到各分订单行</span>
        </div>
        <el-table
          ref="submitTableRef"
          :data="submitDraft.summary_lines || []"
          border
          size="small"
          style="width: 100%"
          max-height="360"
          show-summary
          :summary-method="submitSummaryMethod"
          @header-dragend="onHeaderDragend5"
        >
          <el-table-column column-key="image" label="图片" :width="colWidth5('image', 56)" align="center" resizable>
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
          <el-table-column
            prop="supplier_product_code"
            label="物料编号"
            :width="colWidth5('supplier_product_code', 120)"
            show-overflow-tooltip
            resizable
          />
          <el-table-column
            prop="supplier_product_name"
            label="名称"
            :min-width="flexColMinWidth5('supplier_product_name', 140)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit" label="单位" :width="colWidth5('unit', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth5('qty', 80)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.qty) }}</template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="单价" :width="colWidth5('unit_price', 130)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number
                :model-value="Number(row.unit_price || 0)"
                :min="0"
                :precision="2"
                :step="0.01"
                :controls="false"
                size="small"
                style="width: 110px"
                @change="(v: number) => onSubmitPrice(row, v)"
              />
              <div v-if="row.price_mixed" class="text-warn" style="font-size: 12px">分订单单价不一致</div>
            </template>
          </el-table-column>
          <el-table-column column-key="amount" label="金额" :width="colWidth5('amount', 90)" align="right" resizable>
            <template #default="{ row }">¥{{ formatMoney(row.amount) }}</template>
          </el-table-column>
          <el-table-column column-key="last_price" label="最近成交价" :width="colWidth5('last_price', 100)" align="right" resizable>
            <template #default="{ row }">
              {{ row.last_purchase_price != null ? formatMoney(row.last_purchase_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="confirmSubmit">确认下单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recvVisible" title="到货登记" width="760px" destroy-on-close>
      <p class="recv-hint muted">
        到货先生成 IQC 待检；合格或让步后才入池并分配到订单（齐套占用）。不合格不入池。
      </p>

      <div v-if="recvBatches.length" class="recv-batch">
        <div class="section-head">
          <strong>按物料录总量</strong>
          <span class="muted">填写后点「建议拆分」按未收比例拆到各订单行，可再改</span>
        </div>
        <el-table :data="recvBatches" border size="small" style="width: 100%; margin-bottom: 14px" @header-dragend="onHeaderDragend3">
          <el-table-column prop="supplier_product_code" label="物料" :width="colWidth3('supplier_product_code', 110)" resizable />
          <el-table-column prop="supplier_product_name" label="名称" :width="colWidth3('supplier_product_name', 120)" resizable>
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unreceived_total" label="未收合计" :width="colWidth3('unreceived_total', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.open_total) }}</template>
          </el-table-column>
          <el-table-column column-key="recv_total" label="本次总量" :width="colWidth3('recv_total', 140)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number v-model="row.total_qty" :min="0" :step="1" size="small" />
            </template>
          </el-table-column>
          <el-table-column column-key="col" label="" :width="colWidth3('col', 100)" align="center" resizable>
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="suggestSplit(row)">建议拆分</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="section-head">
        <strong>分订单明细</strong>
      </div>
      <el-table :data="recvLines" border size="small" style="width: 100%" @header-dragend="onHeaderDragend4">
        <el-table-column prop="supplier_product_code" label="物料" :width="colWidth4('supplier_product_code', 100)" resizable />
        <el-table-column column-key="订单号" label="执行单" :width="colWidth4('订单号', 110)" resizable>
          <template #default="{ row }">
            <span v-if="row.order_no">{{ row.order_no }}</span>
            <span v-else class="muted">无挂单</span>
          </template>
        </el-table-column>
        <el-table-column column-key="ordered" label="订购" :width="colWidth4('ordered', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.qty) }}</template>
        </el-table-column>
        <el-table-column column-key="arrived" label="已到" :width="colWidth4('arrived', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="unreceived" label="未收" :width="colWidth4('unreceived', 70)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.open_qty) }}</template>
        </el-table-column>
        <el-table-column column-key="this_recv" label="本次" :width="colWidth4('this_recv', 140)" align="right" resizable>
          <template #default="{ row }">
            <el-input-number v-model="row.this_qty" :min="0" :step="1" size="small" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="recvVisible = false">取消</el-button>
        <el-button type="primary" @click="doReceive">确认到货</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

withDefaults(
  defineProps<{
    embedded?: boolean
  }>(),
  { embedded: false },
)

const route = useRoute()
const tableRef = ref()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, onHeaderDragend } = useTableColWidths('po-list', tableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 140,
  fitToContainer: true,
})
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths('po-detail-summary')
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths('po-detail-lines')
const { colWidth: colWidth3, onHeaderDragend: onHeaderDragend3 } = useTableColWidths('po-recv-batches')
const { colWidth: colWidth4, onHeaderDragend: onHeaderDragend4 } = useTableColWidths('po-recv-lines')
const submitTableRef = ref()
const {
  colWidth: colWidth5,
  flexColMinWidth: flexColMinWidth5,
  onHeaderDragend: onHeaderDragend5,
} = useTableColWidths('po-submit-summary', submitTableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 140,
})
const auth = useAuthStore()

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const status = ref<string>()
const alertFilter = ref<string>()
const detailVisible = ref(false)
const detail = ref<any>(null)
const submitVisible = ref(false)
const submitDraft = ref<any>(null)
const submitLoading = ref(false)
const recvVisible = ref(false)
const recvLines = ref<any[]>([])
const recvBatches = ref<any[]>([])
const recvPoId = ref(0)

const overdueCount = computed(() => rows.value.filter((r) => r.delivery_alert === 'overdue').length)
const dueSoonCount = computed(() => rows.value.filter((r) => r.delivery_alert === 'due_soon').length)

/** 采购单主信息 rowspan + 汇总物料行拆分 */
const displayRows = computed(() => {
  const out: any[] = []
  rows.value.forEach((po, poIndex) => {
    const lines = Array.isArray(po.summary_lines) && po.summary_lines.length ? po.summary_lines : [null]
    const count = lines.length
    lines.forEach((ln: any, i: number) => {
      out.push({
        ...po,
        _key: `${po.id}-${i}`,
        _lineIndex: i,
        _lineCount: count,
        _poIndex: poIndex,
        _line: ln,
      })
    })
  })
  return out
})

const PO_MERGE_KEYS = new Set([
  'po_no',
  'partner_name',
  'ordered_at',
  'summary_total_amount',
  'status',
  'actions',
])

function groupSpanMethod({ row, column }: { row: any; column: any }) {
  const key = column.property || column.columnKey
  if (!PO_MERGE_KEYS.has(key)) return [1, 1]
  if (row._lineIndex === 0) return [row._lineCount || 1, 1]
  return [0, 0]
}

function groupRowClassName({ row }: { row: any }) {
  return (row._poIndex ?? 0) % 2 === 0 ? 'po-group-even' : 'po-group-odd'
}

const PO_STATUS: Record<string, string> = {
  draft: '待下单',
  ordered: '已下单',
  shipped: '已下单', // 历史状态，界面不再单独展示「已发货」
  partial_received: '部分到货',
  received: '已到齐',
  cancelled: '已取消',
}

function poStatusLabel(s: string) {
  return PO_STATUS[s] || s || '—'
}

function formatDateTime(v: string | null | undefined) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}

function effectivePoTerm(d: any) {
  if (d?.payment_term_days != null && d.payment_term_days !== '') {
    return Number(d.payment_term_days)
  }
  return Number(d?.supplier_payment_term_days || 0)
}

async function load() {
  const res: any = await http.get('/purchase-orders', {
    params: {
      page: page.value,
      page_size: pageSize.value,
      status: status.value || undefined,
      delivery_alert: alertFilter.value || undefined,
    },
  })
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  void nextTick(measureTableHeight)
}

function search() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function open(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  detail.value = res.data
  detailVisible.value = true
}

async function saveMeta() {
  if (!detail.value) return
  await http.patch(`/purchase-orders/${detail.value.id}`, {
    expected_date: detail.value.expected_date || undefined,
    payment_term_days: detail.value.payment_term_days,
    logistics_company: detail.value.logistics_company,
    tracking_no: detail.value.tracking_no,
    notes: detail.value.notes,
  })
  ElMessage.success('已保存')
  const res: any = await http.get(`/purchase-orders/${detail.value.id}`)
  detail.value = res.data
  load()
}

async function onSummaryPrice(row: any, v: number) {
  if (!detail.value || detail.value.status !== 'draft') return
  const res: any = await http.patch(`/purchase-orders/${detail.value.id}/summary-price`, {
    supplier_product_id: row.supplier_product_id,
    unit_price: v,
  })
  detail.value = res.data
  ElMessage.success('已按合计数量更新单价')
  load()
}

async function onSubmitPrice(row: any, v: number) {
  if (!submitDraft.value) return
  const res: any = await http.patch(`/purchase-orders/${submitDraft.value.id}/summary-price`, {
    supplier_product_id: row.supplier_product_id,
    unit_price: v,
  })
  submitDraft.value = res.data
  if (detail.value?.id === res.data.id) detail.value = res.data
  load()
}

function submitSummaryMethod({ columns, data }: { columns: any[]; data: any[] }) {
  return columns.map((col: any, i: number) => {
    if (i === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'amount') {
      const total = data.reduce((s, r) => s + Number(r.amount || 0), 0)
      return `¥${formatMoney(total)}`
    }
    return ''
  })
}

async function choosePoDocMode(
  action: '导出' | '打印',
  po: any,
  opts?: { skipDraftWarn?: boolean },
): Promise<boolean | null> {
  if (!po) return null
  if (po.status === 'draft' && !opts?.skipDraftWarn) {
    try {
      await ElMessageBox.confirm(
        action === '打印'
          ? '当前为待下单，确认仍要打印？建议核对单价后再发给供应商。'
          : '当前为待下单，确认仍要导出？',
        `${action}确认`,
        {
          type: 'warning',
          confirmButtonText: `继续${action}`,
          cancelButtonText: '取消',
        },
      )
    } catch {
      return null
    }
  }
  try {
    await ElMessageBox.confirm(`请选择${action}内容`, `${action}采购单`, {
      distinguishCancelAndClose: true,
      confirmButtonText: '完整（含内部明细）',
      cancelButtonText: '仅供应商联',
      type: 'info',
    })
    return true
  } catch (actionType) {
    if (actionType === 'close') return null
    return false
  }
}

async function exportDoc(po?: any) {
  const d = po || detail.value
  if (!d?.id) return
  const includeInternal = await choosePoDocMode('导出', d)
  if (includeInternal === null) return
  const res = await fetch(
    `/api/v1/purchase-orders/${d.id}/export?internal=${includeInternal ? '1' : '0'}`,
    { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} },
  )
  if (!res.ok) {
    let msg = '导出失败'
    try {
      const body = await res.json()
      msg = body.detail || body.error?.message || msg
    } catch {
      /* ignore */
    }
    ElMessage.error(msg)
    return
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  let filename = `${d.po_no || 'po'}.xlsx`
  const mStar = cd.match(/filename\*=UTF-8''([^;]+)/i)
  const m = cd.match(/filename="?([^";]+)"?/i)
  if (mStar?.[1]) filename = decodeURIComponent(mStar[1])
  else if (m?.[1]) filename = m[1]
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出 Excel')
}

async function printPo(po?: any) {
  const d = po || detail.value
  if (!d?.id) return
  const includeInternal = await choosePoDocMode('打印', d)
  if (includeInternal === null) return
  const url = `${window.location.origin}/admin/purchase-orders/print/${d.id}?internal=${includeInternal ? '1' : '0'}`
  const w = window.open(url, '_blank')
  if (!w) ElMessage.warning('请允许弹出窗口以打印')
}

async function openSubmit(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  if (po.status !== 'draft') {
    ElMessage.warning('仅待下单状态可下单')
    return
  }
  // 交期必填，打开时不预填
  po.expected_date = null
  submitDraft.value = po
  submitVisible.value = true
  void nextTick(() => submitTableRef.value?.doLayout?.())
}

async function confirmSubmit() {
  if (!submitDraft.value) return
  const expected = String(submitDraft.value.expected_date || '').trim()
  if (!expected) {
    ElMessage.warning('请填写协商交货日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认向「${submitDraft.value.partner_name || '供应商'}」下单？合计 ¥${formatMoney(submitDraft.value.summary_total_amount)}`,
      '二次确认',
      { type: 'warning', confirmButtonText: '确认下单', cancelButtonText: '再看看' },
    )
  } catch {
    return
  }
  submitLoading.value = true
  try {
    await http.patch(`/purchase-orders/${submitDraft.value.id}`, {
      expected_date: expected,
      notes: submitDraft.value.notes,
    })
    await http.post(`/purchase-orders/${submitDraft.value.id}/submit`)
    ElMessage.success('已下单')
    submitVisible.value = false
    submitDraft.value = null
    if (detailVisible.value && detail.value) {
      const res: any = await http.get(`/purchase-orders/${detail.value.id}`)
      detail.value = res.data
    }
    load()
  } finally {
    submitLoading.value = false
  }
}

async function cancel(row: any) {
  await http.post(`/purchase-orders/${row.id}/cancel`)
  ElMessage.success('已取消')
  load()
}

async function openReceive(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  if (['draft', 'cancelled', 'received'].includes(po.status)) {
    ElMessage.warning(`当前状态「${poStatusLabel(po.status)}」不可到货`)
    return
  }
  recvPoId.value = po.id
  recvLines.value = (po.lines || []).map((ln: any) => {
    const open = Math.max(0, Number(ln.qty) - Number(ln.received_qty || 0))
    return {
      ...ln,
      open_qty: open,
      this_qty: open,
    }
  })
  const bySp = new Map<number, any>()
  for (const ln of recvLines.value) {
    const spId = ln.supplier_product_id
    if (!bySp.has(spId)) {
      bySp.set(spId, {
        supplier_product_id: spId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        open_total: 0,
        total_qty: 0,
      })
    }
    const b = bySp.get(spId)
    b.open_total += Number(ln.open_qty) || 0
  }
  for (const b of bySp.values()) {
    b.total_qty = b.open_total
  }
  recvBatches.value = [...bySp.values()]
  recvVisible.value = true
}

/** 按未收订购量比例拆分；同物料多订单时优先填未收>0 的行 */
function suggestSplit(batch: any) {
  const spId = batch.supplier_product_id
  const total = Math.max(0, Number(batch.total_qty) || 0)
  const lines = recvLines.value.filter((l) => l.supplier_product_id === spId)
  const openSum = lines.reduce((s, l) => s + (Number(l.open_qty) || 0), 0)
  // 先清零
  for (const ln of lines) ln.this_qty = 0
  if (total <= 0 || lines.length === 0) return
  if (openSum <= 0) {
    // 全部超收：记在第一行
    lines[0].this_qty = total
    return
  }
  let left = total
  // 按未收比例分配，最后一行吃尾差
  const withOpen = lines.filter((l) => Number(l.open_qty) > 0)
  withOpen.forEach((ln, idx) => {
    const open = Number(ln.open_qty) || 0
    if (idx === withOpen.length - 1) {
      ln.this_qty = Math.max(0, left)
      return
    }
    const share = Math.min(open, Math.round((total * open) / openSum))
    ln.this_qty = share
    left -= share
  })
  // 总量超过未收合计：余量加到最后一行（超收进池）
  if (left > 0 && withOpen.length) {
    withOpen[withOpen.length - 1].this_qty = Number(withOpen[withOpen.length - 1].this_qty) + left
  } else if (left > 0 && lines.length) {
    lines[0].this_qty = Number(lines[0].this_qty) + left
  }
  ElMessage.success('已按未收比例建议拆分，可再手工调整')
}

async function doReceive() {
  const payload = recvLines.value
    .filter((l) => Number(l.this_qty) > 0)
    .map((l) => ({ line_id: l.id, qty: l.this_qty }))
  if (!payload.length) {
    ElMessage.warning('请填写本次到货数量')
    return
  }
  const res: any = await http.post(`/purchase-orders/${recvPoId.value}/receive`, { lines: payload })
  const n = res.data?.iqc_pending_count
  if (n) {
    ElMessage.success(`已登记到货，生成 ${n} 条待检（请到「来料 IQC」判定后再入池）`)
  } else {
    ElMessage.success('到货已登记（入池并自动分配挂单行）')
  }
  recvVisible.value = false
  load()
  if (detailVisible.value && detail.value?.id === recvPoId.value) {
    open({ id: recvPoId.value })
  }
}

watch(
  () => String(route.query.refresh || ''),
  (v, prev) => {
    if (!v || v === prev) return
    status.value = undefined
    alertFilter.value = undefined
    page.value = 1
    void load()
  },
)

onMounted(load)
</script>

<style scoped>
.text-danger {
  color: #c45656;
  font-weight: 600;
}
.text-warn {
  color: #c45c26;
  font-weight: 600;
}
.detail-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 4px 0 8px;
}
.recv-hint {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.5;
}
.recv-batch {
  margin-bottom: 8px;
}
.submit-meta {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
  padding: 14px 16px;
  border-radius: 10px;
  background: linear-gradient(180deg, #f7faf8 0%, #f3f6f4 100%);
  border: 1px solid #e5ebe7;
}
.submit-meta-main {
  min-width: 0;
  flex: 1;
}
.submit-meta-label {
  font-size: 12px;
  color: #8a9499;
  margin-bottom: 4px;
  letter-spacing: 0.02em;
}
.submit-meta-partner {
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.3;
  letter-spacing: -0.02em;
}
.submit-meta-notes {
  margin: 8px 0 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.45;
  white-space: pre-wrap;
}
.submit-meta-date {
  flex-shrink: 0;
  text-align: right;
}
.submit-meta-date .submit-meta-label {
  text-align: right;
}
.req {
  color: #c45656;
  font-weight: 600;
}
.mat-thumb {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  background: #f8fafc;
  display: block;
  margin: 0 auto;
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
.purchase-panel {
  min-width: 0;
}
:deep(.po-grouped-table .el-table__header-wrapper),
:deep(.po-grouped-table .el-table__body-wrapper),
:deep(.po-grouped-table .el-table__footer-wrapper) {
  overflow-x: hidden !important;
}
:deep(.po-grouped-table .el-table__body td.el-table__cell) {
  vertical-align: middle;
}
:deep(.po-grouped-table .po-group-even > td.el-table__cell) {
  background: #fff !important;
}
:deep(.po-grouped-table .po-group-odd > td.el-table__cell) {
  background: var(--ws-table-stripe, #eef2f7) !important;
}
:deep(.po-grouped-table .el-table__body tr.po-group-even:hover > td.el-table__cell) {
  background: #f5f7fa !important;
}
:deep(.po-grouped-table .el-table__body tr.po-group-odd:hover > td.el-table__cell) {
  background: #e8edf3 !important;
}
</style>
