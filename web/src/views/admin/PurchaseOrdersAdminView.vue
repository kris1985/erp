<template>
  <div>
    <header class="page-hero">
      <div v-if="!embedded" class="page-hero-copy">
        <h1 class="page-title">采购单</h1>
      </div>
      <div class="page-hero-stats so-status-stats">
        <button
          v-for="item in statusStatItems"
          :key="item.value"
          type="button"
          class="so-stat-chip"
          :class="[item.tone, { active: status === item.value }]"
          :title="statusCountTitle(item.label, statusStats.by_status[item.value] || 0)"
          @click="filterByStatus(item.value)"
        >
          <span class="so-stat-label">{{ item.label }}</span>
          <strong class="so-stat-num">{{ formatStatusCount(statusStats.by_status[item.value] || 0) }}</strong>
        </button>
        <button
          type="button"
          class="so-stat-chip"
          :class="{ active: !status }"
          :title="statusCountTitle('全部', statusStats.total)"
          @click="filterByStatus('')"
        >
          <span class="so-stat-label">全部</span>
          <strong class="so-stat-num">{{ formatStatusCount(statusStats.total) }}</strong>
        </button>
      </div>
    </header>
    <div :class="embedded ? 'purchase-panel' : 'admin-card'">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          placeholder="采购单号/供应商/物料/生产单"
          style="width: 220px"
          @clear="search"
          @keyup.enter="search"
        />
        <el-select
          v-model="partnerId"
          clearable
          filterable
          placeholder="供应商"
          style="width: 160px"
          @change="search"
        >
          <el-option v-for="s in suppliers" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-date-picker
          v-model="orderedRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="下单日起"
          end-placeholder="下单日止"
          style="width: 240px"
          @change="search"
        />
        <el-tag v-if="dueSoonCount" type="warning" effect="plain">即将到期 {{ dueSoonCount }}</el-tag>
        <button
          type="button"
          class="po-expect-chip"
          :class="{ active: expectedUnreceived }"
          @click="toggleExpectedUnreceived"
        >
          预期未到货 <strong>{{ expectedUnreceivedCount }}</strong> 单
        </button>
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
          column-key="expected_date"
          label="协商到货日期"
          :width="colWidth('expected_date', 120)"
          align="center"
          resizable
        >
          <template #default="{ row }">{{ formatDate(row.expected_date) }}</template>
        </el-table-column>
        <el-table-column
          column-key="suggested_arrival_date"
          label="建议到货日期"
          :width="colWidth('suggested_arrival_date', 120)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <el-tooltip
              v-if="suggestedDateList(row).length > 1"
              :content="suggestedDateList(row).join('、')"
              placement="top"
            >
              <span :class="{ 'text-danger': isSuggestedOverdue(row) }">{{ formatDate(row.suggested_arrival_date) }}</span>
            </el-tooltip>
            <span v-else :class="{ 'text-danger': isSuggestedOverdue(row) }">{{ formatDate(row.suggested_arrival_date) }}</span>
          </template>
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
            <el-button v-if="row.status === 'draft'" v-permission="'btn.purchase_orders.write'" link type="primary" @click="openSubmit(row)">下单</el-button>
            <el-button
              v-if="['ordered', 'shipped', 'partial_received'].includes(row.status)"
              link
              @click="openReceive(row)"
            >到货</el-button>
            <el-button v-if="row.status === 'draft'" v-permission="'btn.purchase_orders.write'" link type="danger" @click="cancel(row)">取消</el-button>
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
          <el-form-item label="协商到货日期">
            <el-date-picker
              v-model="detail.expected_date"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
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
          <el-button v-permission="'btn.purchase_orders.write'" type="primary" @click="saveMeta">保存</el-button>
        </el-form>

        <div class="section-head">
          <strong>采购汇总</strong>
          <span class="muted">
            {{ detailSummaryHasSize ? '按物料、码数合计' : '按物料合计' }} · 金额 ¥{{ formatMoney(detail.summary_total_amount) }}
          </span>
        </div>
        <el-table ref="detailSummaryTableRef" :data="detailSummaryRows" border size="small" style="width: 100%; margin-bottom: 16px" @header-dragend="onHeaderDragend1">
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
          <el-table-column v-if="detailSummaryHasSize" column-key="size_value" label="码数" :width="colWidth1('size_value', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
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

        <template v-if="detailHasProductionOrder">
        <div class="section-head">
          <strong>分订单明细</strong>
          <span class="muted">到货回写用 · 不合并</span>
        </div>
        <el-table ref="detailLinesTableRef" :data="detail.lines" border size="small" style="width: 100%" @header-dragend="onHeaderDragend2">
          <el-table-column prop="supplier_product_code" label="物料" :width="colWidth2('supplier_product_code', 100)" resizable />
          <el-table-column column-key="size_value" label="尺码" :width="colWidth2('size_value', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.size_value || '—' }}</template>
          </el-table-column>
          <el-table-column prop="order_no" label="生产单" :width="colWidth2('order_no', 90)" resizable />
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
      </template>
    </el-drawer>

    <el-dialog
      v-model="submitVisible"
      :title="submitDraft ? `确认下单 · ${submitDraft.po_no}` : '确认下单'"
      width="820px"
      destroy-on-close
      class="po-submit-dialog"
      @opened="focusSubmitUnitPrice"
    >
      <template v-if="submitDraft">
        <div class="submit-meta">
          <div class="submit-meta-main">
            <div class="submit-meta-label">供应商</div>
            <div class="submit-meta-partner">{{ submitDraft.partner_name || '—' }}</div>
            <p v-if="submitDraft.notes" class="submit-meta-notes">{{ submitDraft.notes }}</p>
          </div>
          <div v-if="submitDraft.suggested_arrival_date" class="submit-meta-date">
            <div class="submit-meta-label">建议到货日期</div>
            <div class="submit-meta-suggest" :class="{ 'text-danger': isSuggestedOverdue(submitDraft) }">{{ formatDate(submitDraft.suggested_arrival_date) }}</div>
            <p v-if="suggestedDateList(submitDraft).length > 1" class="submit-meta-suggest-more">
              另有 {{ suggestedDateList(submitDraft).slice(1).join('、') }}
            </p>
          </div>
          <div class="submit-meta-date">
            <div class="submit-meta-label">协商到货日期 <span class="req">*</span></div>
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
        <el-button v-permission="'btn.purchase_orders.write'" type="primary" :loading="submitLoading" @click="confirmSubmit">确认下单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recvVisible" title="到货登记" width="1100px" destroy-on-close>
      <p class="recv-hint muted">
        确认到货后直接入库存池，并生成待结算明细。
      </p>
      <el-form label-width="88px" style="margin-bottom: 8px">
        <el-form-item label="送货单号">
          <el-input v-model="deliveryNoteNo" clearable placeholder="选填" style="width: 280px" />
        </el-form-item>
      </el-form>

      <div v-if="recvBatches.length" class="recv-batch">
        <div class="section-head">
          <strong>按物料录总量</strong>
          <span class="muted">{{ recvHasProductionOrder ? '填写本次到货后，可平均分配或优先满足急单、早交期订单' : '按物料填写本次到货数量' }}</span>
        </div>
        <el-table ref="recvBatchesTableRef" :data="recvBatches" border size="small" style="width: 100%; margin-bottom: 14px" @header-dragend="onHeaderDragend3">
          <el-table-column column-key="image" label="图片" :width="colWidth3('image', 58)" align="center" resizable>
            <template #default="{ row }">
              <el-image v-if="row.image_url" :src="row.image_url" fit="cover" style="width: 36px; height: 36px; border-radius: 4px" :preview-src-list="[row.image_url]" preview-teleported />
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="supplier_product_code" label="物料" :width="colWidth3('supplier_product_code', 110)" resizable />
          <el-table-column prop="supplier_product_name" label="名称" :width="colWidth3('supplier_product_name', 120)" resizable>
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit" label="单位" :width="colWidth3('unit', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="size_value" label="码数" :width="colWidth3('size_value', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.size_value || '通用' }}</template>
          </el-table-column>
          <el-table-column column-key="ordered_total" label="总数" :width="colWidth3('ordered_total', 72)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.ordered_total) }}</template>
          </el-table-column>
          <el-table-column column-key="unreceived_total" label="未收合计" :width="colWidth3('unreceived_total', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.open_total) }}</template>
          </el-table-column>
          <el-table-column column-key="recv_total" label="本次到货" :width="colWidth3('recv_total', 140)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number v-model="row.total_qty" :min="0" :precision="2" :step="0.01" size="small" />
            </template>
          </el-table-column>
          <el-table-column v-if="recvHasProductionOrder" column-key="col" label="拆分方式" :width="colWidth3('col', 170)" align="center" resizable>
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="suggestSplit(row, 'average')">平均</el-button>
              <el-button link type="primary" size="small" @click="suggestSplit(row, 'priority')">按单优先级</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template v-if="recvHasProductionOrder">
      <div class="section-head">
        <strong>分订单明细</strong>
      </div>
      <el-table ref="recvLinesTableRef" :data="recvLines" border size="small" style="width: 100%" @header-dragend="onHeaderDragend4">
        <el-table-column column-key="image" label="图片" :width="colWidth4('image', 58)" align="center" resizable>
          <template #default="{ row }">
            <el-image v-if="row.image_url" :src="row.image_url" fit="cover" style="width: 36px; height: 36px; border-radius: 4px" :preview-src-list="[row.image_url]" preview-teleported />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料" :width="colWidth4('supplier_product_code', 100)" resizable />
        <el-table-column column-key="unit" label="单位" :width="colWidth4('unit', 64)" align="center" resizable>
          <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="size_value" label="码数" :width="colWidth4('size_value', 64)" align="center" resizable>
          <template #default="{ row }">{{ row.size_value || '通用' }}</template>
        </el-table-column>
        <el-table-column column-key="订单号" label="生产单" :width="colWidth4('订单号', 110)" resizable>
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
        <el-table-column column-key="this_recv" label="本次到货" :width="colWidth4('this_recv', 140)" align="right" resizable>
          <template #default="{ row }">
            <el-input-number v-model="row.this_qty" :min="0" :precision="2" :step="0.01" size="small" />
          </template>
        </el-table-column>
      </el-table>
      </template>
      <template #footer>
        <el-button @click="recvVisible = false">取消</el-button>
        <el-button v-permission="'btn.purchase_orders.write'" type="primary" @click="doReceive">确认到货</el-button>
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
const detailSummaryTableRef = ref()
const detailLinesTableRef = ref()
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths(
  'po-detail-summary',
  detailSummaryTableRef,
  { flexKey: 'supplier_product_name', flexDefaultMin: 120, fitToContainer: true },
)
const { colWidth: colWidth2, onHeaderDragend: onHeaderDragend2 } = useTableColWidths(
  'po-detail-lines',
  detailLinesTableRef,
  { flexKey: 'order_no', flexDefaultMin: 90, fitToContainer: true },
)
const recvBatchesTableRef = ref()
const recvLinesTableRef = ref()
const {
  colWidth: colWidth3,
  onHeaderDragend: onHeaderDragend3,
  relayoutTable: relayoutRecvBatchesTable,
} = useTableColWidths(
  'po-recv-batches',
  recvBatchesTableRef,
  { flexKey: 'supplier_product_name', flexDefaultMin: 120, fitToContainer: true },
)
const {
  colWidth: colWidth4,
  onHeaderDragend: onHeaderDragend4,
  relayoutTable: relayoutRecvLinesTable,
} = useTableColWidths(
  'po-recv-lines',
  recvLinesTableRef,
  { flexKey: '订单号', flexDefaultMin: 110, fitToContainer: true },
)
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
const status = ref('')
const statusStats = ref<{ total: number; by_status: Record<string, number> }>({
  total: 0,
  by_status: {
    draft: 0,
    ordered: 0,
    partial_received: 0,
    received: 0,
    cancelled: 0,
  },
})
const statusStatItems = [
  { value: 'draft', label: '待下单', tone: 'tone-pending-production' },
  { value: 'ordered', label: '已下单', tone: 'tone-in-progress' },
  { value: 'partial_received', label: '部分到货', tone: 'tone-partial' },
  { value: 'received', label: '已到齐', tone: 'tone-completed' },
  { value: 'cancelled', label: '已取消', tone: 'tone-cancelled' },
] as const
const keyword = ref('')
const partnerId = ref<number>()
const suppliers = ref<any[]>([])
const orderedRange = ref<string[] | null>(null)
const expectedUnreceived = ref(false)
const expectedUnreceivedCount = ref(0)
const detailVisible = ref(false)
const detail = ref<any>(null)
const submitVisible = ref(false)
const submitDraft = ref<any>(null)
const submitLoading = ref(false)
const recvVisible = ref(false)
const deliveryNoteNo = ref('')
const recvLines = ref<any[]>([])
const recvBatches = ref<any[]>([])
const recvPoId = ref(0)

function lineHasProductionOrder(ln: any) {
  return Boolean(ln?.order_no || ln?.header_id || ln?.order_id)
}

const detailHasProductionOrder = computed(() =>
  (detail.value?.lines || []).some((ln: any) => lineHasProductionOrder(ln)),
)
const detailSummaryHasSize = computed(() =>
  (detail.value?.lines || []).some((ln: any) => ln.size_id != null),
)
const detailSummaryRows = computed(() => buildDetailSummaryRows(detail.value))
const recvHasProductionOrder = computed(() => recvLines.value.some((ln) => lineHasProductionOrder(ln)))

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
  'expected_date',
  'suggested_arrival_date',
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

function formatStatusCount(value: number) {
  const count = Math.max(0, Number(value || 0))
  if (count < 10_000) return count.toLocaleString('zh-CN')
  const wan = count / 10_000
  const digits = wan < 100 ? 1 : 0
  return `${wan.toFixed(digits).replace(/\.0$/, '')}万`
}

function statusCountTitle(label: string, value: number) {
  return `${label}：${Math.max(0, Number(value || 0)).toLocaleString('zh-CN')} 单`
}

function filterByStatus(next: string) {
  status.value = next
  expectedUnreceived.value = false
  search()
}

function formatDateTime(v: string | null | undefined) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 16)
}

function formatDate(v: string | null | undefined) {
  if (!v) return '—'
  return String(v).slice(0, 10)
}

function suggestedDateList(row: any) {
  const dates = Array.isArray(row?.suggested_arrival_dates) ? row.suggested_arrival_dates : []
  return dates.map((d: any) => String(d).slice(0, 10)).filter(Boolean)
}

function isSuggestedOverdue(row: any) {
  const raw = row?.suggested_arrival_date
  if (!raw) return false
  if (row.status === 'received' || row.status === 'cancelled') return false
  const day = String(raw).slice(0, 10)
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return day < today
}

function formatNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
}

function formatMoney(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toFixed(2)
}

function moneyRound(n: number) {
  return Math.round(n * 100) / 100
}

function buildDetailSummaryRows(po: any) {
  if (!po) return []
  const lines = po.lines || []
  const sized = lines.some((ln: any) => ln.size_id != null)
  if (!sized) return po.summary_lines || []
  const summaryByProduct = new Map<number, any>(
    (po.summary_lines || []).map((row: any) => [row.supplier_product_id, row]),
  )
  const buckets = new Map<string, any>()
  for (const ln of lines) {
    const key = `${ln.supplier_product_id}:${ln.size_id ?? ''}`
    let bucket = buckets.get(key)
    if (!bucket) {
      const summary = summaryByProduct.get(ln.supplier_product_id)
      bucket = {
        key,
        supplier_product_id: ln.supplier_product_id,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        image_url: ln.image_url,
        pricing_unit_name: ln.pricing_unit_name,
        size_value: ln.size_value || null,
        size_sort_order: ln.size_sort_order ?? 0,
        qty: 0,
        received_qty: 0,
        unit_price: summary?.unit_price ?? ln.unit_price,
        price_mixed: Boolean(summary?.price_mixed),
        last_purchase_price: summary?.last_purchase_price ?? ln.last_purchase_price,
      }
      buckets.set(key, bucket)
    }
    bucket.qty += Number(ln.qty || 0)
    bucket.received_qty += Number(ln.received_qty || 0)
  }
  const rows = [...buckets.values()]
  rows.sort((a, b) => {
    const code = String(a.supplier_product_code || '').localeCompare(
      String(b.supplier_product_code || ''),
      'zh',
    )
    if (code) return code
    if (!a.size_value && b.size_value) return 1
    if (a.size_value && !b.size_value) return -1
    const order = Number(a.size_sort_order || 0) - Number(b.size_sort_order || 0)
    if (order) return order
    return String(a.size_value || '').localeCompare(String(b.size_value || ''), 'zh')
  })
  const byProduct = new Map<number, any[]>()
  for (const row of rows) {
    const list = byProduct.get(row.supplier_product_id) || []
    list.push(row)
    byProduct.set(row.supplier_product_id, list)
  }
  for (const [productId, list] of byProduct) {
    const summary = summaryByProduct.get(productId)
    const summaryAmount = summary != null ? Number(summary.amount) : null
    let allocated = 0
    list.forEach((row, index) => {
      const price = Number(row.unit_price || 0)
      if (summaryAmount != null && !Number.isNaN(summaryAmount) && index === list.length - 1) {
        row.amount = moneyRound(summaryAmount - allocated)
      } else {
        row.amount = moneyRound(Number(row.qty || 0) * price)
        allocated += row.amount
      }
    })
  }
  return rows
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function loadStatusStats() {
  try {
    const res: any = await http.get('/purchase-orders/status-stats')
    statusStats.value = {
      total: Number(res.data?.total || 0),
      by_status: {
        draft: Number(res.data?.by_status?.draft || 0),
        ordered: Number(res.data?.by_status?.ordered || 0),
        partial_received: Number(res.data?.by_status?.partial_received || 0),
        received: Number(res.data?.by_status?.received || 0),
        cancelled: Number(res.data?.by_status?.cancelled || 0),
      },
    }
  } catch {
    // keep previous stats
  }
}

async function load() {
  const [res] = await Promise.all([
    http.get('/purchase-orders', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        status: status.value || undefined,
        partner_id: partnerId.value || undefined,
        keyword: keyword.value.trim() || undefined,
        ordered_from: orderedRange.value?.[0] || undefined,
        ordered_to: orderedRange.value?.[1] || undefined,
        expected_unreceived: expectedUnreceived.value || undefined,
      },
    }) as Promise<any>,
    loadStatusStats(),
  ])
  const payload = res.data
  rows.value = payload?.items || (Array.isArray(payload) ? payload : [])
  total.value = payload?.total ?? rows.value.length
  expectedUnreceivedCount.value = Number(payload?.expected_unreceived_count || 0)
  void nextTick(measureTableHeight)
}

function search() {
  page.value = 1
  void load()
}

function toggleExpectedUnreceived() {
  expectedUnreceived.value = !expectedUnreceived.value
    if (expectedUnreceived.value) {
      status.value = ''
    }
  search()
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
  if (d.status === 'draft') {
    try {
      await ElMessageBox.confirm(
        '当前为待下单，确认仍要打印？建议核对单价后再发给供应商。',
        '打印确认',
        {
          type: 'warning',
          confirmButtonText: '继续打印',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  }
  const url = `${window.location.origin}/admin/purchase-orders/print/${d.id}`
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

function focusSubmitUnitPrice() {
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>(
      '.po-submit-dialog .el-input-number input',
    )
    input?.focus()
    input?.select()
  })
}

async function confirmSubmit() {
  if (!submitDraft.value) return
  const expected = String(submitDraft.value.expected_date || '').trim()
  if (!expected) {
    ElMessage.warning('请填写协商交货日期')
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
  deliveryNoteNo.value = ''
  recvLines.value = (po.lines || []).map((ln: any) => {
    const open = Math.max(
      0,
      Number(ln.open_qty ?? (Number(ln.qty) - Number(ln.received_qty || 0) - Number(ln.pending_iqc_qty || 0))),
    )
    return {
      ...ln,
      open_qty: open,
      this_qty: open,
    }
  })
  const bySp = new Map<string, any>()
  for (const ln of recvLines.value) {
    const spId = ln.supplier_product_id
    const batchKey = `${spId}:${ln.size_id || 0}`
    if (!bySp.has(batchKey)) {
      bySp.set(batchKey, {
        batch_key: batchKey,
        supplier_product_id: spId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        image_url: ln.image_url,
        pricing_unit_name: ln.pricing_unit_name,
        size_id: ln.size_id,
        size_value: ln.size_value,
        ordered_total: 0,
        pending_iqc_total: 0,
        open_total: 0,
        total_qty: 0,
      })
    }
    const b = bySp.get(batchKey)
    b.ordered_total += Number(ln.qty) || 0
    b.pending_iqc_total += Number(ln.pending_iqc_qty) || 0
    b.open_total += Number(ln.open_qty) || 0
  }
  for (const b of bySp.values()) {
    b.total_qty = b.open_total
  }
  recvBatches.value = [...bySp.values()]
  recvVisible.value = true
  await nextTick()
  relayoutRecvBatchesTable()
  relayoutRecvLinesTable()
}

/** 以 0.01 为最小单位平均拆分，或按急单→交期→生产单顺序优先满足。 */
function suggestSplit(batch: any, mode: 'average' | 'priority') {
  const spId = batch.supplier_product_id
  const sizeId = batch.size_id || 0
  const lines = recvLines.value.filter(
    (l) => l.supplier_product_id === spId && (l.size_id || 0) === sizeId,
  )
  for (const ln of lines) ln.this_qty = 0
  if (!lines.length) return

  let rows = lines
    .map((line) => ({ line, cap: Math.max(0, Math.floor((Number(line.open_qty) || 0) * 100 + 1e-8)) }))
    .filter((row) => row.cap > 0)
  if (mode === 'priority') {
    rows = rows.sort((a, b) => {
      const rushDiff = Number(Boolean(b.line.is_rush)) - Number(Boolean(a.line.is_rush))
      if (rushDiff) return rushDiff
      const dateA = a.line.delivery_date || '9999-12-31'
      const dateB = b.line.delivery_date || '9999-12-31'
      const dateDiff = String(dateA).localeCompare(String(dateB))
      if (dateDiff) return dateDiff
      return Number(a.line.header_id || a.line.order_id || a.line.id) - Number(b.line.header_id || b.line.order_id || b.line.id)
    })
  }
  const capTotal = rows.reduce((sum, row) => sum + row.cap, 0)
  if (!capTotal) return

  const requested = Math.max(0, Math.round((Number(batch.total_qty) || 0) * 100))
  const target = Math.min(requested, capTotal)
  if (requested > capTotal) {
    batch.total_qty = capTotal / 100
    ElMessage.warning('本次到货超过未收合计，已按未收上限拆分')
  }

  const allocations = rows.map(() => 0)
  let remainder = target
  if (mode === 'priority') {
    for (let i = 0; i < rows.length && remainder > 0; i += 1) {
      allocations[i] = Math.min(rows[i].cap, remainder)
      remainder -= allocations[i]
    }
  } else {
    let active = rows.map((_, index) => index)
    while (remainder > 0 && active.length) {
      const share = Math.max(1, Math.floor(remainder / active.length))
      for (const index of active) {
        if (remainder <= 0) break
        const qty = Math.min(rows[index].cap - allocations[index], share, remainder)
        allocations[index] += qty
        remainder -= qty
      }
      active = active.filter((index) => allocations[index] < rows[index].cap)
    }
  }
  rows.forEach((row, index) => {
    row.line.this_qty = allocations[index] / 100
  })
  ElMessage.success(mode === 'priority' ? '已按订单优先级拆分，可再手工调整' : '已平均拆分，可再手工调整')
}

/** 无生产单时界面只录物料总量，提交前按未收上限写回各行。 */
function applyBatchQtyWithoutOrders() {
  let capped = false
  for (const batch of recvBatches.value) {
    const sizeId = batch.size_id || 0
    const lines = recvLines.value.filter(
      (l) => l.supplier_product_id === batch.supplier_product_id && (l.size_id || 0) === sizeId,
    )
    for (const ln of lines) ln.this_qty = 0
    const rows = lines
      .map((line) => ({
        line,
        cap: Math.max(0, Math.round((Number(line.open_qty) || 0) * 100)),
      }))
      .sort((a, b) => Number(a.line.id) - Number(b.line.id))
    const capTotal = rows.reduce((sum, row) => sum + row.cap, 0)
    let remain = Math.max(0, Math.round((Number(batch.total_qty) || 0) * 100))
    if (remain > capTotal) {
      remain = capTotal
      batch.total_qty = capTotal / 100
      capped = true
    }
    for (const row of rows) {
      const take = Math.min(row.cap, remain)
      row.line.this_qty = take / 100
      remain -= take
    }
  }
  return capped
}

async function doReceive() {
  if (!recvHasProductionOrder.value && applyBatchQtyWithoutOrders()) {
    ElMessage.warning('本次到货超过未收合计，已按未收上限登记')
  }
  const payload = recvLines.value
    .filter((l) => Number(l.this_qty) > 0)
    .map((l) => ({ line_id: l.id, qty: l.this_qty }))
  if (!payload.length) {
    ElMessage.warning('请填写本次到货数量')
    return
  }
  await http.post(`/purchase-orders/${recvPoId.value}/receive`, {
    lines: payload,
    delivery_note_no: deliveryNoteNo.value || undefined,
  })
  ElMessage.success('到货已登记，已入池并生成待结算明细')
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
    status.value = ''
    keyword.value = ''
    partnerId.value = undefined
    orderedRange.value = null
    expectedUnreceived.value = false
    page.value = 1
    void load()
  },
)

onMounted(async () => {
  await loadSuppliers()
  await load()
})
</script>

<style scoped>
.page-hero {
  align-items: center;
}
.so-status-stats {
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
}
.so-stat-chip {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-width: 68px;
  flex: 0 0 auto;
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.so-stat-chip:hover {
  border-color: #93c5fd;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
}
.so-stat-chip.active {
  border-color: #0076ff;
  background: #eff6ff;
  box-shadow: 0 0 0 1px rgba(0, 118, 255, 0.18);
}
.so-stat-label {
  font-size: 12px;
  color: #64748b;
  line-height: 1.1;
}
.so-stat-num {
  font-size: 16px;
  font-weight: 750;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  white-space: nowrap;
}
.so-stat-chip.tone-pending-production .so-stat-num {
  color: #b45309;
}
.so-stat-chip.tone-in-progress .so-stat-num {
  color: #1d4ed8;
}
.so-stat-chip.tone-partial .so-stat-num {
  color: #c45c26;
}
.so-stat-chip.tone-completed .so-stat-num {
  color: #15803d;
}
.so-stat-chip.tone-cancelled .so-stat-num {
  color: #94a3b8;
}
.po-expect-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}
.po-expect-chip strong {
  color: #0076ff;
  font-size: 16px;
  font-weight: 700;
}
.po-expect-chip:hover,
.po-expect-chip.active {
  border-color: #0076ff;
  background: #eef6ff;
  color: #111827;
}
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
.submit-meta-suggest {
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
  line-height: 32px;
  letter-spacing: -0.02em;
}
.submit-meta-suggest-more {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
  text-align: right;
  white-space: nowrap;
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
