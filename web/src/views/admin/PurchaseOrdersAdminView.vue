<template>
  <div>
    <header class="page-hero">
      <div v-if="!embedded" class="page-hero-copy">
        <h1 class="page-title">在途</h1>
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
          placeholder="采购单号"
          style="width: 160px"
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
        <el-select
          v-model="supplierProductId"
          clearable
          filterable
          :filter-method="filterMaterials"
          placeholder="物料编号"
          popper-class="po-material-popper"
          style="width: 160px"
          @change="search"
          @visible-change="onMaterialVisible"
        >
          <el-option
            v-for="item in shownMaterials"
            :key="item.id"
            :label="item.product_code"
            :value="item.id"
          >
            <span class="po-material-option">
              <img v-if="item.image_url" :src="item.image_url" alt="" />
              <span v-else class="po-material-option-ph" />
              <span class="po-material-option-text">
                <span class="po-material-option-name">{{ item.name || item.product_code || '—' }}</span>
                <span class="po-material-option-cat">{{ item.category_name || '—' }}</span>
              </span>
            </span>
          </el-option>
        </el-select>
        <el-date-picker
          v-model="orderedRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="反馈日起"
          end-placeholder="反馈日止"
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
        <el-table-column column-key="ordered_at" label="反馈时间" :width="colWidth('ordered_at', 136)" resizable>
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
        <el-table-column
          column-key="category_name"
          label="分类"
          :width="colWidth('category_name', 100)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row._line?.category_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="unit" label="计价单位" :width="colWidth('unit', 80)" align="center" resizable>
          <template #default="{ row }">{{ row._line?.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="unit_price" label="单价" :width="colWidth('unit_price', 72)" align="right" resizable>
          <template #default="{ row }">{{ row._line ? formatMoney(row._line.unit_price) : '—' }}</template>
        </el-table-column>
        <el-table-column v-if="listSizeColumns.length" label="数量" align="center">
          <el-table-column
            v-for="size in listSizeColumns"
            :key="size"
            :column-key="`sz_${size}`"
            :label="size"
            :width="colWidth(`sz_${size}`, 72)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <div v-if="row._hasSizes" class="qty-stack">
                <template v-if="row._sizeQty[size] != null">
                  <div>{{ formatNum(listBaseQty(row, row._sizeQty[size], row._sizeLoss[size])) }}</div>
                  <div v-if="Number(row._sizeLoss[size])" class="qty-stack-loss">{{ formatNum(row._sizeLoss[size]) }}</div>
                </template>
                <span v-else>—</span>
              </div>
              <div v-else-if="size === listSizeColumns[0]" class="qty-stack">
                <div>{{ row._line ? formatNum(listBaseQty(row, row._line.qty, row._line.loss_qty)) : '—' }}</div>
                <div v-if="row._line && Number(row._line.loss_qty)" class="qty-stack-loss">{{ formatNum(row._line.loss_qty) }}</div>
              </div>
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column v-else column-key="qty" label="数量" :width="colWidth('qty', 140)" align="center" resizable>
          <template #default="{ row }">
            <div class="qty-stack">
              <div>{{ materialQtyText(row, row._line) }}</div>
              <div v-if="materialLossText(row, row._line)" class="qty-stack-loss">{{ materialLossText(row, row._line) }}</div>
            </div>
          </template>
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
        <el-table-column column-key="status" label="状态" :width="colWidth('status', 132)" resizable>
          <template #default="{ row }">
            <span>{{ poStatusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column column-key="actions" label="操作" width="64" align="center" :resizable="false">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(cmd: string) => onRowCommand(row, cmd)">
              <span class="po-action-hit">
                <el-button link type="primary" :icon="MoreFilled" aria-label="更多操作" />
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="export">导出</el-dropdown-item>
                  <el-dropdown-item command="print">打印</el-dropdown-item>
                  <el-dropdown-item v-if="canEditLoss(row)" command="loss">添加损耗</el-dropdown-item>
                  <el-dropdown-item v-if="row.status === 'draft' && canPlacePo" command="submit">下单反馈</el-dropdown-item>
                  <el-dropdown-item v-if="['ordered', 'shipped', 'partial_received'].includes(row.status)" command="receive">到货</el-dropdown-item>
                  <el-dropdown-item v-if="canUnsubscribe(row)" v-permission="'btn.purchase_orders.write'" command="unsubscribe">退订</el-dropdown-item>
                  <el-dropdown-item v-if="row.status === 'draft'" v-permission="'btn.purchase_orders.write'" command="cancel" divided>取消</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
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

    <el-drawer v-model="detailVisible" size="980px" class="po-detail-drawer" append-to-body>
      <template #header>
        <div v-if="detail" class="po-drawer-head">
          <div class="po-drawer-id">
            <span class="po-drawer-no">{{ detail.po_no }}</span>
            <span class="po-stamp" :class="poStatusTone(detail.status)">{{ poStatusLabel(detail.status) }}</span>
            <span v-if="detail.delivery_alert === 'overdue'" class="po-alert is-overdue">
              {{ detail.delivery_alert_label || '已逾期' }}
            </span>
            <span v-else-if="detail.delivery_alert === 'due_soon'" class="po-alert is-soon">
              {{ detail.delivery_alert_label || '即将到期' }}
            </span>
            <span v-else class="po-alert is-ok">交期正常</span>
          </div>
          <div class="po-drawer-actions">
            <el-button @click="exportDoc()">导出</el-button>
            <el-button type="primary" plain @click="printPo()">打印</el-button>
            <el-button v-if="canEditLoss(detail)" @click="openLoss(detail)">添加损耗</el-button>
            <el-button
              v-if="detail.status === 'draft' && canPlacePo"
              type="primary"
              @click="openSubmit(detail)"
            >下单反馈</el-button>
            <el-button
              v-if="canUnsubscribe(detail)"
              v-permission="'btn.purchase_orders.write'"
              @click="openUnsubscribe(detail)"
            >退订</el-button>
          </div>
        </div>
      </template>
      <template v-if="detail">
        <div class="po-detail">
        <section class="po-sheet po-identity">
          <div class="po-identity-main">
            <div class="po-kicker">供应商</div>
            <h2 class="po-supplier">{{ detail.partner_name || '—' }}</h2>
            <dl class="po-facts">
              <div>
                <dt>买方</dt>
                <dd>{{ detail.buyer_name || '—' }}</dd>
              </div>
              <div>
                <dt>反馈时间</dt>
                <dd>{{ formatDateTime(detail.ordered_at) }}</dd>
              </div>
            </dl>
          </div>
          <div class="po-identity-amount">
            <div class="po-kicker">采购金额</div>
            <div class="po-amount">
              <span class="po-amount-yen">¥</span>
              <span class="po-amount-num">{{ formatMoney(detail.summary_total_amount) }}</span>
            </div>
          </div>
        </section>

        <section class="po-sheet">
          <div class="po-sheet-head">
            <h3>到货与物流</h3>
            <el-button v-permission="'btn.purchase_orders.write'" type="primary" @click="saveMeta">保存</el-button>
          </div>
          <div class="po-follow-grid">
            <div class="po-field">
              <span class="po-field-label">协商到货日期</span>
              <el-date-picker
                v-model="detail.expected_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
              />
            </div>
            <div class="po-field">
              <span class="po-field-label">物流公司</span>
              <el-input v-model="detail.logistics_company" clearable placeholder="选填" />
            </div>
            <div class="po-field">
              <span class="po-field-label">运单号</span>
              <el-input v-model="detail.tracking_no" clearable placeholder="选填" />
            </div>
            <div class="po-field po-field-notes">
              <span class="po-field-label">备注</span>
              <el-input v-model="detail.notes" type="textarea" :rows="2" placeholder="选填" />
            </div>
          </div>
        </section>

        <section class="po-sheet">
        <div class="po-sheet-head">
          <h3>采购汇总</h3>
          <span class="po-sheet-note">按物料合计</span>
        </div>
        <el-table
          ref="detailSummaryTableRef"
          :data="detailSummaryRows"
          border
          size="small"
          style="width: 100%"
          :span-method="detailSummarySpan"
          @header-dragend="onHeaderDragend1"
        >
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
          <el-table-column prop="supplier_product_code" label="物料编码" :width="colWidth1('supplier_product_code', 110)" show-overflow-tooltip resizable />
          <el-table-column prop="supplier_product_name" label="名称" :width="colWidth1('supplier_product_name', 120)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit" label="单位" :width="colWidth1('unit', 70)" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column v-if="detailSummarySizeColumns.length" label="码数" align="center">
            <el-table-column
              v-for="size in detailSummarySizeColumns"
              :key="size"
              :column-key="`dsz_${size}`"
              :label="size"
              :width="colWidth1(`dsz_${size}`, 88)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <div v-if="row.has_sizes && row.size_qty[size] != null" class="qty-stack">
                  <div>{{ formatNum(row.size_qty[size]) }}</div>
                  <div class="qty-stack-loss">损耗 {{ formatNum(row.size_loss[size]) }}</div>
                </div>
                <span v-else-if="row.has_sizes || size === detailSummarySizeColumns[0]" class="muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth1('qty', 120)" align="center" resizable>
            <template #default="{ row }">
              <div class="qty-stack">
                <div>{{ formatNum(row.qty) }}</div>
                <div class="qty-stack-loss">损耗 {{ formatNum(row.loss_qty) }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column column-key="arrived" label="已到" :width="colWidth1('arrived', 70)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.received_qty) }}</template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="单价" :width="colWidth1('unit_price', 120)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number
                v-if="detail.status === 'draft'"
                :model-value="shownUnitPrice(row, detailPriceDrafts)"
                :min="0"
                :precision="2"
                :step="0.01"
                :controls="false"
                size="small"
                style="width: 100px"
                :class="{ 'price-input--over': priceOverText(row, shownUnitPrice(row, detailPriceDrafts)) }"
                @change="(v: number) => onSummaryPrice(row, v)"
              />
              <span v-else>{{ formatMoney(row.unit_price) }}</span>
              <div v-if="priceOverText(row, shownUnitPrice(row, detailPriceDrafts))" class="price-over">
                {{ priceOverText(row, shownUnitPrice(row, detailPriceDrafts)) }}
              </div>
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
        </section>

        <section v-if="detailHasProductionOrder" class="po-sheet">
          <div class="po-sheet-head">
            <h3>分订单明细</h3>
            <span class="po-sheet-note">各生产单占用数量</span>
          </div>
          <div class="po-alloc">
            <div class="po-alloc-row po-alloc-head">
              <span>图片</span>
              <span>物料编码</span>
              <span>名称</span>
              <span>单位</span>
              <span>生产单</span>
              <span>数量</span>
            </div>
            <div v-for="line in detailOrderLines" :key="line.id" class="po-alloc-row">
              <span class="po-alloc-image">
                <el-image
                  v-if="line.image_url"
                  :src="line.image_url"
                  :preview-src-list="[line.image_url]"
                  fit="contain"
                  class="mat-thumb"
                  preview-teleported
                />
                <span v-else class="muted">—</span>
              </span>
              <span class="po-alloc-text" :title="line.supplier_product_code || ''">{{ line.supplier_product_code || '—' }}</span>
              <span class="po-alloc-text" :title="line.supplier_product_name || ''">{{ line.supplier_product_name || '—' }}</span>
              <span class="po-alloc-unit">{{ line.pricing_unit_name || '—' }}</span>
              <span class="po-alloc-order" :title="line.order_no || ''">{{ line.order_no || '—' }}</span>
              <span class="po-alloc-qty">{{ formatNum(line.qty) }}</span>
            </div>
          </div>
        </section>
        </div>
      </template>
    </el-drawer>

    <el-dialog
      v-model="submitVisible"
      :title="submitDraft ? `确认下单反馈 · ${submitDraft.po_no}` : '确认下单反馈'"
      :width="submitSizeColumns.length ? '1200px' : '820px'"
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

        <el-alert
          v-if="submitBlockMessage"
          class="submit-price-hint"
          type="error"
          :closable="false"
          show-icon
          :title="submitBlockMessage"
        />
        <el-table
          ref="submitTableRef"
          :data="submitRows"
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
          <el-table-column
            column-key="color_name"
            label="颜色"
            :width="colWidth5('color_name', 72)"
            align="center"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.color_name || '—' }}</template>
          </el-table-column>
          <el-table-column column-key="unit" label="单位" :width="colWidth5('unit', 64)" align="center" resizable>
            <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
          </el-table-column>
          <el-table-column v-if="submitSizeColumns.length" label="码数" align="center">
            <el-table-column
              v-for="size in submitSizeColumns"
              :key="size"
              :column-key="`size_${size}`"
              :label="size"
              :width="colWidth5(`size_${size}`, 96)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <div v-if="row.size_qty && row.size_qty[size] != null" class="qty-stack">
                  <div>{{ formatNum(purchaseQty(row.size_qty[size], row.size_loss?.[size])) }}</div>
                  <div class="qty-stack-loss">损耗 {{ submitSizeLoss(row, size) }}</div>
                </div>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column column-key="qty" label="数量" :width="colWidth5('qty', 120)" align="center" resizable>
            <template #default="{ row }">
              <div class="qty-stack">
                <div>{{ formatNum(purchaseQty(row.qty, row.loss_qty)) }}</div>
                <div class="qty-stack-loss">损耗 {{ formatNum(row.loss_qty) }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column column-key="unit_price" label="单价" :width="colWidth5('unit_price', 130)" align="right" resizable>
            <template #default="{ row }">
              <el-input-number
                :model-value="shownUnitPrice(row, submitPriceDrafts)"
                :min="0"
                :precision="2"
                :step="0.01"
                :controls="false"
                size="small"
                style="width: 110px"
                :class="{ 'price-input--over': priceOverText(row, shownUnitPrice(row, submitPriceDrafts)) }"
                @change="(v: number) => onSubmitPrice(row, v)"
              />
              <div v-if="priceOverText(row, shownUnitPrice(row, submitPriceDrafts))" class="price-over">
                {{ priceOverText(row, shownUnitPrice(row, submitPriceDrafts)) }}
              </div>
              <div v-if="row.price_mixed" class="text-warn" style="font-size: 12px">分订单单价不一致</div>
            </template>
          </el-table-column>
          <el-table-column column-key="amount" label="金额" :width="colWidth5('amount', 90)" align="right" resizable>
            <template #default="{ row }">¥{{ formatMoney(purchaseQty(row.qty, row.loss_qty) * shownUnitPrice(row, submitPriceDrafts)) }}</template>
          </el-table-column>
          <el-table-column column-key="catalog_price" label="物料色卡单价" :width="colWidth5('catalog_price', 120)" align="right" resizable>
            <template #default="{ row }">
              {{ row.catalog_price != null && row.catalog_price !== '' ? formatMoney(row.catalog_price) : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button v-if="canPlacePo" type="primary" :loading="submitLoading" :disabled="submitPriceBlocked" @click="confirmSubmit">
          确认下单反馈
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="lossVisible"
      class="loss-dialog"
      :class="{ 'is-sized': lossSizeColumns.length }"
      :title="lossPo ? `添加损耗 · ${lossPo.po_no}` : '添加损耗'"
      :width="lossSizeColumns.length ? '1100px' : '760px'"
      destroy-on-close
    >
      <p class="loss-hint">填写多买多少。有码数时在对应码列填写，下单时会加进数量。</p>
      <div ref="lossTableHost" class="loss-table-host">
      <el-table class="loss-table" :data="lossRows" border size="small" max-height="420" style="width: 100%">
        <el-table-column prop="supplier_product_code" label="物料编号" width="108" show-overflow-tooltip />
        <el-table-column prop="supplier_product_name" label="名称" width="128" show-overflow-tooltip />
        <el-table-column label="颜色" width="64" align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ row.color_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="单位" width="52" align="center">
          <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="lossSizeColumns.length" label="码数" align="center">
          <el-table-column
            v-for="size in lossSizeColumns"
            :key="size"
            :label="size"
            :width="lossSizeColWidth"
            align="center"
          >
            <template #default="{ row }">
              <div v-if="row.size_qty && row.size_qty[size] != null" class="qty-stack loss-size-cell">
                <div>{{ formatNum(row.size_qty[size]) }}</div>
                <el-input-number
                  v-model="row.size_loss[size]"
                  :min="0"
                  :step="1"
                  :controls="false"
                  size="small"
                  class="qty-input"
                />
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column label="数量" width="96" align="center">
          <template #default="{ row }">
            <div class="qty-stack">
              <div>{{ formatNum(row.qty) }}</div>
              <el-input-number
                v-if="!row.has_sizes"
                v-model="row.loss_qty"
                :min="0"
                :step="1"
                :controls="false"
                size="small"
                class="qty-input"
              />
              <div v-else class="qty-stack-loss">损耗 {{ formatNum(rowLossTotal(row)) }}</div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      </div>
      <template #footer>
        <el-button @click="lossVisible = false">取消</el-button>
        <el-button type="primary" :loading="lossSaving" @click="saveLoss">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unsubVisible" title="退订" :width="unsubSizeColumns.length ? '1100px' : '920px'" destroy-on-close>
      <p class="unsub-hint">只减还没到的数量，已到货的不能退。可以只填一部分，不填的码保持不变。</p>
      <el-table
        v-if="unsubBatches.length"
        ref="unsubTableRef"
        :data="unsubBatches"
        border
        size="small"
        style="width: 100%"
        :span-method="unsubSpanMethod"
        @header-dragend="onUnsubHeaderDragend"
      >
        <el-table-column column-key="image" label="图片" :width="unsubColWidth('image', 58)" align="center" resizable>
          <template #default="{ row }">
            <el-image v-if="row.image_url" :src="row.image_url" fit="cover" style="width: 36px; height: 36px; border-radius: 4px" :preview-src-list="[row.image_url]" preview-teleported />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料" :width="unsubColWidth('supplier_product_code', 110)" show-overflow-tooltip resizable />
        <el-table-column prop="supplier_product_name" label="名称" :width="unsubColWidth('supplier_product_name', 120)" show-overflow-tooltip resizable>
          <template #default="{ row }">{{ row.supplier_product_name || '—' }}</template>
        </el-table-column>
        <el-table-column column-key="unit" label="单位" :width="unsubColWidth('unit', 64)" align="center" resizable>
          <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="unsubSizeColumns.length" label="码数" align="center">
          <el-table-column
            v-for="size in unsubSizeColumns"
            :key="size"
            :column-key="`unsub_${size}`"
            :label="size"
            :width="unsubColWidth(`unsub_${size}`, 108)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <div v-if="row.has_sizes && row.size_open[size] != null" class="qty-stack loss-size-cell">
                <div>未到 {{ formatNum(row.size_open[size]) }}</div>
                <el-input-number
                  v-model="row.size_qty[size]"
                  :min="0"
                  :max="Number(row.size_open[size])"
                  :step="0.01"
                  :controls="false"
                  size="small"
                  class="qty-input"
                />
              </div>
              <span v-else-if="row.has_sizes || size === unsubSizeColumns[0]" class="muted">—</span>
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column column-key="open_total" label="未到合计" :width="unsubColWidth('open_total', 90)" align="right" resizable>
          <template #default="{ row }">{{ formatNum(row.open_total) }}</template>
        </el-table-column>
        <el-table-column column-key="unsub_total" label="本次退订" :width="unsubColWidth('unsub_total', 140)" align="center" resizable>
          <template #default="{ row }">
            <el-input-number
              v-if="!row.has_sizes"
              v-model="row.total_qty"
              :min="0"
              :max="Number(row.open_total)"
              :step="0.01"
              size="small"
            />
            <span v-else>{{ formatNum(unsubSizeSum(row)) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="unsubVisible = false">取消</el-button>
        <el-button v-permission="'btn.purchase_orders.write'" type="primary" :loading="unsubSaving" @click="doUnsubscribe">确认退订</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recvVisible" title="到货登记" :width="recvSizeColumns.length ? '1100px' : '920px'" destroy-on-close>
      <el-form label-width="88px" style="margin-bottom: 8px">
        <el-form-item label="送货单号">
          <el-input v-model="deliveryNoteNo" clearable placeholder="选填" style="width: 280px" />
        </el-form-item>
      </el-form>

      <div v-if="recvBatches.length" class="recv-batch">
        <el-table
          ref="recvBatchesTableRef"
          :data="recvBatches"
          border
          size="small"
          style="width: 100%"
          :span-method="recvSpanMethod"
          @header-dragend="onHeaderDragend3"
        >
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
          <el-table-column v-if="recvSizeColumns.length" label="码数" align="center">
            <el-table-column
              v-for="size in recvSizeColumns"
              :key="size"
              :column-key="`rcv_${size}`"
              :label="size"
              :width="colWidth3(`rcv_${size}`, 108)"
              align="center"
              resizable
            >
              <template #default="{ row }">
                <div v-if="row.has_sizes && row.size_open[size] != null" class="qty-stack loss-size-cell">
                  <div>未收 {{ formatNum(row.size_open[size]) }}</div>
                  <el-input-number
                    v-model="row.size_qty[size]"
                    :min="0"
                    :step="0.01"
                    :controls="false"
                    size="small"
                    class="qty-input"
                  />
                </div>
                <span v-else-if="row.has_sizes || size === recvSizeColumns[0]" class="muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column column-key="ordered_total" label="总数" :width="colWidth3('ordered_total', 72)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.ordered_total) }}</template>
          </el-table-column>
          <el-table-column column-key="unreceived_total" label="未收合计" :width="colWidth3('unreceived_total', 90)" align="right" resizable>
            <template #default="{ row }">{{ formatNum(row.open_total) }}</template>
          </el-table-column>
          <el-table-column column-key="recv_total" label="本次到货" :width="colWidth3('recv_total', 140)" align="center" resizable>
            <template #default="{ row }">
              <el-input-number v-if="!row.has_sizes" v-model="row.total_qty" :min="0" :step="0.01" size="small" />
              <span v-else>{{ formatNum(recvSizeSum(row)) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="recvVisible = false">取消</el-button>
        <el-button v-permission="'btn.purchase_orders.write'" type="primary" @click="doReceive">确认到货</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled } from '@element-plus/icons-vue'
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
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1 } = useTableColWidths(
  'po-detail-summary',
  detailSummaryTableRef,
  { flexKey: 'supplier_product_name', flexDefaultMin: 120, fitToContainer: true },
)
const recvBatchesTableRef = ref()
const {
  colWidth: colWidth3,
  onHeaderDragend: onHeaderDragend3,
  relayoutTable: relayoutRecvBatchesTable,
} = useTableColWidths(
  'po-recv-batches',
  recvBatchesTableRef,
  { flexKey: 'supplier_product_name', flexDefaultMin: 120, fitToContainer: true },
)
const unsubTableRef = ref()
const {
  colWidth: unsubColWidth,
  onHeaderDragend: onUnsubHeaderDragend,
  relayoutTable: relayoutUnsubTable,
} = useTableColWidths(
  'po-unsubscribe',
  unsubTableRef,
  { flexKey: 'supplier_product_name', flexDefaultMin: 120, fitToContainer: true },
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
const canPlacePo = computed(() => auth.hasPermission('btn.purchase_orders.write'))

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const status = ref('draft')
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
  { value: 'draft', label: '未反馈', tone: 'tone-pending-production' },
  { value: 'ordered', label: '已反馈', tone: 'tone-in-progress' },
  { value: 'partial_received', label: '部分到货', tone: 'tone-partial' },
  { value: 'received', label: '已到齐', tone: 'tone-completed' },
  { value: 'cancelled', label: '已取消', tone: 'tone-cancelled' },
] as const
const keyword = ref('')
const partnerId = ref<number>()
const supplierProductId = ref<number>()
const suppliers = ref<any[]>([])
const materials = ref<any[]>([])
const materialQuery = ref('')
const shownMaterials = computed(() => {
  const keyword = materialQuery.value.trim().toLowerCase()
  if (!keyword) return materials.value
  return materials.value.filter((item) =>
    [item.product_code, item.name, item.category_name].some((part) =>
      String(part || '').toLowerCase().includes(keyword),
    ),
  )
})
const masterSizes = ref<any[]>([])
const orderedRange = ref<string[] | null>(null)
const expectedUnreceived = ref(false)
const expectedUnreceivedCount = ref(0)
const detailVisible = ref(false)
const detail = ref<any>(null)
const submitVisible = ref(false)
const submitDraft = ref<any>(null)
const submitPriceDrafts = ref<Record<string, number>>({})
const detailPriceDrafts = ref<Record<string, number>>({})
const submitBlockMessage = ref('')
const submitLoading = ref(false)
const lossVisible = ref(false)
const lossPo = ref<any>(null)
const lossRows = ref<any[]>([])
const lossSaving = ref(false)
const lossSizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const row of lossRows.value) {
    for (const [size, sort] of Object.entries(row.size_sort || {}) as [string, number][]) {
      if (!order.has(size)) order.set(size, Number(sort || 0))
    }
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})
const lossTableHost = ref<HTMLElement | null>(null)
const lossHostWidth = ref(0)
let lossHostObserver: ResizeObserver | null = null

function measureLossTable() {
  const width = lossTableHost.value?.clientWidth || 0
  if (width > 0) lossHostWidth.value = width
}

watch(lossVisible, async (open) => {
  lossHostObserver?.disconnect()
  lossHostObserver = null
  if (!open) return
  await nextTick()
  measureLossTable()
  const host = lossTableHost.value
  if (!host || typeof ResizeObserver === 'undefined') return
  lossHostObserver = new ResizeObserver(() => measureLossTable())
  lossHostObserver.observe(host)
})

onUnmounted(() => lossHostObserver?.disconnect())

const lossSizeColWidth = computed(() => {
  const count = lossSizeColumns.value.length
  if (!count) return 72
  const fixed = 108 + 128 + 64 + 52 + 96
  const room = Math.max(count, (lossHostWidth.value || 1000) - fixed - 16)
  return Math.max(1, Math.floor(room / count))
})
const recvVisible = ref(false)
const deliveryNoteNo = ref('')
const recvLines = ref<any[]>([])
const recvBatches = ref<any[]>([])
const recvPoId = ref(0)
const unsubVisible = ref(false)
const unsubLines = ref<any[]>([])
const unsubBatches = ref<any[]>([])
const unsubPoId = ref(0)
const unsubSaving = ref(false)

function lineHasProductionOrder(ln: any) {
  return Boolean(ln?.order_no || ln?.header_id || ln?.order_id)
}

const detailHasProductionOrder = computed(() =>
  (detail.value?.lines || []).some((ln: any) => lineHasProductionOrder(ln)),
)
const detailOrderLines = computed(() =>
  (detail.value?.lines || []).filter((ln: any) => lineHasProductionOrder(ln)),
)
const detailSummaryRows = computed(() => buildDetailSummaryRows(detail.value))
const detailSummarySizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const row of detailSummaryRows.value) {
    for (const [size, sort] of Object.entries(row.size_sort || {}) as [string, number][]) {
      if (!order.has(size) || Number(sort) < Number(order.get(size))) order.set(size, Number(sort || 0))
    }
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})

const dueSoonCount = computed(() => rows.value.filter((r) => r.delivery_alert === 'due_soon').length)

/** 采购单主信息 rowspan + 汇总物料行拆分 */
const displayRows = computed(() => {
  const out: any[] = []
  rows.value.forEach((po, poIndex) => {
    const lines = Array.isArray(po.summary_lines) && po.summary_lines.length ? po.summary_lines : [null]
    const count = lines.length
    lines.forEach((ln: any, i: number) => {
      const parts = materialSizeParts(po, ln)
      const sizeQty: Record<string, number> = {}
      const sizeLoss: Record<string, number> = {}
      for (const part of parts) {
        sizeQty[part.size] = part.qty
        sizeLoss[part.size] = part.loss
      }
      out.push({
        ...po,
        _key: `${po.id}-${i}`,
        _lineIndex: i,
        _lineCount: count,
        _poIndex: poIndex,
        _line: ln,
        _hasSizes: parts.length > 0,
        _sizeQty: sizeQty,
        _sizeLoss: sizeLoss,
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
  'summary_total_amount',
  'status',
  'actions',
])

const listSizeColumns = computed(() => {
  const active = masterSizes.value
    .filter((size) => size.is_active !== false && String(size.size_value || '').trim())
    .slice()
    .sort(
      (a, b) =>
        Number(a.sort_order || 0) - Number(b.sort_order || 0) ||
        String(a.size_value).localeCompare(String(b.size_value), 'zh-CN', { numeric: true }),
    )
  const labels = active.map((size) => String(size.size_value).trim())
  const known = new Set(labels)
  const extras: { size: string; sort: number }[] = []
  for (const po of rows.value) {
    for (const ln of po.lines || []) {
      const size = sizeColumnLabel(ln)
      if (!size || known.has(size)) continue
      known.add(size)
      extras.push({ size, sort: Number(ln.size_sort_order || 0) })
    }
  }
  extras.sort(
    (a, b) => a.sort - b.sort || a.size.localeCompare(b.size, 'zh-CN', { numeric: true }),
  )
  return [...labels, ...extras.map((item) => item.size)]
})

function groupSpanMethod({ row, column }: { row: any; column: any }) {
  const key = String(column.property || column.columnKey || '')
  if (key.startsWith('sz_') && listSizeColumns.value.length && !row._hasSizes) {
    if (key.slice(3) !== listSizeColumns.value[0]) return [0, 0]
    return [1, listSizeColumns.value.length]
  }
  if (!PO_MERGE_KEYS.has(key)) return [1, 1]
  if (row._lineIndex === 0) return [row._lineCount || 1, 1]
  return [0, 0]
}

function onRowCommand(row: any, command: string) {
  if (command === 'export') exportDoc(row)
  else if (command === 'print') printPo(row)
  else if (command === 'loss') openLoss(row)
  else if (command === 'submit') openSubmit(row)
  else if (command === 'receive') openReceive(row)
  else if (command === 'unsubscribe') openUnsubscribe(row)
  else if (command === 'cancel') cancel(row)
}

function groupRowClassName({ row }: { row: any }) {
  return (row._poIndex ?? 0) % 2 === 0 ? 'po-group-even' : 'po-group-odd'
}

const PO_STATUS: Record<string, string> = {
  draft: '未反馈',
  ordered: '已反馈',
  shipped: '已反馈', // 历史状态，界面不再单独展示「已发货」
  partial_received: '部分到货',
  received: '已到齐',
  cancelled: '已取消',
}

function canEditLoss(row: any) {
  return row?.status === 'draft' && canPlacePo.value
}

function sizeColumnLabel(ln: any) {
  const sizeId = ln?.size_id != null ? Number(ln.size_id) : null
  if (sizeId) {
    const master = masterSizes.value.find((size) => Number(size.id) === sizeId)
    const value = String(master?.size_value || '').trim()
    if (value) return value
  }
  return String(ln?.size_value || '').trim()
}

function materialSizeParts(po: any, line: any) {
  const productId = line?.supplier_product_id
  if (!po || productId == null) return []
  const map = new Map<string, { size: string; qty: number; loss: number; sort: number }>()
  for (const ln of po.lines || []) {
    if (Number(ln.supplier_product_id) !== Number(productId)) continue
    const size = sizeColumnLabel(ln)
    if (!size) continue
    const current = map.get(size) || { size, qty: 0, loss: 0, sort: Number(ln.size_sort_order || 0) }
    current.qty = Math.round((current.qty + Number(ln.qty || 0)) * 10000) / 10000
    current.loss = Math.round((current.loss + Number(ln.loss_qty || 0)) * 10000) / 10000
    map.set(size, current)
  }
  return [...map.values()]
}

function listBaseQty(row: any, qty: unknown, loss: unknown) {
  const total = Number(qty || 0)
  const extra = Number(loss || 0)
  if (row?.status && row.status !== 'draft' && extra > 0 && total >= extra) {
    return Math.round((total - extra) * 10000) / 10000
  }
  return total
}

function materialQtyText(po: any, line: any) {
  const parts = materialSizeParts(po, line)
  if (!parts.length) return line ? formatNum(listBaseQty(po, line.qty, line.loss_qty)) : '—'
  return parts.map((part) => `${part.size} ${formatNum(listBaseQty(po, part.qty, part.loss))}`).join('  ')
}

function materialLossText(po: any, line: any) {
  const parts = materialSizeParts(po, line).filter((part) => Number(part.loss))
  if (!parts.length) return line && Number(line.loss_qty) ? formatNum(line.loss_qty) : ''
  return parts.map((part) => `${part.size} ${formatNum(part.loss)}`).join('  ')
}

function poStatusLabel(s: string) {
  return PO_STATUS[s] || s || '—'
}

function poStatusTone(s: string) {
  if (s === 'draft') return 'is-draft'
  if (s === 'ordered' || s === 'shipped') return 'is-ordered'
  if (s === 'partial_received') return 'is-partial'
  if (s === 'received') return 'is-received'
  if (s === 'cancelled') return 'is-cancelled'
  return ''
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

function buildDetailSummaryRows(po: any) {
  if (!po) return []
  const rows = (po.summary_lines || []).map((row: any) => ({
    ...row,
    has_sizes: false,
    size_qty: {} as Record<string, number>,
    size_loss: {} as Record<string, number>,
    size_sort: {} as Record<string, number>,
  }))
  const byProduct = new Map<number, any>(rows.map((row: any) => [row.supplier_product_id, row]))
  for (const ln of po.lines || []) {
    if (!ln.size_value) continue
    const bucket = byProduct.get(ln.supplier_product_id)
    if (!bucket) continue
    const size = String(ln.size_value)
    bucket.has_sizes = true
    bucket.size_qty[size] = Math.round(((bucket.size_qty[size] || 0) + Number(ln.qty || 0)) * 10000) / 10000
    bucket.size_loss[size] = Math.round(((bucket.size_loss[size] || 0) + Number(ln.loss_qty || 0)) * 10000) / 10000
    bucket.size_sort[size] = Number(ln.size_sort_order || 0)
  }
  return rows
}

function detailSummarySpan({ row, column }: { row: any; column: any }) {
  const key = String(column.columnKey || '')
  if (!key.startsWith('dsz_') || row.has_sizes || !detailSummarySizeColumns.value.length) return [1, 1]
  if (key.slice(4) !== detailSummarySizeColumns.value[0]) return [0, 0]
  return [1, detailSummarySizeColumns.value.length]
}

async function loadSuppliers() {
  const res: any = await http.get('/partners', {
    params: { role: 'supplier', active_only: true, page_size: 200 },
  })
  suppliers.value = res.data?.items || []
}

async function loadMaterials() {
  const pageSize = 200
  const first: any = await http.get('/supplier-products', {
    params: { page_size: pageSize, sort_by: 'product_code', sort_order: 'asc' },
  })
  const items = [...(first.data?.items || [])]
  const totalCount = Number(first.data?.total || items.length)
  const pages = Math.ceil(totalCount / pageSize)
  if (pages > 1) {
    const rest: any[] = await Promise.all(
      Array.from({ length: pages - 1 }, (_, index) =>
        http.get('/supplier-products', {
          params: { page: index + 2, page_size: pageSize, sort_by: 'product_code', sort_order: 'asc' },
        }),
      ),
    )
    for (const res of rest) items.push(...(res.data?.items || []))
  }
  items.sort((a, b) =>
    String(a.product_code || '').localeCompare(String(b.product_code || ''), 'zh-CN', { numeric: true }),
  )
  materials.value = items
}

function filterMaterials(query: string) {
  materialQuery.value = query
}

function onMaterialVisible(open: boolean) {
  if (!open) materialQuery.value = ''
}

async function loadMasterSizes() {
  const res: any = await http.get('/sizes')
  masterSizes.value = res.data?.items || []
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
        supplier_product_id: supplierProductId.value || undefined,
        po_no: keyword.value.trim() || undefined,
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
  detailPriceDrafts.value = {}
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

function shownUnitPrice(row: any, drafts: Record<string, number>) {
  const key = String(row?.supplier_product_id ?? '')
  if (Object.prototype.hasOwnProperty.call(drafts, key)) return drafts[key]
  return Number(row?.unit_price || 0)
}

function priceOverText(row: any, price: number) {
  if (!priceAboveCatalog(row, price)) return ''
  return `不能高于色卡单价 ¥${formatMoney(catalogCeiling(row))}`
}

function rememberPriceDraft(drafts: { value: Record<string, number> }, row: any, price: number) {
  drafts.value = { ...drafts.value, [String(row.supplier_product_id)]: price }
}

function forgetPriceDraft(drafts: { value: Record<string, number> }, row: any) {
  const key = String(row.supplier_product_id)
  if (!Object.prototype.hasOwnProperty.call(drafts.value, key)) return
  const next = { ...drafts.value }
  delete next[key]
  drafts.value = next
}

async function onSummaryPrice(row: any, v: number) {
  if (!detail.value || detail.value.status !== 'draft') return
  if (priceAboveCatalog(row, v)) {
    rememberPriceDraft(detailPriceDrafts, row, Number(v))
    return
  }
  forgetPriceDraft(detailPriceDrafts, row)
  try {
    const res: any = await http.patch(`/purchase-orders/${detail.value.id}/summary-price`, {
      supplier_product_id: row.supplier_product_id,
      unit_price: v,
    })
    detail.value = res.data
    ElMessage.success('已按合计数量更新单价')
    load()
  } catch (e: any) {
    rememberPriceDraft(detailPriceDrafts, row, Number(v))
    ElMessage.warning(e?.response?.data?.detail || e?.message || '单价未保存')
  }
}

async function openLoss(row: any) {
  if (!row?.id) return
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  if (po.status !== 'draft') {
    ElMessage.warning('未反馈才能添加损耗')
    return
  }
  const groups = new Map<number, any>()
  for (const ln of po.lines || []) {
    const productId = ln.supplier_product_id
    let bucket = groups.get(productId)
    if (!bucket) {
      bucket = {
        supplier_product_id: productId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        color_name: ln.color_name,
        pricing_unit_name: ln.pricing_unit_name,
        qty: 0,
        loss_qty: 0,
        has_sizes: false,
        size_qty: {},
        size_loss: {},
        size_sort: {},
      }
      groups.set(productId, bucket)
    }
    bucket.qty += Number(ln.qty || 0)
    bucket.loss_qty += Number(ln.loss_qty || 0)
    if (ln.size_value) {
      const size = String(ln.size_value)
      bucket.has_sizes = true
      bucket.size_qty[size] = Math.round(((bucket.size_qty[size] || 0) + Number(ln.qty || 0)) * 10000) / 10000
      bucket.size_loss[size] = Math.round(((bucket.size_loss[size] || 0) + Number(ln.loss_qty || 0)) * 10000) / 10000
      bucket.size_sort[size] = Number(ln.size_sort_order || 0)
    }
  }
  lossRows.value = [...groups.values()].sort((a, b) =>
    String(a.supplier_product_code || '').localeCompare(String(b.supplier_product_code || ''), 'zh'),
  )
  lossPo.value = po
  lossVisible.value = true
}

function rowLossTotal(row: any) {
  return Object.values(row.size_loss || {}).reduce((sum: number, value) => sum + Number(value || 0), 0)
}

async function saveLoss() {
  if (!lossPo.value) return
  lossSaving.value = true
  try {
    let latest = lossPo.value
    for (const row of lossRows.value) {
      if (row.has_sizes) {
        for (const [size, loss] of Object.entries(row.size_loss || {})) {
          const res: any = await http.patch(`/purchase-orders/${lossPo.value.id}/summary-loss`, {
            supplier_product_id: row.supplier_product_id,
            loss_qty: Number(loss || 0),
            size_value: size,
          })
          latest = res.data
        }
        continue
      }
      const res: any = await http.patch(`/purchase-orders/${lossPo.value.id}/summary-loss`, {
        supplier_product_id: row.supplier_product_id,
        loss_qty: Number(row.loss_qty || 0),
      })
      latest = res.data
    }
    if (submitDraft.value?.id === latest.id) submitDraft.value = latest
    if (detail.value?.id === latest.id) detail.value = latest
    lossVisible.value = false
    ElMessage.success('已记下损耗，下单时会加进数量')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存损耗失败')
  } finally {
    lossSaving.value = false
  }
}

function catalogCeiling(row: any) {
  if (row?.catalog_price == null || row.catalog_price === '') return null
  const n = Number(row.catalog_price)
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null
}

function priceAboveCatalog(row: any, v: number | null | undefined) {
  const ceiling = catalogCeiling(row)
  if (ceiling == null || v == null || Number.isNaN(Number(v))) return false
  return Math.round(Number(v) * 100) / 100 > ceiling
}

async function onSubmitPrice(row: any, v: number) {
  if (!submitDraft.value) return
  if (priceAboveCatalog(row, v)) {
    rememberPriceDraft(submitPriceDrafts, row, Number(v))
    return
  }
  forgetPriceDraft(submitPriceDrafts, row)
  submitBlockMessage.value = ''
  try {
    const res: any = await http.patch(`/purchase-orders/${submitDraft.value.id}/summary-price`, {
      supplier_product_id: row.supplier_product_id,
      unit_price: v,
    })
    submitDraft.value = res.data
    if (detail.value?.id === res.data.id) detail.value = res.data
    load()
  } catch (e: any) {
    rememberPriceDraft(submitPriceDrafts, row, Number(v))
  }
}

function submitSummaryMethod({ columns, data }: { columns: any[]; data: any[] }) {
  return columns.map((col: any, i: number) => {
    if (i === 0) return '合计'
    const key = col.property || col.columnKey
    if (key === 'amount') {
      const total = data.reduce(
        (s, r) => s + purchaseQty(r.qty, r.loss_qty) * shownUnitPrice(r, submitPriceDrafts.value),
        0,
      )
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
          ? '当前为未反馈，确认仍要打印？建议核对单价后再发给供应商。'
          : '当前为未反馈，确认仍要导出？',
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
        '当前为未反馈，确认仍要打印？建议核对单价后再发给供应商。',
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

const submitSizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const line of submitDraft.value?.lines || []) {
    if (!line.size_value) continue
    const size = String(line.size_value)
    if (!order.has(size)) order.set(size, Number(line.size_sort_order || 0))
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})
const submitRows = computed(() => {
  const po = submitDraft.value
  const summaries = po?.summary_lines || []
  if (!po || !submitSizeColumns.value.length) return summaries
  const qtyByProduct = new Map<number, { qty: Record<string, number>; loss: Record<string, number> }>()
  for (const line of po.lines || []) {
    if (!line.size_value) continue
    const size = String(line.size_value)
    const bucket = qtyByProduct.get(line.supplier_product_id) || { qty: {}, loss: {} }
    bucket.qty[size] = Math.round(((bucket.qty[size] || 0) + Number(line.qty || 0)) * 10000) / 10000
    bucket.loss[size] = Math.round(((bucket.loss[size] || 0) + Number(line.loss_qty || 0)) * 10000) / 10000
    qtyByProduct.set(line.supplier_product_id, bucket)
  }
  return summaries.map((row: any) => {
    const bucket = qtyByProduct.get(row.supplier_product_id)
    return {
      ...row,
      size_qty: bucket?.qty || {},
      size_loss: bucket?.loss || {},
    }
  })
})
const submitPriceBlocked = computed(() =>
  submitRows.value.some((row: any) =>
    Boolean(priceOverText(row, shownUnitPrice(row, submitPriceDrafts.value))),
  ),
)
function purchaseQty(base: unknown, loss: unknown) {
  return Math.round((Number(base || 0) + Number(loss || 0)) * 10000) / 10000
}

function submitSizeLoss(row: any, size: string) {
  const qty = row.size_loss?.[size]
  if (qty == null || qty === '') return '0'
  return formatNum(qty)
}

async function openSubmit(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  if (po.status !== 'draft') {
    ElMessage.warning('仅未反馈状态可下单')
    return
  }
  // 交期必填，打开时不预填
  po.expected_date = null
  submitPriceDrafts.value = {}
  submitBlockMessage.value = ''
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
  if (submitPriceBlocked.value) return
  submitLoading.value = true
  try {
    await http.patch(`/purchase-orders/${submitDraft.value.id}`, {
      expected_date: expected,
      notes: submitDraft.value.notes,
    })
    await http.post(`/purchase-orders/${submitDraft.value.id}/submit`)
    ElMessage.success('已反馈')
    submitVisible.value = false
    submitDraft.value = null
    if (detailVisible.value && detail.value) {
      const res: any = await http.get(`/purchase-orders/${detail.value.id}`)
      detail.value = res.data
    }
    load()
  } catch (e: any) {
    const message = e?.response?.data?.detail || e?.message || '不能下单'
    submitBlockMessage.value = typeof message === 'string' ? message : '不能下单'
  } finally {
    submitLoading.value = false
  }
}

async function cancel(row: any) {
  await http.post(`/purchase-orders/${row.id}/cancel`)
  ElMessage.success('已取消')
  load()
}

function canUnsubscribe(row: any) {
  return ['draft', 'ordered', 'shipped', 'partial_received'].includes(String(row?.status || ''))
}

async function openUnsubscribe(row: any) {
  const res: any = await http.get(`/purchase-orders/${row.id}`)
  const po = res.data
  if (!canUnsubscribe(po)) {
    ElMessage.warning(`当前状态「${poStatusLabel(po.status)}」不可退订`)
    return
  }
  unsubPoId.value = po.id
  unsubLines.value = (po.lines || []).map((ln: any) => {
    const open = Math.max(
      0,
      Number(ln.open_qty ?? (Number(ln.qty) - Number(ln.received_qty || 0) - Number(ln.pending_iqc_qty || 0))),
    )
    return { ...ln, open_qty: open, this_qty: 0 }
  }).filter((ln: any) => Number(ln.open_qty) > 0)
  if (!unsubLines.value.length) {
    ElMessage.warning('没有可退的未到数量')
    return
  }
  const bySp = new Map<number, any>()
  for (const ln of unsubLines.value) {
    const spId = Number(ln.supplier_product_id)
    if (!bySp.has(spId)) {
      bySp.set(spId, {
        supplier_product_id: spId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        image_url: ln.image_url,
        pricing_unit_name: ln.pricing_unit_name,
        open_total: 0,
        total_qty: 0,
        has_sizes: false,
        size_open: {} as Record<string, number>,
        size_qty: {} as Record<string, number>,
        size_sort: {} as Record<string, number>,
      })
    }
    const bucket = bySp.get(spId)
    const open = Number(ln.open_qty) || 0
    bucket.open_total += open
    if (ln.size_value) {
      const size = String(ln.size_value)
      bucket.has_sizes = true
      bucket.size_open[size] = Math.round(((bucket.size_open[size] || 0) + open) * 100) / 100
      bucket.size_qty[size] = 0
      bucket.size_sort[size] = Number(ln.size_sort_order || 0)
    }
  }
  for (const bucket of bySp.values()) {
    bucket.open_total = Math.round(bucket.open_total * 100) / 100
    if (!bucket.has_sizes) bucket.total_qty = 0
  }
  unsubBatches.value = [...bySp.values()].sort((a, b) =>
    String(a.supplier_product_code || '').localeCompare(String(b.supplier_product_code || ''), 'zh'),
  )
  unsubVisible.value = true
  await nextTick()
  relayoutUnsubTable()
}

const unsubSizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const row of unsubBatches.value) {
    for (const [size, sort] of Object.entries(row.size_sort || {}) as [string, number][]) {
      if (!order.has(size) || Number(sort) < Number(order.get(size))) order.set(size, Number(sort || 0))
    }
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})

function unsubSizeSum(row: any) {
  return Math.round(
    Object.values(row.size_qty || {}).reduce((sum: number, n) => sum + Number(n || 0), 0) * 100,
  ) / 100
}

function unsubSpanMethod({ row, column }: { row: any; column: any }) {
  const key = String(column.columnKey || '')
  if (!key.startsWith('unsub_') || row.has_sizes || !unsubSizeColumns.value.length) return [1, 1]
  if (key.slice(6) !== unsubSizeColumns.value[0]) return [0, 0]
  return [1, unsubSizeColumns.value.length]
}

async function doUnsubscribe() {
  for (const line of unsubLines.value) line.this_qty = 0
  let capped = false
  for (const batch of unsubBatches.value) {
    const productLines = unsubLines.value.filter((line) => line.supplier_product_id === batch.supplier_product_id)
    if (batch.has_sizes) {
      for (const size of Object.keys(batch.size_open || {})) {
        const result = distributeRecv(
          productLines.filter((line) => String(line.size_value || '') === size),
          Number(batch.size_qty?.[size] || 0),
        )
        if (result.capped) {
          batch.size_qty[size] = result.qty
          capped = true
        }
      }
    } else {
      const result = distributeRecv(
        productLines.filter((line) => !line.size_value),
        Number(batch.total_qty || 0),
      )
      if (result.capped) {
        batch.total_qty = result.qty
        capped = true
      }
    }
  }
  if (capped) ElMessage.warning('退订数量超过未到合计，已按未到上限退订')
  const payload = unsubLines.value
    .filter((line) => Number(line.this_qty) > 0)
    .map((line) => ({ line_id: line.id, qty: line.this_qty }))
  if (!payload.length) {
    ElMessage.warning('请填写退订数量')
    return
  }
  unsubSaving.value = true
  try {
    await http.post(`/purchase-orders/${unsubPoId.value}/unsubscribe`, { lines: payload })
    ElMessage.success('已退订')
    unsubVisible.value = false
    await load()
    if (detailVisible.value && detail.value?.id === unsubPoId.value) {
      const res: any = await http.get(`/purchase-orders/${unsubPoId.value}`)
      detail.value = res.data
    }
  } finally {
    unsubSaving.value = false
  }
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
  const bySp = new Map<number, any>()
  for (const ln of recvLines.value) {
    const spId = Number(ln.supplier_product_id)
    if (!bySp.has(spId)) {
      bySp.set(spId, {
        supplier_product_id: spId,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        image_url: ln.image_url,
        pricing_unit_name: ln.pricing_unit_name,
        ordered_total: 0,
        pending_iqc_total: 0,
        open_total: 0,
        total_qty: 0,
        has_sizes: false,
        size_open: {} as Record<string, number>,
        size_qty: {} as Record<string, number>,
        size_sort: {} as Record<string, number>,
      })
    }
    const b = bySp.get(spId)
    const ordered = Number(ln.qty) || 0
    const open = Number(ln.open_qty) || 0
    b.ordered_total += ordered
    b.pending_iqc_total += Number(ln.pending_iqc_qty) || 0
    b.open_total += open
    if (ln.size_value) {
      const size = String(ln.size_value)
      b.has_sizes = true
      b.size_open[size] = Math.round(((b.size_open[size] || 0) + open) * 100) / 100
      b.size_sort[size] = Number(ln.size_sort_order || 0)
    }
  }
  for (const b of bySp.values()) {
    if (b.has_sizes) {
      for (const size of Object.keys(b.size_open)) {
        b.size_qty[size] = b.size_open[size]
      }
      b.total_qty = Math.round(Object.values(b.size_qty as Record<string, number>).reduce((sum, n) => sum + Number(n || 0), 0) * 100) / 100
    } else {
      b.total_qty = Math.round(b.open_total * 100) / 100
    }
  }
  recvBatches.value = [...bySp.values()].sort((a, b) =>
    String(a.supplier_product_code || '').localeCompare(String(b.supplier_product_code || ''), 'zh'),
  )
  recvVisible.value = true
  await nextTick()
  relayoutRecvBatchesTable()
}

const recvSizeColumns = computed(() => {
  const order = new Map<string, number>()
  for (const row of recvBatches.value) {
    for (const [size, sort] of Object.entries(row.size_sort || {}) as [string, number][]) {
      if (!order.has(size) || Number(sort) < Number(order.get(size))) order.set(size, Number(sort || 0))
    }
  }
  return [...order.entries()]
    .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0], 'zh-CN', { numeric: true }))
    .map(([size]) => size)
})

function recvSizeSum(row: any) {
  return Math.round(
    Object.values(row.size_qty || {}).reduce((sum: number, n) => sum + Number(n || 0), 0) * 100,
  ) / 100
}

function recvSpanMethod({ row, column }: { row: any; column: any }) {
  const key = String(column.columnKey || '')
  if (!key.startsWith('rcv_') || row.has_sizes || !recvSizeColumns.value.length) return [1, 1]
  if (key.slice(4) !== recvSizeColumns.value[0]) return [0, 0]
  return [1, recvSizeColumns.value.length]
}

/** 按物料、码数写回采购明细。同一码的多条明细按未收上限从前往后扣。 */
function distributeRecv(lines: any[], qty: number) {
  const rows = lines
    .map((line) => ({
      line,
      cap: Math.max(0, Math.round((Number(line.open_qty) || 0) * 100)),
    }))
    .sort((a, b) => Number(a.line.id) - Number(b.line.id))
  const capTotal = rows.reduce((sum, row) => sum + row.cap, 0)
  let remain = Math.max(0, Math.round((Number(qty) || 0) * 100))
  let applied = remain
  let capped = false
  if (remain > capTotal) {
    remain = capTotal
    applied = capTotal
    capped = true
  }
  for (const row of rows) {
    const take = Math.min(row.cap, remain)
    row.line.this_qty = Math.round(((Number(row.line.this_qty) || 0) * 100 + take)) / 100
    remain -= take
  }
  return { capped, qty: applied / 100 }
}

async function doReceive() {
  const items: { supplier_product_id: number; qty: number; size_value?: string }[] = []
  for (const batch of recvBatches.value) {
    if (batch.has_sizes) {
      for (const [size, qty] of Object.entries(batch.size_qty || {})) {
        const amount = Number(qty || 0)
        if (amount > 0) {
          items.push({
            supplier_product_id: batch.supplier_product_id,
            size_value: size,
            qty: amount,
          })
        }
      }
    } else if (Number(batch.total_qty) > 0) {
      items.push({
        supplier_product_id: batch.supplier_product_id,
        qty: Number(batch.total_qty),
      })
    }
  }
  if (!items.length) {
    ElMessage.warning('请填写本次到货数量')
    return
  }
  await http.post(`/purchase-orders/${recvPoId.value}/receive`, {
    items,
    delivery_note_no: deliveryNoteNo.value || undefined,
  })
  ElMessage.success('到货已登记，已入池并生成待结算明细')
  recvVisible.value = false
  load()
  if (detailVisible.value && detail.value?.id === recvPoId.value) {
    open({ id: recvPoId.value })
  }
}

watch(listSizeColumns, () => {
  void nextTick(() => tableRef.value?.doLayout?.())
})

watch(
  () => String(route.query.refresh || ''),
  (v, prev) => {
    if (!v || v === prev) return
    status.value = 'draft'
    keyword.value = ''
    partnerId.value = undefined
    supplierProductId.value = undefined
    orderedRange.value = null
    expectedUnreceived.value = false
    page.value = 1
    void load()
  },
)

onMounted(async () => {
  await Promise.all([loadSuppliers(), loadMaterials(), loadMasterSizes()])
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
.price-over {
  margin-top: 4px;
  color: var(--el-color-danger);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.35;
  white-space: normal;
}
.price-input--over :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.submit-price-hint {
  margin-bottom: 12px;
}
.po-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 1;
  min-width: 0;
  padding-right: 8px;
}
.po-drawer-id {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}
.po-drawer-no {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.01em;
  font-variant-numeric: tabular-nums;
  color: #111827;
}
.po-drawer-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.po-stamp,
.po-alert {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}
.po-stamp.is-draft {
  color: #b45309;
  background: #fff7ed;
}
.po-stamp.is-ordered {
  color: #1d4ed8;
  background: #eff6ff;
}
.po-stamp.is-partial {
  color: #c45c26;
  background: #fff4ec;
}
.po-stamp.is-received {
  color: #15803d;
  background: #f0fdf4;
}
.po-stamp.is-cancelled {
  color: #64748b;
  background: #f1f5f9;
}
.po-alert.is-ok {
  color: #64748b;
  background: transparent;
  padding: 0;
  font-weight: 500;
}
.po-alert.is-soon {
  color: #b45309;
  background: #fff7ed;
}
.po-alert.is-overdue {
  color: #b91c1c;
  background: #fef2f2;
}
.po-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}
.po-sheet {
  background: #fff;
  border: 1px solid #e3e8ef;
  border-radius: 12px;
  padding: 16px 18px 18px;
}
.po-sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.po-sheet-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}
.po-sheet-note {
  font-size: 12px;
  color: #8a94a6;
}
.po-identity {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
.po-kicker {
  font-size: 12px;
  color: #8a94a6;
  letter-spacing: 0.08em;
}
.po-supplier {
  margin: 2px 0 0;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
  color: #111827;
}
.po-facts {
  display: flex;
  gap: 28px;
  margin: 14px 0 0;
}
.po-facts dt {
  font-size: 12px;
  color: #8a94a6;
}
.po-facts dd {
  margin: 2px 0 0;
  font-size: 14px;
  color: #1f2937;
  font-variant-numeric: tabular-nums;
}
.po-identity-amount {
  flex-shrink: 0;
  text-align: right;
}
.po-amount {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  margin-top: 4px;
  padding-bottom: 4px;
  border-bottom: 3px double #111827;
  font-variant-numeric: tabular-nums;
}
.po-amount-yen {
  font-size: 15px;
  font-weight: 600;
  color: #64748b;
}
.po-amount-num {
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1;
  color: #111827;
}
.po-follow-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 16px;
}
.po-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.po-field-notes {
  grid-column: 1 / -1;
}
.po-field-label {
  font-size: 12px;
  color: #64748b;
}
.po-field :deep(.el-date-editor),
.po-field :deep(.el-input) {
  width: 100%;
}
.po-alloc {
  border: 1px solid #e3e8ef;
  border-radius: 8px;
  overflow: hidden;
}
.po-alloc-row {
  display: grid;
  grid-template-columns: 48px 110px minmax(0, 1.4fr) 56px minmax(0, 1fr) 72px;
  gap: 10px;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid #eef1f6;
}
.po-alloc-head {
  border-top: 0;
  background: #f7f9fc;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}
.po-alloc-image,
.po-alloc-unit,
.po-alloc-head > :nth-child(1),
.po-alloc-head > :nth-child(4) {
  text-align: center;
}
.po-alloc-head > :last-child {
  text-align: right;
}
.po-alloc-text,
.po-alloc-order {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.po-alloc-order {
  font-weight: 600;
  color: #1f2937;
}
.po-alloc-qty {
  text-align: right;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #111827;
}
@media (max-width: 800px) {
  .po-identity {
    flex-direction: column;
    align-items: flex-start;
  }
  .po-identity-amount {
    text-align: left;
  }
  .po-follow-grid {
    grid-template-columns: 1fr;
  }
  .po-drawer-head {
    flex-wrap: wrap;
  }
}
.po-status-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.submit-approve-hint {
  margin-bottom: 10px;
}
.qty-input {
  width: 100%;
}
.po-action-hit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin: 0;
  padding: 0;
  line-height: 1;
  cursor: pointer;
  vertical-align: middle;
}
.po-action-hit :deep(.el-button) {
  margin: 0;
  padding: 0;
  width: 22px;
  height: 22px;
}
.po-action-hit :deep(.el-button .el-icon) {
  margin: 0;
}
.qty-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.35;
  gap: 2px;
}
.qty-stack-loss {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.loss-size-cell {
  align-items: center;
}
.loss-hint {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.loss-dialog :deep(.el-overlay-dialog) {
  overflow-x: hidden;
}
.loss-dialog :deep(.el-dialog) {
  max-width: calc(100vw - 32px);
}
.loss-dialog.is-sized :deep(.el-dialog) {
  width: min(1100px, calc(100vw - 32px)) !important;
}
.loss-dialog :deep(.el-dialog__body) {
  overflow-x: hidden;
}
.loss-table-host {
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}
.loss-table :deep(.el-scrollbar__wrap),
.loss-table :deep(.el-table__body-wrapper),
.loss-table :deep(.el-table__header-wrapper) {
  overflow-x: hidden !important;
}
.loss-table :deep(.el-input-number) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.loss-table :deep(.el-input-number .el-input__wrapper) {
  min-width: 0;
  padding-left: 4px;
  padding-right: 4px;
}
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 4px 0 8px;
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
:deep(.po-grouped-table .el-table__body td.el-table__cell) {
  vertical-align: middle;
}
:deep(.po-grouped-table .po-group-even > td.el-table__cell) {
  background: #fff !important;
}
.unsub-hint {
  margin: 0 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
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
.po-material-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  max-width: 360px;
}
.po-material-option img,
.po-material-option-ph {
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: 4px;
  object-fit: contain;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.po-material-option-ph {
  display: block;
}
.po-material-option-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}
.po-material-option-name,
.po-material-option-cat {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.po-material-option-name {
  font-size: 13px;
  line-height: 1.3;
  color: inherit;
}
.po-material-option-cat {
  font-size: 12px;
  line-height: 1.2;
  color: var(--el-text-color-secondary);
}
</style>

<style>
.po-material-popper .el-select-dropdown__item {
  height: auto;
  line-height: 1.3;
  padding-top: 4px;
  padding-bottom: 4px;
}
/* drawer 挂到 body，外壳样式不能走 scoped */
.po-detail-drawer.el-drawer {
  --el-drawer-padding-primary: 0;
}
.po-detail-drawer .el-drawer__header {
  margin: 0;
  padding: 14px 16px 14px 20px;
  border-bottom: 1px solid #e3e8ef;
  align-items: center;
  overflow: visible;
}
.po-detail-drawer .el-drawer__body {
  padding: 0;
  background: #eef1f6;
}
.po-detail-drawer .el-drawer__title {
  flex: 1;
}
</style>
