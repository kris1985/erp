<template>
  <div>
    <header class="page-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">订单管理</h1>
        <p class="page-desc">建单 · 派工 · 进度</p>
      </div>
    </header>
  <div class="admin-card">
    <div class="admin-toolbar" style="flex-wrap: wrap; gap: 8px">
      <el-input
        v-model="filters.q"
        clearable
        placeholder="订单号 / 客户"
        style="width: 160px"
        @keyup.enter="search"
      />
      <el-select
        v-model="filters.customer_id"
        clearable
        filterable
        placeholder="客户"
        style="width: 160px"
        @change="search"
      >
        <el-option v-for="c in customers" :key="c.id" :label="c.short_name || c.name" :value="c.id" />
      </el-select>
      <el-select
        v-model="filters.own_product_id"
        clearable
        filterable
        placeholder="产品"
        style="width: 160px"
        @change="search"
      >
        <el-option v-for="p in products" :key="p.id" :label="p.product_code" :value="p.id" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="状态" style="width: 120px" @change="search">
        <el-option label="已确认" value="confirmed" />
        <el-option label="生产中" value="in_progress" />
        <el-option label="已完成" value="completed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-select v-model="filters.kit_ok" clearable placeholder="齐套" style="width: 110px" @change="search">
        <el-option label="齐套" :value="true" />
        <el-option label="缺料" :value="false" />
      </el-select>
      <el-select v-model="filters.is_rush" clearable placeholder="急单" style="width: 100px" @change="search">
        <el-option label="急单" :value="true" />
        <el-option label="普通" :value="false" />
      </el-select>
      <el-date-picker
        v-model="filters.deliveryRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="交期起"
        end-placeholder="交期止"
        style="width: 240px"
        @change="search"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" @click="openCreate">新建订单</el-button>
      <el-button @click="openImport">批量导入</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table
      :data="rows"
      stripe
      border
      style="width: 100%"
      :row-class-name="({ row }: any) => (row.is_rush ? 'rush-row' : '')"
    >
      <el-table-column prop="order_no" label="订单号" width="140">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">{{ row.order_no }}</el-button>
          <el-tag v-if="row.is_rush" size="small" type="danger" style="margin-left: 6px">插单</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="customer_name" label="客户" width="120" />
      <el-table-column label="产品" width="140">
        <template #default="{ row }">{{ row.product_code || productCode(row.own_product_id) }}</template>
      </el-table-column>
      <el-table-column prop="total_qty" label="数量" width="80" />
      <el-table-column label="售价" min-width="90">
        <template #default="{ row }">{{ formatMoney(row.unit_price) }}</template>
      </el-table-column>
      <el-table-column label="齐套" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.kit_ok === true" size="small" type="success">齐套</el-tag>
          <el-tag v-else-if="row.kit_ok === false" size="small" type="danger">缺料</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="delivery_date" label="交期" min-width="110" />
      <el-table-column label="状态" min-width="90">
        <template #default="{ row }">{{ orderStatusLabel(row.status) }}</template>
      </el-table-column>
      <el-table-column label="生产进度" min-width="220">
        <template #default="{ row }">
          <el-tooltip :content="`${overallPercent(row)}%`" placement="top" :show-after="200">
            <el-progress
              :percentage="overallPercent(row)"
              :stroke-width="14"
              :show-text="false"
              :status="overallPercent(row) >= 100 ? 'success' : undefined"
            />
          </el-tooltip>
          <div v-if="bottleneckProcess(row)" class="progress-meta">
            <span class="muted">瓶颈</span>
            <span class="bottleneck-name">{{ bottleneckProcess(row)!.process_name }}</span>
            <span class="muted">{{ processPercent(bottleneckProcess(row)!) }}%</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link @click="openEdit(row)">改明细</el-button>
          <el-button type="primary" link @click="openDispatch(row)">派工</el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => onRowMore(row, cmd)">
            <el-button type="primary" link>更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="toggle-rush">
                  {{ row.is_rush ? '取消急单' : '标急单' }}
                </el-dropdown-item>
                <el-dropdown-item
                  command="status:confirmed"
                  :disabled="row.status === 'confirmed'"
                  divided
                >
                  改为已确认
                </el-dropdown-item>
                <el-dropdown-item
                  command="status:in_progress"
                  :disabled="row.status === 'in_progress'"
                >
                  改为生产中
                </el-dropdown-item>
                <el-dropdown-item
                  command="status:completed"
                  :disabled="row.status === 'completed'"
                >
                  改为已完成
                </el-dropdown-item>
                <el-dropdown-item
                  command="status:cancelled"
                  :disabled="row.status === 'cancelled'"
                >
                  改为已取消
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

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

    <el-drawer
      v-model="detailVisible"
      :title="`订单明细 · ${detailOrder?.order_no || ''}`"
      size="920px"
      class="order-detail-drawer"
    >
      <template v-if="detailOrder">
        <el-tabs v-model="detailTab" class="order-detail-tabs">
          <el-tab-pane label="概览" name="overview">
            <el-descriptions class="detail-kv-table" :column="2" border size="small">
              <el-descriptions-item label="客户">{{ detailOrder.customer_name }}</el-descriptions-item>
              <el-descriptions-item label="产品">{{ detailOrder.product_code || productCode(detailOrder.own_product_id) }}</el-descriptions-item>
              <el-descriptions-item label="交期">{{ detailOrder.delivery_date || '—' }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ orderStatusLabel(detailOrder.status) }}</el-descriptions-item>
              <el-descriptions-item label="总数量">{{ detailOrder.total_qty }}</el-descriptions-item>
              <el-descriptions-item label="售价">{{ formatMoney(detailOrder.unit_price) }}</el-descriptions-item>
              <el-descriptions-item label="急单">
                <el-tag v-if="detailOrder.is_rush" size="small" type="danger">插单</el-tag>
                <span v-else>否</span>
                <span v-if="detailOrder.rush_reason" class="muted" style="margin-left: 8px">
                  {{ detailOrder.rush_reason }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="备注">{{ detailOrder.notes || '—' }}</el-descriptions-item>
              <el-descriptions-item label="总进度">
                <el-progress
                  :percentage="overallPercent(detailOrder)"
                  :stroke-width="12"
                  style="max-width: 200px"
                  :status="overallPercent(detailOrder) >= 100 ? 'success' : undefined"
                />
              </el-descriptions-item>
              <el-descriptions-item label="齐套">
                <el-tag v-if="kit?.kit_ok" size="small" type="success">齐套</el-tag>
                <el-tag v-else-if="kit" size="small" type="danger">缺料</el-tag>
                <span v-else class="muted">—</span>
              </el-descriptions-item>
            </el-descriptions>

            <div style="font-weight: 600; margin: 16px 0 8px">色码明细</div>
            <el-table :data="detailOrder.items || []" stripe border size="small">
              <el-table-column label="颜色" min-width="100">
                <template #default="{ row }">{{ colorName(row.color_id) }}</template>
              </el-table-column>
              <el-table-column label="尺码" width="90">
                <template #default="{ row }">{{ sizeName(row.size_id) }}</template>
              </el-table-column>
              <el-table-column prop="qty" label="计划" width="80" />
              <el-table-column prop="completed_qty" label="完成" width="80" />
              <el-table-column label="进度" min-width="140">
                <template #default="{ row }">
                  <el-progress
                    :percentage="row.qty ? Math.min(100, Math.round((row.completed_qty / row.qty) * 100)) : 0"
                    :stroke-width="12"
                  />
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane name="materials">
            <template #label>
              <span>用料</span>
              <el-tag v-if="kit?.kit_ok" size="small" type="success" style="margin-left: 6px">料够</el-tag>
              <el-tag v-else-if="kit" size="small" type="danger" style="margin-left: 6px">缺料</el-tag>
            </template>
            <div class="materials-toolbar">
              <div class="materials-toolbar-left">
                <el-button @click="loadKit">刷新</el-button>
                <el-dropdown trigger="click">
                  <el-button>
                    BOM
                    <span style="margin-left: 4px">▾</span>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item @click="recalcKit">按双数重算</el-dropdown-item>
                      <el-dropdown-item @click="refreshBom">从BOM刷新</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button v-if="canStockSubmit" type="primary" @click="openIssueDialog('issue')">申请领料</el-button>
                <el-button v-if="canStockSubmit" @click="openIssueDialog('return_mat')">申请退料</el-button>
              </div>
              <div class="materials-toolbar-right">
                <span v-if="kit && materialsToBuyCount > 0" class="muted" style="font-size: 12px">
                  待采 {{ materialsToBuyCount }} 项 · 请到「缺料」处理
                </span>
              </div>
            </div>
            <el-table
              :data="kit?.lines || []"
              stripe
              border
              size="small"
              style="width: 100%"
              empty-text="无物料（空BOM）"
            >
              <el-table-column label="物料图片" width="80" align="center">
                <template #default="{ row }">
                  <el-image
                    v-if="row.image_url"
                    :src="row.image_url"
                    :preview-src-list="[row.image_url]"
                    preview-teleported
                    fit="cover"
                    class="mat-thumb"
                  />
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="物料" min-width="160">
                <template #default="{ row }">
                  <div class="mat-name">{{ row.supplier_product_code }}</div>
                  <div class="mat-sub">{{ row.supplier_product_name || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column prop="required_qty" label="需求" width="72" align="right" />
              <el-table-column label="进度" min-width="140">
                <template #default="{ row }">
                  <div class="mat-progress">
                    已分 {{ row.arrived_qty ?? 0 }} / 已发 {{ row.issued_qty ?? 0 }}
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="110" align="center">
                <template #default="{ row }">
                  <el-tag
                    v-if="Number(row.shortage_qty) > 0"
                    type="danger"
                    size="small"
                    effect="plain"
                  >
                    缺 {{ row.shortage_qty }}
                  </el-tag>
                  <el-tag v-else type="success" size="small" effect="plain">料够</el-tag>
                  <div v-if="Number(row.to_buy_qty) > 0" class="mat-sub" style="margin-top: 4px">
                    待采 {{ row.to_buy_qty }}
                  </div>
                  <div
                    v-else-if="row.purchase_status_label && row.purchase_status !== 'open'"
                    class="mat-sub"
                    style="margin-top: 4px"
                  >
                    {{ row.purchase_status_label }}
                  </div>
                </template>
              </el-table-column>
            </el-table>

            <div class="mat-timeline-head">
              <span style="font-weight: 600">领退料记录</span>
              <el-button link type="primary" :loading="stockDocsLoading" @click="loadStockDocs">刷新</el-button>
            </div>
            <el-table
              v-loading="stockDocsLoading"
              :data="stockDocs"
              stripe
              border
              size="small"
              style="width: 100%"
              empty-text="尚无领退料；车间可点「申请领料」提报，仓管在记录页确认"
            >
              <el-table-column prop="doc_no" label="单号" min-width="110" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.doc_type === 'issue' ? 'success' : 'warning'" size="small">
                    {{ row.doc_type === 'issue' ? row.issue_kind || '领料' : '退料' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag
                    :type="row.status === 'posted' ? 'success' : row.status === 'pending' ? 'warning' : 'info'"
                    size="small"
                    effect="plain"
                  >
                    {{ row.status === 'posted' ? '已过账' : row.status === 'pending' ? '待确认' : '已作废' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="明细" min-width="240">
                <template #default="{ row }">
                  <div v-for="ln in row.lines || []" :key="ln.id" class="doc-line-row">
                    <el-image
                      v-if="ln.image_url"
                      :src="ln.image_url"
                      :preview-src-list="[ln.image_url]"
                      preview-teleported
                      fit="cover"
                      class="mat-thumb-sm"
                    />
                    <span v-else class="mat-thumb-sm mat-thumb-empty">—</span>
                    <span class="mat-sub">{{ ln.supplier_product_code }} × {{ ln.qty }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="notes" label="原因" min-width="120" show-overflow-tooltip />
              <el-table-column label="时间" min-width="150">
                <template #default="{ row }">
                  {{ String(row.posted_at || row.created_at || '').replace('T', ' ').slice(0, 19) || '—' }}
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="生产" name="production">
            <div style="font-weight: 600; margin: 0 0 8px; display: flex; align-items: center; gap: 12px">
              <span>工序进度</span>
              <el-progress
                :percentage="overallPercent(detailOrder)"
                :stroke-width="14"
                style="flex: 1; max-width: 240px"
                :status="overallPercent(detailOrder) >= 100 ? 'success' : undefined"
              />
            </div>
            <el-table :data="detailOrder.processes || []" stripe border size="small" style="width: 100%">
              <el-table-column prop="process_name" label="工序" min-width="90" />
              <el-table-column label="类型" min-width="70">
                <template #default="{ row }">
                  <el-tag v-if="row.process_type === 'group'" size="small" type="warning">集体</el-tag>
                  <span v-else class="muted">个人</span>
                </template>
              </el-table-column>
              <el-table-column label="进度" min-width="180">
                <template #default="{ row }">
                  <div class="muted" style="margin-bottom: 2px">{{ row.completed_qty }}/{{ row.plan_qty }}</div>
                  <el-progress
                    :percentage="processPercent(row)"
                    :stroke-width="12"
                    :status="processPercent(row) >= 100 ? 'success' : undefined"
                  />
                </template>
              </el-table-column>
              <el-table-column label="返修" width="70">
                <template #default="{ row }">{{ row.rework_qty || 0 }}</template>
              </el-table-column>
              <el-table-column label="派工" min-width="220">
                <template #default="{ row }">
                  <template v-if="row.assignments?.length">
                    <el-tag v-if="row.dispatch_mode === 'sku'" size="small" type="info" style="margin-bottom: 4px">
                      色码
                    </el-tag>
                    <el-tag
                      v-else-if="row.dispatch_mode === 'bundle'"
                      size="small"
                      type="warning"
                      style="margin-bottom: 4px"
                    >
                      捆
                    </el-tag>
                    <div
                      v-for="(a, idx) in row.assignments"
                      :key="`${a.worker_id}-${a.color_id || 0}-${a.size_id || 0}-${a.trace_unit_id || 0}-${idx}`"
                      class="muted"
                    >
                      {{ a.worker_name }}
                      <template v-if="a.trace_unit_id"> · {{ a.trace_code || a.trace_unit_id }}</template>
                      <template v-else-if="a.color_id || a.size_id">
                        · {{ a.color_name || '—' }}{{ a.size_value || '' }}
                      </template>
                      <template v-if="a.share_weight != null && a.share_weight !== 1">
                        · 权{{ a.share_weight }}
                      </template>
                      <template v-if="a.quota_qty != null"> · {{ a.reported_qty }}/{{ a.quota_qty }}</template>
                      <template v-else> · 不限</template>
                    </div>
                    <div v-if="!row.has_unlimited_quota && row.unallocated_qty != null" class="muted">
                      未分配池 {{ row.unallocated_qty }}
                    </div>
                  </template>
                  <span v-else>未派工</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">{{ processStatusLabel(row.status) }}</template>
              </el-table-column>
              <el-table-column label="" width="72" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" link @click="openDispatchProcess(detailOrder, row)">派工</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="出货" name="delivery">
            <el-descriptions class="detail-kv-table" :column="1" border size="small">
              <el-descriptions-item label="计划数量">
                {{ delivery?.total_qty ?? detailOrder.total_qty }}
              </el-descriptions-item>
              <el-descriptions-item label="已出货">{{ delivery?.shipped_qty ?? 0 }}</el-descriptions-item>
              <el-descriptions-item label="欠交">{{ delivery?.backlog_qty ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="估算收入">{{ profit?.revenue ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="估算毛利">{{ profit?.gross_profit ?? '—' }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
        </el-tabs>

        <div class="order-detail-actions">
          <el-button @click="openEdit(detailOrder)">改明细</el-button>
          <el-button type="primary" @click="openDispatchFromDetail">选工序派工</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="visible" title="新建订单" width="640px">
      <el-form label-width="90px">
        <el-form-item label="订单号"><el-input v-model="form.order_no" placeholder="可空自动生成" /></el-form-item>
        <el-form-item label="客户">
          <el-select
            v-model="form.customer_id"
            style="width: 100%"
            filterable
            clearable
            allow-create
            default-first-option
            placeholder="选择客户或输入名称"
            @change="onFormCustomerChange"
          >
            <el-option
              v-for="c in customers"
              :key="c.id"
              :label="c.short_name || c.name"
              :value="c.id"
            />
          </el-select>
          <el-input
            v-if="!form.customer_id"
            v-model="form.customer_name"
            placeholder="或手填客户名"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="产品">
          <el-select v-model="form.own_product_id" style="width: 100%" filterable>
            <el-option v-for="p in products" :key="p.id" :label="p.product_code" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="交期">
          <el-date-picker v-model="form.delivery_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="急单">
          <el-switch v-model="form.is_rush" active-text="插单加急" />
          <el-input
            v-if="form.is_rush"
            v-model="form.rush_reason"
            placeholder="加急原因（可选）"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="明细">
          <div style="width: 100%">
            <div v-for="(it, idx) in form.items" :key="idx" style="display: flex; gap: 8px; margin-bottom: 8px">
              <el-select v-model="it.color_id" placeholder="颜色" style="flex: 1">
                <el-option v-for="c in colors" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-select v-model="it.size_id" placeholder="尺码" style="width: 100px">
                <el-option v-for="s in sizes" :key="s.id" :label="s.size_value" :value="s.id" />
              </el-select>
              <el-input-number v-model="it.qty" :min="1" />
              <el-button link type="danger" @click="form.items.splice(idx, 1)">删</el-button>
            </div>
            <el-button size="small" @click="addItem">加一行</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="`改明细 · ${editForm.order_no || ''}`" width="640px">
      <p class="muted" style="margin: 0 0 12px">
        可改客户/交期/色码数量。已有完成量的色码不能删，计划不能低于已完成。保存后工序计划数量会同步。
      </p>
      <el-form label-width="90px">
        <el-form-item label="客户">
          <el-select
            v-model="editForm.customer_id"
            style="width: 100%"
            filterable
            clearable
            placeholder="选择客户"
            @change="onEditCustomerChange"
          >
            <el-option
              v-for="c in customers"
              :key="c.id"
              :label="c.short_name || c.name"
              :value="c.id"
            />
          </el-select>
          <el-input
            v-model="editForm.customer_name"
            placeholder="客户显示名"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="交期">
          <el-date-picker v-model="editForm.delivery_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="急单">
          <el-switch v-model="editForm.is_rush" active-text="插单加急" />
          <el-input
            v-if="editForm.is_rush"
            v-model="editForm.rush_reason"
            placeholder="加急原因（可选）"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="明细">
          <div style="width: 100%">
            <div v-for="(it, idx) in editForm.items" :key="idx" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center">
              <el-select v-model="it.color_id" placeholder="颜色" style="flex: 1" :disabled="it.completed_qty > 0">
                <el-option v-for="c in colors" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-select v-model="it.size_id" placeholder="尺码" style="width: 100px" :disabled="it.completed_qty > 0">
                <el-option v-for="s in sizes" :key="s.id" :label="s.size_value" :value="s.id" />
              </el-select>
              <el-input-number v-model="it.qty" :min="Math.max(1, it.completed_qty || 1)" />
              <span class="muted" style="width: 56px">完成{{ it.completed_qty || 0 }}</span>
              <el-button
                link
                type="danger"
                :disabled="(it.completed_qty || 0) > 0"
                @click="editForm.items.splice(idx, 1)"
              >
                删
              </el-button>
            </div>
            <el-button size="small" @click="addEditItem">加一行</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="editForm.notes" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importVisible" title="批量导入订单" width="520px">
      <p class="muted" style="margin: 0 0 12px">
        CSV 表头：订单号,客户,产品编号,交期,颜色,尺码,数量,备注。同订单号多行会合并色码。
      </p>
      <div style="display: flex; gap: 8px; margin-bottom: 12px">
        <el-button @click="downloadTemplate">下载模板</el-button>
        <el-upload :auto-upload="false" :show-file-list="true" :limit="1" accept=".csv,text/csv" @change="onImportFile">
          <el-button type="primary">选择 CSV</el-button>
        </el-upload>
      </div>
      <div v-if="importResult" class="card-block" style="white-space: pre-wrap; margin: 0">
        {{ importResult.message }}
        <div v-if="importResult.errors?.length" class="muted" style="margin-top: 8px">
          <div v-for="(e, i) in importResult.errors.slice(0, 8)" :key="i">{{ e }}</div>
        </div>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importSaving" :disabled="!importFile" @click="doImport">开始导入</el-button>
      </template>
    </el-dialog>

    <!-- 选工序 -->
    <el-dialog
      v-model="dispatchPickVisible"
      :title="`派工 · ${dispatchOrder?.order_no || ''}`"
      width="480px"
    >
      <p class="muted" style="margin: 0 0 12px">先选一道工序，再派人与配额。</p>
      <div
        v-for="p in dispatchOrder?.processes || []"
        :key="p.id"
        style="display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter)"
      >
        <div style="flex: 1; min-width: 0">
          <div style="font-weight: 600">
            {{ p.process_name }}
            <el-tag v-if="p.process_type === 'group'" size="small" type="warning" style="margin-left: 6px">
              集体
            </el-tag>
            <el-tag v-if="p.dispatch_mode === 'sku'" size="small" type="info" style="margin-left: 6px">色码</el-tag>
            <el-tag v-else-if="p.dispatch_mode === 'bundle'" size="small" type="warning" style="margin-left: 6px">
              捆
            </el-tag>
          </div>
          <div class="muted" style="margin-top: 2px">
            计划 {{ p.plan_qty }}
            <template v-if="p.assigned_worker_names?.length">
              · {{ p.assigned_worker_names.join('、') }}
            </template>
            <template v-else> · 未派工</template>
          </div>
        </div>
        <el-button type="primary" @click="openDispatchProcess(dispatchOrder, p)">派工</el-button>
      </div>
      <template #footer>
        <el-button @click="dispatchPickVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 单工序编辑 -->
    <el-dialog
      v-model="dispatchVisible"
      :title="`派工 · ${dispatchOrder?.order_no || ''} · ${dispatchProcess?.process_name || ''}`"
      width="560px"
    >
      <template v-if="dispatchProcess">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap">
          <span class="muted">计划 {{ dispatchProcess.plan_qty }}</span>
          <template v-if="dispatchMode[dispatchProcess.id] === 'process'">
            <el-tag
              v-if="livePool(dispatchProcess) !== null"
              size="small"
              :type="livePool(dispatchProcess)! > 0 ? 'success' : livePool(dispatchProcess)! < 0 ? 'danger' : 'info'"
            >
              未分配池 {{ livePool(dispatchProcess) }}
            </el-tag>
            <el-tag v-else size="small" type="warning">有人不限 · 池不可用</el-tag>
          </template>
          <el-button link type="primary" style="margin-left: auto" @click="backToDispatchPick">
            换工序
          </el-button>
        </div>

        <template v-if="dispatchMode[dispatchProcess.id] === 'process'">
          <el-select
            v-model="dispatchMap[dispatchProcess.id]"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择工人"
            style="width: 100%; margin-bottom: 12px"
            @change="() => syncQuotas(dispatchProcess!.id)"
          >
            <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
          <div
            v-for="wid in dispatchMap[dispatchProcess.id] || []"
            :key="`${dispatchProcess.id}-${wid}`"
            style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap"
          >
            <span style="width: 72px">{{ workerName(wid) }}</span>
            <el-input-number
              v-model="dispatchQuota[quotaKey(dispatchProcess.id, wid)]"
              :min="0"
              :value-on-clear="null"
              controls-position="right"
              placeholder="不限"
            />
            <el-input-number
              v-if="dispatchProcess.process_type === 'group'"
              v-model="dispatchWeight[quotaKey(dispatchProcess.id, wid)]"
              :min="1"
              :value-on-clear="1"
              controls-position="right"
              placeholder="权重"
              style="width: 110px"
            />
            <span v-if="dispatchProcess.process_type === 'group'" class="muted">权</span>
            <span class="muted">已报 {{ reportedOf(dispatchProcess, wid) ?? 0 }}</span>
            <el-button
              link
              type="warning"
              size="small"
              :disabled="
                (reportedOf(dispatchProcess, wid) ?? 0) <= 0 &&
                Number(dispatchQuota[quotaKey(dispatchProcess.id, wid)] || 0) === 0
              "
              @click="reclaimToPool(dispatchProcess, wid)"
            >
              收回剩余
            </el-button>
            <el-button
              link
              type="primary"
              size="small"
              :disabled="livePool(dispatchProcess) === null || (livePool(dispatchProcess) ?? 0) <= 0"
              @click="claimFromPool(dispatchProcess, wid)"
            >
              从池+100
            </el-button>
          </div>
          <p class="muted" style="margin: 8px 0 0; font-size: 12px">
            配额为空表示不限；未派完的数量进未分配池。请假用「收回剩余」。
            <template v-if="dispatchProcess.process_type === 'group'">
              集体工序可填权重（默认 1=均分；如 2:1 则按比例拆）。
            </template>
          </p>
        </template>

        <template v-else-if="dispatchMode[dispatchProcess.id] === 'bundle'">
          <p v-if="!orderTraceUnits.length" class="muted" style="margin: 0 0 12px">
            本订单暂无捆标。请先打捆后再按捆派工。
          </p>
          <div
            v-for="u in orderTraceUnits"
            :key="`bundle-${dispatchProcess.id}-${u.id}`"
            style="margin-bottom: 12px; padding: 10px; background: var(--el-fill-color-light); border-radius: 6px"
          >
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap">
              <strong>{{ u.code }}</strong>
              <span class="muted">
                {{ u.qty }}双
                <template v-if="u.color_name || u.size_value">
                  · {{ u.color_name || '—' }}{{ u.size_value || '' }}
                </template>
              </span>
              <el-tag
                v-if="liveBundlePool(dispatchProcess, u) !== null"
                size="small"
                :type="
                  liveBundlePool(dispatchProcess, u)! > 0
                    ? 'success'
                    : liveBundlePool(dispatchProcess, u)! < 0
                      ? 'danger'
                      : 'info'
                "
              >
                未分配池 {{ liveBundlePool(dispatchProcess, u) }}
              </el-tag>
              <el-select
                v-model="dispatchBundleMap[bundleMapKey(dispatchProcess.id, u.id)]"
                multiple
                filterable
                clearable
                collapse-tags
                placeholder="工人"
                style="flex: 1; min-width: 140px"
                @change="() => syncBundleQuotas(dispatchProcess!.id, u.id, u.qty)"
              >
                <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
              </el-select>
            </div>
            <div
              v-for="wid in dispatchBundleMap[bundleMapKey(dispatchProcess.id, u.id)] || []"
              :key="`${dispatchProcess.id}-${wid}-${u.id}`"
              style="display: flex; align-items: center; gap: 8px; margin: 4px 0; flex-wrap: wrap"
            >
              <span style="width: 72px">{{ workerName(wid) }}</span>
              <el-input-number
                v-model="dispatchQuota[bundleQuotaKey(dispatchProcess.id, wid, u.id)]"
                :min="0"
                :value-on-clear="null"
                controls-position="right"
                placeholder="不限"
              />
              <el-input-number
                v-if="dispatchProcess.process_type === 'group'"
                v-model="dispatchWeight[bundleQuotaKey(dispatchProcess.id, wid, u.id)]"
                :min="1"
                :value-on-clear="1"
                controls-position="right"
                style="width: 110px"
              />
              <span v-if="dispatchProcess.process_type === 'group'" class="muted">权</span>
              <span class="muted">已报 {{ reportedOfBundle(dispatchProcess, wid, u.id) }}</span>
              <el-button link type="warning" size="small" @click="reclaimBundle(dispatchProcess, wid, u)">
                收回剩余
              </el-button>
            </div>
          </div>
          <p class="muted" style="margin: 8px 0 0; font-size: 12px">
            按捆派工后须扫对应捆报工；默认配额=捆量。与整工序/色码不可同时用。
          </p>
        </template>

        <template v-else>
          <div
            v-for="it in dispatchOrder?.items || []"
            :key="`sku-${dispatchProcess.id}-${it.color_id}-${it.size_id}`"
            style="margin-bottom: 12px; padding: 10px; background: var(--el-fill-color-light); border-radius: 6px"
          >
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap">
              <strong>{{ colorName(it.color_id) }} {{ sizeName(it.size_id) }}码</strong>
              <span class="muted">计划 {{ it.qty }}</span>
              <el-tag
                v-if="liveSkuPool(dispatchProcess, it) !== null"
                size="small"
                :type="
                  liveSkuPool(dispatchProcess, it)! > 0
                    ? 'success'
                    : liveSkuPool(dispatchProcess, it)! < 0
                      ? 'danger'
                      : 'info'
                "
              >
                未分配池 {{ liveSkuPool(dispatchProcess, it) }}
              </el-tag>
              <el-tag v-else size="small" type="warning">有人不限</el-tag>
              <el-select
                v-model="dispatchSkuMap[skuMapKey(dispatchProcess.id, it.color_id, it.size_id)]"
                multiple
                filterable
                clearable
                collapse-tags
                placeholder="工人"
                style="flex: 1; min-width: 140px"
                @change="() => syncSkuQuotas(dispatchProcess!.id, it.color_id, it.size_id)"
              >
                <el-option v-for="w in workers" :key="w.id" :label="w.name" :value="w.id" />
              </el-select>
            </div>
            <div
              v-for="wid in dispatchSkuMap[skuMapKey(dispatchProcess.id, it.color_id, it.size_id)] || []"
              :key="`${dispatchProcess.id}-${wid}-${it.color_id}-${it.size_id}`"
              style="display: flex; align-items: center; gap: 8px; margin: 4px 0; flex-wrap: wrap"
            >
              <span style="width: 72px">{{ workerName(wid) }}</span>
              <el-input-number
                v-model="dispatchQuota[skuQuotaKey(dispatchProcess.id, wid, it.color_id, it.size_id)]"
                :min="0"
                :value-on-clear="null"
                controls-position="right"
                placeholder="不限"
              />
              <el-input-number
                v-if="dispatchProcess.process_type === 'group'"
                v-model="dispatchWeight[skuQuotaKey(dispatchProcess.id, wid, it.color_id, it.size_id)]"
                :min="1"
                :value-on-clear="1"
                controls-position="right"
                style="width: 110px"
              />
              <span v-if="dispatchProcess.process_type === 'group'" class="muted">权</span>
              <span class="muted">已报 {{ reportedOfSku(dispatchProcess, wid, it.color_id, it.size_id) }}</span>
              <el-button link type="warning" size="small" @click="reclaimSku(dispatchProcess, wid, it)">
                收回剩余
              </el-button>
            </div>
          </div>
        </template>

        <el-divider style="margin: 16px 0 12px" />
        <div style="display: flex; flex-direction: column; gap: 12px">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
            <div>
              <div style="font-weight: 500">按色码派工</div>
              <div class="muted" style="font-size: 12px">按颜色×尺码拆配额；与整工序/捆不可同时用</div>
            </div>
            <el-switch
              :model-value="dispatchMode[dispatchProcess.id] === 'sku'"
              @change="(on) => toggleDispatchMode(dispatchProcess!, on ? 'sku' : 'process')"
            />
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
            <div>
              <div style="font-weight: 500">按捆派工</div>
              <div class="muted" style="font-size: 12px">绑 trace_unit；报工须扫对应捆</div>
            </div>
            <el-switch
              :model-value="dispatchMode[dispatchProcess.id] === 'bundle'"
              @change="(on) => toggleDispatchMode(dispatchProcess!, on ? 'bundle' : 'process')"
            />
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="dispatchVisible = false">取消</el-button>
        <el-button type="primary" :loading="dispatchSaving" @click="saveDispatch">保存派工</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="issueDialogVisible"
      :title="issueDialogTitle"
      width="780px"
      destroy-on-close
    >
      <p class="muted" style="margin: 0 0 10px; font-size: 13px; line-height: 1.5">
        <template v-if="issueDialogType === 'issue'">
          提交后进入「待确认」，仓管在「领退料记录」确认后才扣库存发到车间。可多次申请；受库存（占用+池−待确认）限制。
        </template>
        <template v-else>提交退料申请，仓管确认后才把已发退回库存池。</template>
      </p>
      <div style="margin-bottom: 10px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
        <el-tag v-if="issueDialogType === 'issue' && issueMeta?.issue_kind_next" type="info" effect="plain">
          本次：{{ issueMeta.issue_kind_next }}
        </el-tag>
        <el-select
          v-model="issueReason"
          filterable
          allow-create
          clearable
          placeholder="原因（补领建议填写）"
          style="width: 200px"
        >
          <el-option v-for="r in issueReasonOptions" :key="r" :label="r" :value="r" />
        </el-select>
        <el-button size="small" @click="fillIssueMax">
          {{ issueDialogType === 'issue' ? '按库存填满' : '填满可退' }}
        </el-button>
        <el-button size="small" @click="clearIssueQty">清空</el-button>
      </div>
      <el-table v-loading="issueDialogLoading" :data="issueCandidates" border size="small" max-height="380">
        <el-table-column label="图片" width="64" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.image_url"
              :src="row.image_url"
              :preview-src-list="[row.image_url]"
              preview-teleported
              fit="cover"
              class="mat-thumb"
            />
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="supplier_product_code" label="物料" min-width="100" />
        <el-table-column prop="supplier_product_name" label="名称" min-width="130" />
        <el-table-column label="需求" width="70" align="right">
          <template #default="{ row }">{{ row.required_qty }}</template>
        </el-table-column>
        <el-table-column label="已分/已发" width="100" align="right">
          <template #default="{ row }">{{ row.arrived_qty }} / {{ row.issued_qty }}</template>
        </el-table-column>
        <el-table-column v-if="issueDialogType === 'issue'" label="池" width="70" align="right">
          <template #default="{ row }">{{ row.pool_qty ?? 0 }}</template>
        </el-table-column>
        <el-table-column
          v-if="issueDialogType === 'return_mat'"
          label="可退"
          width="80"
          align="right"
        >
          <template #default="{ row }">
            <strong>{{ row.returnable_qty }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="本次" width="120">
          <template #default="{ row }">
            <el-input v-model="issueQtyDraft[row.id]" size="small" placeholder="数量" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="issueDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="issuePosting" @click="submitIssueDialog">
          提交{{ issueDialogType === 'issue' ? '领料' : '退料' }}申请
        </el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const canStockSubmit = computed(
  () =>
    auth.hasCapability('stock_docs') &&
    (auth.role === 'admin' ||
      auth.hasPermission('btn.stock_issues.submit') ||
      auth.hasPermission('btn.stock_issues.write')),
)
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const products = ref<any[]>([])
const customers = ref<any[]>([])
const colors = ref<any[]>([])
const sizes = ref<any[]>([])
const workers = ref<any[]>([])
const filters = reactive<{
  q: string
  customer_id: number | null
  own_product_id: number | null
  status: string
  kit_ok: boolean | null
  is_rush: boolean | null
  deliveryRange: string[] | null
}>({
  q: '',
  customer_id: null,
  own_product_id: null,
  status: '',
  kit_ok: null,
  is_rush: null,
  deliveryRange: null,
})
const visible = ref(false)
const detailVisible = ref(false)
const detailTab = ref('overview')
const detailOrder = ref<any>(null)
const kit = ref<any>(null)
const stockDocs = ref<any[]>([])
const stockDocsLoading = ref(false)
const issueDialogVisible = ref(false)
const issueDialogType = ref<'issue' | 'return_mat'>('issue')
const issueDialogLoading = ref(false)
const issuePosting = ref(false)
const issueCandidates = ref<any[]>([])
const issueMeta = ref<any>(null)
const issueQtyDraft = ref<Record<number, string>>({})
const issueReason = ref('')
const issueReasonOptions = ['计划少算', '到货补领', '部分缺货二次领', '损耗补领', '停工退料', '余料退回', '其他']
const delivery = ref<any>(null)
const profit = ref<any>(null)

const materialsToBuyCount = computed(() =>
  (kit.value?.lines || []).filter((l: any) => Number(l.to_buy_qty) > 0).length,
)

const issueDialogTitle = computed(() => {
  const no = detailOrder.value?.order_no || ''
  if (issueDialogType.value === 'return_mat') return `退料 · ${no}`
  const kind = issueMeta.value?.issue_kind_next
  return kind ? `${kind} · ${no}` : `领料 · ${no}`
})

const editVisible = ref(false)
const editSaving = ref(false)
const editForm = reactive<any>({
  id: null,
  order_no: '',
  customer_id: null,
  customer_name: '',
  delivery_date: '',
  notes: '',
  is_rush: false,
  rush_reason: '',
  items: [],
})
const importVisible = ref(false)
const importSaving = ref(false)
const importFile = ref<File | null>(null)
const importResult = ref<any>(null)
const dispatchPickVisible = ref(false)
const dispatchVisible = ref(false)
const dispatchSaving = ref(false)
const dispatchOrder = ref<any>(null)
const dispatchProcess = ref<any>(null)
const dispatchMap = reactive<Record<number, number[]>>({})
const dispatchQuota = reactive<Record<string, number | null>>({})
const dispatchWeight = reactive<Record<string, number>>({})
const dispatchMode = reactive<Record<number, 'process' | 'sku' | 'bundle'>>({})
const dispatchSkuMap = reactive<Record<string, number[]>>({})
const dispatchBundleMap = reactive<Record<string, number[]>>({})
const orderTraceUnits = ref<any[]>([])
const form = reactive<any>({
  order_no: '',
  customer_id: null,
  customer_name: '',
  own_product_id: null,
  delivery_date: '',
  notes: '',
  is_rush: false,
  rush_reason: '',
  items: [{ color_id: null, size_id: null, qty: 100 }],
})

function onFormCustomerChange(id: number | string | null) {
  if (typeof id === 'string') {
    // allow-create 输入的名称
    form.customer_id = null
    form.customer_name = id
    return
  }
  const c = customers.value.find((x) => x.id === id)
  form.customer_name = c ? c.short_name || c.name : ''
}

function onEditCustomerChange(id: number | null) {
  const c = customers.value.find((x) => x.id === id)
  if (c) editForm.customer_name = c.short_name || c.name
}

function productCode(id: number) {
  return products.value.find((p) => p.id === id)?.product_code || id
}

const ORDER_STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  in_progress: '生产中',
  completed: '已完成',
  cancelled: '已取消',
}

const PROCESS_STATUS_LABEL: Record<string, string> = {
  pending: '待开始',
  in_progress: '进行中',
  completed: '已完成',
}

function formatMoney(v: any) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function orderStatusLabel(status: string) {
  return ORDER_STATUS_LABEL[status] || status
}

function processStatusLabel(status: string) {
  return PROCESS_STATUS_LABEL[status] || status
}

/** 与看板一致：各工序完成率取平均 */
function processPercent(p: { completed_qty?: number; plan_qty?: number }) {
  const plan = Number(p?.plan_qty || 0)
  if (!plan) return 0
  return Math.min(100, Math.round((Number(p.completed_qty || 0) / plan) * 100))
}

function overallPercent(row: { processes?: any[] } | null) {
  const ps = row?.processes || []
  if (!ps.length) return 0
  const sum = ps.reduce((s, p) => s + processPercent(p), 0)
  return Math.round(sum / ps.length)
}

/** 列表用：进度最低且未完成的工序 */
function bottleneckProcess(row: { processes?: any[] } | null) {
  const ps = (row?.processes || []).filter((p) => processPercent(p) < 100)
  if (!ps.length) return null
  return ps.reduce((a, b) => (processPercent(a) <= processPercent(b) ? a : b))
}

function workerName(id: number) {
  return workers.value.find((w) => w.id === id)?.name || id
}

function quotaKey(processId: number, workerId: number) {
  return `${processId}:${workerId}`
}

function skuMapKey(processId: number, colorId: number | null | undefined, sizeId: number | null | undefined) {
  return `${processId}:${colorId ?? 0}:${sizeId ?? 0}`
}

function skuQuotaKey(
  processId: number,
  workerId: number,
  colorId: number | null | undefined,
  sizeId: number | null | undefined,
) {
  return `${processId}:${workerId}:${colorId ?? 0}:${sizeId ?? 0}`
}

function reportedOf(p: any, workerId: number) {
  const a = (p.assignments || []).find(
    (x: any) => x.worker_id === workerId && !x.color_id && !x.size_id && !x.trace_unit_id,
  )
  return a ? Number(a.reported_qty || 0) : 0
}

function reportedOfSku(p: any, workerId: number, colorId: number | null | undefined, sizeId: number | null | undefined) {
  const a = (p.assignments || []).find(
    (x: any) =>
      x.worker_id === workerId &&
      !x.trace_unit_id &&
      (x.color_id || null) === (colorId || null) &&
      (x.size_id || null) === (sizeId || null),
  )
  return a ? Number(a.reported_qty || 0) : 0
}

function bundleMapKey(processId: number, unitId: number) {
  return `${processId}:u:${unitId}`
}

function bundleQuotaKey(processId: number, workerId: number, unitId: number) {
  return `${processId}:${workerId}:u:${unitId}`
}

function reportedOfBundle(p: any, workerId: number, unitId: number) {
  const a = (p.assignments || []).find(
    (x: any) => x.worker_id === workerId && Number(x.trace_unit_id) === Number(unitId),
  )
  return a ? Number(a.reported_qty || 0) : 0
}

function liveBundlePool(p: any, u: any): number | null {
  const key = bundleMapKey(p.id, u.id)
  const ids = dispatchBundleMap[key] || []
  if (!ids.length) return Number(u.qty)
  const quotas = ids.map((wid) => dispatchQuota[bundleQuotaKey(p.id, wid, u.id)])
  if (quotas.some((q) => q === null || q === undefined || Number.isNaN(Number(q)))) return null
  const allocated = quotas.reduce((s, q) => s + Number(q), 0)
  return Number(u.qty) - allocated
}

function weightOf(key: string): number | null {
  const w = dispatchWeight[key]
  if (w === undefined || w === null || Number.isNaN(Number(w))) return null
  const n = Number(w)
  return n > 0 ? n : 1
}

function livePool(p: any): number | null {
  const ids = dispatchMap[p.id] || []
  if (!ids.length) return p.plan_qty
  const quotas = ids.map((wid) => dispatchQuota[quotaKey(p.id, wid)])
  if (quotas.some((q) => q === null || q === undefined || Number.isNaN(Number(q)))) return null
  const allocated = quotas.reduce((s, q) => s + Number(q), 0)
  return Number(p.plan_qty) - allocated
}

function liveSkuPool(p: any, it: any): number | null {
  const key = skuMapKey(p.id, it.color_id, it.size_id)
  const ids = dispatchSkuMap[key] || []
  if (!ids.length) return Number(it.qty)
  const quotas = ids.map((wid) => dispatchQuota[skuQuotaKey(p.id, wid, it.color_id, it.size_id)])
  if (quotas.some((q) => q === null || q === undefined || Number.isNaN(Number(q)))) return null
  const allocated = quotas.reduce((s, q) => s + Number(q), 0)
  return Number(it.qty) - allocated
}

/** 请假：配额锁到已报，剩余回未分配池 */
function reclaimToPool(p: any, workerId: number) {
  const reported = reportedOf(p, workerId)
  dispatchQuota[quotaKey(p.id, workerId)] = reported
  ElMessage.success(`${workerName(workerId)} 配额已锁到已报 ${reported}，剩余回池`)
}

function reclaimSku(p: any, workerId: number, it: any) {
  const reported = reportedOfSku(p, workerId, it.color_id, it.size_id)
  dispatchQuota[skuQuotaKey(p.id, workerId, it.color_id, it.size_id)] = reported
  ElMessage.success(`${workerName(workerId)} 配额已锁到已报 ${reported}`)
}

/** 从池领取固定额度（保存后生效） */
function claimFromPool(p: any, workerId: number, amount = 100) {
  const pool = livePool(p)
  if (pool === null || pool <= 0) {
    ElMessage.warning('无可用未分配池（需人人都有数字配额）')
    return
  }
  const key = quotaKey(p.id, workerId)
  const cur = dispatchQuota[key]
  const base = cur === null || cur === undefined || Number.isNaN(Number(cur)) ? reportedOf(p, workerId) : Number(cur)
  const add = Math.min(amount, pool)
  dispatchQuota[key] = base + add
  ElMessage.success(`${workerName(workerId)} 从池领取 ${add}`)
}

function syncQuotas(processId: number) {
  const ids = dispatchMap[processId] || []
  const keys = Object.keys(dispatchQuota)
  for (const k of keys) {
    const parts = k.split(':')
    if (parts.length === 2 && Number(parts[0]) === processId) {
      const wid = Number(parts[1])
      if (!ids.includes(wid)) {
        delete dispatchQuota[k]
        delete dispatchWeight[k]
      }
    }
  }
  for (const wid of ids) {
    const qk = quotaKey(processId, wid)
    if (dispatchWeight[qk] === undefined) dispatchWeight[qk] = 1
  }
}

function syncSkuQuotas(processId: number, colorId: number | null | undefined, sizeId: number | null | undefined) {
  const ids = dispatchSkuMap[skuMapKey(processId, colorId, sizeId)] || []
  const prefix = `${processId}:`
  const suffix = `:${colorId ?? 0}:${sizeId ?? 0}`
  for (const k of Object.keys(dispatchQuota)) {
    if (k.startsWith(prefix) && k.endsWith(suffix) && k.split(':').length === 4) {
      const wid = Number(k.split(':')[1])
      if (!ids.includes(wid)) delete dispatchQuota[k]
    }
  }
}

function onModeChange(p: any) {
  const mode = dispatchMode[p.id]
  if (mode === 'sku') {
    dispatchMap[p.id] = []
    for (const key of Object.keys(dispatchBundleMap)) {
      if (key.startsWith(`${p.id}:`)) delete dispatchBundleMap[key]
    }
    for (const it of dispatchOrder.value?.items || []) {
      const key = skuMapKey(p.id, it.color_id, it.size_id)
      if (!dispatchSkuMap[key]) dispatchSkuMap[key] = []
    }
  } else if (mode === 'bundle') {
    dispatchMap[p.id] = []
    for (const key of Object.keys(dispatchSkuMap)) {
      if (key.startsWith(`${p.id}:`)) delete dispatchSkuMap[key]
    }
    for (const u of orderTraceUnits.value) {
      const key = bundleMapKey(p.id, u.id)
      if (!dispatchBundleMap[key]) dispatchBundleMap[key] = []
    }
  } else {
    for (const key of Object.keys(dispatchSkuMap)) {
      if (key.startsWith(`${p.id}:`)) delete dispatchSkuMap[key]
    }
    for (const key of Object.keys(dispatchBundleMap)) {
      if (key.startsWith(`${p.id}:`)) delete dispatchBundleMap[key]
    }
  }
}

function toggleDispatchMode(p: any, mode: 'process' | 'sku' | 'bundle') {
  dispatchMode[p.id] = mode
  onModeChange(p)
}

function syncBundleQuotas(processId: number, unitId: number, bundleQty: number) {
  const ids = dispatchBundleMap[bundleMapKey(processId, unitId)] || []
  const prefix = `${processId}:`
  const suffix = `:u:${unitId}`
  for (const k of Object.keys(dispatchQuota)) {
    if (k.startsWith(prefix) && k.endsWith(suffix)) {
      const wid = Number(k.split(':')[1])
      if (!ids.includes(wid)) {
        delete dispatchQuota[k]
        delete dispatchWeight[k]
      }
    }
  }
  for (const wid of ids) {
    const qk = bundleQuotaKey(processId, wid, unitId)
    if (dispatchQuota[qk] === undefined) dispatchQuota[qk] = bundleQty
    if (dispatchWeight[qk] === undefined) dispatchWeight[qk] = 1
  }
}

function reclaimBundle(p: any, workerId: number, u: any) {
  const reported = reportedOfBundle(p, workerId, u.id)
  dispatchQuota[bundleQuotaKey(p.id, workerId, u.id)] = reported
  ElMessage.success(`${workerName(workerId)} 配额已锁到已报 ${reported}`)
}

async function loadOrderTraceUnits(orderId: number) {
  try {
    const res: any = await http.get(`/orders/${orderId}/trace-units`)
    orderTraceUnits.value = res.data?.items || []
  } catch {
    orderTraceUnits.value = []
  }
}

function colorName(id: number | null | undefined) {
  if (!id) return '—'
  return colors.value.find((c) => c.id === id)?.name || id
}

function sizeName(id: number | null | undefined) {
  if (!id) return '—'
  return sizes.value.find((s) => s.id === id)?.size_value || id
}

async function openDetail(row: any) {
  detailOrder.value = row
  detailTab.value = 'overview'
  detailVisible.value = true
  kit.value = null
  stockDocs.value = []
  delivery.value = null
  profit.value = null
  await Promise.all([loadKit(), loadStockDocs(), loadDeliveryProfit()])
}

async function loadKit() {
  if (!detailOrder.value) return
  const res: any = await http.get(`/orders/${detailOrder.value.id}/materials`)
  kit.value = res.data
}

async function loadStockDocs() {
  if (!detailOrder.value) return
  stockDocsLoading.value = true
  try {
    const res: any = await http.get('/stock-issues', {
      params: { order_id: detailOrder.value.id, page_size: 100 },
    })
    stockDocs.value = res.data?.items || []
  } catch {
    stockDocs.value = []
  } finally {
    stockDocsLoading.value = false
  }
}

async function openIssueDialog(docType: 'issue' | 'return_mat') {
  if (!detailOrder.value) return
  if (!canStockSubmit.value) {
    ElMessage.warning('无提报权限')
    return
  }
  issueDialogType.value = docType
  issueReason.value = docType === 'return_mat' ? '停工退料' : ''
  issueDialogVisible.value = true
  await reloadIssueCandidates()
}

function fillIssueDefaults() {
  const draft: Record<number, string> = {}
  for (const row of issueCandidates.value) {
    if (issueDialogType.value === 'return_mat') {
      const max = Number(row.returnable_qty) || 0
      draft[row.id] = max > 0 ? String(max) : ''
      continue
    }
    // 领料：默认填「需求 − 已发」；已发已达需求则为 0
    const required = Number(row.required_qty) || 0
    const issued = Number(row.issued_qty) || 0
    const remain = Math.max(0, required - issued)
    draft[row.id] = remain > 0 ? String(remain) : '0'
  }
  issueQtyDraft.value = draft
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

function clearIssueQty() {
  const draft: Record<number, string> = {}
  for (const row of issueCandidates.value) draft[row.id] = ''
  issueQtyDraft.value = draft
}

async function reloadIssueCandidates() {
  if (!detailOrder.value) return
  issueDialogLoading.value = true
  try {
    const res: any = await http.get('/stock-issues/candidates', {
      params: { order_id: detailOrder.value.id },
    })
    const data = res.data || {}
    issueMeta.value = data
    issueCandidates.value = data.lines || (Array.isArray(data) ? data : [])
    fillIssueDefaults()
  } finally {
    issueDialogLoading.value = false
  }
}

async function submitIssueDialog() {
  if (!detailOrder.value) return
  const lines: { requirement_id: number; qty: number }[] = []
  for (const row of issueCandidates.value) {
    const raw = issueQtyDraft.value[row.id]
    if (raw === undefined || raw === '') continue
    const qty = Number(raw)
    if (!(qty > 0)) continue
    if (issueDialogType.value === 'return_mat') {
      const max = Number(row.returnable_qty) || 0
      if (qty > max) {
        ElMessage.warning(`${row.supplier_product_code} 超过可退 ${max}`)
        return
      }
    } else {
      // 领料允许超计划；仅提示库存可能不足（后端会硬校验池+占用）
      const stockMax = Number(row.max_issue_qty) || 0
      if (stockMax > 0 && qty > stockMax) {
        ElMessage.warning(
          `${row.supplier_product_code} 超过当前库存可发 ${stockMax}（占用+池）`,
        )
        return
      }
    }
    lines.push({ requirement_id: row.id, qty })
  }
  if (!lines.length) {
    ElMessage.warning('请填写数量')
    return
  }
  const isSupplement =
    issueDialogType.value === 'issue' && Number(issueMeta.value?.issue_seq_next || 1) > 1
  if (isSupplement && !issueReason.value) {
    ElMessage.warning('补领请选择原因')
    return
  }
  const label = issueDialogType.value === 'issue' ? (isSupplement ? '补领' : '领料') : '退料'
  await ElMessageBox.confirm(`提交${label}申请（${lines.length} 行），待仓管确认后过账？`, label, {
    type: 'info',
  })
  issuePosting.value = true
  try {
    await http.post('/stock-issues', {
      doc_type: issueDialogType.value,
      order_id: detailOrder.value.id,
      notes: issueReason.value || undefined,
      lines,
    })
    ElMessage.success(`${label}已提交，待仓管确认`)
    issueDialogVisible.value = false
    await Promise.all([loadKit(), loadStockDocs()])
  } finally {
    issuePosting.value = false
  }
}

async function loadDeliveryProfit() {
  if (!detailOrder.value) return
  const [d, p]: any[] = await Promise.all([
    http.get(`/orders/${detailOrder.value.id}/delivery`),
    http.get(`/orders/${detailOrder.value.id}/profit`),
  ])
  delivery.value = d.data
  profit.value = p.data
}

async function recalcKit() {
  if (!detailOrder.value) return
  await http.post(`/orders/${detailOrder.value.id}/materials/recalculate`)
  await loadKit()
}

async function refreshBom() {
  if (!detailOrder.value) return
  await http.post(`/orders/${detailOrder.value.id}/materials/refresh`)
  await loadKit()
}

function openDispatchFromDetail() {
  if (!detailOrder.value) return
  openDispatch(detailOrder.value)
}

function addItem() {
  form.items.push({
    color_id: colors.value[0]?.id || null,
    size_id: sizes.value[0]?.id || null,
    qty: 100,
  })
}

function addEditItem() {
  editForm.items.push({
    color_id: colors.value[0]?.id || null,
    size_id: sizes.value[0]?.id || null,
    qty: 100,
    completed_qty: 0,
  })
}

function openEdit(row: any) {
  if (!row) return
  detailVisible.value = false
  Object.assign(editForm, {
    id: row.id,
    order_no: row.order_no,
    customer_id: row.customer_id || null,
    customer_name: row.customer_name,
    delivery_date: row.delivery_date || '',
    notes: row.notes || '',
    is_rush: !!row.is_rush,
    rush_reason: row.rush_reason || '',
    items: (row.items || []).map((i: any) => ({
      color_id: i.color_id,
      size_id: i.size_id,
      qty: i.qty,
      completed_qty: i.completed_qty || 0,
    })),
  })
  editVisible.value = true
}

async function saveEdit() {
  if (!editForm.id || !editForm.customer_name || !editForm.items.length) {
    ElMessage.warning('请填写客户和明细')
    return
  }
  editSaving.value = true
  try {
    await http.patch(`/orders/${editForm.id}`, {
      customer_id: editForm.customer_id || null,
      customer_name: editForm.customer_name,
      delivery_date: editForm.delivery_date || null,
      notes: editForm.notes || null,
      is_rush: !!editForm.is_rush,
      rush_reason: editForm.is_rush ? editForm.rush_reason || null : null,
      items: editForm.items.map((i: any) => ({
        color_id: i.color_id,
        size_id: i.size_id,
        qty: i.qty,
      })),
    })
    ElMessage.success('明细已更新')
    editVisible.value = false
    await load()
  } finally {
    editSaving.value = false
  }
}

function openImport() {
  importFile.value = null
  importResult.value = null
  importVisible.value = true
}

function onImportFile(file: any) {
  importFile.value = file?.raw || null
  importResult.value = null
}

async function downloadTemplate() {
  const res = await fetch('/api/v1/orders/import-template', {
    headers: { Authorization: `Bearer ${auth.token}` },
  })
  if (!res.ok) {
    ElMessage.error('下载失败')
    return
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'order_import_template.csv'
  a.click()
  URL.revokeObjectURL(url)
}

async function doImport() {
  if (!importFile.value) return
  importSaving.value = true
  try {
    const fd = new FormData()
    fd.append('file', importFile.value)
    const res = await fetch('/api/v1/orders/import', {
      method: 'POST',
      headers: { Authorization: `Bearer ${auth.token}` },
      body: fd,
    })
    const json = await res.json()
    if (!res.ok || !json.ok) {
      ElMessage.error(json?.error?.message || json?.detail || '导入失败')
      return
    }
    importResult.value = json.data
    ElMessage.success(json.data.message || '导入完成')
    await load()
  } finally {
    importSaving.value = false
  }
}

function buildQueryParams() {
  const range = filters.deliveryRange
  return {
    page: page.value,
    page_size: pageSize.value,
    q: filters.q || undefined,
    customer_id: filters.customer_id || undefined,
    own_product_id: filters.own_product_id || undefined,
    status: filters.status || undefined,
    kit_ok: filters.kit_ok === null || filters.kit_ok === undefined ? undefined : filters.kit_ok,
    is_rush: filters.is_rush === null || filters.is_rush === undefined ? undefined : filters.is_rush,
    delivery_date_from: range?.[0] || undefined,
    delivery_date_to: range?.[1] || undefined,
  }
}

async function load() {
  const res: any = await http.get('/orders', {
    params: buildQueryParams(),
  })
  rows.value = res.data.items
  total.value = res.data.total || 0
  if (!rows.value.length && page.value > 1 && total.value > 0) {
    page.value = Math.max(1, Math.ceil(total.value / pageSize.value))
    await load()
  }
}

function search() {
  page.value = 1
  void load()
}

function resetFilters() {
  filters.q = ''
  filters.customer_id = null
  filters.own_product_id = null
  filters.status = ''
  filters.kit_ok = null
  filters.is_rush = null
  filters.deliveryRange = null
  search()
}

function onPageSizeChange() {
  page.value = 1
  void load()
}

function openCreate() {
  Object.assign(form, {
    order_no: '',
    customer_id: null,
    customer_name: '',
    own_product_id: products.value[0]?.id || null,
    delivery_date: '',
    notes: '',
    is_rush: false,
    rush_reason: '',
    items: [
      {
        color_id: colors.value[0]?.id || null,
        size_id: sizes.value[0]?.id || null,
        qty: 100,
      },
    ],
  })
  visible.value = true
}

function resetDispatchState() {
  for (const key of Object.keys(dispatchMap)) delete dispatchMap[Number(key)]
  for (const key of Object.keys(dispatchQuota)) delete dispatchQuota[key]
  for (const key of Object.keys(dispatchWeight)) delete dispatchWeight[key]
  for (const key of Object.keys(dispatchMode)) delete dispatchMode[Number(key)]
  for (const key of Object.keys(dispatchSkuMap)) delete dispatchSkuMap[key]
  for (const key of Object.keys(dispatchBundleMap)) delete dispatchBundleMap[key]
}

function loadProcessDispatchState(p: any) {
  const mode =
    p.dispatch_mode === 'sku' ? 'sku' : p.dispatch_mode === 'bundle' ? 'bundle' : 'process'
  dispatchMode[p.id] = mode
  if (mode === 'sku') {
    dispatchMap[p.id] = []
    for (const it of dispatchOrder.value?.items || []) {
      dispatchSkuMap[skuMapKey(p.id, it.color_id, it.size_id)] = []
    }
    for (const a of p.assignments || []) {
      const key = skuMapKey(p.id, a.color_id, a.size_id)
      if (!dispatchSkuMap[key]) dispatchSkuMap[key] = []
      if (!dispatchSkuMap[key].includes(a.worker_id)) dispatchSkuMap[key].push(a.worker_id)
      const qk = skuQuotaKey(p.id, a.worker_id, a.color_id, a.size_id)
      dispatchQuota[qk] = a.quota_qty === null || a.quota_qty === undefined ? null : a.quota_qty
      dispatchWeight[qk] = a.share_weight && a.share_weight > 0 ? a.share_weight : 1
    }
  } else if (mode === 'bundle') {
    dispatchMap[p.id] = []
    for (const u of orderTraceUnits.value) {
      dispatchBundleMap[bundleMapKey(p.id, u.id)] = []
    }
    for (const a of p.assignments || []) {
      if (!a.trace_unit_id) continue
      const key = bundleMapKey(p.id, a.trace_unit_id)
      if (!dispatchBundleMap[key]) dispatchBundleMap[key] = []
      if (!dispatchBundleMap[key].includes(a.worker_id)) dispatchBundleMap[key].push(a.worker_id)
      const qk = bundleQuotaKey(p.id, a.worker_id, a.trace_unit_id)
      dispatchQuota[qk] = a.quota_qty === null || a.quota_qty === undefined ? null : a.quota_qty
      dispatchWeight[qk] = a.share_weight && a.share_weight > 0 ? a.share_weight : 1
    }
  } else {
    const processAssigns = (p.assignments || []).filter(
      (a: any) => !a.color_id && !a.size_id && !a.trace_unit_id,
    )
    dispatchMap[p.id] = processAssigns.length
      ? processAssigns.map((a: any) => a.worker_id)
      : [...(p.assigned_worker_ids || [])]
    for (const a of processAssigns) {
      const qk = quotaKey(p.id, a.worker_id)
      dispatchQuota[qk] = a.quota_qty === null || a.quota_qty === undefined ? null : a.quota_qty
      dispatchWeight[qk] = a.share_weight && a.share_weight > 0 ? a.share_weight : 1
    }
  }
}

/** 列表「派工」：先选工序 */
function openDispatch(row: any) {
  dispatchOrder.value = JSON.parse(JSON.stringify(row))
  dispatchProcess.value = null
  resetDispatchState()
  dispatchVisible.value = false
  dispatchPickVisible.value = true
}

async function openDispatchProcess(order: any, process: any) {
  if (!order || !process) return
  // 详情里直接点某工序：确保订单上下文最新
  if (!dispatchOrder.value || dispatchOrder.value.id !== order.id) {
    dispatchOrder.value = JSON.parse(JSON.stringify(order))
  } else if (order !== dispatchOrder.value) {
    // 同步该工序最新 assignments（详情表里的 row）
    const idx = (dispatchOrder.value.processes || []).findIndex((x: any) => x.id === process.id)
    if (idx >= 0) dispatchOrder.value.processes[idx] = JSON.parse(JSON.stringify(process))
  }
  const p =
    (dispatchOrder.value.processes || []).find((x: any) => x.id === process.id) ||
    JSON.parse(JSON.stringify(process))
  resetDispatchState()
  await loadOrderTraceUnits(dispatchOrder.value.id)
  loadProcessDispatchState(p)
  dispatchProcess.value = p
  dispatchPickVisible.value = false
  dispatchVisible.value = true
}

function backToDispatchPick() {
  dispatchVisible.value = false
  dispatchProcess.value = null
  if (dispatchOrder.value) dispatchPickVisible.value = true
}

async function saveDispatch() {
  if (!dispatchOrder.value || !dispatchProcess.value) return
  const p = dispatchProcess.value
  const mode = dispatchMode[p.id]
  if (mode === 'sku') {
    for (const it of dispatchOrder.value.items || []) {
      const pool = liveSkuPool(p, it)
      if (pool !== null && pool < 0) {
        ElMessage.error(`${colorName(it.color_id)}${sizeName(it.size_id)}码 配额超过计划`)
        return
      }
    }
  } else if (mode === 'bundle') {
    for (const u of orderTraceUnits.value) {
      const pool = liveBundlePool(p, u)
      if (pool !== null && pool < 0) {
        ElMessage.error(`捆 ${u.code} 配额超过捆量`)
        return
      }
    }
  } else {
    const pool = livePool(p)
    if (pool !== null && pool < 0) {
      ElMessage.error('已派配额超过计划，请先减配额')
      return
    }
  }
  dispatchSaving.value = true
  try {
    let assignments: any[] = []
    const isGroup = p.process_type === 'group'
    if (mode === 'sku') {
      for (const it of dispatchOrder.value.items || []) {
        const ids = dispatchSkuMap[skuMapKey(p.id, it.color_id, it.size_id)] || []
        for (const wid of ids) {
          const qk = skuQuotaKey(p.id, wid, it.color_id, it.size_id)
          const q = dispatchQuota[qk]
          const row: any = {
            worker_id: wid,
            color_id: it.color_id,
            size_id: it.size_id,
            quota_qty: q === undefined || q === null || Number.isNaN(Number(q)) ? null : Number(q),
          }
          if (isGroup) row.share_weight = weightOf(qk) ?? 1
          assignments.push(row)
        }
      }
    } else if (mode === 'bundle') {
      for (const u of orderTraceUnits.value) {
        const ids = dispatchBundleMap[bundleMapKey(p.id, u.id)] || []
        for (const wid of ids) {
          const qk = bundleQuotaKey(p.id, wid, u.id)
          const q = dispatchQuota[qk]
          const row: any = {
            worker_id: wid,
            trace_unit_id: u.id,
            quota_qty: q === undefined || q === null || Number.isNaN(Number(q)) ? null : Number(q),
          }
          if (isGroup) row.share_weight = weightOf(qk) ?? 1
          assignments.push(row)
        }
      }
    } else {
      const ids = dispatchMap[p.id] || []
      assignments = ids.map((wid) => {
        const qk = quotaKey(p.id, wid)
        const q = dispatchQuota[qk]
        const row: any = {
          worker_id: wid,
          quota_qty: q === undefined || q === null || Number.isNaN(Number(q)) ? null : Number(q),
        }
        if (isGroup) row.share_weight = weightOf(qk) ?? 1
        return row
      })
    }
    await http.patch(`/orders/${dispatchOrder.value.id}/processes/${p.id}`, { assignments })
    ElMessage.success(`${p.process_name}派工已保存`)
    dispatchVisible.value = false
    await load()
    if (detailOrder.value?.id === dispatchOrder.value.id) {
      const res: any = await http.get(`/orders/${dispatchOrder.value.id}`)
      detailOrder.value = res.data
      dispatchOrder.value = JSON.parse(JSON.stringify(res.data))
    } else {
      const updated = rows.value.find((r) => r.id === dispatchOrder.value.id)
      if (updated) dispatchOrder.value = JSON.parse(JSON.stringify(updated))
    }
    dispatchPickVisible.value = true
    dispatchProcess.value = null
  } finally {
    dispatchSaving.value = false
  }
}

async function save() {
  const name =
    form.customer_name ||
    customers.value.find((c) => c.id === form.customer_id)?.name ||
    ''
  if ((!form.customer_id && !name) || !form.own_product_id || !form.items.length) {
    ElMessage.warning('请填写客户、产品和明细')
    return
  }
  await http.post('/orders', {
    order_no: form.order_no || undefined,
    customer_id: form.customer_id || null,
    customer_name: name || null,
    own_product_id: form.own_product_id,
    delivery_date: form.delivery_date || null,
    notes: form.notes || null,
    is_rush: !!form.is_rush,
    rush_reason: form.is_rush ? form.rush_reason || null : null,
    items: form.items.map((i: any) => ({
      color_id: i.color_id,
      size_id: i.size_id,
      qty: i.qty,
    })),
  })
  ElMessage.success('已创建')
  visible.value = false
  await load()
}

function onRowMore(row: any, cmd: string) {
  if (cmd === 'toggle-rush') {
    void toggleRush(row)
    return
  }
  if (cmd.startsWith('status:')) {
    void changeStatus(row, cmd.slice('status:'.length))
  }
}

async function toggleRush(row: any) {
  const next = !row.is_rush
  let rush_reason: string | null = row.rush_reason || null
  if (next) {
    try {
      const { value } = await ElMessageBox.prompt('加急原因（可选）', '标为急单/插单', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputPlaceholder: '如：客户催货',
        inputValue: rush_reason || '',
      })
      rush_reason = (value || '').trim() || null
    } catch {
      return
    }
  }
  await http.patch(`/orders/${row.id}`, {
    is_rush: next,
    rush_reason: next ? rush_reason : null,
  })
  ElMessage.success(next ? '已标为急单' : '已取消急单')
  await load()
  if (detailOrder.value?.id === row.id) {
    detailOrder.value = { ...detailOrder.value, is_rush: next, rush_reason: next ? rush_reason : null }
  }
}

async function changeStatus(row: any, status: string) {
  await http.patch(`/orders/${row.id}`, { status })
  ElMessage.success('状态已更新')
  await load()
}

onMounted(async () => {
  const [s, c, z, w, cust]: any[] = await Promise.all([
    http.get('/own-products', { params: { page_size: 200 } }),
    http.get('/colors'),
    http.get('/sizes'),
    http.get('/workers', { params: { page_size: 200 } }),
    http.get('/partners', { params: { role: 'customer_brand', page_size: 200 } }),
  ])
  products.value = s.data.items
  colors.value = c.data.items
  sizes.value = z.data.items
  workers.value = w.data.items.filter((x: any) => x.is_active)
  customers.value = cust.data.items
  await load()
  const openId = Number(route.query.open)
  if (openId > 0) {
    let row = rows.value.find((r) => r.id === openId)
    if (!row) {
      try {
        const res: any = await http.get(`/orders/${openId}`)
        row = res.data
      } catch {
        /* ignore */
      }
    }
    if (row) {
      await openDetail(row)
      detailTab.value = 'materials'
    }
  }
})
</script>

<style scoped>
.progress-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.3;
}
.bottleneck-name {
  color: #c45c26;
  font-weight: 600;
}
:deep(.rush-row) {
  --el-table-tr-bg-color: #fff5f2;
}
:deep(.rush-row td.el-table__cell) {
  background-color: #fff5f2 !important;
}
:deep(.rush-row:hover td.el-table__cell),
:deep(.rush-row.hover-row td.el-table__cell) {
  background-color: #ffd4c8 !important;
}
.order-detail-tabs {
  margin-bottom: 8px;
}
.materials-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.materials-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.materials-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.mat-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
}
.mat-thumb :deep(.el-image__inner) {
  border-radius: 4px;
}
.mat-thumb-sm {
  width: 28px;
  height: 28px;
  border-radius: 4px;
  flex-shrink: 0;
  background: #f8fafc;
}
.mat-thumb-sm :deep(.el-image__inner) {
  border-radius: 4px;
}
.mat-thumb-empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 11px;
}
.doc-line-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0;
}
.mat-progress {
  font-size: 12px;
  line-height: 1.45;
  color: var(--el-text-color-regular);
}
.mat-timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 16px 0 8px;
}
.mat-name {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.3;
}
.mat-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.35;
  margin-top: 2px;
}
.order-detail-actions {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  text-align: right;
}
/* 与色码明细 el-table 一致的圆角描边 / 表头 / 单元格 */
.detail-kv-table :deep(.el-descriptions__body) {
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow:
    0 0 0 1px rgba(15, 23, 42, 0.06),
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 24px rgba(15, 23, 42, 0.04);
}
.detail-kv-table :deep(.el-descriptions__table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.detail-kv-table :deep(.el-descriptions__cell) {
  border: 1px solid #dce3ed !important;
  padding: 13px 14px !important;
  line-height: 1.45;
}
.detail-kv-table :deep(.el-descriptions__label) {
  background: #f7f9fc !important;
  color: #64748b !important;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.04em;
  width: 96px;
}
.detail-kv-table :deep(.el-descriptions__content) {
  background: #fff !important;
  color: #1f2937 !important;
  font-size: 13px;
  font-weight: 400;
}
.detail-kv-table.is-bordered :deep(.el-descriptions__cell),
.detail-kv-table :deep(.is-bordered-label),
.detail-kv-table :deep(.is-bordered-content) {
  border-color: #dce3ed !important;
}
</style>
