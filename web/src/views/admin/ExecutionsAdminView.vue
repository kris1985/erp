<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">生产进度</h1>
      </div>
      <div class="page-hero-stats so-status-stats">
        <button
          type="button"
          class="so-stat-chip"
          :class="{ active: filters.status === 'active' }"
          :title="statusCountTitle('未完成', statusStatsActiveTotal)"
          @click="filterByStatus('active')"
        >
          <span class="so-stat-label">未完成</span>
          <strong class="so-stat-num">{{ formatStatusCount(statusStatsActiveTotal) }}</strong>
        </button>
        <button
          v-for="item in statusStatItems"
          :key="item.value"
          type="button"
          class="so-stat-chip"
          :class="[item.tone, { active: filters.status === item.value }]"
          :title="statusCountTitle(item.label, statusStatCount(item.value))"
          @click="filterByStatus(item.value)"
        >
          <span class="so-stat-label">{{ item.label }}</span>
          <strong class="so-stat-num">{{ formatStatusCount(statusStatCount(item.value)) }}</strong>
        </button>
        <button
          type="button"
          class="so-stat-chip"
          :class="{ active: !filters.status }"
          :title="statusCountTitle('全部', statusStats.total)"
          @click="filterByStatus('')"
        >
          <span class="so-stat-label">全部</span>
          <strong class="so-stat-num">{{ formatStatusCount(statusStats.total) }}</strong>
        </button>
      </div>
    </header>

    <div class="admin-card">
    <div class="admin-toolbar">
      <el-select
        v-model="filters.header_no"
        clearable
        filterable
        placeholder="生产单号"
        style="width: 160px"
        @change="searchExecutions"
      >
        <el-option v-for="item in filterOptions.header_nos" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select
        v-model="filters.order_no"
        clearable
        filterable
        placeholder="订单号"
        style="width: 150px"
        @change="searchExecutions"
      >
        <el-option v-for="item in filterOptions.order_nos" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select
        v-model="filters.customer"
        clearable
        filterable
        placeholder="客户"
        style="width: 140px"
        @change="searchExecutions"
      >
        <el-option v-for="item in filterOptions.customers" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select
        v-model="filters.brand"
        clearable
        filterable
        placeholder="品牌"
        style="width: 130px"
        @change="searchExecutions"
      >
        <el-option v-for="item in filterOptions.brands" :key="item" :label="item" :value="item" />
      </el-select>
      <div class="exe-product-select" :class="{ 'has-thumb': selectedProductOption?.image_url }">
        <img
          v-if="selectedProductOption?.image_url"
          :src="selectedProductOption.image_url"
          alt=""
          class="exe-product-selected-thumb"
        />
        <el-select
          v-model="filters.product_code"
          clearable
          filterable
          placeholder="工厂型号"
          popper-class="exe-product-popper"
          @change="searchExecutions"
        >
          <el-option
            v-for="item in filterOptions.product_codes"
            :key="item.product_code"
            :label="item.product_code"
            :value="item.product_code"
          >
            <span class="exe-product-option">
              <img v-if="item.image_url" :src="item.image_url" alt="" />
              <span v-else class="exe-product-option-ph" />
              <span class="exe-product-option-name">{{ item.product_code }}</span>
            </span>
          </el-option>
        </el-select>
      </div>
      <div class="execution-delivery-range">
        <el-date-picker
          v-model="filters.deliveryRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="-"
          start-placeholder="交货起"
          end-placeholder="交货止"
          @change="searchExecutions"
        />
      </div>
    </div>
    <div
      ref="tableHostRef"
      class="execution-table-host"
      :class="{ 'is-row-dragging': draggedHeaderId != null }"
      @dragover="onTableDragOver"
      @drop="onTableDrop"
      @dragleave="onTableDragLeave"
    >
    <el-table
      ref="listTableRef"
      class="execution-list-table"
      v-loading="listLoading || reorderLoading"
      :data="displayExecutions"
      border
      row-key="_displayKey"
      :span-method="executionSpanMethod"
      :row-class-name="reorderRowClassName"
      :max-height="tableMaxHeight"
      empty-text="暂无生产单。请先在订单中确认接单，系统会自动创建生产单。"
      @header-dragend="onListHeaderDragend"
    >
      <el-table-column column-key="sequence" label="顺序" width="72" align="center" fixed="left">
        <template #default="{ row }">
          <span
            class="row-drag-handle"
            :class="{ disabled: !canReorder(row), 'is-dragging': draggedHeaderId === Number(row.id) }"
            :draggable="canReorder(row)"
            :title="canReorder(row) ? '按住拖拽调整生产顺序' : reorderDisabledReason()"
            @dragstart="onRowDragStart($event, row)"
            @dragend="onRowDragEnd"
          >
            <span class="drag-grip" aria-hidden="true">⋮⋮</span>
            <span class="drag-index">{{ executionSequence(row) }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column
        prop="execution_no"
        label="生产单号"
        :width="listColWidth('execution_no', 150)"
        show-overflow-tooltip
        resizable
      >
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">
            {{ row.header_no || row.execution_no }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column
        column-key="order_nos"
        label="订单号"
        :width="listColWidth('order_nos', 150)"
        show-overflow-tooltip
        resizable
      >
        <template #default="{ row }">{{ sourceOrderNo(row) }}</template>
      </el-table-column>
      <el-table-column
        column-key="customers"
        label="客户/品牌"
        class-name="exe-brand-col"
        :width="listColWidth('customers', 120)"
        resizable
      >
        <template #default="{ row }">
          <div class="exe-brand-stack" :title="sourceBrandTitle(row)">
            <div class="exe-brand-stack-line">{{ sourceCustomer(row) }}</div>
            <div class="exe-brand-stack-line exe-brand-stack-brand">{{ sourceBrand(row) }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="product_code"
        label="工厂型号"
        :width="listColWidth('product_code', 110)"
        show-overflow-tooltip
        resizable
      />
      <el-table-column
        prop="product_image_url"
        label="图片"
        :width="listColWidth('product_image_url', 72)"
        align="center"
        class-name="mat-image-col"
        header-class-name="mat-image-col"
        resizable
      >
        <template #default="{ row }">
          <el-image
            v-if="row.product_image_url"
            :src="row.product_image_url"
            :preview-src-list="[row.product_image_url]"
            fit="contain"
            class="product-thumb"
            preview-teleported
          />
          <span v-else class="muted mat-image-empty"></span>
        </template>
      </el-table-column>
      <el-table-column
        prop="color_name"
        label="颜色"
        :width="listColWidth('color_name', 90)"
        resizable
      >
        <template #default="{ row }">{{ row.color_name || '—' }}</template>
      </el-table-column>
      <el-table-column
        prop="total_qty"
        column-key="total_qty"
        label="数量"
        :width="listColWidth('total_qty', 80)"
        align="right"
        resizable
      >
        <template #default="{ row }">{{ sourceQty(row) }}</template>
      </el-table-column>
      <el-table-column
        prop="delivery_date"
        label="交货日期"
        :width="listColWidth('delivery_date', 110)"
        resizable
      >
        <template #default="{ row }">{{ sourceDeliveryDate(row) }}</template>
      </el-table-column>
      <el-table-column
        column-key="projected_finish"
        label="预计交货日期"
        :width="listColWidth('projected_finish', 110)"
        resizable
      >
        <template #default="{ row }">
          <el-popover
            v-if="hasRisk(row)"
            placement="bottom"
            :width="360"
            trigger="hover"
            :show-after="180"
            :hide-after="120"
            popper-class="exe-risk-popper"
          >
            <template #reference>
              <span :class="projectedFinish(row) === '-' ? 'muted' : 'exe-risk-date'">{{ projectedFinish(row) }}</span>
            </template>
            <div class="exe-risk-detail">
              <div class="exe-risk-head">
                <strong>{{ row.header_no || row.execution_no }}</strong>
                <el-tag size="small" :type="riskTagType(row)" effect="light">
                  {{ riskOf(row).label }}
                </el-tag>
              </div>
              <div v-if="riskOf(row).projected_finish" class="exe-risk-meta">
                预计完成 {{ riskOf(row).projected_finish }}
                <template v-if="Number(riskOf(row).delivery_delta_days) > 0">
                  · 晚 {{ riskOf(row).delivery_delta_days }} 天
                </template>
                <template v-else-if="Number(riskOf(row).delivery_delta_days) < 0">
                  · 提前 {{ Math.abs(Number(riskOf(row).delivery_delta_days)) }} 天
                </template>
              </div>
              <div v-if="!row.kit?.kit_ok && row.kit?.kit_ready_date" class="exe-risk-meta">
                预计齐套 {{ row.kit.kit_ready_date }}
              </div>
              <div v-if="riskOf(row).current_process" class="exe-risk-meta">
                当前工序 {{ riskOf(row).current_process }} · 剩余 {{ riskOf(row).remaining_qty || 0 }} 双
              </div>
              <div class="exe-risk-reasons">
                <div v-for="reason in riskOf(row).reasons || []" :key="reason.code" class="exe-risk-reason">
                  <strong>{{ reason.label }}</strong>
                  <span>{{ reason.detail }}</span>
                </div>
              </div>
              <div class="exe-risk-advice">
                <span>建议</span>
                <strong>{{ riskOf(row).recommendation || '继续关注' }}</strong>
              </div>
            </div>
          </el-popover>
          <span v-else :class="{ muted: projectedFinish(row) === '-' }">{{ projectedFinish(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column
        column-key="material_status"
        label="仓库"
        :width="listColWidth('material_status', 100)"
        align="center"
        resizable
      >
        <template #default="{ row }">
          <template v-if="row.status !== 'completed'">
          <el-popover
            v-if="showWarehouseKit(row)"
            placement="bottom"
            :width="warehouseKitWidth(row)"
            trigger="hover"
            :show-after="200"
            :hide-after="200"
            popper-class="exe-warehouse-kit-popper"
            :popper-options="warehouseKitPopperOptions"
            @show="onWarehouseKitShow(row)"
          >
            <template #reference>
              <el-tag
                size="small"
                :type="materialStatusTag(row)"
                effect="plain"
                class="exe-warehouse-tag"
              >
                {{ materialStatus(row) }}
              </el-tag>
            </template>
            <div v-loading="warehouseKitLoadingId === Number(row.id)" class="exe-wh-kit">
              <div class="exe-wh-kit-head">
                <strong>用料 · {{ row.header_no || row.execution_no }}</strong>
              </div>
              <div class="exe-wh-kit-body">
                <div v-if="!warehousePlainLines(row).length && !warehouseSizedLines(row).length" class="muted exe-wh-kit-empty">
                  {{ warehouseKitLoadingId === Number(row.id) ? '加载中…' : '暂无用料' }}
                </div>
                <template v-else>
                  <div v-if="warehousePlainLines(row).length" class="exe-wh-kit-seg">
                    <div class="exe-wh-kit-seg-head"><span class="exe-wh-kit-seg-title">不分码</span></div>
                    <el-table
                      class="exe-wh-kit-table"
                      :data="warehousePlainLines(row)"
                      size="small"
                      border
                      style="width: 100%"
                      :row-class-name="warehouseKitRowClass"
                      :span-method="warehouseKitSpan"
                    >
                      <el-table-column prop="consume_segment_name" label="消耗部门" width="88" show-overflow-tooltip />
                      <el-table-column prop="supplier_product_code" label="物料编号" min-width="96" show-overflow-tooltip />
                      <el-table-column prop="supplier_product_name" label="名称" min-width="88" show-overflow-tooltip />
                      <el-table-column label="颜色" width="72" show-overflow-tooltip>
                        <template #default="{ row: ln }">{{ ln.color_name || '—' }}</template>
                      </el-table-column>
                      <el-table-column label="数量" width="64" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.plan_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="报废数量" width="80" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.scrap_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="报工" width="64" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.reported_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="每双用量" width="80" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.qty_per_pair) }}</template>
                      </el-table-column>
                      <el-table-column label="总用量" width="80" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.total_usage_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="车间剩余" width="80" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.own_workshop_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="仓库现存" width="80" align="right">
                        <template #default="{ row: ln }">{{ formatMatQty(ln.on_hand_qty) }}</template>
                      </el-table-column>
                      <el-table-column label="缺口" width="72" align="right">
                        <template #default="{ row: ln }">
                          <strong :class="Number(ln.shortage_qty) > 0 ? 'risk-text' : ''">{{ formatMatQty(ln.shortage_qty) }}</strong>
                        </template>
                      </el-table-column>
                    </el-table>
                    <p class="exe-wh-kit-note">总用量 = (数量 + 报废数量 − 报工) × 每双用量</p>
                    <p class="exe-wh-kit-note">缺口 = 总用量 − 车间剩余 − 仓库现存，小于 0 记 0。只扣当时的仓库现存，不算在途。还在待买的不扣仓库现存。</p>
                  </div>
                  <div v-if="warehouseSizedLines(row).length" class="exe-wh-kit-seg">
                    <div class="exe-wh-kit-seg-head"><span class="exe-wh-kit-seg-title">按码</span></div>
                    <el-table
                      class="exe-wh-kit-table"
                      :data="warehouseSizedLines(row)"
                      size="small"
                      border
                      style="width: 100%"
                      :row-class-name="warehouseKitRowClass"
                      :span-method="warehouseKitSpan"
                    >
                      <el-table-column prop="consume_segment_name" label="消耗部门" width="88" show-overflow-tooltip />
                      <el-table-column prop="supplier_product_code" label="物料编号" min-width="96" show-overflow-tooltip />
                      <el-table-column prop="supplier_product_name" label="名称" min-width="88" show-overflow-tooltip />
                      <el-table-column label="颜色" width="72" show-overflow-tooltip>
                        <template #default="{ row: ln }">{{ ln.color_name || '—' }}</template>
                      </el-table-column>
                      <el-table-column
                        v-for="metric in warehouseSizedMetrics"
                        :key="metric.field"
                        :label="metric.label"
                        align="center"
                      >
                        <el-table-column
                          v-for="size in warehouseSizeColumns(row)"
                          :key="`${metric.field}_${size}`"
                          :label="size"
                          width="64"
                          align="right"
                        >
                          <template #default="{ row: ln }">
                            <strong
                              v-if="metric.field === 'shortage_qty'"
                              :class="warehouseSizeShort(ln, size) ? 'risk-text' : ''"
                            >{{ warehouseSizeMetric(ln, size, metric.field) }}</strong>
                            <span v-else>{{ warehouseSizeMetric(ln, size, metric.field) }}</span>
                          </template>
                        </el-table-column>
                      </el-table-column>
                    </el-table>
                    <p class="exe-wh-kit-note">缺口 =（生产单数量 + 报废）−（领料 − 退料）− 仓库现存，小于 0 记 0。不减车间剩余，不算在途。还在待买的不扣仓库现存。</p>
                  </div>
                </template>
              </div>
            </div>
          </el-popover>
          <el-tag
            v-else-if="materialStatus(row)"
            size="small"
            :type="materialStatusTag(row)"
            effect="plain"
            class="exe-warehouse-tag"
          >
            {{ materialStatus(row) }}
          </el-tag>
          <span v-else class="muted">—</span>
          </template>
        </template>
      </el-table-column>
      <el-table-column
        v-for="process in listProcessColumns"
        :key="`proc-${process.key}`"
        :column-key="`proc-${process.key}`"
        :label="process.label"
        align="center"
      >
        <el-table-column
          :column-key="`proc-${process.key}-plan`"
          label="任务"
          :width="listColWidth(`proc-${process.key}-plan`, 64)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <span>{{ listProcessQty(row, process.key, 'plan') }}</span>
          </template>
        </el-table-column>
        <el-table-column
          :column-key="`proc-${process.key}-completed-base`"
          label="完工"
          :width="listColWidth(`proc-${process.key}-completed-base`, 52)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <span>{{ segmentCompletedQty(row, process.key) }}</span>
          </template>
        </el-table-column>
      </el-table-column>
      <el-table-column column-key="finished_goods" label="成品仓" align="center">
        <el-table-column
          column-key="base_shipped_qty"
          label="已出货"
          :width="listColWidth('base_shipped_qty', 76)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <span>{{ row.shipped_qty ?? 0 }}</span>
          </template>
        </el-table-column>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" width="72" fixed="right" :resizable="false">
        <template #default="{ row }">
          <div class="exe-row-actions">
            <el-dropdown
              v-if="availableRowActions(row).length"
              trigger="click"
              @command="(cmd: string) => runRowAction(row, cmd)"
            >
              <el-button link type="primary" :icon="MoreFilled" aria-label="更多操作" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="a in availableRowActions(row)"
                    :key="a.cmd"
                    :command="a.cmd"
                    :divided="a.divided"
                    :disabled="a.disabled"
                  >
                    {{ a.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <span v-else class="muted">—</span>
          </div>
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
        @current-change="loadExecutions"
        @size-change="onPageSizeChange"
      />
    </div>
    </div>

    <el-dialog v-model="intakeVisible" title="入成品仓" width="1080px" :close-on-click-modal="false">
      <p v-if="intakeFinished" class="muted">已自动入成品仓，不用再入仓。</p>
      <template v-else>
        <p class="muted" style="margin: 0 0 12px">最后工序段已完工 {{ intakeDoneText }} 双。按订单行填箱数，换算后的双数不能超过已完工数量。</p>
        <el-table
          ref="intakeTableRef"
          :data="intakeOrders"
          border
          size="small"
          style="width: 100%"
          empty-text="这张生产单没有关联订单"
          @header-dragend="onIntakeHeaderDragend"
        >
          <el-table-column prop="order_no" label="订单号" :width="intakeColWidth('order_no', 140)" show-overflow-tooltip resizable />
          <el-table-column prop="customer_name" label="客户" :width="intakeColWidth('customer_name', 100)" show-overflow-tooltip resizable />
          <el-table-column prop="brand_name" label="品牌" :width="intakeColWidth('brand_name', 80)" show-overflow-tooltip resizable />
          <el-table-column prop="customer_sku" label="客户型号" :width="intakeColWidth('customer_sku', 100)" show-overflow-tooltip resizable />
          <el-table-column prop="notes" label="备注" :width="intakeColWidth('notes', 140)" show-overflow-tooltip resizable>
            <template #default="{ row }">{{ row.notes || '—' }}</template>
          </el-table-column>
          <el-table-column prop="carton_qty" label="订单箱数" :width="intakeColWidth('carton_qty', 90)" align="center" resizable />
          <el-table-column prop="intake_carton_qty" label="已入仓" :width="intakeColWidth('intake_carton_qty', 80)" align="center" resizable />
          <el-table-column prop="remain_carton_qty" label="还可入" :width="intakeColWidth('remain_carton_qty', 80)" align="center" resizable />
          <el-table-column column-key="carton_input" label="本次箱数" :width="intakeColWidth('carton_input', 150)" align="center" resizable>
            <template #default="{ row }">
              <el-input-number
                v-model="row.carton_input"
                :min="0"
                :max="row.remain_carton_qty"
                :step="1"
                :precision="0"
                :disabled="!row.remain_carton_qty"
                controls-position="right"
              />
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="intakeVisible = false">取消</el-button>
        <el-button v-if="!intakeFinished" type="primary" :loading="intakeSaving" @click="submitIntake">放入待出货</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dispatchVisible"
      width="min(1080px, 96vw)"
      class="dispatch-dialog"
      append-to-body
    >
      <template #header>
        <div class="dispatch-dialog-header">
          <span class="dispatch-eyebrow">生产派工</span>
          <div class="dispatch-header-title-row">
            <h2>{{ detail?.header_no || detail?.execution_no || '生产单' }}</h2>
            <el-button link class="dispatch-copy-button" aria-label="复制生产单号" @click="copyDispatchNo">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
          </div>
          <p>每个工序段选择一个部门。只有一个部门时默认选中。</p>
        </div>
      </template>

      <div class="dispatch-flow-scroll">
        <div
          v-if="dispatchSegmentCards.length"
          class="dispatch-flow-track"
          :style="{
            width: `max(100%, ${dispatchSegmentCards.length * 190}px)`,
            gridTemplateColumns: `repeat(${dispatchSegmentCards.length}, minmax(0, 1fr))`,
          }"
        >
          <section
            v-for="segment in dispatchSegmentCards"
            :key="segment.key"
            class="dispatch-flow-stage"
            :class="{ 'is-assigned': dispatchDeptId(segment.segmentId) != null }"
          >
            <div class="dispatch-flow-title">
              <strong>{{ segment.name }}</strong>
              <span v-if="dispatchDeptId(segment.segmentId) != null" class="dispatch-flow-status assigned">已派</span>
            </div>
            <div class="dispatch-flow-marker">
              <span :class="{ assigned: dispatchDeptId(segment.segmentId) != null }">
                {{ String(segment.order).padStart(2, '0') }}
              </span>
            </div>
            <div class="dispatch-flow-note">
              <span
                v-if="segment.inconsistent"
                class="dispatch-flow-warning"
                title="该工序段现有工序的部门不一致，保存后将统一为本次选择"
              >
                派工待统一
              </span>
            </div>
            <el-radio-group
              :model-value="dispatchDeptId(segment.segmentId)"
              class="dispatch-team-stack"
              @change="(value: number) => setDispatchDept(segment.segmentId, value)"
            >
              <el-radio
                v-for="dept in segment.departments"
                :key="dept.id"
                :value="dept.id"
              >
                <span class="dispatch-team-name">{{ dept.name }}</span>
              </el-radio>
            </el-radio-group>
          </section>
        </div>
        <div v-else class="muted" style="padding: 24px 8px">没有挂了工序段的叶子部门，请先在员工与部门中维护。</div>
      </div>
      <template #footer>
        <div class="dispatch-dialog-footer">
          <div class="dispatch-footer-left">
            <el-button text class="dispatch-clear-button" @click="clearDispatchSelection">清空选择</el-button>
            <span class="dispatch-footer-summary" :class="{ complete: !dispatchUnassignedSegmentCount }">
              <template v-if="!dispatchSegmentCards.length">请先维护叶子部门</template>
              <template v-else-if="dispatchUnassignedSegmentCount">
                还有 <strong>{{ dispatchUnassignedSegmentCount }}</strong> 个工序段未派工
              </template>
              <template v-else>相关工序段均已派到部门</template>
            </span>
          </div>
          <div class="dispatch-footer-actions">
            <el-button @click="dispatchVisible = false">取消</el-button>
            <el-button type="primary" :loading="dispatchSaving" :disabled="!dispatchSegmentCards.length" @click="saveDispatch">保存派工</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      width="min(1180px, 94vw)"
      class="execution-detail-dialog"
    >
      <template v-if="detail">
        <ProductionSheetPanel :sheet="flowCard" :loading="flowCardLoading" />
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="false && detail && canChangeQty(detail)"
          type="warning"
          plain
          @click="openChangeQty(detail)"
        >
          改量
        </el-button>
        <el-button
          v-if="detail && canCancelProduction(detail)"
          v-permission="'btn.orders.cancel'"
          type="danger"
          plain
          @click="cancelProduction(detail)"
        >
          取消生产
        </el-button>
        <el-button v-if="detail?.id || detail?.shop_order_id" plain @click="printFlowCardDoc(detail)">
          打印生产单
        </el-button>
        <el-button
          v-if="false && detail && canReschedule(detail)"
          plain
          @click="goReschedule(detail)"
        >
          改排
        </el-button>
        <el-button
          v-if="false && detail && canWithdraw(detail)"
          type="danger"
          plain
          @click="cancelExecution(detail)"
        >
          撤回待排
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="issueDialogVisible" :title="issueDialogTitle" width="920px" destroy-on-close>
      <p class="muted dlg-hint">
        <template v-if="issueDialogType === 'issue'">
          先填本次领料双数，按单耗自动算料；默认只看本工序段。提交后待仓管确认过账。
        </template>
        <template v-else>提交退料申请，仓管确认后把已发退回库存池。</template>
      </p>
      <div
        v-if="issueDialogType === 'issue'"
        style="margin-bottom: 10px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center"
      >
        <span class="issue-pairs-label">本次领料</span>
        <el-input-number
          v-model="issuePairs"
          :min="1"
          :max="Math.max(1, issueTotalQty || 99999)"
          size="small"
          controls-position="right"
          style="width: 120px"
          @change="onIssuePairsChange"
        />
        <span class="muted">双</span>
        <span class="muted issue-pairs-total">（整单共 {{ issueTotalQty || '—' }} 双）</span>
        <el-radio-group v-if="auth.processSegmentId" v-model="issueSegmentScope" size="small" @change="reloadIssueCandidates">
          <el-radio-button value="mine">本段{{ auth.processSegmentName ? `·${auth.processSegmentName}` : '' }}</el-radio-button>
          <el-radio-button value="all">全部段</el-radio-button>
        </el-radio-group>
      </div>
      <el-table
        v-loading="issueDialogLoading"
        :data="issueCandidates"
        border
        size="small"
        max-height="360"
        @header-dragend="onIssueHeaderDragend"
      >
        <el-table-column
          column-key="image"
          label="图片"
          :width="issueColWidth('image', 72)"
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
              preview-teleported
              fit="contain"
              class="product-thumb"
            />
            <span v-else class="muted mat-image-empty"></span>
          </template>
        </el-table-column>
        <el-table-column
          prop="supplier_product_code"
          label="物料"
          :width="issueColWidth('supplier_product_code', 100)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          prop="supplier_product_name"
          label="名称"
          :min-width="issueFlexColMinWidth('supplier_product_name', 120)"
          show-overflow-tooltip
          resizable
        />
        <el-table-column
          column-key="unit"
          label="单位"
          :width="issueColWidth('unit', 64)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template>
        </el-table-column>
        <el-table-column
          column-key="required"
          label="用量需求"
          :width="issueColWidth('required', 88)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMatQty(row.required_qty) }}</template>
        </el-table-column>
        <el-table-column
          column-key="issued"
          label="已领"
          :width="issueColWidth('issued', 72)"
          align="right"
          resizable
        >
          <template #default="{ row }">{{ formatMatQty(row.issued_qty) }}</template>
        </el-table-column>
        <el-table-column
          column-key="consume_segment"
          label="工序段"
          :width="issueColWidth('consume_segment', 88)"
          show-overflow-tooltip
          resizable
        >
          <template #default="{ row }">{{ row.consume_segment_name || '未分段' }}</template>
        </el-table-column>
        <el-table-column
          :label="issueDialogType === 'issue' ? '可领' : '可退'"
          :width="issueColWidth('max_qty', 96)"
          align="right"
          resizable
        >
          <template #default="{ row }">
            {{ formatMatQty(issueDialogType === 'issue' ? row.max_issue_qty : row.returnable_qty) }}
          </template>
        </el-table-column>
        <el-table-column label="本次" :width="issueColWidth('qty', 120)" resizable>
          <template #default="{ row }">
            <el-input v-model="issueQtyDraft[row.id]" size="small" placeholder="0" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="issueDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="issuePosting" @click="submitIssueDialog">
          提交{{ issueDialogType === 'issue' ? '领料' : '退料' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="changeQtyVisible"
      :title="`未开工改量 · ${changeQtyTarget?.execution_no || ''}`"
      width="640px"
      destroy-on-close
    >
      <p class="muted dlg-hint">仅未开工可改量。须提交全部现有分配行。</p>
      <el-table :data="changeQtyRows" size="small" border>
        <el-table-column prop="sales_order_no" label="销售单" min-width="120" />
        <el-table-column label="原量" width="80" align="right">
          <template #default="{ row }">{{ row.old_qty }}</template>
        </el-table-column>
        <el-table-column label="新量" width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.qty" :min="1" :max="999999" size="small" />
          </template>
        </el-table-column>
      </el-table>
      <el-form class="create-form" label-width="80px" style="margin-top: 12px">
        <el-form-item label="备注">
          <el-input v-model="changeQtyNotes" maxlength="120" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changeQtyVisible = false">取消</el-button>
        <el-button :loading="changeQtySaving" @click="submitChangeQty(true)">预览</el-button>
        <el-button type="primary" :loading="changeQtySaving" @click="submitChangeQty(false)">确认改量</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="cutVisible"
      :title="`开裁打框码 · ${cutTarget?.execution_no || ''}`"
      width="640px"
    >
      <p class="muted dlg-hint">
        开裁生成框码：一色码行按筐量拆成若干框，每框只属于一个品牌。框码用标签打印机打印；生产流转卡（A4）另打。
      </p>
      <el-form label-width="88px" size="small">
        <el-form-item label="拆筐量">
          <el-input-number v-model="cutBundleSize" :min="1" :step="10" controls-position="right" />
          <span class="muted" style="margin-left: 8px">
            每筐 {{ cutBundleSize || defaultCutBundleSize }} 双，超出自动另起一筐
          </span>
        </el-form-item>
        <el-form-item label="生产批次">
          <el-radio-group v-model="cutBatchMode" size="small" @change="onCutBatchModeChange">
            <el-radio-button value="single">不分批（默认一批）</el-radio-button>
            <el-radio-button value="split">分批</el-radio-button>
          </el-radio-group>
          <span class="muted" style="margin-left: 8px">
            批次号自动生成，如 {{ cutTarget?.execution_no }}-01
          </span>
        </el-form-item>
        <template v-if="cutBatchMode === 'split'">
          <el-form-item v-for="(b, i) in cutBatchQtys" :key="i" :label="`批 ${i + 1}（${b}双）`">
            <el-input-number v-model="cutBatchQtys[i]" :min="1" :step="10" controls-position="right" style="width: 160px" />
            <el-button
              v-if="cutBatchQtys.length > 1"
              link
              type="danger"
              style="margin-left: 8px"
              @click="removeCutBatch(i)"
            >
              删除
            </el-button>
          </el-form-item>
          <el-form-item label=" ">
            <el-button link type="primary" @click="addCutBatch">＋ 加一批</el-button>
            <span class="muted" style="margin-left: 8px">最后一批自动吃余数</span>
          </el-form-item>
        </template>
        <el-form-item v-if="cutNeedsKitReason" label="缺料原因" required>
          <el-input
            v-model="cutSkipKitReason"
            type="textarea"
            :rows="2"
            placeholder="首道不齐套。厂里偶尔会先裁已到的料，请写明原因。"
          />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="cutNeedsKitReason"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 10px"
        title="首道不齐套，不能开裁。要开必须填写原因。"
      />
      <el-table v-if="cutPreview?.lines?.length" :data="cutPreview.lines" size="small" max-height="280">
        <el-table-column label="颜色" prop="color_name" width="90" />
        <el-table-column label="尺码" prop="size_value" width="70" />
        <el-table-column label="行量" prop="item_qty" width="70" />
        <el-table-column label="拆筐">
          <template #default="{ row }">
            <BasketChips v-if="(row.planned_units || []).length" :units="row.planned_units" />
            <span v-else class="muted">{{ row.reason || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="cutPreview?.batches?.length" class="muted" style="margin: 8px 0 0">
        批次：{{ batchPreviewText }}
      </p>
      <template #footer>
        <el-button @click="cutVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="cutCreating || cutPreviewing"
          :disabled="!cutPreview || !(cutPreview.to_create > 0) || (cutNeedsKitReason && !cutSkipKitReason.trim())"
          @click="confirmCutCards"
        >
          确认生成并打印
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, MoreFilled } from '@element-plus/icons-vue'
import ProductionSheetPanel from '@/components/ProductionSheetPanel.vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useAuthStore } from '@/stores/auth'

type RowActionCmd = 'dispatch' | 'print-flow' | 'print-cartons' | 'cancel'
type RowAction = { cmd: RowActionCmd; label: string; divided?: boolean; disabled?: boolean }

type ExecutionRow = {
  id: number
  execution_no: string
  header_no?: string
  own_product_id?: number
  product_code?: string
  product_image_url?: string | null
  trace_enabled?: boolean
  color_id?: number | null
  color_name?: string | null
  size_value?: string | null
  size_summary?: string | null
  customers?: string[]
  brands?: string[]
  sales_order_nos?: string[]
  size_lines?: Array<{
    id: number
    execution_no: string
    size_id: number
    size_value?: string | null
    total_qty: number
    completed_qty?: number
    status: string
    is_rush?: boolean
  }>
  total_qty: number
  completed_qty?: number
  scheduled_qty?: number
  reported_qty?: number
  recut_task_qty?: number
  recut_reported_qty?: number
  recut_headers?: Array<{ id: number; header_no: string; total_qty: number; completed_qty: number }>
  wip_qty?: number
  produced_qty?: number
  shipped_qty?: number
  base_shipped_qty?: number
  recut_shipped_qty?: number
  progress_kind?: { wip?: string; produced?: string; shipped?: string }
  status: string
  started?: boolean
  shop_order_id?: number | null
  delivery_date?: string | null
  projected_finish?: string | null
  is_rush?: boolean
  notes?: string | null
  created_at?: string | null
  risk?: {
    level: 'normal' | 'attention' | 'high' | 'late'
    label: string
    projected_finish?: string | null
    delivery_delta_days?: number | null
    current_process?: string | null
    remaining_qty?: number
    reasons?: Array<{ code: string; label: string; detail: string }>
    recommendation?: string
    preview?: boolean
  } | null
  kit?: {
    kit_ok?: boolean
    first_kit_ok?: boolean
    empty_bom?: boolean
    shortage_lines?: number
    material_status?: 'kit_ok' | 'purchasing' | 'short' | 'to_buy' | null
    kit_ready_date?: string | null
    kit_ready_label?: string | null
  } | null
  allocations?: Array<{
    sales_order_line_item_id?: number
    sales_order_id?: number
    sales_order_no?: string
    customer_name?: string | null
    brand_name?: string | null
    sales_order_line_id?: number
    delivery_date?: string | null
    qty: number
    ratio: number
    produced_qty_est?: number
  }>
  process_progress?: Array<{
    process_id: number
    process_name: string
    label?: string
    segment_id?: number | null
    segment_name?: string | null
    plan_qty: number
    completed_qty: number
    base_plan_qty?: number
    base_completed_qty?: number
    recut_plan_qty?: number
    recut_completed_qty?: number
    status: string
    start_date?: string | null
    end_date?: string | null
    is_current?: boolean
    is_done?: boolean
    assigned_department_ids?: number[]
    route_department_ids?: number[]
    route_department_shared?: boolean
  }>
}

const router = useRouter()
const route = useRoute()
const listLoading = ref(false)
const executions = ref<ExecutionRow[]>([])
const listSegments = ref<Array<{
  id: number
  name: string
  code: string
  sort_order?: number
  is_active?: boolean
  is_optional?: boolean
}>>([])
const listSkivingEnabled = ref(false)
type ExecutionDisplayRow = ExecutionRow & {
  _displayKey: string
  _sourceIndex: number
  _sourceCount: number
  _sourceOrderNo: string
  _sourceCustomer: string
  _sourceBrand: string
  _sourceQty: number
  _sourceDeliveryDate: string | null
}

function pushUnique(values: string[], value: string | null | undefined) {
  const text = String(value || '').trim()
  if (text && !values.includes(text)) values.push(text)
}

function expandExecutionSources(row: ExecutionRow): ExecutionDisplayRow[] {
  const headerBrands = uniqueNonEmpty(row.brands || [])
  const grouped = new Map<
    string,
    { orderNo: string; customer: string; brands: string[]; qty: number; deliveryDates: string[] }
  >()
  for (const allocation of row.allocations || []) {
    const orderNo = String(allocation.sales_order_no || '').trim()
    const key = orderNo || `order-${allocation.sales_order_id || 'unknown'}`
    const source = grouped.get(key) || {
      orderNo: orderNo || '—',
      customer: String(allocation.customer_name || '').trim(),
      brands: [],
      qty: 0,
      deliveryDates: [],
    }
    source.qty += Number(allocation.qty || 0)
    if (!source.customer && allocation.customer_name) {
      source.customer = String(allocation.customer_name).trim()
    }
    pushUnique(source.brands, allocation.brand_name)
    if (allocation.delivery_date) source.deliveryDates.push(String(allocation.delivery_date))
    grouped.set(key, source)
  }

  if (!grouped.size) {
    const orderNos = row.sales_order_nos?.length
      ? row.sales_order_nos
      : [String((row as any).sales_order_no || '').trim()].filter(Boolean)
    const customers = row.customers || []
    for (const [index, orderNo] of orderNos.entries()) {
      const brand = headerBrands[index] || (headerBrands.length === 1 ? headerBrands[0] : '')
      grouped.set(orderNo, {
        orderNo,
        customer: customers[index] || customers[0] || '',
        brands: brand ? [brand] : [],
        qty: orderNos.length === 1 ? Number(row.total_qty || 0) : 0,
        deliveryDates: row.delivery_date ? [row.delivery_date] : [],
      })
    }
  }

  const sources = grouped.size
    ? [...grouped.values()]
    : [{ orderNo: '—', customer: '', brands: [...headerBrands], qty: Number(row.total_qty || 0), deliveryDates: [] }]
  return sources.map((source, index) => {
    if (!source.brands.length && headerBrands.length === 1) source.brands = [headerBrands[0]]
    return {
      ...row,
      _displayKey: `${row.id}-${index}-${source.orderNo}`,
      _sourceIndex: index,
      _sourceCount: sources.length,
      _sourceOrderNo: source.orderNo || '—',
      _sourceCustomer: source.customer || '—',
      _sourceBrand: source.brands.join('、') || '—',
      _sourceQty: source.qty,
      _sourceDeliveryDate: source.deliveryDates.length
        ? [...source.deliveryDates].sort()[0] || null
        : row.delivery_date || null,
    }
  })
}

const displayExecutions = computed<ExecutionDisplayRow[]>(() =>
  executions.value.flatMap(expandExecutionSources),
)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const savedExecutionIds = ref<number[]>([])
const draggedHeaderId = ref<number | null>(null)
const dropIndicator = ref<{ id: number; position: 'before' | 'after' } | null>(null)
const reorderLoading = ref(false)

const PROCESS_SEGMENT_CODE_ORDER = ['cut', 'skiving', 'stitch', 'forming', 'packing']
const PROCESS_SEGMENT_NAME_CODE: Record<string, string> = {
  截断: 'cut',
  裁断: 'cut',
  冲裁: 'cut',
  铲皮: 'skiving',
  针车: 'stitch',
  成型: 'forming',
  包装: 'packing',
}

function processSegmentRank(name: string, segmentId?: number | null) {
  const configured = segmentId == null
    ? null
    : listSegments.value.find((segment) => Number(segment.id) === Number(segmentId))
  const code = configured?.code || PROCESS_SEGMENT_NAME_CODE[name]
  const canonicalIndex = PROCESS_SEGMENT_CODE_ORDER.indexOf(code)
  if (canonicalIndex >= 0) return canonicalIndex
  if (name === '未分段') return 10000
  return 100 + Number(configured?.sort_order || 0)
}

const listProcessColumns = computed(() => {
  // 已启用的工序段固定出列，没有工序的段也要能看到。可选段仍只在开关打开时显示。
  const columns = new Map<string, { key: string; label: string; segmentId: number | null }>()
  for (const segment of listSegments.value) {
    if (segment.is_active === false) continue
    if (segment.is_optional && !(segment.code === 'skiving' && listSkivingEnabled.value)) continue
    const key = `seg:${segment.id}`
    columns.set(key, { key, label: segment.name || '工序段', segmentId: segment.id })
  }
  for (const row of executions.value) {
    for (const p of row.process_progress || []) {
      const segId = p.segment_id ?? 'unlabeled'
      const label = p.segment_name || (segId === 'unlabeled' ? '未分段' : '工序')
      const key = `seg:${segId}`
      if (!columns.has(key)) {
        columns.set(key, {
          key,
          label,
          segmentId: p.segment_id == null ? null : Number(p.segment_id),
        })
      }
    }
  }
  return [...columns.values()].sort((a, b) => {
    return processSegmentRank(a.label, a.segmentId) - processSegmentRank(b.label, b.segmentId)
  })
})

/** 段完工只算派工部门在工艺路线里的工序。别的部门路线上的工序不参与瓶颈。 */
function countsOnDispatchedRoute(proc: any) {
  const routeIds = new Set(
    (proc?.route_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean),
  )
  if (proc?.route_department_shared || !routeIds.size) return true
  const assigned = (proc?.assigned_department_ids || [])
    .map((id: unknown) => Number(id))
    .filter(Boolean)
  if (!assigned.length) return true
  return assigned.some((id: number) => routeIds.has(id))
}

function trimPairQty(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

function segmentProgressQty(
  row: ExecutionRow,
  processKey: string,
  kind: 'combined' | 'base' | 'recut',
) {
  // 工序段按生产「双数」展示，不能把段内多道工艺的工作量直接相加。
  // 同一段取任务量最大的工艺作为段任务，以最低完成率作为段完工（瓶颈口径）。
  const segKey = processKey.replace(/^seg:/, '')
  const matched = (row.process_progress || []).filter(
    (p: any) => String(p.segment_id ?? 'unlabeled') === segKey && countsOnDispatchedRoute(p),
  )
  if (!matched.length) return '—'

  const planField = kind === 'base' ? 'base_plan_qty' : kind === 'recut' ? 'recut_plan_qty' : 'plan_qty'
  const doneField = kind === 'base' ? 'base_completed_qty' : kind === 'recut' ? 'recut_completed_qty' : 'completed_qty'
  const effective = matched.filter((p: any) => Number(p[planField] || 0) > 0)
  if (!effective.length) return kind === 'recut' ? 0 : '—'

  const taskQty = Math.max(...effective.map((p: any) => Math.max(0, Number(p[planField] || 0))))
  if (!taskQty) return kind === 'recut' ? 0 : '—'

  const bottleneckRate = Math.min(
    ...effective.map((p: any) => {
      const plan = Number(p[planField] || 0)
      const completed = Math.max(0, Number(p[doneField] || 0))
      return Math.min(1, completed / plan)
    }),
  )
  return trimPairQty(Math.min(taskQty, taskQty * bottleneckRate))
}

function segmentCompletedQty(row: ExecutionRow, processKey: string) {
  return segmentProgressQty(row, processKey, 'combined')
}

function segmentBottleneckQty(procs: any[], planField: string, doneField: string) {
  const effective = procs.filter((p) => Number(p?.[planField] || 0) > 0)
  if (!effective.length) return null
  const plan = Math.max(...effective.map((p) => Math.max(0, Number(p[planField] || 0))))
  if (!plan) return null
  const rate = Math.min(
    ...effective.map((p) => {
      const itemPlan = Number(p[planField] || 0)
      const completed = Math.max(0, Number(p[doneField] || 0))
      return Math.min(1, completed / itemPlan)
    }),
  )
  return {
    plan,
    done: trimPairQty(Math.min(plan, plan * rate)),
  }
}

/** 任务沿工艺路线往后传。后段只承接本段计划里有的数量，发现在本段的报废不再往本段传。 */
function segmentFlowTasks(row: ExecutionRow) {
  const groups = new Map<string, any[]>()
  for (const proc of row.process_progress || []) {
    const key = `seg:${proc.segment_id ?? 'unlabeled'}`
    if (!countsOnDispatchedRoute(proc)) continue
    const list = groups.get(key)
    if (list) list.push(proc)
    else groups.set(key, [proc])
  }
  const keys = [...groups.keys()].sort((a, b) => {
    const left = groups.get(a)?.[0]
    const right = groups.get(b)?.[0]
    return (
      processSegmentRank(left?.segment_name || '', left?.segment_id) -
      processSegmentRank(right?.segment_name || '', right?.segment_id)
    )
  })
  // 主单超报的双数就是补做进度，任务按合计计划与合计完工计算。
  const streams = [['plan_qty', 'completed_qty']]
  const prevDone = streams.map(() => 0)
  const prevPlan = streams.map(() => 0)
  const started = streams.map(() => false)
  const tasks = new Map<string, number>()
  for (const key of keys) {
    const procs = groups.get(key) || []
    let task = 0
    streams.forEach(([planField, doneField], index) => {
      const stage = segmentBottleneckQty(procs, planField, doneField)
      if (!stage) return
      const inflow = started[index] ? prevDone[index] : stage.plan
      const stoppedBefore = started[index] ? Math.max(0, prevPlan[index] - stage.plan) : 0
      const relevant = Math.max(0, inflow - stoppedBefore)
      task += Math.max(0, trimPairQty(Math.min(relevant, stage.plan) - stage.done))
      prevDone[index] = stage.done
      prevPlan[index] = stage.plan
      started[index] = true
    })
    tasks.set(key, trimPairQty(task))
  }
  return tasks
}

function listProcessQty(row: ExecutionRow, processKey: string, field: 'completed' | 'plan') {
  if (field === 'completed') return String(segmentProgressQty(row, processKey, 'combined'))
  const tasks = segmentFlowTasks(row)
  if (!tasks.has(processKey)) return '—'
  return String(tasks.get(processKey) ?? 0)
}
const filters = reactive({
  header_no: '' as string | null,
  customer: '' as string | null,
  product_code: '' as string | null,
  order_no: '' as string | null,
  brand: '' as string | null,
  status: 'active' as string | undefined,
  deliveryRange: null as [string, string] | null,
})
type ProductCodeOption = { product_code: string; image_url: string | null }
const filterOptions = ref({
  header_nos: [] as string[],
  customers: [] as string[],
  product_codes: [] as ProductCodeOption[],
  order_nos: [] as string[],
  brands: [] as string[],
})
const selectedProductOption = computed(
  () => filterOptions.value.product_codes.find((item) => item.product_code === filters.product_code) || null,
)
const statusStats = ref<{ total: number; by_status: Record<string, number> }>({
  total: 0,
  by_status: {
    confirmed: 0,
    cut: 0,
    in_progress: 0,
    completed: 0,
    cancelled: 0,
  },
})
const statusStatItems = [
  { value: 'confirmed', label: '待生产', tone: 'tone-confirmed' },
  { value: 'production', label: '生产中', tone: 'tone-in-progress' },
  { value: 'completed', label: '已完成', tone: 'tone-completed' },
  { value: 'cancelled', label: '已取消', tone: 'tone-cancelled' },
] as const
const statusStatsActiveTotal = computed(() => {
  return ['confirmed', 'cut', 'in_progress'].reduce(
    (total, status) => total + Number(statusStats.value.by_status[status] || 0),
    0,
  )
})

function statusStatCount(status: string) {
  if (status === 'production') {
    return Number(statusStats.value.by_status.cut || 0) + Number(statusStats.value.by_status.in_progress || 0)
  }
  return Number(statusStats.value.by_status[status] || 0)
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

function filterByStatus(status: string) {
  filters.status = status || undefined
  searchExecutions()
}
const detailVisible = ref(false)
const detail = ref<ExecutionRow | null>(null)
const flowCard = ref<any>(null)
const flowCardLoading = ref(false)
let flowCardSeq = 0
const listTableRef = ref()
const {
  colWidth: listColWidth,
  onHeaderDragend: onListHeaderDragend,
  relayoutTable: relayoutListTable,
} = useTableColWidths(
  'executions-list',
  listTableRef,
  { flexKey: 'order_nos', flexDefaultMin: 150, fitToContainer: true },
)
const kitTableRef = ref<any>(null)
const kitTableEls = new Map<string, any>()
const kitTableRefSetters = new Map<string, (el: any) => void>()

function kitTableRefSetter(key: string) {
  let setter = kitTableRefSetters.get(key)
  if (!setter) {
    setter = (el: any) => setKitTableRef(key, el)
    kitTableRefSetters.set(key, setter)
  }
  return setter
}
const {
  colWidth: kitColWidth,
  onHeaderDragend: onKitHeaderDragend,
  relayoutTable: relayoutKitTable,
} = useTableColWidths('executions-warehouse-kit', kitTableRef, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 96,
  fitToContainer: true,
  groupEdgeResize: true,
})

function setKitTableRef(key: string, el: any) {
  if (el) kitTableEls.set(key, el)
  else kitTableEls.delete(key)
  if (el && !kitTableRef.value) kitTableRef.value = el
  if (!el && kitTableRef.value && ![...kitTableEls.values()].includes(kitTableRef.value)) {
    kitTableRef.value = kitTableEls.values().next().value ?? null
  }
}

function focusKitTable(key: string) {
  const el = kitTableEls.get(key)
  if (el && kitTableRef.value !== el) kitTableRef.value = el
}

function onKitTableDrag(key: string, newWidth: number, oldWidth: number, column: any) {
  focusKitTable(key)
  onKitHeaderDragend(newWidth, oldWidth, column)
}

const { tableHostRef, tableMaxHeight } = useTableMaxHeight()
const { colWidth: basketWidth, flexColMinWidth: flexBasket, onHeaderDragend: onBasketDragend } =
  useTableColWidths('executions-detail-baskets')
const { colWidth: procColWidth, flexColMinWidth: flexProc, onHeaderDragend: onProcDragend } =
  useTableColWidths('executions-detail-processes')
const {
  colWidth: issueColWidth,
  flexColMinWidth: issueFlexColMinWidth,
  onHeaderDragend: onIssueHeaderDragend,
} = useTableColWidths('executions-issue-dialog', undefined, {
  flexKey: 'supplier_product_name',
  flexDefaultMin: 120,
})
const intakeTableRef = ref()
const { colWidth: intakeColWidth, onHeaderDragend: onIntakeHeaderDragend } = useTableColWidths(
  'executions-fg-intake',
  intakeTableRef,
  { flexKey: 'notes', flexDefaultMin: 120, fitToContainer: true },
)
const auth = useAuthStore()
const canStockIssue = computed(() => auth.hasCapability('stock_docs'))
type HeaderProcessRow = {
  id: number
  process_name: string
  label?: string
  part_name?: string | null
  plan_qty: number
  completed_qty: number
  rework_qty?: number
  start_date?: string | null
  end_date?: string | null
  is_current?: boolean
  is_done?: boolean
}
const headerProcesses = ref<HeaderProcessRow[]>([])
const processProgress = ref<{ all_done: boolean; current_process_name: string | null }>({
  all_done: false,
  current_process_name: null,
})
const detailBaskets = ref<any[]>([])
const basketsLoading = ref(false)
const headerMaterials = ref<any[]>([])
const materialsLoading = ref(false)
const cutBatches = ref<any[]>([])
const cutBatchesLoading = ref(false)
const packingPlans = ref<any[]>([])
const packingShipments = ref<any[]>([])
const packingShippingLoading = ref(false)
const packingCartons = computed(() => packingPlans.value.flatMap((plan: any) => plan.cartons || []))
const packingShippingSizeCols = computed(() => collectCartonSizes(packingCartons.value))
const packingCartonSizeColWidth = computed(() => {
  const count = Math.max(1, packingShippingSizeCols.value.length)
  return Math.max(26, Math.min(42, Math.floor(450 / count)))
})
const stockDocs = ref<any[]>([])
const stockDocsLoading = ref(false)
const materialRows = computed(() => headerMaterials.value.map((row: any) => {
  const requirementId = Number(row.id)
  let issued = 0
  let returned = 0
  let hasPostedIssueLine = false
  for (const doc of stockDocs.value) {
    if (doc.status !== 'posted') continue
    const qty = (doc.lines || [])
      .filter((line: any) => Number(line.order_material_requirement_id) === requirementId)
      .reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0)
    if (doc.doc_type === 'issue' && qty > 0) {
      issued += qty
      hasPostedIssueLine = true
    }
    if (doc.doc_type === 'return_mat') returned += qty
  }
  if (!hasPostedIssueLine) issued = Number(row.issued_qty || 0) + returned
  const theoretical = cutBatches.value.reduce(
    (sum: number, batch: any) => sum + (batch.materials || [])
      .filter((item: any) => Number(item.requirement_id) === requirementId)
      .reduce((sub: number, item: any) => sub + Number(item.theoretical_qty || 0), 0),
    0,
  )
  const required = Number(row.required_qty || 0)
  const arrived = Number(row.arrived_qty || 0)
  const toBuy = Math.max(0, Number(row.to_buy_qty ?? row.shortage_qty ?? 0))
  const materialStatus = toBuy > 0
    ? { label: '有缺口', type: 'danger' as const }
    : arrived >= required
      ? { label: '已覆盖', type: 'success' as const }
      : { label: '采购中', type: 'warning' as const }
  return {
    ...row,
    gross_issued_qty: issued,
    returned_qty: returned,
    net_issued_qty: issued - returned,
    theoretical_qty: theoretical,
    to_buy_display_qty: toBuy,
    material_status: materialStatus,
  }
}))
const consumptionRows = computed(() => {
  const grouped = new Map<number, any>()
  for (const batch of cutBatches.value) {
    for (const row of batch.materials || []) {
      const key = Number(row.supplier_product_id)
      const item = grouped.get(key) || {
        supplier_product_id: key,
        material_code: row.material_code,
        material_name: row.material_name,
        theoretical_qty: 0,
        batchIds: new Set<number>(),
        issuedByRequirement: new Map<number, number>(),
      }
      item.theoretical_qty += Number(row.theoretical_qty || 0)
      item.batchIds.add(Number(batch.id))
      item.issuedByRequirement.set(
        Number(row.requirement_id),
        Math.max(
          Number(item.issuedByRequirement.get(Number(row.requirement_id)) || 0),
          Number(row.issued_qty_order_total || 0),
        ),
      )
      grouped.set(key, item)
    }
  }
  return [...grouped.values()].map((item: any) => {
    const issued = [...item.issuedByRequirement.values()].reduce((sum: number, qty: unknown) => sum + Number(qty || 0), 0)
    return {
      ...item,
      issued_qty: issued,
      variance: issued - item.theoretical_qty,
      batch_count: item.batchIds.size,
    }
  })
})
const warehouseKitCache = ref<Record<number, any>>({})
const warehouseKitLoadingId = ref<number | null>(null)
const warehouseKitPopperOptions = {
  strategy: 'fixed' as const,
  modifiers: [
    {
      name: 'preventOverflow',
      options: { boundary: 'viewport', padding: 8, altAxis: true },
    },
    {
      name: 'flip',
      options: {
        boundary: 'viewport',
        padding: 8,
        fallbackPlacements: ['top', 'bottom'],
      },
    },
  ],
}
const buyingGapId = ref<number | null>(null)
const issueDialogVisible = ref(false)
const issueDialogType = ref<'issue' | 'return_mat'>('issue')
const issueDialogLoading = ref(false)
const issuePosting = ref(false)
const issueCandidates = ref<any[]>([])
const issueMeta = ref<any>(null)
const issueQtyDraft = ref<Record<number, string>>({})
const issueTarget = ref<{ id: number; header_no?: string; execution_no?: string; total_qty?: number } | null>(
  null,
)
const issuePairs = ref(1)
const issueSegmentScope = ref<'mine' | 'all'>('mine')
const issueTotalQty = computed(
  () => Number(issueMeta.value?.total_qty) || Number(issueTarget.value?.total_qty) || 0,
)
const packingLoading = ref(false)
const packingSaving = ref(false)
const packingSavingLineId = ref<number | null>(null)
const packingWarehousing = ref(false)
const packingWarehousingId = ref<number | null>(null)
const packingSources = ref<any[]>([])
const packingSourceSizeCols = computed(() => {
  const values = new Set<string>()
  for (const source of packingSources.value) {
    for (const line of source.assortment_lines || []) {
      if (line.size_value) values.add(String(line.size_value))
    }
  }
  return [...values].sort((a, b) => {
    const na = Number(a)
    const nb = Number(b)
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
    return a.localeCompare(b, 'zh')
  })
})
const packingSourceSizeColWidth = computed(() => {
  const count = Math.max(1, packingSourceSizeCols.value.length)
  return Math.max(28, Math.min(44, Math.floor(420 / count)))
})
const cutVisible = ref(false)
const changeQtyVisible = ref(false)
const changeQtyTarget = ref<ExecutionRow | null>(null)
const changeQtyRows = ref<Array<{ sales_order_line_item_id: number; sales_order_no: string; old_qty: number; qty: number }>>([])
const changeQtyNotes = ref('')
const changeQtySaving = ref(false)
const cutTarget = ref<ExecutionRow | null>(null)
const defaultCutBundleSize = ref(40)
const cutBundleSize = ref(40)
const cutPreview = ref<any>(null)
const cutPreviewing = ref(false)
const cutCreating = ref(false)
const cutSkipKitReason = ref('')
const cutNeedsKitReason = computed(
  () =>
    Boolean(cutPreview.value) &&
    cutPreview.value.first_kit_ok === false &&
    cutPreview.value.empty_bom !== true,
)

function printPrimary(row: ExecutionRow) {
  return (row.status === 'cut' || row.status === 'in_progress') && Boolean(row.id || row.shop_order_id)
}

function printSecondary(row: ExecutionRow) {
  if (!(row.id || row.shop_order_id)) return false
  return row.status === 'confirmed' || row.status === 'completed'
}

/** 生产单列表操作统一收进三点菜单，避免操作列随状态抖动。 */
function availableRowActions(row: ExecutionRow): RowAction[] {
  const actions: RowAction[] = []
  if (row.status !== 'cancelled') {
    actions.push({ cmd: 'dispatch', label: '派工' })
  }
  if (printPrimary(row) || printSecondary(row)) {
    actions.push({ cmd: 'print-flow', label: '打印生产单' })
  }
  if (row.status !== 'cancelled') {
    actions.push({ cmd: 'print-cartons', label: '打印箱唛' })
    if (auth.hasPermission('btn.orders.fg_intake')) {
      actions.push({ cmd: 'fg-intake', label: '入成品仓' })
    }
  }
  if (canCancelProduction(row) && auth.hasPermission('btn.orders.cancel')) {
    actions.push({ cmd: 'cancel', label: '取消', divided: true })
  }
  return actions
}

const intakeVisible = ref(false)
const intakeSaving = ref(false)
const intakeFinished = ref(false)
const intakeDonePairs = ref(0)
const intakeHeaderId = ref(0)
const intakeDoneText = computed(() => {
  const text = intakeDonePairs.value.toFixed(2).replace(/\.?0+$/, '')
  return text || '0'
})
const intakeOrders = ref<Array<{
  sales_order_id: number
  sales_order_line_id: number
  order_no: string
  customer_name: string
  brand_name: string
  customer_sku: string
  notes: string
  carton_qty: number
  intake_carton_qty: number
  remain_carton_qty: number
  carton_input: number
}>>([])

async function openFgIntake(row: ExecutionRow) {
  intakeHeaderId.value = Number(row.id)
  intakeFinished.value = false
  intakeDonePairs.value = 0
  intakeOrders.value = []
  intakeVisible.value = true
  try {
    const res: any = await http.get(`/fg-stocks/orders/${row.id}/intake`)
    const data = res.data || {}
    intakeFinished.value = Boolean(data.finished)
    intakeDonePairs.value = Number(data.done_pairs || 0)
    intakeOrders.value = (data.orders || []).map((order: any) => ({
      sales_order_id: Number(order.sales_order_id),
      sales_order_line_id: Number(order.sales_order_line_id),
      order_no: String(order.order_no || ''),
      customer_name: String(order.customer_name || ''),
      brand_name: String(order.brand_name || ''),
      customer_sku: String(order.customer_sku || ''),
      notes: String(order.notes || ''),
      carton_qty: Number(order.carton_qty || 0),
      intake_carton_qty: Number(order.intake_carton_qty || 0),
      remain_carton_qty: Number(order.remain_carton_qty || 0),
      carton_input: 0,
    }))
  } catch (e: any) {
    intakeVisible.value = false
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载订单失败')
  }
}

async function submitIntake() {
  const orders = intakeOrders.value
    .filter((row) => Number(row.carton_input) > 0)
    .map((row) => ({
      sales_order_id: row.sales_order_id,
      sales_order_line_id: row.sales_order_line_id,
      carton_qty: Number(row.carton_input),
    }))
  if (!orders.length) {
    ElMessage.warning('请填写箱数')
    return
  }
  intakeSaving.value = true
  try {
    await http.post(`/fg-stocks/orders/${intakeHeaderId.value}/intake`, { orders })
    ElMessage.success('已放入成品仓待出货')
    intakeVisible.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '入仓失败')
  } finally {
    intakeSaving.value = false
  }
}

function runRowAction(row: ExecutionRow, cmd: string) {
  if (cmd === 'dispatch') openRowDispatch(row)
  else if (cmd === 'print-flow') printFlowCardDoc(row)
  else if (cmd === 'print-cartons') openRowCartonMarks(row)
  else if (cmd === 'fg-intake') void openFgIntake(row)
  else if (cmd === 'cancel') void cancelProduction(row)
}

function showWarehouseKit(row: ExecutionRow | Record<string, any> | null | undefined) {
  const status = materialStatus(row)
  return Boolean(status) && status !== '待买'
}

function materialStatus(row: ExecutionRow | Record<string, any> | null | undefined) {
  const s = row?.kit?.material_status
  if (!s) return ''
  if (s === 'kit_ok') return '齐套'
  if (s === 'to_buy') return '待买'
  return '缺料'
}

function materialStatusTag(row: ExecutionRow | Record<string, any> | null | undefined): 'success' | 'warning' | 'danger' {
  const s = row?.kit?.material_status
  if (s === 'kit_ok') return 'success'
  if (s === 'to_buy') return 'warning'
  return 'danger'
}

function warehouseKitOf(row: ExecutionRow) {
  return warehouseKitCache.value[Number(row.id)] || null
}

function warehouseKitWidth(row: ExecutionRow) {
  const sizes = warehouseSizeColumns(row).length
  if (!sizes) return 1180
  return Math.min(1280, 420 + sizes * 64 * warehouseSizedMetrics.length)
}

function warehouseSegmentLabel(line: any) {
  return String(line?.consume_segment_name || '').trim() || '未分段'
}

function compareSizeLabel(a: string, b: string) {
  return a.localeCompare(b, 'zh-CN', { numeric: true })
}

function mergeWarehouseKitMaterials(lines: any[]) {
  const groups = new Map<string, any>()
  for (const ln of lines) {
    const key = String(ln.supplier_product_id ?? `${ln.supplier_product_code}|${ln.color_name || ''}`)
    let row = groups.get(key)
    if (!row) {
      row = {
        ...ln,
        size_qty: {} as Record<string, { required: number; shortage: number; in_transit: number; issued: number }>,
        sizes: [] as string[],
        has_sizes: false,
        required_qty: 0,
        shortage_qty: 0,
        in_transit_qty: 0,
        issued_qty: 0,
      }
      groups.set(key, row)
    }
    const size = String(ln.size_value || '').trim()
    row.required_qty = Number(row.required_qty) + Number(ln.required_qty || 0)
    row.shortage_qty = Number(row.shortage_qty) + Number(ln.shortage_qty || 0)
    row.in_transit_qty = Number(row.in_transit_qty) + Number(ln.in_transit_qty || 0)
    row.issued_qty = Number(row.issued_qty) + Number(ln.issued_qty || 0)
    if (!row.color_name && ln.color_name) row.color_name = ln.color_name
    if (!size) continue
    row.has_sizes = true
    const bucket = row.size_qty[size] || { required: 0, shortage: 0, in_transit: 0, issued: 0 }
    bucket.required += Number(ln.required_qty || 0)
    bucket.shortage += Number(ln.shortage_qty || 0)
    bucket.in_transit += Number(ln.in_transit_qty || 0)
    bucket.issued += Number(ln.issued_qty || 0)
    row.size_qty[size] = bucket
  }
  return [...groups.values()].map((row) => {
    row.sizes = Object.keys(row.size_qty).sort(compareSizeLabel)
    return row
  })
}

function warehouseKitSegments(row: ExecutionRow) {
  const kit = warehouseKitOf(row)
  const lines = Array.isArray(kit?.lines) ? kit.lines : []
  if (!lines.length) return [] as Array<{
    key: string
    label: string
    shortageCount: number
    sizes: string[]
    lines: any[]
  }>

  const groups = new Map<string, any[]>()
  for (const ln of lines) {
    const label = warehouseSegmentLabel(ln)
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(ln)
  }

  const segs = [...groups.entries()].map(([label, seglines]) => {
    const sorted = mergeWarehouseKitMaterials(seglines).sort((a, b) => {
      const sa = Number(a.shortage_qty) > 0 ? 0 : 1
      const sb = Number(b.shortage_qty) > 0 ? 0 : 1
      if (sa !== sb) return sa - sb
      const dq = Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
      if (dq) return dq
      return Number(a.sort_order || 0) - Number(b.sort_order || 0)
    })
    const sizes = [...new Set(sorted.flatMap((x) => (x.sizes || []) as string[]))].sort(compareSizeLabel)
    return {
      key: label,
      label,
      shortageCount: sorted.filter((x) => Number(x.shortage_qty) > 0).length,
      sizes,
      lines: sorted,
    }
  })

  segs.sort((a, b) => {
    const ash = a.shortageCount > 0 ? 0 : 1
    const bsh = b.shortageCount > 0 ? 0 : 1
    if (ash !== bsh) return ash - bsh
    const rankDiff = processSegmentRank(a.label) - processSegmentRank(b.label)
    return rankDiff || a.label.localeCompare(b.label, 'zh')
  })
  return segs
}

const warehouseSizedMetrics = [
  { label: '生产单数量', field: 'order_qty' },
  { label: '报废', field: 'scrap_material_qty' },
  { label: '领料', field: 'picked_qty' },
  { label: '退料', field: 'returned_qty' },
  { label: '仓库现存', field: 'on_hand_qty' },
  { label: '缺口', field: 'shortage_qty' },
]

function warehouseSourceLines(row: ExecutionRow) {
  const kit = warehouseKitOf(row)
  const lines = Array.isArray(kit?.lines) ? kit.lines : []
  return lines.filter((ln) => {
    if (ln?.is_tooling) return false
    return ln?.production_need != null || ln?.warehouse_qty != null || ln?.task_qty != null
  })
}

function sortWarehouseRows(rows: any[]) {
  return rows.sort((a, b) => {
    const rank = processSegmentRank(a.consume_segment_name, a.consume_segment_id)
      - processSegmentRank(b.consume_segment_name, b.consume_segment_id)
    if (rank) return rank
    return String(a.supplier_product_code || '').localeCompare(String(b.supplier_product_code || ''), 'zh')
  })
}

function stampDeptSpan(rows: any[]) {
  let index = 0
  while (index < rows.length) {
    const name = rows[index].consume_segment_name
    let end = index + 1
    while (end < rows.length && rows[end].consume_segment_name === name) end += 1
    rows[index].deptSpan = end - index
    for (let cursor = index + 1; cursor < end; cursor += 1) rows[cursor].deptSpan = 0
    index = end
  }
  return rows
}

function warehousePlainLines(row: ExecutionRow) {
  const groups = new Map<string, any>()
  for (const ln of warehouseSourceLines(row)) {
    if (ln.usage_by_size) continue
    const segment = warehouseSegmentLabel(ln)
    const key = `${segment}\0${ln.supplier_product_id ?? ln.supplier_product_code}`
    let item = groups.get(key)
    if (!item) {
      item = {
        consume_segment_name: segment,
        consume_segment_id: ln.consume_segment_id,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        color_name: ln.color_name,
        plan_qty: Number(ln.plan_qty || 0),
        scrap_qty: 0,
        reported_qty: Number(ln.reported_qty || 0),
        qty_per_pair: ln.qty_per_pair,
        total_usage_qty: 0,
        own_workshop_qty: Number(ln.own_workshop_qty || 0),
        on_hand_qty: Number(ln.on_hand_qty ?? ln.warehouse_qty ?? 0),
        shortage_qty: 0,
      }
      groups.set(key, item)
    }
    item.scrap_qty += Number(ln.scrap_qty || 0)
    item.total_usage_qty += Number(ln.total_usage_qty || 0)
    item.shortage_qty += Number(ln.shortage_qty || 0)
    if (!item.color_name && ln.color_name) item.color_name = ln.color_name
  }
  return stampDeptSpan(sortWarehouseRows([...groups.values()]))
}

function warehouseSizedLines(row: ExecutionRow) {
  const groups = new Map<string, any>()
  for (const ln of warehouseSourceLines(row)) {
    if (!ln.usage_by_size) continue
    const segment = warehouseSegmentLabel(ln)
    const key = `${segment}\0${ln.supplier_product_id ?? ln.supplier_product_code}`
    let item = groups.get(key)
    if (!item) {
      item = {
        consume_segment_name: segment,
        consume_segment_id: ln.consume_segment_id,
        supplier_product_code: ln.supplier_product_code,
        supplier_product_name: ln.supplier_product_name,
        color_name: ln.color_name,
        size_qty: {} as Record<string, Record<string, number>>,
        shortage_qty: 0,
      }
      groups.set(key, item)
    }
    const size = String(ln.size_value || '')
    if (size) {
      item.size_qty[size] = {
        order_qty: Number(ln.order_qty || 0),
        scrap_material_qty: Number(ln.scrap_material_qty || 0),
        picked_qty: Number(ln.picked_qty || 0),
        returned_qty: Number(ln.returned_qty || 0),
        on_hand_qty: Number(ln.on_hand_qty ?? ln.warehouse_qty ?? 0),
        shortage_qty: Number(ln.shortage_qty || 0),
      }
    }
    item.shortage_qty += Number(ln.shortage_qty || 0)
    if (!item.color_name && ln.color_name) item.color_name = ln.color_name
  }
  return stampDeptSpan(sortWarehouseRows([...groups.values()]))
}

function warehouseSizeColumns(row: ExecutionRow) {
  const sizes = new Set<string>()
  for (const ln of warehouseSourceLines(row)) {
    if (ln.usage_by_size && ln.size_value) sizes.add(String(ln.size_value))
  }
  return [...sizes].sort(compareSizeLabel)
}

function warehouseSizeShort(line: any, size: string) {
  return Number(line?.size_qty?.[size]?.shortage_qty || 0) > 0
}

function warehouseSizeMetric(line: any, size: string, field: string) {
  const bucket = line?.size_qty?.[size]
  if (!bucket || bucket[field] == null) return '—'
  return formatMatQty(bucket[field])
}

function warehouseKitSpan({
  row,
  column,
}: {
  row: { deptSpan?: number }
  column: { property?: string }
}) {
  if (column.property !== 'consume_segment_name') return { rowspan: 1, colspan: 1 }
  return row.deptSpan ? { rowspan: row.deptSpan, colspan: 1 } : { rowspan: 0, colspan: 0 }
}

function warehouseKitRowClass({ row }: { row: any }) {
  return Number(row.shortage_qty) > 0 ? 'exe-wh-kit-shortage' : ''
}

function visibleWarehouseKitPopper() {
  return [...document.querySelectorAll<HTMLElement>('.exe-warehouse-kit-popper')].find((el) => {
    const style = getComputedStyle(el)
    return style.display !== 'none' && style.visibility !== 'hidden'
  })
}

/** 用料变高后把弹出层收回视口，底部用内部滚动看完。 */
function fitWarehouseKitPopover() {
  const pop = visibleWarehouseKitPopper()
  if (!pop) return
  const margin = 8
  const body = pop.querySelector<HTMLElement>('.exe-wh-kit-body')
  if (body) body.style.maxHeight = ''
  pop.style.marginTop = ''
  const overflow = () => pop.getBoundingClientRect().bottom - (window.innerHeight - margin)
  let extra = overflow()
  if (extra <= 1) return
  if (body) {
    const next = Math.max(160, body.getBoundingClientRect().height - extra)
    body.style.maxHeight = `${Math.floor(next)}px`
    extra = overflow()
  }
  if (extra > 1) {
    const room = Math.max(0, pop.getBoundingClientRect().top - margin)
    const shift = Math.min(extra, room)
    if (shift > 0) pop.style.marginTop = `${-Math.ceil(shift)}px`
  }
}

function scheduleFitWarehouseKitPopover() {
  nextTick(() => {
    requestAnimationFrame(() => {
      fitWarehouseKitPopover()
      requestAnimationFrame(() => fitWarehouseKitPopover())
    })
  })
}

async function onWarehouseKitShow(row: ExecutionRow) {
  const hid = Number(row.id)
  if (!hid) return
  warehouseKitLoadingId.value = hid
  scheduleFitWarehouseKitPopover()
  try {
    const res: any = await http.get(`/executions/headers/${hid}/materials`, { params: { progress: true } })
    warehouseKitCache.value = { ...warehouseKitCache.value, [hid]: res.data || {} }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载用料失败')
  } finally {
    if (warehouseKitLoadingId.value === hid) warehouseKitLoadingId.value = null
    scheduleFitWarehouseKitPopover()
    relayoutKitTable()
  }
}

function formatIssuedNeed(issued: unknown, required: unknown) {
  return `${formatMatQty(required)}-${formatMatQty(issued)}`
}

function formatMatQty(v: unknown) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

function uniqueNonEmpty(values: Array<string | null | undefined>) {
  const out: string[] = []
  const seen = new Set<string>()
  for (const v of values) {
    const s = String(v || '').trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

function orderNosText(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const r = row as Record<string, any>
  const sos = r.sales_order_nos?.length
    ? r.sales_order_nos
    : uniqueNonEmpty(
        [r.sales_order_no, ...(r.allocations || []).map((a: any) => a.sales_order_no)],
      )
  return sos.length ? sos.join('、') : '—'
}

function customersText(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const customers = row.customers?.length
    ? row.customers
    : uniqueNonEmpty((row.allocations || []).map((a: any) => a.customer_name))
  return customers.length ? customers.join('、') : '—'
}

function sourceOrderNo(row: ExecutionDisplayRow) {
  return row._sourceOrderNo || '—'
}

function sourceCustomer(row: ExecutionDisplayRow) {
  return row._sourceCustomer || '—'
}

function sourceBrand(row: ExecutionDisplayRow) {
  return row._sourceBrand || '—'
}

function sourceBrandTitle(row: ExecutionDisplayRow) {
  return `${sourceCustomer(row)}\n${sourceBrand(row)}`
}

function sourceQty(row: ExecutionDisplayRow) {
  return Number(row._sourceQty || 0)
}

function sourceDeliveryDate(row: ExecutionDisplayRow) {
  return row._sourceDeliveryDate || '—'
}

const SOURCE_ROW_COLUMNS = new Set(['order_nos', 'customers', 'total_qty', 'delivery_date'])

function executionSpanMethod({ row, column }: { row: ExecutionDisplayRow; column: any }) {
  if (row._sourceCount <= 1) return [1, 1]
  const key = String(column.columnKey || column.property || '')
  if (SOURCE_ROW_COLUMNS.has(key)) return [1, 1]
  return row._sourceIndex === 0 ? [row._sourceCount, 1] : [0, 0]
}

function executionSequence(row: ExecutionRow) {
  const index = executions.value.findIndex((item) => Number(item.id) === Number(row.id))
  return index >= 0 ? index + 1 : '—'
}

function projectedFinish(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const computed = String(row.risk?.projected_finish || row.projected_finish || '').slice(0, 10)
  if (computed) return computed
  const status = String(row.status || '')
  if (status === 'completed' || status === 'cancelled') {
    const ends = (row.process_progress || [])
      .map((p: any) => String(p.end_date || '').slice(0, 10))
      .filter(Boolean)
      .sort()
    return ends.length ? ends[ends.length - 1] : '—'
  }
  return '-'
}

function riskOf(row: ExecutionRow) {
  return row.risk || {
    level: 'normal' as const,
    label: '正常',
    reasons: [{ code: 'unknown', label: '暂无异常', detail: '当前未发现明显风险' }],
    recommendation: '按当前顺序生产',
  }
}

function riskTagType(row: ExecutionRow) {
  const level = riskOf(row).level
  if (level === 'late') return 'danger'
  if (level === 'high') return 'warning'
  if (level === 'attention') return 'primary'
  return 'success'
}

function hasRisk(row: ExecutionRow) {
  return riskOf(row).level !== 'normal'
}

function filterText(value: string | null | undefined) {
  return String(value || '').trim()
}

/** 待生产和生产中的生产单可拖拽；查询或交期筛选时禁止，避免局部改序打乱全局。 */
function reorderContextOk() {
  return (
    !filterText(filters.header_no) &&
    !filterText(filters.customer) &&
    !filterText(filters.product_code) &&
    !filterText(filters.order_no) &&
    !filterText(filters.brand) &&
    !filters.deliveryRange
  )
}

const REORDERABLE_STATUSES = new Set(['confirmed', 'cut', 'in_progress'])

function rowReorderable(row: ExecutionRow) {
  return REORDERABLE_STATUSES.has(String(row.status || '')) && reorderContextOk()
}

function canReorder(row: ExecutionRow) {
  return !reorderLoading.value && rowReorderable(row)
}

function reorderDisabledReason() {
  if (reorderLoading.value) return '正在保存生产顺序'
  if (!reorderContextOk()) return '请先清空查询或交期筛选后再拖拽'
  return '仅待生产 / 生产中可拖拽'
}

function reorderableIds() {
  return executions.value.filter(rowReorderable).map((x) => Number(x.id))
}

function rowFromDragEvent(event: DragEvent): { row: ExecutionRow; tr: HTMLTableRowElement } | null {
  const el = event.target as HTMLElement | null
  if (!el?.closest) return null
  const tr = el.closest('tr.el-table__row') as HTMLTableRowElement | null
  if (!tr) return null
  const tbody = tr.parentElement
  if (!tbody) return null
  const rows = Array.from(tbody.querySelectorAll(':scope > tr.el-table__row'))
  const index = rows.indexOf(tr)
  const row = displayExecutions.value[index]
  if (!row) return null
  return { row, tr }
}

function resolveInsertIndex(
  dragId: number,
  targetId: number,
  position: 'before' | 'after',
) {
  const from = executions.value.findIndex((x) => Number(x.id) === dragId)
  const to = executions.value.findIndex((x) => Number(x.id) === targetId)
  if (from < 0 || to < 0) return null
  let insertIndex = position === 'before' ? to : to + 1
  if (insertIndex > from) insertIndex -= 1
  if (insertIndex === from) return null
  return { from, insertIndex }
}

function moveRow(dragId: number, targetId: number, position: 'before' | 'after') {
  const resolved = resolveInsertIndex(dragId, targetId, position)
  if (!resolved) return false
  const next = [...executions.value]
  const [moving] = next.splice(resolved.from, 1)
  if (!moving) return false
  next.splice(resolved.insertIndex, 0, moving)
  executions.value = next
  return true
}

function autoScrollDuringDrag(event: DragEvent) {
  const root = listTableRef.value?.$el as HTMLElement | undefined
  if (!root) return
  const wraps = root.querySelectorAll(
    '.el-table__body-wrapper, .el-table__fixed-body-wrapper',
  ) as NodeListOf<HTMLElement>
  const main = wraps[0]
  if (!main) return
  const rect = main.getBoundingClientRect()
  const edge = 48
  const step = 18
  let delta = 0
  if (event.clientY < rect.top + edge) delta = -step
  else if (event.clientY > rect.bottom - edge) delta = step
  if (!delta) return
  for (const wrap of wraps) wrap.scrollTop += delta
}

function onRowDragStart(event: DragEvent, row: ExecutionRow) {
  if (!canReorder(row)) {
    event.preventDefault()
    return
  }
  draggedHeaderId.value = Number(row.id)
  dropIndicator.value = null
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', String(row.id))
  const ghost = document.createElement('div')
  ghost.textContent = `${executionSequence(row)} · ${row.header_no || row.execution_no || ''}`
  ghost.style.cssText =
    'position:fixed;top:-999px;left:-999px;padding:8px 12px;background:var(--el-color-primary,#409eff);color:#fff;border-radius:6px;font-size:13px;font-weight:600;box-shadow:0 6px 16px rgba(0,0,0,.18);white-space:nowrap;pointer-events:none;z-index:9999;'
  document.body.appendChild(ghost)
  event.dataTransfer.setDragImage(ghost, 24, 18)
  requestAnimationFrame(() => ghost.remove())
}

function reorderRowClassName({ row }: { row: ExecutionRow }) {
  const classes: string[] = []
  const groupIndex = executions.value.findIndex((item) => Number(item.id) === Number(row.id))
  classes.push(groupIndex % 2 === 1 ? 'execution-group-alt' : 'execution-group-base')
  if (draggedHeaderId.value && Number(row.id) === draggedHeaderId.value) classes.push('dragging-row')
  if (dropIndicator.value && Number(row.id) === dropIndicator.value.id) {
    classes.push(dropIndicator.value.position === 'before' ? 'drop-before' : 'drop-after')
  }
  return classes.join(' ')
}

function onTableDragOver(event: DragEvent) {
  if (!draggedHeaderId.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  autoScrollDuringDrag(event)

  const hit = rowFromDragEvent(event)
  if (!hit) return

  const { row, tr } = hit
  const rect = tr.getBoundingClientRect()
  const position: 'before' | 'after' =
    event.clientY < rect.top + rect.height / 2 ? 'before' : 'after'

  // 无效落点（含拖到自身等效位置）不显示插入线
  if (!resolveInsertIndex(draggedHeaderId.value, Number(row.id), position)) {
    if (dropIndicator.value) dropIndicator.value = null
    return
  }
  if (
    dropIndicator.value?.id === Number(row.id) &&
    dropIndicator.value?.position === position
  ) {
    return
  }
  dropIndicator.value = { id: Number(row.id), position }
}

function onTableDragLeave(event: DragEvent) {
  if (!draggedHeaderId.value) return
  const host = tableHostRef.value as HTMLElement | undefined
  const related = event.relatedTarget as Node | null
  if (host && related && host.contains(related)) return
  dropIndicator.value = null
}

async function onTableDrop(event: DragEvent) {
  if (!draggedHeaderId.value || reorderLoading.value) return
  event.preventDefault()
  const indicator = dropIndicator.value
  const dragId = draggedHeaderId.value
  dropIndicator.value = null
  draggedHeaderId.value = null
  if (!indicator) return

  const changed = moveRow(dragId, indicator.id, indicator.position)
  if (!changed) return
  await confirmReorder()
}

function onRowDragEnd() {
  draggedHeaderId.value = null
  dropIndicator.value = null
}

function cancelReorder() {
  const byId = new Map(executions.value.map((x) => [Number(x.id), x]))
  const restored = savedExecutionIds.value.map((id) => byId.get(id)).filter(Boolean) as ExecutionRow[]
  const extras = executions.value.filter((x) => !savedExecutionIds.value.includes(Number(x.id)))
  executions.value = [...restored, ...extras]
  draggedHeaderId.value = null
  dropIndicator.value = null
}

async function confirmReorder() {
  const orderedHeaderIds = reorderableIds()
  const baseHeaderIds = savedExecutionIds.value.filter((id) => {
    const row = executions.value.find((x) => Number(x.id) === id)
    return row ? rowReorderable(row) : false
  })
  reorderLoading.value = true
  try {
    await http.post('/executions/reorder/confirm', {
      ordered_header_ids: orderedHeaderIds,
      base_header_ids: baseHeaderIds,
    })
    ElMessage.success('生产顺序已生效')
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '保存生产顺序失败')
    cancelReorder()
  } finally {
    reorderLoading.value = false
  }
}

function sizeLinePercent(row: { completed_qty?: number; total_qty?: number }) {
  const plan = Math.max(0, Number(row.total_qty || 0))
  if (!plan) return 0
  const completed = Math.max(0, Number(row.completed_qty || 0))
  return Math.min(100, Math.round((completed / plan) * 100))
}

function sizeLineStatus(row: { completed_qty?: number; total_qty?: number }) {
  const plan = Math.max(0, Number(row.total_qty || 0))
  const completed = Math.max(0, Number(row.completed_qty || 0))
  if (plan > 0 && completed >= plan) return { label: '已完成', type: 'success' as const }
  if (completed > 0) return { label: '生产中', type: 'primary' as const }
  return { label: '未开始', type: 'info' as const }
}

function planWindow(row: { start_date?: string | null; end_date?: string | null }) {
  const a = row.start_date || ''
  const b = row.end_date || ''
  if (a && b) return a === b ? a : `${a}–${b}`
  return a || b || '—'
}

async function loadStatusStats() {
  try {
    const res: any = await http.get('/executions/status-stats')
    statusStats.value = {
      total: Number(res.data?.total || 0),
      by_status: {
        confirmed: Number(res.data?.by_status?.confirmed || 0),
        cut: Number(res.data?.by_status?.cut || 0),
        in_progress: Number(res.data?.by_status?.in_progress || 0),
        completed: Number(res.data?.by_status?.completed || 0),
        cancelled: Number(res.data?.by_status?.cancelled || 0),
      },
    }
  } catch {
    // keep previous stats
  }
}

async function loadExecutions() {
  listLoading.value = true
  try {
    const res: any = await http.get('/executions', {
      params: {
        header_no: filterText(filters.header_no) || undefined,
        customer: filterText(filters.customer) || undefined,
        product_code: filterText(filters.product_code) || undefined,
        order_no: filterText(filters.order_no) || undefined,
        brand: filterText(filters.brand) || undefined,
        status: filters.status || undefined,
        delivery_from: filters.deliveryRange?.[0] || undefined,
        delivery_to: filters.deliveryRange?.[1] || undefined,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    executions.value = res.data?.items || []
    total.value = Number(res.data?.total || 0)
    savedExecutionIds.value = executions.value.map((x) => Number(x.id))
    warehouseKitCache.value = {}
    // 数据加载后动态工序列才出现，需重新等比缩放列宽铺满容器，避免横向滚动条
    relayoutListTable()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载生产单失败')
  } finally {
    listLoading.value = false
  }
  void loadStatusStats()
}

async function loadListProcessConfig() {
  try {
    const [orgRes, segmentRes]: any[] = await Promise.all([
      http.get('/org/settings'),
      http.get('/process-segments', { params: { active_only: true } }),
    ])
    listSkivingEnabled.value = Boolean(orgRes.data?.skiving_enabled)
    listSegments.value = segmentRes.data?.items || []
  } catch {
    // 配置读取失败时保留生产单实际工序列，不阻断主列表。
  }
}

function searchExecutions() {
  page.value = 1
  void loadExecutions()
}

async function loadFilterOptions() {
  try {
    const res: any = await http.get('/executions/filter-options')
    const data = res.data || {}
    filterOptions.value = {
      header_nos: data.header_nos || [],
      customers: data.customers || [],
      product_codes: (data.product_codes || []).map((item: ProductCodeOption | string) =>
        typeof item === 'string' ? { product_code: item, image_url: null } : item,
      ),
      order_nos: data.order_nos || [],
      brands: data.brands || [],
    }
  } catch {
    // 下拉失败时仍可看列表
  }
}

function onPageSizeChange() {
  page.value = 1
  void loadExecutions()
}

async function loadFlowCard() {
  const hid = Number(detail.value?.id)
  const seq = ++flowCardSeq
  flowCard.value = null
  if (!hid) {
    flowCardLoading.value = false
    return
  }
  flowCardLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${hid}/flow-card`)
    if (seq !== flowCardSeq) return
    flowCard.value = res.data
  } catch {
    if (seq === flowCardSeq) flowCard.value = null
  } finally {
    if (seq === flowCardSeq) flowCardLoading.value = false
  }
}

async function openDetail(row: ExecutionRow) {
  try {
    flowCard.value = null
    flowCardLoading.value = true
    const res: any = await http.get(`/executions/headers/${row.id}`)
    detail.value = res.data
    detailVisible.value = true
    await loadFlowCard()
  } catch (e: any) {
    flowCardLoading.value = false
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载详情失败')
  }
}

function basketsForBatch(batchId: number) {
  return detailBaskets.value.filter((basket: any) => Number(basket.batch_id) === Number(batchId))
}

function shipmentById(shipmentId: number | null | undefined) {
  if (!shipmentId) return null
  return packingShipments.value.find((shipment: any) => Number(shipment.id) === Number(shipmentId)) || null
}

async function loadPackingShipping() {
  const hid = Number(detail.value?.id)
  packingPlans.value = []
  packingShipments.value = []
  if (!hid) return
  packingShippingLoading.value = true
  try {
    const plansRes: any = await http.get(`/executions/headers/${hid}/packing-plans`)
    packingPlans.value = plansRes.data?.items || []
    const shipmentIds = [
      ...new Set(
        packingPlans.value
          .flatMap((plan: any) => plan.cartons || [])
          .map((carton: any) => Number(carton.shipment_id || 0))
          .filter(Boolean),
      ),
    ]
    const shipmentResults = await Promise.allSettled(
      shipmentIds.map((shipmentId) => http.get(`/shipments/${shipmentId}`)),
    )
    packingShipments.value = shipmentResults
      .filter((result): result is PromiseFulfilledResult<any> => result.status === 'fulfilled')
      .map((result) => result.value?.data)
      .filter(Boolean)
  } catch {
    packingPlans.value = []
    packingShipments.value = []
  } finally {
    packingShippingLoading.value = false
  }
}

async function loadCutBatches() {
  const hid = Number(detail.value?.id)
  cutBatches.value = []
  if (!hid) return
  cutBatchesLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${hid}/cut-batches`)
    cutBatches.value = res.data?.items || []
  } catch {
    cutBatches.value = []
  } finally {
    cutBatchesLoading.value = false
  }
}

async function loadStockDocs() {
  const hid = Number(detail.value?.id)
  stockDocs.value = []
  if (!hid || !canStockIssue.value) return
  stockDocsLoading.value = true
  try {
    const res: any = await http.get('/stock-issues', { params: { header_id: hid, page_size: 100 } })
    stockDocs.value = res.data?.items || []
  } catch {
    stockDocs.value = []
  } finally {
    stockDocsLoading.value = false
  }
}

function shortBatchNo(batchNo: string) {
  return (String(batchNo || '').split('-').pop() || '').padStart(3, '0')
}

function batchStatusLabel(status: string) {
  return ({ open: '已生框', in_production: '流转中', confirmed: '已确认' } as Record<string, string>)[status] || status || '—'
}

function stockDocStatusLabel(status: string) {
  return ({ pending: '待仓库确认', posted: '已过账', void: '已作废' } as Record<string, string>)[status] || status || '—'
}

function formatDetailTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function printCutBatch(batch: any) {
  const hid = Number(detail.value?.id)
  if (!hid || !batch?.id) return
  window.open(`${window.location.origin}/admin/executions/print/${hid}?mode=basket-labels&batch_id=${batch.id}`, '_blank')
}

// ── 工序派工：按工序段合并，每个段单选一个叶子部门 ──
const dispatchVisible = ref(false)
const dispatchLeaves = ref<any[]>([])
const dispatchSaving = ref(false)
const dispatchDeptBySegment = ref<Record<number, number | null>>({})

const dispatchSegmentCards = computed(() => {
  const segmentIds = new Set(
    headerProcesses.value
      .map((process: any) => process.segment_id)
      .filter((id: any) => id != null)
      .map((id: any) => Number(id)),
  )
  const cards: any[] = []
  const bySegment = new Map<number, any>()
  for (const dept of dispatchLeaves.value) {
    const segmentId = Number(dept.process_segment_id)
    if (!segmentIds.has(segmentId)) continue
    let card = bySegment.get(segmentId)
    if (!card) {
      const processes = headerProcesses.value.filter(
        (process: any) => Number(process.segment_id) === segmentId,
      )
      const signatures = processes.map((process: any) =>
        [...(process.assigned_department_ids || [])].map(Number).sort((a, b) => a - b).join(','),
      )
      card = {
        key: `seg-${segmentId}`,
        segmentId,
        name: dept.segment_name || dept.name,
        departments: [],
        inconsistent: new Set(signatures).size > 1,
      }
      bySegment.set(segmentId, card)
      cards.push(card)
    }
    card.departments.push(dept)
  }
  return cards.map((card, index) => ({ ...card, order: index + 1 }))
})

const dispatchUnassignedSegmentCount = computed(() =>
  dispatchSegmentCards.value.filter((segment: any) => dispatchDeptId(segment.segmentId) == null).length,
)

function dispatchDeptId(segmentId: number) {
  const value = dispatchDeptBySegment.value[segmentId]
  return value == null ? null : Number(value)
}

function setDispatchDept(segmentId: number, departmentId: number) {
  dispatchDeptBySegment.value = {
    ...dispatchDeptBySegment.value,
    [segmentId]: Number(departmentId),
  }
}

async function copyDispatchNo() {
  const orderNo = detail.value?.header_no || detail.value?.execution_no
  if (!orderNo) return
  try {
    await navigator.clipboard.writeText(String(orderNo))
    ElMessage.success('生产单号已复制')
  } catch {
    ElMessage.warning('复制失败，请手动复制')
  }
}

async function ensureDispatchOptions() {
  try {
    const res: any = await http.get('/departments/segment-leaves')
    dispatchLeaves.value = res.data?.items || []
  } catch {
    dispatchLeaves.value = []
  }
}

function defaultDispatchSelection() {
  const next: Record<number, number | null> = {}
  for (const card of dispatchSegmentCards.value) {
    const available = new Set(card.departments.map((dept: any) => Number(dept.id)))
    let chosen: number | null = null
    for (const process of headerProcesses.value) {
      if (Number(process.segment_id) !== card.segmentId) continue
      const saved = (process.assigned_department_ids || [])
        .map(Number)
        .find((departmentId: number) => available.has(departmentId))
      if (saved) {
        chosen = saved
        break
      }
    }
    if (chosen == null && card.departments.length === 1) chosen = Number(card.departments[0].id)
    next[card.segmentId] = chosen
  }
  return next
}

function initializeDispatchSelection() {
  dispatchDeptBySegment.value = defaultDispatchSelection()
}

async function openDispatchEditor() {
  if (!headerProcesses.value.length) {
    ElMessage.warning('该生产单暂无可派工工序')
    return
  }
  await ensureDispatchOptions()
  initializeDispatchSelection()
  dispatchVisible.value = true
}

async function openRowDispatch(row: ExecutionRow) {
  try {
    const res: any = await http.get(`/executions/headers/${row.id}`)
    detail.value = res.data
    await loadHeaderProcesses()
    await openDispatchEditor()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载派工信息失败')
  }
}

async function saveDispatch() {
  const headerId = Number(detail.value?.id)
  if (!headerId) return
  if (!dispatchSegmentCards.value.length) {
    ElMessage.warning('没有可派工的叶子部门')
    return
  }
  dispatchSaving.value = true
  try {
    const res: any = await http.patch(`/executions/headers/${headerId}/dispatch-by-segment`, {
      assignments: dispatchSegmentCards.value.map((segment: any) => {
        const departmentId = dispatchDeptId(segment.segmentId)
        return {
          segment_id: segment.segmentId,
          department_ids: departmentId == null ? [] : [departmentId],
        }
      }),
    })
    ElMessage.success('已保存派工')
    headerProcesses.value = res.data?.items || []
    dispatchVisible.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '派工失败')
  } finally {
    dispatchSaving.value = false
  }
}

function clearDispatchSelection() {
  const next: Record<number, number | null> = {}
  for (const card of dispatchSegmentCards.value) {
    next[card.segmentId] = card.departments.length === 1 ? Number(card.departments[0].id) : null
  }
  dispatchDeptBySegment.value = next
}

async function loadHeaderProcesses() {
  const headerId = Number(detail.value?.id)
  if (!headerId) {
    headerProcesses.value = []
    processProgress.value = { all_done: false, current_process_name: null }
    return
  }
  try {
    const res: any = await http.get(`/executions/headers/${headerId}/processes`)
    headerProcesses.value = res.data?.items || []
    processProgress.value = {
      all_done: Boolean(res.data?.all_done),
      current_process_name: res.data?.current_process_name || null,
    }
  } catch {
    headerProcesses.value = []
    processProgress.value = { all_done: false, current_process_name: null }
  }
}

async function loadDetailBaskets() {
  const headerId = Number(detail.value?.id)
  detailBaskets.value = []
  if (!headerId) return
  basketsLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${headerId}/trace-units`)
    const items = res.data?.items || []
    detailBaskets.value = items.filter((u: any) => u.unit_type === 'basket')
  } catch {
    detailBaskets.value = []
  } finally {
    basketsLoading.value = false
  }
}

async function loadHeaderMaterials() {
  const hid = Number(detail.value?.id)
  headerMaterials.value = []
  if (!hid) return
  materialsLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${hid}/materials`)
    headerMaterials.value = res.data?.lines || []
    warehouseKitCache.value = { ...warehouseKitCache.value, [hid]: res.data || {} }
    if (detail.value && res.data) {
      detail.value = {
        ...detail.value,
        kit: {
          kit_ok: Boolean(res.data.kit_ok),
          shortage_lines: res.data.shortage_lines,
          empty_bom: Boolean(res.data.empty_bom),
          first_kit_ok: Boolean(res.data.first_kit_ok),
        },
      }
    }
  } catch {
    headerMaterials.value = []
  } finally {
    materialsLoading.value = false
  }
}

const issueDialogTitle = computed(() => {
  const no =
    issueTarget.value?.header_no ||
    issueTarget.value?.execution_no ||
    detail.value?.header_no ||
    detail.value?.execution_no ||
    ''
  return issueDialogType.value === 'return_mat' ? `退料 · ${no}` : `领料 · ${no}`
})

async function openIssueDialog(
  docType: 'issue' | 'return_mat',
  row?: ExecutionRow | null,
) {
  if (!canStockIssue.value) {
    ElMessage.warning('未开启领退料单能力，请在库存设置中打开')
    return
  }
  const target = row || detail.value
  const hid = Number(target?.id)
  if (!hid) {
    ElMessage.warning('请先打开生产单')
    return
  }
  issueDialogType.value = docType
  issueTarget.value = {
    id: hid,
    header_no: target?.header_no,
    execution_no: (target as any)?.execution_no,
    total_qty: Number(target?.total_qty) || 0,
  }
  issueQtyDraft.value = {}
  issuePairs.value = Math.max(1, Number(target?.total_qty) || 1)
  issueSegmentScope.value = auth.processSegmentId ? 'mine' : 'all'
  if (!auth.processSegmentId && !auth.processSegmentName) {
    // 会话可能尚未拉过 org 元数据
    await auth.refreshPermissions()
    issueSegmentScope.value = auth.processSegmentId ? 'mine' : 'all'
  }
  issueDialogVisible.value = true
  await reloadIssueCandidates()
}

async function reloadIssueCandidates() {
  const hid = Number(issueTarget.value?.id || detail.value?.id)
  if (!hid) return
  issueDialogLoading.value = true
  try {
    const params: Record<string, number> = { header_id: hid }
    if (
      issueDialogType.value === 'issue' &&
      issueSegmentScope.value === 'mine' &&
      auth.processSegmentId
    ) {
      params.consume_segment_id = auth.processSegmentId
    }
    if (issueDialogType.value === 'issue' && issuePairs.value > 0) {
      params.pairs = issuePairs.value
    }
    const res: any = await http.get('/stock-issues/candidates', { params })
    const data = res.data || {}
    issueMeta.value = data
    issueCandidates.value = data.lines || []
    if (issueDialogType.value === 'issue') {
      fillIssueByPairs()
    } else {
      const draft: Record<number, string> = {}
      for (const row of issueCandidates.value) {
        const max = Number(row.returnable_qty) || 0
        draft[row.id] = max > 0 ? String(max) : ''
      }
      issueQtyDraft.value = draft
    }
  } catch (e: any) {
    issueCandidates.value = []
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载领退料失败')
  } finally {
    issueDialogLoading.value = false
  }
}

function fillIssueByPairs() {
  const draft: Record<number, string> = {}
  for (const row of issueCandidates.value) {
    const suggested = Number(row.suggested_qty)
    if (Number.isFinite(suggested) && suggested > 0) {
      draft[row.id] = String(suggested)
      continue
    }
    // 无后端 suggested 时本地估算
    const pairs = Number(issuePairs.value) || 0
    const total = issueTotalQty.value || 0
    const remain = Number(row.remain_need_qty) || 0
    const maxIssue = Number(row.max_issue_qty) || 0
    if (!(pairs > 0) || remain <= 0) {
      draft[row.id] = ''
      continue
    }
    const qpp = Number(row.qty_per_pair) || 0
    const loss = Number(row.loss_rate) || 0
    const coeff = Number(row.size_coeff) || 1
    let need = qpp * coeff * pairs * (1 + loss)
    const required = Number(row.required_qty) || 0
    if (total > 0 && required > 0) {
      const byRatio = (required * pairs) / total
      need = row.usage_by_size ? byRatio : Math.min(need || byRatio, byRatio)
    }
    let qty = Math.min(need, remain)
    if (maxIssue > 0) qty = Math.min(qty, maxIssue)
    draft[row.id] = qty > 0 ? String(Number(qty.toFixed(4))) : ''
  }
  issueQtyDraft.value = draft
}

function onIssuePairsChange() {
  if (issueDialogType.value !== 'issue') return
  // 双数变更时重新拉 suggested（含库存上限）
  void reloadIssueCandidates()
}

async function submitIssueDialog() {
  const hid = Number(issueTarget.value?.id || detail.value?.id)
  if (!hid) return
  const lines: { requirement_id: number; qty: number }[] = []
  for (const row of issueCandidates.value) {
    const qty = Number(issueQtyDraft.value[row.id])
    if (!(qty > 0)) continue
    lines.push({ requirement_id: row.id, qty })
  }
  if (!lines.length) {
    ElMessage.warning('请填写数量')
    return
  }
  const label = issueDialogType.value === 'issue' ? '领料' : '退料'
  await ElMessageBox.confirm(`提交${label}申请（${lines.length} 行），待仓管确认后过账？`, label)
  issuePosting.value = true
  try {
    await http.post('/stock-issues', {
      doc_type: issueDialogType.value,
      header_id: hid,
      lines,
    })
    ElMessage.success(`${label}已提交，待仓管确认`)
    issueDialogVisible.value = false
    if (detail.value?.id === hid) await Promise.all([loadHeaderMaterials(), loadStockDocs()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '提交失败')
  } finally {
    issuePosting.value = false
  }
}

async function loadHeaderPackingSources() {
  const hid = Number(detail.value?.id)
  if (!hid) return
  packingLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${hid}/packing-sources`)
    packingSources.value = res.data?.items || []
  } catch {
    packingSources.value = []
  } finally {
    packingLoading.value = false
  }
}

function generatedPackingPlan(source: any) {
  return packingPlans.value.find(
    (plan: any) => Number(plan.sales_order_line_id) === Number(source?.sales_order_line_id),
  ) || null
}

async function refreshPackingWorkspace() {
  await Promise.all([loadHeaderPackingSources(), loadPackingShipping()])
}

async function openRowCartonMarks(row: ExecutionRow) {
  try {
    const res: any = await http.get(`/executions/headers/${row.id}/packing-plans`)
    const cartons = (res.data?.items || []).flatMap((plan: any) => plan.cartons || [])
    if (!cartons.length) {
      ElMessage.warning('请先生成装箱')
      return
    }
    const maxOpen = 8
    for (const carton of cartons.slice(0, maxOpen)) {
      if (carton?.id) printCarton(carton.id)
    }
    if (cartons.length > maxOpen) {
      ElMessage.info(`已打开前 ${maxOpen} 箱，共 ${cartons.length} 箱可逐箱补打`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载箱唛失败')
  }
}

async function loadHeaderPackingPlans() {
  const hid = Number(detail.value?.id)
  if (!hid) return
  packingLoading.value = true
  try {
    const res: any = await http.get(`/executions/headers/${hid}/packing-plans`)
    packingPlans.value = res.data?.items || []
  } finally {
    packingLoading.value = false
  }
}

async function generateHeaderPacking(source: any) {
  const hid = Number(detail.value?.id)
  const lineId = Number(source?.sales_order_line_id)
  if (!hid || !lineId || !source?.packable) return
  if (generatedPackingPlan(source)) {
    try {
      await ElMessageBox.confirm(
        `重新生成 ${source.sales_order_no} 第${source.line_no}行的箱唛？只能替换尚未报工、入库或出货的草稿箱。`,
        '重新生成箱唛',
        { type: 'warning' },
      )
    } catch {
      return
    }
  }
  packingSaving.value = true
  packingSavingLineId.value = lineId
  try {
    const res: any = await http.post(`/executions/headers/${hid}/packing-plans`, {
      replace_draft: true,
      sales_order_line_id: lineId,
    })
    ElMessage.success(`已生成 ${res.data?.carton_count || 0} 箱`)
    await refreshPackingWorkspace()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成装箱失败')
  } finally {
    packingSaving.value = false
    packingSavingLineId.value = null
  }
}

async function generateAllSourcePacking() {
  const hid = Number(detail.value?.id)
  const pendingSources = packingSources.value.filter(
    (source: any) => source.packable && !generatedPackingPlan(source),
  )
  if (!hid || !pendingSources.length) return
  packingSaving.value = true
  try {
    for (const source of pendingSources) {
      await http.post(`/executions/headers/${hid}/packing-plans`, {
        replace_draft: true,
        sales_order_line_id: source.sales_order_line_id,
      })
    }
    await refreshPackingWorkspace()
    const cartons = packingPlans.value.reduce(
      (sum: number, plan: any) => sum + Number(plan.carton_count || 0),
      0,
    )
    ElMessage.success(`已按 ${pendingSources.length} 条订单明细生成，当前共 ${cartons} 箱`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '批量生成装箱失败')
  } finally {
    packingSaving.value = false
  }
}

const packableWarehouseCartons = computed(() =>
  packingCartons.value.filter((c: any) => c?.id && !c.warehoused_at),
)

function collectCartonSizes(cartons: any[]) {
  const seen = new Set<string>()
  const cols: string[] = []
  for (const c of cartons || []) {
    for (const ln of c.lines || []) {
      const sv = String(ln.size_value || '').trim()
      if (!sv || seen.has(sv)) continue
      seen.add(sv)
      cols.push(sv)
    }
  }
  return cols.sort((a, b) => {
    const na = Number(a)
    const nb = Number(b)
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
    return a.localeCompare(b, 'zh')
  })
}

function cartonSizeQty(row: any, sizeValue: string) {
  return (row?.lines || [])
    .filter((line: any) => String(line.size_value || '').trim() === sizeValue)
    .reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0)
}

function sourceAssortmentQty(row: any, sizeValue: string) {
  return (row?.assortment_lines || [])
    .filter((line: any) => String(line.size_value || '').trim() === sizeValue)
    .reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0)
}

function printCarton(id: number) {
  window.open(`${window.location.origin}/admin/packing/print/${id}`, '_blank')
}

function printAllHeaderCartons() {
  const cartons = packingPlans.value.flatMap((plan: any) => plan.cartons || [])
  if (!cartons.length) {
    ElMessage.warning('请先生成装箱')
    return
  }
  const maxOpen = 8
  for (const c of cartons.slice(0, maxOpen)) {
    if (c?.id) printCarton(c.id)
  }
  if (cartons.length > maxOpen) {
    ElMessage.info(`已打开前 ${maxOpen} 箱，共 ${cartons.length} 箱可逐箱补打`)
  }
}

async function refreshAfterCartonWarehouse() {
  await loadHeaderPackingPlans()
  if (detail.value?.id) {
    const d: any = await http.get(`/executions/headers/${detail.value.id}`)
    detail.value = d.data
  }
  await Promise.all([loadDetailBaskets(), loadHeaderProcesses()])
  await loadExecutions()
}

async function warehouseOneCarton(row: any) {
  if (!row?.id || row.warehoused_at) return
  try {
    await ElMessageBox.confirm(`确认入库箱 ${row.code}（${row.total_qty || 0} 双）？`, '按箱入库', {
      type: 'warning',
    })
  } catch {
    return
  }
  packingWarehousingId.value = row.id
  try {
    await http.post(`/packing-cartons/${row.id}/warehouse`)
    ElMessage.success(`已入库 ${row.code}`)
    await refreshAfterCartonWarehouse()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '入库失败')
  } finally {
    packingWarehousingId.value = null
  }
}

async function warehousePendingCartons() {
  const cartons = packableWarehouseCartons.value
  if (!cartons.length) {
    ElMessage.warning('没有未入库的箱')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将 ${cartons.length} 箱逐箱入库？将按箱写入成品仓与精确产量。`,
      '按箱入库',
      { type: 'warning' },
    )
  } catch {
    return
  }
  packingWarehousing.value = true
  let okCount = 0
  const errors: string[] = []
  try {
    for (const row of cartons) {
      try {
        await http.post(`/packing-cartons/${row.id}/warehouse`)
        okCount += 1
      } catch (e: any) {
        const detail = e?.response?.data?.detail
        const msg =
          (typeof detail === 'string' && detail.trim() && !detail.trim().startsWith('<') && detail) ||
          e?.message ||
          '失败'
        errors.push(`${row.code}: ${msg}`)
      }
    }
    if (okCount) ElMessage.success(`已入库 ${okCount} 箱`)
    if (errors.length) ElMessage.warning(errors.slice(0, 3).join('；'))
    await refreshAfterCartonWarehouse()
  } finally {
    packingWarehousing.value = false
  }
}

function canBuyGap(row: any) {
  if (row?.is_customer_supplied) return false
  if (row.can_create_draft != null) return Boolean(row.can_create_draft)
  return Number(row?.to_buy_qty) > 0 && !row?.has_purchase
}

function goPurchaseOrders() {
  void router.push({ path: '/admin/purchase', query: { tab: 'orders' } })
}

async function buyGap(row: any) {
  if (!canBuyGap(row) || !row?.id) return
  try {
    await ElMessageBox.confirm(
      `只买这颗料还没挂到本生产单的缺口。接单时若已经买过，请先打开采购单核对，避免重复下单。`,
      '补差',
      { type: 'warning', confirmButtonText: '生成草稿' },
    )
  } catch {
    return
  }
  buyingGapId.value = Number(row.id)
  try {
    const res: any = await http.post('/purchase-orders/from-shortages', {
      requirement_ids: [row.id],
      include_shared: true,
    })
    const created = res.data || []
    if (!created.length) {
      ElMessage.warning('没有可买的缺口（可能已有草稿或在途）')
      await loadHeaderMaterials()
      return
    }
    ElMessage.success(`已开 ${created.length} 张草稿，还没发给供应商`)
    await loadHeaderMaterials()
    await router.push({ path: '/admin/purchase', query: { tab: 'orders', refresh: String(Date.now()) } })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '补差失败')
  } finally {
    buyingGapId.value = null
  }
}

function basketStatusLabel(s: string) {
  const map: Record<string, string> = {
    open: '未开工',
    in_process: '流转中',
    done: '已完成',
    // 兼容旧数据：框码不再承担入库或出货，只表达实物框已退出生产流转。
    warehoused: '已回收',
    shipped: '已回收',
    scrapped: '作废',
  }
  return map[s] || s
}

async function cancelExecution(row: ExecutionRow) {
  try {
    await ElMessageBox.confirm(
      `撤回 ${row.header_no || row.execution_no}？数量回到待排池，可重新出方案。已开裁不能撤回。`,
      '撤回待排',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await http.post('/schedule/gantt-withdraw', { header_id: row.id })
    ElMessage.success('已撤回，数量回到待排')
    detailVisible.value = false
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '撤回失败')
  }
}

function canChangeQty(row: ExecutionRow | null | undefined) {
  if (!row || row.status === 'cancelled' || row.status === 'completed') return false
  if (row.started === true) return false
  if (row.started === false) return true
  // 列表未带 started 时：无完成量且未在制视为可改
  return !row.completed_qty && row.status === 'confirmed'
}

function canReschedule(row: ExecutionRow | null | undefined) {
  if (!row || row.status === 'cancelled' || row.status === 'completed') return false
  if (row.started === true) return false
  if (row.status === 'cut' || row.status === 'in_progress') return false
  if (Number(row.completed_qty || 0) > 0) return false
  return row.status === 'confirmed'
}

function canWithdraw(row: ExecutionRow | null | undefined) {
  return canReschedule(row)
}

function canCancelProduction(row: ExecutionRow | null | undefined) {
  if (!row || row.status === 'cancelled' || row.status === 'completed') return false
  if (Number(row.reported_qty || 0) > 0 || Number(row.completed_qty || 0) > 0) return false
  if (Number(row.recut_reported_qty || 0) > 0) return false
  return true
}

async function cancelProduction(row: ExecutionRow) {
  try {
    await ElMessageBox.confirm(
      '确认取消？',
      '取消生产',
      { type: 'warning', confirmButtonText: '取消生产', cancelButtonText: '留下' },
    )
  } catch {
    return
  }
  try {
    await http.post(`/executions/headers/${row.id}/cancel`)
    ElMessage.success('已取消生产单')
    detailVisible.value = false
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '取消失败')
  }
}

function goReschedule(row: ExecutionRow) {
  detailVisible.value = false
  void router.push({ path: '/admin/schedule', query: { reschedule: String(row.id) } })
}

async function openChangeQty(row: ExecutionRow) {
  if (!canChangeQty(row)) {
    ElMessage.warning('已开工不可改量')
    return
  }
  let detailRow = row
  try {
    const res: any = await http.get(`/executions/${row.id}`)
    detailRow = res.data
  } catch {
    /* use list row */
  }
  if (detailRow.started) {
    ElMessage.warning('已开工不可改量')
    return
  }
  changeQtyTarget.value = detailRow
  changeQtyNotes.value = ''
  changeQtyRows.value = (detailRow.allocations || []).map((a) => ({
    sales_order_line_item_id: Number(a.sales_order_line_item_id),
    sales_order_no: a.sales_order_no || String(a.sales_order_line_item_id || ''),
    old_qty: Number(a.qty),
    qty: Number(a.qty),
  }))
  if (!changeQtyRows.value.length) {
    ElMessage.warning('无分配行，无法改量')
    return
  }
  changeQtyVisible.value = true
}

async function submitChangeQty(dryRun: boolean) {
  const id = Number(changeQtyTarget.value?.id)
  if (!id) return
  changeQtySaving.value = true
  try {
    const res: any = await http.post(`/executions/${id}/change-qty`, {
      items: changeQtyRows.value.map((r) => ({
        sales_order_line_item_id: r.sales_order_line_item_id,
        qty: r.qty,
      })),
      notes: changeQtyNotes.value || undefined,
      dry_run: dryRun,
    })
    if (dryRun) {
      const items = res.data?.items || []
      const lines = items
        .map((x: any) => `${x.sales_order_line_item_id}: ${x.old_qty}→${x.new_qty}`)
        .join('；')
      ElMessage.success(`预览合计 ${res.data?.old_total_qty}→${res.data?.new_total_qty}（${lines}）`)
      return
    }
    ElMessage.success(`已改量：合计 ${res.data?.new_total_qty}`)
    changeQtyVisible.value = false
    detailVisible.value = false
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '改量失败')
  } finally {
    changeQtySaving.value = false
  }
}

function printFlowCardDoc(row: ExecutionRow | null) {
  const headerId = Number(row?.id)
  if (!headerId) {
    ElMessage.warning('无生产单，无法打印')
    return
  }
  window.open(
    `${window.location.origin}/admin/executions/print/${headerId}?mode=flow-card`,
    '_blank',
  )
}

function printBasketLabels(row: ExecutionRow | null) {
  const headerId = Number(row?.id)
  if (!headerId) {
    ElMessage.warning('无生产单，无法打印')
    return
  }
  window.open(
    `${window.location.origin}/admin/executions/print/${headerId}?mode=basket-labels`,
    '_blank',
  )
}

/** @deprecated 兼容旧调用：默认打开框码标签 */
function printFlowCard(row: ExecutionRow | null) {
  printBasketLabels(row)
}

function openCutCards(row: ExecutionRow | null) {
  if (!row?.id) return
  if (row.status === 'cancelled') {
    ElMessage.warning('已取消的生产单不能开裁')
    return
  }
  cutTarget.value = row
  cutPreview.value = null
  cutSkipKitReason.value = ''
  suppressCutWatch = true
  cutBundleSize.value = defaultCutBundleSize.value
  cutBatchMode.value = 'single'
  cutBatchQtys.value = [40]
  cutVisible.value = true
  void previewCutCards()
}

// 生产批次：single=不分批（默认一批自动编号）；split=分批（每批双数）
const cutBatchMode = ref<'single' | 'split'>('single')
const cutBatchQtys = ref<number[]>([40])

const batchPreviewText = computed(() =>
  (cutPreview.value?.batches || [])
    .map((b: any) => `${b.batch_no}（${b.qty}双 / ${b.unit_count}筐）`)
    .join('，'),
)

function addCutBatch() {
  cutBatchQtys.value.push(40)
  void previewCutCards()
}

function removeCutBatch(i: number) {
  cutBatchQtys.value.splice(i, 1)
  void previewCutCards()
}

function onCutBatchModeChange() {
  void previewCutCards()
}

function cutBatchPayload(): number[] | null {
  if (cutBatchMode.value !== 'split') return null
  const qtys = cutBatchQtys.value.filter((q) => q && q > 0)
  return qtys.length ? qtys : null
}

// 改拆筐量自动重算计划（防抖），无需点预览
let cutPreviewTimer: number | null = null
let suppressCutWatch = false
watch(cutBundleSize, () => {
  if (suppressCutWatch) {
    suppressCutWatch = false
    return
  }
  if (!cutVisible.value || !cutTarget.value) return
  if (cutPreviewTimer) window.clearTimeout(cutPreviewTimer)
  cutPreviewTimer = window.setTimeout(() => void previewCutCards(), 300)
})
watch(cutSkipKitReason, () => {
  if (!cutVisible.value || !cutTarget.value) return
  if (cutPreviewTimer) window.clearTimeout(cutPreviewTimer)
  cutPreviewTimer = window.setTimeout(() => void previewCutCards(), 300)
})

async function previewCutCards() {
  const id = Number(cutTarget.value?.id)
  if (!id) return
  cutPreviewing.value = true
  try {
    const res: any = await http.post(`/executions/headers/${id}/cut-cards`, null, {
      params: {
        dry_run: true,
        bundle_size: cutBundleSize.value > 0 ? cutBundleSize.value : null,
        only_missing: true,
        skip_kit_reason: cutSkipKitReason.value.trim() || undefined,
        batch_qtys: cutBatchPayload(),
      },
      paramsSerializer: { indexes: null },
    })
    cutPreview.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '预览失败')
  } finally {
    cutPreviewing.value = false
  }
}

async function confirmCutCards() {
  const id = Number(cutTarget.value?.id)
  if (!id) return
  if (cutNeedsKitReason.value && !cutSkipKitReason.value.trim()) {
    ElMessage.warning('首道不齐套，请填写开裁原因')
    return
  }
  cutCreating.value = true
  try {
    const res: any = await http.post(`/executions/headers/${id}/cut-cards`, null, {
      params: {
        dry_run: false,
        bundle_size: cutBundleSize.value > 0 ? cutBundleSize.value : null,
        only_missing: true,
        skip_kit_reason: cutSkipKitReason.value.trim() || undefined,
        batch_qtys: cutBatchPayload(),
      },
      paramsSerializer: { indexes: null },
    })
    cutPreview.value = res.data
    ElMessage.success(`已开裁，生成 ${res.data?.to_create || 0} 个框码；已打开框码标签，请另用「打印生产单」打 A4`)
    cutVisible.value = false
    if (res.data?.print_path) {
      window.open(`${window.location.origin}${res.data.print_path}`, '_blank')
    }
    await loadExecutions()
    if (detail.value?.id === id) await Promise.all([loadCutBatches(), loadDetailBaskets()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '开裁失败')
  } finally {
    cutCreating.value = false
  }
}

onMounted(async () => {
  const q = String(route.query.tab || '')
  if (q === 'kit' || q === 'shortages') {
    // 开裁未齐页已下线：清理遗留 tab 参数
    void router.replace({ path: '/admin/executions', query: { ...route.query, tab: undefined } })
  }
  await Promise.all([loadListProcessConfig(), loadFilterOptions(), loadExecutions()])
  try {
    const settings: any = await http.get('/shop-floor-settings')
    const n = Number(settings.data?.basket_pairs_cutting)
    if (Number.isFinite(n) && n > 0) defaultCutBundleSize.value = n
  } catch {
    /* 读不到用默认 40 */
  }
  const headerId = Number(route.query.header_id || 0)
  const shopId = Number(route.query.shop_order_id || 0)
  if (headerId) {
    const row = executions.value.find((x) => x.id === headerId)
    if (row) {
      void openDetail(row)
    } else {
      // 售后重做等入口可能指向非当前页生产单，按 id 直接打开详情。
      void openDetail({ id: headerId } as ExecutionRow)
    }
  } else if (shopId) {
    const row = executions.value.find((x) => Number(x.shop_order_id) === shopId)
    if (row) void openDetail(row)
  }
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
@media (max-width: 960px) {
  .so-status-stats {
    justify-content: flex-start;
  }
}
.so-stat-chip.tone-confirmed .so-stat-num {
  color: #b45309;
}
.so-stat-chip.tone-cut .so-stat-num {
  color: #7c3aed;
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
.risk-text {
  color: var(--el-color-danger);
  font-weight: 600;
}
.row-drag-handle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 52px;
  min-height: 28px;
  padding: 2px 4px;
  border-radius: 4px;
  color: var(--el-color-primary);
  cursor: grab;
  user-select: none;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.row-drag-handle:hover:not(.disabled) {
  background: var(--el-color-primary-light-9);
}
.row-drag-handle:active:not(.disabled) {
  cursor: grabbing;
}
.row-drag-handle.disabled {
  color: var(--el-text-color-placeholder);
  cursor: not-allowed;
}
.row-drag-handle.is-dragging {
  color: var(--el-color-primary);
  font-weight: 700;
  background: var(--el-color-primary-light-8);
}
.drag-grip {
  letter-spacing: -2px;
  font-size: 12px;
  line-height: 1;
  opacity: 0.75;
}
.drag-index {
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: 600;
}
.execution-table-host.is-row-dragging {
  user-select: none;
}
.execution-table-host.is-row-dragging :deep(.el-table__body tr) {
  cursor: grabbing;
}
.execution-list-table :deep(.execution-group-base) {
  --el-table-tr-bg-color: var(--el-fill-color-blank);
}
.execution-list-table :deep(.execution-group-alt) {
  --el-table-tr-bg-color: var(--el-fill-color-lighter);
}
:deep(.dragging-row td.el-table__cell) {
  opacity: 0.42;
  background-color: var(--el-color-primary-light-9) !important;
}
:deep(.drop-before td.el-table__cell) {
  box-shadow: inset 0 3px 0 0 var(--el-color-primary) !important;
  background-color: var(--el-color-primary-light-9) !important;
}
:deep(.drop-after td.el-table__cell) {
  box-shadow: inset 0 -3px 0 0 var(--el-color-primary) !important;
  background-color: var(--el-color-primary-light-9) !important;
}
.must-material-date {
  color: var(--el-color-danger);
  font-weight: 600;
}
.execution-list-table.execution-list-table :deep(td.exe-brand-col > .cell) {
  white-space: normal;
  text-overflow: clip;
  line-height: 1.25;
}
.exe-brand-stack {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.exe-brand-stack-line {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.35;
}
.exe-brand-stack-brand {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.execution-list-table :deep(th.el-table__cell) {
  padding-top: 3px;
  padding-bottom: 3px;
}
.execution-list-table :deep(th.el-table__cell > .cell) {
  line-height: 18px;
}
.kit-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.4;
}
.dlg-hint {
  margin: 0 0 12px;
}
.issue-pairs-label {
  font-weight: 500;
  color: var(--el-text-color-primary);
}
.issue-pairs-total {
  font-size: 13px;
}
.packing-fit-table {
  width: 100%;
  min-width: 0;
}
.packing-fit-table :deep(.el-table__body-wrapper .el-scrollbar__wrap) {
  overflow-x: hidden;
}
.packing-fit-table :deep(.el-scrollbar__bar.is-horizontal) {
  display: none;
}
.packing-status-stack {
  display: grid;
  gap: 2px;
  min-width: 0;
  font-size: 12px;
  line-height: 1.25;
}
.ellipsis-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tab-count {
  display: inline-flex;
  min-width: 20px;
  height: 20px;
  margin-left: 4px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: #edf1f2;
  color: #52646a;
  font-size: 11px;
  font-style: normal;
}
.detail-section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.detail-section-head h3 { margin: 0; color: #193b44; font-size: 18px; }
.detail-section-head p { margin: 5px 0 0; color: #7a898d; font-size: 12px; }
.batch-table { border-radius: 8px; overflow: hidden; }
.batch-table :deep(.el-table__header th) { background: #f6f8f8; color: #5f7075; font-weight: 600; }
.batch-no { color: #284a53; font: 650 12px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace; }
.batch-expand { padding: 10px 18px 16px 44px; background: #f8faf9; }
.batch-expand-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; color: #294850; font-size: 13px; font-weight: 600; }
.batch-ledger-summary { display: flex; align-items: center; gap: 0; color: #738287; font-size: 12px; white-space: nowrap; }
.batch-ledger-summary span + span::before { margin: 0 12px; color: #c5cdcf; content: '/'; }
.batch-ledger-summary b { margin-right: 3px; color: #274750; font-size: 15px; font-variant-numeric: tabular-nums; }
.batch-ledger { min-height: 100px; }
.batch-ledger :deep(.el-collapse) { border: 0; }
.batch-ledger :deep(.el-collapse-item__header) { height: auto; min-height: 72px; border-bottom-color: #dce4e6; background: transparent; }
.batch-ledger :deep(.el-collapse-item__wrap) { border-bottom-color: #dce4e6; }
.batch-ledger :deep(.el-collapse-item__content) { padding: 0 0 16px; }
.batch-ledger-row { display: grid; grid-template-columns: 78px minmax(150px, 1fr) 76px auto; width: 100%; align-items: center; gap: 14px; padding: 8px 10px 8px 0; }
.batch-ticket { display: flex; align-items: baseline; gap: 6px; padding-left: 12px; border-left: 3px solid #d56229; color: #a74b20; }
.batch-ticket small { font-size: 10px; letter-spacing: .12em; }
.batch-ticket strong { font: 750 17px/1.1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.batch-main { display: flex; flex-direction: column; }
.batch-main > strong { color: #183b44; font-size: 22px; line-height: 1.15; font-variant-numeric: tabular-nums; }
.batch-main > strong small { font-size: 12px; font-weight: 500; }
.batch-main > span { margin-top: 4px; color: #879398; font-size: 11px; }
.batch-fact { display: flex; flex-direction: column; }
.batch-fact small { color: #879398; font-size: 10px; }
.batch-fact b { color: #314e56; font-size: 15px; font-variant-numeric: tabular-nums; }
.batch-ledger-detail { padding: 12px 16px 4px 92px; background: #f8faf9; }
.batch-ledger-detail section { min-width: 0; }
.batch-detail-head { display: flex; align-items: center; justify-content: space-between; min-height: 30px; }
.batch-detail-head h4 { margin: 0; color: #294850; font-size: 13px; }
.batch-detail-head > span { color: #879398; font-size: 11px; }
.doc-lines { display: flex; flex-wrap: wrap; gap: 5px; }
.doc-lines span { padding: 2px 6px; border-radius: 4px; background: #f3f5f6; font-size: 12px; }
.material-list-thumb { width: 38px; height: 38px; display: block; margin: 0 auto; border-radius: 4px; background: #fff; }
.material-toolbar { display: flex; justify-content: flex-end; gap: 8px; width: 100%; margin-bottom: 10px; }
.material-toolbar :deep(.el-button) { width: auto !important; min-width: 88px; flex: 0 0 auto; margin: 0; }
.material-main-table { width: 100% !important; }
.material-docs-collapse { margin-top: 12px; }
.material-docs-collapse :deep(.el-collapse-item__header) { height: 40px; color: #405a61; font-size: 12px; font-weight: 600; }
.consumption-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.consumption-summary > div { padding: 14px 16px; border: 1px solid #dde5e6; border-radius: 10px; background: #f8faf9; }
.consumption-summary span { display: block; color: #78878b; font-size: 11px; }
.consumption-summary strong { display: inline-block; margin-top: 5px; color: #193b44; font-size: 25px; }
.consumption-summary small { margin-left: 4px; color: #879398; }
.consumption-note { margin: 10px 0 0; color: #8a9699; font-size: 11px; }
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
  display: inline-block;
  min-height: 1em;
}
.section-label {
  margin: 16px 0 8px;
  font-weight: 600;
  font-size: 13px;
}
.muted {
  color: var(--el-text-color-secondary);
}
.danger {
  color: var(--el-color-danger);
}
.exe-status {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.exe-status.is-completed,
.exe-status.is-cancelled {
  color: var(--el-text-color-secondary);
}
.exe-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}
.exe-row-actions :deep(.el-dropdown) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
.exe-row-actions :deep(.el-button) {
  margin: 0;
}
:global(.dispatch-dialog) {
  overflow: hidden;
  border: 1px solid #dbe5f0;
  border-radius: 14px;
  box-shadow: 0 24px 64px rgb(26 45 72 / 18%);
}
:global(.dispatch-dialog .el-dialog__header) {
  margin: 0;
  padding: 14px 24px 12px;
  border-bottom: 1px solid #e8eef5;
  background: linear-gradient(135deg, #f7faff 0%, #eef5fc 100%);
}
:global(.dispatch-dialog .el-dialog__body) {
  padding: 16px 24px 0;
}
:global(.dispatch-dialog .el-dialog__footer) {
  padding: 16px 24px;
  border-top: 1px solid #e8eef5;
  background: #fff;
}
.dispatch-dialog-header {
  padding-right: 40px;
}
.dispatch-eyebrow {
  display: block;
  margin-bottom: 2px;
  color: var(--el-color-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
}
.dispatch-header-title-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dispatch-dialog-header h2 {
  margin: 0;
  color: #18283d;
  font-size: 18px;
  line-height: 1.35;
}
.dispatch-copy-button {
  width: 24px;
  height: 24px;
  color: #718096;
}
.dispatch-copy-button:hover {
  color: var(--el-color-primary);
}
.dispatch-dialog-header p {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 12px;
}
.dispatch-flow-scroll {
  max-height: min(58vh, 520px);
  padding: 2px 2px 14px;
  overflow: auto;
  scrollbar-width: thin;
}
.dispatch-flow-track {
  display: grid;
  align-items: start;
  gap: 14px;
  padding: 2px;
}
.dispatch-flow-stage {
  position: relative;
  display: grid;
  grid-template-rows: 22px 38px 18px auto;
  justify-items: center;
  align-content: start;
  min-width: 0;
  padding: 12px 10px 14px;
  border: 1px solid #e2eaf2;
  border-radius: 12px;
  background: #fbfcfe;
  box-shadow: 0 1px 2px rgb(32 50 73 / 4%);
}
.dispatch-flow-stage:not(:last-child)::before {
  position: absolute;
  z-index: 0;
  top: 48px;
  left: 50%;
  width: calc(100% + 14px);
  height: 2px;
  background: #d6e3ee;
  content: '';
}
.dispatch-flow-marker {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  justify-content: center;
  margin: 0;
}
.dispatch-flow-marker > span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 2px solid #a9c8e3;
  border-radius: 50%;
  background: #fff;
  color: #3778aa;
  font: 700 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
}
.dispatch-flow-marker > span.assigned {
  border-color: #2e83c3;
  background: #2e83c3;
  color: #fff;
}
.dispatch-flow-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  width: 100%;
  min-height: 20px;
  margin: 0;
}
.dispatch-flow-title strong {
  overflow: hidden;
  color: #203249;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-flow-status {
  flex: none;
  padding: 1px 5px;
  border-radius: 999px;
  background: #f0f2f5;
  color: #7c8795;
  font-size: 10px;
  line-height: 17px;
}
.dispatch-flow-status.assigned {
  background: #e7f4ed;
  color: #25805b;
}
.dispatch-flow-note {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
}
.dispatch-flow-warning {
  display: block;
  margin: 0;
  color: #b66a16;
  text-align: center;
  font-size: 10px;
}
.dispatch-team-stack {
  display: grid;
  gap: 6px;
  width: 100%;
  max-width: 180px;
  margin: 0 auto;
  padding: 0;
}
.dispatch-team-stack :deep(.el-checkbox) {
  display: flex;
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  min-width: 0;
  margin: 0;
  padding: 0 9px;
  border: 1px solid #e1e8ef;
  border-radius: 8px;
  background: #fff;
  transition: border-color 0.16s ease, background-color 0.16s ease, box-shadow 0.16s ease;
}
.dispatch-team-stack :deep(.el-checkbox:hover) {
  border-color: #a9cbe3;
  box-shadow: 0 2px 7px rgb(46 105 149 / 8%);
}
.dispatch-team-stack :deep(.el-checkbox.is-selected-card) {
  background: #e8f2fb;
  border-color: #78acd2;
  box-shadow: 0 0 0 1px rgb(46 131 195 / 8%);
}
.dispatch-team-stack :deep(.el-checkbox__label) {
  min-width: 0;
  padding-left: 6px;
}
.dispatch-team-name {
  display: block;
  overflow: hidden;
  color: #26384e;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-team-stack :deep(.el-checkbox.is-selected-card) .dispatch-team-name {
  color: #216b9f;
}
.dispatch-team-stack :deep(.el-radio) {
  display: flex;
  box-sizing: border-box;
  width: 100%;
  height: 36px;
  min-width: 0;
  margin: 0;
  padding: 0 9px;
  border: 1px solid #e1e8ef;
  border-radius: 8px;
  background: #fff;
}
.dispatch-team-stack :deep(.el-radio.is-checked) {
  background: #e8f2fb;
  border-color: #78acd2;
}
.dispatch-team-stack :deep(.el-radio__label) {
  min-width: 0;
  padding-left: 6px;
}
.dispatch-team-stack :deep(.el-radio.is-checked) .dispatch-team-name {
  color: #216b9f;
}
.dispatch-flow-empty {
  width: 100%;
  max-width: 180px;
  height: 36px;
  box-sizing: border-box;
  margin: 0 auto;
  padding: 9px 6px;
  border: 1px dashed #d7e0e9;
  border-radius: 8px;
  background: #fff;
  color: #8a96a5;
  text-align: center;
  font-size: 11px;
}
.dispatch-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.dispatch-footer-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.dispatch-clear-button {
  flex: none;
  color: #7b8794;
}
.dispatch-clear-button:hover {
  color: #4d5d70;
  background: #f3f5f7;
}
.dispatch-footer-summary {
  color: #6b7889;
  font-size: 12px;
}
.dispatch-footer-summary strong {
  color: #b66a16;
}
.dispatch-footer-summary.complete {
  color: #25805b;
  font-weight: 600;
}
.dispatch-footer-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
}
@media (max-width: 720px) {
  .dispatch-dialog-footer {
    align-items: stretch;
    flex-direction: column;
  }
  .dispatch-footer-left {
    justify-content: space-between;
  }
  .dispatch-footer-actions {
    justify-content: flex-end;
  }
}
@media (max-width: 640px) {
  .consumption-summary { grid-template-columns: 1fr; }
  .batch-ledger-row { grid-template-columns: 64px minmax(90px, 1fr) 44px auto; gap: 8px; }
  .batch-ledger-detail { padding-left: 12px; }
}
.exe-warehouse-tag {
  cursor: default;
}
.exe-product-select {
  position: relative;
  flex: 0 0 168px;
  width: 168px;
}
.exe-product-select :deep(.el-select) {
  width: 100%;
}
.exe-product-selected-thumb {
  position: absolute;
  left: 8px;
  top: 50%;
  z-index: 1;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  object-fit: cover;
  transform: translateY(-50%);
  pointer-events: none;
}
.exe-product-select.has-thumb :deep(.el-select__wrapper) {
  padding-left: 36px;
}
.execution-delivery-range {
  flex: 0 0 auto;
  display: inline-flex;
}
.execution-delivery-range :deep(.el-date-editor--daterange) {
  --el-date-editor-width: 214px;
  width: 214px !important;
  max-width: 214px;
}
.execution-delivery-range :deep(.el-date-editor--daterange .el-input__wrapper) {
  justify-content: flex-start;
  gap: 0;
  padding-left: 6px;
  padding-right: 2px;
}
.execution-delivery-range :deep(.el-date-editor--daterange .el-range-input) {
  width: 84px !important;
  flex: 0 0 84px;
}
.execution-delivery-range :deep(.el-date-editor--daterange .el-range-separator) {
  flex: 0 0 auto;
  width: auto;
  padding: 0 2px;
}
.execution-delivery-range :deep(.el-date-editor--daterange .el-range__close-icon) {
  display: inline-flex;
  flex: 0 0 14px;
  width: 14px;
  margin-left: 0;
}
</style>

<style>
.exe-product-popper .el-select-dropdown__item {
  height: 40px;
  line-height: 40px;
}
.exe-product-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.exe-product-option img,
.exe-product-option-ph {
  width: 28px;
  height: 28px;
  border-radius: 4px;
  object-fit: cover;
  flex: 0 0 28px;
  background: #f1f5f9;
}
.exe-product-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.execution-detail-dialog .el-dialog__header {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 2;
  width: 48px;
  height: 48px;
  padding: 0;
  margin: 0;
}
.execution-detail-dialog .el-dialog__title {
  display: none;
}
.execution-detail-dialog .el-dialog__body {
  min-height: clamp(420px, 62vh, 600px);
  box-sizing: border-box;
}
.execution-detail-dialog .material-main-table,
.execution-detail-dialog .material-main-table .el-table__inner-wrapper,
.execution-detail-dialog .material-main-table .el-scrollbar,
.execution-detail-dialog .material-main-table .el-scrollbar__wrap {
  width: 100% !important;
  max-width: none !important;
}
@media (max-height: 680px) {
  .execution-detail-dialog .el-dialog__body {
    min-height: calc(100vh - 180px);
  }
}
.exe-warehouse-kit-popper.el-popover {
  max-width: min(96vw, 1120px);
  max-height: calc(100vh - 16px);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 10px 12px 12px;
}
.exe-warehouse-kit-popper .exe-wh-kit-table {
  width: 100% !important;
}
.exe-wh-kit {
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: 100%;
  overflow: hidden;
}
.exe-wh-kit-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
  flex: none;
}
.exe-wh-kit-body {
  flex: 1 1 auto;
  min-height: 0;
  max-height: calc(100vh - 72px);
  overflow: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
  padding-bottom: 6px;
}
.exe-wh-kit-note {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.exe-wh-kit-seg + .exe-wh-kit-seg {
  margin-top: 10px;
}
.exe-wh-kit-seg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.exe-wh-kit-seg-title {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}
.exe-warehouse-kit-popper .must-material-date {
  font-size: 12px;
  font-weight: 600;
}
.exe-warehouse-kit-popper .exe-wh-kit-shortage td {
  background: var(--el-color-danger-light-9) !important;
}
.exe-warehouse-kit-popper .risk-text {
  color: var(--el-color-danger);
  font-weight: 600;
}
.exe-wh-qty-tip {
  border-bottom: 1px dashed var(--el-text-color-secondary);
  cursor: help;
}
.exe-wh-size-tip-table {
  border-collapse: collapse;
  font-size: 12px;
}
.exe-wh-size-tip-table th,
.exe-wh-size-tip-table td {
  padding: 2px 8px;
  text-align: center;
  white-space: nowrap;
}
.exe-wh-size-tip-table th {
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.exe-warehouse-kit-popper .muted {
  color: var(--el-text-color-placeholder);
}
.exe-risk-popper.el-popover {
  padding: 12px 14px;
}
.exe-risk-date {
  color: var(--el-color-danger);
  font-weight: 600;
  cursor: help;
}
.exe-risk-detail {
  display: grid;
  gap: 9px;
}
.exe-risk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.exe-risk-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.exe-risk-reasons {
  display: grid;
  gap: 7px;
  padding: 8px 0;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.exe-risk-reason {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 8px;
  font-size: 12px;
}
.exe-risk-reason span {
  color: var(--el-text-color-secondary);
}
.exe-risk-advice {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 8px;
  font-size: 12px;
}
.exe-risk-advice span {
  color: var(--el-text-color-secondary);
}
</style>
