<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">订单管理</h1>
        <p class="page-desc">订单信息合并 · 明细行内编辑 · 确认接单后待排产 · 产品视图可批量接单分析</p>
      </div>
      <div class="page-hero-stats so-status-stats">
        <button
          type="button"
          class="so-stat-chip"
          :class="{ active: !statusFilter }"
          @click="filterByStatus('')"
        >
          <span class="so-stat-label">全部</span>
          <strong class="so-stat-num">{{ statusStats.total }}</strong>
        </button>
        <button
          v-for="item in statusStatItems"
          :key="item.value"
          type="button"
          class="so-stat-chip"
          :class="[item.tone, { active: statusFilter === item.value }]"
          @click="filterByStatus(item.value)"
        >
          <span class="so-stat-label">{{ item.label }}</span>
          <strong class="so-stat-num">{{ statusStats.by_status[item.value] || 0 }}</strong>
        </button>
      </div>
    </header>
    <div class="admin-card so-admin-card">
      <div class="admin-toolbar">
        <el-input
          v-model="keyword"
          clearable
          :placeholder="viewMode === 'product' ? '工厂型号' : '订单号 / 客户'"
          style="width: 200px"
          @keyup.enter="search"
        />
        <el-select
          v-model="statusFilter"
          clearable
          placeholder="状态"
          style="width: 120px"
          @change="search"
        >
          <el-option label="待确认" value="pending_confirm" />
          <el-option label="待排产" value="pending_schedule" />
          <el-option label="已排产" value="pending_production" />
          <el-option label="生产中" value="in_progress" />
          <el-option label="已完成" value="completed" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button>
        <el-radio-group v-model="viewMode" class="view-mode" @change="onViewModeChange">
          <el-radio-button value="split">订单视图</el-radio-button>
          <el-radio-button value="production">生产进度</el-radio-button>
          <el-radio-button value="product">产品视图</el-radio-button>
        </el-radio-group>
        <el-checkbox
          v-if="viewMode === 'split'"
          v-model="showSizes"
          @change="persistShowSizesPref"
        >显示码数</el-checkbox>
        <el-button
          v-if="viewMode === 'product' && showBatchMrp"
          type="primary"
          :disabled="!selectedAnalyzableLines.length"
          :loading="mrpLoading"
          @click="batchSimulateMrp"
        >
          接单分析{{ selectedAnalyzableLines.length ? ` (${selectedAnalyzableLines.length})` : '' }}
        </el-button>
        <div class="spacer" />
        <el-button :disabled="viewMode !== 'split'" @click="openImport">导入</el-button>
        <el-button type="primary" :disabled="viewMode !== 'split'" @click="startCreate">
          新建订单
        </el-button>
      </div>

      <div ref="tableHostRef" class="so-table-host">
      <!-- 订单视图：订单信息列 rowspan 合并 + 明细同行 -->
      <template v-if="viewMode === 'split' || viewMode === 'production'">
        <el-table
          ref="groupTableRef"
          :data="displayGroupedRows"
          border
          :class="[
            'so-admin-compact-table',
            'so-grouped-table',
            { 'so-production-table': viewMode === 'production' },
          ]"
          row-key="_key"
          :max-height="tableMaxHeight"
          :span-method="groupSpanMethod"
          :row-class-name="groupRowClassName"
          @header-dragend="onHeaderDragend"
          @cell-mouse-enter="onGroupCellEnter"
          @cell-mouse-leave="onGroupCellLeave"
        >
          <el-table-column
            prop="order_no"
            label="订单号"
            :width="colWidth('order_no', 148)"
            resizable
          >
            <template #default="{ row }">
              <div class="so-order-cell">
                <el-tooltip
                  :content="String(row.order_no || '')"
                  placement="top"
                  :show-after="200"
                  :disabled="isOverflowTipDisabled(tipKey('order', row))"
                >
                  <button
                    type="button"
                    class="so-order-no-btn"
                    @mouseenter="onOverflowTipEnter(tipKey('order', row), $event)"
                    @click.stop="openOrderDetail(row.sales_order_id)"
                  >
                    {{ row.order_no || '' }}
                  </button>
                </el-tooltip>
                <el-popover
                  v-if="viewMode === 'split' && (row.order_notes || row.notes_image_url)"
                  placement="bottom-start"
                  :width="320"
                  trigger="hover"
                  :show-after="200"
                  popper-class="so-order-req-popper"
                >
                  <template #reference>
                    <span class="so-order-req" @click.stop>做货要求</span>
                  </template>
                  <div class="so-order-req-panel">
                    <el-image
                      v-if="row.brand_logo_url"
                      :src="row.brand_logo_url"
                      fit="contain"
                      class="so-order-req-logo"
                      :preview-src-list="[row.brand_logo_url]"
                      preview-teleported
                    />
                    <el-image
                      v-if="row.notes_image_url"
                      :src="row.notes_image_url"
                      fit="contain"
                      class="so-order-req-img"
                      :preview-src-list="[row.notes_image_url]"
                      preview-teleported
                    />
                    <div v-if="row.order_notes" class="so-order-req-text">{{ row.order_notes }}</div>
                  </div>
                </el-popover>
              </div>
            </template>
          </el-table-column>
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 100)"
            resizable
          >
            <template #default="{ row }">
              <el-tooltip
                :content="String(row.customer_name || '')"
                placement="top"
                :show-after="200"
                :disabled="!row.customer_name || isOverflowTipDisabled(tipKey('customer', row))"
              >
                <span
                  class="so-text-ellipsis"
                  @mouseenter="onOverflowTipEnter(tipKey('customer', row), $event)"
                >{{ row.customer_name || '' }}</span>
              </el-tooltip>
              <el-tag
                v-if="row.biz_mode === 'subcontract_in' && !isSummaryRow(row)"
                size="small"
                type="warning"
                class="so-biz-tag"
              >承接外包</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="ordered_at"
            label="下单日期"
            :width="colWidth('ordered_at', 100)"
            resizable
          >
            <template #default="{ row }">{{ row.ordered_at || '' }}</template>
          </el-table-column>
          <el-table-column
            prop="line_no"
            label="序号"
            :width="colWidth('line_no', 56)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"><span class="so-summary-label">合计</span></template>
              <template v-else-if="isRowEditing(row) && !row.sales_order_line_id">新</template>
              <template v-else-if="isRowEditing(row)"></template>
              <template v-else>{{ row.line_no || '' }}</template>
            </template>
          </el-table-column>
          <el-table-column
            prop="product_code"
            label="工厂型号"
            :width="colWidth('product_code', 110)"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-select
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.own_product_id"
                filterable
                size="small"
                placeholder="产品"
                style="width: 100%"
                @change="onInlineProductChange"
              >
                <el-option
                  v-for="p in products"
                  :key="p.id"
                  :label="p.product_code"
                  :value="p.id"
                />
              </el-select>
              <el-tooltip
                v-else-if="row.own_product_id && row.product_code"
                :content="String(row.product_code || '')"
                placement="top"
                :show-after="200"
                :disabled="isOverflowTipDisabled(tipKey('product', row))"
              >
                <span
                  class="so-text-ellipsis"
                  @mouseenter="onOverflowTipEnter(tipKey('product', row), $event)"
                >
                  <el-button
                    link
                    type="primary"
                    class="so-product-code-btn"
                    @click="openProductDetail(row.own_product_id)"
                  >
                    {{ row.product_code }}
                  </el-button>
                </span>
              </el-tooltip>
              <button
                v-else-if="row._emptyPlaceholder && row._canAddLine"
                type="button"
                class="so-add-line-quiet"
                title="增加明细行"
                @click.stop="startAddLine(row.sales_order_id)"
              >
                添加明细
              </button>
              <el-tooltip
                v-else-if="row.product_code"
                :content="String(row.product_code || '')"
                placement="top"
                :show-after="200"
                :disabled="isOverflowTipDisabled(tipKey('product', row))"
              >
                <span
                  class="so-product-code-text so-text-ellipsis"
                  @mouseenter="onOverflowTipEnter(tipKey('product', row), $event)"
                >{{ row.product_code }}</span>
              </el-tooltip>
              <span v-else></span>
            </template>
          </el-table-column>
          <el-table-column
            prop="product_image_url"
            label="图片"
            :width="colWidth('product_image_url', 72)"
            align="center"
            class-name="mat-image-col"
            header-class-name="mat-image-col"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <template v-else-if="isRowEditing(row)">
                <el-image
                  v-if="inlineLineImageUrl()"
                  :src="inlineLineImageUrl()"
                  :preview-src-list="[inlineLineImageUrl()]"
                  fit="contain"
                  class="product-thumb"
                  preview-teleported
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
              <template v-else>
                <el-image
                  v-if="rowProductImageUrl(row)"
                  :src="rowProductImageUrl(row)"
                  :preview-src-list="[rowProductImageUrl(row)]"
                  fit="contain"
                  class="product-thumb"
                  preview-teleported
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </template>
          </el-table-column>
          <el-table-column prop="color_name" label="颜色" :width="colWidth('color_name', 64)" resizable>
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-select
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.color_id"
                filterable
                size="small"
                placeholder="颜色"
                style="width: 100%"
              >
                <el-option
                  v-for="c in productColors(inlineLine.draft.own_product_id)"
                  :key="c.id"
                  :label="c.name"
                  :value="c.id"
                />
              </el-select>
              <span v-else>{{ row.color_name || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="fabric"
            label="鞋面"
            :width="colWidth('fabric', 88)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-input
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.fabric"
                size="small"
              />
              <span v-else>{{ row.fabric || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="lining"
            label="内里/垫脚"
            :width="colWidth('lining', 100)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-input
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.lining"
                size="small"
              />
              <span v-else>{{ row.lining || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="brand_name"
            label="品牌"
            :width="colWidth('brand_name', 88)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-input
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.brand_name"
                size="small"
              />
              <span v-else>{{ row.brand_name || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="customer_sku"
            label="客户型号"
            :width="colWidth('customer_sku', 96)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-input
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.customer_sku"
                size="small"
              />
              <span v-else>{{ row.customer_sku || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split' && (showSizes || !!inlineLine)"
            column-key="sizes"
            align="center"
            class-name="size-group-col"
            resizable
          >
            <template #header>
              <span class="so-sizes-header">
                码数
                <el-button
                  link
                  type="primary"
                  :icon="EditPen"
                  class="so-sizes-edit-btn"
                  title="编辑码数"
                  @click.stop="openSizesEditor"
                />
              </span>
            </template>
            <el-table-column
              v-for="s in sortedSizes"
              :key="`size-${s.id}`"
              :prop="`size_${s.id}`"
              :label="s.size_value"
              :width="colWidth(`size_${s.id}`, 40)"
              align="right"
              header-align="center"
              class-name="size-col"
              header-class-name="size-col"
              resizable
            >
              <template #default="{ row }">
                <span v-if="isSummaryRow(row)" class="muted" />
                <el-input-number
                  v-else-if="isRowEditing(row) && inlineLine"
                  :model-value="getLineSizeQty(inlineLine.draft, s.id)"
                  :min="0"
                  :controls="false"
                  size="small"
                  class="size-qty-input"
                  @update:model-value="setLineSizeQty(inlineLine.draft, s.id, $event)"
                />
                <el-tooltip
                  v-else-if="sizeProgressTip(row, s.id)"
                  :content="sizeProgressTip(row, s.id)"
                  placement="top"
                  :show-after="200"
                >
                  <span>{{ sizeQty(row, s.id) }}</span>
                </el-tooltip>
                <span v-else>{{ sizeQty(row, s.id) }}</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column
            prop="total_qty"
            label="数量"
            :width="colWidth('total_qty', 64)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <strong v-if="isSummaryRow(row)" class="so-summary-num">
                {{ row.order_total_qty || 0 }}
              </strong>
              <span v-else-if="isRowEditing(row) && inlineLine">
                {{ lineQtyTotal(inlineLine.draft) || '' }}
              </span>
              <span v-else>{{ row.total_qty || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'production'"
            prop="delivery_date"
            label="交货日期"
            :width="colWidth('production_delivery_date', 96)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <span v-if="!isSummaryRow(row)">{{ row.delivery_date || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'production'"
            column-key="production_status_w"
            label="状态"
            :width="colWidth('production_status_w', 80)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row) || row._emptyPlaceholder" />
              <el-tag v-else size="small" :type="lineStatusTagType(row)">
                {{ lineStatusLabel(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            prop="unit_price"
            label="单价"
            :width="colWidth('unit_price', 80)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <span v-else-if="isRowEditing(row) && inlineLine">
                {{ formatMoney(inlineLine.draft.unit_price) }}
              </span>
              <span v-else>{{ formatMoney(row.unit_price) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            prop="line_total"
            label="总价"
            :width="colWidth('line_total', 88)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              <strong v-if="isSummaryRow(row)" class="so-summary-num">
                {{ formatMoney(row.order_total_amount) }}
              </strong>
              <span v-else-if="isRowEditing(row) && inlineLine">
                {{ formatMoney(lineTotalAmount(inlineLine.draft)) }}
              </span>
              <span v-else>{{ displayLineTotal(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            prop="delivery_date"
            label="交货日期"
            :width="colWidth('delivery_date', 100)"
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-date-picker
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.delivery_date"
                type="date"
                value-format="YYYY-MM-DD"
                size="small"
                placeholder=""
                :clearable="false"
                style="width: 100%"
              />
              <span v-else>{{ row.delivery_date || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            prop="notes"
            label="备注"
            :width="colWidth('notes', 64)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)"></template>
              <el-input
                v-else-if="isRowEditing(row) && inlineLine"
                v-model="inlineLine.draft.notes"
                size="small"
              />
              <el-tooltip
                v-else-if="row.notes"
                :content="String(row.notes)"
                placement="top"
                :show-after="200"
                :disabled="isOverflowTipDisabled(tipKey('notes', row))"
              >
                <span
                  class="notes-cell"
                  @mouseenter="onOverflowTipEnter(tipKey('notes', row), $event)"
                >{{ row.notes }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'production'"
            column-key="material_status"
            label="采购"
            :width="colWidth('material_status', 88)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <el-tag
                v-if="!isSummaryRow(row) && row.material_status"
                size="small"
                :type="materialStatusTagType(row)"
              >{{ materialStatusText(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'production'"
            v-for="process in productionProcessColumns"
            :key="`process-${process.key}`"
            :column-key="`process-${process.key}`"
            :label="process.name"
            :width="colWidth(`process-${process.key}`, 96)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <span v-if="!isSummaryRow(row)">{{ processProgressText(row, process.key) }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'production'"
            prop="shipped_qty"
            label="已出货"
            :width="colWidth('shipped_qty', 88)"
            align="right"
            resizable
          >
            <template #default="{ row }">
              {{ isSummaryRow(row) ? row.order_shipped_qty || 0 : row.shipped_qty || 0 }}
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            column-key="status_w"
            label="状态"
            :width="colWidth('status_w', 80)"
            align="center"
            resizable
          >
            <template #default="{ row }">
              <template
                v-if="isSummaryRow(row) || isRowEditing(row) || row._emptyPlaceholder"
              />
              <el-tag
                v-else-if="!canGoSchedule(row)"
                size="small"
                :type="lineStatusTagType(row)"
              >
                {{ lineStatusLabel(row) }}
              </el-tag>
              <button
                v-else
                type="button"
                class="so-status-link"
                @click.stop="goScheduleForRow(row)"
              >
                <el-tag size="small" :type="lineStatusTagType(row)">
                  {{ lineStatusLabel(row) }}
                </el-tag>
              </button>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            column-key="fulfill_progress"
            label="进度"
            :width="colWidth('fulfill_progress', 108)"
            resizable
          >
            <template #header>
              <el-tooltip content="产=已产 · 出=已出 / 需求；未出货不显示出货数；点击下钻" placement="top">
                <span>进度</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)">
                <el-tooltip
                  v-if="row.order_total_qty"
                  :content="progressHoverTip({
                    total_qty: row.order_total_qty,
                    produced_qty: row.order_produced_qty,
                    shipped_qty: row.order_shipped_qty,
                    allocated_qty: row.order_allocated_qty,
                    wip_qty: row.order_wip_qty,
                  })"
                  placement="top"
                  :show-after="300"
                >
                  <button
                    type="button"
                    class="so-progress-cell so-progress-cell--summary"
                    @click.stop="openProgressDrawer(row)"
                  >
                    <span class="so-progress-main">{{
                      progressCompactText(
                        row.order_produced_qty,
                        row.order_shipped_qty,
                        row.order_total_qty,
                      )
                    }}</span>
                  </button>
                </el-tooltip>
              </template>
              <template v-else-if="isRowEditing(row) || row._emptyPlaceholder" />
              <el-tooltip
                v-else
                :content="progressHoverTip(row)"
                placement="top"
                :show-after="300"
              >
                <button
                  type="button"
                  class="so-progress-cell"
                  @click.stop="openProgressDrawer(row)"
                >
                  <span class="so-progress-main">{{
                    progressCompactText(row.produced_qty, row.shipped_qty, row.total_qty)
                  }}</span>
                </button>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column
            v-if="viewMode === 'split'"
            column-key="actions"
            label="操作"
            width="148"
            align="center"
            class-name="so-actions-col"
            header-class-name="so-actions-col"
            :resizable="false"
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row) || row._emptyPlaceholder" />
              <div v-else-if="isRowEditing(row)" class="so-actions">
                <el-tooltip content="保存" placement="top" :show-after="200">
                  <span class="so-action-hit">
                    <el-button
                      link
                      type="primary"
                      :icon="Check"
                      :loading="saving"
                      @click="saveInlineLine"
                    />
                  </span>
                </el-tooltip>
                <el-tooltip content="取消" placement="top" :show-after="200">
                  <span class="so-action-hit">
                    <el-button link :icon="Close" @click="cancelInlineLine" />
                  </span>
                </el-tooltip>
              </div>
              <div v-else class="so-actions">
                <el-tooltip
                  v-if="canEditLine(row)"
                  content="编辑"
                  placement="top"
                  :show-after="200"
                >
                  <span class="so-action-hit">
                    <el-button
                      link
                      type="primary"
                      :icon="EditPen"
                      @click="startEditLine(row)"
                    />
                  </span>
                </el-tooltip>
                <el-tooltip
                  v-if="row._canAddLine"
                  content="在上方加一行"
                  placement="top"
                  :show-after="200"
                >
                  <span class="so-action-hit">
                    <el-button
                      link
                      type="primary"
                      :icon="Plus"
                      @click.stop="startAddLine(row.sales_order_id, row.sales_order_line_id)"
                    />
                  </span>
                </el-tooltip>
                <el-button
                  v-if="canGoSchedule(row)"
                  link
                  type="primary"
                  @click.stop="goScheduleForRow(row)"
                >
                  去排产
                </el-button>
                <el-dropdown
                  v-if="hasLineMoreActions(row)"
                  trigger="click"
                  @command="(cmd: string) => onLineMore(row, cmd)"
                >
                  <span class="so-action-hit">
                    <el-button link type="primary" :icon="MoreFilled" />
                  </span>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-if="canSimulateMrp(row)" command="mrp">
                        接单分析
                      </el-dropdown-item>
                      <el-dropdown-item v-if="canDemandShortage(row)" command="demand">
                        看要采的料
                      </el-dropdown-item>
                      <el-dropdown-item
                        v-if="row.execution_header_id || row.production_order_id"
                        command="production"
                      >
                        查生产单
                      </el-dropdown-item>
                      <el-dropdown-item
                        v-if="canDeleteLine(row)"
                        command="delete"
                        divided
                        style="color: var(--el-color-danger)"
                      >
                        删除
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 产品视图 -->
      <el-table
        v-else-if="viewMode === 'product'"
        ref="productTableRef"
        :data="productRows"
        border
        class="so-admin-compact-table"
        row-key="_key"
        :max-height="tableMaxHeight"
        :row-class-name="productRowClassName"
        @selection-change="onProductSelectionChange"
        @header-dragend="onHeaderDragend1"
      >
        <el-table-column
          type="selection"
          :width="colWidth1('selection', 48)"
          align="center"
          :selectable="canSelectLine"
        />
        <el-table-column
          prop="line_no"
          label="序号"
          :width="colWidth1('line_no', 56)"
          align="center"
          resizable
        >
          <template #default="{ row }">{{ row.line_no || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="product_code"
          label="工厂型号"
          :width="colWidth1('product_code', 105)"
          resizable
        >
          <template #default="{ row }">
            <el-tooltip
              v-if="row.own_product_id && row.product_code"
              :content="String(row.product_code || '')"
              placement="top"
              :show-after="200"
              :disabled="isOverflowTipDisabled(tipKey('product', row))"
            >
              <span
                class="so-text-ellipsis"
                @mouseenter="onOverflowTipEnter(tipKey('product', row), $event)"
              >
                <el-button
                  link
                  type="primary"
                  class="so-product-code-btn"
                  @click="openProductDetail(row.own_product_id)"
                >
                  {{ row.product_code }}
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip
              v-else-if="row.product_code"
              :content="String(row.product_code || '')"
              placement="top"
              :show-after="200"
              :disabled="isOverflowTipDisabled(tipKey('product', row))"
            >
              <span
                class="so-product-code-text so-text-ellipsis"
                @mouseenter="onOverflowTipEnter(tipKey('product', row), $event)"
              >{{ row.product_code }}</span>
            </el-tooltip>
            <span v-else></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="product_image_url"
          label="图片"
          :width="colWidth1('product_image_url', 72)"
          align="center"
          class-name="mat-image-col"
          header-class-name="mat-image-col"
          resizable
        >
          <template #default="{ row }">
            <el-image
              v-if="rowProductImageUrl(row)"
              :src="rowProductImageUrl(row)"
              :preview-src-list="[rowProductImageUrl(row)]"
              fit="contain"
              class="product-thumb"
              preview-teleported
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column prop="color_name" label="颜色" :width="colWidth1('color_name', 64)" resizable>
          <template #default="{ row }">{{ row.color_name || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="fabric"
          label="鞋面"
          :width="colWidth1('fabric', 88)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.fabric || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="lining"
          label="内里/垫脚"
          :width="colWidth1('lining', 100)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.lining || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="brand_name"
          label="品牌"
          :width="colWidth1('brand_name', 88)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.brand_name || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="customer_sku"
          label="客户型号"
          :width="colWidth1('customer_sku', 96)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.customer_sku || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="order_no"
          label="订单号"
          :width="colWidth1('order_no', 120)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="customer_name"
          label="客户"
          :width="colWidth1('customer_name', 90)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          v-if="showSizes"
          column-key="sizes"
          align="center"
          class-name="size-group-col"
          resizable
        >
          <template #header>
            <span class="so-sizes-header">
              码数
              <el-button
                link
                type="primary"
                :icon="EditPen"
                class="so-sizes-edit-btn"
                title="编辑码数"
                @click.stop="openSizesEditor"
              />
            </span>
          </template>
          <el-table-column
            v-for="s in sortedSizes"
            :key="`size-${s.id}`"
            :prop="`size_${s.id}`"
            :label="s.size_value"
            :width="colWidth1(`size_${s.id}`, 36)"
            align="right"
            header-align="center"
            class-name="size-col"
            header-class-name="size-col"
            resizable
          >
            <template #default="{ row }">
              <el-tooltip
                v-if="sizeProgressTip(row, s.id)"
                :content="sizeProgressTip(row, s.id)"
                placement="top"
                :show-after="200"
              >
                <span>{{ sizeQty(row, s.id) }}</span>
              </el-tooltip>
              <span v-else>{{ sizeQty(row, s.id) }}</span>
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column
          prop="total_qty"
          label="数量"
          :width="colWidth1('total_qty', 64)"
          align="right"
          resizable
        />
        <el-table-column
          prop="unit_price"
          label="单价"
          :width="colWidth1('unit_price', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column
          prop="line_total"
          label="总价"
          :width="colWidth1('line_total', 88)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ displayLineTotal(row) }}</template>
        </el-table-column>
        <el-table-column
          prop="delivery_date"
          label="交货日期"
          :width="colWidth1('delivery_date', 100)"
          resizable
        >
          <template #default="{ row }">{{ row.delivery_date || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="notes"
          label="备注"
          :width="colWidth1('notes', 64)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">
            <el-tooltip
              v-if="row.notes"
              :content="String(row.notes)"
              placement="top"
              :show-after="200"
              :disabled="isOverflowTipDisabled(tipKey('notes', row))"
            >
              <span
                class="notes-cell"
                @mouseenter="onOverflowTipEnter(tipKey('notes', row), $event)"
              >{{ row.notes }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column
          column-key="status_w"
          label="状态"
          :width="colWidth1('status_w', 80)"
          align="center"
          fixed="right"
          resizable
        >
          <template #default="{ row }">
            <button
              v-if="canGoSchedule(row)"
              type="button"
              class="so-status-link"
              @click.stop="goScheduleForRow(row)"
            >
              <el-tag size="small" :type="lineStatusTagType(row)">
                {{ lineStatusLabel(row) }}
              </el-tag>
            </button>
            <el-tag v-else size="small" :type="lineStatusTagType(row)">
              {{ lineStatusLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          column-key="fulfill_progress"
          label="进度"
          :width="colWidth1('fulfill_progress', 108)"
          fixed="right"
          resizable
        >
          <template #header>
            <el-tooltip content="产=已产 · 出=已出 / 需求；未出货不显示出货数；点击下钻" placement="top">
              <span>进度</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-tooltip :content="progressHoverTip(row)" placement="top" :show-after="300">
              <button
                type="button"
                class="so-progress-cell"
                @click.stop="openProgressDrawer(row)"
              >
                <span class="so-progress-main">{{
                  progressCompactText(row.produced_qty, row.shipped_qty, row.total_qty)
                }}</span>
              </button>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column
          column-key="actions"
          label="操作"
          width="120"
          align="center"
          fixed="right"
          :resizable="false"
        >
          <template #default="{ row }">
            <div class="so-actions">
              <el-button
                v-if="canGoSchedule(row)"
                link
                type="primary"
                @click.stop="goScheduleForRow(row)"
              >
                去排产
              </el-button>
            <el-dropdown
              v-if="hasLineMoreActions(row)"
              trigger="click"
              @command="(cmd: string) => onLineMore(row, cmd)"
            >
              <el-button link type="primary" :icon="MoreFilled" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="canSimulateMrp(row)" command="mrp">
                    接单分析
                  </el-dropdown-item>
                  <el-dropdown-item v-if="canDemandShortage(row)" command="demand">
                    看要采的料
                  </el-dropdown-item>
                  <el-dropdown-item
                    v-if="row.execution_header_id || row.production_order_id"
                    command="production"
                  >
                    查生产单
                  </el-dropdown-item>
                  <el-dropdown-item
                    v-if="canDeleteLine(row)"
                    command="delete"
                    divided
                    style="color: var(--el-color-danger)"
                  >
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <p v-if="viewMode === 'product'" class="view-hint muted">
        产品视图按工厂型号排序平铺，勾选行后可批量接单分析（物料缺口 · 利润 · 确认接单）。
      </p>

      <div class="admin-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          @current-change="load"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <!-- 订单详情 / 新建：订单级字段 -->
    <el-dialog
      v-model="headerDialogVisible"
      :title="headerDialogTitle"
      width="720px"
      destroy-on-close
      class="so-order-detail-dialog"
    >
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="headerDraft.id" label="状态">
          <el-tag size="small" :type="orderStatusTagType(headerDraft.status)">
            {{ orderStatusLabel(headerDraft.status) }}
          </el-tag>
          <span v-if="headerDraft.summaryText" class="so-detail-summary">{{
            headerDraft.summaryText
          }}</span>
        </el-form-item>
        <el-form-item label="订单号">
          <el-input
            v-model="headerDraft.order_no"
            placeholder="可空自动生成"
            clearable
            :disabled="headerReadonly"
          />
        </el-form-item>
        <el-form-item label="客户" required>
          <el-select
            v-model="headerDraft.customer_id"
            filterable
            clearable
            placeholder="选择客户"
            style="width: 100%"
            :disabled="headerReadonly"
            @change="onHeaderCustomerChange"
          >
            <el-option
              v-for="c in customers"
              :key="c.id"
              :label="c.short_name || c.name"
              :value="c.id"
            />
          </el-select>
          <el-input
            v-if="!headerDraft.customer_id && !headerReadonly"
            v-model="headerDraft.customer_name"
            placeholder="或手填客户名"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="下单日期">
          <el-date-picker
            v-model="headerDraft.ordered_at"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :clearable="false"
            style="width: 100%"
            :disabled="headerReadonly"
          />
        </el-form-item>
        <el-form-item label="业务形态">
          <el-select
            v-model="headerDraft.biz_mode"
            placeholder="业务形态"
            style="width: 100%"
            :disabled="headerReadonly"
          >
            <el-option label="自产自销" value="self_produce" />
            <el-option label="承接外包 / 来料加工" value="subcontract_in" />
          </el-select>
          <p class="so-detail-hint">
            承接外包：上家供料、我方收加工费；材料不计成本、走客供收货台。
          </p>
        </el-form-item>
        <el-form-item label="品牌 Logo">
          <div
            class="so-logo-box"
            :class="{
              'is-dragging': logoDragging,
              'is-uploading': logoUploading,
              'is-readonly': headerReadonly,
            }"
            tabindex="0"
            @dragenter.prevent="onLogoDragEnter"
            @dragover.prevent="onLogoDragOver"
            @dragleave.prevent="onLogoDragLeave"
            @drop.prevent="onLogoDrop"
            @click="onLogoZoneClick"
          >
            <el-image
              v-if="headerDraft.brand_logo_url"
              :src="headerDraft.brand_logo_url"
              fit="contain"
              class="so-logo-preview"
            />
            <div v-else class="so-logo-preview empty">
              <span>{{ logoUploading ? '上传中…' : '拖拽 / 点击上传' }}</span>
            </div>
            <div v-if="logoDragging && !headerReadonly" class="so-logo-drop-mask">松开以上传</div>
            <button
              v-if="headerDraft.brand_logo_url && !logoUploading && !headerReadonly"
              type="button"
              class="so-logo-clear-btn"
              @click.stop="headerDraft.brand_logo_url = ''"
            >
              清除
            </button>
            <input
              ref="logoFileInputRef"
              type="file"
              class="so-logo-file-input"
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onLogoFileChange"
            />
          </div>
        </el-form-item>
        <el-form-item label="做货要求">
          <el-input
            v-model="headerDraft.notes"
            type="textarea"
            :rows="4"
            placeholder="订单级工艺要求，如：必须有条码、品牌包装、烫印位置、除味后再装箱等"
            maxlength="2000"
            show-word-limit
            :disabled="headerReadonly"
          />
          <p class="so-detail-hint">整单共用；某色特例请写在明细行「备注」。</p>
        </el-form-item>
        <el-form-item label="做货要求图片">
          <div
            class="so-logo-box so-notes-img-box"
            :class="{
              'is-dragging': notesImgDragging,
              'is-uploading': notesImgUploading,
              'is-readonly': headerReadonly,
            }"
            tabindex="0"
            @dragenter.prevent="onNotesImgDragEnter"
            @dragover.prevent="onNotesImgDragOver"
            @dragleave.prevent="onNotesImgDragLeave"
            @drop.prevent="onNotesImgDrop"
            @click="onNotesImgZoneClick"
          >
            <el-image
              v-if="headerDraft.notes_image_url"
              :src="headerDraft.notes_image_url"
              fit="contain"
              class="so-logo-preview so-notes-img-preview"
            />
            <div v-else class="so-logo-preview so-notes-img-preview empty">
              <span>{{ notesImgUploading ? '上传中…' : '拖拽 / 点击上传客户发来的要求图' }}</span>
            </div>
            <div v-if="notesImgDragging && !headerReadonly" class="so-logo-drop-mask">松开以上传</div>
            <button
              v-if="headerDraft.notes_image_url && !notesImgUploading && !headerReadonly"
              type="button"
              class="so-logo-clear-btn"
              @click.stop="headerDraft.notes_image_url = ''"
            >
              清除
            </button>
            <input
              ref="notesImgFileInputRef"
              type="file"
              class="so-logo-file-input"
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onNotesImgFileChange"
            />
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="headerDialogVisible = false">{{
          headerReadonly ? '关闭' : '取消'
        }}</el-button>
        <el-button
          v-if="!headerReadonly"
          type="primary"
          :loading="headerSaving"
          @click="saveHeader"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="importVisible"
      title="导入销售订单"
      :width="importSession && !importSession.result ? '1400px' : '560px'"
      top="4vh"
      destroy-on-close
      class="so-import-dialog"
      :class="{ 'is-review': !!(importSession && !importSession.result) }"
      @closed="resetImport"
    >
      <template v-if="!importSession">
        <p class="muted so-import-lead">
          拖入客户订单 Excel（.xlsx）。解析后在本页核对，确认后再入库；匹配不清时不会自动选定。
        </p>
        <div class="so-import-file-row">
          <el-button @click="downloadImportTemplate">下载模版</el-button>
        </div>
        <div
          class="so-import-drop"
          :class="{ 'is-dragging': importDragging, 'has-file': !!importFile }"
          tabindex="0"
          @dragenter.prevent="onImportDragEnter"
          @dragover.prevent="onImportDragOver"
          @dragleave.prevent="onImportDragLeave"
          @drop.prevent="onImportDrop"
          @click="onImportZoneClick"
        >
          <template v-if="importFile">
            <div class="so-import-file-name">{{ importFile.name }}</div>
            <div class="so-import-file-meta muted">
              {{ formatImportFileSize(importFile.size) }} · 点击更换或继续拖入
            </div>
            <button type="button" class="so-import-clear-btn" @click.stop="clearImportFile">
              清除
            </button>
          </template>
          <template v-else>
            <div class="so-import-drop-title">
              {{ importDragging ? '松开以上传' : '拖拽 Excel 到此处' }}
            </div>
            <div class="muted">或点击选择 .xlsx 文件</div>
          </template>
          <input
            ref="importFileInputRef"
            type="file"
            class="so-import-file-input"
            accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            @change="onImportFileInputChange"
          />
        </div>
      </template>

      <template v-else-if="importSession.result">
        <div class="so-import-done">
          <div class="so-import-done-title">已导入 {{ importSession.result.order_no }}</div>
          <div class="muted">可关闭本窗，或继续导入下一份。</div>
        </div>
      </template>

      <template v-else>
        <div
          class="so-import-todo"
          :class="importBlockingIssues.length ? 'is-pending' : 'is-ready'"
        >
          <template v-if="importBlockingIssues.length">
            <span class="so-import-todo-label">还需处理</span>
            <span class="so-import-todo-chip">
              {{ importBlockingIssues.slice(0, 4).map((x) => x.text).join(' · ') }}
            </span>
            <span v-if="importBlockingIssues.length > 4" class="muted">
              等共 {{ importBlockingIssues.length }} 项
            </span>
          </template>
          <template v-else>
            <span class="so-import-todo-label is-ok">可确认导入</span>
            <span class="muted">请再扫一眼订单头与明细，无误后点底部确认</span>
          </template>
          <span v-if="importAttrMismatchCount" class="so-import-todo-mismatch">
            {{ importAttrMismatchCount }} 行颜色/鞋面/内里与产品档案不一致（已标红对照）
          </span>
        </div>

        <div v-if="importParseAlerts.length" class="so-import-alerts">
          <div v-for="(a, i) in importParseAlerts" :key="`a-${i}`">{{ a }}</div>
        </div>
        <div v-else-if="importSession.warnings?.length" class="so-import-warnings">
          <div v-for="(w, i) in importSession.warnings" :key="`w-${i}`">{{ w }}</div>
        </div>

        <div v-if="importDraft" class="so-import-draft">
          <el-form label-position="top" size="small" class="so-import-head-form">
            <div class="so-import-head-grid">
              <el-form-item label="订单号">
                <el-input v-model="importDraft.order_no" @change="scheduleDraftPatch" />
              </el-form-item>
              <el-form-item label="下单日期">
                <el-date-picker
                  v-model="importDraft.ordered_at"
                  type="date"
                  value-format="YYYY-MM-DD"
                  style="width: 100%"
                  @change="scheduleDraftPatch"
                />
              </el-form-item>
              <el-form-item label="出货日期">
                <el-date-picker
                  v-model="importDraft.delivery_date"
                  type="date"
                  value-format="YYYY-MM-DD"
                  style="width: 100%"
                  @change="scheduleDraftPatch"
                />
              </el-form-item>
              <el-form-item
                label="客户"
                :class="{ 'is-error': importCustomerNeedsAttention }"
                required
              >
                <el-select
                  :model-value="importDraft.customer?.customer_id ?? null"
                  clearable
                  filterable
                  placeholder="选择客户档案"
                  style="width: 100%"
                  @update:model-value="onImportCustomerId"
                >
                  <el-option
                    v-for="c in importCustomerOptions"
                    :key="c.id"
                    :label="c.name"
                    :value="c.id"
                  />
                </el-select>
                <div
                  v-if="importCustomerHint"
                  class="so-import-field-hint"
                  :class="{ 'is-warn': importCustomerNeedsAttention }"
                >
                  Excel：{{ importCustomerHint }}
                </div>
              </el-form-item>
            </div>

            <div
              class="so-import-mid-grid"
              :class="{ 'has-images': !!importSession.images?.length }"
            >
              <el-form-item label="做货要求" class="so-import-notes-item">
                <el-input
                  v-model="importDraft.notes"
                  type="textarea"
                  :rows="5"
                  resize="none"
                  @change="scheduleDraftPatch"
                />
              </el-form-item>
              <div v-if="importSession.images?.length" class="so-import-images">
                <div class="so-import-inline-label">
                  图片
                  <span class="muted">Logo / 做货要求图</span>
                </div>
                <div class="so-import-image-list">
                  <div
                    v-for="img in importSession.images"
                    :key="img.id"
                    class="so-import-image-card"
                  >
                    <el-image
                      :src="img.url"
                      fit="contain"
                      class="so-import-image-thumb"
                      :preview-src-list="[img.url]"
                    />
                    <el-select
                      :model-value="img.role || 'ignore'"
                      size="small"
                      style="width: 100%"
                      @update:model-value="(v) => onImportImageRole(img.id, v)"
                    >
                      <el-option label="不用" value="ignore" />
                      <el-option label="品牌 Logo" value="brand_logo" />
                      <el-option label="做货要求图" value="notes_image" />
                    </el-select>
                  </div>
                </div>
              </div>
            </div>
          </el-form>

          <div class="so-import-block-title">
            明细
            <span class="muted so-import-block-sub">
              {{ importDraft.lines?.length || 0 }} 行
              <template v-if="importSizeColumns.length">
                · {{ importSizeColumns.length }} 个码
              </template>
            </span>
          </div>
          <el-table
            :key="importTableKey"
            :data="importDraftLines"
            border
            size="small"
            row-key="_importKey"
            class="so-import-lines"
            :row-class-name="importLineRowClass"
          >
            <el-table-column label="#" width="44" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column label="工厂型号" min-width="140">
              <template #default="{ row }">
                <el-select
                  :model-value="row.own_product_id"
                  filterable
                  size="small"
                  placeholder="选择产品"
                  style="width: 100%"
                  @update:model-value="(v) => onImportLineProduct(row._importIndex, v)"
                >
                  <el-option
                    v-for="p in importLineProductOptions(row)"
                    :key="p.id"
                    :label="p.product_code"
                    :value="p.id"
                  />
                </el-select>
                <div
                  v-if="row.raw_product_code && row.raw_product_code !== row.product_code"
                  class="so-import-raw-code"
                >
                  Excel：{{ row.raw_product_code }}
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="brand_name" label="品牌" width="72" show-overflow-tooltip />
            <el-table-column prop="customer_sku" label="客人型号" width="80" show-overflow-tooltip />
            <el-table-column label="颜色" width="108">
              <template #default="{ row }">
                <div
                  class="so-import-attr"
                  :class="{ 'is-mismatch': importAttrMismatch(row, 'color') }"
                >
                  <div v-if="importAttrMismatch(row, 'color')">
                    <div>Excel：{{ row.color_name || '—' }}</div>
                    <div class="so-import-attr-sys">系统：{{ importAttrSystem(row, 'color') }}</div>
                  </div>
                  <div v-else>{{ row.color_name || '—' }}</div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="鞋面" width="112">
              <template #default="{ row }">
                <div
                  class="so-import-attr"
                  :class="{ 'is-mismatch': importAttrMismatch(row, 'fabric') }"
                >
                  <div v-if="importAttrMismatch(row, 'fabric')">
                    <div>Excel：{{ row.fabric || '—' }}</div>
                    <div class="so-import-attr-sys">系统：{{ importAttrSystem(row, 'fabric') }}</div>
                  </div>
                  <div v-else>{{ row.fabric || '—' }}</div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="内里/垫脚" width="112">
              <template #default="{ row }">
                <div
                  class="so-import-attr"
                  :class="{ 'is-mismatch': importAttrMismatch(row, 'lining') }"
                >
                  <div v-if="importAttrMismatch(row, 'lining')">
                    <div>Excel：{{ row.lining || '—' }}</div>
                    <div class="so-import-attr-sys">系统：{{ importAttrSystem(row, 'lining') }}</div>
                  </div>
                  <div v-else>{{ row.lining || '—' }}</div>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              v-for="sv in importSizeColumns"
              :key="`isz-${sv}`"
              :label="String(sv)"
              :prop="`_sz_${sv}`"
              width="46"
              align="center"
            >
              <template #default="{ row }">
                <span>{{ row[`_sz_${sv}`] || '' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="合计" width="52" align="right">
              <template #default="{ row }">
                {{ importLineQty(row) }}
              </template>
            </el-table-column>
            <el-table-column prop="notes" label="备注" min-width="100" show-overflow-tooltip />
          </el-table>
        </div>
      </template>

      <template #footer>
        <div class="so-import-footer">
          <div class="so-import-footer-left muted">
            <template v-if="importSession && !importSession.result && importBlockingIssues.length">
              还差 {{ importBlockingIssues.length }} 项
            </template>
          </div>
          <div class="so-import-footer-right">
            <el-button @click="importVisible = false">
              {{ importSession?.result ? '关闭' : '取消' }}
            </el-button>
            <el-button
              v-if="importSession?.result"
              type="primary"
              @click="resetImportToUpload"
            >
              继续导入
            </el-button>
            <el-button
              v-else-if="importSession"
              @click="resetImportToUpload"
            >
              重新上传
            </el-button>
            <el-button
              v-if="!importSession"
              type="primary"
              :loading="importSaving"
              :disabled="!importFile"
              @click="startImportParse"
            >
              解析并核对
            </el-button>
            <el-tooltip
              v-else-if="!importSession.result"
              :disabled="!importBlockingIssues.length"
              :content="importBlockingIssues.map((x) => x.text).join('；') || ''"
              placement="top"
            >
              <span>
                <el-button
                  type="primary"
                  :loading="importSaving"
                  :disabled="!importSession.can_confirm || !!importBlockingIssues.length"
                  @click="confirmImportSession"
                >
                  确认导入
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </div>
      </template>
    </el-dialog>

    <OwnProductDetailDialog v-model="productDetailVisible" :product-id="productDetailId" />

    <el-dialog
      v-model="sizesEditorVisible"
      title="码数设置"
      width="420px"
      destroy-on-close
      class="so-sizes-editor-dialog"
      @closed="resetSizeForm"
    >
      <div class="so-sizes-toolbar">
        <el-button type="primary" size="small" @click="startAddSize">新增码数</el-button>
      </div>
      <el-table
        :data="sizesEditorRows"
        border
        size="small"
        class="so-sizes-editor-table"
        :max-height="sizesEditorTableMaxHeight"
      >
        <el-table-column prop="size_value" label="码数" min-width="120" />
        <el-table-column prop="is_active" label="启用" width="100" align="center">
          <template #default="{ row }">
            <el-switch
              size="small"
              :model-value="row.is_active !== false"
              @change="(v) => toggleSizeActive(row, !!v)"
            />
          </template>
        </el-table-column>
      </el-table>

      <div v-if="addingSize" class="so-size-add-row">
        <el-input
          v-model="sizeForm.size_value"
          size="small"
          placeholder="码数，如 36"
          maxlength="10"
          style="width: 140px"
          @keyup.enter="saveNewSize"
        />
        <el-button type="primary" size="small" :loading="sizeSaving" @click="saveNewSize">
          添加
        </el-button>
        <el-button size="small" @click="addingSize = false">取消</el-button>
      </div>

      <template #footer>
        <el-button type="primary" @click="sizesEditorVisible = false">完成</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="mrpVisible"
      direction="rtl"
      :size="intakeDrawerSize"
      destroy-on-close
      class="intake-drawer"
      :class="{ 'intake-drawer--with-agent': agentPanelOpen }"
      @closed="resetAgentPanel"
    >
      <template #header>
        <div class="intake-drawer-header">
          <div class="intake-drawer-header-main">
            <span class="intake-drawer-title">接单分析</span>
            <span class="intake-meta">即时诊断 · 可直接确认</span>
          </div>
          <el-button
            v-if="agentEnabled && !agentPanelOpen"
            type="primary"
            plain
            size="small"
            @click="openIntakeAgent()"
          >
            问军师
          </el-button>
          <el-button
            v-else-if="agentPanelOpen"
            size="small"
            @click="closeIntakeAgent()"
          >
            收起军师
          </el-button>
        </div>
      </template>

      <div class="intake-drawer-body">
        <div class="intake-split" :class="{ 'is-solo': !agentPanelOpen }">
          <!-- 主：即时诊断 -->
          <section class="intake-pane intake-pane-left" aria-label="即时诊断">
            <div v-loading="intakeLoading && !intakeReport" class="intake-board">
              <div class="intake-sheet">
                <!-- 裁决 -->
                <header class="intake-hero" :class="`tone-${intakeVerdictTone}`">
                  <div class="intake-hero-kicker">
                    <span>即时诊断</span>
                    <span
                      v-if="intakeHyp.is_rush || intakeHyp.qty || intakeHyp.delivery_date || intakeHyp.default_daily_capacity"
                      class="intake-sim-pill"
                    >假设中</span>
                  </div>
                  <h2 class="intake-hero-title">
                    {{ intakeVerdictLabel || (intakeLoading ? '诊断中…' : '—') }}
                  </h2>
                  <p v-if="intakeReasons[0]" class="intake-hero-lead">{{ intakeReasons[0] }}</p>
                  <ul v-if="intakeReasons.length > 1" class="intake-hero-rest">
                    <li v-for="(r, i) in intakeReasons.slice(1, 3)" :key="i">{{ r }}</li>
                  </ul>
                </header>

                <!-- 假设 -->
                <div class="intake-toolbar">
                  <span class="intake-toolbar-label">假设</span>
                  <el-input-number
                    v-model="intakeHyp.qty"
                    :min="1"
                    :controls="false"
                    size="small"
                    placeholder="数量"
                    class="intake-hyp-qty"
                    @change="onIntakeHypChange"
                  />
                  <el-date-picker
                    v-model="intakeHyp.delivery_date"
                    type="date"
                    size="small"
                    value-format="YYYY-MM-DD"
                    placeholder="交期"
                    class="intake-hyp-date"
                    @change="onIntakeHypChange"
                  />
                  <el-input-number
                    v-model="intakeHyp.default_daily_capacity"
                    :min="1"
                    :controls="false"
                    size="small"
                    placeholder="日产能"
                    class="intake-hyp-cap"
                    title="假设日产能（双/天），仅本次仿真，不改排产设置"
                    @change="onIntakeHypChange"
                  />
                  <span class="intake-hyp-unit">双/天</span>
                  <el-checkbox v-model="intakeHyp.is_rush" @change="onIntakeHypChange">急单</el-checkbox>
                  <el-button
                    type="primary"
                    size="small"
                    :loading="intakeLoading"
                    class="intake-recalc-btn"
                    @click="refreshIntakeLeft()"
                  >
                    重算
                  </el-button>
                </div>

                <!-- 毛利 KPI -->
                <div v-if="analysisProfit" class="intake-kpi">
                  <div class="intake-kpi-hero">
                    <span class="intake-label">估算毛利率</span>
                    <strong
                      class="intake-kpi-xl"
                      :class="(analysisProfit.margin ?? 0) >= 0 ? 'is-pos' : 'is-neg'"
                    >
                      {{
                        analysisProfit.margin == null
                          ? '—'
                          : `${(analysisProfit.margin * 100).toFixed(1)}%`
                      }}
                    </strong>
                    <span v-if="intakeMarginPeerText" class="intake-kpi-note">{{ intakeMarginPeerText }}</span>
                  </div>
                  <div class="intake-kpi-grid">
                    <div class="intake-kpi-cell">
                      <span class="intake-label">利润</span>
                      <b :class="analysisProfit.profit >= 0 ? 'is-pos' : 'is-neg'">
                        ¥{{ formatMoney(analysisProfit.profit) }}
                      </b>
                    </div>
                    <div class="intake-kpi-cell">
                      <span class="intake-label">数量</span>
                      <b>{{ analysisProfit.qty }}</b>
                    </div>
                    <div class="intake-kpi-cell">
                      <span class="intake-label">收入</span>
                      <b>¥{{ formatMoney(analysisProfit.revenue) }}</b>
                    </div>
                    <div class="intake-kpi-cell">
                      <span class="intake-label">成本</span>
                      <b>¥{{ formatMoney(analysisProfit.cost) }}</b>
                    </div>
                  </div>
                </div>

                <!-- 风险四格 -->
                <div class="intake-status">
                  <div class="intake-status-item" :class="intakeKitSignalClass">
                    <span class="intake-label">齐套</span>
                    <strong>{{ intakeKitLabel }}</strong>
                    <em v-if="intakeMaterialEta">齐套日 {{ intakeMaterialEta }}</em>
                  </div>
                  <div class="intake-status-item" :class="intakeScheduleSignalClass">
                    <span class="intake-label">本单交期</span>
                    <strong>{{ intakeScheduleRiskLabel || '—' }}</strong>
                    <em v-if="intakeScheduleHint">{{ intakeScheduleHint }}</em>
                  </div>
                  <div class="intake-status-item" :class="intakePaySignalClass">
                    <span class="intake-label">回款</span>
                    <strong>{{ intakePayRiskLabel || '—' }}</strong>
                    <em v-if="intakePayRiskDetail">{{ intakePayRiskDetail }}</em>
                  </div>
                  <div class="intake-status-item" :class="intakeImpactSignalClass">
                    <span class="intake-label">交期冲击</span>
                    <strong>{{ intakeImpactShort }}</strong>
                    <em v-if="intakeImpactNos">{{ intakeImpactNos }}</em>
                  </div>
                </div>

                <!-- 明细区块 -->
                <div class="intake-blocks">
                  <section class="intake-block">
                    <div class="intake-block-head">
                      <h3>物料</h3>
                      <el-checkbox v-model="mrpShortagesOnly" size="small">仅缺料</el-checkbox>
                    </div>
                    <el-table
                      ref="mrpTableRef"
                      v-loading="intakeLoading || mrpLoading"
                      :data="intakeMaterialLines"
                      border
                      max-height="200"
                      size="small"
                      class="so-admin-compact-table mrp-material-table intake-mat-table"
                      :row-class-name="mrpRowClassName"
                      @header-dragend="onMrpHeaderDragend"
                    >
                      <el-table-column
                        prop="name"
                        label="名称"
                        :min-width="mrpFlexColMinWidth('name', 120)"
                        show-overflow-tooltip
                        resizable
                      />
                      <el-table-column
                        prop="required_qty"
                        label="需求"
                        :width="mrpColWidth('required_qty', 56)"
                        align="right"
                        resizable
                      >
                        <template #default="{ row }">{{ formatMrpNum(row.required_qty) }}</template>
                      </el-table-column>
                      <el-table-column
                        prop="shortage_qty"
                        label="缺口"
                        :width="mrpColWidth('shortage_qty', 56)"
                        align="right"
                        resizable
                      >
                        <template #default="{ row }">
                          <strong :class="Number(row.shortage_qty) > 0 ? 'mrp-shortage-num' : 'muted'">
                            {{ formatMrpNum(row.shortage_qty) }}
                          </strong>
                        </template>
                      </el-table-column>
                      <el-table-column
                        prop="expected_ready_date"
                        label="预计到料"
                        :width="mrpColWidth('expected_ready_date', 100)"
                        show-overflow-tooltip
                        resizable
                      >
                        <template #default="{ row }">
                          {{ row.expected_ready_date || '—' }}
                        </template>
                      </el-table-column>
                    </el-table>
                  </section>

                  <section v-if="intakeSizeCurveShow" class="intake-block">
                    <div class="intake-block-head">
                      <h3>色码曲线</h3>
                      <span class="intake-meta">{{ intakeSizeCurveMeta }}</span>
                    </div>
                    <div class="intake-curve-list">
                      <div v-for="row in intakeSizeCurveRows" :key="row.size_id" class="intake-curve-row">
                        <span class="intake-curve-size">{{ row.size_value }}</span>
                        <div class="intake-curve-bars">
                          <div class="intake-curve-track">
                            <div
                              class="intake-curve-fill is-this"
                              :style="{ width: `${Math.min(100, row.this_share_pct || 0)}%` }"
                            />
                          </div>
                          <div class="intake-curve-track">
                            <div
                              class="intake-curve-fill is-hist"
                              :style="{ width: `${Math.min(100, row.hist_share_pct || 0)}%` }"
                            />
                          </div>
                        </div>
                        <span
                          class="intake-curve-delta"
                          :class="{
                            'is-hot': Math.abs(row.delta_pp || 0) >= 12,
                            'is-pos': (row.delta_pp || 0) > 0,
                            'is-neg': (row.delta_pp || 0) < 0,
                          }"
                        >
                          {{ formatDeltaPp(row.delta_pp) }}
                        </span>
                      </div>
                      <div class="intake-curve-legend">
                        <span><i class="lg is-this" />本单</span>
                        <span><i class="lg is-hist" />历史</span>
                      </div>
                    </div>
                  </section>

                  <section v-if="intakeContentionShow" class="intake-block">
                    <div class="intake-block-head">
                      <h3>争料</h3>
                      <span class="intake-meta">{{ intakeContentionMeta }}</span>
                    </div>
                    <div class="intake-contend-list">
                      <div
                        v-for="item in intakeContentionItems"
                        :key="item.supplier_product_id"
                        class="intake-contend-item"
                        :class="{ 'is-conflict': item.conflict }"
                      >
                        <div class="intake-contend-top">
                          <strong class="intake-contend-name">{{ item.name || item.code }}</strong>
                          <span class="intake-contend-gap">缺 {{ formatMrpNum(item.shortage_qty) }}</span>
                        </div>
                        <div v-if="item.intake_sources?.length" class="intake-contend-subs">
                          <span
                            v-for="(s, i) in item.intake_sources.slice(0, 3)"
                            :key="`s-${i}`"
                            class="intake-mini-tag"
                          >
                            {{ s.order_no || s.label || '本批' }}
                            需{{ formatMrpNum(s.required_qty) }}
                          </span>
                        </div>
                        <div v-if="item.open_order_peers?.length" class="intake-contend-subs">
                          <span class="intake-meta">在制同料</span>
                          <span
                            v-for="(p, i) in item.open_order_peers.slice(0, 3)"
                            :key="`p-${i}`"
                            class="intake-mini-tag is-peer"
                          >
                            {{ p.is_rush ? '急·' : '' }}{{ p.order_no }}
                          </span>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section v-if="intakeCostDevShow" class="intake-block">
                    <div class="intake-block-head">
                      <h3>实耗偏差</h3>
                      <span class="intake-meta">成本卡 vs 出货实耗</span>
                    </div>
                    <div class="intake-cost-list">
                      <div
                        v-for="p in intakeCostDevProducts"
                        :key="p.own_product_id"
                        class="intake-cost-row"
                      >
                        <div class="intake-cost-main">
                          <strong>{{ p.product_code || `款${p.own_product_id}` }}</strong>
                          <span class="intake-meta">
                            卡 ¥{{ formatMoney(p.card_unit_cost) }}
                            · 实 ¥{{ formatMoney(p.actual_unit_cost_avg) }}
                          </span>
                        </div>
                        <span
                          class="intake-cost-delta"
                          :class="{
                            'is-hot': Number(p.delta_pct) >= 12,
                            'is-pos': Number(p.delta_pct) > 0,
                            'is-neg': Number(p.delta_pct) < 0,
                          }"
                        >
                          {{ formatDeltaPct(p.delta_pct) }}
                        </span>
                      </div>
                    </div>
                  </section>

                  <section v-if="intakeImpacts.length" class="intake-block">
                    <div class="intake-block-head">
                      <h3>冲击明细</h3>
                      <span class="intake-meta">{{ intakeImpacts.length }} 单</span>
                    </div>
                    <div class="intake-impact-rows">
                      <div v-for="(it, idx) in intakeImpacts" :key="idx" class="intake-impact-row">
                        <span class="intake-impact-no">{{ it.order_no || '—' }}</span>
                        <span v-if="it.delay_days" class="intake-impact-delay">+{{ it.delay_days }}日</span>
                        <span class="intake-impact-risk">
                          {{ it.old_risk_label || '—' }}
                          <i>→</i>
                          {{ it.new_risk_label || '—' }}
                        </span>
                      </div>
                    </div>
                  </section>
                </div>

                <!-- 建议 -->
                <footer v-if="intakeSuggestions.length" class="intake-suggest">
                  <div class="intake-suggest-head">
                    <h3>建议</h3>
                    <span class="intake-meta">规则 · 即出</span>
                  </div>
                  <ol class="intake-suggest-list">
                    <li v-for="(s, i) in intakeSuggestions" :key="i" :class="`tone-${s.tone}`">
                      {{ s.text }}
                    </li>
                  </ol>
                  <button
                    v-if="agentEnabled && !agentPanelOpen"
                    type="button"
                    class="intake-ask-link"
                    @click="openIntakeAgent()"
                  >
                    情景推演 · 问军师
                  </button>
                </footer>
              </div>
            </div>
          </section>

          <!-- 辅：军师（按需打开） -->
          <section
            v-if="agentPanelOpen"
            class="intake-pane intake-pane-right"
            aria-label="车间军师"
          >
            <header class="intake-pane-head">
              <span class="intake-pane-title">车间军师</span>
              <el-tag size="small" type="warning" effect="plain">情景追问</el-tag>
              <div class="intake-pane-head-spacer" />
              <el-button
                v-if="agentMessages.length"
                type="primary"
                link
                size="small"
                :disabled="agentStreaming"
                @click="resetIntakeAgentChat()"
              >
                换问题
              </el-button>
            </header>

            <p v-if="agentStale" class="intake-stale-banner">
              假设已变；可点下方问题基于最新左栏结论追问。
            </p>

            <div v-if="agentEnabled && !agentMessages.length" class="intake-presets">
              <p class="intake-presets-lead">左侧已有诊断。选一个追问，或自己输入：</p>
              <div class="intake-preset-chips">
                <button
                  v-for="p in intakeAgentPresets"
                  :key="p.id"
                  type="button"
                  class="intake-preset-chip"
                  :disabled="agentStreaming"
                  @click="askIntakePreset(p)"
                >
                  {{ p.label }}
                </button>
              </div>
            </div>

            <AssistantChatPanel
              v-if="agentEnabled"
              ref="intakeChatPanelRef"
              v-model="agentInput"
              class="intake-chat-panel"
              compact
              :messages="agentMessages"
              :sending="agentStreaming"
              :disabled="agentStreaming"
              placeholder="或自己追问：交期延到… / 只保急单…"
              note="基于左侧当前分析追问；不落库。"
              @send="sendIntakeFollowUp()"
              @action="sendIntakeFollowUp($event)"
            >
              <template #empty>
                <div class="intake-chat-empty muted">选择上方问题开始</div>
              </template>
            </AssistantChatPanel>

            <div v-else class="intake-agent-off muted">
              <p>{{ agentReason || '军师暂不可用' }}</p>
            </div>
          </section>
        </div>
      </div>

      <template #footer>
        <div class="intake-footer">
          <el-button
            v-if="canCancelFromAnalysis"
            type="danger"
            plain
            :loading="cancellingFromAnalysis"
            @click="cancelFromAnalysis"
          >
            取消订单{{ analysisOrderIds.length > 1 ? ` (${analysisOrderIds.length})` : '' }}
          </el-button>
          <div class="intake-footer-spacer" />
          <el-button @click="mrpVisible = false">关闭</el-button>
          <el-button
            v-if="canCreateDemandPurchase"
            type="warning"
            plain
            :loading="creatingDemandPurchase"
            @click="createDemandPurchaseFromAnalysis"
          >
            去买料
          </el-button>
          <el-button
            v-if="canConfirmFromAnalysis"
            type="primary"
            :loading="confirmingFromAnalysis"
            @click="confirmFromAnalysis"
          >
            确认接单{{ mrpRefs.length > 1 ? ` (${mrpRefs.length})` : '' }}
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-drawer
      v-model="progressVisible"
      direction="rtl"
      size="420px"
      destroy-on-close
      title="履约进度"
    >
      <template v-if="progressRow">
        <p class="so-progress-drawer-meta muted">
          {{ progressRow.order_no || '' }}
          <template v-if="progressRow.product_code"> · {{ progressRow.product_code }}</template>
          <template v-if="progressRow.color_name"> · {{ progressRow.color_name }}</template>
        </p>
        <div v-if="isSummaryRow(progressRow)" class="so-progress-drawer-sum">
          <div>需求 {{ progressRow.order_total_qty || 0 }}</div>
          <div>已产 {{ progressRow.order_produced_qty || 0 }}</div>
          <div>已出 {{ progressRow.order_shipped_qty || 0 }}</div>
          <div>已排 {{ progressRow.order_allocated_qty || 0 }}</div>
          <div v-if="Number(progressRow.order_wip_qty || 0) > 0">
            约在制 {{ progressRow.order_wip_qty || 0 }}
          </div>
        </div>
        <template v-else>
          <div class="so-progress-drawer-sum">
            <div>
              产 {{ Number(progressRow.produced_qty || 0) }}/{{ Number(progressRow.total_qty || 0) }}
            </div>
            <div>
              出 {{ Number(progressRow.shipped_qty || 0) }}/{{ Number(progressRow.total_qty || 0) }}
            </div>
            <div>排 {{ Number(progressRow.allocated_qty || 0) }}</div>
            <div v-if="Number(progressRow.wip_qty || 0) > 0">
              约在制 {{ Number(progressRow.wip_qty || 0) }}
            </div>
          </div>
          <el-table :data="progressRow.items || []" size="small" border>
            <el-table-column prop="size_value" label="码" width="56" />
            <el-table-column prop="qty" label="需求" width="56" align="right" />
            <el-table-column prop="allocated_qty" label="已排" width="56" align="right" />
            <el-table-column prop="produced_qty" label="已产" width="56" align="right" />
            <el-table-column prop="shipped_qty" label="已出" width="56" align="right" />
          </el-table>
          <div v-if="progressRow.execution_header_id || progressRow.production_order_id" class="so-progress-drawer-actions">
            <el-button type="primary" link @click="goProductionFromProgress">查生产单</el-button>
          </div>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { TableInstance } from 'element-plus'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, EditPen, MoreFilled, Plus } from '@element-plus/icons-vue'
import http from '@/api/http'
import AssistantChatPanel, {
  type AssistantChatMsg,
} from '@/components/assistant/AssistantChatPanel.vue'
import { type ChartSpec } from '@/components/assistant/AssistantChart.vue'
import OwnProductDetailDialog from '@/components/OwnProductDetailDialog.vue'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useAuthStore } from '@/stores/auth'

type LineDraft = {
  own_product_id: number | null
  color_id: number | null
  fabric: string
  lining: string
  customer_sku: string
  brand_name: string
  delivery_date: string | null
  unit_price: number | null
  notes: string
  items: { size_id: number; qty: number }[]
}

type InlineLineState = {
  salesOrderId: number
  lineId: number | null
  /** 新增时插到该明细上方；null 则追加到末尾 */
  insertBeforeLineId: number | null
  key: string
  draft: LineDraft
}

const groupTableRef = ref<TableInstance>()
const productTableRef = ref<TableInstance>()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()

/** 订单视图 hover：订单头三列 → 整单；明细列 → 单行 */
const hoverMode = ref<'order' | 'line' | null>(null)
const hoverOrderId = ref<number | null>(null)
const hoverLineKey = ref<string | null>(null)
let groupHoverLeaveTimer: ReturnType<typeof setTimeout> | null = null

const ORDER_HOVER_COLS = new Set(['order_no', 'customer_name', 'ordered_at'])

function onGroupCellEnter(row: any, column: any) {
  if (groupHoverLeaveTimer) {
    clearTimeout(groupHoverLeaveTimer)
    groupHoverLeaveTimer = null
  }
  const key = String(column?.property || column?.columnKey || '')
  if (!row?.sales_order_id) {
    clearGroupHover()
    return
  }
  if (ORDER_HOVER_COLS.has(key)) {
    hoverMode.value = 'order'
    hoverOrderId.value = row.sales_order_id
    hoverLineKey.value = null
    return
  }
  hoverMode.value = 'line'
  hoverOrderId.value = row.sales_order_id
  hoverLineKey.value = row._key
}

function onGroupCellLeave() {
  if (groupHoverLeaveTimer) clearTimeout(groupHoverLeaveTimer)
  groupHoverLeaveTimer = setTimeout(() => {
    clearGroupHover()
    groupHoverLeaveTimer = null
  }, 40)
}

function clearGroupHover() {
  hoverMode.value = null
  hoverOrderId.value = null
  hoverLineKey.value = null
}

const { colWidth, onHeaderDragend, relayoutTable } = useTableColWidths(
  'sales-orders-grouped',
  groupTableRef,
  { flexKey: 'notes', flexDefaultMin: 64, fitToContainer: true },
)
const {
  colWidth: colWidth1,
  onHeaderDragend: onHeaderDragend1,
  relayoutTable: relayoutProductTable,
} = useTableColWidths('sales-orders-product', productTableRef, {
  flexKey: 'notes',
  flexDefaultMin: 64,
  fitToContainer: true,
})
const mrpTableRef = ref<TableInstance>()
const {
  colWidth: mrpColWidth,
  flexColMinWidth: mrpFlexColMinWidth,
  onHeaderDragend: onMrpHeaderDragend,
} = useTableColWidths('sales-orders-mrp', mrpTableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 140,
})

const router = useRouter()
const rows = ref<any[]>([])
const productRows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const statusFilter = ref('')
const statusStats = ref<{ total: number; by_status: Record<string, number> }>({
  total: 0,
  by_status: {
    pending_confirm: 0,
    pending_schedule: 0,
    pending_production: 0,
    in_progress: 0,
    completed: 0,
    cancelled: 0,
  },
})
const statusStatItems = [
  { value: 'pending_confirm', label: '待确认', tone: 'tone-pending-confirm' },
  { value: 'pending_schedule', label: '待排产', tone: 'tone-pending-production' },
  { value: 'pending_production', label: '已排产', tone: 'tone-pending-production' },
  { value: 'in_progress', label: '生产中', tone: 'tone-in-progress' },
  { value: 'completed', label: '已完成', tone: 'tone-completed' },
  { value: 'cancelled', label: '已取消', tone: 'tone-cancelled' },
] as const

function filterByStatus(status: string) {
  statusFilter.value = status
  page.value = 1
  void load()
}
const viewMode = ref<'split' | 'production' | 'product'>('split')
const SHOW_SIZES_KEY = 'erp_sales_orders_show_sizes'

function readShowSizesPref(): boolean {
  try {
    return localStorage.getItem(SHOW_SIZES_KEY) !== '0'
  } catch {
    return true
  }
}

function persistShowSizesPref() {
  try {
    localStorage.setItem(SHOW_SIZES_KEY, showSizes.value ? '1' : '0')
  } catch {
    /* ignore quota / private mode */
  }
}

const showSizes = ref(readShowSizesPref())
watch(showSizes, persistShowSizesPref)
const selectedProductLines = ref<any[]>([])
const selectedAnalyzableLines = computed(() =>
  selectedProductLines.value.filter((row) => canSimulateMrp(row)),
)
const showBatchMrp = computed(
  () => !statusFilter.value || statusFilter.value === 'pending_confirm',
)
const saving = ref(false)
const headerSaving = ref(false)
const customers = ref<any[]>([])
const products = ref<any[]>([])
const colors = ref<any[]>([])
const sizes = ref<any[]>([])

const headerDialogVisible = ref(false)
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importSaving = ref(false)
const importSession = ref<any>(null)
const importFileInputRef = ref<HTMLInputElement | null>(null)
const importDragging = ref(false)
let importDragDepth = 0
let importDraftPatchTimer: ReturnType<typeof setTimeout> | null = null
const importDraft = computed(() => importSession.value?.draft || null)

const importCustomerHint = computed(() => {
  const c = importDraft.value?.customer || {}
  return String(c.suggested_name || c.hint || '').trim()
})

const importCustomerNeedsAttention = computed(() => {
  const c = importDraft.value?.customer || {}
  return !c.customer_id
})

const importCustomerOptions = computed(() => {
  const map = new Map<number, { id: number; name: string }>()
  for (const c of importDraft.value?.customer?.candidates || []) {
    if (c?.id != null) map.set(c.id, { id: c.id, name: c.name })
  }
  for (const c of customers.value) {
    if (c?.id != null && !map.has(c.id)) {
      map.set(c.id, { id: c.id, name: c.short_name || c.name })
    }
  }
  return [...map.values()]
})

const importParseAlerts = computed(() => {
  const out: string[] = []
  if (importSession.value?.parse_error) out.push(String(importSession.value.parse_error))
  for (const q of importSession.value?.clarifications || []) {
    if (q?.type === 'parse' || q?.type === 'mapping') {
      const text = String(q.question || '').trim()
      if (text && !out.includes(text)) out.push(text)
    }
  }
  return out
})

const importBlockingIssues = computed(() => {
  const issues: { key: string; text: string }[] = []
  if (!importSession.value || importSession.value.result) return issues
  for (const a of importParseAlerts.value) {
    issues.push({ key: `parse-${issues.length}`, text: a.slice(0, 36) + (a.length > 36 ? '…' : '') })
  }
  const draft = importDraft.value
  if (!draft) return issues
  if (!draft.customer?.customer_id) {
    issues.push({ key: 'customer', text: '选择客户' })
  }
  for (const [i, ln] of (draft.lines || []).entries()) {
    if (!ln?.own_product_id || ln.product_status !== 'matched') {
      const code = ln?.raw_product_code || ln?.product_code || `${i + 1}`
      issues.push({ key: `line-${i}`, text: `第${i + 1}行「${code}」` })
    }
  }
  return issues
})

const importSizeColumns = computed(() => {
  const set = new Set<string>()
  for (const ln of importDraft.value?.lines || []) {
    for (const it of ln?.items || []) {
      const sv = String(it?.size_value || '').trim()
      if (sv) set.add(sv)
    }
  }
  return [...set].sort((a, b) => {
    const na = Number(a)
    const nb = Number(b)
    if (Number.isFinite(na) && Number.isFinite(nb) && String(na) === a && String(nb) === b) {
      return na - nb
    }
    return a.localeCompare(b, 'zh')
  })
})

const importAttrMismatchCount = computed(() =>
  (importDraft.value?.lines || []).filter((ln: any) => ln?.has_attr_mismatch).length,
)

const importDraftLines = computed(() => {
  const lines = importDraft.value?.lines || []
  return lines.map((ln: any, index: number) => {
    const sized: Record<string, number | string> = {}
    for (const sv of importSizeColumns.value) {
      sized[`_sz_${sv}`] = importLineSizeQty(ln, sv) || ''
    }
    return {
      ...ln,
      ...sized,
      _importIndex: index,
      _importKey: `${importSession.value?.id || 'x'}-${index}-${ln?.raw_product_code || ''}-${ln?.color_name || ''}`,
    }
  })
})

const importTableKey = computed(
  () =>
    `${importSession.value?.id || 'none'}-${importDraftLines.value.length}-${importSizeColumns.value.join('_')}`,
)
const headerDraft = reactive({
  id: null as number | null,
  order_no: '',
  customer_id: null as number | null,
  customer_name: '',
  ordered_at: new Date().toISOString().slice(0, 10),
  notes: '',
  brand_logo_url: '',
  notes_image_url: '',
  biz_mode: 'self_produce' as string,
  status: '' as string,
  summaryText: '',
})
const headerReadonly = computed(() => {
  if (!headerDraft.id) return false
  return headerDraft.status === 'completed' || headerDraft.status === 'cancelled'
})
const headerDialogTitle = computed(() => {
  if (!headerDraft.id) return '新建订单'
  return headerReadonly.value ? '订单详情' : '订单详情'
})

const inlineLine = ref<InlineLineState | null>(null)
let inlineLineSeq = 0

/** 文本溢出时才启用 tooltip；默认禁用，mouseenter 时再量宽 */
const overflowTipDisabled = reactive<Record<string, boolean>>({})

function tipKey(prefix: string, row: any) {
  return `${prefix}:${row?._key ?? row?.sales_order_line_id ?? row?.sales_order_id ?? ''}`
}

function isOverflowTipDisabled(key: string) {
  return overflowTipDisabled[key] !== false
}

function onOverflowTipEnter(key: string, ev: Event) {
  const el = ev.currentTarget as HTMLElement | null
  if (!el) {
    overflowTipDisabled[key] = true
    return
  }
  const inner = el.querySelector('span') as HTMLElement | null
  const measure = inner && inner.scrollWidth ? inner : el
  overflowTipDisabled[key] = measure.scrollWidth <= measure.clientWidth + 1
}

const mrpVisible = ref(false)
const progressVisible = ref(false)
const progressRow = ref<any>(null)
const mrpLoading = ref(false)
const mrpIncludeShared = ref(true)
const mrpShortagesOnly = ref(false)
const mrpResult = ref<any>(null)
const mrpRefs = ref<{ sales_order_id: number; line_id: number }[]>([])
const mrpAnalysisRows = ref<any[]>([])
const confirmingFromAnalysis = ref(false)
const creatingDemandPurchase = ref(false)
const cancellingFromAnalysis = ref(false)

const auth = useAuthStore()
const agentEnabled = ref(true)
const agentReason = ref('')
const agentStreaming = ref(false)
const agentError = ref('')
const agentConversationId = ref<string | null>(null)
const agentInput = ref('')
const agentMessages = ref<AssistantChatMsg[]>([])
const agentStale = ref(false)
const agentPanelOpen = ref(false)
const intakeChatPanelRef = ref<InstanceType<typeof AssistantChatPanel> | null>(null)
const intakeReport = ref<any>(null)
const intakeLoading = ref(false)
const intakeDrawerSize = ref('640px')
const intakeHyp = reactive({
  qty: null as number | null,
  delivery_date: '' as string,
  is_rush: false,
  default_daily_capacity: null as number | null,
})
let agentAbort: AbortController | null = null
let intakeHypTimer: ReturnType<typeof setTimeout> | null = null

const intakeData = computed(() => intakeReport.value?.data || intakeReport.value || {})
const intakeVerdict = computed(() => intakeData.value?.verdict)
const intakeVerdictLabel = computed(
  () => intakeData.value?.verdict_label || intakeReport.value?.summary || '',
)
const intakeReasons = computed(() => {
  const rs = listOf(intakeData.value?.reasons)
  if (rs.length) return rs.slice(0, 4).map(String)
  const text = String(intakeReport.value?.summary || '').trim()
  return text ? [text] : []
})
const intakeMaterialEta = computed(
  () =>
    intakeData.value?.material_eta?.earliest_start ||
    intakeData.value?.schedule_sim?.earliest_start ||
    '',
)
const intakePayRisk = computed(() => intakeData.value?.customer_pay_risk?.risk || '')
const intakePayRiskLabel = computed(
  () => intakeData.value?.customer_pay_risk?.risk_label || '',
)
const intakePayRiskDetail = computed(() => {
  const p = intakeData.value?.customer_pay_risk || {}
  const bits: string[] = []
  if (p.avg_collect_days != null) bits.push(`均回款 ${p.avg_collect_days} 天`)
  if (p.open_balance != null && Number(p.open_balance) > 0) {
    bits.push(`未结 ¥${formatMoney(p.open_balance)}`)
  }
  if (p.overdue_count) bits.push(`逾期 ${p.overdue_count} 笔`)
  const reason = listOf(p.reasons)[0]
  if (!bits.length && reason) return String(reason)
  return bits.join(' · ')
})
const intakeScheduleRisk = computed(() => intakeData.value?.schedule_sim?.intake_risk || '')
const intakeScheduleRiskLabel = computed(() => {
  const sim = intakeData.value?.schedule_sim || {}
  const label = sim.intake_risk_label || ''
  const finish = sim.intake_finish
  if (label && finish) return `${label} · ${finish}`
  return label || finish || ''
})
const intakeScheduleHint = computed(
  () => intakeData.value?.schedule_sim?.intake_risk_hint || '',
)
const intakeVerdictTone = computed(() => {
  const v = String(intakeVerdict.value || '')
  if (v === 'accept') return 'ok'
  if (v === 'reject') return 'bad'
  if (v === 'caution') return 'warn'
  return 'neutral'
})
const intakeKit = computed(() => {
  const kit = intakeData.value?.kit
  if (kit && (kit.kit_ok != null || kit.empty_bom != null || kit.shortage_lines != null)) {
    return kit
  }
  const m = mrpResult.value
  return {
    kit_ok: m?.kit_ok,
    empty_bom: m?.empty_bom,
    shortage_lines: m?.shortage_lines,
  }
})
const intakeKitLabel = computed(() => {
  const kit = intakeKit.value
  if (kit.empty_bom) return '无 BOM'
  if (kit.kit_ok) return '齐套'
  if (kit.shortage_lines != null) return `缺 ${kit.shortage_lines} 项`
  return '—'
})
const intakeKitSignalClass = computed(() => {
  const kit = intakeKit.value
  if (kit.empty_bom) return 'is-bad'
  if (kit.kit_ok) return 'is-ok'
  if (Number(kit.shortage_lines) > 0) return 'is-bad'
  return 'is-neutral'
})
const intakeScheduleSignalClass = computed(() => {
  const r = intakeScheduleRisk.value
  if (r === 'late' || r === 'kit_blocked' || r === 'capacity_blocked') return 'is-bad'
  if (r === 'tight') return 'is-warn'
  if (r === 'ok') return 'is-ok'
  return 'is-neutral'
})
const intakePaySignalClass = computed(() => {
  const r = intakePayRisk.value
  if (r === 'high') return 'is-bad'
  if (r === 'medium') return 'is-warn'
  if (r === 'low') return 'is-ok'
  return 'is-neutral'
})
const intakeImpactSignalClass = computed(() => {
  const sim = intakeData.value?.schedule_sim || {}
  if (Number(sim.delayed_count || 0) > 0) return 'is-bad'
  if (Number(sim.impact_count || 0) > 0) return 'is-warn'
  if (sim.capacity_configured === false) return 'is-warn'
  return 'is-ok'
})
const intakeImpacts = computed(() => listOf(intakeData.value?.schedule_sim?.impacts).slice(0, 8))

const intakeSizeCurve = computed(() => intakeData.value?.size_curve || {})
const intakeSizeCurveRows = computed(() => {
  const c0 = listOf(intakeSizeCurve.value?.curves)[0] || {}
  const deltas = listOf(c0.top_deltas)
  if (deltas.length) {
    return deltas.map((d) => ({
      size_id: d.size_id,
      size_value: d.size_value,
      this_share_pct: Number(d.this_share_pct || 0),
      hist_share_pct: Number(d.hist_share_pct || 0),
      delta_pp: Number(d.delta_pp || 0),
    }))
  }
  return listOf(c0.current)
    .filter((r) => Number(r.qty || r.share_pct || 0) > 0)
    .map((r) => ({
      size_id: r.size_id,
      size_value: r.size_value,
      this_share_pct: Number(r.share_pct || 0),
      hist_share_pct: 0,
      delta_pp: null as number | null,
    }))
})
const intakeSizeCurveShow = computed(() => intakeSizeCurveRows.value.length > 0)
const intakeSizeCurveMeta = computed(() => {
  const c0 = listOf(intakeSizeCurve.value?.curves)[0] || {}
  const scope =
    c0.baseline_scope === 'customer_product'
      ? '同客同款'
      : c0.baseline_scope === 'product'
        ? '同款'
        : '本单占比'
  const n = c0.baseline_sample_orders || 0
  return n ? `${scope} · ${n} 单` : scope
})

const intakeContention = computed(() => intakeData.value?.contention || {})
const intakeContentionShow = computed(
  () => listOf(intakeContention.value?.items).length > 0,
)
const intakeContentionMeta = computed(() => {
  const n = Number(intakeContention.value?.conflict_count || 0)
  return n > 0 ? `${n} 项冲突` : '缺料透视'
})
const intakeContentionItems = computed(() =>
  listOf(intakeContention.value?.items).slice(0, 5),
)

const intakeCostDev = computed(() => intakeData.value?.cost_deviation || {})
const intakeCostDevProducts = computed(() =>
  listOf(intakeCostDev.value?.products)
    .filter((p) => Number(p.sample_size || 0) > 0 && p.actual_unit_cost_avg != null)
    .slice(0, 4),
)
const intakeCostDevShow = computed(() => intakeCostDevProducts.value.length > 0)

const intakeSuggestions = computed(() => {
  const tips: { text: string; tone: string }[] = []
  const seen = new Set<string>()
  const push = (text: string, tone = 'medium') => {
    const t = String(text || '').trim()
    if (!t || seen.has(t)) return
    seen.add(t)
    tips.push({ text: t, tone })
  }
  for (const ins of listOf(intakeReport.value?.insights)) {
    push(ins.text, String(ins.severity || 'medium'))
    if (tips.length >= 3) break
  }
  if (tips.length < 3) {
    for (const r of intakeReasons.value) {
      push(r, 'medium')
      if (tips.length >= 3) break
    }
  }
  if (tips.length < 3 && Number(intakeContention.value?.conflict_count || 0) > 0) {
    push('缺料料号存在争料，排产确认前先定保谁、催谁。', 'high')
  }
  if (tips.length < 3) {
    const hl = intakeSizeCurve.value?.highlight
    if (hl && Math.abs(Number(hl.delta_pp || 0)) >= 12) {
      push(
        `色码「${hl.size_value}」偏离历史 ${formatDeltaPp(hl.delta_pp)}，留意尾码风险。`,
        'medium',
      )
    }
  }
  if (tips.length < 3) {
    const worst = intakeCostDev.value?.worst
    if (worst?.delta_pct != null && Number(worst.delta_pct) >= 12) {
      push(
        `${worst.product_code || '该款'}历史实耗高于成本卡 ${formatDeltaPct(worst.delta_pct)}，报价宜留余量。`,
        'medium',
      )
    }
  }
  return tips.slice(0, 3)
})

type IntakeAgentPreset = { id: string; label: string; prompt: string }

const intakeAgentPresets = computed((): IntakeAgentPreset[] => {
  const presets: IntakeAgentPreset[] = []
  const push = (id: string, label: string, prompt: string) => {
    if (presets.some((p) => p.id === id)) return
    presets.push({ id, label, prompt })
  }

  const verdict = String(intakeVerdict.value || '')
  const kit = intakeKit.value
  const sim = intakeData.value?.schedule_sim || {}
  const pay = String(intakePayRisk.value || '')
  const hl = intakeSizeCurve.value?.highlight
  const worst = intakeCostDev.value?.worst
  const contentionN = Number(intakeContention.value?.conflict_count || 0)

  if (kit.empty_bom) {
    push('bom', '没有 BOM 还能怎么推进？', '左侧显示无 BOM。请说明排产确认前必须补什么，以及临时怎么控风险。')
  } else if (!kit.kit_ok && Number(kit.shortage_lines || 0) > 0) {
    push(
      'shortage',
      '缺料先催哪几项？',
      '基于左侧缺料与预计齐套日，给出催料优先级（最多 3 项）和能否先开局部工序。',
    )
  }
  if (contentionN > 0) {
    push(
      'contention',
      '争料时保谁、推迟谁？',
      '基于左侧争料信息，给出保单/让路建议，并说明对交期的影响。',
    )
  }
  if (sim.intake_risk === 'late' || sim.intake_risk === 'tight') {
    push(
      'delivery',
      '交期紧：延交期还是加急？',
      '基于左侧本单交期风险与冲击，比较「谈延交期」与「加急/插单」的利弊，给一个建议。',
    )
  }
  if (Number(sim.delayed_count || 0) > 0 || Number(sim.impact_count || 0) > 0) {
    push(
      'impact',
      '插单冲击怎么对外说？',
      '基于左侧交期冲击明细，用简短话术说明会影响哪些单、建议怎么协调。',
    )
  }
  if (sim.capacity_configured === false) {
    push(
      'capacity',
      '假设日产能 800 会怎样？',
      '请重查 analytics.order_intake：当前 lines 加 default_daily_capacity=800，对比是否超产能与交期风险变化，禁止重复贴物料/利润明细表。',
    )
  } else if (sim.capacity_from_hypothesis) {
    push(
      'capacity',
      '产能再紧一半会怎样？',
      `请重查 analytics.order_intake：当前 lines 把 default_daily_capacity 改为约 ${Math.max(1, Math.round(Number(sim.capacity_hypothesis || 800) / 2))}，对比超产能与交期变化。`,
    )
  }
  if (hl && Math.abs(Number(hl.delta_pp || 0)) >= 8) {
    push(
      'size',
      '色码偏离怎么跟客户谈？',
      `左侧色码「${hl.size_value}」相对历史偏离 ${formatDeltaPp(hl.delta_pp)}。请给改码/控尾码的沟通建议。`,
    )
  }
  if (worst?.delta_pct != null && Number(worst.delta_pct) >= 8) {
    push(
      'cost',
      '实耗偏高，报价怎么留余量？',
      `左侧显示 ${worst.product_code || '该款'} 实耗较成本卡 ${formatDeltaPct(worst.delta_pct)}。请给报价与接单留余量建议。`,
    )
  }
  if (pay === 'high' || pay === 'medium') {
    push(
      'pay',
      '回款风险下订金/放货怎么控？',
      '基于左侧回款风险，给出订金比例或放货节奏建议（简短可执行）。',
    )
  }
  if (verdict === 'caution' || verdict === 'reject') {
    push(
      'verdict',
      '一句话告诉老板接不接',
      '综合左侧裁决，用一句话给老板：接/不接/有条件接，并附最多 2 个条件。',
    )
  }
  push(
    'whatif_delivery',
    '若交期再宽 7 天呢？',
    '请重查 analytics.order_intake：在当前 lines 上把 delivery_date 整体延后 7 天（其余不变），对比风险变化，禁止重复贴物料/利润明细表。',
  )
  push(
    'whatif_rush',
    '如果当急单插进去？',
    '请重查 analytics.order_intake：当前 lines 加 is_rush=true，看对本单与其它单的冲击，只给结论与 3 条建议。',
  )
  if (presets.length < 4) {
    push(
      'brief',
      '把左侧结论整理成 3 条行动',
      '不要重算。把左侧诊断整理成最多 3 条今日行动（谁做什么）。',
    )
  }
  return presets.slice(0, 6)
})

const intakeImpactShort = computed(() => {
  const sim = intakeData.value?.schedule_sim || {}
  if (sim.sim_error) return '仿真不可用'
  const delayed = Number(sim.delayed_count || 0)
  const hit = Number(sim.impact_count || 0)
  if (sim.capacity_configured === false && !hit) return '未校验产能'
  if (delayed > 0) return `延期 ${delayed} / 波及 ${hit}`
  if (hit > 0) return `波及 ${hit} 单`
  return '无明显冲击'
})
const intakeImpactNos = computed(() => {
  const sim = intakeData.value?.schedule_sim || {}
  const nos = listOf(sim.impacted_order_nos).filter(Boolean).slice(0, 4)
  if (!nos.length) {
    if (sim.capacity_from_hypothesis && sim.capacity_hypothesis) {
      return `按假设 ${sim.capacity_hypothesis} 双/天`
    }
    return sim.capacity_configured === false ? '未配置日产能' : ''
  }
  return nos.join('、') + (listOf(sim.impacted_order_nos).length > 4 ? '…' : '')
})
const intakeMarginPeerText = computed(() => {
  const m = intakeData.value?.margin_vs_peers || {}
  if (m.peer_median_margin == null && m.percentile == null) return ''
  const bits: string[] = []
  if (m.peer_median_margin != null) {
    bits.push(`厂内中位 ${(Number(m.peer_median_margin) * 100).toFixed(1)}%`)
  }
  if (m.delta_pp != null) {
    const d = Number(m.delta_pp)
    bits.push(d >= 0 ? `高 ${d.toFixed(1)}pt` : `低 ${Math.abs(d).toFixed(1)}pt`)
  }
  if (m.percentile != null) bits.push(`约 P${Math.round(Number(m.percentile))}`)
  return bits.join(' · ')
})

const analysisProfit = computed(() => {
  const p = intakeData.value?.profit
  if (p && typeof p.qty !== 'undefined') return p
  return buildAnalysisProfit(mrpAnalysisRows.value)
})
const analysisOrderIds = computed(() => {
  const ids = new Set<number>()
  for (const row of mrpAnalysisRows.value) {
    if (row?.sales_order_id) ids.add(Number(row.sales_order_id))
  }
  return [...ids]
})
const canConfirmFromAnalysis = computed(() =>
  mrpAnalysisRows.value.some((row) => canConfirmLine(row)),
)
const canCreateDemandPurchase = computed(() => {
  const hasShortage = Number(intakeKit.value?.shortage_lines || 0) > 0
  if (!hasShortage) return false
  return mrpAnalysisRows.value.some(
    (row) =>
      canDemandShortage(row) &&
      !row.production_order_id &&
      !row.execution_header_id,
  )
})
const canCancelFromAnalysis = computed(() =>
  mrpAnalysisRows.value.some((row) => canCancelOrder(row)),
)

/** 物料行：优先 intake kit（含预计到料），否则 MRP 兜底；缺料行在前 */
const intakeMaterialLines = computed(() => {
  const kitLines = listOf(intakeData.value?.kit?.material_lines)
  let lines: any[]
  if (kitLines.length) {
    lines = kitLines.map((r) => ({
      code: r.code || r.supplier_product_code || '',
      name: r.name || r.supplier_product_name || r.supplier_product_code || '',
      required_qty: r.required_qty,
      shortage_qty: r.shortage_qty,
      expected_ready_date: r.expected_ready_date || r.eta || '',
      partner_name: r.partner_name,
    }))
  } else {
    lines = listOf(mrpResult.value?.lines).map((r) => ({
      code: r.supplier_product_code || '',
      name: r.supplier_product_name || r.supplier_product_code || '',
      required_qty: r.required_qty,
      shortage_qty: r.shortage_qty,
      expected_ready_date: '',
      partner_name: r.partner_name,
    }))
  }
  lines.sort((a, b) => {
    const sa = Number(a.shortage_qty) > 0 ? 0 : 1
    const sb = Number(b.shortage_qty) > 0 ? 0 : 1
    if (sa !== sb) return sa - sb
    return Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
  })
  if (mrpShortagesOnly.value) {
    return lines.filter((r) => Number(r.shortage_qty) > 0)
  }
  return lines
})

function listOf(v: any): any[] {
  return Array.isArray(v) ? v : []
}

function mrpRowClassName({ row }: { row: any }) {
  return Number(row.shortage_qty) > 0 ? 'mrp-row-shortage' : 'mrp-row-ok'
}

const productDetailVisible = ref(false)
const productDetailId = ref<number | null>(null)

function openProductDetail(productId?: number | null) {
  if (!productId) return
  productDetailId.value = productId
  productDetailVisible.value = true
}

type SortOrder = 'ascending' | 'descending' | null
const serverSortBy = ref('')
const serverSortOrder = ref<'asc' | 'desc'>('desc')

function compareSizeValue(a: any, b: any) {
  return String(a.size_value).localeCompare(String(b.size_value), undefined, { numeric: true })
}

const sortedSizes = computed(() =>
  [...sizes.value].filter((s) => s.is_active !== false).sort(compareSizeValue),
)

const sizesEditorVisible = ref(false)
const sizesEditorRows = computed(() => [...sizes.value].sort(compareSizeValue))
const sizesEditorTableMaxHeight = computed(() => {
  if (typeof window === 'undefined') return 560
  return Math.max(420, Math.floor(window.innerHeight * 0.72))
})
const addingSize = ref(false)
const sizeSaving = ref(false)
const sizeForm = reactive({
  size_value: '',
  is_active: true,
})

function openSizesEditor() {
  resetSizeForm()
  sizesEditorVisible.value = true
}

function resetSizeForm() {
  addingSize.value = false
  sizeForm.size_value = ''
  sizeForm.is_active = true
}

function startAddSize() {
  sizeForm.size_value = ''
  sizeForm.is_active = true
  addingSize.value = true
}

async function reloadSizes() {
  const sizeRes: any = await http.get('/sizes')
  sizes.value = sizeRes.data?.items || []
}

async function saveNewSize() {
  const value = sizeForm.size_value.trim()
  if (!value) {
    ElMessage.warning('请填写码数')
    return
  }
  sizeSaving.value = true
  try {
    await http.post('/sizes', {
      size_value: value,
      sort_order: 0,
      is_active: true,
    })
    ElMessage.success('已添加')
    addingSize.value = false
    sizeForm.size_value = ''
    await reloadSizes()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    sizeSaving.value = false
  }
}

async function toggleSizeActive(row: any, active: boolean) {
  try {
    await http.patch(`/sizes/${row.id}`, { is_active: active })
    row.is_active = active
    await reloadSizes()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

watch(
  () => [sortedSizes.value.length, viewMode.value, inlineLine.value?.key, showSizes.value] as const,
  () => {
    relayoutTable()
    relayoutProductTable()
    void nextTick(measureTableHeight)
  },
)

watch(mrpVisible, (open) => {
  if (!open) resetAgentPanel()
})

const displayGroupedRows = computed(() => {
  const out: any[] = []
  for (const so of rows.value) {
    out.push(...rowsFromSalesOrder(so))
  }
  return out
})

function rowsFromSalesOrder(so: any) {
  const lines = so.lines?.length ? so.lines : []
  const canEditHeader = so.status !== 'completed' && so.status !== 'cancelled'
  const canAddLine = so.status === 'draft'
  const totals = calcOrderTotals(so.lines || [])
  const il = inlineLine.value
  const insertingNew = !!(il && il.lineId == null && il.salesOrderId === so.id)
  const orderNotes = (so.notes || '').trim()
  const brandLogoUrl = (so.brand_logo_url || '').trim()
  const notesImageUrl = (so.notes_image_url || '').trim()

  const displayLines: any[] = []
  const newEditRow =
    insertingNew
      ? {
          _key: il!.key,
          _rowType: 'line' as const,
          _editing: true,
          sales_order_id: so.id,
          sales_order_line_id: null,
          order_no: so.order_no,
          order_notes: orderNotes,
          brand_logo_url: brandLogoUrl,
          notes_image_url: notesImageUrl,
          customer_id: so.customer_id,
          customer_name: so.customer_name,
          biz_mode: so.biz_mode,
          ordered_at: so.ordered_at,
          order_status: so.status,
          order_total_qty: totals.qty,
          order_total_amount: totals.amount,
          line_no: '新',
          items: [],
          _canEditHeader: canEditHeader,
          _canAddLine: false,
        }
      : null
  let placedNew = false
  for (let idx = 0; idx < lines.length; idx++) {
    if (
      newEditRow &&
      !placedNew &&
      il!.insertBeforeLineId != null &&
      lines[idx].id === il!.insertBeforeLineId
    ) {
      displayLines.push(newEditRow)
      placedNew = true
    }
    displayLines.push(
      buildDisplayRow({
        orderKey: so.id,
        line: lines[idx],
        lineIndex: idx,
        orderNo: so.order_no,
        orderNotes,
        brandLogoUrl,
        notesImageUrl,
        customerName: so.customer_name,
        orderedAt: so.ordered_at,
        orderStatus: so.status,
        salesOrderId: so.id,
        orderTotalQty: totals.qty,
        orderTotalAmount: totals.amount,
        canEditHeader,
        canAddLine,
        customerId: so.customer_id,
        bizMode: so.biz_mode,
      }),
    )
  }
  if (newEditRow && !placedNew) {
    displayLines.push(newEditRow)
  }
  // 无明细时仍保留一行，用于展示合并的订单信息
  if (!displayLines.length) {
    displayLines.push({
      _key: `empty-${so.id}`,
      _rowType: 'line' as const,
      sales_order_id: so.id,
      sales_order_line_id: null,
      order_no: so.order_no,
      order_notes: orderNotes,
      brand_logo_url: brandLogoUrl,
      notes_image_url: notesImageUrl,
      customer_id: so.customer_id,
      customer_name: so.customer_name,
      biz_mode: so.biz_mode,
      ordered_at: so.ordered_at,
      order_status: so.status,
      order_total_qty: totals.qty,
      order_total_amount: totals.amount,
      line_no: '',
      items: [],
      _canEditHeader: canEditHeader,
      _canAddLine: canAddLine,
      _emptyPlaceholder: true,
    })
  } else {
    // 仅多明细时加合计行；单行订单数量/总价即本行，无需汇总
    const dataLineCount = lines.length + (insertingNew ? 1 : 0)
    if (dataLineCount > 1) {
      displayLines.push({
        _key: `summary-${so.id}`,
        _rowType: 'summary' as const,
        _isSummary: true,
        sales_order_id: so.id,
        sales_order_line_id: null,
        order_no: so.order_no,
        order_notes: orderNotes,
        brand_logo_url: brandLogoUrl,
        notes_image_url: notesImageUrl,
        customer_id: so.customer_id,
        customer_name: so.customer_name,
        biz_mode: so.biz_mode,
        ordered_at: so.ordered_at,
        order_status: so.status,
        order_total_qty: totals.qty,
        order_total_amount: totals.amount,
        order_produced_qty: totals.produced,
        order_shipped_qty: totals.shipped,
        order_allocated_qty: totals.allocated,
        order_wip_qty: totals.wip,
        total_qty: totals.qty,
        line_total: totals.amount,
        line_no: '合计',
        items: [],
        _canEditHeader: false,
        _canAddLine: false,
      })
    }
  }

  const lineCount = displayLines.length
  return displayLines.map((row, idx) => ({
    ...row,
    _lineIndex: idx,
    _lineCount: lineCount,
  }))
}

function buildDisplayRow(opts: {
  orderKey: number
  line: any
  lineIndex: number
  orderNo: string
  orderNotes?: string
  brandLogoUrl?: string
  notesImageUrl?: string
  customerName: string
  orderedAt: string
  orderStatus: string
  salesOrderId: number
  orderTotalQty?: number
  orderTotalAmount?: number | null
  canEditHeader?: boolean
  canAddLine?: boolean
  customerId?: number | null
  bizMode?: string | null
}) {
  const { line, lineIndex } = opts
  const product = line?.own_product_id
    ? products.value.find((p) => p.id === line.own_product_id)
    : null
  const color = line?.color_id ? colors.value.find((c) => c.id === line.color_id) : null
  const lineItems = line?.items || []
  const total_qty = line?.total_qty ?? lineQtyTotal(line || { items: [] })
  const unit_price = line?.unit_price
  const line_total = unit_price != null ? Number(unit_price) * Number(total_qty) : null
  return {
    _key: line?.id ? `${opts.salesOrderId}-${line.id}` : `${opts.orderKey}-empty-${lineIndex}`,
    _rowType: 'line' as const,
    _lineIndex: lineIndex,
    _orderKey: opts.orderKey,
    _canEditHeader: !!opts.canEditHeader,
    _canAddLine: !!opts.canAddLine,
    sales_order_id: opts.salesOrderId,
    sales_order_line_id: line?.id,
    order_no: opts.orderNo,
    order_notes: opts.orderNotes || '',
    brand_logo_url: opts.brandLogoUrl || '',
    notes_image_url: opts.notesImageUrl || '',
    customer_id: opts.customerId,
    customer_name: opts.customerName,
    biz_mode: opts.bizMode || 'self_produce',
    ordered_at: opts.orderedAt,
    order_total_qty: opts.orderTotalQty ?? 0,
    order_total_amount: opts.orderTotalAmount ?? null,
    notes: line?.notes || '',
    order_status: opts.orderStatus,
    sort_order: line?.sort_order ?? lineIndex,
    line_no: line?.line_no ?? (line?.sort_order != null ? line.sort_order + 1 : lineIndex + 1),
    own_product_id: line?.own_product_id,
    product_code: line?.product_code || product?.product_code,
    product_image_url: line?.product_image_url || product?.image_url,
    color_id: line?.color_id,
    color_name: line?.color_name || color?.name,
    fabric: line?.fabric || product?.fabric || '',
    lining: line?.lining || product?.lining || '',
    customer_sku: line?.customer_sku,
    brand_name: line?.brand_name || '',
    items: lineItems,
    delivery_date: line?.delivery_date,
    total_qty,
    unit_price,
    line_total,
    line_status: line?.status,
    display_status: line?.display_status,
    allocated_qty: Number(line?.allocated_qty || 0),
    produced_qty: Number(line?.produced_qty || 0),
    shipped_qty: Number(line?.shipped_qty || 0),
    wip_qty: Number(line?.wip_qty || 0),
    production_order_id: line?.production_order_id,
    production_order_no: line?.production_order_no,
    production_order_status: line?.production_order_status,
    execution_header_id: line?.execution_header_id,
    process_progress: line?.process_progress || [],
    material_status: line?.material_status || null,
  }
}

const productionProcessColumns = computed(() => {
  const columns = new Map<string, { key: string; name: string }>()
  for (const row of displayGroupedRows.value) {
    if (isSummaryRow(row)) continue
    for (const process of row.process_progress || []) {
      const key = String(process.process_id || process.process_name || '')
      if (key && !columns.has(key)) {
        columns.set(key, { key, name: String(process.process_name || '工序') })
      }
    }
  }
  return [...columns.values()]
})

function processProgressText(row: any, processKey: string) {
  const matched = (row.process_progress || []).filter(
    (process: any) => String(process.process_id || process.process_name || '') === processKey,
  )
  if (!matched.length) return '—'
  const completed = matched.reduce(
    (sum: number, process: any) => sum + Number(process.completed_qty || 0),
    0,
  )
  return `${completed}`
}

function materialStatusText(row: any) {
  const material = row.material_status
  if (material?.kit_ok) return '齐套'
  if (['purchased', 'partial'].includes(material?.purchase_status)) return '采购中'
  return '缺材料'
}

function materialStatusTagType(row: any) {
  const material = row.material_status
  if (material?.kit_ok) return 'success'
  if (['purchased', 'partial'].includes(material?.purchase_status)) return 'warning'
  return 'danger'
}

const productGroupIndex = computed(() => {
  const map = new Map<number, number>()
  let idx = 0
  for (const row of productRows.value) {
    if (!map.has(row.own_product_id)) {
      map.set(row.own_product_id, idx++)
    }
  }
  return map
})

function productRowClassName({ row }: { row: any }) {
  const idx = productGroupIndex.value.get(row.own_product_id) ?? 0
  return idx % 2 === 0 ? 'product-group-even' : 'product-group-odd'
}

function isSummaryRow(row: any) {
  return !!row?._isSummary
}

function isRowEditing(row: any) {
  if (!inlineLine.value || isSummaryRow(row)) return false
  if (row._editing) return true
  return (
    inlineLine.value.lineId != null &&
    row.sales_order_line_id === inlineLine.value.lineId &&
    row.sales_order_id === inlineLine.value.salesOrderId
  )
}

const groupRowClassName = computed(() => {
  const mode = hoverMode.value
  const oid = hoverOrderId.value
  const lkey = hoverLineKey.value
  return ({ row }: { row: any }) => {
    const orderIndex =
      row.sales_order_id == null
        ? 0
        : rows.value.findIndex((so) => so.id === row.sales_order_id)
    const parity = orderIndex % 2 === 0 ? 'order-group-even' : 'order-group-odd'
    const editing = isRowEditing(row) ? ' order-group-editing' : ''
    const summary = isSummaryRow(row) ? ' order-group-summary' : ''
    let hover = ''
    if (mode === 'order' && row.sales_order_id === oid) {
      hover = ' order-hover'
    } else if (mode === 'line' && lkey != null && row._key === lkey) {
      hover = ' line-hover'
    }
    return `${parity}${editing}${summary}${hover}`
  }
})

function groupSpanMethod({ row, columnIndex }: { row: any; columnIndex: number }) {
  // 订单号 / 客户 / 下单日期 三列跨该单明细行合并
  if (columnIndex > 2) return [1, 1]
  if (row._lineIndex === 0) return [row._lineCount || 1, 1]
  return [0, 0]
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return ''
  const n = Number(v)
  if (Number.isNaN(n)) return ''
  return String(Math.round(n))
}

function lineStatusLabel(row: any) {
  if (row._emptyPlaceholder) return ''
  if (row.display_status === 'cancelled') return '已取消'
  if (row.display_status === 'completed') return '已完成'
  if (row.display_status === 'in_progress') return '生产中'
  if (row.display_status === 'pending_production') return '已排产'
  if (row.display_status === 'pending_schedule') return '待排产'
  if (row.order_status === 'cancelled' || row.line_status === 'cancelled') return '已取消'
  if (row.order_status === 'completed' || row.line_status === 'completed') return '已完成'
  const items = row.items || []
  if (
    items.length &&
    items.every((i: any) => Number(i.shipped_qty || 0) >= Number(i.qty || 0) && Number(i.qty || 0) > 0)
  ) {
    return '已完成'
  }
  if (items.some((i: any) => Number(i.shipped_qty || 0) > 0)) return '生产中'
  const prodStatus = row.production_order_status
  if (prodStatus === 'completed') return '已完成'
  if (prodStatus === 'cancelled') return '已取消'
  if (prodStatus === 'in_progress') return '生产中'
  const allocated = Number(row.allocated_qty || 0)
  const hasExec =
    row.production_order_id ||
    row.execution_header_id ||
    allocated > 0 ||
    row.line_status === 'in_production'
  if (hasExec) return '已排产'
  if (row.order_status === 'confirmed') return '待排产'
  return '待确认'
}

function lineStatusTagType(row: any): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const label = lineStatusLabel(row)
  if (label === '生产中') return 'primary'
  if (label === '待排产') return 'warning'
  if (label === '已排产') return 'warning'
  if (label === '待确认') return 'info'
  if (label === '已取消') return 'info'
  if (label === '已完成') return 'success'
  return 'primary'
}

function orderStatusLabel(status: string) {
  if (status === 'draft') return '草稿'
  if (status === 'confirmed') return '已确认'
  if (status === 'completed') return '已完成'
  if (status === 'cancelled') return '已取消'
  return status || '—'
}

function orderStatusTagType(status: string): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  if (status === 'completed') return 'success'
  if (status === 'confirmed') return 'warning'
  if (status === 'cancelled') return 'info'
  return 'primary'
}

function productById(id?: number | null) {
  if (!id) return null
  return products.value.find((p) => p.id === id) ?? null
}

function resolveProductUnitPrice(product: any, customerId?: number | null) {
  if (!product) return null
  if (customerId != null) {
    const q = (product.quotes || []).find(
      (x: any) => Number(x.partner_id) === Number(customerId),
    )
    if (q?.quote_price != null && q.quote_price !== '') {
      return Number(q.quote_price)
    }
  }
  if (product.quote_price != null && product.quote_price !== '') {
    return Number(product.quote_price)
  }
  return null
}

function lineTotalAmount(line: any) {
  if (!line) return null
  const qty = line.total_qty != null ? Number(line.total_qty) : lineQtyTotal(line)
  const price = Number(line.unit_price)
  if (!qty || Number.isNaN(price)) return null
  return qty * price
}

function calcOrderTotals(lines: any[]) {
  let qty = 0
  let amount = 0
  let hasAmount = false
  let produced = 0
  let shipped = 0
  let allocated = 0
  let wip = 0
  for (const ln of lines || []) {
    if (!ln) continue
    const q = ln.total_qty != null ? Number(ln.total_qty) : lineQtyTotal(ln)
    qty += q || 0
    const a = lineTotalAmount(ln)
    if (a != null) {
      amount += a
      hasAmount = true
    }
    produced += Number(ln.produced_qty || 0)
    shipped += Number(ln.shipped_qty || 0)
    allocated += Number(ln.allocated_qty || 0)
    wip += Number(ln.wip_qty || 0)
  }
  return {
    qty,
    amount: hasAmount ? amount : null,
    produced,
    shipped,
    allocated,
    wip,
  }
}

function displayLineTotal(row: any) {
  const qty = Number(row.total_qty) || 0
  const price = Number(row.unit_price)
  if (!qty || Number.isNaN(price)) return ''
  return formatMoney(qty * price)
}

function applyProductToDraft(draft: LineDraft, productId: number | null, customerId?: number | null) {
  draft.own_product_id = productId
  if (!productId) {
    draft.color_id = null
    draft.fabric = ''
    draft.lining = ''
    draft.items = []
    draft.unit_price = null
    return
  }
  const product = productById(productId)
  const pcs = productColors(productId)
  draft.color_id = pcs[0]?.id ?? null
  draft.fabric = product?.fabric || ''
  draft.lining = product?.lining || ''
  draft.items = []
  draft.unit_price = resolveProductUnitPrice(product, customerId)
}

function progressCompactText(produced: any, shipped: any, qty: any) {
  const q = Number(qty || 0)
  const p = Number(produced || 0)
  const s = Number(shipped || 0)
  if (!q) return '—'
  // 未出货只显示产/需求，避免「出0」噪音
  if (s <= 0) return `产${p}/${q}`
  return `产${p} 出${s}/${q}`
}

function progressHoverTip(row: any) {
  const q = Number(row.total_qty || 0)
  const p = Number(row.produced_qty || 0)
  const s = Number(row.shipped_qty || 0)
  const w = Number(row.wip_qty || 0)
  const parts = [`需求 ${q}`, `已产 ${p}`]
  if (s > 0) parts.push(`已出 ${s}`)
  if (w > 0) parts.push(`约在制 ${w}`)
  return parts.join(' · ')
}

function sizeQty(row: any, sizeId: number) {
  const it = row.items?.find((x: any) => x.size_id === sizeId)
  const q = Number(it?.qty)
  if (!q) return ''
  return q
}

function sizeProgressTip(row: any, sizeId: number): string {
  const it = row.items?.find((x: any) => x.size_id === sizeId)
  if (!it || !Number(it.qty)) return ''
  const qty = Number(it.qty || 0)
  const allocated = Number(it.allocated_qty || 0)
  const produced = Number(it.produced_qty || 0)
  const shipped = Number(it.shipped_qty || 0)
  if (!allocated && !produced && !shipped) return ''
  return `需求 ${qty} · 已排 ${allocated} · 已产 ${produced} · 已出 ${shipped}`
}

function openProgressDrawer(row: any) {
  progressRow.value = row
  progressVisible.value = true
}

function goProductionFromProgress() {
  const row = progressRow.value
  if (!row) return
  progressVisible.value = false
  goExecution(row)
}

function rowProductImageUrl(row: any) {
  if (row.product_image_url) return row.product_image_url
  if (!row.own_product_id) return ''
  return products.value.find((p) => p.id === row.own_product_id)?.image_url || ''
}

function inlineLineImageUrl() {
  const id = inlineLine.value?.draft.own_product_id
  if (!id) return ''
  return products.value.find((p) => p.id === id)?.image_url || ''
}

function productColors(ownProductId?: number | null) {
  if (!ownProductId) return colors.value
  const product = products.value.find((p) => p.id === ownProductId)
  if (product?.colors?.length) return product.colors
  return colors.value
}

function getLineSizeQty(line: any, sizeId: number) {
  if (!line?.items) return undefined
  const it = line.items.find((x: any) => x.size_id === sizeId)
  return it ? Number(it.qty) : undefined
}

function setLineSizeQty(line: any, sizeId: number, val: number | undefined) {
  if (!line) return
  if (!line.items) line.items = []
  const qty = Number(val) || 0
  const idx = line.items.findIndex((x: any) => x.size_id === sizeId)
  if (qty <= 0) {
    if (idx >= 0) line.items.splice(idx, 1)
  } else if (idx >= 0) {
    line.items[idx].qty = qty
  } else {
    line.items.push({ size_id: sizeId, qty })
  }
}

function lineQtyTotal(line: any) {
  return (line?.items || []).reduce((sum: number, it: any) => sum + (Number(it.qty) || 0), 0)
}

function emptyLineDraft(): LineDraft {
  return {
    own_product_id: null,
    color_id: null,
    fabric: '',
    lining: '',
    customer_sku: '',
    brand_name: '',
    delivery_date: null,
    unit_price: null,
    notes: '',
    items: [],
  }
}

function warnIfInlineBusy() {
  if (inlineLine.value) {
    ElMessage.warning('请先保存或取消当前行编辑')
    return true
  }
  return false
}

function onInlineProductChange(productId: number | null) {
  const il = inlineLine.value
  if (!il) return
  const so = rows.value.find((r) => r.id === il.salesOrderId)
  applyProductToDraft(il.draft, productId, so?.customer_id)
}

function startCreate() {
  if (warnIfInlineBusy()) return
  if (viewMode.value !== 'split') {
    viewMode.value = 'split'
  }
  headerDraft.id = null
  headerDraft.order_no = ''
  headerDraft.customer_id = customers.value[0]?.id ?? null
  headerDraft.customer_name = ''
  headerDraft.ordered_at = new Date().toISOString().slice(0, 10)
  headerDraft.notes = ''
  headerDraft.brand_logo_url = ''
  headerDraft.notes_image_url = ''
  headerDraft.biz_mode = 'self_produce'
  headerDraft.status = 'draft'
  headerDraft.summaryText = ''
  onHeaderCustomerChange(headerDraft.customer_id)
  headerDialogVisible.value = true
}

async function openImport() {
  if (warnIfInlineBusy()) return
  resetImport()
  importVisible.value = true
  try {
    await loadMasters()
  } catch {
    /* 核对页可选档案；失败不阻断上传 */
  }
}

function resetImport() {
  if (importDraftPatchTimer) {
    clearTimeout(importDraftPatchTimer)
    importDraftPatchTimer = null
  }
  importFile.value = null
  importSession.value = null
  importSaving.value = false
  importDragging.value = false
  importDragDepth = 0
  if (importFileInputRef.value) importFileInputRef.value.value = ''
}

function resetImportToUpload() {
  const file = importFile.value
  resetImport()
  importFile.value = file
}

function applyImportSession(session: any, _opts: { autofillCustomer?: boolean } = {}) {
  importSession.value = session
}

function importLineProductOptions(row: any) {
  const map = new Map<number, { id: number; product_code: string }>()
  for (const c of row?.product_candidates || []) {
    if (c?.id != null) map.set(c.id, { id: c.id, product_code: c.product_code })
  }
  for (const p of products.value) {
    if (p?.id != null && !map.has(p.id)) {
      map.set(p.id, { id: p.id, product_code: p.product_code })
    }
  }
  return [...map.values()]
}

function importLineQty(row: any) {
  return (row?.items || []).reduce((s: number, it: any) => s + Number(it.qty || 0), 0)
}

function importLineSizeQty(row: any, sizeValue: string) {
  const hit = (row?.items || []).find((it: any) => String(it?.size_value) === String(sizeValue))
  const qty = Number(hit?.qty || 0)
  return qty > 0 ? qty : 0
}

function importAttrMismatch(row: any, key: 'color' | 'fabric' | 'lining') {
  return row?.attr_checks?.[key]?.status === 'mismatch'
}

function importAttrSystem(row: any, key: 'color' | 'fabric' | 'lining') {
  return row?.attr_checks?.[key]?.system || '—'
}

function importLineRowClass({ row }: { row: any }) {
  if (!row?.own_product_id || row.product_status !== 'matched') return 'so-import-line-warn'
  if (row.has_attr_mismatch) return 'so-import-line-mismatch'
  return ''
}

function isExcelImportFile(file: File) {
  const name = (file.name || '').toLowerCase()
  return name.endsWith('.xlsx') || name.endsWith('.xlsm')
}

function setImportFile(file: File | null) {
  if (!file) {
    importFile.value = null
    return
  }
  if (!isExcelImportFile(file)) {
    ElMessage.warning('请上传 .xlsx 订单文件')
    return
  }
  importFile.value = file
}

function clearImportFile() {
  importFile.value = null
  if (importFileInputRef.value) importFileInputRef.value.value = ''
}

function formatImportFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function onImportZoneClick() {
  if (importSaving.value) return
  importFileInputRef.value?.click()
}

function onImportFileInputChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0] || null
  input.value = ''
  setImportFile(file)
}

function onImportDragEnter() {
  if (importSaving.value) return
  importDragDepth += 1
  importDragging.value = true
}

function onImportDragOver() {
  if (importSaving.value) return
  importDragging.value = true
}

function onImportDragLeave() {
  importDragDepth = Math.max(0, importDragDepth - 1)
  if (importDragDepth === 0) importDragging.value = false
}

function onImportDrop(e: DragEvent) {
  importDragDepth = 0
  importDragging.value = false
  if (importSaving.value) return
  const file = e.dataTransfer?.files?.[0] || null
  setImportFile(file)
}

async function downloadImportTemplate() {
  try {
    const res: any = await http.get('/sales-orders/import-template', {
      responseType: 'blob',
    })
    const blob =
      res instanceof Blob
        ? res
        : new Blob([res.data || res], {
            type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '销售订单导入模版.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '下载失败')
  }
}

async function startImportParse() {
  if (!importFile.value) {
    ElMessage.warning('请选择 Excel 文件')
    return
  }
  importSaving.value = true
  try {
    const fd = new FormData()
    fd.append('file', importFile.value)
    const res: any = await http.post('/sales-orders/import-sessions', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    applyImportSession(res.data)
    if (res.data?.status === 'failed') {
      ElMessage.warning(res.data?.parse_error || '解析失败，请核对后重传')
    } else if (importBlockingIssues.value.length) {
      ElMessage.info(`解析完成，还有 ${importBlockingIssues.value.length} 项待核对`)
    } else {
      ElMessage.success('解析完成，请核对后确认导入')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '解析失败')
  } finally {
    importSaving.value = false
  }
}

function scheduleDraftPatch() {
  if (!importSession.value?.id || importSession.value?.result) return
  if (importDraftPatchTimer) clearTimeout(importDraftPatchTimer)
  importDraftPatchTimer = setTimeout(() => {
    void flushDraftPatch({}, { silent: true })
  }, 400)
}

async function flushDraftPatch(extra: Record<string, any> = {}, opts: { silent?: boolean } = {}) {
  if (!importSession.value?.id || importSession.value?.result) return
  const draft = importSession.value.draft || {}
  if (!opts.silent) importSaving.value = true
  try {
    const res: any = await http.patch(`/sales-orders/import-sessions/${importSession.value.id}`, {
      order_no: draft.order_no,
      ordered_at: draft.ordered_at,
      delivery_date: draft.delivery_date,
      notes: draft.notes,
      customer: draft.customer
        ? {
            customer_id: draft.customer.customer_id ?? null,
            customer_name: draft.customer.customer_name || '',
          }
        : undefined,
      ...extra,
    })
    applyImportSession(res.data, { autofillCustomer: false })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存草稿失败')
  } finally {
    if (!opts.silent) importSaving.value = false
  }
}

function onImportCustomerId(id: number | null) {
  if (!importSession.value?.draft) return
  const full = customers.value.find((x) => x.id === id)
  const cand = importCustomerOptions.value.find((x) => x.id === id)
  importSession.value.draft.customer = {
    ...(importSession.value.draft.customer || {}),
    customer_id: id,
    customer_name: full
      ? full.short_name || full.name
      : cand?.name || '',
    status: id ? 'matched' : 'needs_input',
  }
  scheduleDraftPatch()
}

function onImportImageRole(imageId: string, role: string) {
  if (!importSession.value?.images) return
  for (const img of importSession.value.images) {
    if (img.id === imageId) img.role = role
    else if (role !== 'ignore' && img.role === role) img.role = 'ignore'
  }
  void flushDraftPatch(
    {
      images: importSession.value.images.map((img: any) => ({ id: img.id, role: img.role })),
    },
    { silent: true },
  )
}

function onImportLineProduct(index: number, productId: number) {
  if (!importSession.value?.draft?.lines?.[index]) return
  const p = products.value.find((x) => x.id === productId)
  const line = importSession.value.draft.lines[index]
  line.own_product_id = productId
  line.product_code = p?.product_code || line.product_code
  line.product_status = productId ? 'matched' : 'missing'
  void flushDraftPatch(
    {
      lines: [{ index, own_product_id: productId }],
    },
    { silent: true },
  )
}

async function confirmImportSession() {
  if (!importSession.value?.id) return
  if (importBlockingIssues.value.length || !importSession.value.can_confirm) {
    ElMessage.warning(importBlockingIssues.value.map((x) => x.text).join('；') || '请先完成核对')
    return
  }
  importSaving.value = true
  try {
    if (importDraftPatchTimer) {
      clearTimeout(importDraftPatchTimer)
      importDraftPatchTimer = null
      await flushDraftPatch({}, { silent: true })
    }
    const res: any = await http.post(
      `/sales-orders/import-sessions/${importSession.value.id}/confirm`,
    )
    applyImportSession(res.data)
    ElMessage.success(`已导入：${res.data?.result?.order_no || ''}`)
    await load()
    await loadMasters()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认导入失败')
  } finally {
    importSaving.value = false
  }
}

function openOrderDetail(salesOrderId: number) {
  if (warnIfInlineBusy()) return
  const so = rows.value.find((r) => r.id === salesOrderId)
  if (!so) return
  const totals = calcOrderTotals(so.lines || [])
  const lineN = (so.lines || []).length
  headerDraft.id = so.id
  headerDraft.order_no = so.order_no || ''
  headerDraft.customer_id = so.customer_id ?? null
  headerDraft.customer_name = so.customer_name || ''
  headerDraft.ordered_at = so.ordered_at || new Date().toISOString().slice(0, 10)
  headerDraft.notes = so.notes || ''
  headerDraft.brand_logo_url = so.brand_logo_url || ''
  headerDraft.notes_image_url = so.notes_image_url || ''
  headerDraft.biz_mode = so.biz_mode || 'self_produce'
  headerDraft.status = so.status || ''
  headerDraft.summaryText =
    lineN > 0 ? `共 ${lineN} 行明细 · ${totals.qty} 双` : '暂无明细'
  headerDialogVisible.value = true
}

function onHeaderCustomerChange(id: number | null) {
  const c = customers.value.find((x) => x.id === id)
  if (c) headerDraft.customer_name = c.short_name || c.name
}

const logoFileInputRef = ref<HTMLInputElement | null>(null)
const logoUploading = ref(false)
const logoDragging = ref(false)
let logoDragDepth = 0

async function uploadLogoFile(file: File) {
  if (headerReadonly.value) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请上传图片文件')
    return
  }
  logoUploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await http.post('/supplier-products/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    headerDraft.brand_logo_url = res.data.url
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    logoUploading.value = false
  }
}

function onLogoZoneClick() {
  if (headerReadonly.value || logoUploading.value) return
  logoFileInputRef.value?.click()
}

function onLogoFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void uploadLogoFile(file)
}

function onLogoDragEnter() {
  if (headerReadonly.value || logoUploading.value) return
  logoDragDepth += 1
  logoDragging.value = true
}

function onLogoDragOver() {
  if (headerReadonly.value || logoUploading.value) return
  logoDragging.value = true
}

function onLogoDragLeave() {
  logoDragDepth = Math.max(0, logoDragDepth - 1)
  if (logoDragDepth === 0) logoDragging.value = false
}

function onLogoDrop(e: DragEvent) {
  logoDragDepth = 0
  logoDragging.value = false
  if (headerReadonly.value || logoUploading.value) return
  const file = e.dataTransfer?.files?.[0]
  if (file) void uploadLogoFile(file)
}

const notesImgFileInputRef = ref<HTMLInputElement | null>(null)
const notesImgUploading = ref(false)
const notesImgDragging = ref(false)
let notesImgDragDepth = 0

async function uploadNotesImgFile(file: File) {
  if (headerReadonly.value) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请上传图片文件')
    return
  }
  notesImgUploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await http.post('/supplier-products/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    headerDraft.notes_image_url = res.data.url
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    notesImgUploading.value = false
  }
}

function onNotesImgZoneClick() {
  if (headerReadonly.value || notesImgUploading.value) return
  notesImgFileInputRef.value?.click()
}

function onNotesImgFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void uploadNotesImgFile(file)
}

function onNotesImgDragEnter() {
  if (headerReadonly.value || notesImgUploading.value) return
  notesImgDragDepth += 1
  notesImgDragging.value = true
}

function onNotesImgDragOver() {
  if (headerReadonly.value || notesImgUploading.value) return
  notesImgDragging.value = true
}

function onNotesImgDragLeave() {
  notesImgDragDepth = Math.max(0, notesImgDragDepth - 1)
  if (notesImgDragDepth === 0) notesImgDragging.value = false
}

function onNotesImgDrop(e: DragEvent) {
  notesImgDragDepth = 0
  notesImgDragging.value = false
  if (headerReadonly.value || notesImgUploading.value) return
  const file = e.dataTransfer?.files?.[0]
  if (file) void uploadNotesImgFile(file)
}

async function saveHeader() {
  if (headerReadonly.value) {
    headerDialogVisible.value = false
    return
  }
  if (!headerDraft.customer_id && !headerDraft.customer_name?.trim()) {
    ElMessage.warning('请选择或填写客户')
    return
  }
  const optionalDate = (v: unknown) => {
    if (v == null) return undefined
    const s = String(v).trim()
    return s || undefined
  }
  const payload = {
    order_no: headerDraft.order_no?.trim() || undefined,
    customer_id: headerDraft.customer_id || undefined,
    customer_name: headerDraft.customer_name?.trim() || undefined,
    ordered_at: optionalDate(headerDraft.ordered_at),
    notes: headerDraft.notes?.trim() || null,
    brand_logo_url: headerDraft.brand_logo_url?.trim() || null,
    notes_image_url: headerDraft.notes_image_url?.trim() || null,
    biz_mode: headerDraft.biz_mode || 'self_produce',
  }
  headerSaving.value = true
  try {
    let createdId: number | null = null
    if (headerDraft.id) {
      await http.patch(`/sales-orders/${headerDraft.id}`, payload)
    } else {
      const res: any = await http.post('/sales-orders', { ...payload, lines: [] })
      createdId = res.data?.id ?? null
    }
    ElMessage.success('已保存')
    headerDialogVisible.value = false
    await load()
    if (createdId != null) {
      startAddLine(createdId)
    }
  } catch {
    // 错误提示由 http 拦截器处理
  } finally {
    headerSaving.value = false
  }
}

function startAddLine(salesOrderId: number, insertBeforeLineId: number | null = null) {
  if (warnIfInlineBusy()) return
  const so = rows.value.find((r) => r.id === salesOrderId)
  if (!so || so.status !== 'draft') {
    ElMessage.warning('仅草稿订单可增加明细')
    return
  }
  inlineLineSeq += 1
  inlineLine.value = {
    salesOrderId,
    lineId: null,
    insertBeforeLineId,
    key: `new-line-${salesOrderId}-${inlineLineSeq}`,
    draft: emptyLineDraft(),
  }
}

function startEditLine(row: any) {
  if (warnIfInlineBusy()) return
  if (!canEditLine(row)) return
  inlineLine.value = {
    salesOrderId: row.sales_order_id,
    lineId: row.sales_order_line_id,
    insertBeforeLineId: null,
    key: row._key,
    draft: {
      own_product_id: row.own_product_id ?? null,
      color_id: row.color_id ?? null,
      fabric: row.fabric || '',
      lining: row.lining || '',
      customer_sku: row.customer_sku || '',
      brand_name: row.brand_name || '',
      delivery_date: row.delivery_date || null,
      unit_price: row.unit_price != null ? Number(row.unit_price) : null,
      notes: row.notes || '',
      items: (row.items || []).map((it: any) => ({
        size_id: it.size_id,
        qty: Number(it.qty) || 0,
      })),
    },
  }
}

function cancelInlineLine() {
  inlineLine.value = null
}

function buildLinePayload(draft: LineDraft) {
  const optionalDate = (v: unknown) => {
    if (v == null) return undefined
    const s = String(v).trim()
    return s || undefined
  }
  return {
    own_product_id: draft.own_product_id!,
    color_id: draft.color_id!,
    fabric: draft.fabric?.trim() || undefined,
    lining: draft.lining?.trim() || undefined,
    customer_sku: draft.customer_sku?.trim() || undefined,
    brand_name: draft.brand_name?.trim() || undefined,
    delivery_date: optionalDate(draft.delivery_date),
    unit_price:
      draft.unit_price == null || (draft.unit_price as any) === ''
        ? undefined
        : Number(draft.unit_price),
    notes: draft.notes?.trim() || undefined,
    items: (draft.items || [])
      .filter((it) => it.size_id && Number(it.qty) > 0)
      .map((it) => ({
        size_id: Number(it.size_id),
        qty: Math.trunc(Number(it.qty)),
      })),
  }
}

async function saveInlineLine() {
  const il = inlineLine.value
  if (!il) return
  const d = il.draft
  if (!d.own_product_id) {
    ElMessage.warning('请选择产品')
    return
  }
  if (!d.color_id) {
    ElMessage.warning('请选择产品颜色')
    return
  }
  if (!(d.items || []).some((it) => it.size_id && Number(it.qty) > 0)) {
    ElMessage.warning('请至少填写一个码数数量')
    return
  }
  saving.value = true
  try {
    const payload = buildLinePayload(d)
    if (il.lineId) {
      await http.patch(`/sales-orders/${il.salesOrderId}/lines/${il.lineId}`, payload)
    } else {
      await http.post(`/sales-orders/${il.salesOrderId}/lines`, {
        ...payload,
        insert_before_line_id: il.insertBeforeLineId ?? undefined,
      })
    }
    ElMessage.success('已保存')
    inlineLine.value = null
    await load()
  } catch {
    // 错误提示由 http 拦截器处理
  } finally {
    saving.value = false
  }
}

function onSortChange({ prop, order }: { prop: string; order: SortOrder }) {
  if (!prop || !order) {
    serverSortBy.value = ''
    serverSortOrder.value = viewMode.value === 'product' ? 'asc' : 'desc'
  } else {
    serverSortBy.value = prop
    serverSortOrder.value = order === 'ascending' ? 'asc' : 'desc'
    page.value = 1
  }
  void load()
}

async function onViewModeChange() {
  if (inlineLine.value) {
    try {
      await ElMessageBox.confirm('切换视图将放弃未保存的行编辑，继续？', '切换视图', {
        type: 'warning',
      })
      inlineLine.value = null
    } catch {
      viewMode.value = 'split'
      return
    }
  }
  selectedProductLines.value = []
  serverSortBy.value = ''
  serverSortOrder.value = viewMode.value === 'product' ? 'asc' : 'desc'
  if (viewMode.value === 'product' && pageSize.value < 100) {
    pageSize.value = 100
  }
  page.value = 1
  void load()
}

function onProductSelectionChange(sel: any[]) {
  selectedProductLines.value = sel
}

function canSelectLine(row: any) {
  return canConfirmLine(row)
}

function search() {
  page.value = 1
  void load()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

async function loadStatusStats() {
  try {
    const res: any = await http.get('/sales-orders/status-stats')
    statusStats.value = {
      total: Number(res.data?.total || 0),
      by_status: {
        pending_confirm: Number(res.data?.by_status?.pending_confirm || 0),
        pending_schedule: Number(res.data?.by_status?.pending_schedule || 0),
        pending_production: Number(res.data?.by_status?.pending_production || 0),
        in_progress: Number(res.data?.by_status?.in_progress || 0),
        completed: Number(res.data?.by_status?.completed || 0),
        cancelled: Number(res.data?.by_status?.cancelled || 0),
      },
    }
  } catch {
    // keep previous stats
  }
}

async function load() {
  const kw = keyword.value.trim()
  const params: Record<string, unknown> = {
    page: page.value,
    page_size: pageSize.value,
    status: statusFilter.value || undefined,
    view: viewMode.value,
  }
  if (viewMode.value === 'product') {
    if (kw) params.product_code = kw
    params.sort_by = serverSortBy.value || 'line_no'
    params.sort_order = serverSortOrder.value
  } else {
    if (kw) params.keyword = kw
    if (serverSortBy.value) {
      params.sort_by = serverSortBy.value
      params.sort_order = serverSortOrder.value
    }
  }
  const [res] = await Promise.all([
    http.get('/sales-orders', { params }) as Promise<any>,
    loadStatusStats(),
  ])
  if (viewMode.value === 'product') {
    productRows.value = (res.data?.items || []).map((row: any, idx: number) => {
      const product = row.own_product_id
        ? products.value.find((p) => p.id === row.own_product_id)
        : null
      return {
        ...row,
        fabric: row.fabric || product?.fabric || '',
        lining: row.lining || product?.lining || '',
        _key: row.sales_order_line_id
          ? `${row.sales_order_id}-${row.sales_order_line_id}`
          : `p-${idx}`,
        line_status: row.line_status ?? row.status,
      }
    })
    rows.value = []
  } else {
    rows.value = res.data?.items || []
    productRows.value = []
  }
  total.value = res.data?.total || 0
  selectedProductLines.value = []
  productTableRef.value?.clearSelection()
  if (viewMode.value === 'production') {
    await nextTick()
    relayoutTable()
  }
  await nextTick()
  measureTableHeight()
}

async function loadMasters() {
  const [cust, prod, colorRes, sizeRes]: any[] = await Promise.all([
    http.get('/partners', { params: { role: 'customer', active_only: true, page_size: 200 } }),
    http.get('/own-products', { params: { page_size: 200 } }),
    http.get('/colors'),
    http.get('/sizes'),
  ])
  customers.value = cust.data?.items || []
  products.value = prod.data?.items || []
  colors.value = colorRes.data?.items || []
  sizes.value = sizeRes.data?.items || []
}

function canConfirmLine(row: any) {
  return Boolean(
    !row._emptyPlaceholder &&
      !row._isSummary &&
      row.sales_order_line_id &&
      !row.production_order_id &&
      !row.execution_header_id &&
      row.order_status === 'draft',
  )
}

function canGoSchedule(row: any) {
  return Boolean(
    !row._emptyPlaceholder &&
      !row._isSummary &&
      row.sales_order_line_id &&
      row.order_status === 'confirmed' &&
      !row.production_order_id &&
      !row.execution_header_id &&
      Number(row.allocated_qty || 0) === 0,
  )
}

function canDemandShortage(row: any) {
  return canGoSchedule(row) || canConfirmLine(row)
}

/** 取消订单（改状态为已取消）；删除明细是物理删行，二者不同 */
function canCancelOrder(row: any) {
  return Boolean(
    !row._emptyPlaceholder &&
      !row._isSummary &&
      row.sales_order_id &&
      row.order_status !== 'completed' &&
      row.order_status !== 'cancelled',
  )
}

function canDeleteLine(row: any) {
  return Boolean(
    !row._emptyPlaceholder &&
      !row._isSummary &&
      row.sales_order_line_id &&
      !row.production_order_id &&
      !row.execution_header_id &&
      Number(row.allocated_qty || 0) === 0 &&
      row.line_status !== 'in_production' &&
      row.order_status !== 'completed' &&
      row.order_status !== 'cancelled',
  )
}

function canEditLine(row: any) {
  // 已接单未排产仍可改明细；已排进执行单不可在此改
  return canDeleteLine(row)
}

async function deleteLine(row: any) {
  if (!canDeleteLine(row)) return
  if (inlineLine.value?.lineId === row.sales_order_line_id) {
    ElMessage.warning('请先取消当前行编辑')
    return
  }
  const label = [row.product_code, row.color_name].filter(Boolean).join(' · ')
  await ElMessageBox.confirm(
    `删除「${row.order_no}」${label ? `的 ${label}` : '该'} 明细行？`,
    '删除明细',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await http.delete(`/sales-orders/${row.sales_order_id}/lines/${row.sales_order_line_id}`)
  ElMessage.success('已删除')
  await load()
}

function canSimulateMrp(row: any) {
  return Boolean(
    !row._emptyPlaceholder &&
      !row._isSummary &&
      row.sales_order_line_id &&
      row.own_product_id &&
      Number(row.total_qty) > 0 &&
      row.order_status === 'draft' &&
      !row.production_order_id &&
      !row.execution_header_id,
  )
}

function hasLineMoreActions(row: any) {
  return Boolean(
    canSimulateMrp(row) ||
      canDemandShortage(row) ||
      row.production_order_id ||
      row.execution_header_id ||
      canDeleteLine(row),
  )
}

function goScheduleForRow(row: any) {
  router.push({
    path: '/admin/schedule',
    query: {
      tab: 'color',
      sales_order_id: String(row.sales_order_id),
      sales_order_no: row.order_no || undefined,
    },
  })
}

async function promptGoScheduleAfterConfirm(rows: any[], orderCount?: number) {
  const unique = new Set(rows.map((r) => Number(r.sales_order_id)).filter((id) => id > 0))
  const text =
    orderCount && orderCount > 1 ? `已确认接单 ${orderCount} 张订单` : '接单成功'
  try {
    await ElMessageBox.confirm(`${text}，是否去排产？`, '接单成功', {
      type: 'success',
      confirmButtonText: '去排产',
      cancelButtonText: '稍后',
      distinguishCancelAndClose: true,
    })
    const target = unique.size === 1 ? rows[0] : null
    if (target) goScheduleForRow(target)
    else router.push({ path: '/admin/schedule', query: { tab: 'color' } })
  } catch {
    // 稍后 / 关闭：留在当前页
  }
}

function onLineMore(row: any, cmd: string) {
  if (cmd === 'mrp') {
    void openProductionAnalysis([row])
    return
  }
  if (cmd === 'schedule') {
    goScheduleForRow(row)
    return
  }
  if (cmd === 'demand') {
    void openProductionAnalysis([row])
    return
  }
  if (cmd === 'production' && (row.execution_header_id || row.production_order_id)) {
    goExecution(row)
    return
  }
  if (cmd === 'delete') {
    void deleteLine(row)
  }
}

function productUnitCost(ownProductId?: number | null) {
  if (!ownProductId) return 0
  const product = products.value.find((p) => p.id === ownProductId)
  if (!product) return 0
  return (
    Number(product.material_cost || 0) +
    Number(product.labor_cost || 0) +
    Number(product.other_cost || 0)
  )
}

function buildAnalysisProfit(rows: any[]) {
  if (!rows?.length) return null
  let qty = 0
  let revenue = 0
  let cost = 0
  for (const row of rows) {
    const q = Number(row.total_qty) || 0
    const price = Number(row.unit_price)
    const unitCost = productUnitCost(row.own_product_id)
    const rev = !Number.isNaN(price) ? price * q : 0
    const c = unitCost * q
    qty += q
    revenue += rev
    cost += c
  }
  const profit = revenue - cost
  return {
    qty,
    revenue,
    cost,
    profit,
    margin: revenue > 0 ? profit / revenue : null,
  }
}

function formatMrpNum(v: any) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function formatDeltaPp(v: any) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}pt`
}

function formatDeltaPct(v: any) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

async function runSimulateMrp(
  refs: { sales_order_id: number; line_id: number }[],
  opts?: { quiet?: boolean },
) {
  if (!refs.length) return
  mrpRefs.value = refs
  mrpVisible.value = true
  mrpLoading.value = true
  try {
    const res: any = await http.post('/sales-orders/lines/simulate-mrp', {
      lines: refs,
      include_shared: mrpIncludeShared.value,
      shortages_only: mrpShortagesOnly.value,
    })
    mrpResult.value = res.data
    if (!opts?.quiet) {
      if (res.data?.empty_bom) {
        ElMessage.info('所选产品无 BOM 物料')
      } else if (res.data?.kit_ok) {
        ElMessage.success('物料齐套，无缺料')
      }
    }
  } catch {
    mrpResult.value = null
  } finally {
    mrpLoading.value = false
  }
}

function updateIntakeDrawerSize() {
  const w = typeof window !== 'undefined' ? window.innerWidth : 1400
  if (agentPanelOpen.value) {
    if (w <= 720) intakeDrawerSize.value = '100%'
    else if (w <= 1100) intakeDrawerSize.value = `${Math.min(1040, Math.floor(w * 0.96))}px`
    else intakeDrawerSize.value = `${Math.min(1120, Math.floor(w * 0.78))}px`
  } else if (w <= 720) {
    intakeDrawerSize.value = '100%'
  } else {
    intakeDrawerSize.value = `${Math.min(680, Math.floor(w * 0.56))}px`
  }
}

async function loadAgentStatus() {
  try {
    const res: any = await http.get('/schedule/agent/status')
    agentEnabled.value = !!res.data?.enabled
    agentReason.value = res.data?.reason || ''
    if (!agentEnabled.value) {
      agentError.value = agentReason.value || '军师暂不可用'
    }
  } catch {
    agentEnabled.value = false
    agentReason.value = '无法连接军师服务'
    agentError.value = agentReason.value
  }
}

function stopAgentStream() {
  if (agentAbort) {
    agentAbort.abort()
    agentAbort = null
  }
  agentStreaming.value = false
}

function resetIntakeHyp() {
  intakeHyp.qty = null
  intakeHyp.delivery_date = ''
  intakeHyp.is_rush = false
  intakeHyp.default_daily_capacity = null
}

function resetAgentPanel() {
  stopAgentStream()
  if (intakeHypTimer) {
    clearTimeout(intakeHypTimer)
    intakeHypTimer = null
  }
  agentError.value = ''
  agentConversationId.value = null
  agentInput.value = ''
  agentMessages.value = []
  agentStale.value = false
  agentPanelOpen.value = false
  intakeReport.value = null
  intakeLoading.value = false
  resetIntakeHyp()
}

function intakeLinesPayload(rows: any[]) {
  return rows.map((row) => ({
    sales_order_id: row.sales_order_id,
    line_id: row.sales_order_line_id,
  }))
}

function intakeMetricParams(rows: any[]) {
  const params: Record<string, any> = {
    lines: intakeLinesPayload(rows),
    include_shared: mrpIncludeShared.value,
  }
  if (intakeHyp.qty != null && Number(intakeHyp.qty) > 0) {
    params.qty = Number(intakeHyp.qty)
  }
  if (intakeHyp.delivery_date) {
    params.delivery_date = intakeHyp.delivery_date
  }
  if (intakeHyp.is_rush) {
    params.is_rush = true
  }
  if (
    intakeHyp.default_daily_capacity != null &&
    Number(intakeHyp.default_daily_capacity) > 0
  ) {
    params.default_daily_capacity = Number(intakeHyp.default_daily_capacity)
  }
  return params
}

function buildIntakeFollowUpMessage(userQuestion: string) {
  const params = intakeMetricParams(mrpAnalysisRows.value)
  const ctx = JSON.stringify(params)
  const verdict = intakeVerdictLabel.value || '—'
  return [
    userQuestion,
    `（左侧已完成即时诊断，裁决「${verdict}」。上下文 params=${ctx}。`,
    '禁止重复输出利润表/物料明细表；不要从头再讲一遍左侧数字。',
    '若问题涉及改交期/数量/急单/日产能，可重查 analytics.order_intake 并带覆盖参数，只对比变化。',
    '答复：直接回答问题 → 最多 3 条可执行建议。）',
  ].join('')
}

async function openIntakeAgent() {
  if (!agentEnabled.value) {
    ElMessage.warning(agentReason.value || '军师暂不可用')
    return
  }
  agentPanelOpen.value = true
  updateIntakeDrawerSize()
  await nextTick()
  // 不自动开聊：等用户点预制问题或自己输入
}

function closeIntakeAgent() {
  agentPanelOpen.value = false
  updateIntakeDrawerSize()
}

function resetIntakeAgentChat() {
  stopAgentStream()
  agentConversationId.value = null
  agentMessages.value = []
  agentInput.value = ''
  agentStale.value = false
}

async function askIntakePreset(preset: IntakeAgentPreset) {
  if (!agentEnabled.value || agentStreaming.value) return
  await streamAgentMessage(buildIntakeFollowUpMessage(preset.prompt), {
    userVisible: preset.label,
  })
  agentStale.value = false
}

async function sendIntakeFollowUp(suggestedText?: string) {
  const text = (suggestedText ?? agentInput.value).trim()
  if (!text || agentStreaming.value || !agentEnabled.value) return
  agentInput.value = ''
  await streamAgentMessage(buildIntakeFollowUpMessage(text), { userVisible: text })
  agentStale.value = false
}

async function openProductionAnalysis(rows: any[]) {
  const usable = rows.filter((row) => canSimulateMrp(row))
  if (!usable.length) {
    ElMessage.warning('请选择待确认且有数量的产品行')
    return
  }
  mrpAnalysisRows.value = usable
  resetAgentPanel()
  await loadAgentStatus()
  updateIntakeDrawerSize()
  mrpRefs.value = usable.map((row) => ({
    sales_order_id: row.sales_order_id,
    line_id: row.sales_order_line_id,
  }))
  mrpVisible.value = true
  // 默认只跑即时诊断；军师按需打开并选预制问题
  void runSimulateMrp(mrpRefs.value, { quiet: true })
  void loadIntakeReport(usable)
}

async function scrollIntakeChat() {
  await nextTick()
  await intakeChatPanelRef.value?.scrollToBottom()
}

async function loadIntakeReport(rows: any[]) {
  intakeLoading.value = true
  try {
    const res: any = await http.post('/schedule/agent/metrics/query', {
      metric_id: 'analytics.order_intake',
      params: intakeMetricParams(rows),
    })
    const payload = res?.data
    if (payload?.data?.analysis_id === 'order_intake') {
      intakeReport.value = payload.data
    } else if (payload?.analysis_id === 'order_intake') {
      intakeReport.value = payload
    } else if (payload?.data) {
      intakeReport.value = payload.data
    } else {
      intakeReport.value = payload
    }
  } catch (e: any) {
    const profit = buildAnalysisProfit(rows)
    intakeReport.value = {
      summary: e?.error?.message || e?.message || '诊断接口暂不可用',
      data: {
        verdict: profit && profit.profit < 0 ? 'caution' : 'unknown',
        verdict_label: '待补充诊断',
        profit,
      },
    }
  } finally {
    intakeLoading.value = false
  }
}

function onIntakeHypChange() {
  agentStale.value = true
  if (intakeHypTimer) clearTimeout(intakeHypTimer)
  intakeHypTimer = setTimeout(() => {
    intakeHypTimer = null
    void refreshIntakeLeft()
  }, 350)
}

async function refreshIntakeLeft() {
  if (!mrpAnalysisRows.value.length) return
  await loadIntakeReport(mrpAnalysisRows.value)
}

async function streamAgentMessage(message: string, opts?: { userVisible?: string }) {
  const userText = opts?.userVisible || message
  agentMessages.value.push({ role: 'user', content: userText })
  agentMessages.value.push({ role: 'assistant', content: '', streaming: true, charts: [] })
  const assistantIdx = agentMessages.value.length - 1
  agentStreaming.value = true
  agentError.value = ''
  agentAbort = new AbortController()
  await scrollIntakeChat()

  try {
    const res = await fetch('/api/v1/schedule/agent/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
      },
      body: JSON.stringify({
        message,
        conversation_id: agentConversationId.value || undefined,
      }),
      signal: agentAbort.signal,
    })
    if (!res.ok || !res.body) {
      const errText = await res.text().catch(() => '')
      let detail = errText
      try {
        const j = JSON.parse(errText)
        detail = typeof j.detail === 'string' ? j.detail : j.detail?.message || errText
      } catch {
        /* keep */
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    const pendingCharts: ChartSpec[] = []

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        for (const line of part.split('\n')) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const payload = trimmed.slice(5).trim()
          if (!payload || payload === '[DONE]') continue
          let ev: any
          try {
            ev = JSON.parse(payload)
          } catch {
            continue
          }
          const row = agentMessages.value[assistantIdx]
          if (!row || row.role !== 'assistant') continue
          if (ev.type === 'meta' && ev.conversation_id) {
            agentConversationId.value = String(ev.conversation_id)
          } else if (ev.type === 'agent_stage' && ev.label) {
            const activity = [...(row.activity || []), { label: String(ev.label), status: ev.status }]
            row.activity = activity.length > 4 ? [activity[0], ...activity.slice(-3)] : activity
          } else if (ev.type === 'agent_activity' && Array.isArray(ev.items)) {
            row.agents = ev.items
          } else if (ev.type === 'evidence' && Array.isArray(ev.items)) {
            row.evidence = ev.items
          } else if (ev.type === 'todo' && Array.isArray(ev.items)) {
            row.todos = ev.items
          } else if (ev.type === 'token' && ev.text) {
            row.content += String(ev.text)
            await scrollIntakeChat()
          } else if (ev.type === 'chart' && ev.chart) {
            pendingCharts.push(ev.chart as ChartSpec)
          } else if (ev.type === 'done') {
            if (ev.reply && !row.content.trim()) row.content = String(ev.reply)
            if (Array.isArray(ev.evidence)) row.evidence = ev.evidence
            if (Array.isArray(ev.todos)) row.todos = ev.todos
            if (ev.detail?.available && ev.detail.content) row.detail = ev.detail
            if (Array.isArray(ev.charts) && ev.charts.length) {
              row.charts = ev.charts as ChartSpec[]
            } else if (pendingCharts.length) {
              row.charts = pendingCharts
            }
            row.streaming = false
          } else if (ev.type === 'error') {
            throw new Error(ev.message || 'agent_error')
          }
        }
      }
    }
    const row = agentMessages.value[assistantIdx]
    if (row) row.streaming = false
    if (row && !row.content.trim()) {
      agentError.value = '军师未返回内容'
    }
    agentStale.value = false
  } catch (e: any) {
    if (e?.name === 'AbortError') return
    agentError.value = e?.message || '车间军师暂不可用'
    const row = agentMessages.value[assistantIdx]
    if (row) {
      row.streaming = false
      if (!row.content) row.content = agentError.value
    }
  } finally {
    agentStreaming.value = false
    agentAbort = null
    await scrollIntakeChat()
  }
}

async function batchSimulateMrp() {
  await openProductionAnalysis(selectedProductLines.value)
}

async function createDemandPurchaseFromAnalysis() {
  const rows = mrpAnalysisRows.value.filter(
    (row) => canDemandShortage(row) && !row.production_order_id && !row.execution_header_id,
  )
  if (!rows.length) {
    ElMessage.warning('没有要买的料')
    return
  }
  const n = Number(intakeKit.value?.to_buy_lines || intakeKit.value?.shortage_lines || 0)
  await ElMessageBox.confirm(
    `按当前待买（约 ${n} 项）生成采购草稿？\n草稿还没发给供应商，下一步在采购单里下单。`,
    '去买料',
    { type: 'warning', confirmButtonText: '生成草稿' },
  )
  creatingDemandPurchase.value = true
  try {
    const res: any = await http.post('/sales-orders/lines/purchase-drafts-from-mrp', {
      lines: rows.map((row) => ({
        sales_order_id: row.sales_order_id,
        line_id: row.sales_order_line_id,
      })),
      include_shared: true,
      shortages_only: true,
    })
    const count = res.data?.count ?? (res.data?.items || []).length
    ElMessage.success(count ? `已开 ${count} 张草稿，还没发给供应商` : '已处理')
    router.push({ path: '/admin/purchase', query: { tab: 'orders' } })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成失败')
  } finally {
    creatingDemandPurchase.value = false
  }
}

async function confirmFromAnalysis() {
  const rows = mrpAnalysisRows.value.filter((row) => canConfirmLine(row))
  if (!rows.length) {
    ElMessage.warning('没有可确认接单的行（须为草稿且尚未排产）')
    return
  }
  const n = rows.length
  const profit = analysisProfit.value
  const kit = intakeKit.value
  const kitBad = kit && !kit.kit_ok && !kit.empty_bom
  const loss = profit != null && Number(profit.profit) < 0
  let tip =
    n === 1
      ? `确认接单「${rows[0].order_no}」？接单后进入待排产，不生成生产单。`
      : `确认接单选中的 ${n} 个产品行所属订单？接单后进入待排产，不生成生产单。`
  if (loss || kitBad || intakeVerdict.value === 'reject') {
    const warns: string[] = []
    if (loss) warns.push('预估利润为负')
    if (kitBad) warns.push(`仍有缺料 ${kit.shortage_lines || ''} 项`)
    if (intakeVerdict.value === 'reject') warns.push('诊断为不建议接产')
    tip = `${warns.join('，')}。${tip}\n（军师仅建议；确认接单后可去排产或先采长周期料）`
  }
  await ElMessageBox.confirm(tip, '确认接单（人工确认）', {
    type: loss || kitBad || intakeVerdict.value === 'reject' ? 'warning' : 'info',
    confirmButtonText: '确认接单',
    cancelButtonText: '再想想',
  })
  confirmingFromAnalysis.value = true
  try {
    if (n === 1) {
      await http.post(
        `/sales-orders/${rows[0].sales_order_id}/lines/${rows[0].sales_order_line_id}/confirm`,
      )
      await promptGoScheduleAfterConfirm(rows)
    } else {
      const res: any = await http.post('/sales-orders/lines/confirm-batch', {
        lines: rows.map((row) => ({
          sales_order_id: row.sales_order_id,
          line_id: row.sales_order_line_id,
        })),
      })
      const count = res.data?.confirmed_count ?? n
      await promptGoScheduleAfterConfirm(rows, count)
    }
    mrpVisible.value = false
    mrpAnalysisRows.value = []
    mrpRefs.value = []
    resetAgentPanel()
    await load()
  } finally {
    confirmingFromAnalysis.value = false
  }
}

async function cancelFromAnalysis() {
  const orderMap = new Map<number, string>()
  for (const row of mrpAnalysisRows.value) {
    if (!canCancelOrder(row)) continue
    orderMap.set(Number(row.sales_order_id), row.order_no || String(row.sales_order_id))
  }
  const orders = [...orderMap.entries()]
  if (!orders.length) {
    ElMessage.warning('没有可取消的订单')
    return
  }
  const names = orders.map(([, no]) => `「${no}」`).join('、')
  await ElMessageBox.confirm(
    orders.length === 1
      ? `取消订单 ${names}？\n订单将标记为已取消，记录仍保留（与删除明细不同）。`
      : `取消以下 ${orders.length} 个订单？\n${names}\n订单将标记为已取消，记录仍保留（与删除明细不同）。`,
    '取消订单',
    { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '返回' },
  )
  cancellingFromAnalysis.value = true
  try {
    for (const [id] of orders) {
      await http.post(`/sales-orders/${id}/cancel`)
    }
    ElMessage.success(orders.length === 1 ? '订单已取消' : `已取消 ${orders.length} 个订单`)
    mrpVisible.value = false
    mrpAnalysisRows.value = []
    mrpRefs.value = []
    resetAgentPanel()
    await load()
  } finally {
    cancellingFromAnalysis.value = false
  }
}

function goExecution(row: { execution_header_id?: number; production_order_id?: number }) {
  if (row.execution_header_id) {
    void router.push({
      path: '/admin/executions',
      query: { header_id: String(row.execution_header_id) },
    })
    return
  }
  if (row.production_order_id) {
    void router.push({
      path: '/admin/executions',
      query: { shop_order_id: String(row.production_order_id) },
    })
  }
}

function goProductionOrder(productionOrderId?: number) {
  // 兼容旧调用：改跳执行单
  goExecution({ production_order_id: productionOrderId })
}

function hasOpenSelectOrPicker() {
  return Boolean(
    document.querySelector(
      '.el-select__popper:not([aria-hidden="true"]), .el-picker__popper:not([aria-hidden="true"])',
    ),
  )
}

function onEditHotkey(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
    if (inlineLine.value) {
      e.preventDefault()
      void saveInlineLine()
    } else if (headerDialogVisible.value) {
      e.preventDefault()
      void saveHeader()
    }
    return
  }
  if (e.key === 'Escape') {
    if (hasOpenSelectOrPicker()) return
    if (inlineLine.value) {
      e.preventDefault()
      cancelInlineLine()
    } else if (headerDialogVisible.value) {
      e.preventDefault()
      headerDialogVisible.value = false
    }
  }
}

onActivated(() => {
  showSizes.value = readShowSizesPref()
})

onMounted(async () => {
  window.addEventListener('keydown', onEditHotkey)
  window.addEventListener('resize', updateIntakeDrawerSize)
  updateIntakeDrawerSize()
  await loadMasters()
  await load()
  await nextTick()
  measureTableHeight()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onEditHotkey)
  window.removeEventListener('resize', updateIntakeDrawerSize)
  resetAgentPanel()
})
</script>

<style scoped>
.view-mode {
  margin-left: 8px;
}
.so-biz-tag {
  margin-left: 6px;
  flex-shrink: 0;
}
.page-hero {
  align-items: center;
}
.so-status-stats {
  gap: 8px;
}
.so-stat-chip {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 72px;
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
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
  line-height: 1.2;
}
.so-stat-num {
  font-size: 18px;
  font-weight: 750;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.so-stat-chip.tone-pending-confirm .so-stat-num {
  color: #64748b;
}
.so-stat-chip.tone-pending-production .so-stat-num {
  color: #b45309;
}
.so-stat-chip.tone-in-progress .so-stat-num {
  color: #1d4ed8;
}
.so-stat-chip.tone-completed .so-stat-num {
  color: #15803d;
}
.so-stat-chip.tone-cancelled .so-stat-num {
  color: #94a3b8;
}
.so-table-host {
  min-width: 0;
}
:deep(.so-production-table .el-scrollbar__bar.is-horizontal) {
  display: none;
}
:deep(.so-production-table .el-scrollbar__wrap) {
  overflow-x: hidden;
}
.view-hint {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.35;
}
.so-order-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  padding: 2px 4px;
  text-align: center;
}
.so-order-no {
  font-weight: 650;
  color: #0f172a;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.so-order-no-btn {
  appearance: none;
  border: 0;
  background: transparent;
  padding: 0;
  margin: 0;
  font: inherit;
  font-weight: 650;
  color: var(--el-color-primary);
  font-size: 13px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  text-align: center;
  display: block;
  width: 100%;
}
.so-order-no-btn:hover {
  text-decoration: underline;
}
.so-sizes-header {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}
.so-sizes-edit-btn {
  padding: 0 2px !important;
  height: auto !important;
  min-height: 0 !important;
}
.so-import-lead {
  margin: 0 0 12px;
  line-height: 1.5;
}
.so-import-file-row {
  margin-bottom: 8px;
}
.so-import-drop {
  position: relative;
  width: 100%;
  min-height: 108px;
  padding: 18px 16px;
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 8px,
      #f8fafc 8px,
      #f8fafc 16px
    );
  text-align: center;
  cursor: pointer;
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.so-import-drop:hover,
.so-import-drop.is-dragging {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.18);
}
.so-import-drop.has-file {
  background: #f8fafc;
}
.so-import-drop-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}
.so-import-file-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  word-break: break-all;
}
.so-import-file-meta {
  margin-top: 4px;
  font-size: 12px;
}
.so-import-clear-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  appearance: none;
  border: 0;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  background: rgba(15, 23, 42, 0.72);
  color: #fff;
  cursor: pointer;
}
.so-import-file-input {
  display: none;
}
.so-import-todo {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 6px;
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.35;
}
.so-import-todo.is-pending {
  background: #fff7ed;
  color: #9a3412;
  border: 1px solid #fed7aa;
}
.so-import-todo.is-ready {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}
.so-import-todo-label {
  font-weight: 600;
  margin-right: 4px;
}
.so-import-todo-label.is-ok {
  color: #166534;
}
.so-import-todo-chip {
  color: inherit;
}
.so-import-done {
  padding: 24px 8px 12px;
  text-align: center;
}
.so-import-done-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 6px;
}
.so-import-warnings,
.so-import-alerts {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.so-import-warnings {
  background: #fff7ed;
  color: #9a3412;
}
.so-import-alerts {
  background: #fef2f2;
  color: #991b1b;
}
.so-import-block-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  margin: 2px 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}
.so-import-block-sub {
  font-weight: 400;
  font-size: 12px;
}
.so-import-head-form :deep(.el-form-item) {
  margin-bottom: 8px;
}
.so-import-head-form :deep(.el-form-item__label) {
  margin-bottom: 2px !important;
  line-height: 1.2;
  font-size: 12px;
}
.so-import-head-grid {
  display: grid;
  grid-template-columns: 1.1fr 1fr 1fr 1.2fr;
  gap: 0 10px;
}
.so-import-mid-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0 12px;
  align-items: start;
}
.so-import-mid-grid.has-images {
  grid-template-columns: 1.25fr 1fr;
}
.so-import-notes-item {
  margin-bottom: 6px !important;
}
.so-import-notes-item :deep(textarea) {
  min-height: 110px !important;
}
.so-import-inline-label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}
.so-import-field-hint {
  margin-top: 2px;
  font-size: 11px;
  color: #64748b;
  line-height: 1.3;
}
.so-import-field-hint.is-warn {
  color: #c2410c;
}
.so-import-head-form :deep(.el-form-item.is-error .el-input__wrapper),
.so-import-head-form :deep(.el-form-item.is-error .el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
.so-import-images {
  margin-top: 0;
  padding-top: 22px;
}
.so-import-image-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 0;
}
.so-import-image-card {
  width: 88px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.so-import-image-thumb {
  width: 88px;
  height: 58px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: #f8fafc;
}
.so-import-raw-code {
  margin-top: 2px;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.3;
}
.so-import-attr {
  font-size: 12px;
  line-height: 1.35;
  word-break: break-all;
}
.so-import-attr.is-mismatch {
  color: #b91c1c;
  font-weight: 600;
}
.so-import-attr-sys {
  margin-top: 2px;
  font-size: 11px;
  font-weight: 400;
  color: #c2410c;
  line-height: 1.3;
}
.so-import-todo-mismatch {
  flex-basis: 100%;
  margin-top: 0;
  font-size: 11px;
  color: #c2410c;
}
.so-import-lines :deep(.so-import-line-warn) > td {
  background: #fffbeb !important;
}
.so-import-lines :deep(.so-import-line-mismatch) > td {
  background: #fff7ed !important;
}
.so-import-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.so-import-footer-right {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.so-import-dialog :deep(.el-dialog) {
  margin-top: 4vh !important;
}
.so-import-dialog.is-review :deep(.el-dialog) {
  width: min(1400px, 92vw) !important;
}
.so-import-dialog:not(.is-review) :deep(.el-dialog) {
  width: min(560px, 92vw) !important;
}
.so-import-dialog :deep(.el-dialog__header) {
  padding: 12px 16px 8px;
  margin-right: 0;
}
.so-import-dialog :deep(.el-dialog__body) {
  padding: 4px 16px 8px;
  max-height: min(82vh, 860px);
  overflow: auto;
}
.so-import-dialog :deep(.el-dialog__footer) {
  padding: 8px 16px 12px;
}
.so-import-lines {
  width: 100%;
}
/* 勿强制 overflow:visible，否则横向滚动时表头与正文不同步 */
.so-size-add-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.so-order-req-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.so-order-req-logo {
  width: 100%;
  max-height: 120px;
  border-radius: 6px;
  background: #f8fafc;
}
.so-order-req-logo :deep(.el-image__inner) {
  max-height: 120px;
  object-fit: contain;
}
.so-order-req-img {
  width: 100%;
  max-height: 220px;
  border-radius: 6px;
  background: #f8fafc;
}
.so-order-req-img :deep(.el-image__inner) {
  max-height: 220px;
  object-fit: contain;
}
.so-notes-img-box {
  width: 100%;
  max-width: 360px;
}
.so-notes-img-preview {
  width: 100%;
  height: 160px;
}
.so-order-req-text {
  font-size: 13px;
  line-height: 1.5;
  color: #0f172a;
  white-space: pre-wrap;
  word-break: break-word;
}
.so-logo-box {
  position: relative;
  width: 160px;
  cursor: pointer;
  outline: none;
}
.so-logo-box.is-readonly {
  cursor: default;
}
.so-logo-box.is-uploading {
  pointer-events: none;
  opacity: 0.75;
}
.so-logo-box.is-dragging .so-logo-preview {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.25);
}
.so-logo-preview {
  width: 160px;
  height: 96px;
  border-radius: 8px;
  border: 1px dashed var(--el-border-color);
  background: #fff;
  display: block;
}
.so-logo-preview.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  background:
    repeating-linear-gradient(
      -45deg,
      #fff,
      #fff 8px,
      #f1f5f9 8px,
      #f1f5f9 16px
    );
}
.so-logo-preview :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.so-logo-drop-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(64, 158, 255, 0.12);
  color: var(--el-color-primary);
  font-size: 13px;
  font-weight: 600;
  pointer-events: none;
}
.so-logo-clear-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  appearance: none;
  border: 0;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  background: rgba(15, 23, 42, 0.72);
  color: #fff;
  cursor: pointer;
}
.so-logo-file-input {
  display: none;
}
.so-text-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.so-product-code-btn {
  font-size: 11px !important;
  max-width: 100%;
  height: auto !important;
  padding: 0 !important;
  vertical-align: middle;
  display: inline-flex !important;
  justify-content: center;
}
.so-product-code-btn :deep(span) {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.so-product-code-text {
  font-size: 11px;
}
.so-detail-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
.so-detail-summary {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.so-add-line-quiet {
  appearance: none;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--el-color-primary);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
}
.so-add-line-quiet:hover {
  text-decoration: underline;
}
:deep(.so-grouped-table .el-table__body td.el-table__cell:nth-child(-n + 3)) {
  vertical-align: middle;
}
/* 关默认行 hover，改由订单/明细两套 class 控制 */
:deep(.so-grouped-table .el-table__body tr.order-group-even:hover:not(.order-hover):not(.line-hover) > td.el-table__cell) {
  background: #fff !important;
}
:deep(.so-grouped-table .el-table__body tr.order-group-odd:hover:not(.order-hover):not(.line-hover) > td.el-table__cell) {
  background: #f3f5f8 !important;
}
/* 同一订单头+明细同色；相邻订单交替底色 */
:deep(.so-grouped-table .order-group-even > td.el-table__cell) {
  background: #fff !important;
}
:deep(.so-grouped-table .order-group-odd > td.el-table__cell) {
  background: #f3f5f8 !important;
}
/* hover 订单头三列：整单浅蓝 */
:deep(.so-grouped-table .el-table__body tr.order-hover > td.el-table__cell),
:deep(.so-grouped-table .el-table__body tr.order-hover:hover > td.el-table__cell) {
  background: #e8f1ff !important;
}
/* hover 明细列：仅当前行 */
:deep(.so-grouped-table .el-table__body tr.line-hover > td.el-table__cell),
:deep(.so-grouped-table .el-table__body tr.line-hover:hover > td.el-table__cell) {
  background: #dbeafe !important;
}
:deep(.so-grouped-table .order-group-editing > td.el-table__cell) {
  background: #eff6ff !important;
}
:deep(.so-grouped-table .el-table__body tr.order-group-editing.line-hover > td.el-table__cell),
:deep(.so-grouped-table .el-table__body tr.order-group-editing.order-hover > td.el-table__cell),
:deep(.so-grouped-table .el-table__body tr.order-group-editing.line-hover:hover > td.el-table__cell),
:deep(.so-grouped-table .el-table__body tr.order-group-editing.order-hover:hover > td.el-table__cell) {
  background: #dbeafe !important;
}
:deep(.so-grouped-table .order-group-summary > td.el-table__cell) {
  /* 背景随订单奇偶色，不再单独着色 */
  font-variant-numeric: tabular-nums;
}
.so-summary-label {
  font-weight: 650;
  color: #334155;
  font-size: 12px;
}
.so-summary-num {
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.so-progress-cell {
  appearance: none;
  display: inline-flex;
  align-items: center;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  line-height: 1.3;
  max-width: 100%;
}
.so-progress-cell:hover .so-progress-main {
  color: var(--el-color-primary);
}
.so-progress-main {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.so-progress-cell--summary .so-progress-main {
  font-weight: 600;
}
.so-progress-drawer-meta {
  margin: 0 0 10px;
  font-size: 13px;
}
.so-progress-drawer-sum {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 12px;
  margin-bottom: 14px;
  font-size: 13px;
}
.so-progress-drawer-actions {
  margin-top: 12px;
}
.so-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: nowrap;
  line-height: 1;
}
.so-status-link {
  display: inline-flex;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  vertical-align: middle;
}
.so-status-link:hover :deep(.el-tag) {
  color: #005fcc;
  border-color: #80baff;
}
.so-actions :deep(.el-tooltip__trigger),
.so-actions :deep(.el-dropdown) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0;
  line-height: 1;
  vertical-align: middle;
}
.so-action-hit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin: 0;
  padding: 0;
  line-height: 1;
  cursor: pointer;
}
.so-actions :deep(.el-button) {
  margin: 0;
  padding: 0;
  width: 22px;
  height: 22px;
}
.so-actions :deep(.el-button .el-icon) {
  margin: 0;
}
:deep(.so-grouped-table .so-actions-col) {
  padding-left: 8px !important;
  padding-right: 14px !important;
}
:deep(.so-grouped-table th.so-actions-col) {
  padding-left: 8px !important;
  padding-right: 14px !important;
}
.mrp-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 14px 0 12px;
}
.mrp-section-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}
:deep(.mrp-material-table .mrp-row-shortage > td.el-table__cell) {
  background: #fef2f2 !important;
}
:deep(.mrp-material-table .mrp-row-ok > td.el-table__cell) {
  background: #f0fdf4 !important;
}
:deep(.mrp-material-table .el-table__body .mrp-row-shortage:hover > td.el-table__cell) {
  background: #fee2e2 !important;
}
:deep(.mrp-material-table .el-table__body .mrp-row-ok:hover > td.el-table__cell) {
  background: #dcfce7 !important;
}
:deep(.intake-mat-table .mrp-row-shortage > td.el-table__cell) {
  background: #fffaf9 !important;
}
:deep(.intake-mat-table .mrp-row-ok > td.el-table__cell) {
  background: transparent !important;
}
:deep(.intake-mat-table .el-table__body .mrp-row-shortage:hover > td.el-table__cell) {
  background: #fef2f2 !important;
}
:deep(.intake-mat-table .el-table__body .mrp-row-ok:hover > td.el-table__cell) {
  background: #f8fafc !important;
}
.mrp-shortage-num {
  color: #dc2626;
}
.analysis-profit {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.analysis-profit-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.analysis-profit-label {
  font-size: 12px;
  color: #64748b;
}
.analysis-profit-card strong {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.profit-pos {
  color: #15803d;
}
.profit-neg {
  color: #dc2626;
}
.mrp-hint {
  font-size: 12px;
}
.mrp-skipped {
  margin: 10px 0 0;
  font-size: 12px;
}
.intake-drawer-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.intake-split {
  display: flex;
  flex-direction: row;
  gap: 0;
  flex: 1;
  min-height: 0;
  height: 100%;
}
.intake-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.intake-pane-left {
  flex: 1.7 1 0;
  padding-right: 14px;
  overflow: auto;
  border-right: 1px solid #e6ebf2;
}
.intake-split.is-solo .intake-pane-left {
  flex: 1 1 auto;
  max-width: none;
  padding-right: 0;
  border-right: none;
}
.intake-pane-right {
  flex: 1 1 0;
  max-width: 38%;
  padding-left: 16px;
  gap: 8px;
}
.intake-pane-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-bottom: 8px;
}
.intake-pane-title {
  font-size: 13px;
  font-weight: 650;
  color: #0f172a;
}
.intake-pane-head-spacer {
  flex: 1;
}
.intake-board {
  min-height: 100%;
  padding-bottom: 8px;
}
.intake-sheet {
  background: #fff;
  border: 1px solid #e5eaf1;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.intake-hero {
  padding: 20px 20px 18px;
  position: relative;
}
.intake-hero::after {
  content: '';
  position: absolute;
  left: 20px;
  right: 20px;
  bottom: 0;
  height: 1px;
  background: rgba(15, 23, 42, 0.06);
}
.intake-hero.tone-ok {
  background: linear-gradient(180deg, #f0fdf6 0%, #ffffff 78%);
}
.intake-hero.tone-warn {
  background: linear-gradient(180deg, #fff8eb 0%, #ffffff 78%);
}
.intake-hero.tone-bad {
  background: linear-gradient(180deg, #fff5f5 0%, #ffffff 78%);
}
.intake-hero.tone-neutral {
  background: linear-gradient(180deg, #f7f9fc 0%, #ffffff 78%);
}
.intake-hero-kicker {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #94a3b8;
}
.intake-sim-pill {
  margin-left: auto;
  text-transform: none;
  letter-spacing: 0;
  font-size: 11px;
  font-weight: 650;
  color: #1d4ed8;
  background: #eff6ff;
  border-radius: 999px;
  padding: 2px 9px;
}
.intake-hero-title {
  margin: 0;
  font-size: 26px;
  font-weight: 720;
  letter-spacing: -0.03em;
  line-height: 1.2;
  color: #0f172a;
}
.intake-hero.tone-ok .intake-hero-title { color: #166534; }
.intake-hero.tone-warn .intake-hero-title { color: #9a3412; }
.intake-hero.tone-bad .intake-hero-title { color: #b91c1c; }
.intake-hero-lead {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: #475569;
}
.intake-hero-rest {
  margin: 8px 0 0;
  padding: 0 0 0 16px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.55;
}
.intake-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: #fbfcfe;
  border-bottom: 1px solid #eef2f7;
}
.intake-toolbar-label {
  font-size: 12px;
  font-weight: 650;
  color: #94a3b8;
}
.intake-hyp-qty { width: 84px; }
.intake-hyp-date { width: 140px; }
.intake-hyp-cap { width: 88px; }
.intake-hyp-unit {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 2px;
  white-space: nowrap;
}
.intake-recalc-btn { margin-left: auto; }
.intake-label,
.intake-meta {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 0.02em;
}
.intake-kpi {
  padding: 18px 20px 16px;
  border-bottom: 1px solid #eef2f7;
}
.intake-kpi-hero {
  margin-bottom: 14px;
}
.intake-kpi-xl {
  display: block;
  margin-top: 2px;
  font-size: 34px;
  font-weight: 740;
  letter-spacing: -0.04em;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
}
.intake-kpi-note {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}
.intake-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  border: 1px solid #eef2f7;
  border-radius: 12px;
  overflow: hidden;
  background: #fafbfc;
}
.intake-kpi-cell {
  padding: 10px 12px;
  min-width: 0;
}
.intake-kpi-cell + .intake-kpi-cell {
  border-left: 1px solid #eef2f7;
}
.intake-kpi-cell b {
  display: block;
  margin-top: 3px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-kpi-xl.is-pos,
.intake-kpi-cell b.is-pos { color: #15803d; }
.intake-kpi-xl.is-neg,
.intake-kpi-cell b.is-neg { color: #dc2626; }
.intake-status {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid #eef2f7;
  background: #fcfdff;
}
.intake-status-item {
  padding: 12px 12px 11px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eef2f7;
  border-left-width: 3px;
  border-left-color: #cbd5e1;
  min-width: 0;
}
.intake-status-item.is-ok { border-left-color: #22c55e; }
.intake-status-item.is-warn { border-left-color: #f59e0b; }
.intake-status-item.is-bad { border-left-color: #ef4444; }
.intake-status-item strong {
  display: block;
  margin-top: 4px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.35;
  word-break: break-word;
}
.intake-status-item.is-ok strong { color: #166534; }
.intake-status-item.is-warn strong { color: #9a3412; }
.intake-status-item.is-bad strong { color: #b91c1c; }
.intake-status-item em {
  display: block;
  margin-top: 4px;
  font-style: normal;
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-blocks {
  display: flex;
  flex-direction: column;
}
.intake-block {
  padding: 16px 20px 14px;
  border-bottom: 1px solid #eef2f7;
}
.intake-block:last-child {
  border-bottom: none;
}
.intake-block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.intake-block-head h3,
.intake-suggest-head h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}
.intake-mat-table {
  border-left: none !important;
  border-right: none !important;
  border-radius: 8px;
  overflow: hidden;
}
.intake-mat-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.intake-curve-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.intake-curve-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 52px;
  gap: 10px;
  align-items: center;
}
.intake-curve-size {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}
.intake-curve-bars {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.intake-curve-track {
  height: 5px;
  border-radius: 999px;
  background: #f1f5f9;
  overflow: hidden;
}
.intake-curve-fill {
  height: 100%;
  border-radius: 999px;
}
.intake-curve-fill.is-this { background: #0076ff; }
.intake-curve-fill.is-hist { background: #94a3b8; }
.intake-curve-delta {
  font-size: 12px;
  font-weight: 700;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #64748b;
}
.intake-curve-delta.is-pos { color: #b45309; }
.intake-curve-delta.is-neg { color: #0369a1; }
.intake-curve-delta.is-hot { color: #b91c1c; }
.intake-curve-legend {
  display: flex;
  gap: 14px;
  font-size: 11px;
  color: #94a3b8;
}
.intake-curve-legend .lg {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
}
.intake-curve-legend .lg.is-this { background: #0076ff; }
.intake-curve-legend .lg.is-hist { background: #94a3b8; }
.intake-contend-list {
  display: flex;
  flex-direction: column;
}
.intake-contend-item {
  padding: 10px 0;
}
.intake-contend-item + .intake-contend-item {
  border-top: 1px dashed #eef2f7;
}
.intake-contend-item.is-conflict {
  margin: 0 -8px;
  padding-left: 8px;
  padding-right: 8px;
  border-radius: 8px;
  background: #fff8f7;
}
.intake-contend-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
.intake-contend-name {
  font-size: 13px;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-contend-gap {
  font-size: 12px;
  font-weight: 700;
  color: #b91c1c;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.intake-contend-subs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 6px;
}
.intake-mini-tag {
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  border-radius: 999px;
  padding: 2px 8px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-mini-tag.is-peer {
  background: #eff6ff;
  color: #1d4ed8;
}
.intake-cost-list {
  display: flex;
  flex-direction: column;
}
.intake-cost-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
}
.intake-cost-row + .intake-cost-row {
  border-top: 1px dashed #eef2f7;
}
.intake-cost-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.intake-cost-main strong {
  font-size: 13px;
  color: #0f172a;
}
.intake-cost-delta {
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.intake-cost-delta.is-pos { color: #b45309; }
.intake-cost-delta.is-neg { color: #15803d; }
.intake-cost-delta.is-hot { color: #b91c1c; }
.intake-impact-rows {
  display: flex;
  flex-direction: column;
}
.intake-impact-row {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) auto minmax(0, 1.4fr);
  gap: 8px;
  align-items: center;
  padding: 8px 0;
}
.intake-impact-row + .intake-impact-row {
  border-top: 1px dashed #eef2f7;
}
.intake-impact-no {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-impact-delay {
  font-size: 11px;
  font-weight: 700;
  color: #b91c1c;
  background: #fef2f2;
  border-radius: 999px;
  padding: 1px 7px;
  font-variant-numeric: tabular-nums;
}
.intake-impact-risk {
  font-size: 12px;
  color: #64748b;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.intake-impact-risk i {
  font-style: normal;
  margin: 0 4px;
  color: #cbd5e1;
}
.intake-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding-right: 8px;
}
.intake-drawer-header-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.intake-drawer-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
}
.intake-suggest {
  padding: 16px 20px 18px;
  background: linear-gradient(180deg, #fffdf8 0%, #ffffff 100%);
  border-top: 1px solid #f3e8d4;
}
.intake-suggest-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.intake-suggest-list {
  margin: 0;
  padding: 0 0 0 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.intake-suggest-list li {
  font-size: 13px;
  line-height: 1.5;
  color: #334155;
}
.intake-suggest-list li.tone-high {
  color: #9a3412;
}
.intake-ask-link {
  display: inline-flex;
  margin-top: 12px;
  padding: 0;
  border: 0;
  background: none;
  color: #0076ff;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.intake-ask-link:hover {
  text-decoration: underline;
}
.intake-stale-banner {
  margin: 0;
  padding: 6px 8px;
  font-size: 12px;
  color: #92400e;
  background: #fffbeb;
  border-radius: 6px;
  border: 1px solid #fde68a;
  flex-shrink: 0;
}
.intake-chat-panel {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}
.intake-chat-empty {
  padding: 12px;
  text-align: center;
  font-size: 12px;
}
.intake-presets {
  flex-shrink: 0;
  padding: 0 2px 10px;
}
.intake-presets-lead {
  margin: 0 0 8px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}
.intake-preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.intake-preset-chip {
  appearance: none;
  border: 1px solid #dbe3ef;
  background: #fff;
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.35;
  padding: 7px 11px;
  border-radius: 999px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.12s ease, background 0.12s ease, color 0.12s ease;
}
.intake-preset-chip:hover:not(:disabled) {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}
.intake-preset-chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.intake-agent-off {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 4px;
  padding: 24px 12px;
  font-size: 13px;
  text-align: center;
}
.intake-agent-off p {
  margin: 0;
}
.intake-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.intake-footer-spacer {
  flex: 1;
}
.shared-switch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
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
.mat-image-empty {
  line-height: 1.45;
  display: inline-block;
}
.size-qty-input {
  width: 100%;
}
.size-qty-input :deep(.el-input__wrapper) {
  padding: 0;
}
.size-qty-input :deep(.el-input__inner) {
  text-align: center;
  padding: 0 1px;
}
/* 行内编辑：控件左右 padding 收紧，窄列也能看清更多内容 */
:deep(.so-grouped-table .order-group-editing .el-input__wrapper),
:deep(.so-grouped-table .order-group-editing .el-select__wrapper) {
  padding-left: 4px !important;
  padding-right: 4px !important;
}
:deep(.so-grouped-table .order-group-editing .el-input__inner) {
  padding-left: 0;
  padding-right: 0;
}
:deep(.so-grouped-table .order-group-editing .el-select__wrapper) {
  gap: 2px;
  min-height: 24px;
}
:deep(.so-grouped-table .order-group-editing .el-select__suffix) {
  width: 14px;
}
:deep(.so-grouped-table .order-group-editing .el-select__caret) {
  font-size: 12px;
}
:deep(.so-grouped-table .order-group-editing .el-date-editor .el-input__prefix) {
  display: none;
}
:deep(.so-grouped-table .order-group-editing .el-date-editor .el-input__wrapper) {
  padding-left: 4px !important;
  padding-right: 4px !important;
}
:deep(td.size-col .cell),
:deep(th.size-col .cell) {
  font-size: 11px;
}
:deep(.el-table .product-group-even > td.el-table__cell) {
  background: var(--el-fill-color-blank);
}
:deep(.el-table .product-group-odd > td.el-table__cell) {
  background: var(--el-fill-color-light);
}
:deep(.el-table--enable-row-hover .product-group-even:hover > td.el-table__cell),
:deep(.el-table--enable-row-hover .product-group-odd:hover > td.el-table__cell) {
  background: var(--el-fill-color-light);
}
:deep(td.size-col) {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(th.size-col) {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(td.size-col .cell) {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(th.size-col .cell) {
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(.so-admin-compact-table .el-table__cell) {
  padding-top: 1px !important;
  padding-bottom: 1px !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(.so-admin-compact-table .el-table__header-cell) {
  padding-top: 2px !important;
  padding-bottom: 2px !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
  text-align: center !important;
}
:deep(.so-admin-compact-table .el-table__cell .cell),
:deep(.so-admin-compact-table .el-table__header-cell .cell) {
  line-height: 1.2;
  padding-left: 0 !important;
  padding-right: 0 !important;
}
:deep(.so-admin-compact-table .el-table__header-cell .cell) {
  display: block;
  text-align: center !important;
}
:deep(.so-admin-compact-table .el-table__cell .cell) {
  display: block;
  text-align: center !important;
}
.muted {
  color: #94a3b8;
}
.notes-cell {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
</style>

<style>
/* drawer 挂到 body，需非 scoped */
.intake-drawer.el-drawer {
  --el-drawer-padding-primary: 12px 14px;
}
.so-order-req-popper.el-popover {
  padding: 12px;
  max-width: 360px;
}
.so-sizes-editor-dialog.el-dialog {
  margin-top: 6vh !important;
}
.so-sizes-editor-dialog .el-dialog__body {
  padding-top: 8px;
  padding-bottom: 8px;
}
.so-sizes-editor-dialog .so-sizes-editor-table .el-table__header th {
  padding: 4px 0;
  height: 28px;
  font-size: 12px;
}
.so-sizes-editor-dialog .so-sizes-editor-table .el-table__cell {
  padding: 2px 0;
}
.so-sizes-editor-dialog .so-sizes-editor-table .el-table__row {
  height: 28px;
}
.so-sizes-editor-dialog .so-sizes-editor-table .cell {
  padding: 0 8px;
  line-height: 24px;
}
.intake-drawer .el-drawer__body {
  display: flex;
  flex-direction: column;
  height: calc(100% - 55px);
  padding: 0 14px 12px;
  overflow: hidden;
  box-sizing: border-box;
  background: #f3f5f8;
}
.intake-drawer .el-drawer__footer {
  padding: 10px 14px 14px;
  border-top: 1px solid #e6ebf2;
}
@media (max-width: 900px) {
  .intake-drawer .intake-split {
    flex-direction: column;
  }
  .intake-drawer .intake-pane-left {
    flex: 0 1 auto;
    max-width: none;
    max-height: 54%;
    padding-right: 0;
    padding-bottom: 10px;
    border-right: none;
    border-bottom: 1px solid #e8eef5;
  }
  .intake-drawer .intake-pane-right {
    flex: 1 1 auto;
    max-width: none;
    padding-left: 0;
    padding-top: 8px;
    min-height: 220px;
  }
  .intake-drawer .intake-hero-title {
    font-size: 22px;
  }
  .intake-drawer .intake-kpi-xl {
    font-size: 28px;
  }
  .intake-drawer .intake-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .intake-drawer .intake-kpi-cell:nth-child(3) {
    border-left: none;
  }
  .intake-drawer .intake-kpi-cell:nth-child(n + 3) {
    border-top: 1px solid #eef2f7;
  }
  .intake-drawer .intake-recalc-btn {
    margin-left: 0;
  }
}
@media (max-width: 640px) {
  .intake-drawer .el-drawer__body {
    padding: 0 10px 10px;
  }
}
</style>
