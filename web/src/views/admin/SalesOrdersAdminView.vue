<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">订单管理</h1>
        <p class="page-desc">订单信息合并 · 明细行内编辑 · 产品视图可批量生产分析</p>
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
          :placeholder="viewMode === 'product' ? '产品编号' : '订单号 / 客户'"
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
          <el-option label="待生产" value="pending_production" />
          <el-option label="生产中" value="in_progress" />
          <el-option label="已完成" value="completed" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button>
        <el-radio-group v-model="viewMode" class="view-mode" @change="onViewModeChange">
          <el-radio-button value="split">订单视图</el-radio-button>
          <el-radio-button value="product">产品视图</el-radio-button>
        </el-radio-group>
        <el-button
          v-if="viewMode === 'product'"
          type="primary"
          :disabled="!selectedProductLines.length"
          :loading="mrpLoading"
          @click="batchSimulateMrp"
        >
          生产分析{{ selectedProductLines.length ? ` (${selectedProductLines.length})` : '' }}
        </el-button>
        <div class="spacer" />
        <el-button type="primary" :disabled="viewMode !== 'split'" @click="startCreate">
          新建订单
        </el-button>
      </div>

      <div ref="tableHostRef" class="so-table-host">
      <!-- 订单视图：订单信息列 rowspan 合并 + 明细同行 -->
      <template v-if="viewMode === 'split'">
        <el-table
          ref="groupTableRef"
          :data="displayGroupedRows"
          border
          class="so-admin-compact-table so-grouped-table"
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
            label="产品编号"
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
          <el-table-column column-key="sizes" label="码数" align="center" class-name="size-group-col" resizable>
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
              <el-tag v-else size="small" :type="lineStatusTagType(row)">
                {{ lineStatusLabel(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            column-key="actions"
            label="操作"
            width="100"
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
                        生产分析
                      </el-dropdown-item>
                      <el-dropdown-item v-if="row.production_order_id" command="production">
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
          label="产品编号"
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
        <el-table-column column-key="sizes" label="码数" align="center" class-name="size-group-col" resizable>
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
            <template #default="{ row }">{{ sizeQty(row, s.id) }}</template>
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
            <el-tag size="small" :type="lineStatusTagType(row)">
              {{ lineStatusLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          column-key="actions"
          label="操作"
          width="56"
          align="center"
          fixed="right"
          :resizable="false"
        >
          <template #default="{ row }">
            <el-dropdown
              v-if="hasLineMoreActions(row)"
              trigger="click"
              @command="(cmd: string) => onLineMore(row, cmd)"
            >
              <el-button link type="primary" :icon="MoreFilled" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="canSimulateMrp(row)" command="mrp">
                    生产分析
                  </el-dropdown-item>
                  <el-dropdown-item v-if="row.production_order_id" command="production">
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
          </template>
        </el-table-column>
      </el-table>
      </div>

      <p v-if="viewMode === 'product'" class="view-hint muted">
        产品视图按产品编号排序平铺，勾选待产行后可批量生产分析（物料缺口 · 利润 · 确认生产）。
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

    <!-- 订单详情 / 新建：订单级字段 + 用料预览（读产品 BOM，不落销售用料账） -->
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
      </el-form>

      <div v-if="headerDraft.id" class="so-bom-block">
        <div class="so-bom-head">
          <h4 class="so-bom-title">BOM 用料预览</h4>
          <span class="so-bom-meta">按产品 BOM × 明细双数估算 · 未写入销售单 · 下生产后以生产单用料为准</span>
        </div>
        <el-table
          :data="headerBomRows"
          size="small"
          border
          class="so-bom-table"
          empty-text="暂无明细或产品未建 BOM"
          max-height="280"
        >
          <el-table-column prop="product_code" label="工厂型号" min-width="100" show-overflow-tooltip />
          <el-table-column prop="color_name" label="颜色" width="72" show-overflow-tooltip />
          <el-table-column prop="material_code" label="物料编号" width="100" show-overflow-tooltip />
          <el-table-column prop="material_name" label="物料名称" min-width="120" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="56" />
          <el-table-column prop="qty_per_pair" label="单耗" width="72" align="right">
            <template #default="{ row }">
              <span v-if="row.empty" class="muted">—</span>
              <span v-else>{{ formatBomQty(row.qty_per_pair) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="pairs" label="双数" width="64" align="right">
            <template #default="{ row }">{{ row.pairs }}</template>
          </el-table-column>
          <el-table-column prop="required" label="估算需求" width="88" align="right">
            <template #default="{ row }">
              <span v-if="row.empty" class="muted">未建 BOM</span>
              <span v-else>{{ formatBomQty(row.required) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <p v-else class="so-detail-hint so-bom-create-hint">
        保存并添加明细后，可在此查看各款产品 BOM 用料估算。
      </p>

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

    <OwnProductDetailDialog v-model="productDetailVisible" :product-id="productDetailId" />

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
            <span class="intake-drawer-title">生产分析</span>
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
            v-if="canConfirmFromAnalysis"
            type="primary"
            :loading="confirmingFromAnalysis"
            @click="confirmFromAnalysis"
          >
            确认生产{{ mrpRefs.length > 1 ? ` (${mrpRefs.length})` : '' }}
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
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
    pending_production: 0,
    in_progress: 0,
    completed: 0,
    cancelled: 0,
  },
})
const statusStatItems = [
  { value: 'pending_confirm', label: '待确认', tone: 'tone-pending-confirm' },
  { value: 'pending_production', label: '待生产', tone: 'tone-pending-production' },
  { value: 'in_progress', label: '生产中', tone: 'tone-in-progress' },
  { value: 'completed', label: '已完成', tone: 'tone-completed' },
  { value: 'cancelled', label: '已取消', tone: 'tone-cancelled' },
] as const

function filterByStatus(status: string) {
  statusFilter.value = status
  page.value = 1
  void load()
}
const viewMode = ref<'split' | 'product'>('split')
const selectedProductLines = ref<any[]>([])
const saving = ref(false)
const headerSaving = ref(false)
const customers = ref<any[]>([])
const products = ref<any[]>([])
const colors = ref<any[]>([])
const sizes = ref<any[]>([])

const headerDialogVisible = ref(false)
const headerDraft = reactive({
  id: null as number | null,
  order_no: '',
  customer_id: null as number | null,
  customer_name: '',
  ordered_at: new Date().toISOString().slice(0, 10),
  notes: '',
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

type HeaderBomRow = {
  key: string
  product_code: string
  color_name: string
  material_code: string
  material_name: string
  unit: string
  qty_per_pair: number
  pairs: number
  required: number
  empty?: boolean
}

const headerBomRows = computed((): HeaderBomRow[] => {
  if (!headerDraft.id) return []
  const so = rows.value.find((r) => r.id === headerDraft.id)
  const lines = so?.lines || []
  if (!lines.length) return []
  const out: HeaderBomRow[] = []
  for (const line of lines) {
    const product = products.value.find((p) => p.id === line.own_product_id)
    const productCode = String(line.product_code || product?.product_code || '—')
    const colorName = String(line.color_name || '—')
    const pairs = Number(line.total_qty || 0)
    const mats = listOf(product?.materials)
    if (!mats.length) {
      out.push({
        key: `empty-${line.id}`,
        product_code: productCode,
        color_name: colorName,
        material_code: '',
        material_name: '',
        unit: '',
        qty_per_pair: 0,
        pairs,
        required: 0,
        empty: true,
      })
      continue
    }
    for (const m of mats) {
      const qty = Number(m.qty || 0)
      out.push({
        key: `${line.id}-${m.supplier_product_id || m.id}`,
        product_code: productCode,
        color_name: colorName,
        material_code: String(m.supplier_product_code || ''),
        material_name: String(m.supplier_product_name || m.supplier_product_code || '—'),
        unit: String(m.pricing_unit_name || ''),
        qty_per_pair: qty,
        pairs,
        required: qty * pairs,
      })
    }
  }
  return out
})

function formatBomQty(v: number) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (Number.isInteger(n)) return String(n)
  return n.toFixed(4).replace(/\.?0+$/, '')
}

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
const mrpLoading = ref(false)
const mrpIncludeShared = ref(true)
const mrpShortagesOnly = ref(false)
const mrpResult = ref<any>(null)
const mrpRefs = ref<{ sales_order_id: number; line_id: number }[]>([])
const mrpAnalysisRows = ref<any[]>([])
const confirmingFromAnalysis = ref(false)
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
    push('缺料料号存在争料，确认生产前先定保谁、催谁。', 'high')
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
    push('bom', '没有 BOM 还能怎么推进？', '左侧显示无 BOM。请说明确认生产前必须补什么，以及临时怎么控风险。')
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

const sortedSizes = computed(() =>
  [...sizes.value].sort((a, b) => {
    const ao = Number(a.sort_order) || 0
    const bo = Number(b.sort_order) || 0
    if (ao !== bo) return ao - bo
    return String(a.size_value).localeCompare(String(b.size_value), undefined, { numeric: true })
  }),
)

watch(
  () => [sortedSizes.value.length, viewMode.value, inlineLine.value?.key] as const,
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
          customer_id: so.customer_id,
          customer_name: so.customer_name,
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
        customerName: so.customer_name,
        orderedAt: so.ordered_at,
        orderStatus: so.status,
        salesOrderId: so.id,
        orderTotalQty: totals.qty,
        orderTotalAmount: totals.amount,
        canEditHeader,
        canAddLine,
        customerId: so.customer_id,
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
      customer_id: so.customer_id,
      customer_name: so.customer_name,
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
        customer_id: so.customer_id,
        customer_name: so.customer_name,
        ordered_at: so.ordered_at,
        order_status: so.status,
        order_total_qty: totals.qty,
        order_total_amount: totals.amount,
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
  customerName: string
  orderedAt: string
  orderStatus: string
  salesOrderId: number
  orderTotalQty?: number
  orderTotalAmount?: number | null
  canEditHeader?: boolean
  canAddLine?: boolean
  customerId?: number | null
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
    customer_id: opts.customerId,
    customer_name: opts.customerName,
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
    fabric: line?.fabric || '',
    lining: line?.lining || '',
    customer_sku: line?.customer_sku,
    brand_name: line?.brand_name || '',
    items: lineItems,
    delivery_date: line?.delivery_date,
    total_qty,
    unit_price,
    line_total,
    line_status: line?.status,
    production_order_id: line?.production_order_id,
    production_order_no: line?.production_order_no,
    production_order_status: line?.production_order_status,
  }
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
  if (row.order_status === 'cancelled' || row.line_status === 'cancelled') return '已取消'
  if (row.order_status === 'completed' || row.line_status === 'completed') return '已完成'
  const prodStatus = row.production_order_status
  if (prodStatus === 'completed') return '已完成'
  if (prodStatus === 'cancelled') return '已取消'
  if (prodStatus === 'in_progress') return '生产中'
  // 已确认下生产：有生产单但尚未开工 → 待生产
  if (row.production_order_id || row.line_status === 'in_production') return '待生产'
  return '待确认'
}

function lineStatusTagType(row: any): 'success' | 'warning' | 'info' | 'danger' | 'primary' {
  const label = lineStatusLabel(row)
  if (label === '生产中') return 'success'
  if (label === '待生产') return 'warning'
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
  for (const ln of lines || []) {
    if (!ln) continue
    const q = ln.total_qty != null ? Number(ln.total_qty) : lineQtyTotal(ln)
    qty += q || 0
    const a = lineTotalAmount(ln)
    if (a != null) {
      amount += a
      hasAmount = true
    }
  }
  return { qty, amount: hasAmount ? amount : null }
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

function sizeQty(row: any, sizeId: number) {
  const it = row.items?.find((x: any) => x.size_id === sizeId)
  const q = Number(it?.qty)
  if (!q) return ''
  return q
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
  headerDraft.status = 'draft'
  headerDraft.summaryText = ''
  onHeaderCustomerChange(headerDraft.customer_id)
  headerDialogVisible.value = true
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
  headerDraft.status = so.status || ''
  headerDraft.summaryText =
    lineN > 0 ? `共 ${lineN} 行明细 · ${totals.qty} 双` : '暂无明细'
  headerDialogVisible.value = true
  void ensureBomProductsForOrder(so)
}

/** 列表缓存若缺 materials，按需拉产品详情补齐 BOM 预览 */
async function ensureBomProductsForOrder(so: any) {
  const ids = [
    ...new Set(
      (so.lines || [])
        .map((l: any) => Number(l.own_product_id))
        .filter((id: number) => Number.isFinite(id) && id > 0),
    ),
  ]
  for (const id of ids) {
    const idx = products.value.findIndex((p) => p.id === id)
    const cached = idx >= 0 ? products.value[idx] : null
    if (cached && Array.isArray(cached.materials)) continue
    try {
      const res: any = await http.get(`/own-products/${id}`)
      const detail = res.data
      if (!detail) continue
      if (idx >= 0) products.value[idx] = { ...cached, ...detail }
      else products.value.push(detail)
    } catch {
      /* 预览失败不阻断详情 */
    }
  }
}

function onHeaderCustomerChange(id: number | null) {
  const c = customers.value.find((x) => x.id === id)
  if (c) headerDraft.customer_name = c.short_name || c.name
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
    view: viewMode.value === 'product' ? 'product' : 'split',
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
    productRows.value = (res.data?.items || []).map((row: any, idx: number) => ({
      ...row,
      _key: row.sales_order_line_id
        ? `${row.sales_order_id}-${row.sales_order_line_id}`
        : `p-${idx}`,
      line_status: row.line_status ?? row.status,
    }))
    rows.value = []
  } else {
    rows.value = res.data?.items || []
    productRows.value = []
  }
  total.value = res.data?.total || 0
  selectedProductLines.value = []
  productTableRef.value?.clearSelection()
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
      row.order_status === 'draft',
  )
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
      row.line_status !== 'in_production' &&
      row.order_status !== 'completed' &&
      row.order_status !== 'cancelled',
  )
}

function canEditLine(row: any) {
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
      !row.production_order_id,
  )
}

function hasLineMoreActions(row: any) {
  return Boolean(canSimulateMrp(row) || row.production_order_id || canDeleteLine(row))
}

function onLineMore(row: any, cmd: string) {
  if (cmd === 'mrp') {
    void openProductionAnalysis([row])
    return
  }
  if (cmd === 'production' && row.production_order_id) {
    goProductionOrder(row.production_order_id)
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

async function sendIntakeFollowUp() {
  const text = agentInput.value.trim()
  if (!text || agentStreaming.value || !agentEnabled.value) return
  agentInput.value = ''
  await streamAgentMessage(buildIntakeFollowUpMessage(text), { userVisible: text })
  agentStale.value = false
}

async function openProductionAnalysis(rows: any[]) {
  const usable = rows.filter((row) => canSimulateMrp(row))
  if (!usable.length) {
    ElMessage.warning('请选择未下生产且有数量的产品行')
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
          } else if (ev.type === 'token' && ev.text) {
            row.content += String(ev.text)
            await scrollIntakeChat()
          } else if (ev.type === 'chart' && ev.chart) {
            pendingCharts.push(ev.chart as ChartSpec)
          } else if (ev.type === 'done') {
            if (ev.reply && !row.content.trim()) row.content = String(ev.reply)
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

async function confirmFromAnalysis() {
  const rows = mrpAnalysisRows.value.filter((row) => canConfirmLine(row))
  if (!rows.length) {
    ElMessage.warning('没有可确认生产的行')
    return
  }
  const n = rows.length
  const profit = analysisProfit.value
  const kit = intakeKit.value
  const kitBad = kit && !kit.kit_ok && !kit.empty_bom
  const loss = profit != null && Number(profit.profit) < 0
  let tip =
    n === 1
      ? `按订单原数量为「${rows[0].order_no}」生成生产单？`
      : `按订单原数量确认为选中的 ${n} 个产品行生成生产单？`
  if (loss || kitBad || intakeVerdict.value === 'reject') {
    const warns: string[] = []
    if (loss) warns.push('预估利润为负')
    if (kitBad) warns.push(`仍有缺料 ${kit.shortage_lines || ''} 项`)
    if (intakeVerdict.value === 'reject') warns.push('诊断为不建议接产')
    tip = `${warns.join('，')}。${tip}\n（军师仅建议；确认按库内原数量下生产）`
  }
  await ElMessageBox.confirm(tip, '确认生产（人工确认）', {
    type: loss || kitBad || intakeVerdict.value === 'reject' ? 'warning' : 'info',
    confirmButtonText: '确认生产',
    cancelButtonText: '再想想',
  })
  confirmingFromAnalysis.value = true
  try {
    if (n === 1) {
      await http.post(
        `/sales-orders/${rows[0].sales_order_id}/lines/${rows[0].sales_order_line_id}/confirm`,
      )
      ElMessage.success('已下生产')
    } else {
      const res: any = await http.post('/sales-orders/lines/confirm-batch', {
        lines: rows.map((row) => ({
          sales_order_id: row.sales_order_id,
          line_id: row.sales_order_line_id,
        })),
      })
      const count = res.data?.confirmed_count ?? n
      ElMessage.success(`已下生产 ${count} 行`)
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

function goProductionOrder(productionOrderId?: number) {
  if (!productionOrderId) return
  void router.push({ path: '/admin/orders', query: { id: String(productionOrderId) } })
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
  color: #15803d;
}
.so-stat-chip.tone-completed .so-stat-num {
  color: #0369a1;
}
.so-stat-chip.tone-cancelled .so-stat-num {
  color: #94a3b8;
}
.so-table-host {
  min-width: 0;
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
.so-bom-block {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.so-bom-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 12px;
  margin-bottom: 8px;
}
.so-bom-title {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
}
.so-bom-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.35;
}
.so-bom-table {
  width: 100%;
}
.so-bom-create-hint {
  margin-top: 4px;
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
.so-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: nowrap;
  line-height: 1;
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
