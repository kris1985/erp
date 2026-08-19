<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">生产单</h1>
        <p class="page-desc">排产确认下发后在此开裁、报工、入库。</p>
      </div>
    </header>

    <div class="admin-card">
    <div class="admin-toolbar">
      <el-input
        v-model="filters.q"
        clearable
        placeholder="生产单号/工厂型号/销售单/客户"
        style="width: 240px"
        @clear="loadExecutions"
        @keyup.enter="loadExecutions"
      />
      <el-select v-model="filters.status" clearable placeholder="状态" style="width: 120px" @change="loadExecutions">
        <el-option label="已排产" value="confirmed" />
        <el-option label="已开裁" value="cut" />
        <el-option label="生产中" value="in_progress" />
        <el-option label="已完成" value="completed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-select v-model="filters.kit_ok" clearable placeholder="齐套" style="width: 110px" @change="loadExecutions">
        <el-option label="齐套" :value="true" />
        <el-option label="缺料" :value="false" />
      </el-select>
      <el-select v-model="filters.first_kit_ok" clearable placeholder="开裁齐套" style="width: 120px" @change="loadExecutions">
        <el-option label="齐套" :value="true" />
        <el-option label="未齐" :value="false" />
      </el-select>
      <el-select v-model="filters.is_rush" clearable placeholder="急单" style="width: 100px" @change="loadExecutions">
        <el-option label="急单" :value="true" />
        <el-option label="普通" :value="false" />
      </el-select>
      <el-date-picker
        v-model="filters.deliveryRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="交货日期起"
        end-placeholder="交货日期止"
        style="width: 240px"
        @change="loadExecutions"
      />
      <el-button type="primary" :loading="listLoading" @click="loadExecutions">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button :loading="listLoading" @click="loadExecutions">刷新</el-button>
    </div>
    <div ref="tableHostRef">
    <el-table
      ref="listTableRef"
      v-loading="listLoading"
      :data="executions"
      stripe
      border
      :max-height="tableMaxHeight"
      empty-text="暂无生产单。请先在订单确认接单，再到「排产」出方案并确认。"
      @header-dragend="onListHeaderDragend"
      @sort-change="onSortChange"
    >
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
        <template #default="{ row }">{{ projectedFinish(row) }}</template>
      </el-table-column>
      <el-table-column
        column-key="material_status"
        label="采购"
        :width="listColWidth('material_status', 90)"
        align="center"
        resizable
      >
        <template #default="{ row }">
          <el-tag
            v-if="materialStatus(row)"
            size="small"
            :type="materialStatusTag(row)"
            effect="plain"
          >
            {{ materialStatus(row) }}
          </el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column
        v-for="process in listProcessColumns"
        :key="`proc-${process.key}`"
        :column-key="`proc-${process.key}`"
        :label="process.label"
        :width="listColWidth(`proc-${process.key}`, 80)"
        align="center"
        resizable
      >
        <template #default="{ row }">
          <span>{{ listProcessText(row, process.key) }}</span>
        </template>
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
            <el-button
              v-if="canCut(row)"
              type="primary"
              size="small"
              @click="openCutCards(row)"
            >
              开裁
            </el-button>
            <el-button
              v-else-if="printPrimary(row)"
              type="primary"
              size="small"
              plain
              @click="printFlowCard(row)"
            >
              打印
            </el-button>
            <el-button
              v-if="printSecondary(row)"
              link
              @click="printFlowCard(row)"
            >
              打印
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
    </div>
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="`生产单 · ${detail?.header_no || detail?.execution_no || ''}`"
      width="860px"
      class="execution-detail-dialog"
    >
      <template v-if="detail">
        <el-tabs v-model="detailTab" class="execution-detail-tabs">
          <el-tab-pane label="概览" name="overview">
            <div class="detail-overview-head">
              <el-image
                v-if="detail.product_image_url"
                :src="detail.product_image_url"
                :preview-src-list="[detail.product_image_url]"
                fit="contain"
                class="detail-product-thumb"
                preview-teleported
              />
              <el-descriptions :column="2" border size="small" class="detail-overview-kv">
                <el-descriptions-item label="工厂型号">{{ detail.product_code }}</el-descriptions-item>
                <el-descriptions-item label="颜色">{{ detail.color_name || '—' }}</el-descriptions-item>
                <el-descriptions-item label="尺码">{{ detail.size_summary || detail.size_value || '—' }}</el-descriptions-item>
                <el-descriptions-item label="数量">
                  {{ detail.completed_qty || 0 }} / {{ detail.total_qty }}
                  <span class="muted">（在制预估）</span>
                </el-descriptions-item>
                <el-descriptions-item label="状态">{{ statusLabel(detail.status) }}</el-descriptions-item>
                <el-descriptions-item label="交货日期">{{ detail.delivery_date || '—' }}</el-descriptions-item>
                <el-descriptions-item label="齐套">
                  <template v-if="detail.kit">
                    <el-tag :type="kitFullTag(detail.kit)" size="small">{{ kitFullLabel(detail.kit) }}</el-tag>
                  </template>
                  <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item label="开裁齐套">
                  <template v-if="detail.kit && !detail.kit.empty_bom">
                    <el-tag :type="detail.kit.first_kit_ok ? 'success' : 'danger'" size="small">
                      {{ detail.kit.first_kit_ok ? '齐套' : '未齐' }}
                    </el-tag>
                  </template>
                  <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item label="来源" :span="2">{{ sourceSummary(detail) }}</el-descriptions-item>
                <el-descriptions-item label="备注" :span="2">{{ detail.notes || '—' }}</el-descriptions-item>
              </el-descriptions>
            </div>
            <div class="exe-four-track" aria-label="生产单四轨进度">
              <div><span>已排产</span><b>{{ detail.scheduled_qty ?? detail.total_qty ?? 0 }}</b></div>
              <div><span>在制（约）</span><b>{{ detail.wip_qty ?? 0 }}</b></div>
              <div><span>已产</span><b>{{ detail.produced_qty ?? 0 }}</b></div>
              <div><span>已出</span><b>{{ detail.shipped_qty ?? 0 }}</b></div>
            </div>
            <div class="section-label">
              工序进度
              <span v-if="processProgress.all_done" class="muted"> · 已完成</span>
              <span v-else-if="processProgress.current_process_name" class="muted">
                · 当前 {{ processProgress.current_process_name }}
              </span>
            </div>
            <p v-if="!headerProcesses.length" class="muted kit-hint">暂无工序。排产确认下发后写入。</p>
            <div v-else class="exe-proc-track">
              <div
                v-for="p in headerProcesses"
                :key="p.id"
                class="exe-proc-step"
                :class="{ 'is-current': p.is_current, 'is-done': p.is_done && !p.is_current }"
              >
                <div class="exe-proc-name">
                  {{ p.label || p.process_name }}
                  <el-tag v-if="p.is_current" size="small" type="primary" class="exe-proc-tag">当前</el-tag>
                </div>
                <div class="exe-proc-qty">{{ p.completed_qty || 0 }}/{{ p.plan_qty || 0 }}</div>
              </div>
            </div>
            <el-table
              v-if="headerProcesses.length"
              :data="headerProcesses"
              size="small"
              border
              class="exe-proc-table"
              @header-dragend="onProcDragend"
            >
              <el-table-column
                prop="label"
                label="工序"
                :min-width="flexProc('label', 120)"
                show-overflow-tooltip
                resizable
              >
                <template #default="{ row }">{{ row.label || row.process_name }}</template>
              </el-table-column>
              <el-table-column
                column-key="progress"
                label="进度"
                :width="procColWidth('progress', 180)"
                resizable
              >
                <template #default="{ row }">
                  <el-progress
                    :percentage="processPercent(row)"
                    :stroke-width="8"
                    :status="processPercent(row) >= 100 ? 'success' : undefined"
                  >
                    <span>{{ row.completed_qty || 0 }}/{{ row.plan_qty || 0 }}</span>
                  </el-progress>
                </template>
              </el-table-column>
              <el-table-column
                column-key="window"
                label="计划窗"
                :width="procColWidth('window', 130)"
                resizable
              >
                <template #default="{ row }">{{ planWindow(row) }}</template>
              </el-table-column>
              <el-table-column
                prop="rework_qty"
                label="返修"
                :width="procColWidth('rework_qty', 64)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ row.rework_qty || 0 }}</template>
              </el-table-column>
              <el-table-column
                column-key="dispatch"
                label="派工"
                :width="procColWidth('dispatch', 160)"
                resizable
              >
                <template #default="{ row }">
                  <span v-if="row.assignee_names?.length" class="muted" style="font-size: 12px">
                    {{ row.assignee_names.join('、') }}
                  </span>
                  <span v-else class="muted" style="font-size: 12px">未派</span>
                  <el-button
                    v-if="detail?.shop_order_id"
                    link
                    type="primary"
                    size="small"
                    style="margin-left: 6px"
                    @click="openDispatchProc(row)"
                  >
                    派工
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <!-- 工序派工弹窗 -->
            <el-dialog
              v-model="dispatchVisible"
              :title="dispatchLine ? `派工 · ${dispatchLine.label || dispatchLine.process_name}` : '派工'"
              width="520px"
              append-to-body
            >
              <template v-if="dispatchLine">
                <p class="muted" style="margin: 0 0 12px">
                  计划 {{ dispatchLine.plan_qty || 0 }} 双 · 勾选工人即派工（不限配额）；如需配额/色码/捆请到排产草稿或生产单调整。
                </p>
                <div v-if="dispatchCurrent?.length" style="margin-bottom: 10px">
                  <span class="muted" style="font-size: 12px">当前派工：</span>
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
                <el-select
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

            <div class="section-label">码明细</div>
            <el-table
              :data="detail.size_lines || []"
              size="small"
              border
              width="100%"
              empty-text="无码明细"
              @header-dragend="onSizeLinesDragend"
            >
              <el-table-column
                column-key="qty"
                label="数量"
                :width="sizeLinesWidth('qty', 100)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ row.completed_qty || 0 }}/{{ row.total_qty }}</template>
              </el-table-column>
              <el-table-column
                column-key="status"
                label="状态"
                :width="sizeLinesWidth('status', 90)"
                resizable
              >
                <template #default="{ row }">{{ statusLabel(row.status) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane name="materials">
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
            <div class="section-label" style="margin-top: 0">
              齐套
              <el-button link type="primary" style="margin-left: 8px" :loading="materialsLoading" @click="loadHeaderMaterials">
                刷新
              </el-button>
              <el-button link type="primary" @click="openIssueDialog('issue')">申请领料</el-button>
              <el-button link @click="openIssueDialog('return_mat')">申请退料</el-button>
              <el-button link @click="goPurchaseOrders">看采购单</el-button>
            </div>
            <p class="muted kit-hint">齐套才能开裁。已买的去催；排产前没买的可在本表补差（先核对采购单，避免买两次）。</p>
            <el-table
              v-loading="materialsLoading"
              :data="headerMaterials"
              size="small"
              border
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

          <el-tab-pane name="baskets">
            <template #label>
              <span>筐卡</span>
              <el-tag v-if="detailBaskets.length" size="small" type="info" style="margin-left: 6px">
                {{ detailBaskets.length }}
              </el-tag>
            </template>
            <div class="section-label" style="margin-top: 0">流转卡（筐）成品处理</div>
            <el-table
              v-loading="basketsLoading"
              :data="detailBaskets"
              size="small"
              border
              empty-text="暂无筐卡（请先开裁）"
              @header-dragend="onBasketDragend"
            >
              <el-table-column
                prop="code"
                label="筐码"
                :min-width="flexBasket('code', 130)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                column-key="qty"
                label="数量"
                :width="basketWidth('qty', 70)"
                align="right"
                resizable
              >
                <template #default="{ row }">{{ row.qty }}</template>
              </el-table-column>
              <el-table-column
                column-key="status"
                label="状态"
                :width="basketWidth('status', 90)"
                resizable
              >
                <template #default="{ row }">{{ basketStatusLabel(row.status) }}</template>
              </el-table-column>
              <el-table-column column-key="actions" label="操作" width="260" :resizable="false">
                <template #default="{ row }">
                  <el-button
                    v-if="canWarehouse(row)"
                    link
                    type="warning"
                    :loading="prepackingId === row.id"
                    @click="prepackBasket(row)"
                  >
                    预装
                  </el-button>
                  <el-button
                    v-if="canWarehouse(row) || row.status === 'warehoused'"
                    link
                    @click="printBasketMarks(row)"
                  >
                    箱唛
                  </el-button>
                  <el-button
                    v-if="canWarehouse(row)"
                    link
                    type="primary"
                    :loading="warehousingId === row.id"
                    @click="warehouseBasket(row)"
                  >
                    入库
                  </el-button>
                  <el-button
                    v-if="allowDirectShip && canWarehouse(row)"
                    link
                    type="danger"
                    :loading="directShippingId === row.id"
                    @click="directShipBasket(row)"
                  >
                    直发
                  </el-button>
                  <el-button
                    v-if="row.status === 'warehoused'"
                    link
                    type="danger"
                    :loading="fgShippingId === row.id"
                    @click="shipFromFg(row)"
                  >
                    出货
                  </el-button>
                  <span v-else-if="!canWarehouse(row) && row.status !== 'warehoused'" class="muted">—</span>
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
          开裁打主码
        </el-button>
        <el-button v-if="detail && detail.status !== 'cancelled'" plain @click="openHeaderPacking">
          整单装箱
        </el-button>
        <el-button v-if="detail?.id || detail?.shop_order_id" plain @click="printFlowCard(detail)">打印主码</el-button>
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

    <el-dialog v-model="issueDialogVisible" :title="issueDialogTitle" width="720px" destroy-on-close>
      <p class="muted dlg-hint">
        <template v-if="issueDialogType === 'issue'">
          提交后待仓管在出入库单确认过账。可多次申请。
        </template>
        <template v-else>提交退料申请，仓管确认后把已发退回库存池。</template>
      </p>
      <div style="margin-bottom: 10px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
        <el-tag v-if="issueDialogType === 'issue' && issueMeta?.issue_kind_next" type="info" effect="plain">
          本次：{{ issueMeta.issue_kind_next }}
        </el-tag>
        <el-button size="small" @click="fillIssueMax">
          {{ issueDialogType === 'issue' ? '按库存填满' : '填满可退' }}
        </el-button>
      </div>
      <el-table v-loading="issueDialogLoading" :data="issueCandidates" border size="small" max-height="360">
        <el-table-column prop="supplier_product_code" label="物料" min-width="100" />
        <el-table-column prop="supplier_product_name" label="名称" min-width="120" />
        <el-table-column label="可发/可退" width="100" align="right">
          <template #default="{ row }">
            {{ formatMatQty(issueDialogType === 'issue' ? row.max_issue_qty : row.returnable_qty) }}
          </template>
        </el-table-column>
        <el-table-column label="本次" width="140">
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
      :title="`整单装箱 · ${detail?.header_no || detail?.execution_no || ''}`"
      width="720px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="每箱双数">
          <el-input-number v-model="packingForm.pairs_per_carton" :min="1" :max="999" />
        </el-form-item>
        <el-form-item label="规则">
          <el-radio-group v-model="packingForm.mode">
            <el-radio value="single_size">单码</el-radio>
            <el-radio value="mixed">混码</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div style="margin-bottom: 10px">
        <el-button type="primary" :loading="packingSaving" @click="generateHeaderPacking">生成装箱</el-button>
        <el-button :loading="packingLoading" @click="loadHeaderPackingPlans">刷新</el-button>
      </div>
      <div v-if="packingPlan" class="muted" style="margin-bottom: 8px">
        {{ packingPlan.mode === 'mixed' ? '混码' : '单码' }} · 每箱
        {{ packingPlan.pairs_per_carton }} · 共 {{ packingPlan.carton_count }} 箱 /
        {{ packingPlan.total_qty }} 双
      </div>
      <el-table :data="packingPlan?.cartons || []" size="small" border empty-text="尚未生成装箱计划">
        <el-table-column prop="code" label="箱码" min-width="160" />
        <el-table-column prop="total_qty" label="双数" width="80" align="right" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="printCarton(row.id)">打印</el-button>
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
      :title="`开裁打主码 · ${cutTarget?.execution_no || ''}`"
      width="640px"
    >
      <p class="muted dlg-hint">
        开裁只出流转卡（筐）：一色码行按筐量拆成若干筐，每筐只属于一个品牌。
      </p>
      <el-form label-width="88px" size="small">
        <el-form-item label="拆筐量">
          <el-input-number v-model="cutBundleSize" :min="1" :step="10" controls-position="right" />
          <span class="muted" style="margin-left: 8px">
            每筐 {{ cutBundleSize || defaultCutBundleSize }} 双，超出自动另起一筐
          </span>
        </el-form-item>
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
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import MaterialCoverCell from '@/components/MaterialCoverCell.vue'

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

const listProcessColumns = computed(() => {
  const columns = new Map<string, { key: string; label: string }>()
  for (const row of executions.value) {
    for (const p of row.process_progress || []) {
      const key = String(p.process_id || p.process_name || '')
      if (key && !columns.has(key)) {
        columns.set(key, { key, label: p.label || p.process_name || '工序' })
      }
    }
  }
  return [...columns.values()]
})

function listProcessText(row: ExecutionRow, processKey: string) {
  const matched = (row.process_progress || []).filter(
    (p: any) => String(p.process_id || p.process_name || '') === processKey,
  )
  if (!matched.length) return '—'
  return `${matched.reduce((sum: number, p: any) => sum + Number(p.completed_qty || 0), 0)}`
}
const filters = reactive({
  q: '',
  status: undefined as string | undefined,
  kit_ok: undefined as boolean | undefined,
  first_kit_ok: undefined as boolean | undefined,
  is_rush: undefined as boolean | undefined,
  deliveryRange: null as [string, string] | null,
})
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
const { colWidth: basketWidth, flexColMinWidth: flexBasket, onHeaderDragend: onBasketDragend } =
  useTableColWidths('executions-detail-baskets')
const { colWidth: procColWidth, flexColMinWidth: flexProc, onHeaderDragend: onProcDragend } =
  useTableColWidths('executions-detail-processes')
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
const buyingGapId = ref<number | null>(null)
const issueDialogVisible = ref(false)
const issueDialogType = ref<'issue' | 'return_mat'>('issue')
const issueDialogLoading = ref(false)
const issuePosting = ref(false)
const issueCandidates = ref<any[]>([])
const issueMeta = ref<any>(null)
const issueQtyDraft = ref<Record<number, string>>({})
const packingVisible = ref(false)
const packingLoading = ref(false)
const packingSaving = ref(false)
const packingPlan = ref<any | null>(null)
const packingForm = reactive({ mode: 'single_size', pairs_per_carton: 12 })
const warehousingId = ref<number | null>(null)
const directShippingId = ref<number | null>(null)
const fgShippingId = ref<number | null>(null)
const prepackingId = ref<number | null>(null)
const allowDirectShip = ref(false)
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
    confirmed: '已排产',
    cut: '已开裁',
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

function printPrimary(row: ExecutionRow) {
  return (row.status === 'cut' || row.status === 'in_progress') && Boolean(row.id || row.shop_order_id)
}

function printSecondary(row: ExecutionRow) {
  if (!(row.id || row.shop_order_id)) return false
  return row.status === 'confirmed' || row.status === 'completed'
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

function processPercent(row: { completed_qty?: number; plan_qty?: number }) {
  const plan = Number(row.plan_qty || 0)
  if (!plan) return 0
  return Math.min(100, Math.round((Number(row.completed_qty || 0) / plan) * 100))
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
  void loadExecutions()
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
        is_rush: filters.is_rush ?? undefined,
        delivery_from: filters.deliveryRange?.[0] || undefined,
        delivery_to: filters.deliveryRange?.[1] || undefined,
        sort_by: serverSortBy.value || undefined,
        sort_order: serverSortBy.value ? serverSortOrder.value : undefined,
        limit: 100,
      },
    })
    executions.value = res.data?.items || []
    // 数据加载后动态工序列才出现，需重新等比缩放列宽铺满容器，避免横向滚动条
    relayoutListTable()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载生产单失败')
  } finally {
    listLoading.value = false
  }
}

function resetFilters() {
  filters.q = ''
  filters.status = undefined
  filters.kit_ok = undefined
  filters.first_kit_ok = undefined
  filters.is_rush = undefined
  filters.deliveryRange = null
  serverSortBy.value = ''
  serverSortOrder.value = 'desc'
  listTableRef.value?.clearSort?.()
  void loadExecutions()
}

async function openDetail(row: ExecutionRow) {
  try {
    const [res, settings]: any[] = await Promise.all([
      http.get(`/executions/headers/${row.id}`),
      http.get('/shop-floor-settings'),
    ])
    detail.value = res.data
    allowDirectShip.value = Boolean(settings.data?.allow_direct_ship)
    detailTab.value = 'overview'
    detailVisible.value = true
    await Promise.all([loadDetailBaskets(), loadHeaderMaterials(), loadHeaderProcesses()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载详情失败')
  }
}

async function directShipBasket(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认将筐 ${row.code}（${row.qty} 双）直接发货？须已预装且箱合计=筐数量；系统会生成虚拟入/出库流水，并按销售来源拆分出货与应收。`,
      '筐完工直发',
      { type: 'warning', confirmButtonText: '确认直发' },
    )
  } catch {
    return
  }
  directShippingId.value = row.id
  try {
    const res: any = await http.post(`/trace-units/${row.id}/direct-ship`)
    const shipments = (res.data?.shipments || [])
      .map((x: any) => `${x.sales_order_no} ${x.total_qty}`)
      .join(' / ')
    ElMessage.success(shipments ? `已直发：${shipments}` : '已直发')
    if (detail.value?.id) {
      const d: any = await http.get(`/executions/headers/${detail.value.id}`)
      detail.value = d.data
    }
    await Promise.all([loadDetailBaskets(), loadHeaderProcesses()])
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '直发失败')
  } finally {
    directShippingId.value = null
  }
}

async function prepackBasket(row: any) {
  let pairs = 12
  try {
    const { value } = await ElMessageBox.prompt(
      `为筐 ${row.code}（${row.qty} 双）生成预装箱。请输入每箱双数：`,
      '按筐预装',
      {
        inputValue: '12',
        inputPattern: /^[1-9]\d*$/,
        inputErrorMessage: '请输入正整数',
        confirmButtonText: '生成预装',
      },
    )
    pairs = Number(value)
  } catch {
    return
  }
  prepackingId.value = row.id
  try {
    const res: any = await http.post(`/trace-units/${row.id}/prepack-plans`, {
      mode: 'single_size',
      pairs_per_carton: pairs,
      replace_draft: true,
    })
    const count = res.data?.carton_count || 0
    ElMessage.success(`已预装 ${count} 箱 · 合计 ${res.data?.total_qty || 0} 双`)
    const firstId = res.data?.cartons?.[0]?.id
    if (firstId) {
      try {
        await ElMessageBox.confirm('是否打开第一箱箱唛打印？', '草稿箱唛', {
          confirmButtonText: '打印',
          cancelButtonText: '稍后',
          type: 'info',
        })
        window.open(`${window.location.origin}/admin/packing/print/${firstId}`, '_blank')
      } catch {
        /* skip */
      }
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '预装失败')
  } finally {
    prepackingId.value = null
  }
}

async function printBasketMarks(row: any) {
  try {
    const res: any = await http.get(`/trace-units/${row.id}/prepack-plans`)
    const plan = (res.data?.items || [])[0]
    const cartons = plan?.cartons || []
    if (!cartons.length) {
      ElMessage.warning('该筐尚无预装箱，请先预装')
      return
    }
    // 逐箱打开打印页（批量入口：同预装计划下全部箱）
    for (const c of cartons.slice(0, 8)) {
      window.open(`${window.location.origin}/admin/packing/print/${c.id}`, '_blank')
    }
    if (cartons.length > 8) {
      ElMessage.info(`已打开前 8 箱，共 ${cartons.length} 箱可在预装计划中补打`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载箱唛失败')
  }
}

async function shipFromFg(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认将已入库筐 ${row.code}（${row.qty} 双）从成品仓出货？须已预装；将扣 FG、按销售来源拆出货并落成箱唛。`,
      '成品仓出货',
      { type: 'warning', confirmButtonText: '确认出货' },
    )
  } catch {
    return
  }
  fgShippingId.value = row.id
  try {
    const res: any = await http.post(`/trace-units/${row.id}/ship-from-fg`)
    const shipments = (res.data?.shipments || [])
      .map((x: any) => `${x.sales_order_no} ${x.total_qty}`)
      .join(' / ')
    ElMessage.success(shipments ? `已出货：${shipments}` : '已出货')
    const cartonId = res.data?.prepack?.cartons?.[0]?.id
    if (cartonId) {
      try {
        await ElMessageBox.confirm('预装已落成，是否打印第一箱正式箱唛？', '箱唛', {
          confirmButtonText: '打印',
          cancelButtonText: '稍后',
        })
        window.open(`${window.location.origin}/admin/packing/print/${cartonId}`, '_blank')
      } catch {
        /* skip */
      }
    }
    if (detail.value?.id) {
      const d: any = await http.get(`/executions/headers/${detail.value.id}`)
      detail.value = d.data
    }
    await Promise.all([loadDetailBaskets(), loadHeaderProcesses()])
    await loadExecutions()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '出货失败')
  } finally {
    fgShippingId.value = null
  }
}

// ── 工序派工 ──
const dispatchVisible = ref(false)
const dispatchLine = ref<any>(null)
const dispatchWorkerIds = ref<number[]>([])
const dispatchCurrent = ref<any[]>([])
const dispatchWorkers = ref<any[]>([])
const dispatchSaving = ref(false)

async function ensureDispatchWorkers() {
  if (dispatchWorkers.value.length) return
  try {
    const res: any = await http.get('/workers', { params: { is_active: true, page_size: 500 } })
    dispatchWorkers.value = res.data?.items || []
  } catch {
    dispatchWorkers.value = []
  }
}

async function openDispatchProc(row: any) {
  const orderId = Number(detail.value?.shop_order_id)
  if (!orderId) {
    ElMessage.warning('执行单未关联生产单，无法派工')
    return
  }
  dispatchLine.value = row
  dispatchWorkerIds.value = []
  dispatchCurrent.value = []
  await ensureDispatchWorkers()
  try {
    const res: any = await http.get(`/orders/${orderId}`)
    const order = res.data || {}
    const proc = (order.processes || []).find((p: any) => Number(p.id) === Number(row.order_process_id))
    dispatchCurrent.value = (proc?.assignments || []).map((a: any) => ({
      worker_id: a.worker_id,
      worker_name: a.worker_name || a.worker_id,
      quota_qty: a.quota_qty,
    }))
    dispatchWorkerIds.value = dispatchCurrent.value.map((a: any) => a.worker_id)
  } catch {
    dispatchCurrent.value = []
  }
  dispatchVisible.value = true
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
  const orderId = Number(detail.value?.shop_order_id)
  const procId = Number(dispatchLine.value?.order_process_id)
  if (!orderId || !procId) return
  dispatchSaving.value = true
  try {
    await http.patch(`/orders/${orderId}/processes/${procId}`, {
      worker_ids: dispatchWorkerIds.value,
    })
    ElMessage.success('已保存派工')
    dispatchVisible.value = false
    await loadHeaderProcesses()
    // 派工与排产出入提醒
    const est = dispatchEstimate(dispatchLine.value, dispatchWorkerIds.value.length)
    if (est && est.planDays && est.needDays > est.planDays) {
      ElMessage.warning(
        `派 ${dispatchWorkerIds.value.length} 人，按单人产能 ${dispatchLine.value?.per_worker_capacity} 双/人/天，` +
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
  const orderId = Number(detail.value?.shop_order_id)
  const procId = Number(dispatchLine.value?.order_process_id)
  if (!orderId || !procId) return
  dispatchSaving.value = true
  try {
    await http.patch(`/orders/${orderId}/processes/${procId}`, { worker_ids: [] })
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

function formatMatQty(v: unknown) {
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, '')
}

const issueDialogTitle = computed(() => {
  const no = detail.value?.header_no || detail.value?.execution_no || ''
  return issueDialogType.value === 'return_mat' ? `退料 · ${no}` : `领料 · ${no}`
})

async function openIssueDialog(docType: 'issue' | 'return_mat') {
  issueDialogType.value = docType
  issueQtyDraft.value = {}
  issueDialogVisible.value = true
  await reloadIssueCandidates()
}

async function reloadIssueCandidates() {
  const hid = Number(detail.value?.id)
  if (!hid) return
  issueDialogLoading.value = true
  try {
    const res: any = await http.get('/stock-issues/candidates', { params: { header_id: hid } })
    const data = res.data || {}
    issueMeta.value = data
    issueCandidates.value = data.lines || []
    const draft: Record<number, string> = {}
    for (const row of issueCandidates.value) {
      const max =
        issueDialogType.value === 'issue'
          ? Number(row.remain_need_qty) || 0
          : Number(row.returnable_qty) || 0
      draft[row.id] = max > 0 ? String(max) : ''
    }
    issueQtyDraft.value = draft
  } catch (e: any) {
    issueCandidates.value = []
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载领退料失败')
  } finally {
    issueDialogLoading.value = false
  }
}

function fillIssueMax() {
  const draft: Record<number, string> = {}
  for (const row of issueCandidates.value) {
    const max =
      issueDialogType.value === 'issue'
        ? Number(row.max_issue_qty) || 0
        : Number(row.returnable_qty) || 0
    draft[row.id] = max > 0 ? String(max) : '0'
  }
  issueQtyDraft.value = draft
}

async function submitIssueDialog() {
  const hid = Number(detail.value?.id)
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
    await loadHeaderMaterials()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '提交失败')
  } finally {
    issuePosting.value = false
  }
}

async function openHeaderPacking() {
  packingForm.mode = 'single_size'
  packingForm.pairs_per_carton = 12
  packingPlan.value = null
  packingVisible.value = true
  await loadHeaderPackingPlans()
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
      packingForm.mode = packingPlan.value.mode || 'single_size'
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

function printCarton(id: number) {
  window.open(`${window.location.origin}/admin/packing/print/${id}`, '_blank')
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
    in_process: '在制',
    done: '完工',
    warehoused: '已入库',
    shipped: '已出货',
    scrapped: '作废',
  }
  return map[s] || s
}

function canWarehouse(row: any) {
  return row?.unit_type === 'basket' && !['warehoused', 'shipped', 'scrapped', 'split'].includes(row.status)
}

async function warehouseBasket(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认将筐 ${row.code}（${row.qty} 双）入库？将按分配写入精确销售产量。`,
      '成品入库',
      { type: 'warning' },
    )
  } catch {
    return
  }
  warehousingId.value = row.id
  try {
    const res: any = await http.post(`/trace-units/${row.id}/warehouse`)
    const splits = (res.data?.produced_splits || [])
      .map((x: any) => `${x.sales_order_no} ${x.qty}`)
      .join(' / ')
    ElMessage.success(splits ? `已入库；精确产量 ${splits}` : '已入库')
    if (detail.value?.id) {
      const d: any = await http.get(`/executions/headers/${detail.value.id}`)
      detail.value = d.data
    }
    await Promise.all([loadDetailBaskets(), loadHeaderProcesses()])
    await loadExecutions()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    const msg =
      (typeof detail === 'string' && detail.trim() && !detail.trim().startsWith('<') && detail) ||
      (e?.response?.status === 500 ? '入库失败：服务器内部错误' : '') ||
      e?.message ||
      '入库失败'
    ElMessage.error(msg)
  } finally {
    warehousingId.value = null
  }
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

function printFlowCard(row: ExecutionRow | null) {
  const headerId = Number(row?.id)
  if (!headerId) {
    ElMessage.warning('无生产单，无法打印')
    return
  }
  window.open(
    `${window.location.origin}/admin/executions/print/${headerId}?mode=main-codes`,
    '_blank',
  )
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
  cutVisible.value = true
  void previewCutCards()
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
      },
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
      },
    })
    cutPreview.value = res.data
    ElMessage.success(`已开裁，生成 ${res.data?.to_create || 0} 个码`)
    cutVisible.value = false
    if (res.data?.print_path) {
      window.open(`${window.location.origin}${res.data.print_path}`, '_blank')
    }
    await loadExecutions()
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
.kit-hint {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.4;
}
.dlg-hint {
  margin: 0 0 12px;
}
.execution-detail-tabs {
  margin-bottom: 4px;
}
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
.detail-overview-kv {
  flex: 1;
  min-width: 0;
}
.exe-four-track {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.exe-four-track > div {
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 8px 10px;
  min-width: 0;
}
.exe-four-track span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.exe-four-track b {
  display: block;
  margin-top: 3px;
  font-size: 18px;
  font-variant-numeric: tabular-nums;
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
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 2px;
}
.exe-proc-track {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 10px;
}
.exe-proc-step {
  flex: 1 1 100px;
  min-width: 100px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--el-bg-color);
}
.exe-proc-step.is-current {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.exe-proc-step.is-done {
  border-color: var(--el-color-success-light-5);
}
.exe-proc-name {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.exe-proc-tag {
  font-weight: 500;
}
.exe-proc-qty {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.exe-proc-table {
  margin-bottom: 4px;
}
.exe-proc-table :deep(.el-progress__text) {
  font-size: 12px;
  min-width: 52px;
  margin-left: 6px;
}
@media (max-width: 640px) {
  .exe-four-track {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
