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
            :width="colWidth('order_no', 130)"
            resizable
          >
            <template #default="{ row }">
              <div class="so-order-cell">
                <span class="so-order-no">{{ row.order_no || '' }}</span>
                <span class="so-order-banner-actions">
                  <el-tooltip
                    v-if="row._canEditHeader"
                    content="编辑头条"
                    placement="top"
                    :show-after="200"
                  >
                    <el-button
                      link
                      type="primary"
                      :icon="EditPen"
                      @click.stop="startEditHeader(row.sales_order_id)"
                    />
                  </el-tooltip>
                  <el-tooltip
                    v-if="row._canAddLine"
                    content="增加明细"
                    placement="top"
                    :show-after="200"
                  >
                    <el-button
                      link
                      type="primary"
                      :icon="Plus"
                      @click.stop="startAddLine(row.sales_order_id)"
                    />
                  </el-tooltip>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column
            prop="customer_name"
            label="客户"
            :width="colWidth('customer_name', 100)"
            show-overflow-tooltip
            resizable
          >
            <template #default="{ row }">{{ row.customer_name || '' }}</template>
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
                clearable
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
              <el-button
                v-else-if="row.own_product_id && row.product_code"
                link
                type="primary"
                @click="openProductDetail(row.own_product_id)"
              >
                {{ row.product_code }}
              </el-button>
              <span v-else>{{ row.product_code || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="product_image_url"
            label="产品图片"
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
            label="客户品牌"
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
            label="客户货号"
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
              <template v-else>
                <span v-if="row.notes" class="notes-cell">{{ row.notes }}</span>
              </template>
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
            width="72"
            align="center"
            :resizable="false"
          >
            <template #default="{ row }">
              <template v-if="isSummaryRow(row)" />
              <div v-else-if="isRowEditing(row)" class="so-actions">
                <el-tooltip content="保存" placement="top" :show-after="200">
                  <el-button
                    link
                    type="primary"
                    :icon="Check"
                    :loading="saving"
                    @click="saveInlineLine"
                  />
                </el-tooltip>
                <el-tooltip content="取消" placement="top" :show-after="200">
                  <el-button link :icon="Close" @click="cancelInlineLine" />
                </el-tooltip>
              </div>
              <div v-else class="so-actions">
                <el-tooltip
                  v-if="canEditLine(row)"
                  content="编辑"
                  placement="top"
                  :show-after="200"
                >
                  <el-button
                    link
                    type="primary"
                    :icon="EditPen"
                    @click="startEditLine(row)"
                  />
                </el-tooltip>
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
            <el-button
              v-if="row.own_product_id && row.product_code"
              link
              type="primary"
              @click="openProductDetail(row.own_product_id)"
            >
              {{ row.product_code }}
            </el-button>
            <span v-else>{{ row.product_code || '' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          prop="product_image_url"
          label="产品图片"
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
          label="客户品牌"
          :width="colWidth1('brand_name', 88)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.brand_name || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="customer_sku"
          label="客户货号"
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
          resizable
        />
        <el-table-column
          prop="customer_name"
          label="客户"
          :width="colWidth1('customer_name', 90)"
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
            <span v-if="row.notes" class="notes-cell">{{ row.notes }}</span>
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

    <!-- 订单头条弹窗 -->
    <el-dialog
      v-model="headerDialogVisible"
      :title="headerDraft.id ? '编辑订单头条' : '新建订单'"
      width="480px"
      destroy-on-close
    >
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="订单号">
          <el-input v-model="headerDraft.order_no" placeholder="可空自动生成" clearable />
        </el-form-item>
        <el-form-item label="客户" required>
          <el-select
            v-model="headerDraft.customer_id"
            filterable
            clearable
            placeholder="选择客户"
            style="width: 100%"
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
            v-if="!headerDraft.customer_id"
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
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="headerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="headerSaving" @click="saveHeader">保存</el-button>
      </template>
    </el-dialog>

    <OwnProductDetailDialog v-model="productDetailVisible" :product-id="productDetailId" />

    <el-dialog
      v-model="mrpVisible"
      title="生产分析"
      width="980px"
      destroy-on-close
      class="mrp-dialog"
    >
      <div v-if="analysisProfit" class="analysis-profit">
        <div class="analysis-profit-card">
          <span class="analysis-profit-label">数量</span>
          <strong>{{ analysisProfit.qty }}</strong>
        </div>
        <div class="analysis-profit-card">
          <span class="analysis-profit-label">销售额</span>
          <strong>¥{{ formatMoney(analysisProfit.revenue) }}</strong>
        </div>
        <div class="analysis-profit-card">
          <span class="analysis-profit-label">成本</span>
          <strong>¥{{ formatMoney(analysisProfit.cost) }}</strong>
        </div>
        <div class="analysis-profit-card">
          <span class="analysis-profit-label">利润</span>
          <strong :class="analysisProfit.profit >= 0 ? 'profit-pos' : 'profit-neg'">
            ¥{{ formatMoney(analysisProfit.profit) }}
          </strong>
        </div>
        <div class="analysis-profit-card">
          <span class="analysis-profit-label">毛利率</span>
          <strong :class="(analysisProfit.margin ?? 0) >= 0 ? 'profit-pos' : 'profit-neg'">
            {{
              analysisProfit.margin == null
                ? '—'
                : `${(analysisProfit.margin * 100).toFixed(1)}%`
            }}
          </strong>
        </div>
      </div>

      <div class="mrp-toolbar">
        <span class="mrp-section-title">物料情况</span>
        <el-tag v-if="mrpResult?.kit_ok" type="success" size="small">齐套</el-tag>
        <el-tag v-else-if="mrpResult && !mrpResult.empty_bom" type="danger" size="small">
          缺料 {{ mrpResult.shortage_lines }} 项
        </el-tag>
        <el-tag v-else-if="mrpResult?.empty_bom" type="info" size="small">无 BOM</el-tag>
        <span class="muted mrp-hint">实时计算 · 不锁库</span>
        <el-checkbox v-model="mrpShortagesOnly" @change="reloadMrp">仅缺料</el-checkbox>
      </div>
      <el-table
        ref="mrpTableRef"
        v-loading="mrpLoading"
        :data="mrpDisplayLines"
        border
        max-height="360"
        class="so-admin-compact-table mrp-material-table"
        :row-class-name="mrpRowClassName"
        @header-dragend="onMrpHeaderDragend"
      >
        <el-table-column
          column-key="image"
          label="图片"
          :width="mrpColWidth('image', 72)"
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
              fit="contain"
              class="product-thumb"
              preview-teleported
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="partner_name"
          label="供应商"
          :width="mrpColWidth('partner_name', 110)"
          resizable
        >
          <template #default="{ row }">{{ row.partner_name || '' }}</template>
        </el-table-column>
        <el-table-column
          prop="supplier_product_code"
          label="物料编码"
          :width="mrpColWidth('supplier_product_code', 120)"
          resizable
        />
        <el-table-column
          prop="supplier_product_name"
          label="物料"
          :min-width="mrpFlexColMinWidth('supplier_product_name', 140)"
          resizable
        />
        <el-table-column
          prop="required_qty"
          label="需求"
          :width="mrpColWidth('required_qty', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMrpNum(row.required_qty) }}</template>
        </el-table-column>
        <el-table-column
          prop="free_pool_qty"
          label="可用池"
          :width="mrpColWidth('free_pool_qty', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMrpNum(row.free_pool_qty) }}</template>
        </el-table-column>
        <el-table-column
          prop="in_transit_qty"
          label="在途"
          :width="mrpColWidth('in_transit_qty', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMrpNum(row.in_transit_qty) }}</template>
        </el-table-column>
        <el-table-column
          prop="shortage_qty"
          label="缺口"
          :width="mrpColWidth('shortage_qty', 80)"
          align="right"
          resizable
        >
          <template #default="{ row }">
            <strong :class="Number(row.shortage_qty) > 0 ? 'mrp-shortage-num' : 'muted'">
              {{ formatMrpNum(row.shortage_qty) }}
            </strong>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="(mrpResult?.skipped || []).length" class="muted mrp-skipped">
        已跳过 {{ mrpResult.skipped.length }} 行（已下生产或无数量）
      </p>
      <template #footer>
        <el-button
          v-if="canCancelFromAnalysis"
          type="danger"
          plain
          :loading="cancellingFromAnalysis"
          @click="cancelFromAnalysis"
        >
          取消订单{{ analysisOrderIds.length > 1 ? ` (${analysisOrderIds.length})` : '' }}
        </el-button>
        <el-button @click="mrpVisible = false">关闭</el-button>
        <el-button
          v-if="canConfirmFromAnalysis"
          type="primary"
          :loading="confirmingFromAnalysis"
          @click="confirmFromAnalysis"
        >
          确认生产{{ mrpRefs.length > 1 ? ` (${mrpRefs.length})` : '' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import type { TableInstance } from 'element-plus'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close, EditPen, MoreFilled, Plus } from '@element-plus/icons-vue'
import http from '@/api/http'
import OwnProductDetailDialog from '@/components/OwnProductDetailDialog.vue'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

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
})

const inlineLine = ref<InlineLineState | null>(null)
let inlineLineSeq = 0

const mrpVisible = ref(false)
const mrpLoading = ref(false)
const mrpIncludeShared = ref(true)
const mrpShortagesOnly = ref(false)
const mrpResult = ref<any>(null)
const mrpRefs = ref<{ sales_order_id: number; line_id: number }[]>([])
const mrpAnalysisRows = ref<any[]>([])
const confirmingFromAnalysis = ref(false)
const cancellingFromAnalysis = ref(false)

const analysisProfit = computed(() => buildAnalysisProfit(mrpAnalysisRows.value))
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

/** 缺料行排前，齐套行在后 */
const mrpDisplayLines = computed(() => {
  const lines = [...(mrpResult.value?.lines || [])]
  return lines.sort((a, b) => {
    const sa = Number(a.shortage_qty) > 0 ? 0 : 1
    const sb = Number(b.shortage_qty) > 0 ? 0 : 1
    if (sa !== sb) return sa - sb
    return Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
  })
})

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
  if (insertingNew) {
    displayLines.push({
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
      _canAddLine: canAddLine,
    })
  }
  for (let idx = 0; idx < lines.length; idx++) {
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
  } else if (displayLines.length > 1) {
    // 仅多明细时加合计行；单行订单数量/总价即本行，无需汇总
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
  onHeaderCustomerChange(headerDraft.customer_id)
  headerDialogVisible.value = true
}

function startEditHeader(salesOrderId: number) {
  if (warnIfInlineBusy()) return
  const row = rows.value.find((r) => r.id === salesOrderId)
  if (!row) return
  if (row.status === 'completed' || row.status === 'cancelled') {
    ElMessage.warning('已完成或已取消的订单不可编辑头条')
    return
  }
  headerDraft.id = row.id
  headerDraft.order_no = row.order_no || ''
  headerDraft.customer_id = row.customer_id ?? null
  headerDraft.customer_name = row.customer_name || ''
  headerDraft.ordered_at = row.ordered_at || new Date().toISOString().slice(0, 10)
  headerDialogVisible.value = true
}

function onHeaderCustomerChange(id: number | null) {
  const c = customers.value.find((x) => x.id === id)
  if (c) headerDraft.customer_name = c.short_name || c.name
}

async function saveHeader() {
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

function startAddLine(salesOrderId: number) {
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
      await http.post(`/sales-orders/${il.salesOrderId}/lines`, payload)
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

async function reloadMrp() {
  if (!mrpRefs.value.length) return
  await runSimulateMrp(mrpRefs.value, { quiet: true })
}

async function openProductionAnalysis(rows: any[]) {
  const usable = rows.filter((row) => canSimulateMrp(row))
  if (!usable.length) {
    ElMessage.warning('请选择未下生产且有数量的产品行')
    return
  }
  mrpAnalysisRows.value = usable
  await runSimulateMrp(
    usable.map((row) => ({
      sales_order_id: row.sales_order_id,
      line_id: row.sales_order_line_id,
    })),
  )
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
  await ElMessageBox.confirm(
    n === 1
      ? `为「${rows[0].order_no}」生成生产订单？`
      : `确认为选中的 ${n} 个产品行生成生产订单？`,
    '确认生产',
  )
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
  await loadMasters()
  await load()
  await nextTick()
  measureTableHeight()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onEditHotkey)
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
.so-order-banner-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  flex-shrink: 0;
}
.so-order-banner-actions :deep(.el-button) {
  padding: 0 4px;
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
  gap: 0;
  flex-wrap: nowrap;
}
.so-actions :deep(.el-button) {
  padding: 0 4px;
}
.so-actions :deep(.el-dropdown) {
  display: inline-flex;
  vertical-align: middle;
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
}
</style>
