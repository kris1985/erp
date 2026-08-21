<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">生产单</h1>
        <p class="page-desc">订单确认后自动创建；待生产和生产中均可拖拽调整顺序，缺料催料见仓库弹窗。</p>
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
      <el-input
        v-model="filters.q"
        clearable
        placeholder="生产单号/工厂型号/销售单/客户"
        style="width: 240px"
        @clear="searchExecutions"
        @keyup.enter="searchExecutions"
      />
      <el-select v-model="filters.status" clearable placeholder="状态" style="width: 120px" @change="searchExecutions">
        <el-option label="未完成" value="active" />
        <el-option label="待生产" value="confirmed" />
        <el-option label="生产中" value="production" />
        <el-option label="已完成" value="completed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-select v-model="filters.kit_ok" clearable placeholder="齐套" style="width: 110px" @change="searchExecutions">
        <el-option label="齐套" :value="true" />
        <el-option label="缺料" :value="false" />
      </el-select>
      <el-select v-model="filters.first_kit_ok" clearable placeholder="开裁齐套" style="width: 120px" @change="searchExecutions">
        <el-option label="齐套" :value="true" />
        <el-option label="未齐" :value="false" />
      </el-select>
      <el-date-picker
        v-model="filters.deliveryRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="交货日期起"
        end-placeholder="交货日期止"
        style="width: 240px"
        @change="searchExecutions"
      />
      <el-button type="primary" :loading="listLoading" @click="searchExecutions">查询</el-button>
    </div>
    <div class="execution-risk-summary" aria-label="生产风险摘要">
      <button
        type="button"
        class="execution-risk-chip late"
        :class="{ active: riskFilter === 'late' }"
        @click="filterByRisk('late')"
      >
        <span>必延期</span><strong>{{ riskStats.by_level.late || 0 }}</strong>
      </button>
      <button
        type="button"
        class="execution-risk-chip high"
        :class="{ active: riskFilter === 'high' }"
        @click="filterByRisk('high')"
      >
        <span>高风险</span><strong>{{ riskStats.by_level.high || 0 }}</strong>
      </button>
      <button
        type="button"
        class="execution-risk-chip attention"
        :class="{ active: exceptionFilter === 'progress_lag' }"
        @click="filterByException('progress_lag')"
      >
        <span>进度落后</span><strong>{{ riskStats.progress_lag || 0 }}</strong>
      </button>
      <button
        type="button"
        class="execution-risk-chip attention"
        :class="{ active: exceptionFilter === 'unassigned' }"
        @click="filterByException('unassigned')"
      >
        <span>未派工异常</span><strong>{{ riskStats.unassigned || 0 }}</strong>
      </button>
      <button type="button" class="execution-risk-chip" @click="filterByKitShort">
        <span>缺料</span><strong>{{ riskStats.shortage || 0 }}</strong>
      </button>
      <button
        type="button"
        class="execution-risk-chip"
        :class="{ active: dueSoonActive }"
        @click="filterByDueSoon"
      >
        <span>未来7天交货</span><strong>{{ riskStats.due_7_days || 0 }}</strong>
      </button>
      <button
        v-if="riskFilter || exceptionFilter"
        type="button"
        class="execution-risk-clear"
        @click="filterByRisk('')"
      >清除风险筛选</button>
      <div class="staffing-advice-slot">
        <el-button
          type="primary"
          plain
          :loading="staffingLoading"
          @click="openStaffingAdvice"
        >
          产能优化<template v-if="riskStats.overloaded_processes"> · {{ riskStats.overloaded_processes }}处超负荷</template>
        </el-button>
      </div>
    </div>
    <div v-if="reorderDirty" class="reorder-confirm-bar">
      <div>
        <strong>生产顺序尚未生效</strong>
        <span v-if="reorderPreview?.summary">
          · 预计影响 {{ reorderPreview.summary.affected }} 单，交期风险 {{ reorderPreview.summary.at_risk }} 单
          <template v-if="reorderPreview.summary.shortage">
            ，缺料 {{ reorderPreview.summary.shortage }} 单
          </template>
        </span>
        <span v-else>· 正在计算预计影响</span>
      </div>
      <div>
        <el-button
          v-if="reorderPreview?.summary?.affected || reorderPreview?.summary?.shortage"
          @click="reorderDialogVisible = true"
        >查看影响明细</el-button>
        <el-button @click="cancelReorder">取消并还原</el-button>
        <el-button
          type="primary"
          :loading="reorderLoading"
          :disabled="!reorderPreview"
          @click="reorderDialogVisible = true"
        >完成调整</el-button>
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
      v-loading="listLoading"
      :data="executions"
      stripe
      border
      row-key="id"
      :row-class-name="reorderRowClassName"
      :max-height="tableMaxHeight"
      empty-text="暂无生产单。请先在订单中确认接单，系统会自动创建生产单。"
      @header-dragend="onListHeaderDragend"
      @sort-change="onSortChange"
    >
      <el-table-column label="顺序" width="72" align="center" fixed="left">
        <template #default="{ row, $index }">
          <span
            class="row-drag-handle"
            :class="{ disabled: !canReorder(row), 'is-dragging': draggedHeaderId === Number(row.id) }"
            :draggable="canReorder(row)"
            :title="canReorder(row) ? '按住拖拽调整生产顺序' : reorderDisabledReason()"
            @dragstart="onRowDragStart($event, row, $index)"
            @dragend="onRowDragEnd"
          >
            <span class="drag-grip" aria-hidden="true">⋮⋮</span>
            <span class="drag-index">{{ $index + 1 }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column
        prop="execution_no"
        label="生产单号"
        :width="listColWidth('execution_no', 150)"
        show-overflow-tooltip
        resizable
        sortable="custom"
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
        <template #default="{ row }">{{ orderNosText(row) }}</template>
      </el-table-column>
      <el-table-column
        column-key="customers"
        label="客户"
        :width="listColWidth('customers', 110)"
        show-overflow-tooltip
        resizable
      >
        <template #default="{ row }">{{ customersText(row) }}</template>
      </el-table-column>
      <el-table-column
        prop="product_code"
        label="工厂型号"
        :width="listColWidth('product_code', 110)"
        show-overflow-tooltip
        resizable
        sortable="custom"
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
        label="数量"
        :width="listColWidth('total_qty', 80)"
        align="right"
        resizable
      />
      <el-table-column
        prop="delivery_date"
        label="交货日期"
        :width="listColWidth('delivery_date', 110)"
        resizable
        sortable="custom"
      >
        <template #default="{ row }">{{ row.delivery_date || '—' }}</template>
      </el-table-column>
      <el-table-column
        column-key="projected_finish"
        label="预计交货日期"
        :width="listColWidth('projected_finish', 110)"
        resizable
      >
        <template #default="{ row }">
          <span
            v-if="previewFinish(row)"
            :class="{ 'date-changed': previewFinish(row) !== projectedFinish(row) }"
          >
            {{ previewFinish(row) }}
          </span>
          <span v-else>{{ projectedFinish(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column
        column-key="risk"
        label="风险"
        :width="listColWidth('risk', 88)"
        align="center"
        resizable
      >
        <template #default="{ row }">
          <el-popover
            placement="bottom"
            :width="360"
            trigger="hover"
            :show-after="180"
            :hide-after="120"
            popper-class="exe-risk-popper"
          >
            <template #reference>
              <el-tag
                size="small"
                :type="riskTagType(row)"
                :effect="riskOf(row).level === 'normal' ? 'plain' : 'light'"
                class="exe-risk-tag"
              >
                {{ riskOf(row).label }}
              </el-tag>
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
              <div v-if="riskOf(row).preview" class="exe-risk-preview-note">按当前未生效排序试算</div>
            </div>
          </el-popover>
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
          <el-popover
            v-if="materialStatus(row)"
            placement="bottom"
            :width="580"
            trigger="hover"
            :show-after="200"
            :hide-after="200"
            popper-class="exe-warehouse-kit-popper"
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
                <span v-if="warehouseKitOf(row)?.kit_ready_date" class="muted">
                  预计齐套 {{ warehouseKitOf(row)?.kit_ready_date }}
                </span>
              </div>
              <div class="exe-wh-kit-body">
                <div
                  v-if="!(warehouseKitSegments(row).length)"
                  class="muted exe-wh-kit-empty"
                >
                  {{ warehouseKitLoadingId === Number(row.id) ? '加载中…' : '暂无用料' }}
                </div>
                <div
                  v-for="seg in warehouseKitSegments(row)"
                  :key="seg.key"
                  class="exe-wh-kit-seg"
                >
                  <div class="exe-wh-kit-seg-head">
                    <div class="exe-wh-kit-seg-title">
                      <span>{{ seg.label }}</span>
                      <span
                        v-if="seg.shortageCount && mustMaterialDate(row) !== '—'"
                        class="must-material-date"
                      >
                        必须到料 {{ mustMaterialDate(row) }}
                      </span>
                    </div>
                    <el-tag
                      size="small"
                      :type="seg.shortageCount ? 'danger' : 'success'"
                      effect="plain"
                    >
                      {{ seg.shortageCount ? `缺${seg.shortageCount}` : '齐' }}
                    </el-tag>
                  </div>
                  <el-table
                    :data="seg.lines"
                    size="small"
                    border
                    :row-class-name="warehouseKitRowClass"
                  >
                    <el-table-column prop="supplier_product_code" label="物料" min-width="100" show-overflow-tooltip />
                    <el-table-column prop="supplier_product_name" label="名称" min-width="110" show-overflow-tooltip />
                    <el-table-column label="尺码" width="56" align="center">
                      <template #default="{ row: ln }">{{ ln.size_value || '—' }}</template>
                    </el-table-column>
                    <el-table-column label="需求" width="64" align="right">
                      <template #default="{ row: ln }">{{ formatMatQty(ln.required_qty) }}</template>
                    </el-table-column>
                    <el-table-column label="缺口" width="64" align="right">
                      <template #default="{ row: ln }">
                        <strong :class="Number(ln.shortage_qty) > 0 ? 'risk-text' : 'muted'">
                          {{ formatMatQty(ln.shortage_qty) }}
                        </strong>
                      </template>
                    </el-table-column>
                    <el-table-column label="预计到货日期" width="110" align="center">
                      <template #default="{ row: ln }">
                        <span v-if="Number(ln.shortage_qty) > 0">
                          {{ ln.expected_ready_date || '—' }}
                        </span>
                        <span v-else class="muted">—</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </div>
            </div>
          </el-popover>
          <span v-else class="muted">—</span>
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
          label="派工"
          :width="listColWidth(`proc-${process.key}-plan`, 64)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <span>{{ listProcessQty(row, process.key, 'plan') }}</span>
          </template>
        </el-table-column>
        <el-table-column
          :column-key="`proc-${process.key}-completed`"
          label="完工"
          :width="listColWidth(`proc-${process.key}-completed`, 64)"
          align="center"
          resizable
        >
          <template #default="{ row }">
            <span>{{ listProcessQty(row, process.key, 'completed') }}</span>
          </template>
        </el-table-column>
      </el-table-column>
      <el-table-column
        prop="shipped_qty"
        label="已出货"
        :width="listColWidth('shipped_qty', 80)"
        align="right"
        resizable
      >
        <template #default="{ row }">{{ row.shipped_qty ?? 0 }}</template>
      </el-table-column>
      <el-table-column column-key="actions" label="操作" width="100" fixed="right" :resizable="false">
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

    <el-dialog
      v-model="reorderDialogVisible"
      title="生产顺序调整影响"
      width="1120px"
      class="reorder-impact-dialog"
      :close-on-click-modal="false"
    >
      <div class="reorder-dialog-summary">
        调整后共影响 <strong>{{ reorderPreview?.summary?.affected ?? 0 }}</strong> 个生产单的交期
        <template v-if="reorderPreview?.summary?.at_risk">
          ，其中 <strong class="risk-text">{{ reorderPreview.summary.at_risk }}</strong> 单存在交期风险
        </template>
        <template v-if="reorderPreview?.summary?.shortage">
          ；缺料 <strong>{{ reorderPreview.summary.shortage }}</strong> 单可在仓库弹窗查看必须到料日期
        </template>
      </div>
      <el-table
        :data="reorderImpactRows"
        border
        size="small"
        max-height="420"
        empty-text="该调整不会改变任何生产单的交期"
      >
        <el-table-column type="index" label="#" width="48" align="center" />
        <el-table-column prop="header_no" label="生产单号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="customers" label="客户" min-width="100" show-overflow-tooltip />
        <el-table-column prop="product_code" label="工厂型号" min-width="110" show-overflow-tooltip />
        <el-table-column prop="total_qty" label="数量" width="70" align="right" />
        <el-table-column prop="delivery_date" label="交货日期" width="108">
          <template #default="{ row }">{{ row.delivery_date || '—' }}</template>
        </el-table-column>
        <el-table-column label="原预计交货" width="108">
          <template #default="{ row }">{{ row.old_finish || '—' }}</template>
        </el-table-column>
        <el-table-column label="新预计交货" width="108">
          <template #default="{ row }">
            <span :class="{ 'risk-text': row.at_risk }">{{ row.new_finish || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="顺延" width="76" align="center">
          <template #default="{ row }">
            <span v-if="row.delay_days > 0" class="risk-text">+{{ row.delay_days }}天</span>
            <span v-else-if="row.delay_days < 0" class="success-text">{{ row.delay_days }}天</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="68" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.at_risk" type="danger" size="small" effect="plain">超期</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="cancelReorder">取消并还原</el-button>
        <el-button type="primary" :loading="reorderLoading" @click="confirmReorder">确认生效</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="staffingVisible"
      title="工序产能优化建议"
      width="960px"
      class="staffing-advice-dialog"
      destroy-on-close
    >
      <div class="staffing-summary">
        {{ staffingAdvice?.summary || '根据当前已下发生产单的工序负荷，给出加人 / 减人 / 加班建议。' }}
        <span v-if="staffingAdvice" class="muted">
          · 窗口 {{ staffingAdvice.date_from }} ~ {{ staffingAdvice.date_to }}
          <template v-if="staffingAdvice.allow_overtime"> · 已开加班可排假日</template>
        </span>
      </div>
      <el-table
        v-loading="staffingLoading"
        :data="staffingAdvice?.items || []"
        border
        size="small"
        max-height="480"
        empty-text="暂无负荷数据；请先确认排产并配置工序产能"
      >
        <el-table-column prop="process_name" label="工序" min-width="120" show-overflow-tooltip />
        <el-table-column label="建议" width="88" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="staffingActionTag(row.action)" effect="plain">
              {{ row.action_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="现人数" width="72" align="center">
          <template #default="{ row }">{{ row.current_workers ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="建议人数" width="80" align="center">
          <template #default="{ row }">{{ row.suggested_workers ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="增减" width="64" align="center">
          <template #default="{ row }">
            <span v-if="row.delta_workers > 0" class="risk-text">+{{ row.delta_workers }}</span>
            <span v-else-if="row.delta_workers < 0" class="success-text">{{ row.delta_workers }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="峰值负荷" width="88" align="right">
          <template #default="{ row }">{{ row.peak_load ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="峰值利用率" width="96" align="center">
          <template #default="{ row }">
            <span :class="{ 'risk-text': Number(row.peak_utilization) > 1 }">
              {{ formatUtil(row.peak_utilization) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="超产能天" width="80" align="center">
          <template #default="{ row }">
            <span :class="{ 'risk-text': Number(row.over_capacity_days) > 0 }">
              {{ row.over_capacity_days ?? 0 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="220" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="staffingVisible = false">关闭</el-button>
        <el-button type="primary" :loading="staffingLoading" @click="loadStaffingAdvice">刷新</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dispatchPickVisible"
      :title="`派工 · ${detail?.header_no || detail?.execution_no || ''}`"
      width="560px"
      append-to-body
    >
      <p class="muted" style="margin: 0 0 12px">请选择要派工的工序。</p>
      <div class="dispatch-process-list">
        <div v-for="p in headerProcesses" :key="p.id" class="dispatch-process-row">
          <div>
            <strong>{{ p.label || p.process_name }}</strong>
            <span class="muted" style="margin-left: 8px">
              {{ p.assigned_group_name || (p.assignee_names?.length ? p.assignee_names.join('、') : '未派工') }}
            </span>
          </div>
          <el-button type="primary" link @click="selectDispatchProcess(p)">派工</el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="dispatchPickVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dispatchVisible"
      :title="dispatchLine ? `派工 · ${dispatchLine.label || dispatchLine.process_name}` : '派工'"
      width="520px"
      append-to-body
    >
      <template v-if="dispatchLine">
        <p class="muted" style="margin: 0 0 12px">
          计划 {{ dispatchLine.plan_qty || 0 }} 双 · 日常建议派到班组；特殊任务再指定人员。
        </p>
        <div v-if="dispatchLine.assigned_group_name || dispatchCurrent?.length" style="margin-bottom: 10px">
          <span class="muted" style="font-size: 12px">当前派工：</span>
          <el-tag v-if="dispatchLine.assigned_group_name" size="small" type="success">
            {{ dispatchLine.assigned_group_name }}
          </el-tag>
          <el-tag
            v-for="a in dispatchCurrent"
            :key="a.worker_id"
            size="small"
            style="margin-right: 4px"
          >
            {{ a.worker_name }}
            <span v-if="a.quota_qty != null"> · {{ a.quota_qty }}</span>
          </el-tag>
        </div>
        <el-radio-group v-model="dispatchTargetType" style="margin-bottom: 12px">
          <el-radio-button value="team">按班组</el-radio-button>
          <el-radio-button value="worker">按人员</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="dispatchTargetType === 'team'"
          v-model="dispatchTeamId"
          filterable
          clearable
          style="width: 100%"
          placeholder="选择班组"
        >
          <el-option
            v-for="team in dispatchTeamsForProcess"
            :key="team.id"
            :label="dispatchTeamLabel(team)"
            :value="team.id"
          />
        </el-select>
        <div v-if="dispatchTargetType === 'team'" class="dispatch-load" v-loading="dispatchLoadLoading">
          <div class="dispatch-load__title">
            <span>未来 7 天班组负荷</span>
            <span class="muted">当前工序段：{{ dispatchLine.segment_name || '未标注' }}</span>
          </div>
          <div v-if="dispatchLoadError" class="muted">{{ dispatchLoadError }}</div>
          <template v-else-if="dispatchSelectedLoad">
            <div class="dispatch-load__summary">
              派入 {{ dispatchLine.plan_qty || 0 }} 双后峰值
              <strong :class="dispatchLoadTone(dispatchProjectedPeak(dispatchSelectedLoad))">
                {{ dispatchPercent(dispatchProjectedPeak(dispatchSelectedLoad)) }}
              </strong>
            </div>
            <div class="dispatch-load__days">
              <span
                v-for="day in dispatchSelectedLoad.days"
                :key="day.date"
                :class="dispatchLoadTone(dispatchProjectedUtil(dispatchSelectedLoad, day))"
              >
                {{ day.date.slice(5) }} {{ day.load_qty }}/{{ day.capacity ?? '未配置' }}
              </span>
            </div>
          </template>
          <div v-else-if="!dispatchLoadLoading" class="muted">请选择对应工序段的班组</div>
        </div>
        <el-select
          v-else
          v-model="dispatchWorkerIds"
          multiple
          filterable
          style="width: 100%"
          placeholder="选择工人（可多选）"
        >
          <el-option v-for="w in dispatchWorkers" :key="w.id" :label="w.name" :value="w.id" />
        </el-select>
      </template>
      <template #footer>
        <el-button @click="dispatchVisible = false">取消</el-button>
        <el-button @click="clearDispatch">清空派工</el-button>
        <el-button type="primary" :loading="dispatchSaving" @click="saveDispatch">保存派工</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="detailVisible"
      :title="`生产单 · ${detail?.header_no || detail?.execution_no || ''}`"
      width="min(1180px, 94vw)"
      class="execution-detail-dialog"
    >
      <template v-if="detail">
        <el-tabs v-model="detailTab" class="execution-detail-tabs">
          <el-tab-pane label="概览" name="overview">
            <section class="production-dossier">
              <el-image
                v-if="detail.product_image_url"
                :src="detail.product_image_url"
                :preview-src-list="[detail.product_image_url]"
                fit="contain"
                class="detail-product-thumb"
                preview-teleported
              />
              <div v-else class="detail-product-thumb detail-product-placeholder" aria-label="暂无产品图片">
                <el-icon><Picture /></el-icon>
                <span>暂无图片</span>
              </div>
              <div class="dossier-main">
                <div class="dossier-eyebrow">{{ detail.header_no }}</div>
                <div class="dossier-title-row">
                  <h2>{{ detail.product_code || '未命名款式' }}</h2>
                  <span class="dossier-status" :data-status="detail.status">{{ statusLabel(detail.status) }}</span>
                </div>
                <div class="dossier-spec">
                  <span>{{ detail.color_name || '未定颜色' }}</span>
                  <span>{{ detail.size_summary || detail.size_value || '未分码' }}</span>
                  <span>{{ detail.total_qty || 0 }} 双</span>
                  <span>交期 {{ detail.delivery_date || '—' }}</span>
                </div>
                <p class="dossier-source">{{ sourceSummary(detail) }}</p>
              </div>
              <div class="dossier-kit">
                <span>物料状态</span>
                <strong :class="{ danger: detail.kit && !detail.kit.kit_ok }">
                  {{ detail.kit ? kitFullLabel(detail.kit) : '未计算' }}
                </strong>
                <small>{{ detail.kit?.first_kit_ok ? '可开裁' : '开裁料待齐' }}</small>
              </div>
            </section>
            <section class="production-pulse">
              <div class="exe-four-track" aria-label="生产单数量进度">
                <div><span>计划</span><b>{{ detail.scheduled_qty ?? detail.total_qty ?? 0 }}</b><small>双</small></div>
                <div><span>在制</span><b>{{ detail.wip_qty ?? 0 }}</b><small>双</small></div>
                <div><span>已产</span><b>{{ detail.produced_qty ?? 0 }}</b><small>双</small></div>
                <div><span>已出</span><b>{{ detail.shipped_qty ?? 0 }}</b><small>双</small></div>
              </div>
              <div class="process-rail-head">
                <span>工序进度</span>
                <small v-if="processProgress.all_done">全部完成</small>
                <small v-else-if="processProgress.current_process_name">当前：{{ processProgress.current_process_name }}</small>
              </div>
              <p v-if="!headerProcesses.length" class="muted kit-hint">暂无工序</p>
              <div v-else class="exe-proc-track">
                <div v-for="p in headerProcesses" :key="p.id" class="exe-proc-step" :class="{ 'is-current': p.is_current, 'is-done': p.is_done && !p.is_current }">
                  <div class="exe-proc-name"><span>{{ p.label || p.process_name }}</span><b>{{ p.completed_qty || 0 }}/{{ p.plan_qty || 0 }}</b></div>
                  <el-progress :percentage="processPercent(p)" :stroke-width="4" :show-text="false" :status="processPercent(p) >= 100 ? 'success' : undefined" />
                  <div class="exe-proc-foot">
                    <span>{{ p.assigned_group_name || (p.assignee_names || []).join('、') || '未派工' }}</span>
                    <el-button v-if="detail?.status !== 'cancelled'" link type="primary" size="small" @click="openDispatchProc(p)">派工</el-button>
                  </div>
                </div>
              </div>
            </section>
            <div class="section-label">码明细</div>
            <el-table
              :data="detail.size_lines || []"
              size="small"
              border
              style="width: 100%"
              empty-text="无码明细"
              @header-dragend="onSizeLinesDragend"
            >
              <el-table-column
                prop="size_value"
                label="尺码"
                min-width="120"
                show-overflow-tooltip
              />
              <el-table-column
                column-key="plan_qty"
                label="计划"
                :width="sizeLinesWidth('plan_qty', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ row.total_qty || 0 }}</template>
              </el-table-column>
              <el-table-column
                column-key="completed_qty"
                label="完成"
                :width="sizeLinesWidth('completed_qty', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ row.completed_qty || 0 }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane name="cut-batches">
            <template #label><span>裁断批次 <em class="tab-count">{{ cutBatches.length }}</em></span></template>
            <el-table
              v-loading="cutBatchesLoading"
              :data="cutBatches"
              row-key="id"
              border
              stripe
              size="small"
              style="width: 100%"
              empty-text="尚无裁断批次，首次裁断报工后自动生成"
              class="batch-table"
            >
              <el-table-column type="expand" width="44">
                <template #default="{ row: batch }">
                  <div class="batch-expand">
                    <div class="batch-expand-head"><span>本批框码</span><el-button link type="primary" @click="printCutBatch(batch)">补打本批框码</el-button></div>
                    <el-table :data="basketsForBatch(batch.id)" size="small" style="width: 100%" empty-text="本批次暂无框码">
                      <el-table-column prop="code" label="框码" min-width="180" show-overflow-tooltip />
                      <el-table-column prop="color_name" label="颜色" width="100" />
                      <el-table-column prop="size_value" label="尺码" width="90" />
                      <el-table-column prop="qty" label="双数" width="90" align="right" />
                      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" effect="plain" type="info">{{ basketStatusLabel(row.status) }}</el-tag></template></el-table-column>
                    </el-table>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="批次" min-width="160"><template #default="{ row }"><span class="batch-no">{{ row.batch_no || `裁批 ${shortBatchNo(row.batch_no)}` }}</span></template></el-table-column>
              <el-table-column label="开裁时间" width="150"><template #default="{ row }">{{ formatDetailTime(row.created_at) }}</template></el-table-column>
              <el-table-column prop="qty" label="开裁双数" width="100" align="right" />
              <el-table-column label="框码数" width="90" align="right"><template #default="{ row }">{{ basketsForBatch(row.id).length }}</template></el-table-column>
              <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" effect="plain" :type="row.status === 'confirmed' ? 'success' : 'primary'">{{ batchStatusLabel(row.status) }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="110"><template #default="{ row }"><el-button link type="primary" @click="printCutBatch(row)">补打框码</el-button></template></el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane name="materials">
            <template #label>
              <span>物料</span>
              <el-tag v-if="detail.kit" size="small" :type="detail.kit.kit_ok ? 'success' : 'danger'" style="margin-left: 6px">
                {{ detail.kit.kit_ok ? '齐套' : `缺 ${detail.kit.shortage_lines || 0}` }}
              </el-tag>
            </template>
            <div class="material-toolbar" style="display: flex; flex-direction: row; justify-content: flex-end; align-items: center; gap: 8px">
              <el-button type="primary" size="small" style="width: 88px !important; flex: 0 0 88px" @click="openIssueDialog('issue')">申请领料</el-button>
              <el-button size="small" style="width: 88px !important; flex: 0 0 88px; margin-left: 0" @click="openIssueDialog('return_mat')">申请退料</el-button>
            </div>
            <el-table v-loading="materialsLoading || stockDocsLoading" :data="materialRows" width="100%" :fit="true" size="small" border style="width: 100%; max-width: none" class="material-main-table" empty-text="暂无物料需求" @header-dragend="onMatDragend">
              <el-table-column label="图片" width="52" align="center" class-name="mat-image-col" header-class-name="mat-image-col">
                <template #default="{ row }">
                  <el-image v-if="row.image_url" :src="row.image_url" :preview-src-list="[row.image_url]" preview-teleported fit="contain" class="material-list-thumb" />
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="supplier_product_code" label="物料编码" width="100" show-overflow-tooltip />
              <el-table-column prop="supplier_product_name" label="物料名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="size_value" label="尺码" width="58" />
              <el-table-column prop="pricing_unit_name" label="单位" width="58"><template #default="{ row }">{{ row.pricing_unit_name || '—' }}</template></el-table-column>
              <el-table-column label="需求" width="68" align="right"><template #default="{ row }">{{ formatMatQty(row.required_qty) }}</template></el-table-column>
              <el-table-column label="已领" width="68" align="right"><template #default="{ row }">{{ formatMatQty(row.gross_issued_qty) }}</template></el-table-column>
              <el-table-column label="已退" width="68" align="right"><template #default="{ row }">{{ formatMatQty(row.returned_qty) }}</template></el-table-column>
              <el-table-column label="净领" width="68" align="right"><template #default="{ row }">{{ formatMatQty(row.net_issued_qty) }}</template></el-table-column>
              <el-table-column label="理论耗用" width="82" align="right"><template #default="{ row }">{{ formatMatQty(row.theoretical_qty) }}</template></el-table-column>
              <el-table-column label="待采" width="68" align="right"><template #default="{ row }"><span :class="{ danger: row.to_buy_display_qty > 0 }">{{ formatMatQty(row.to_buy_display_qty) }}</span></template></el-table-column>
              <el-table-column label="状态" width="82"><template #default="{ row }"><el-tag size="small" effect="plain" :type="row.material_status.type">{{ row.material_status.label }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="105">
                <template #default="{ row }">
                  <el-button v-if="canHeaderAllocate(row)" link type="primary" @click="allocateHeaderMaterial(row)">锁料</el-button>
                  <el-button v-if="canHeaderDeallocate(row)" link type="warning" @click="deallocateHeaderMaterial(row)">回收</el-button>
                  <el-button v-if="canBuyGap(row)" link type="warning" :loading="buyingGapId === row.id" @click="buyGap(row)">补差</el-button>
                  <el-button v-else-if="row.has_purchase || Number(row.in_transit_qty) > 0 || Number(row.draft_qty) > 0" link @click="goPurchaseOrders">催料</el-button>
                  <span v-else-if="!canHeaderAllocate(row) && !canHeaderDeallocate(row)" class="muted">—</span>
                </template>
              </el-table-column>
            </el-table>
            <el-collapse class="material-docs-collapse">
              <el-collapse-item name="stock-docs">
                <template #title><span>领退料记录 <em class="tab-count">{{ stockDocs.length }}</em></span></template>
                <el-table :data="stockDocs" stripe size="small" style="width: 100%" empty-text="暂无领退料记录">
                  <el-table-column prop="doc_no" label="单号" width="140" />
                  <el-table-column label="类型" width="90"><template #default="{ row }"><el-tag :type="row.doc_type === 'issue' ? 'primary' : 'warning'" size="small">{{ row.doc_type === 'issue' ? (row.issue_kind || '领料') : '退料' }}</el-tag></template></el-table-column>
                  <el-table-column label="物料明细" min-width="260"><template #default="{ row }"><div class="doc-lines"><span v-for="line in row.lines || []" :key="line.id">{{ line.supplier_product_name || line.supplier_product_code }} × {{ formatMatQty(line.qty) }}</span></div></template></el-table-column>
                  <el-table-column label="状态" width="100"><template #default="{ row }">{{ stockDocStatusLabel(row.status) }}</template></el-table-column>
                  <el-table-column label="时间" width="150"><template #default="{ row }">{{ formatDetailTime(row.posted_at || row.created_at) }}</template></el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>

          <el-tab-pane name="packing-shipping">
            <template #label><span>包装出货 <em class="tab-count">{{ packingCartons.length }}</em></span></template>
            <div class="detail-section-head">
              <div><h3>包装与出货</h3><p>包装后以箱唛追踪；框在成型上线后回收，不再作为出货载体。</p></div>
            </div>
            <el-table ref="packingShippingTableRef" v-loading="packingShippingLoading" :data="packingCartons" stripe border style="width: 100%" empty-text="暂无箱唛记录" @header-dragend="onPackingShippingHeaderDragend">
              <el-table-column prop="code" label="箱唛" :width="packingShippingWidth('code', 160)" show-overflow-tooltip resizable />
              <el-table-column column-key="seq" label="箱序" :width="packingShippingWidth('seq', 80)" align="center" resizable><template #default="{ row }">{{ row.seq }}/{{ row.carton_count || '—' }}</template></el-table-column>
              <el-table-column v-if="packingShippingSizeCols.length" label="尺码配比" align="center">
                <el-table-column
                  v-for="sizeValue in packingShippingSizeCols"
                  :key="sizeValue"
                  :column-key="`size_${sizeValue}`"
                  :label="sizeValue"
                  :width="packingShippingWidth(`size_${sizeValue}`, 48)"
                  align="center"
                  resizable
                >
                  <template #default="{ row }">{{ cartonSizeQty(row, sizeValue) || '—' }}</template>
                </el-table-column>
              </el-table-column>
              <el-table-column v-else prop="assortment" label="尺码配比" :width="packingShippingWidth('assortment', 140)" show-overflow-tooltip resizable />
              <el-table-column prop="total_qty" label="双数" :width="packingShippingWidth('total_qty', 75)" align="right" resizable />
              <el-table-column column-key="packing_status" label="包装" :width="packingShippingWidth('packing_status', 90)" resizable><template #default="{ row }"><el-tag size="small" effect="plain" :type="row.reported_work_log_id ? 'success' : 'info'">{{ row.reported_work_log_id ? '已报工' : '待报工' }}</el-tag></template></el-table-column>
              <el-table-column column-key="warehouse_status" label="入库" :width="packingShippingWidth('warehouse_status', 90)" resizable><template #default="{ row }">{{ row.warehoused_at ? '已入库' : '未入库' }}</template></el-table-column>
              <el-table-column column-key="shipment_no" label="出货单" :width="packingShippingWidth('shipment_no', 150)" resizable><template #default="{ row }">{{ shipmentById(row.shipment_id)?.shipment_no || '未出货' }}</template></el-table-column>
              <el-table-column column-key="ship_date" label="出货日期" :width="packingShippingWidth('ship_date', 110)" resizable><template #default="{ row }">{{ shipmentById(row.shipment_id)?.ship_date || '—' }}</template></el-table-column>
              <el-table-column column-key="actions" label="操作" width="70" :resizable="false"><template #default="{ row }"><el-button link type="primary" @click="printCarton(row.id)">补打</el-button></template></el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane v-if="false" name="materials-legacy">
            <template #label>
              <span>齐套</span>
              <el-tag
                v-if="detail.kit"
                size="small"
                :type="detail.kit.kit_ok ? 'success' : 'danger'"
                style="margin-left: 6px"
              >
                {{ detail.kit.kit_ok ? '齐套' : `缺 ${detail.kit.shortage_lines || 0}` }}
              </el-tag>
            </template>
            <div class="section-label" style="margin-top: 0">齐套</div>
            <p class="muted kit-hint">齐套才能开裁。已买的去催；排产前没买的可在本表补差（先核对采购单，避免买两次）。</p>
            <el-table
              v-loading="materialsLoading"
              :data="headerMaterials"
              size="small"
              border
              style="width: 100%"
              empty-text="暂无用料（排产确认下发后自动快照）"
              @header-dragend="onMatDragend"
            >
              <el-table-column
                prop="supplier_product_code"
                label="物料"
                :width="matWidth('supplier_product_code', 100)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                prop="supplier_product_name"
                label="名称"
                :min-width="flexMat('supplier_product_name', 120)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                column-key="arrived_qty"
                label="占用"
                :width="matWidth('arrived_qty', 80)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ formatMatQty(row.arrived_qty) }}</template>
              </el-table-column>
              <el-table-column
                column-key="cover"
                label="覆盖"
                :width="matWidth('cover', 200)"
                resizable
              >
                <template #default="{ row }">
                  <MaterialCoverCell
                    :required="row.required_qty"
                    :pool="row.shared_credit_qty ?? row.shared_qty"
                    :transit="row.in_transit_qty"
                    :draft="row.draft_qty"
                    :to-buy="row.to_buy_qty ?? row.shortage_qty"
                  />
                </template>
              </el-table-column>
              <el-table-column
                column-key="purchase_status"
                label="采购"
                :width="matWidth('purchase_status', 100)"
                resizable
              >
                <template #default="{ row }">{{ row.purchase_status_label || '—' }}</template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="180" fixed="right" :resizable="false">
                <template #default="{ row }">
                  <el-button
                    v-if="canHeaderAllocate(row)"
                    link
                    type="primary"
                    @click="allocateHeaderMaterial(row)"
                  >
                    锁料
                  </el-button>
                  <el-button
                    v-if="canHeaderDeallocate(row)"
                    link
                    type="warning"
                    @click="deallocateHeaderMaterial(row)"
                  >
                    回收
                  </el-button>
                  <el-button
                    v-if="canBuyGap(row)"
                    link
                    type="warning"
                    :loading="buyingGapId === row.id"
                    @click="buyGap(row)"
                  >
                    补差
                  </el-button>
                  <el-button
                    v-else-if="row.has_purchase || Number(row.in_transit_qty) > 0 || Number(row.draft_qty) > 0"
                    link
                    @click="goPurchaseOrders"
                  >
                    催料
                  </el-button>
                  <span v-else-if="!canHeaderAllocate(row) && !canHeaderDeallocate(row)" class="muted">—</span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

        </el-tabs>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="detail && canChangeQty(detail)"
          type="warning"
          plain
          @click="openChangeQty(detail)"
        >
          改量
        </el-button>
        <el-button
          v-if="detail && canHalt(detail)"
          type="danger"
          plain
          @click="openHalt(detail)"
        >
          停产/减产
        </el-button>
        <el-button
          v-if="detail && canCut(detail)"
          type="primary"
          plain
          @click="openCutCards(detail)"
        >
          开裁打框码
        </el-button>
        <el-button v-if="detail && detail.status !== 'cancelled'" plain @click="openHeaderPacking">
          装箱
        </el-button>
        <el-button v-if="detail?.id || detail?.shop_order_id" plain @click="printFlowCardDoc(detail)">
          打印流转卡
        </el-button>
        <el-button v-if="detail?.id || detail?.shop_order_id" plain @click="printBasketLabels(detail)">
          打印框码
        </el-button>
        <el-button
          v-if="detail && canReschedule(detail)"
          plain
          @click="goReschedule(detail)"
        >
          改排
        </el-button>
        <el-button
          v-if="detail && canWithdraw(detail)"
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
      v-model="packingVisible"
      :title="`装箱 · ${detail?.header_no || detail?.execution_no || ''}`"
      width="860px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="规则">
          <el-radio-group v-model="packingForm.mode">
            <el-radio value="assortment">订单配码</el-radio>
            <el-radio value="single_size">单码</el-radio>
            <el-radio value="mixed">混码</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="packingForm.mode !== 'assortment'" label="每箱双数">
          <el-input-number v-model="packingForm.pairs_per_carton" :min="1" :max="999" />
        </el-form-item>
        <p v-else class="muted" style="margin: 0 0 8px">
          按销售订单配码装箱：每箱色码=订单配码，箱数=订单箱数。
        </p>
      </el-form>
      <div style="margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 8px">
        <el-button type="primary" :loading="packingSaving" @click="generateHeaderPacking">生成装箱</el-button>
        <el-button :loading="packingLoading" @click="loadHeaderPackingPlans">刷新</el-button>
        <el-button
          :disabled="!(packingPlan?.cartons || []).length"
          @click="printAllHeaderCartons"
        >
          打印全部箱唛
        </el-button>
        <el-button
          type="success"
          :disabled="!packableWarehouseCartons.length"
          :loading="packingWarehousing"
          @click="warehousePendingCartons"
        >
          入库未入箱{{ packableWarehouseCartons.length ? ` (${packableWarehouseCartons.length})` : '' }}
        </el-button>
      </div>
      <div v-if="packingPlan" class="muted" style="margin-bottom: 8px">
        {{
          packingPlan.mode === 'assortment'
            ? '订单配码'
            : packingPlan.mode === 'mixed'
              ? '混码'
              : '单码'
        }}
        · 每箱 {{ packingPlan.pairs_per_carton }} 双
        · 共 {{ packingPlan.carton_count }} 箱 / {{ packingPlan.total_qty }} 双
      </div>
      <p class="muted" style="margin: 0 0 8px; font-size: 12px">
        先生成装箱并打印箱唛，再按箱入库（写入成品仓与精确产量）。
      </p>
      <el-table :data="packingPlan?.cartons || []" size="small" border empty-text="尚未生成装箱计划">
        <el-table-column prop="code" label="箱码" min-width="130" show-overflow-tooltip />
        <el-table-column v-if="packingSizeCols.length" label="配码" align="center">
          <el-table-column
            v-for="sz in packingSizeCols"
            :key="sz"
            :label="sz"
            width="52"
            align="center"
          >
            <template #default="{ row }">
              {{ cartonSizeQty(row, sz) || '—' }}
            </template>
          </el-table-column>
        </el-table-column>
        <el-table-column v-else label="配码" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{
              row.assortment ||
              (row.lines || [])
                .map((l: any) => `${l.size_value || ''}×${l.qty}`)
                .filter(Boolean)
                .join(' / ') ||
              '—'
            }}
          </template>
        </el-table-column>
        <el-table-column prop="total_qty" label="双数" width="72" align="right" />
        <el-table-column label="入库" width="72" align="center">
          <template #default="{ row }">
            <span :class="row.warehoused_at ? '' : 'muted'">
              {{ row.warehoused_at ? '已入' : '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="printCarton(row.id)">打印</el-button>
            <el-button
              link
              type="success"
              :disabled="!!row.warehoused_at"
              :loading="packingWarehousingId === row.id"
              @click="warehouseOneCarton(row)"
            >
              入库
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="packingVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="changeQtyVisible"
      :title="`未开工改量 · ${changeQtyTarget?.execution_no || ''}`"
      width="640px"
      destroy-on-close
    >
      <p class="muted dlg-hint">仅未开工可改量；已开工请走停产/减产。须提交全部现有分配行。</p>
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
      v-model="haltVisible"
      :title="`停产/减产 · ${haltTarget?.execution_no || ''}`"
      width="720px"
      destroy-on-close
    >
      <p class="muted dlg-hint">
        已开工回滚：释放未完可产与料占用；未报工筐可作废。已入库数量为下限，不会冲销成品。
      </p>
      <el-form label-width="120px" size="small">
        <el-form-item label="目标合计">
          <el-input-number v-model="haltTargetQty" :min="0" :max="999999" />
          <span class="muted" style="margin-left: 8px">空=全停至下限</span>
        </el-form-item>
        <el-form-item label="作废未报工">
          <el-switch v-model="haltVoidOpen" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="haltNotes" maxlength="120" placeholder="可选" />
        </el-form-item>
      </el-form>
      <el-button :loading="haltSimulating" @click="simulateHalt">重新仿真</el-button>
      <el-alert
        v-if="haltSim?.warning"
        style="margin: 12px 0"
        type="warning"
        :title="haltSim.warning"
        show-icon
        :closable="false"
      />
      <div v-if="haltSim?.will_void?.length" class="section-label">将作废</div>
      <el-table v-if="haltSim?.will_void?.length" :data="haltSim.will_void" size="small" border>
        <el-table-column prop="code" label="码" min-width="120" />
        <el-table-column prop="qty" label="数量" width="80" align="right" />
        <el-table-column prop="status" label="状态" width="90" />
      </el-table>
      <div v-if="haltSim?.pool_releases?.length" class="section-label">可产释放</div>
      <el-table v-if="haltSim?.pool_releases?.length" :data="haltSim.pool_releases" size="small" border>
        <el-table-column prop="sales_order_no" label="销售单" min-width="120" />
        <el-table-column prop="old_qty" label="原占用" width="80" align="right" />
        <el-table-column prop="new_qty" label="新占用" width="80" align="right" />
        <el-table-column prop="release_qty" label="释放" width="80" align="right" />
      </el-table>
      <template #footer>
        <el-button @click="haltVisible = false">取消</el-button>
        <el-button type="danger" :loading="haltConfirming" :disabled="!haltSim" @click="confirmHalt">
          确认停产
        </el-button>
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled, Picture } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import MaterialCoverCell from '@/components/MaterialCoverCell.vue'
import { useAuthStore } from '@/stores/auth'

type RowActionCmd = 'dispatch' | 'cut' | 'issue' | 'print-flow' | 'print-labels' | 'print-cartons' | 'halt'
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
  wip_qty?: number
  produced_qty?: number
  shipped_qty?: number
  progress_kind?: { wip?: string; produced?: string; shipped?: string }
  status: string
  started?: boolean
  shop_order_id?: number | null
  delivery_date?: string | null
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
    material_status?: 'kit_ok' | 'purchasing' | 'short' | null
  } | null
  allocations?: Array<{
    sales_order_line_item_id?: number
    sales_order_no?: string
    customer_name?: string | null
    qty: number
    ratio: number
    produced_qty_est?: number
  }>
  process_progress?: Array<{
    process_id: number
    process_name: string
    label?: string
    plan_qty: number
    completed_qty: number
    status: string
    start_date?: string | null
    end_date?: string | null
    is_current?: boolean
    is_done?: boolean
  }>
}

const router = useRouter()
const route = useRoute()
const listLoading = ref(false)
const executions = ref<ExecutionRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const savedExecutionIds = ref<number[]>([])
const draggedHeaderId = ref<number | null>(null)
const dropIndicator = ref<{ id: number; position: 'before' | 'after' } | null>(null)
const reorderDirty = ref(false)
const reorderLoading = ref(false)
const reorderPreview = ref<any>(null)
const reorderDialogVisible = ref(false)
let reorderPreviewTimer: number | null = null
let reorderPreviewRequest = 0
const staffingVisible = ref(false)
const staffingLoading = ref(false)
const staffingAdvice = ref<any>(null)
const riskFilter = ref('')
const exceptionFilter = ref('')
const riskStats = ref({
  active: 0,
  by_level: { normal: 0, attention: 0, high: 0, late: 0 },
  shortage: 0,
  due_7_days: 0,
  progress_lag: 0,
  unassigned: 0,
  overloaded_processes: 0,
})

const impactedRows = computed(() => {
  const impacts = reorderPreview.value?.impacts || []
  const byId = new Map<number, any>(impacts.map((x: any) => [Number(x.header_id), x]))
  // 缺料单即使交期未变，也要在影响明细里展示必须到料日期
  for (const row of reorderPreview.value?.items || []) {
    const id = Number(row.header_id)
    if (byId.has(id)) continue
    if (row.kit_ok === false && row.must_material_date) byId.set(id, row)
  }
  return [...byId.values()]
})
const impactById = computed(() => {
  const out = new Map<number, any>()
  for (const row of reorderPreview.value?.items || []) out.set(Number(row.header_id), row)
  return out
})
const reorderImpactRows = computed(() => {
  const byId = new Map(executions.value.map((x) => [Number(x.id), x]))
  return impactedRows.value.map((im: any) => {
    const exe = byId.get(Number(im.header_id))
    return {
      ...im,
      header_no: im.header_no || exe?.header_no || exe?.execution_no || '—',
      customers: exe ? customersText(exe) : '—',
      product_code: exe?.product_code || '—',
      total_qty: exe?.total_qty ?? 0,
      is_rush: exe?.is_rush ?? false,
      delivery_date: im.delivery_date || exe?.delivery_date || '—',
      must_material_date: im.must_material_date || null,
    }
  })
})

const listProcessColumns = computed(() => {
  // 工序段重构（21.1/D17）：每段一列；未分段工序进「未分段」兜底列（D18）
  const columns = new Map<string, { key: string; label: string }>()
  for (const row of executions.value) {
    for (const p of row.process_progress || []) {
      const segId = p.segment_id ?? 'unlabeled'
      const label = p.segment_name || (segId === 'unlabeled' ? '未分段' : '工序')
      const key = `seg:${segId}`
      if (!columns.has(key)) {
        columns.set(key, { key, label })
      }
    }
  }
  const segmentOrder = ['截断', '针车', '成型', '包装', '铲皮', '未分段']
  return [...columns.values()].sort((a, b) => {
    const ai = segmentOrder.indexOf(a.label)
    const bi = segmentOrder.indexOf(b.label)
    if (ai === -1 && bi === -1) return 0
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
})

function listProcessQty(row: ExecutionRow, processKey: string, field: 'completed' | 'plan') {
  // 工序段按生产「双数」展示，不能把段内多道工艺的工作量直接相加。
  // 完工双数 = 生产单数量 × 段内有效工艺的最低完成率（瓶颈口径）。
  const segKey = processKey.replace(/^seg:/, '')
  const matched = (row.process_progress || []).filter(
    (p: any) => String(p.segment_id ?? 'unlabeled') === segKey,
  )
  if (!matched.length) return '—'
  const totalQty = Math.max(0, Number(row.total_qty || 0))
  const effective = matched.filter((p: any) => Number(p.plan_qty || 0) > 0)
  if (!effective.length || !totalQty) return '—'
  if (field === 'plan') return String(totalQty)

  const bottleneckRate = Math.min(
    ...effective.map((p: any) => {
      const plan = Number(p.plan_qty || 0)
      const completed = Math.max(0, Number(p.completed_qty || 0))
      return Math.min(1, completed / plan)
    }),
  )
  return String(Math.min(totalQty, Math.floor(totalQty * bottleneckRate + Number.EPSILON)))
}
const filters = reactive({
  q: '',
  status: 'active' as string | undefined,
  kit_ok: undefined as boolean | undefined,
  first_kit_ok: undefined as boolean | undefined,
  deliveryRange: null as [string, string] | null,
})
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
const detailTab = ref('overview')
const detail = ref<ExecutionRow | null>(null)
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
const { tableHostRef, tableMaxHeight } = useTableMaxHeight()
const { colWidth: sizeLinesWidth, onHeaderDragend: onSizeLinesDragend } =
  useTableColWidths('executions-detail-sizes')
const { colWidth: matWidth, flexColMinWidth: flexMat, onHeaderDragend: onMatDragend } =
  useTableColWidths('executions-detail-materials')
const packingShippingTableRef = ref()
const {
  colWidth: packingShippingWidth,
  onHeaderDragend: onPackingShippingHeaderDragend,
} = useTableColWidths('executions-detail-packing-shipping', packingShippingTableRef, {
  flexKey: 'shipment_no',
  flexDefaultMin: 120,
  fitToContainer: true,
})
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
const packingVisible = ref(false)
const packingLoading = ref(false)
const packingSaving = ref(false)
const packingWarehousing = ref(false)
const packingWarehousingId = ref<number | null>(null)
const packingPlan = ref<any | null>(null)
const packingForm = reactive({ mode: 'assortment', pairs_per_carton: 12 })
const cutVisible = ref(false)
const changeQtyVisible = ref(false)
const changeQtyTarget = ref<ExecutionRow | null>(null)
const changeQtyRows = ref<Array<{ sales_order_line_item_id: number; sales_order_no: string; old_qty: number; qty: number }>>([])
const changeQtyNotes = ref('')
const changeQtySaving = ref(false)
const haltVisible = ref(false)
const haltTarget = ref<ExecutionRow | null>(null)
const haltSim = ref<any | null>(null)
const haltTargetQty = ref<number | undefined>(undefined)
const haltVoidOpen = ref(true)
const haltNotes = ref('')
const haltSimulating = ref(false)
const haltConfirming = ref(false)
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

function statusLabel(s: string) {
  const map: Record<string, string> = {
    draft: '草稿',
    confirmed: '待生产',
    cut: '生产中',
    in_progress: '生产中',
    completed: '已完成',
    cancelled: '已取消',
  }
  return map[s] || s
}

type KitSummary = {
  kit_ok?: boolean
  first_kit_ok?: boolean
  empty_bom?: boolean
  shortage_lines?: number
}

function kitFullLabel(kit: KitSummary) {
  if (kit.empty_bom) return '无BOM'
  return kit.kit_ok ? '齐套' : `缺${kit.shortage_lines || 0}`
}

function kitFullTag(kit: KitSummary): 'success' | 'danger' | 'info' {
  if (kit.empty_bom) return 'info'
  return kit.kit_ok ? 'success' : 'danger'
}

function canCut(row: ExecutionRow | null | undefined) {
  return Boolean(row && row.status === 'confirmed')
}

function canIssue(row: ExecutionRow | null | undefined) {
  if (!canStockIssue.value || !row?.id) return false
  return row.status === 'confirmed' || row.status === 'cut' || row.status === 'in_progress'
}

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
  if (canCut(row)) actions.push({ cmd: 'cut', label: '开裁' })
  if (canIssue(row)) actions.push({ cmd: 'issue', label: '领料' })
  if (printPrimary(row) || printSecondary(row)) {
    actions.push({ cmd: 'print-flow', label: '打印流转卡' })
    actions.push({ cmd: 'print-labels', label: '打印框码' })
  }
  if (row.status !== 'cancelled') {
    actions.push({ cmd: 'print-cartons', label: '打印箱唛' })
  }
  if (canHalt(row)) {
    actions.push({ cmd: 'halt', label: '停产', divided: true })
  }
  return actions
}

function runRowAction(row: ExecutionRow, cmd: string) {
  if (cmd === 'dispatch') openRowDispatch(row)
  else if (cmd === 'cut') openCutCards(row)
  else if (cmd === 'issue') openIssueDialog('issue', row)
  else if (cmd === 'print-flow') printFlowCardDoc(row)
  else if (cmd === 'print-labels') printBasketLabels(row)
  else if (cmd === 'print-cartons') openRowCartonMarks(row)
  else if (cmd === 'halt') openHalt(row)
}

function materialStatus(row: ExecutionRow | Record<string, any> | null | undefined) {
  const s = row?.kit?.material_status
  if (s === 'kit_ok') return '齐套'
  if (s === 'purchasing') return '采购中'
  if (s === 'short') return '缺材料'
  return ''
}

function materialStatusTag(row: ExecutionRow | Record<string, any> | null | undefined): 'success' | 'warning' | 'danger' {
  const s = row?.kit?.material_status
  if (s === 'kit_ok') return 'success'
  if (s === 'purchasing') return 'warning'
  return 'danger'
}

const WAREHOUSE_SEGMENT_ORDER = ['截断', '针车', '成型', '包装', '铲皮', '未分段']

function warehouseKitOf(row: ExecutionRow) {
  return warehouseKitCache.value[Number(row.id)] || null
}

function warehouseSegmentLabel(line: any) {
  return String(line?.consume_segment_name || '').trim() || '未分段'
}

function warehouseKitSegments(row: ExecutionRow) {
  const kit = warehouseKitOf(row)
  const lines = Array.isArray(kit?.lines) ? kit.lines : []
  if (!lines.length) return [] as Array<{
    key: string
    label: string
    shortageCount: number
    lines: any[]
  }>

  const groups = new Map<string, any[]>()
  for (const ln of lines) {
    const label = warehouseSegmentLabel(ln)
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(ln)
  }

  const segs = [...groups.entries()].map(([label, seglines]) => {
    const sorted = [...seglines].sort((a, b) => {
      const sa = Number(a.shortage_qty) > 0 ? 0 : 1
      const sb = Number(b.shortage_qty) > 0 ? 0 : 1
      if (sa !== sb) return sa - sb
      const dq = Number(b.shortage_qty || 0) - Number(a.shortage_qty || 0)
      if (dq) return dq
      return Number(a.sort_order || 0) - Number(b.sort_order || 0)
    })
    return {
      key: label,
      label,
      shortageCount: sorted.filter((x) => Number(x.shortage_qty) > 0).length,
      lines: sorted,
    }
  })

  segs.sort((a, b) => {
    const ash = a.shortageCount > 0 ? 0 : 1
    const bsh = b.shortageCount > 0 ? 0 : 1
    if (ash !== bsh) return ash - bsh
    const ai = WAREHOUSE_SEGMENT_ORDER.indexOf(a.label)
    const bi = WAREHOUSE_SEGMENT_ORDER.indexOf(b.label)
    if (ai === -1 && bi === -1) return a.label.localeCompare(b.label, 'zh')
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
  return segs
}

function warehouseKitRowClass({ row }: { row: any }) {
  return Number(row.shortage_qty) > 0 ? 'exe-wh-kit-shortage' : ''
}

async function onWarehouseKitShow(row: ExecutionRow) {
  const hid = Number(row.id)
  if (!hid) return
  warehouseKitLoadingId.value = hid
  try {
    const res: any = await http.get(`/executions/headers/${hid}/materials`)
    warehouseKitCache.value = { ...warehouseKitCache.value, [hid]: res.data || {} }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载用料失败')
  } finally {
    if (warehouseKitLoadingId.value === hid) warehouseKitLoadingId.value = null
  }
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

function sourceSummary(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const customers = row.customers?.length
    ? row.customers
    : uniqueNonEmpty((row.allocations || []).map((a: any) => a.customer_name))
  const sos = row.sales_order_nos?.length
    ? row.sales_order_nos
    : uniqueNonEmpty(
        [row.sales_order_no, ...(row.allocations || []).map((a: any) => a.sales_order_no)],
      )
  if (!customers.length && !sos.length) return '—'
  const c = customers.join('、')
  if (sos.length <= 1) return [c, sos[0]].filter(Boolean).join(' · ') || '—'
  return [c, `${sos.length}单`].filter(Boolean).join(' · ')
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

type SortOrder = 'ascending' | 'descending' | null
const serverSortBy = ref('')
const serverSortOrder = ref<'asc' | 'desc'>('desc')
const SORTABLE_PROPS = new Set([
  'execution_no',
  'product_code',
  'delivery_date',
])

function projectedFinish(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const ends = (row.process_progress || [])
    .map((p: any) => String(p.end_date || '').slice(0, 10))
    .filter(Boolean)
    .sort()
  return ends.length ? ends[ends.length - 1] : '—'
}

function projectedStart(row: ExecutionRow | Record<string, any> | null | undefined) {
  if (!row) return '—'
  const starts = (row.process_progress || [])
    .map((p: any) => String(p.start_date || '').slice(0, 10))
    .filter(Boolean)
    .sort()
  return starts.length ? starts[0] : '—'
}

function isKitShort(row: ExecutionRow | Record<string, any> | null | undefined) {
  const kit = row?.kit
  if (!kit || kit.empty_bom) return false
  return kit.kit_ok === false
}

function mustMaterialDate(row: ExecutionRow) {
  const preview = previewFor(row)
  if (preview?.must_material_date) return String(preview.must_material_date).slice(0, 10)
  if (preview && preview.kit_ok === false && preview.new_start) {
    return String(preview.new_start).slice(0, 10)
  }
  if (!isKitShort(row)) return '—'
  if (preview?.new_start) return String(preview.new_start).slice(0, 10)
  return projectedStart(row)
}

function previewFor(row: ExecutionRow) {
  return impactById.value.get(Number(row.id))
}

function previewFinish(row: ExecutionRow) {
  const preview = previewFor(row)
  if (!preview || !reorderDirty.value) return ''
  const next = String(preview.new_finish || '').slice(0, 10)
  return next || ''
}

function riskOf(row: ExecutionRow) {
  const previewRisk = reorderDirty.value ? previewFor(row)?.risk : null
  const baseRisk = row.risk || {
    level: 'normal',
    label: '正常',
    reasons: [{ code: 'unknown', label: '暂无异常', detail: '当前未发现明显风险' }],
    recommendation: '按当前顺序生产',
  }
  if (!previewRisk) return baseRisk
  const rank: Record<string, number> = { normal: 0, attention: 1, high: 2, late: 3 }
  const level = rank[previewRisk.level] >= rank[baseRisk.level] ? previewRisk.level : baseRisk.level
  const labels: Record<string, string> = { normal: '正常', attention: '关注', high: '高风险', late: '必延期' }
  const reasons = [...(baseRisk.reasons || []), ...(previewRisk.reasons || [])]
  const seen = new Set<string>()
  return {
    ...baseRisk,
    ...previewRisk,
    level,
    label: labels[level] || previewRisk.label || baseRisk.label,
    reasons: reasons.filter((reason: any) => {
      if (seen.has(reason.code)) return false
      seen.add(reason.code)
      return true
    }),
    recommendation:
      rank[previewRisk.level] >= rank[baseRisk.level]
        ? previewRisk.recommendation
        : baseRisk.recommendation,
    preview: true,
  }
}

function riskTagType(row: ExecutionRow) {
  const level = riskOf(row).level
  if (level === 'late') return 'danger'
  if (level === 'high') return 'warning'
  if (level === 'attention') return 'primary'
  return 'success'
}

function filterByRisk(level: string) {
  riskFilter.value = riskFilter.value === level ? '' : level
  exceptionFilter.value = ''
  filters.kit_ok = null
  page.value = 1
  void loadExecutions()
}

function filterByException(type: string) {
  exceptionFilter.value = exceptionFilter.value === type ? '' : type
  riskFilter.value = ''
  filters.kit_ok = null
  page.value = 1
  void loadExecutions()
}

function filterByKitShort() {
  riskFilter.value = ''
  exceptionFilter.value = ''
  filters.kit_ok = filters.kit_ok === false ? null : false
  page.value = 1
  void loadExecutions()
}

function localDateYmd(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const dueSoonRange = computed<[string, string]>(() => {
  const start = new Date()
  const end = new Date(start)
  end.setDate(end.getDate() + 7)
  return [localDateYmd(start), localDateYmd(end)]
})

const dueSoonActive = computed(() => {
  const range = filters.deliveryRange
  return Boolean(
    range &&
    range[0] === dueSoonRange.value[0] &&
    range[1] === dueSoonRange.value[1],
  )
})

function filterByDueSoon() {
  riskFilter.value = ''
  exceptionFilter.value = ''
  filters.kit_ok = null
  filters.deliveryRange = dueSoonActive.value ? null : [...dueSoonRange.value]
  page.value = 1
  void loadExecutions()
}

/** 待生产和生产中的生产单可拖拽；关键词与齐套等筛选仍禁止，避免局部改序打乱全局。 */
function reorderContextOk() {
  return (
    !filters.q.trim() &&
    filters.kit_ok == null &&
    filters.first_kit_ok == null &&
    !filters.deliveryRange
  )
}

const REORDERABLE_STATUSES = new Set(['confirmed', 'cut', 'in_progress'])

function canReorder(row: ExecutionRow) {
  return (
    REORDERABLE_STATUSES.has(String(row.status || '')) &&
    !serverSortBy.value &&
    reorderContextOk()
  )
}

function reorderDisabledReason() {
  if (serverSortBy.value) return '请先取消列排序后再拖拽'
  if (!reorderContextOk()) return '请先清空关键词/齐套/交期筛选后再拖拽'
  return '仅待生产 / 生产中可拖拽'
}

function reorderableIds() {
  return executions.value.filter(canReorder).map((x) => Number(x.id))
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
  const row = executions.value[index]
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

function onRowDragStart(event: DragEvent, row: ExecutionRow, index: number) {
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
  ghost.textContent = `${index + 1} · ${row.header_no || row.execution_no || ''}`
  ghost.style.cssText =
    'position:fixed;top:-999px;left:-999px;padding:8px 12px;background:var(--el-color-primary,#409eff);color:#fff;border-radius:6px;font-size:13px;font-weight:600;box-shadow:0 6px 16px rgba(0,0,0,.18);white-space:nowrap;pointer-events:none;z-index:9999;'
  document.body.appendChild(ghost)
  event.dataTransfer.setDragImage(ghost, 24, 18)
  requestAnimationFrame(() => ghost.remove())
}

function reorderRowClassName({ row }: { row: ExecutionRow }) {
  const classes: string[] = []
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
  if (!draggedHeaderId.value) return
  event.preventDefault()
  const indicator = dropIndicator.value
  const dragId = draggedHeaderId.value
  dropIndicator.value = null
  draggedHeaderId.value = null
  if (!indicator) return

  const changed = moveRow(dragId, indicator.id, indicator.position)
  if (!changed) return

  reorderDirty.value = true
  scheduleReorderPreview()
}

function onRowDragEnd() {
  draggedHeaderId.value = null
  dropIndicator.value = null
}

function scheduleReorderPreview() {
  if (reorderPreviewTimer != null) window.clearTimeout(reorderPreviewTimer)
  reorderPreviewTimer = window.setTimeout(() => {
    reorderPreviewTimer = null
    void previewReorder()
  }, 300)
}

async function previewReorder() {
  const requestId = ++reorderPreviewRequest
  reorderLoading.value = true
  try {
    const res: any = await http.post('/executions/reorder/preview', {
      ordered_header_ids: reorderableIds(),
    })
    if (requestId !== reorderPreviewRequest || !reorderDirty.value) return
    reorderPreview.value = res.data
    // 暂不自动弹出；需要时由「查看影响明细」打开 reorderDialogVisible
  } catch (e: any) {
    if (requestId !== reorderPreviewRequest) return
    ElMessage.error(e?.response?.data?.detail || e?.message || '生产顺序试算失败')
    cancelReorder()
  } finally {
    if (requestId === reorderPreviewRequest) reorderLoading.value = false
  }
}

function cancelReorder() {
  if (reorderPreviewTimer != null) window.clearTimeout(reorderPreviewTimer)
  reorderPreviewTimer = null
  reorderPreviewRequest += 1
  const byId = new Map(executions.value.map((x) => [Number(x.id), x]))
  const restored = savedExecutionIds.value.map((id) => byId.get(id)).filter(Boolean) as ExecutionRow[]
  const extras = executions.value.filter((x) => !savedExecutionIds.value.includes(Number(x.id)))
  executions.value = [...restored, ...extras]
  reorderDirty.value = false
  reorderPreview.value = null
  draggedHeaderId.value = null
  dropIndicator.value = null
  reorderDialogVisible.value = false
}

async function confirmReorder() {
  reorderLoading.value = true
  try {
    await http.post('/executions/reorder/confirm', {
      ordered_header_ids: reorderableIds(),
      base_header_ids: savedExecutionIds.value.filter((id) => {
        const row = executions.value.find((x) => x.id === id)
        return row ? canReorder(row) : false
      }),
    })
    ElMessage.success('生产顺序及预计日期已生效')
    reorderDirty.value = false
    reorderPreview.value = null
    reorderDialogVisible.value = false
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认生产顺序失败')
    cancelReorder()
  } finally {
    reorderLoading.value = false
  }
}

function processPercent(row: { completed_qty?: number; plan_qty?: number }) {
  const plan = Number(row.plan_qty || 0)
  if (!plan) return 0
  return Math.min(100, Math.round((Number(row.completed_qty || 0) / plan) * 100))
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

function onSortChange({ prop, order }: { prop: string; order: SortOrder }) {
  if (!prop || !order || !SORTABLE_PROPS.has(prop)) {
    serverSortBy.value = ''
    serverSortOrder.value = 'desc'
  } else {
    serverSortBy.value = prop
    serverSortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  }
  searchExecutions()
}

async function openStaffingAdvice() {
  staffingVisible.value = true
  await loadStaffingAdvice()
}

async function loadStaffingAdvice() {
  staffingLoading.value = true
  try {
    const res: any = await http.get('/executions/staffing-advice', { params: { days: 14 } })
    staffingAdvice.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载产能优化建议失败')
  } finally {
    staffingLoading.value = false
  }
}

function staffingActionTag(action: string): 'danger' | 'warning' | 'success' | 'info' {
  if (action === 'hire') return 'danger'
  if (action === 'overtime') return 'warning'
  if (action === 'layoff') return 'success'
  if (action === 'configure') return 'info'
  return 'info'
}

function formatUtil(v: unknown) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${Math.round(n * 100)}%`
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
        q: filters.q.trim() || undefined,
        status: filters.status || undefined,
        kit_ok: filters.kit_ok ?? undefined,
        first_kit_ok: filters.first_kit_ok ?? undefined,
        risk_level: riskFilter.value || undefined,
        exception_type: exceptionFilter.value || undefined,
        delivery_from: filters.deliveryRange?.[0] || undefined,
        delivery_to: filters.deliveryRange?.[1] || undefined,
        sort_by: serverSortBy.value || undefined,
        sort_order: serverSortBy.value ? serverSortOrder.value : undefined,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    executions.value = res.data?.items || []
    total.value = Number(res.data?.total || 0)
    savedExecutionIds.value = executions.value.map((x) => Number(x.id))
    warehouseKitCache.value = {}
    reorderDirty.value = false
    reorderPreview.value = null
    if (reorderPreviewTimer != null) window.clearTimeout(reorderPreviewTimer)
    reorderPreviewTimer = null
    reorderPreviewRequest += 1
    // 数据加载后动态工序列才出现，需重新等比缩放列宽铺满容器，避免横向滚动条
    relayoutListTable()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载生产单失败')
  } finally {
    listLoading.value = false
  }
  void loadStatusStats()
  void loadRiskStats()
}

async function loadRiskStats() {
  try {
    const res: any = await http.get('/executions/risk-stats')
    riskStats.value = {
      active: Number(res.data?.active || 0),
      by_level: {
        normal: Number(res.data?.by_level?.normal || 0),
        attention: Number(res.data?.by_level?.attention || 0),
        high: Number(res.data?.by_level?.high || 0),
        late: Number(res.data?.by_level?.late || 0),
      },
      shortage: Number(res.data?.shortage || 0),
      due_7_days: Number(res.data?.due_7_days || 0),
      progress_lag: Number(res.data?.progress_lag || 0),
      unassigned: Number(res.data?.unassigned || 0),
      overloaded_processes: Number(res.data?.overloaded_processes || 0),
    }
  } catch {
    // 摘要失败不影响生产单主列表
  }
}

function searchExecutions() {
  page.value = 1
  void loadExecutions()
}

function onPageSizeChange() {
  page.value = 1
  void loadExecutions()
}

async function openDetail(row: ExecutionRow) {
  try {
    const res: any = await http.get(`/executions/headers/${row.id}`)
    detail.value = res.data
    detailTab.value = 'overview'
    detailVisible.value = true
    await Promise.all([
      loadDetailBaskets(),
      loadHeaderMaterials(),
      loadHeaderProcesses(),
      loadCutBatches(),
      loadStockDocs(),
      loadPackingShipping(),
    ])
  } catch (e: any) {
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

// ── 工序派工 ──
const dispatchVisible = ref(false)
const dispatchPickVisible = ref(false)
const dispatchLine = ref<any>(null)
const dispatchTargetType = ref<'team' | 'worker'>('team')
const dispatchTeamId = ref<number | null>(null)
const dispatchWorkerIds = ref<number[]>([])
const dispatchCurrent = ref<any[]>([])
const dispatchWorkers = ref<any[]>([])
const dispatchTeams = ref<any[]>([])
const dispatchSaving = ref(false)
const dispatchLoadLoading = ref(false)
const dispatchLoadError = ref('')
const dispatchLoadItems = ref<any[]>([])
const dispatchTeamsForProcess = computed(() => {
  const segmentId = dispatchLine.value?.segment_id
  if (segmentId == null) return []
  return dispatchTeams.value.filter((team: any) => Number(team.segment_id) === Number(segmentId))
})
const dispatchSelectedLoad = computed(() => (
  dispatchLoadItems.value.find((row: any) => Number(row.team_id) === Number(dispatchTeamId.value)) || null
))

async function ensureDispatchOptions() {
  const requests: Promise<void>[] = []
  if (!dispatchWorkers.value.length) {
    requests.push(
      http.get('/workers', { params: { is_active: true, page_size: 500 } })
        .then((res: any) => { dispatchWorkers.value = res.data?.items || [] })
        .catch(() => { dispatchWorkers.value = [] }),
    )
  }
  if (!dispatchTeams.value.length) {
    requests.push(
      http.get('/teams')
        .then((res: any) => { dispatchTeams.value = res.data?.items || [] })
        .catch(() => { dispatchTeams.value = [] }),
    )
  }
  await Promise.all(requests)
}

async function openRowDispatch(row: ExecutionRow) {
  try {
    const res: any = await http.get(`/executions/headers/${row.id}`)
    detail.value = res.data
    await loadHeaderProcesses()
    if (!headerProcesses.value.length) {
      ElMessage.warning('该生产单暂无可派工工序')
      return
    }
    if (headerProcesses.value.length === 1) {
      await openDispatchProc(headerProcesses.value[0])
      return
    }
    dispatchPickVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载派工信息失败')
  }
}

function selectDispatchProcess(row: any) {
  dispatchPickVisible.value = false
  // Element Plus 的关闭动画约 300ms；等遮罩和焦点锁完全释放后再打开人员弹窗。
  window.setTimeout(() => {
    void openDispatchProc(row)
  }, 350)
}

async function openDispatchProc(row: any) {
  dispatchLine.value = row
  dispatchTeamId.value = row.assigned_group_id ? Number(row.assigned_group_id) : null
  dispatchCurrent.value = (row.assignments || []).map((a: any) => ({
    worker_id: a.worker_id,
    worker_name: a.worker_name || a.worker_id,
    quota_qty: a.quota_qty,
  }))
  dispatchWorkerIds.value = dispatchCurrent.value.map((a: any) => a.worker_id)
  dispatchTargetType.value = dispatchTeamId.value ? 'team' : (dispatchWorkerIds.value.length ? 'worker' : 'team')
  await ensureDispatchOptions()
  if (dispatchTeamId.value && !dispatchTeamsForProcess.value.some((t: any) => Number(t.id) === dispatchTeamId.value)) {
    dispatchTeamId.value = null
  }
  dispatchVisible.value = true
  void loadDispatchTeamLoad(row)
}

async function loadDispatchTeamLoad(row: any) {
  dispatchLoadItems.value = []
  dispatchLoadError.value = ''
  if (!row?.process_id) return
  const from = row.start_date || new Date().toISOString().slice(0, 10)
  const end = new Date(`${from}T00:00:00`)
  end.setDate(end.getDate() + 6)
  dispatchLoadLoading.value = true
  try {
    const res: any = await http.get('/schedule/team-load', {
      params: {
        process_id: row.process_id,
        date_from: from,
        date_to: end.toISOString().slice(0, 10),
        exclude_order_process_id: row.order_process_id,
      },
    })
    const allowed = new Set(dispatchTeamsForProcess.value.map((t: any) => Number(t.id)))
    dispatchLoadItems.value = (res.data?.items || []).filter((x: any) => allowed.has(Number(x.team_id)))
  } catch (e: any) {
    dispatchLoadError.value = e?.response?.data?.detail || '班组负荷暂不可用'
  } finally {
    dispatchLoadLoading.value = false
  }
}

function dispatchWorkdays() {
  const start = dispatchLine.value?.start_date
  const end = dispatchLine.value?.end_date
  if (!start || !end) return Math.max(1, dispatchSelectedLoad.value?.days?.length || 1)
  const cursor = new Date(`${start}T00:00:00`)
  const last = new Date(`${end}T00:00:00`)
  let count = 0
  while (cursor <= last) {
    if (cursor.getDay() !== 0 && cursor.getDay() !== 6) count += 1
    cursor.setDate(cursor.getDate() + 1)
  }
  return Math.max(1, count)
}

function dispatchProjectedUtil(_team: any, day: any) {
  if (!day?.capacity) return null
  const added = Number(dispatchLine.value?.plan_qty || 0) / dispatchWorkdays()
  return (Number(day.load_qty || 0) + added) / Number(day.capacity)
}

function dispatchProjectedPeak(team: any) {
  const values = (team?.days || []).map((day: any) => dispatchProjectedUtil(team, day)).filter((x: any) => x != null)
  return values.length ? Math.max(...values) : null
}

function dispatchPercent(value: number | null) {
  return value == null ? '未配置产能' : `${Math.round(value * 100)}%`
}

function dispatchLoadTone(value: number | null) {
  if (value == null) return 'muted'
  if (value > 1) return 'dispatch-load--danger'
  if (value >= 0.9) return 'dispatch-load--warn'
  return 'dispatch-load--ok'
}

function dispatchTeamLabel(team: any) {
  const load = dispatchLoadItems.value.find((x: any) => Number(x.team_id) === Number(team.id))
  const suffix = load ? `｜派入后 ${dispatchPercent(dispatchProjectedPeak(load))}` : ''
  return `${team.name}（${team.member_count || 0}人）${suffix}`
}

function dispatchEstimate(row: any, workerCount: number) {
  const qty = Number(row?.plan_qty || 0)
  const cap = row?.per_worker_capacity ? Number(row.per_worker_capacity) : 0
  if (!qty || !cap || !workerCount) return null
  const needDays = Math.max(1, Math.ceil(qty / (cap * workerCount)))
  const planDays = scheduleWorkdays(row?.start_date, row?.end_date)
  return { needDays, planDays }
}

function scheduleWorkdays(start?: string, end?: string): number | null {
  if (!start || !end) return null
  const a = new Date(start)
  const b = new Date(end)
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return null
  return Math.max(1, Math.round((b.getTime() - a.getTime()) / 86400000) + 1)
}

async function saveDispatch() {
  const headerId = Number(detail.value?.id)
  const procId = Number(dispatchLine.value?.order_process_id)
  if (!headerId || !procId) return
  if (dispatchTargetType.value === 'team' && !dispatchTeamId.value) {
    ElMessage.warning('请选择班组')
    return
  }
  dispatchSaving.value = true
  try {
    await http.patch(`/executions/headers/${headerId}/processes/${procId}/assign`, {
      worker_ids: dispatchTargetType.value === 'worker' ? dispatchWorkerIds.value : [],
      team_id: dispatchTargetType.value === 'team' ? dispatchTeamId.value : null,
    })
    ElMessage.success('已保存派工')
    dispatchVisible.value = false
    await loadHeaderProcesses()
    // 派工与排产出入提醒
    const team = dispatchTeams.value.find((x: any) => Number(x.id) === Number(dispatchTeamId.value))
    const workerCount = dispatchTargetType.value === 'team'
      ? Number(team?.member_count || 0)
      : dispatchWorkerIds.value.length
    const est = dispatchEstimate(dispatchLine.value, workerCount)
    if (est && est.planDays && est.needDays > est.planDays) {
      ElMessage.warning(
        `派 ${workerCount} 人，按单人产能 ${dispatchLine.value?.per_worker_capacity} 双/人/天，` +
          `预计需 ${est.needDays} 天，比排产窗口（${est.planDays} 天）晚 ${est.needDays - est.planDays} 天，` +
          `可能影响后续工序和交期，建议加人或调整排期。`,
      )
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '派工失败')
  } finally {
    dispatchSaving.value = false
  }
}

async function clearDispatch() {
  const headerId = Number(detail.value?.id)
  const procId = Number(dispatchLine.value?.order_process_id)
  if (!headerId || !procId) return
  dispatchSaving.value = true
  try {
    await http.patch(`/executions/headers/${headerId}/processes/${procId}/assign`, {
      worker_ids: [],
      team_id: null,
    })
    ElMessage.success('已清空派工（不限报工）')
    dispatchVisible.value = false
    await loadHeaderProcesses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '清空失败')
  } finally {
    dispatchSaving.value = false
  }
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

async function openHeaderPacking() {
  packingForm.mode = 'assortment'
  packingForm.pairs_per_carton = 12
  packingPlan.value = null
  packingVisible.value = true
  await loadHeaderPackingPlans()
}

async function openRowCartonMarks(row: ExecutionRow) {
  try {
    const res: any = await http.get(`/executions/headers/${row.id}`)
    detail.value = res.data
    await openHeaderPacking()
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
    const items = res.data?.items || []
    packingPlan.value = items[0] || null
    if (packingPlan.value) {
      packingForm.mode = packingPlan.value.mode || 'assortment'
      packingForm.pairs_per_carton = Number(packingPlan.value.pairs_per_carton || 12)
    }
  } finally {
    packingLoading.value = false
  }
}

async function generateHeaderPacking() {
  const hid = Number(detail.value?.id)
  if (!hid) return
  packingSaving.value = true
  try {
    const res: any = await http.post(`/executions/headers/${hid}/packing-plans`, {
      mode: packingForm.mode,
      pairs_per_carton: packingForm.pairs_per_carton,
      replace_draft: true,
    })
    packingPlan.value = res.data
    ElMessage.success(`已生成 ${packingPlan.value?.carton_count || 0} 箱`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '生成装箱失败')
  } finally {
    packingSaving.value = false
  }
}

const packableWarehouseCartons = computed(() =>
  (packingPlan.value?.cartons || []).filter((c: any) => c?.id && !c.warehoused_at),
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

const packingSizeCols = computed(() => collectCartonSizes(packingPlan.value?.cartons || []))

function cartonSizeQty(row: any, sizeValue: string) {
  return (row?.lines || [])
    .filter((line: any) => String(line.size_value || '').trim() === sizeValue)
    .reduce((sum: number, line: any) => sum + Number(line.qty || 0), 0)
}

function printCarton(id: number) {
  window.open(`${window.location.origin}/admin/packing/print/${id}`, '_blank')
}

function printAllHeaderCartons() {
  const cartons = packingPlan.value?.cartons || []
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

function canHeaderAllocate(row: any) {
  return Number(row?.shortage_qty) > 0 && Number(row?.pool_qty) > 0 && !row?.is_customer_supplied
}

function canHeaderDeallocate(row: any) {
  const arrived = Number(row?.arrived_qty) || 0
  const issued = Number(row?.issued_qty) || 0
  return arrived - issued > 0 && !row?.is_customer_supplied
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

async function allocateHeaderMaterial(row: any) {
  const hid = Number(detail.value?.id)
  if (!hid) return
  const max = Math.min(Number(row.shortage_qty) || 0, Number(row.pool_qty) || 0)
  if (max <= 0) {
    ElMessage.warning('无可锁数量')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      `锁料到本生产单（最多 ${formatMatQty(max)}）`,
      '锁料',
      {
        inputValue: String(max),
        inputPattern: /^\d+(\.\d+)?$/,
        inputErrorMessage: '请输入数量',
      },
    )
    const qty = Number(value)
    if (!(qty > 0)) return
    await http.post(`/executions/headers/${hid}/materials/${row.id}/allocate`, { qty })
    ElMessage.success('已锁料')
    await loadHeaderMaterials()
  } catch (e: any) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) return
    ElMessage.error(e?.response?.data?.detail || e?.message || '锁料失败')
  }
}

async function deallocateHeaderMaterial(row: any) {
  const hid = Number(detail.value?.id)
  if (!hid) return
  const max = Math.max(0, (Number(row.arrived_qty) || 0) - (Number(row.issued_qty) || 0))
  if (max <= 0) {
    ElMessage.warning('无可回收占用')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      `回收到库存池（最多 ${formatMatQty(max)}）`,
      '回收',
      {
        inputValue: String(max),
        inputPattern: /^\d+(\.\d+)?$/,
        inputErrorMessage: '请输入数量',
      },
    )
    const qty = Number(value)
    if (!(qty > 0)) return
    await http.post(`/executions/headers/${hid}/materials/${row.id}/deallocate`, { qty })
    ElMessage.success('已回收')
    await loadHeaderMaterials()
  } catch (e: any) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) return
    ElMessage.error(e?.response?.data?.detail || e?.message || '回收失败')
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

function canHalt(row: ExecutionRow | null | undefined) {
  if (!row || row.status === 'cancelled') return false
  if (row.started === true) return true
  if (row.started === false) return false
  return row.status === 'cut' || row.status === 'in_progress' || Number(row.completed_qty || 0) > 0
}

function canReschedule(row: ExecutionRow | null | undefined) {
  if (!row || row.status === 'cancelled' || row.status === 'completed') return false
  if (canHalt(row)) return false
  return row.status === 'confirmed'
}

function canWithdraw(row: ExecutionRow | null | undefined) {
  return canReschedule(row)
}

function goReschedule(row: ExecutionRow) {
  detailVisible.value = false
  void router.push({ path: '/admin/schedule', query: { reschedule: String(row.id) } })
}

async function openChangeQty(row: ExecutionRow) {
  if (!canChangeQty(row)) {
    ElMessage.warning('已开工不可改量；请走停产/减产')
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
    ElMessage.warning('已开工不可改量；请走停产/减产')
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

async function openHalt(row: ExecutionRow) {
  if (!canHalt(row)) {
    ElMessage.warning('仅已开工生产单可停产回滚')
    return
  }
  haltTarget.value = row
  haltTargetQty.value = undefined
  haltVoidOpen.value = true
  haltNotes.value = ''
  haltSim.value = null
  haltVisible.value = true
  await simulateHalt()
}

async function simulateHalt() {
  if (!haltTarget.value?.id) return
  haltSimulating.value = true
  try {
    const res: any = await http.post(`/executions/${haltTarget.value.id}/halt/simulate`, {
      target_total_qty: haltTargetQty.value === undefined || haltTargetQty.value === null
        ? null
        : haltTargetQty.value,
      void_open_units: haltVoidOpen.value,
      notes: haltNotes.value || undefined,
    })
    haltSim.value = res.data
  } catch (e: any) {
    haltSim.value = null
    ElMessage.error(e?.response?.data?.detail || e?.message || '仿真失败')
  } finally {
    haltSimulating.value = false
  }
}

async function confirmHalt() {
  if (!haltTarget.value?.id || !haltSim.value) return
  try {
    await ElMessageBox.confirm(
      haltSim.value.warning || '确认停产/减产？',
      '确认停产',
      { type: 'warning', confirmButtonText: '确认回滚' },
    )
  } catch {
    return
  }
  haltConfirming.value = true
  try {
    const res: any = await http.post(`/executions/${haltTarget.value.id}/halt/confirm`, {
      target_total_qty: haltTargetQty.value === undefined || haltTargetQty.value === null
        ? null
        : haltTargetQty.value,
      void_open_units: haltVoidOpen.value,
      notes: haltNotes.value || undefined,
    })
    ElMessage.success(
      res.data?.will_cancel_execution
        ? '已停产并取消生产单'
        : `已减产至 ${res.data?.new_total_qty}`,
    )
    haltVisible.value = false
    detailVisible.value = false
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认失败')
  } finally {
    haltConfirming.value = false
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
    ElMessage.success(`已开裁，生成 ${res.data?.to_create || 0} 个框码；已打开框码标签，请另用「打印流转卡」打 A4`)
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
  void loadExecutions()
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
    if (row) void openDetail(row)
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
  align-items: flex-start;
  gap: 2px;
  min-width: 72px;
  flex: 0 0 auto;
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
.reorder-confirm-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0 0 10px;
  padding: 10px 14px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}
.reorder-dialog-summary {
  margin: 0 0 12px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
.staffing-summary {
  margin: 0 0 12px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
.reorder-dialog-summary strong {
  font-weight: 600;
}
.risk-text {
  color: var(--el-color-danger);
  font-weight: 600;
}
.success-text {
  color: var(--el-color-success);
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
.date-changed {
  color: var(--el-color-warning-dark-2);
  font-weight: 600;
}
.must-material-date {
  color: var(--el-color-danger);
  font-weight: 600;
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
.execution-detail-tabs {
  margin-bottom: 4px;
}
.execution-detail-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}
.execution-detail-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: #dfe5e7;
}
.execution-detail-tabs :deep(.el-tabs__item) {
  height: 42px;
  color: #657176;
  font-weight: 600;
}
.execution-detail-tabs :deep(.el-tabs__item.is-active) {
  color: #183b45;
}
.execution-detail-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px;
  background: #e36f32;
}
.execution-detail-tabs :deep(.el-tabs__content),
.execution-detail-tabs :deep(.el-tab-pane) {
  width: 100%;
  min-width: 0;
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
.production-dossier {
  position: relative;
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr) 150px;
  gap: 20px;
  align-items: center;
  overflow: hidden;
  padding: 20px;
  border: 1px solid #dce4e6;
  border-radius: 14px;
  background: linear-gradient(118deg, #f7faf9 0%, #fff 62%);
  box-shadow: 0 12px 28px rgb(28 52 59 / 7%);
}
.production-dossier::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 5px;
  background: #e36f32;
  content: '';
}
.dossier-main { min-width: 0; }
.dossier-eyebrow {
  margin-bottom: 6px;
  color: #6a7b80;
  font: 700 11px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .11em;
}
.dossier-title-row { display: flex; align-items: center; gap: 12px; }
.dossier-title-row h2 { margin: 0; color: #173b45; font-size: 26px; line-height: 1.15; letter-spacing: -.02em; }
.dossier-status { padding: 4px 9px; border-radius: 999px; background: #e8f1f0; color: #35615f; font-size: 12px; font-weight: 700; }
.dossier-status[data-status='cut'] { background: #fff0e7; color: #b65320; }
.dossier-status[data-status='in_progress'] { background: #e7f0fb; color: #315f91; }
.dossier-status[data-status='completed'] { background: #e6f4ec; color: #2e7550; }
.dossier-spec { display: flex; flex-wrap: wrap; gap: 0; margin-top: 12px; color: #334c53; font-size: 13px; }
.dossier-spec span + span::before { margin: 0 10px; color: #b6c0c3; content: '·'; }
.dossier-source { overflow: hidden; margin: 9px 0 0; color: #7a898d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.dossier-kit { align-self: stretch; display: flex; flex-direction: column; justify-content: center; padding-left: 20px; border-left: 1px solid #e1e7e8; }
.dossier-kit span, .dossier-kit small { color: #829095; font-size: 11px; }
.dossier-kit strong { margin: 5px 0 3px; color: #27694b; font-size: 19px; }
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
.detail-overview-head {
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.detail-product-thumb {
  width: 96px;
  flex: 0 0 96px;
  aspect-ratio: 1 / 1;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  background: #fff;
}
.detail-product-thumb :deep(.el-image__inner) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.detail-product-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  color: #9aa7aa;
  background: #f5f7f7;
}
.detail-product-placeholder .el-icon { font-size: 28px; }
.detail-product-placeholder span { font-size: 11px; }
.detail-overview-kv {
  flex: 1;
  min-width: 0;
}
.exe-four-track {
  display: grid;
  grid-template-columns: repeat(4, minmax(80px, 1fr));
  border-bottom: 1px solid #e3e8e9;
}
.exe-four-track > div {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 5px;
  padding: 8px 10px;
}
.exe-four-track > div + div {
  border-left: 1px solid #e7ebec;
}
.exe-four-track span {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.exe-four-track b {
  color: #25464f;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}
.exe-four-track small { color: #8b989c; font-size: 10px; }
.production-pulse { margin-top: 10px; border: 1px solid #dfe6e7; border-radius: 9px; overflow: hidden; background: #fff; }
.process-rail-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px 4px; }
.process-rail-head > span { color: #294850; font-size: 12px; font-weight: 650; }
.process-rail-head small { color: #7d8c90; font-size: 10px; }
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
.dispatch-process-list {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.dispatch-process-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
}
.dispatch-process-row + .dispatch-process-row {
  border-top: 1px solid var(--el-border-color-lighter);
}
.dispatch-load {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  font-size: 12px;
}
.dispatch-load__title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  font-weight: 600;
}
.dispatch-load__summary { margin-bottom: 8px; }
.dispatch-load__days {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
}
.dispatch-load--ok { color: var(--el-color-success); }
.dispatch-load--warn { color: var(--el-color-warning); }
.dispatch-load--danger { color: var(--el-color-danger); font-weight: 600; }
.exe-proc-track {
  display: flex;
  flex-wrap: nowrap;
  gap: 0;
  overflow-x: auto;
  margin: 0;
  padding: 0 6px 7px;
  scrollbar-width: thin;
}
.exe-proc-step {
  flex: 1 0 145px;
  min-width: 145px;
  padding: 5px 8px 3px;
  border-left: 2px solid #d8dfe1;
}
.exe-proc-step.is-current {
  border-left-color: #e36f32;
  background: #fff8f3;
}
.exe-proc-step.is-done {
  border-left-color: var(--el-color-success-light-3);
}
.exe-proc-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  color: #334f57;
  font-size: 11px;
  font-weight: 600;
}
.exe-proc-name b { color: #66777c; font-size: 10px; font-weight: 500; font-variant-numeric: tabular-nums; }
.exe-proc-foot { display: flex; align-items: center; justify-content: space-between; min-height: 22px; margin-top: 1px; }
.exe-proc-foot > span { overflow: hidden; color: #8a979b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.exe-proc-foot :deep(.el-button) { height: 20px; padding: 0; font-size: 10px; }
@media (max-width: 640px) {
  .production-dossier { grid-template-columns: 76px 1fr; padding: 14px; gap: 12px; }
  .production-dossier .detail-product-thumb { width: 76px; flex-basis: 76px; }
  .dossier-kit { grid-column: 1 / -1; padding: 10px 0 0; border-top: 1px solid #e1e7e8; border-left: 0; }
  .dossier-title-row h2 { font-size: 21px; }
  .consumption-summary { grid-template-columns: 1fr; }
  .batch-ledger-row { grid-template-columns: 64px minmax(90px, 1fr) 44px auto; gap: 8px; }
  .batch-ledger-detail { padding-left: 12px; }
}
.exe-warehouse-tag {
  cursor: default;
}
.execution-risk-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 10px;
}
.execution-risk-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  min-height: 28px;
  padding: 3px 8px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-regular);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.execution-risk-chip.static {
  cursor: default;
}
.execution-risk-chip strong {
  font-size: 14px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.execution-risk-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.execution-risk-chip.late strong { color: var(--el-color-danger); }
.execution-risk-chip.high strong { color: var(--el-color-warning-dark-2); }
.execution-risk-chip.attention strong { color: var(--el-color-primary); }
.execution-risk-clear {
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  font-size: 12px;
  cursor: pointer;
}
.staffing-advice-slot {
  margin-left: auto;
}
@media (max-width: 800px) {
  .staffing-advice-slot {
    flex-basis: 100%;
    margin-left: 0;
  }
}
</style>

<style>
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
  max-width: min(92vw, 600px);
  padding: 10px 12px;
}
.exe-wh-kit-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}
.exe-wh-kit-body {
  max-height: min(60vh, 420px);
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}
.exe-wh-kit-empty {
  padding: 12px 0;
  text-align: center;
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
.exe-warehouse-kit-popper .muted {
  color: var(--el-text-color-placeholder);
}
.exe-risk-popper.el-popover {
  padding: 12px 14px;
}
.exe-risk-tag {
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
.exe-risk-meta,
.exe-risk-preview-note {
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
