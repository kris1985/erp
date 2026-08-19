<template>
  <div class="schedule-page">
    <header class="page-hero schedule-hero">
      <div class="page-hero-copy">
        <h1 class="page-title">排产</h1>
        <p class="page-desc">待排上图，确认后才下发生产单。</p>
      </div>
    </header>

    <div class="admin-card schedule-workbench">
    <div v-if="legacyMode" class="schedule-stage-bar">
      <button
        type="button"
        class="schedule-stage"
        :class="{ 'is-on': mainTab === 'color' }"
        @click="goWorkbench('color')"
      >
        排产
        <span class="schedule-stage-n">待排 {{ colorRows.length }}</span>
      </button>
      <div class="schedule-stage-more">
        <el-button text :type="mainTab === 'pool' ? 'primary' : undefined" @click="goWorkbench('pool')">
          旧版倒排
        </el-button>
        <el-button text :type="mainTab === 'weekly' ? 'primary' : undefined" @click="goWorkbench('weekly')">
          周负荷
        </el-button>
        <el-button text :type="mainTab === 'calendar' ? 'primary' : undefined" @click="goWorkbench('calendar')">
          日历
        </el-button>
      </div>
    </div>

    <el-tabs v-model="mainTab" class="schedule-inner-tabs" @tab-change="onTabChange">
      <el-tab-pane label="待排款" name="color">
        <div class="schedule-panel color-board">
          <div v-if="colorPlanDraft" class="gantt-toolbar">
            <div class="strategy-seg">
              <button
                v-for="p in colorPlanDraft.proposals || []"
                :key="p.strategy"
                type="button"
                :class="{ 'is-on': colorPlanDraft.strategy === p.strategy }"
                @click="selectColorStrategy(p.strategy)"
              >
                {{ p.title || p.strategy }}
                <span v-if="colorPlanDraft.recommended_strategy === p.strategy" class="n">建议</span>
              </button>
            </div>
            <div class="color-plan-actions">
              <el-button size="small" @click="discardColorPlan">取消</el-button>
              <el-button
                type="primary"
                size="small"
                :loading="colorConfirming"
                :disabled="!colorPlanDraft.jobs?.length"
                @click="openConfirmProduction"
              >
                确认排产
              </el-button>
            </div>
          </div>
          <p v-if="colorPlanAlert.text" class="gantt-alert" :class="'is-' + colorPlanAlert.tone">
            {{ colorPlanAlert.text }}
          </p>
          <div class="gantt-nav">
            <button type="button" class="gantt-nav-chevron" aria-label="上一周" @click="shiftGanttDays(-7)">
              ‹
            </button>
            <el-dropdown trigger="click" @command="onGanttNav">
              <button type="button" class="gantt-nav-range">{{ ganttRangeLabel }}</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="week-">上一周</el-dropdown-item>
                  <el-dropdown-item command="week+">下一周</el-dropdown-item>
                  <el-dropdown-item command="month-">上一月</el-dropdown-item>
                  <el-dropdown-item command="month+">下一月</el-dropdown-item>
                  <el-dropdown-item command="today" :disabled="ganttAtDefault">今天</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <button type="button" class="gantt-nav-chevron" aria-label="下一周" @click="shiftGanttDays(7)">
              ›
            </button>
            <el-button size="small" :disabled="ganttAtDefault" @click="resetGanttRange">今天</el-button>
            <el-button size="small" :icon="Setting" @click="openSettings">计划设置</el-button>
            <span v-if="settingsHint" class="gantt-settings-hint">{{ settingsHint }}</span>
          </div>
          <div class="gantt-host">
            <ScheduleGanttBoard
              fill
              :workdays="ganttWorkdays"
              :rows="ganttRows"
              :load="colorActiveProposal?.load || []"
              :loading="ganttLoading || colorShifting"
              :lookback-days="settingsForm.actual_capacity_lookback_days || 7"
              @open-header="openIssuedHeader"
              @shift-job="shiftColorJob"
              @shift-issued="shiftIssuedJob"
              @insert-rush="openGanttRush"
              @reschedule="openReschedule"
              @pick-pending="openColorPool"
              @drop-source="dropDraftSource"
              @edit-window="openProcessWindowEditor"
            />
            <button
              v-show="!colorPoolOpen"
              type="button"
              class="color-pool-fab"
              @click="openColorPool"
            >
              待排 {{ colorRows.length }}
              <span v-if="colorSelectedQty"> · 已选 {{ colorSelectedQty }}双</span>
            </button>
            <div
              v-if="colorPoolOpen"
              class="color-pool-scrim"
              @click="closeColorPool"
            />
            <div v-show="colorPoolOpen" class="color-pool-overlay">
              <div class="color-pool-bar">
                <button type="button" class="color-pool-toggle" @click="closeColorPool">
                  待排 {{ colorRows.length }}
                  <span v-if="colorSelectedQty"> · 已选 {{ colorSelectedQty }}双</span>
                  <span class="muted">收起</span>
                </button>
                <el-button
                  type="primary"
                  size="small"
                  :disabled="!colorSelected.length"
                  :loading="colorProposing"
                  @click="proposeColorPlan"
                >
                  出方案{{ colorSelectedQty ? `（${colorSelectedQty} 双）` : '' }}
                </el-button>
              </div>
              <div class="color-pool-body">
          <div class="admin-toolbar">
            <el-input
              v-model="colorKeyword"
              clearable
              placeholder="款号/销售单/客户"
              style="width: 200px"
            />
            <el-checkbox v-model="colorKitReadyOnly" @change="loadColorPool">仅齐套</el-checkbox>
            <el-checkbox v-model="colorAsRush">作为急单</el-checkbox>
            <el-button :loading="colorPoolLoading" @click="loadColorPool">刷新</el-button>
          </div>

          <div class="color-pool-table">
            <el-table
              ref="colorTableRef"
              v-loading="colorPoolLoading"
              :data="colorRows"
              border
              stripe
              row-key="key"
              :max-height="'calc(45vh - 148px)'"
              empty-text="暂无待排款"
              :row-class-name="colorRowClassName"
              @selection-change="onColorSelectionChange"
              @header-dragend="onColorHeaderDragend"
            >
              <el-table-column type="selection" width="48" align="center" />
              <el-table-column
                prop="product_code"
                label="款号"
                :width="colorColWidth('product_code', 120)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                column-key="product_image"
                label="图片"
                :width="colorColWidth('product_image', 72)"
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
                    preview-teleported
                    fit="contain"
                    class="product-thumb"
                  />
                  <span v-else class="muted mat-image-empty"></span>
                </template>
              </el-table-column>
              <el-table-column
                prop="color_name"
                label="颜色"
                :width="colorColWidth('color_name', 72)"
                resizable
              >
                <template #default="{ row }">{{ row.color_name || '—' }}</template>
              </el-table-column>
              <el-table-column
                prop="sales_order_nos"
                label="销售单"
                :width="colorColWidth('sales_order_nos', 160)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                prop="customer_names"
                label="客户"
                :width="colorColWidth('customer_names', 120)"
                show-overflow-tooltip
                resizable
              />
              <el-table-column
                prop="remaining_qty"
                label="数量"
                :width="colorColWidth('remaining_qty', 72)"
                align="right"
                resizable
              />
              <el-table-column
                prop="earliest_delivery"
                label="最早交期"
                :width="colorColWidth('earliest_delivery', 110)"
                resizable
              />
              <el-table-column
                column-key="kit_hint"
                label="齐套"
                :width="colorColWidth('kit_hint', 80)"
                resizable
              >
                <template #default="{ row }">
                  <el-tag size="small" :type="kitTagType(row.kit_hint)">{{ kitHintLabel(row.kit_hint) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="legacyMode" label="旧版倒排" name="pool">
        <div class="schedule-panel">
        <p class="muted tip" style="margin: 0 0 12px">
          给已下发生产单改工序日。日常排产请用「待排款」出方案。
        </p>
        <div class="admin-toolbar">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="单号/客户/产品"
            style="width: 200px"
            @clear="onFilterChange"
            @keyup.enter="onFilterChange"
          />
          <el-checkbox v-model="filters.rush_only" @change="onFilterChange">仅急单</el-checkbox>
          <el-checkbox v-model="filters.hide_first_kit_blocked" @change="onFilterChange">隐藏首道缺料</el-checkbox>
          <el-checkbox v-model="filters.show_scheduled" @change="onFilterChange">显示已排</el-checkbox>
          <el-select
            v-model="filters.merge_batch_id"
            clearable
            filterable
            placeholder="按合批筛选"
            style="width: 180px"
            @change="onFilterChange"
          >
            <el-option
              v-for="b in mergeBatchOptions"
              :key="b.id"
              :label="`${b.batch_no} · ${b.member_count || 0}单`"
              :value="b.id"
            />
          </el-select>
          <el-button @click="loadPool">刷新</el-button>
          <el-button @click="openDraftPicker">未确认草稿（{{ draftList.length }}）</el-button>
          <el-button :loading="proposing" @click="generateProposals">
            重算已下发{{ selectedIds.length || selectedHeaderIds.length ? `（${selectedIds.length + selectedHeaderIds.length}）` : '' }}
          </el-button>
          <el-button
            :loading="creating"
            :disabled="!selectedIds.length && !selectedHeaderIds.length"
            @click="createDraft"
          >
            生成倒排草稿（{{ selectedIds.length + selectedHeaderIds.length }}）
          </el-button>
          <el-button type="primary" plain @click="goAssistant">车间军师</el-button>
          <el-button :loading="mergeSuggestLoading" @click="openMergeSuggest">合批推荐</el-button>
          <el-button @click="openSettings">计划设置</el-button>
        </div>

        <div ref="tableHostRef">
          <el-table
            ref="tableRef"
            v-loading="loading"
            :data="pool"
            border
            stripe
            :max-height="tableMaxHeight"
            @selection-change="onSelect"
            @header-dragend="onHeaderDragend"
          >
            <el-table-column type="selection" width="48" />
            <el-table-column column-key="order_no" label="单号" :width="colWidth('order_no', 140)" show-overflow-tooltip resizable>
              <template #default="{ row }">
                <template v-if="row.header_id && !row.order_id">
                  <el-tag size="small" type="info" effect="plain" style="margin-right: 4px">生产单</el-tag>
                  {{ row.header_no || row.order_no }}
                </template>
                <template v-else>{{ row.order_no }}</template>
              </template>
            </el-table-column>
            <el-table-column prop="merge_batch_no" label="合批" :width="colWidth('merge_batch_no', 120)" resizable>
              <template #default="{ row }">
                <span v-if="row.merge_batch_no">{{ row.merge_batch_no }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column
              column-key="product_image"
              label="图片"
              :width="colWidth('product_image', 72)"
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
                  preview-teleported
                  fit="contain"
                  class="product-thumb"
                />
                <span v-else class="muted mat-image-empty"></span>
              </template>
            </el-table-column>
            <el-table-column prop="product_code" label="产品" :width="colWidth('product_code', 120)" resizable>
              <template #default="{ row }">{{ row.product_code || '—' }}</template>
            </el-table-column>
            <el-table-column
              prop="customer_name"
              label="客户"
              :min-width="flexColMinWidth('customer_name', 100)"
              resizable
            />
            <el-table-column prop="total_qty" label="数量" :width="colWidth('total_qty', 72)" align="right" resizable />
            <el-table-column prop="delivery_date" label="交期" :width="colWidth('delivery_date', 110)" resizable />
            <el-table-column column-key="rush" label="急" :width="colWidth('rush', 56)" align="center" resizable>
              <template #default="{ row }">
                <el-tag v-if="row.is_rush" type="danger" size="small">急</el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column column-key="kit" label="齐套" :width="colWidth('kit', 120)" resizable>
              <template #default="{ row }">
                <el-tag :type="row.kit_ok ? 'success' : 'danger'" size="small" effect="plain">
                  整单{{ row.kit_ok ? '齐' : '缺' }}
                </el-tag>
                <el-tag
                  :type="row.first_kit_ok ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                  style="margin-left: 4px"
                >
                  首道{{ row.first_kit_ok ? '齐' : '缺' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column column-key="sched" label="排产" :width="colWidth('sched', 90)" resizable>
              <template #default="{ row }">
                {{ scheduleLabel(row.schedule_status) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="admin-pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="poolTotal"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="loadPool"
            @size-change="onPageSizeChange"
          />
        </div>
        </div>

        <el-dialog v-model="draftPickerVisible" title="未确认草稿" width="640px" destroy-on-close>
          <el-table
            v-loading="draftListLoading"
            :data="draftList"
            border
            stripe
            size="small"
            empty-text="暂无未确认草稿"
            max-height="420"
          >
            <el-table-column prop="id" label="#" width="70" />
            <el-table-column column-key="summary" label="内容" min-width="180">
              <template #default="{ row }">
                {{ row.order_count || 0 }} 单 · {{ row.included_count || row.line_count || 0 }} 道工序
                <span v-if="row.assigned_line_count" class="muted">
                  · 已建议派 {{ row.assigned_line_count }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建" width="170">
              <template #default="{ row }">{{ formatDt(row.created_at) }}</template>
            </el-table-column>
            <el-table-column column-key="actions" label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDraft(row.id)">打开</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-dialog>

        <el-dialog v-model="proposalVisible" title="智能排产方案（规则引擎）" width="920px" destroy-on-close>
          <p class="muted" style="margin: 0 0 8px; font-size: 12px">
            方案由确定性规则生成；采用后进入草稿，仍须人工确认才写日期/派工。
          </p>
          <p v-if="proposalScopeNote" class="proposal-scope">{{ proposalScopeNote }}</p>
          <p v-if="proposalRecommend.text" class="proposal-recommend" :class="{ 'is-tie': proposalRecommend.tie }">
            {{ proposalRecommend.text }}
          </p>
          <p v-if="proposalDiffHint" class="proposal-diff-hint">{{ proposalDiffHint }}</p>
          <div v-loading="proposing" class="proposal-grid">
            <div
              v-for="p in proposals"
              :key="p.proposal_id"
              class="proposal-card"
              :class="{ 'is-recommended': proposalRecommend.id === p.proposal_id }"
            >
              <div class="proposal-head">
                <strong>{{ p.title }}</strong>
                <div class="proposal-head-tags">
                  <el-tag
                    v-if="proposalRecommend.id === p.proposal_id"
                    size="small"
                    type="success"
                    effect="dark"
                  >
                    建议
                  </el-tag>
                  <el-tag size="small" effect="plain">{{ p.strategy }}</el-tag>
                </div>
              </div>
              <div class="proposal-compare">
                <div class="proposal-compare-item">
                  <span class="proposal-compare-label">预计逾期</span>
                  <strong
                    class="proposal-compare-value"
                    :class="{ 'is-bad': proposalHeadline(p).lateCount > 0 }"
                  >
                    {{ proposalHeadline(p).lateCount }}
                  </strong>
                  <span v-if="lateSample(p).text" class="proposal-compare-sub">{{ lateSample(p).text }}</span>
                </div>
                <div class="proposal-compare-item">
                  <span class="proposal-compare-label">产能冲突</span>
                  <strong
                    class="proposal-compare-value"
                    :class="{ 'is-bad': proposalHeadline(p).capacityCount > 0 }"
                  >
                    {{ proposalHeadline(p).capacityCount }}
                  </strong>
                </div>
                <div class="proposal-compare-item">
                  <span class="proposal-compare-label">负荷峰</span>
                  <strong
                    class="proposal-compare-value"
                    :class="{ 'is-bad': (proposalHeadline(p).peakUtilPct || 0) > 100 }"
                  >
                    {{ proposalHeadline(p).peakUtilPct != null ? proposalHeadline(p).peakUtilPct + '%' : '—' }}
                  </strong>
                  <span v-if="proposalHeadline(p).peakUtilPct != null" class="proposal-compare-sub">
                    {{ proposalHeadline(p).peakLabel }}
                    <template v-if="proposalHeadline(p).overDays">
                      · 超产 {{ proposalHeadline(p).overDays }} 天
                    </template>
                  </span>
                </div>
              </div>
              <div class="proposal-spark">
                <span
                  v-for="(bar, bi) in proposalSpark(p)"
                  :key="bi"
                  class="proposal-spark-cell"
                >
                  <el-tooltip :content="bar.label" placement="top" :show-after="200">
                    <span
                      class="proposal-spark-bar"
                      :class="bar.tone"
                      :style="{ height: bar.height + '%' }"
                    />
                  </el-tooltip>
                </span>
              </div>
              <p class="proposal-spark-legend">近两周日负荷峰 · 绿&lt;85% · 黄&lt;100% · 红超产</p>
              <p class="proposal-summary">{{ proposalSummaryShort(p) }}</p>
              <div v-if="(p.skipped_kit_order_nos || []).length" class="proposal-skip">
                <button type="button" class="proposal-skip-toggle" @click="toggleSkipKit(p.proposal_id)">
                  待料未排 {{ p.skipped_kit_order_nos.length }} 单
                  {{ skipKitOpen[p.proposal_id] ? '▴' : '▾' }}
                </button>
                <div v-if="skipKitOpen[p.proposal_id]" class="proposal-skip-list">
                  {{ p.skipped_kit_order_nos.join('、') }}
                </div>
              </div>
              <div class="proposal-risks">
                <el-tag size="small" type="success">余量 {{ p.risks?.ok || 0 }}</el-tag>
                <el-tag size="small" type="warning">偏紧 {{ p.risks?.tight || 0 }}</el-tag>
                <el-tag size="small" type="danger">逾期 {{ p.risks?.late || 0 }}</el-tag>
                <el-tag size="small">产能冲突 {{ p.risks?.capacity_blocked || 0 }}</el-tag>
                <el-tag size="small">缺料 {{ p.risks?.kit_blocked || 0 }}</el-tag>
              </div>
              <div class="proposal-actions">
                <el-button type="primary" size="small" :loading="adopting" @click="adoptProposal(p)">
                  {{ proposalRecommend.id === p.proposal_id ? '采用建议' : '采用进草稿' }}
                </el-button>
              </div>
            </div>
            <el-empty v-if="!proposing && !proposals.length" description="暂无方案" />
          </div>
        </el-dialog>

        <el-drawer
          v-model="draftDrawerVisible"
          :title="draft ? `排产草稿 #${draft.id}` : '排产草稿'"
          size="86%"
          destroy-on-close
          @opened="onDraftDrawerOpened"
          @closed="onDraftDrawerClosed"
        >
          <template v-if="draft">
            <div class="admin-toolbar" style="margin-bottom: 8px">
              <el-tag size="small">{{ draft.status }}</el-tag>
              <span class="muted" style="font-size: 12px">
                勾选「纳入」可分段；确认后写开工/完工日，有派工建议则一并落派工
              </span>
              <div style="flex: 1" />
              <el-tag v-if="unassignedCount > 0" type="danger" size="small">
                {{ unassignedCount }} 道工序未派工
              </el-tag>
              <el-button
                v-if="draft.status === 'draft'"
                :loading="saving"
                @click="suggestAssignments"
              >
                重算派工建议
              </el-button>
              <el-button v-if="draft.status === 'draft'" :loading="saving" @click="discardDraft">作废</el-button>
              <el-button
                v-if="draft.status === 'draft'"
                type="primary"
                :loading="saving"
                @click="confirmDraft"
              >
                确认排产
              </el-button>
            </div>
            <div v-if="draftSummary.text" class="draft-summary" :class="{ 'is-warn': draftSummary.warn }">
              <span>{{ draftSummary.text }}</span>
              <el-button link type="primary" @click="goWeeklyFromDraft">查看周负荷</el-button>
            </div>
            <el-table
              ref="draftTableRef"
              :data="draft.lines || []"
              border
              stripe
              size="small"
              style="width: 100%"
              @header-dragend="onHeaderDragend1"
            >
              <el-table-column
                column-key="included"
                label="纳入"
                :width="colWidth1('included', 64)"
                align="center"
                resizable
              >
                <template #default="{ row }">
                  <el-checkbox
                    :model-value="row.included"
                    :disabled="draft.status !== 'draft'"
                    @change="(v: boolean) => patchLine(row, { included: v })"
                  />
                </template>
              </el-table-column>
              <el-table-column column-key="order_no" label="生产单" :width="colWidth1('order_no', 128)" resizable>
                <template #default="{ row }">
                  <div class="draft-order-cell">
                    <span>
                      {{ row.header_no || row.order_no || '—' }}
                      <el-tag v-if="row.is_rush" size="small" type="danger" effect="plain" style="margin-left: 4px">
                        急
                      </el-tag>
                    </span>
                    <span class="draft-order-delivery">
                      交期 {{ row.delivery_date ? shortDate(row.delivery_date) : '—' }}
                      <template v-if="orderLateHint(row)"> · {{ orderLateHint(row) }}</template>
                    </span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="product_code" label="产品" :width="colWidth1('product_code', 100)" resizable>
                <template #default="{ row }">{{ row.product_code || '—' }}</template>
              </el-table-column>
              <el-table-column prop="process_name" label="工序" :width="colWidth1('process_name', 100)" resizable>
                <template #default="{ row }">
                  {{ row.process_name }}
                  <el-tag v-if="row.is_first" size="small" type="warning" style="margin-left: 4px">首道</el-tag>
                  <el-tag
                    v-if="row.process_type === 'group'"
                    size="small"
                    type="info"
                    style="margin-left: 4px"
                  >
                    集体
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="plan_qty" label="数量" :width="colWidth1('plan_qty', 72)" align="right" resizable />
              <el-table-column
                column-key="assignments"
                label="派工建议"
                :width="colWidth1('assignments', 140)"
                resizable
              >
                <template #default="{ row }">
                  <div class="assign-cell">
                    <template v-if="(row.assignments || []).length">
                      <button
                        type="button"
                        class="assign-fold-toggle"
                        @click="toggleAssignExpand(row.id)"
                      >
                        <template v-if="row.team_name">
                          {{ row.team_name }}
                          <template v-if="row.team_assign_mode === 'leader'"> · 组长</template>
                          <template v-else> · {{ row.assignments.length }} 人</template>
                        </template>
                        <template v-else>已建议 {{ row.assignments.length }} 人</template>
                        {{ assignExpanded[row.id] ? '▴' : '▾' }}
                      </button>
                      <div v-if="assignExpanded[row.id]" class="assign-fold-list">
                        <el-tag
                          v-for="a in row.assignments"
                          :key="a.id || a.worker_id"
                          size="small"
                          class="assign-tag"
                        >
                          {{ a.worker_name || a.worker_id }}
                          <span v-if="a.quota_qty != null"> · {{ a.quota_qty }}</span>
                        </el-tag>
                      </div>
                    </template>
                    <span v-else class="muted">未派</span>
                    <el-button
                      v-if="draft.status === 'draft'"
                      link
                      :type="(row.assignments || []).length ? 'primary' : 'primary'"
                      :class="{ 'assign-btn-unset': !(row.assignments || []).length }"
                      @click="openAssign(row)"
                    >
                      {{ (row.assignments || []).length ? '编辑' : '＋ 派工' }}
                    </el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column column-key="start_date" label="开工" :width="colWidth1('start_date', 140)" resizable>
                <template #default="{ row }">
                  <el-date-picker
                    v-if="draft.status === 'draft'"
                    :model-value="row.start_date"
                    type="date"
                    value-format="YYYY-MM-DD"
                    style="width: 100%"
                    @update:model-value="(v: string) => patchLine(row, { start_date: v })"
                  />
                  <span v-else>{{ row.start_date || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column column-key="end_date" label="完工" :width="colWidth1('end_date', 140)" resizable>
                <template #default="{ row }">
                  <el-date-picker
                    v-if="draft.status === 'draft'"
                    :model-value="row.end_date"
                    type="date"
                    value-format="YYYY-MM-DD"
                    style="width: 100%"
                    @update:model-value="(v: string) => patchLine(row, { end_date: v })"
                  />
                  <span v-else>{{ row.end_date || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column column-key="kit" label="齐套" :width="colWidth1('kit', 72)" resizable>
                <template #default="{ row }">
                  <el-tag :type="row.process_kit_ok ? 'success' : 'danger'" size="small" effect="plain">
                    {{ row.process_kit_ok ? '齐' : '缺' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-drawer>

        <el-dialog
          v-model="assignVisible"
          :title="assignLine ? `派工 · ${assignLine.process_name}` : '派工'"
          width="520px"
          destroy-on-close
          append-to-body
        >
          <p class="muted" style="margin: 0 0 12px">
            计划 {{ assignLine?.plan_qty || 0 }} 双 · 可派班组（展开为成员）或直接选人；色码/捆请确认后在订单里改
          </p>
          <div class="assign-team-row">
            <el-select
              v-model="assignTeamId"
              clearable
              filterable
              placeholder="选班组（可选）"
              style="flex: 1"
              @change="onAssignTeamChange"
            >
              <el-option
                v-for="t in teams"
                :key="t.id"
                :label="`${t.name}（${t.member_count || (t.members || []).length}人）`"
                :value="t.id"
              />
            </el-select>
            <el-radio-group v-model="assignTeamMode" size="small" :disabled="!assignTeamId" @change="onAssignTeamChange">
              <el-radio-button value="members">整班</el-radio-button>
              <el-radio-button value="leader">仅组长</el-radio-button>
            </el-radio-group>
          </div>
          <el-select
            v-model="assignWorkerIds"
            multiple
            filterable
            style="width: 100%; margin-top: 10px"
            placeholder="选择工人"
          >
            <el-option
              v-for="w in workers"
              :key="w.id"
              :label="w.name"
              :value="w.id"
            />
          </el-select>
          <div style="margin-top: 12px; display: flex; gap: 8px; align-items: center">
            <el-checkbox v-model="assignEqualSplit">保存时按计划数均分配额</el-checkbox>
          </div>
          <template #footer>
            <el-button @click="assignVisible = false">取消</el-button>
            <el-button @click="clearAssign">清空</el-button>
            <el-button type="primary" :loading="saving" @click="saveAssign">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <el-tab-pane v-if="legacyMode" label="周负荷" name="weekly">
        <div class="schedule-panel">
          <div class="admin-toolbar">
            <span class="muted" style="font-size: 12px">
              自然周（周一～周日）汇总；超载=任一道工序负荷&gt;产能；预警=利用率≥设置阈值
            </span>
            <div style="flex: 1" />
            <el-button :loading="weeklyLoading" @click="loadWeekly">刷新</el-button>
          </div>
          <el-table v-loading="weeklyLoading" :data="weeklyItems" border stripe empty-text="暂无负荷数据">
            <el-table-column prop="label" label="周" width="88" />
            <el-table-column label="区间" min-width="200">
              <template #default="{ row }">{{ row.week_start }} ~ {{ row.week_end }}</template>
            </el-table-column>
            <el-table-column prop="over_days" label="超载天" width="88" align="right">
              <template #default="{ row }">
                <span :class="{ 'is-bad-num': row.over_days > 0 }">{{ row.over_days }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="warn_days" label="预警天" width="88" align="right" />
            <el-table-column label="峰利用率" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.peak_utilization != null">{{ Math.round(row.peak_utilization * 100) }}%</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="超载工序" min-width="160">
              <template #default="{ row }">
                <span v-if="row.over_process_names?.length">{{ row.over_process_names.join('、') }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
          <p v-if="weeklyHeadline" class="weekly-headline">{{ weeklyHeadline }}</p>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="legacyMode" label="计划日历" name="calendar">
        <div class="schedule-panel">
        <div class="admin-toolbar">
          <el-button @click="shiftMonth(-1)">上一月</el-button>
          <el-button @click="goThisMonth">本月</el-button>
          <el-button @click="shiftMonth(1)">下一月</el-button>
          <strong style="margin-left: 8px">{{ monthLabel }}</strong>
          <div style="flex: 1" />
          <span class="cal-legend">
            <span class="cal-leg holiday">节假日</span>
            <span class="cal-leg off">周末休</span>
            <span class="cal-leg makeup">调休班</span>
          </span>
          <span class="muted" style="font-size: 12px; margin-left: 8px">只读 · 点击工序打开生产单</span>
          <el-button :loading="calLoading" @click="loadCalendar">刷新</el-button>
        </div>

        <div v-loading="calLoading" class="cal-month">
          <div class="cal-dow" v-for="w in WEEKDAY" :key="w">周{{ w }}</div>
          <div
            v-for="day in monthDays"
            :key="day.key"
            class="cal-cell"
            :class="{
              'is-today': day.isToday,
              'is-other': !day.inMonth,
              'is-off': day.isOff,
              'is-holiday': day.isHoliday,
              'is-makeup': day.isMakeup,
            }"
          >
            <div class="cal-cell-head">
              <strong class="cal-date">{{ day.dayNum }}</strong>
              <span v-if="day.label" class="cal-badge" :class="{ holiday: day.isHoliday, makeup: day.isMakeup }">
                {{ day.label }}
              </span>
              <span v-if="day.items.length" class="cal-count">{{ day.items.length }}</span>
            </div>
            <div class="cal-cell-body">
              <button
                v-for="it in day.items.slice(0, 4)"
                :key="`${it.order_process_id}-${day.key}`"
                type="button"
                class="cal-chip"
                :class="{ rush: it.is_rush }"
                :title="`${it.process_name} · ${it.order_no} · ${it.product_code || ''} · ${it.plan_qty}双`"
                @click="openOrder(it.order_id)"
              >
                <span class="cal-chip-name">{{ it.process_name }}</span>
                <span class="cal-chip-meta">{{ it.order_no }}</span>
              </button>
              <div v-if="day.items.length > 4" class="cal-more">+{{ day.items.length - 4 }}</div>
            </div>
          </div>
        </div>
        </div>
      </el-tab-pane>
    </el-tabs>
    </div>

    <!-- 未配产能补填（排产页内联，不跳转） -->
    <el-dialog v-model="capacityFillVisible" title="补齐工序单人日产能" width="560px">
      <p class="muted" style="margin: 0 0 12px">
        以下工序未配置单人日产能，无法排产。请直接在这里填写（无需跳转工序管理）：
      </p>
      <el-table :data="capacityMissingRows" border stripe size="small" max-height="360">
        <el-table-column prop="name" label="工序" min-width="120" />
        <el-table-column prop="type" label="类型" width="70">
          <template #default="{ row }">{{ row.type === 'group' ? '集体' : '个人' }}</template>
        </el-table-column>
        <el-table-column label="单人日产能（双/人/天）" width="170">
          <template #default="{ row }">
            <el-input-number v-model="row.per_worker_capacity" :min="1" :precision="2" size="small" style="width: 130px" />
          </template>
        </el-table-column>
        <el-table-column label="标准人力" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.standard_workers" :min="1" size="small" style="width: 90px" />
          </template>
        </el-table-column>
        <el-table-column label="可用人数覆盖(空=不覆盖)" width="180">
          <template #default="{ row }">
            <el-input-number v-model="row.current_workers" :min="1" size="small" style="width: 150px" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="capacityFillVisible = false">取消</el-button>
        <el-button type="primary" :loading="capacityFilling" @click="saveCapacityFill">保存并重新出方案</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="processEditorVisible" title="调工序（草稿）" width="420px" destroy-on-close>
      <p class="muted" style="margin: 0 0 12px">
        从哪天开始、排多少天（只动选中的这一道，其它工序不动；改完自动重算风险）。
      </p>
      <el-form label-width="90px">
        <el-form-item label="工序">
          <el-select
            v-model="processEditorForm.processId"
            style="width: 100%"
            @change="onProcessEditorSwitch"
          >
            <el-option
              v-for="w in processEditorWindows"
              :key="w.process_id"
              :label="w.process_name"
              :value="w.process_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker
            v-model="processEditorForm.startDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择开工日"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="排几天">
          <el-input-number v-model="processEditorForm.days" :min="1" :max="180" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="processEditorVisible = false">取消</el-button>
        <el-button type="primary" :loading="processEditorSaving" @click="saveProcessWindow">
          保存并重算
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="confirmProdVisible"
      title="排产方案"
      width="820px"
      destroy-on-close
    >
      <p class="muted tip" style="margin: 0 0 12px">
        按当前方案下发生产单，并写入下面的工序窗口。确认前不下发；确认后不锁料。
      </p>
      <p v-if="colorActiveProposal" class="muted tip" style="margin: 0 0 12px">
        {{ colorActiveProposal.title }} · {{ colorActiveProposal.summary }}
      </p>
      <p v-if="colorPlanDraft?.rush_impact?.warning" class="muted tip" style="margin: 0 0 12px">
        {{ colorPlanDraft.rush_impact.warning }}
      </p>
      <el-table
        v-if="colorPlanDraft?.rush_impact?.impacts?.length"
        :data="colorPlanDraft.rush_impact.impacts"
        border
        stripe
        size="small"
        max-height="180"
        style="margin-bottom: 12px"
      >
        <el-table-column prop="header_no" label="将推迟" min-width="140" />
        <el-table-column prop="product_code" label="款号" width="120" />
        <el-table-column label="推迟" width="90">
          <template #default="{ row }">{{ row.delay_workdays }} 工作日</template>
        </el-table-column>
      </el-table>
      <el-table
        v-if="colorPlanDraft?.rush_impact?.frozen?.length"
        :data="colorPlanDraft.rush_impact.frozen"
        border
        stripe
        size="small"
        max-height="140"
        style="margin-bottom: 12px"
      >
        <el-table-column prop="header_no" label="已开裁不动" min-width="140" />
        <el-table-column prop="freeze_reason" label="原因" min-width="160" />
      </el-table>
      <el-table :data="colorPlanDraft?.jobs || []" border stripe size="small" max-height="360">
        <el-table-column prop="product_code" label="款号" min-width="100" show-overflow-tooltip />
        <el-table-column prop="color_name" label="颜色" width="80" />
        <el-table-column prop="customer_name" label="客户" width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ row.customer_name || '合单' }}</template>
        </el-table-column>
        <el-table-column prop="total_qty" label="数量" width="72" align="right" />
        <el-table-column prop="delivery_date" label="交期" width="110" />
        <el-table-column label="工序窗口 · 派工" min-width="260">
          <template #default="{ row }">
            <div v-if="row.windows?.length" class="confirm-windows">
              <div v-for="(w, i) in row.windows" :key="i" class="confirm-window">
                <div class="confirm-window__line">
                  {{ w.process_name }} {{ shortDate(w.start_date) }}–{{ shortDate(w.end_date) }}
                </div>
                <div v-if="capacityNote(w)" class="confirm-window__note">
                  {{ capacityNote(w) }}
                </div>
                <el-select
                  :model-value="dispatchGet(row.key, w.process_id)"
                  multiple
                  filterable
                  size="small"
                  placeholder="选工人（确认时落派工）"
                  style="width: 100%; margin-top: 2px"
                  @update:model-value="(v: number[]) => dispatchSet(row.key, w.process_id, v)"
                >
                  <el-option v-for="wk in dispatchWorkers" :key="wk.id" :label="wk.name" :value="wk.id" />
                </el-select>
              </div>
            </div>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="风险" width="90">
          <template #default="{ row }">{{ row.risk_label || '—' }}</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="confirmProdVisible = false">取消</el-button>
        <el-button type="primary" :loading="colorConfirming" @click="submitConfirmProduction">
          确认下发
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mergeAskVisible" title="同款同色" width="560px">
      <p class="muted tip" style="margin: 0 0 12px">
        同款同色按客户分开排（暂不支持合单）。待排还有未勾的会列出来，默认不排进这次。
      </p>
      <div v-for="g in mergeAskGroups" :key="g.styleKey" class="merge-ask-block">
        <div class="merge-ask-title">{{ g.product_code }} {{ g.color_name || '' }}</div>
        <div class="merge-ask-label">已勾</div>
        <ul class="merge-ask-cust">
          <li v-for="(c, i) in g.customers" :key="i">
            {{ c.name }} {{ c.qty }}双
            <span v-if="c.order_nos" class="muted"> · {{ c.order_nos }}</span>
            <span v-if="c.delivery" class="muted"> · 交期 {{ shortDate(c.delivery) }}</span>
          </li>
        </ul>
        <template v-if="g.leftovers?.length">
          <div class="merge-ask-label is-left">待排未勾</div>
          <ul class="merge-ask-cust is-left">
            <li v-for="(c, i) in g.leftovers" :key="i">
              {{ c.name }} {{ c.qty }}双
              <span v-if="c.order_nos" class="muted"> · {{ c.order_nos }}</span>
              <span v-if="c.delivery" class="muted"> · 交期 {{ shortDate(c.delivery) }}</span>
            </li>
          </ul>
          <el-checkbox v-model="g.includeLeftover">这次也排进来</el-checkbox>
        </template>
        <p v-if="askGapDays(g) > 0" class="merge-ask-gap">交期相差 {{ askGapDays(g) }} 天</p>
      </div>
      <template #footer>
        <el-button @click="mergeAskVisible = false">取消</el-button>
        <el-button type="primary" :loading="colorProposing" @click="confirmMergeAsk">出方案</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="rescheduleVisible" title="改开裁日" width="480px" destroy-on-close>
      <p class="muted tip" style="margin: 0 0 12px">
        未开裁可以改开裁日（甘特上拖条子同样生效）：整单按工作日历重算，保持各工序相对工期。撤回后数量回到待排池，可重新出方案。已开裁请去生产单停产。
      </p>
      <p v-if="rescheduleHeaderNo" class="muted tip" style="margin: 0 0 12px">
        {{ rescheduleHeaderNo }}
      </p>
      <el-form label-width="88px">
        <el-form-item label="开裁日">
          <el-date-picker
            v-model="rescheduleCutStart"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择开裁日"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rescheduleVisible = false">取消</el-button>
        <el-button type="danger" plain :loading="rescheduleWithdrawing" @click="withdrawIssued">
          撤回待排
        </el-button>
        <el-button type="primary" :loading="rescheduleSaving" :disabled="!rescheduleCutStart" @click="confirmReschedule">
          确认改期
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ganttRushVisible" title="插急单" width="640px" destroy-on-close>
      <p class="muted tip" style="margin: 0 0 12px">
        只推迟未开裁条。已开裁日期不动。确认前不改库。
      </p>
      <p v-if="ganttRushSim?.warning" class="muted tip">{{ ganttRushSim.warning }}</p>
      <div v-loading="ganttRushLoading">
        <el-table
          v-if="ganttRushSim?.impacts?.length"
          :data="ganttRushSim.impacts"
          border
          stripe
          size="small"
        >
          <el-table-column prop="header_no" label="将推迟" min-width="140" />
          <el-table-column prop="product_code" label="款号" width="120" />
          <el-table-column label="推迟" width="100">
            <template #default="{ row }">{{ row.delay_workdays }} 工作日</template>
          </el-table-column>
        </el-table>
        <el-table
          v-if="ganttRushSim?.frozen?.length"
          :data="ganttRushSim.frozen"
          border
          stripe
          size="small"
          style="margin-top: 12px"
        >
          <el-table-column prop="header_no" label="已开裁不动" min-width="140" />
          <el-table-column prop="freeze_reason" label="原因" min-width="160" />
        </el-table>
        <el-empty v-if="ganttRushSim && !ganttRushSim.impacts?.length && !ganttRushSim.frozen?.length" description="没有可冲击的生产单" />
      </div>
      <template #footer>
        <el-button @click="ganttRushVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="ganttRushConfirming"
          :disabled="!ganttRushSim"
          @click="confirmGanttRush"
        >
          确认冲击
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mergeSuggestVisible" title="合批推荐（只读）" width="720px" destroy-on-close @open="loadMergeSuggest">
      <p class="muted" style="margin: 0 0 12px; font-size: 12px">
        合批组批已停用。以下仅供参考；生产单合单暂未开放。
        同款
        <template v-if="mergeSuggestParams.merge_require_same_color">·同色</template>
        ·交期窗 {{ mergeSuggestParams.merge_delivery_window_days }} 天 ·首道齐套。
      </p>
      <div v-loading="mergeSuggestLoading">
        <el-empty v-if="!mergeSuggestItems.length" description="暂无推荐组" />
        <div v-for="(g, idx) in mergeSuggestItems" :key="idx" class="merge-suggest-card">
          <div class="merge-suggest-head">
            <strong>{{ g.product_code || '—' }}</strong>
            <span v-if="g.color_name" class="muted">· {{ g.color_name }}</span>
            <el-tag size="small" effect="plain">{{ g.order_count }} 单 · {{ g.total_qty }} 双</el-tag>
            <span v-if="g.delivery_from" class="muted" style="margin-left: 8px; font-size: 12px">
              交期 {{ g.delivery_from }}
              <template v-if="g.delivery_to && g.delivery_to !== g.delivery_from"> ~ {{ g.delivery_to }}</template>
            </span>
          </div>
          <div class="merge-suggest-orders">
            <el-tag v-for="o in g.orders" :key="o.order_id" size="small" class="merge-suggest-tag">
              {{ o.order_no }} · {{ o.total_qty }}双
            </el-tag>
          </div>
        </div>
        <p v-if="mergeSuggestSkipped" class="muted" style="margin-top: 12px; font-size: 12px">
          已跳过：已在批 {{ mergeSuggestSkipped.already_in_batch || 0 }} · 未齐套
          {{ mergeSuggestSkipped.not_kit || 0 }} · 异色/多色 {{ mergeSuggestSkipped.color || 0 }}
        </p>
      </div>
      <template #footer>
        <el-button @click="mergeSuggestVisible = false">关闭</el-button>
        <el-button :loading="mergeSuggestLoading" @click="loadMergeSuggest">刷新</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="settingsVisible" title="计划设置" width="520px" destroy-on-close @open="loadSettings">
      <el-form label-width="140px" v-loading="settingsLoading">
        <el-form-item label="加班可排假日">
          <el-switch v-model="settingsForm.allow_schedule_on_non_workdays" />
          <span class="muted" style="margin-left: 8px">周末/法定假也可排；停工日仍跳过</span>
        </el-form-item>
        <el-form-item label="合批交期窗(天)">
          <el-input-number v-model="settingsForm.merge_delivery_window_days" :min="0" :max="60" />
        </el-form-item>
        <el-form-item label="合批须同色">
          <el-switch v-model="settingsForm.merge_require_same_color" />
        </el-form-item>
        <el-form-item label="合批最小双数">
          <el-input-number v-model="settingsForm.merge_min_qty" :min="0" :max="100000" />
        </el-form-item>
        <el-form-item label="负荷预警阈值">
          <el-input-number
            v-model="settingsForm.load_warn_utilization"
            :min="0.1"
            :max="2"
            :step="0.05"
            :precision="2"
          />
        </el-form-item>
        <el-form-item label="实测产能窗口(天)">
          <el-input-number v-model="settingsForm.actual_capacity_lookback_days" :min="0" :max="60" />
          <span class="muted" style="margin-left: 8px">按近 N 天报工实测人均×人数排；0=关闭实测按标准人力</span>
        </el-form-item>
        <el-form-item label="停工日">
          <div class="blackout-editor">
            <div v-for="(row, idx) in settingsForm.schedule_blackout_dates" :key="idx" class="blackout-row">
              <el-date-picker v-model="row.date" type="date" value-format="YYYY-MM-DD" placeholder="停工日期" style="width: 160px" />
              <el-input v-model="row.note" placeholder="原因" clearable style="width: 130px" />
              <el-button link type="danger" @click="settingsForm.schedule_blackout_dates.splice(idx, 1)">删</el-button>
            </div>
            <div class="blackout-row blackout-add-row">
              <el-button link type="primary" @click="settingsForm.schedule_blackout_dates.push({ date: '', note: '' })">
                <el-icon style="font-size: 16px; margin-right: 2px;"><Plus /></el-icon>
                添加停工日
              </el-button>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="settingsSaving" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, Plus } from '@element-plus/icons-vue'
import http from '@/api/http'
import { useTableColWidths } from '@/composables/useTableColWidths'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import ScheduleGanttBoard from '@/components/ScheduleGanttBoard.vue'
import type { GanttRow } from '@/components/ScheduleGanttBoard.vue'

const route = useRoute()
const router = useRouter()
const legacyMode = computed(() => {
  const v = String(route.query.legacy ?? '').toLowerCase()
  return v === '1' || v === 'true' || v === 'yes'
})
const tableRef = ref()
const draftTableRef = ref()
const colorTableRef = ref()
const { tableHostRef, tableMaxHeight, measureTableHeight } = useTableMaxHeight()
const { colWidth, flexColMinWidth, onHeaderDragend } = useTableColWidths('schedule-pool', tableRef, {
  flexKey: 'customer_name',
})
const { colWidth: colorColWidth, onHeaderDragend: onColorHeaderDragend } = useTableColWidths(
  'schedule-color-rows',
  colorTableRef,
  { flexKey: 'customer_names', flexDefaultMin: 120, fitToContainer: true },
)
const { colWidth: colWidth1, onHeaderDragend: onHeaderDragend1, relayoutTable: relayoutDraftTable } =
  useTableColWidths('schedule-draft', draftTableRef, {
    flexKey: 'assignments',
    flexDefaultMin: 180,
    fitToContainer: true,
  })

const mainTab = ref('color')
const loading = ref(false)
const creating = ref(false)
const proposing = ref(false)
const adopting = ref(false)
const saving = ref(false)
const calLoading = ref(false)
const weeklyLoading = ref(false)
const weeklyItems = ref<any[]>([])
const weeklyWarnUtil = ref(0.9)

// AU-I3：按款排产 HITL
const colorPoolLoading = ref(false)
const colorConfirming = ref(false)
const colorProposing = ref(false)
const colorShifting = ref(false)
const colorKitReadyOnly = ref(false)
const colorAsRush = ref(false)
const ganttRushVisible = ref(false)
const ganttRushHeaderId = ref<number | null>(null)
const ganttRushSim = ref<any | null>(null)
const ganttRushLoading = ref(false)
const ganttRushConfirming = ref(false)
const rescheduleVisible = ref(false)
const rescheduleHeaderId = ref<number | null>(null)
const rescheduleHeaderNo = ref('')
const rescheduleCutStart = ref('')
const rescheduleSaving = ref(false)
const rescheduleWithdrawing = ref(false)
const colorPoolOpen = ref(false)
const colorPoolTouched = ref(false)
const ganttLoading = ref(false)
const ganttFrom = ref('')
const ganttTo = ref('')
const ganttWorkdays = ref<{ date: string }[]>([])
const ganttIssued = ref<any[]>([])
const colorKeyword = ref('')
const colorPool = ref<any[]>([])
const colorSelection = ref<Map<number, { sales_order_line_item_id: number; qty: number }>>(new Map())
const colorSelected = computed(() => Array.from(colorSelection.value.values()))
const colorSelectedQty = computed(() =>
  colorSelected.value.reduce((sum, x) => sum + Number(x.qty || 0), 0),
)
const confirmProdVisible = ref(false)
const colorPlanDraft = ref<any | null>(null)
const colorActiveProposal = computed(() => {
  const d = colorPlanDraft.value
  if (!d) return null
  return (d.proposals || []).find((p: any) => p.strategy === d.strategy) || d.proposals?.[0] || null
})

const colorPlanAlert = computed(() => {
  const d = colorPlanDraft.value
  if (!d) return { tone: '', text: '' }
  const p = colorActiveProposal.value
  const h = p ? proposalHeadline(p) : null
  const bits: string[] = []
  if (d.plan_error) bits.push(d.plan_error)
  if (h?.lateCount) bits.push(`交期紧张 ${h.lateCount}`)
  if (h?.capacityCount) bits.push(`产能冲突 ${h.capacityCount}`)
  if (h?.overDays) bits.push(`超产 ${h.overDays} 天`)
  const kit = p?.risks?.kit_blocked || 0
  if (kit) bits.push(`缺料卡住 ${kit}`)
  if (d.rush_impact?.warning) bits.push(d.rush_impact.warning)
  if (!bits.length) return { tone: '', text: '' }
  const tone = d.plan_error || h?.lateCount || h?.capacityCount ? 'bad' : 'warn'
  return { tone, text: bits.join(' · ') }
})

const ganttRows = computed<GanttRow[]>(() => {
  const overrides = colorPlanDraft.value?.overrides || {}
  const draft: GanttRow[] = (colorPlanDraft.value?.jobs || []).map((j: any) => ({
    key: `d:${j.key || j.product_code}`,
    kind: 'draft',
    title: `${j.product_code || ''} ${j.color_name || ''}${j.customer_name ? ` · ${j.customer_name}` : ''}`.trim() || j.label || '草稿',
    subtitle: `${j.total_qty || 0}双${j.delivery_date ? ` · 交期 ${shortDate(j.delivery_date)}` : ''}`,
    kit_hint: j.kit_hint,
    risk_label: j.risk_label,
    is_rush: !!j.is_rush,
    jobKey: j.key,
    overridden: !!overrides[j.key],
    windows: j.windows || [],
    sources: j.sources || [],
  }))
  const draftImpact = colorPlanDraft.value?.rush_impact
  const rushImpact =
    ganttRushVisible.value && ganttRushSim.value ? ganttRushSim.value : draftImpact
  const issued: GanttRow[] = (ganttIssued.value || []).map((j: any) => {
    const impact = (rushImpact?.impacts || []).find(
      (x: any) => Number(x.header_id) === Number(j.header_id),
    )
    const frozen = (rushImpact?.frozen || []).find(
      (x: any) => Number(x.header_id) === Number(j.header_id),
    )
    return {
      key: j.key,
      kind: 'issued',
      title: j.header_no || `${j.product_code || ''} ${j.color_name || ''}`.trim(),
      subtitle: `${j.product_code || ''} ${j.color_name || ''} · ${j.total_qty || 0}双`.trim(),
      status: j.status,
      locked: !!j.locked || j.status === 'cut' || j.status === 'in_progress',
      is_rush: !!j.is_rush || Number(ganttRushHeaderId.value) === Number(j.header_id),
      header_id: j.header_id,
      impact: impact ? 'push' : frozen ? 'frozen' : undefined,
      previewWindows: impact?.windows || [],
      windows: j.windows || [],
    }
  })
  return [...draft, ...issued]
})

const colorFilterSalesOrderId = ref<number | null>(null)
const colorFilterSalesOrderNo = ref('')

function uniqueJoin(vals: string[]) {
  const seen = new Set<string>()
  const out: string[] = []
  for (const v of vals) {
    const s = String(v || '').trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out.join('、')
}

function worstKit(hints: string[]) {
  if (hints.includes('short')) return 'short'
  if (hints.includes('empty_bom')) return 'empty_bom'
  if (hints.length && hints.every((h) => h === 'ready')) return 'ready'
  return 'unknown'
}

function kitHintLabel(h?: string) {
  if (h === 'ready') return '齐套'
  if (h === 'short') return '缺料'
  if (h === 'empty_bom') return '无BOM'
  return '未知'
}

function kitTagType(h?: string) {
  if (h === 'ready') return 'success'
  if (h === 'short') return 'danger'
  return 'info'
}

function minDelivery(dates: string[]) {
  const vals = dates.filter(Boolean).sort()
  return vals[0] || ''
}

function customerKeyOf(name?: string, salesOrderId?: number) {
  const s = String(name || '').trim()
  if (s) return s
  const sid = Number(salesOrderId || 0)
  return sid ? `so:${sid}` : 'unknown'
}

function styleKeyOf(row: { own_product_id?: number; color_id?: number | null }) {
  return `${row.own_product_id}-${row.color_id ?? 'none'}`
}

function groupColorRows(buckets: any[]) {
  const rows = new Map<string, any>()
  for (const b of buckets) {
    const sources = Array.isArray(b.sources) ? b.sources : []
    const byCust = new Map<string, any[]>()
    if (!sources.length) {
      byCust.set('unknown', [])
    } else {
      for (const src of sources) {
        const ck = customerKeyOf(src.customer_name, src.sales_order_id)
        const bucket = byCust.get(ck) || []
        bucket.push(src)
        byCust.set(ck, bucket)
      }
    }
    for (const [ck, srcs] of byCust) {
      const custQty = srcs.length
        ? srcs.reduce((sum, x) => sum + Number(x.remaining_qty || 0), 0)
        : Number(b.remaining_qty || 0)
      if (custQty <= 0) continue
      const custName =
        srcs.find((x) => String(x.customer_name || '').trim())?.customer_name ||
        srcs[0]?.sales_order_no ||
        ck
      const key = `${b.own_product_id}-${b.color_id ?? 'none'}::${ck}`
      let row = rows.get(key)
      if (!row) {
        row = {
          key,
          own_product_id: b.own_product_id,
          product_code: b.product_code,
          product_image_url: b.product_image_url,
          color_id: b.color_id,
          color_name: b.color_name || '',
          customer_key: ck,
          remaining_qty: 0,
          sizeMap: {} as Record<number, number>,
          sizeMeta: {} as Record<number, { size_id: number; size_value: string; size_sort_order: number }>,
          sources: [] as any[],
          kitHints: [] as string[],
          deliveries: [] as string[],
          orderNos: [] as string[],
          customers: [] as string[],
        }
        rows.set(key, row)
      }
      if (!row.product_image_url && b.product_image_url) row.product_image_url = b.product_image_url
      row.remaining_qty += custQty
      const sid = Number(b.size_id)
      if (sid) {
        row.sizeMap[sid] = (row.sizeMap[sid] || 0) + custQty
        row.sizeMeta[sid] = {
          size_id: sid,
          size_value: b.size_value,
          size_sort_order: Number(b.size_sort_order || 0),
        }
      }
      row.kitHints.push(b.kit_hint)
      for (const src of srcs) {
        row.sources.push(src)
        if (src.sales_order_no) row.orderNos.push(src.sales_order_no)
        if (src.customer_name) row.customers.push(src.customer_name)
        if (src.delivery_date) row.deliveries.push(src.delivery_date)
      }
      if (custName && !row.customers.includes(custName)) row.customers.push(custName)
    }
  }
  return Array.from(rows.values())
    .map((row) => ({
      ...row,
      sales_order_nos: uniqueJoin(row.orderNos),
      customer_names: uniqueJoin(row.customers),
      earliest_delivery: minDelivery(row.deliveries),
      kit_hint: worstKit(row.kitHints),
      size_summary: Object.values(row.sizeMeta || {})
        .sort(
          (a: any, b: any) =>
            a.size_sort_order - b.size_sort_order ||
            String(a.size_value || '').localeCompare(String(b.size_value || ''), 'zh'),
        )
        .map((m: any) => `${m.size_value}×${row.sizeMap[m.size_id] || 0}`)
        .join(' '),
    }))
    .sort(
      (a, b) =>
        String(a.product_code || '').localeCompare(String(b.product_code || ''), 'zh') ||
        String(a.color_name || '').localeCompare(String(b.color_name || ''), 'zh') ||
        String(a.customer_names || '').localeCompare(String(b.customer_names || ''), 'zh'),
    )
}

const colorRows = computed(() => {
  const grouped = groupColorRows(colorPool.value)
  const kw = colorKeyword.value.trim().toLowerCase()
  const filtered = kw
    ? grouped.filter((row) =>
        [row.product_code, row.color_name, row.sales_order_nos, row.customer_names]
          .join(' ')
          .toLowerCase()
          .includes(kw),
      )
    : grouped
  const sid = colorFilterSalesOrderId.value
  if (!sid) return filtered
  return [...filtered].sort((a, b) => {
    const am = rowHasSalesOrder(a, sid) ? 0 : 1
    const bm = rowHasSalesOrder(b, sid) ? 0 : 1
    return am - bm
  })
})

function rowHasSalesOrder(row: any, sid: number) {
  return (row?.sources || []).some((s: any) => Number(s.sales_order_id) === sid)
}

function colorRowClassName({ row }: { row: any }) {
  const sid = colorFilterSalesOrderId.value
  return sid && rowHasSalesOrder(row, sid) ? 'is-from-sales' : ''
}

function goWorkbench(tab: string) {
  if (!legacyMode.value && tab !== 'color') return
  mainTab.value = tab
  onTabChange(tab)
}

function parseYmd(s: string) {
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}

function defaultGanttFromTo() {
  const today = new Date()
  return { from: toYmd(addDays(today, -2)), to: toYmd(addDays(today, 35)) }
}

function ensureGanttRange() {
  if (ganttFrom.value && ganttTo.value) return
  const d = defaultGanttFromTo()
  ganttFrom.value = d.from
  ganttTo.value = d.to
}

function compactMd(iso?: string) {
  if (!iso) return ''
  const s = String(iso).slice(0, 10)
  return `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}`
}

const ganttRangeLabel = computed(() => {
  if (!ganttFrom.value || !ganttTo.value) return ''
  const y0 = ganttFrom.value.slice(0, 4)
  const y1 = ganttTo.value.slice(0, 4)
  if (y0 !== y1) return `${ganttFrom.value.replace(/-/g, '/')} – ${compactMd(ganttTo.value)}`
  return `${compactMd(ganttFrom.value)} – ${compactMd(ganttTo.value)}`
})

const ganttAtDefault = computed(() => {
  const d = defaultGanttFromTo()
  return ganttFrom.value === d.from && ganttTo.value === d.to
})

async function loadGanttBoard() {
  ensureGanttRange()
  ganttLoading.value = true
  try {
    const res: any = await http.get('/schedule/gantt', {
      params: { date_from: ganttFrom.value, date_to: ganttTo.value },
    })
    const d = res.data || {}
    ganttWorkdays.value = d.days || d.workdays || []
    ganttIssued.value = d.issued || []
  } catch (e: any) {
    ganttWorkdays.value = []
    ganttIssued.value = []
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载甘特失败')
  } finally {
    ganttLoading.value = false
  }
}

function shiftGanttDays(n: number) {
  ensureGanttRange()
  ganttFrom.value = toYmd(addDays(parseYmd(ganttFrom.value), n))
  ganttTo.value = toYmd(addDays(parseYmd(ganttTo.value), n))
  void loadGanttBoard()
}

function shiftGanttMonths(n: number) {
  ensureGanttRange()
  const from = parseYmd(ganttFrom.value)
  const to = parseYmd(ganttTo.value)
  ganttFrom.value = toYmd(new Date(from.getFullYear(), from.getMonth() + n, from.getDate()))
  ganttTo.value = toYmd(new Date(to.getFullYear(), to.getMonth() + n, to.getDate()))
  void loadGanttBoard()
}

function resetGanttRange() {
  const d = defaultGanttFromTo()
  ganttFrom.value = d.from
  ganttTo.value = d.to
  void loadGanttBoard()
}

function onGanttNav(cmd: string) {
  if (cmd === 'week-') shiftGanttDays(-7)
  else if (cmd === 'week+') shiftGanttDays(7)
  else if (cmd === 'month-') shiftGanttMonths(-1)
  else if (cmd === 'month+') shiftGanttMonths(1)
  else if (cmd === 'today') resetGanttRange()
}

ensureGanttRange()

async function openDraftForAssign() {
  // 1) 当前已打开草稿 → 直接显示
  if (draft.value) {
    draftDrawerVisible.value = true
    return
  }
  // 2) 有未确认草稿 → 自动打开第一个
  if (!draftList.value.length) await loadDraftList()
  if (draftList.value.length) {
    await openDraft(draftList.value[0].id)
    return
  }
  // 3) 完全没草稿 → 引导
  ElMessageBox.alert(
    '派工在排产草稿中进行。流程：\n① 顶部选策略，点「出方案」\n② 在方案卡片点「采用进草稿」\n\n草稿打开后，工序表每行即可「＋ 派工」，确认排产才正式生效。',
    '还没有排产草稿',
    { type: 'info', confirmButtonText: '知道了' },
  )
}

function openIssuedHeader(id: number) {
  router.push({ path: '/admin/executions', query: { header_id: String(id) } })
}

function issuedCutStart(headerId: number) {
  const row = ganttIssued.value.find((j: any) => Number(j.header_id) === Number(headerId))
  const first = (row?.windows || []).map((w: any) => String(w.start_date || '').slice(0, 10)).filter(Boolean).sort()[0]
  return first || ''
}

function openReschedule(headerId: number) {
  const row = ganttIssued.value.find((j: any) => Number(j.header_id) === Number(headerId))
  rescheduleHeaderId.value = headerId
  rescheduleHeaderNo.value = row?.header_no || ''
  rescheduleCutStart.value = issuedCutStart(headerId)
  rescheduleVisible.value = true
}

async function shiftIssuedJob(payload: { headerId: number; cutStart: string }) {
  if (!payload?.headerId || !payload?.cutStart) return
  try {
    await ElMessageBox.confirm(
      `将开裁改到 ${payload.cutStart}？工序窗口整体平移，不改其它已下发单。`,
      '改开裁日',
      { type: 'warning', confirmButtonText: '确认改期', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await http.post('/schedule/gantt-shift', {
      header_id: payload.headerId,
      cut_start: payload.cutStart,
    })
    ElMessage.success('已改开裁日')
    await loadGanttBoard()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '改期失败')
  }
}

async function confirmReschedule() {
  const hid = rescheduleHeaderId.value
  if (!hid || !rescheduleCutStart.value) return
  rescheduleSaving.value = true
  try {
    await http.post('/schedule/gantt-shift', {
      header_id: hid,
      cut_start: rescheduleCutStart.value,
    })
    ElMessage.success('已改开裁日')
    rescheduleVisible.value = false
    await loadGanttBoard()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '改期失败')
  } finally {
    rescheduleSaving.value = false
  }
}

async function withdrawIssued() {
  const hid = rescheduleHeaderId.value
  if (!hid) return
  try {
    await ElMessageBox.confirm(
      `撤回 ${rescheduleHeaderNo.value || '这张生产单'}？数量回到待排池，可重新出方案。已开裁不能撤回。`,
      '撤回待排',
      { type: 'warning', confirmButtonText: '撤回', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rescheduleWithdrawing.value = true
  try {
    await http.post('/schedule/gantt-withdraw', { header_id: hid })
    ElMessage.success('已撤回，数量回到待排')
    rescheduleVisible.value = false
    await loadGanttBoard()
    await loadColorPool()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '撤回失败')
  } finally {
    rescheduleWithdrawing.value = false
  }
}

async function openGanttRush(headerId: number) {
  ganttRushHeaderId.value = headerId
  ganttRushSim.value = null
  ganttRushVisible.value = true
  ganttRushLoading.value = true
  try {
    const res: any = await http.post('/schedule/gantt-rush/simulate', {
      header_id: headerId,
      push_workdays: 3,
    })
    ganttRushSim.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '仿真失败')
    ganttRushVisible.value = false
  } finally {
    ganttRushLoading.value = false
  }
}

async function confirmGanttRush() {
  const hid = ganttRushHeaderId.value
  if (!hid || !ganttRushSim.value) return
  ganttRushConfirming.value = true
  try {
    const res: any = await http.post('/schedule/gantt-rush/confirm', {
      header_id: hid,
      push_workdays: 3,
    })
    const n = (res.data?.applied || []).length
    ElMessage.success(`已标记急单；推迟 ${n} 张未开裁`)
    ganttRushVisible.value = false
    ganttRushSim.value = null
    ganttRushHeaderId.value = null
    await loadGanttBoard()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认失败')
  } finally {
    ganttRushConfirming.value = false
  }
}

async function shiftColorJob(payload: { jobKey: string; cutStart: string }) {
  const id = colorPlanDraft.value?.id
  if (!id || !payload?.jobKey || !payload?.cutStart) return
  colorShifting.value = true
  try {
    const res: any = await http.post(`/schedule/execution-drafts/${id}/shift`, {
      job_key: payload.jobKey,
      cut_start: payload.cutStart,
    })
    colorPlanDraft.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '改期失败')
  } finally {
    colorShifting.value = false
  }
}

// 单道工序窗口微调：改开始日 / 排几天（甘特条子点击或「调窗」按钮弹出）
const processEditorVisible = ref(false)
const processEditorSaving = ref(false)
const processEditorWindows = ref<any[]>([])
const processEditorForm = reactive<{
  jobKey: string
  processId: number
  processName: string
  startDate: string
  days: number
}>({ jobKey: '', processId: 0, processName: '', startDate: '', days: 1 })

function openProcessWindowEditor(payload: {
  jobKey: string
  processId: number
  processName?: string
  startDate?: string
  days?: number
}) {
  if (!payload?.jobKey || !payload.processId) return
  processEditorWindows.value =
    (colorPlanDraft.value?.jobs || []).find((j: any) => j.key === payload.jobKey)?.windows || []
  Object.assign(processEditorForm, {
    jobKey: payload.jobKey,
    processId: Number(payload.processId),
    processName: payload.processName || '工序',
    startDate: payload.startDate || '',
    days: Number(payload.days || 1),
  })
  processEditorVisible.value = true
}

function onProcessEditorSwitch(processId: number) {
  const w = processEditorWindows.value.find((x: any) => Number(x.process_id) === Number(processId))
  if (!w) return
  processEditorForm.processName = w.process_name || '工序'
  processEditorForm.startDate = String(w.start_date || '').slice(0, 10)
  processEditorForm.days = Number(w.days || 1)
}

async function saveProcessWindow() {
  const id = colorPlanDraft.value?.id
  if (!id || !processEditorForm.jobKey || !processEditorForm.processId) return
  if (!processEditorForm.startDate) {
    ElMessage.warning('请选择开始日期')
    return
  }
  processEditorSaving.value = true
  try {
    const res: any = await http.post(`/schedule/execution-drafts/${id}/process-window`, {
      job_key: processEditorForm.jobKey,
      process_id: processEditorForm.processId,
      start_date: processEditorForm.startDate,
      days: processEditorForm.days,
    })
    colorPlanDraft.value = res.data
    processEditorVisible.value = false
    ElMessage.success('已调整并重算')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '调整失败')
  } finally {
    processEditorSaving.value = false
  }
}

async function dropDraftSource(payload: { jobKey: string; salesOrderId: number }) {
  const id = colorPlanDraft.value?.id
  if (!id || !payload?.jobKey || !payload?.salesOrderId) return
  const job = (colorPlanDraft.value?.jobs || []).find((j: any) => j.key === payload.jobKey)
  const src = (job?.sources || []).find(
    (s: any) => Number(s.sales_order_id) === Number(payload.salesOrderId),
  )
  const who = [src?.customer_name, src?.sales_order_no].filter(Boolean).join(' ')
  try {
    await ElMessageBox.confirm(
      `从这张草稿剔除 ${who || '该客户'}（${src?.qty || ''}双）？条子和负荷会当场重算，不改本次数量。`,
      '剔除来源',
      { type: 'warning', confirmButtonText: '剔除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  colorShifting.value = true
  try {
    const res: any = await http.post(`/schedule/execution-drafts/${id}/drop-sources`, {
      job_key: payload.jobKey,
      sales_order_ids: [payload.salesOrderId],
    })
    colorPlanDraft.value = res.data
    ElMessage.success('已剔除，条子已重算')
    await loadColorPool()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '剔除失败')
  } finally {
    colorShifting.value = false
  }
}

async function openConfirmProduction() {
  dispatchMap.value = {}
  await ensureConfirmDispatchWorkers()
  if (!colorPlanDraft.value?.jobs?.length) return
  confirmProdVisible.value = true
}

const mergeAskVisible = ref(false)
const mergeAskGroups = ref<any[]>([])

function selectedPoolRows() {
  const ids = new Set(colorSelected.value.map((x) => Number(x.sales_order_line_item_id)))
  return colorRows.value.filter((row) =>
    (row.sources || []).some((s: any) => ids.has(Number(s.sales_order_line_item_id))),
  )
}

function customerFromRow(row: any) {
  const dates = (row.sources || [])
    .map((s: any) => String(s.delivery_date || '').slice(0, 10))
    .filter(Boolean)
  return {
    name: row.customer_names || '客户',
    qty: Number(row.remaining_qty || 0),
    delivery: minDelivery(dates) || row.earliest_delivery || '',
    order_nos: row.sales_order_nos,
    items: (row.sources || [])
      .map((s: any) => ({
        sales_order_line_item_id: Number(s.sales_order_line_item_id),
        qty: Number(s.remaining_qty || 0),
      }))
      .filter((x: any) => x.sales_order_line_item_id && x.qty > 0),
  }
}

function deliveryGapDays(customers: any[]) {
  const ds = (customers || [])
    .map((c) => String(c.delivery || '').slice(0, 10))
    .filter(Boolean)
    .sort()
  if (ds.length < 2) return 0
  const a = Date.parse(ds[0])
  const b = Date.parse(ds[ds.length - 1])
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  return Math.round(Math.abs(b - a) / 86400000)
}

function buildStyleAskGroups() {
  const selected = selectedPoolRows()
  const selectedRowKeys = new Set(selected.map((r) => r.key))
  const styles = new Map<string, any>()
  for (const row of selected) {
    const sk = styleKeyOf(row)
    let g = styles.get(sk)
    if (!g) {
      g = {
        styleKey: sk,
        product_code: row.product_code,
        color_name: row.color_name,
        customers: [] as any[],
        leftovers: [] as any[],
        includeLeftover: false,
      }
      styles.set(sk, g)
    }
    g.customers.push(customerFromRow(row))
  }
  for (const row of groupColorRows(colorPool.value)) {
    const g = styles.get(styleKeyOf(row))
    if (!g || selectedRowKeys.has(row.key)) continue
    if (Number(row.remaining_qty || 0) <= 0) continue
    g.leftovers.push(customerFromRow(row))
  }
  return Array.from(styles.values()).filter(
    (g) => g.customers.length > 1 || g.leftovers.length > 0,
  )
}

function askMergeCount(g: any) {
  return (g.customers?.length || 0) + (g.includeLeftover ? g.leftovers?.length || 0 : 0)
}

function askGapDays(g: any) {
  const all = g.includeLeftover ? [...(g.customers || []), ...(g.leftovers || [])] : g.customers || []
  return deliveryGapDays(all)
}

async function proposeColorPlan() {
  if (!colorSelected.value.length) return
  const groups = buildStyleAskGroups()
  if (groups.length) {
    mergeAskGroups.value = groups
    mergeAskVisible.value = true
    return
  }
  await submitColorPropose([])
}

async function confirmMergeAsk() {
  const extra: { sales_order_line_item_id: number; qty: number }[] = []
  const splitKeys: string[] = []
  for (const g of mergeAskGroups.value) {
    if (g.includeLeftover) {
      for (const c of g.leftovers || []) extra.push(...(c.items || []))
    }
    if (askMergeCount(g) > 1) splitKeys.push(g.styleKey)
  }
  mergeAskVisible.value = false
  await submitColorPropose(splitKeys, extra)
}

async function submitColorPropose(
  splitStyleKeys: string[],
  extraItems: { sales_order_line_item_id: number; qty: number }[] = [],
) {
  if (!colorSelected.value.length && !extraItems.length) return
  const items = [...colorSelected.value]
  const seen = new Set(items.map((x) => Number(x.sales_order_line_item_id)))
  for (const x of extraItems) {
    const id = Number(x.sales_order_line_item_id)
    const qty = Number(x.qty || 0)
    if (!id || qty <= 0 || seen.has(id)) continue
    items.push({ sales_order_line_item_id: id, qty })
    seen.add(id)
  }
  colorProposing.value = true
  try {
    const res: any = await http.post('/schedule/execution-drafts', {
      items,
      note: colorAsRush.value ? '急单排产' : '排产方案',
      is_rush: colorAsRush.value,
      split_style_keys: splitStyleKeys,
    })
    colorPlanDraft.value = res.data
    colorPoolOpen.value = false
    if (res.data?.plan_error) {
      ElMessage.warning(res.data.plan_error)
    }
  } catch (e: any) {
    colorPlanDraft.value = null
    const detail = e?.response?.data?.detail || e?.message || ''
    if (detail.includes('未配置单人日产能')) {
      openCapacityFill()
      return
    }
    ElMessage.error(detail || '出方案失败')
  } finally {
    colorProposing.value = false
  }
}

async function selectColorStrategy(strategy: string) {
  const id = colorPlanDraft.value?.id
  if (!id || !strategy) return
  try {
    const res: any = await http.post(`/schedule/execution-drafts/${id}/strategy`, { strategy })
    colorPlanDraft.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '切换方案失败')
  }
}

async function discardColorPlan() {
  const id = colorPlanDraft.value?.id
  if (!id) {
    colorPlanDraft.value = null
    colorPoolTouched.value = true
    colorPoolOpen.value = true
    return
  }
  try {
    await http.post(`/schedule/execution-drafts/${id}/discard`)
  } catch {
    /* still drop local */
  }
  colorPlanDraft.value = null
  colorPoolTouched.value = true
  colorPoolOpen.value = true
}

// ── 未配产能内联补填 ──
const capacityFillVisible = ref(false)
const capacityMissingRows = ref<any[]>([])
const capacityFilling = ref(false)

async function openCapacityFill() {
  try {
    const res: any = await http.get('/processes')
    const all = (res.data?.items || []).filter((p: any) => p.is_active !== false)
    capacityMissingRows.value = all.filter((p: any) => !p.per_worker_capacity || Number(p.per_worker_capacity) <= 0)
  } catch {
    capacityMissingRows.value = []
  }
  if (!capacityMissingRows.value.length) {
    ElMessage.warning('工序产能已配置，请重新出方案')
    return
  }
  capacityFillVisible.value = true
}

async function saveCapacityFill() {
  const rows = capacityMissingRows.value.filter((r: any) => r.per_worker_capacity && Number(r.per_worker_capacity) > 0)
  if (!rows.length) {
    ElMessage.warning('请至少填写一道工序的单人日产能')
    return
  }
  capacityFilling.value = true
  try {
    for (const r of rows) {
      await http.patch(`/processes/${r.id}`, {
        per_worker_capacity: Number(r.per_worker_capacity),
        standard_workers: Number(r.standard_workers || 1),
        current_workers: r.current_workers ? Number(r.current_workers) : null,
      })
    }
    ElMessage.success(`已保存 ${rows.length} 道工序产能`)
    capacityFillVisible.value = false
    await submitColorPropose([], [])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    capacityFilling.value = false
  }
}

// 排产方案确认前的派工（按 job_key × process_id 选工人）
const dispatchMap = ref<Record<string, Record<string, number[]>>>({})
const dispatchWorkers = ref<any[]>([])

async function ensureConfirmDispatchWorkers() {
  if (dispatchWorkers.value.length) return
  try {
    const res: any = await http.get('/workers', { params: { is_active: true, page_size: 500 } })
    dispatchWorkers.value = res.data?.items || []
  } catch {
    dispatchWorkers.value = []
  }
}

function dispatchGet(jobKey: string | undefined, processId: number | undefined): number[] {
  if (!jobKey || processId == null) return []
  return (dispatchMap.value[jobKey] || {})[String(processId)] || []
}

function dispatchSet(jobKey: string | undefined, processId: number | undefined, v: number[]) {
  if (!jobKey || processId == null) return
  if (!dispatchMap.value[jobKey]) dispatchMap.value[jobKey] = {}
  dispatchMap.value[jobKey][String(processId)] = v
}

async function submitConfirmProduction() {
  const id = colorPlanDraft.value?.id
  if (!id) return
  colorConfirming.value = true
  try {
    const res: any = await http.post(`/schedule/execution-drafts/${id}/confirm`, {
      dispatch: dispatchMap.value,
    })
    const headers = res.data?.headers || []
    const nos = headers.map((x: any) => x.header_no).filter(Boolean)
    confirmProdVisible.value = false
    colorPlanDraft.value = null
    colorAsRush.value = false
    colorTableRef.value?.clearSelection()
    colorSelection.value = new Map()
    colorFilterSalesOrderId.value = null
    colorFilterSalesOrderNo.value = ''
    ElMessage.success(
      nos.length
        ? `已下发 ${nos.join('、')}。下一步：开裁`
        : '已确认方案并下发生产单',
    )
    await loadGanttBoard()
    await loadColorPool()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '确认下发失败')
  } finally {
    colorConfirming.value = false
  }
}

async function loadColorPool() {
  colorPoolLoading.value = true
  try {
    const res: any = await http.get('/schedule/color-pool', {
      params: { kit_ready_only: colorKitReadyOnly.value || undefined },
    })
    const items = res.data?.items || []
    colorPool.value = items.map((b: any) => ({
      ...b,
      key: `${b.own_product_id}-${b.color_id}-${b.size_id}`,
    }))
    if (colorFilterSalesOrderId.value && !colorFilterSalesOrderNo.value) {
      const sid = colorFilterSalesOrderId.value
      const hit = items
        .flatMap((b: any) => b.sources || [])
        .find((s: any) => Number(s.sales_order_id) === sid)
      colorFilterSalesOrderNo.value = hit?.sales_order_no || ''
    }
    await nextTick()
    await applySalesOrderFocus()
    await applyPendingItemSelection()
  } catch (e: any) {
    colorPool.value = []
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载待排款失败')
  } finally {
    colorPoolLoading.value = false
  }
}

function openColorPool() {
  colorPoolTouched.value = true
  colorPoolOpen.value = true
}

function closeColorPool() {
  colorPoolTouched.value = true
  colorPoolOpen.value = false
}

function maybeAutoOpenColorPool() {
  if (colorPoolTouched.value) return
  if (colorPlanDraft.value) {
    colorPoolOpen.value = false
    return
  }
  colorPoolOpen.value = !ganttRows.value.length && colorRows.value.length > 0
}

function onColorSelectionChange(rows: any[]) {
  const next = new Map<number, { sales_order_line_item_id: number; qty: number }>()
  for (const row of rows || []) {
    for (const src of row.sources || []) {
      const id = Number(src.sales_order_line_item_id)
      const qty = Number(src.remaining_qty || 0)
      if (id && qty > 0) {
        next.set(id, { sales_order_line_item_id: id, qty })
      }
    }
  }
  colorSelection.value = next
}

async function applySalesOrderFocus() {
  const sid = colorFilterSalesOrderId.value
  const table = colorTableRef.value
  if (!sid || !table) return
  table.clearSelection()
  await nextTick()
  for (const row of colorRows.value) {
    if (rowHasSalesOrder(row, sid)) table.toggleRowSelection(row, true)
  }
}

function parseItemIds(raw: unknown) {
  return String(raw || '')
    .split(',')
    .map((x) => Number(x.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)
}

const pendingItemIds = ref<number[]>([])
const pendingAutoPropose = ref(false)

function rowHasItemIds(row: any, ids: Set<number>) {
  return (row?.sources || []).some((s: any) => ids.has(Number(s.sales_order_line_item_id)))
}

async function applyPendingItemSelection() {
  const ids = new Set(pendingItemIds.value)
  if (!ids.size) return
  const table = colorTableRef.value
  colorPoolTouched.value = true
  colorPoolOpen.value = true
  if (!table) return
  table.clearSelection()
  await nextTick()
  for (const row of colorRows.value) {
    if (rowHasItemIds(row, ids)) table.toggleRowSelection(row, true)
  }
  if (pendingAutoPropose.value && colorSelected.value.length) {
    pendingAutoPropose.value = false
    pendingItemIds.value = []
    if (String(route.query.from || '') === 'merge') {
      await submitColorPropose([])
    } else {
      await proposeColorPlan()
    }
  }
}

const settingsVisible = ref(false)
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settingsForm = reactive({
  allow_schedule_on_non_workdays: false,
  merge_delivery_window_days: 7,
  merge_require_same_color: true,
  merge_min_qty: 0,
  load_warn_utilization: 0.9,
  schedule_blackout_dates: [] as { date: string; note: string }[],
  actual_capacity_lookback_days: 7,
})
const settingsHint = computed(() => {
  const bits: string[] = []
  if (settingsForm.allow_schedule_on_non_workdays) bits.push('加班开')
  if (settingsForm.schedule_blackout_dates.some((x) => x.date)) bits.push('有停工日')
  return bits.join(' · ')
})
const mergeSuggestVisible = ref(false)
const mergeSuggestLoading = ref(false)
const mergeAdoptKey = ref<number | null>(null)
const mergeSuggestItems = ref<any[]>([])
const mergeSuggestParams = reactive({
  merge_delivery_window_days: 7,
  merge_require_same_color: true,
  merge_min_qty: 0,
})
const mergeSuggestSkipped = ref<Record<string, number> | null>(null)
const pool = ref<any[]>([])
const poolTotal = ref(0)
const page = ref(1)
const pageSize = ref(50)
const selectedIds = ref<number[]>([])
const selectedHeaderIds = ref<number[]>([])
const draft = ref<any>(null)
const draftDrawerVisible = ref(false)
const draftCapacityCfg = ref<{
  byProcess: Record<string, number>
  defaultCap: number | null
}>({ byProcess: {}, defaultCap: null })
const assignExpanded = reactive<Record<number, boolean>>({})
const draftPickerVisible = ref(false)
const draftList = ref<any[]>([])
const draftListLoading = ref(false)
const proposalVisible = ref(false)
const proposals = ref<any[]>([])
const proposalScopeNote = ref('')
const skipKitOpen = reactive<Record<string, boolean>>({})
const unassignedCount = computed(() => {
  const lines: any[] = (draft.value?.lines || []).filter((ln: any) => ln.included)
  return lines.filter((ln: any) => !(ln.assignments || []).length).length
})

const workers = ref<any[]>([])
const teams = ref<any[]>([])
const assignVisible = ref(false)
const assignLine = ref<any>(null)
const assignWorkerIds = ref<number[]>([])
const assignEqualSplit = ref(true)
const assignTeamId = ref<number | null>(null)
const assignTeamMode = ref<'members' | 'leader'>('members')
const filters = reactive({
  keyword: '',
  rush_only: false,
  hide_first_kit_blocked: false,
  show_scheduled: false,
  merge_batch_id: null as number | null,
})
const mergeBatchOptions = ref<any[]>([])
const pendingSelectIds = ref<number[]>([])
const monthCursor = ref(startOfMonth(new Date()))
const calByDate = ref<Record<string, any[]>>({})
const calDayMeta = ref<Record<string, any>>({})

const WEEKDAY = ['一', '二', '三', '四', '五', '六', '日']

function pad(n: number) {
  return String(n).padStart(2, '0')
}

function toYmd(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function addMonths(d: Date, n: number) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1)
}

function addDays(d: Date, n: number) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  x.setDate(x.getDate() + n)
  return x
}

/** 月视图网格起点：当月 1 号所在周的周一 */
function monthGridStart(month: Date) {
  const first = startOfMonth(month)
  const day = first.getDay() // 0 Sun
  const diff = day === 0 ? -6 : 1 - day
  return addDays(first, diff)
}

function monthGridEnd(month: Date) {
  return addDays(monthGridStart(month), 41) // 6 周
}

const monthLabel = computed(() => {
  const d = monthCursor.value
  return `${d.getFullYear()}年${d.getMonth() + 1}月`
})

const monthDays = computed(() => {
  const today = toYmd(new Date())
  const y = monthCursor.value.getFullYear()
  const m = monthCursor.value.getMonth()
  const start = monthGridStart(monthCursor.value)
  return Array.from({ length: 42 }, (_, i) => {
    const d = addDays(start, i)
    const key = toYmd(d)
    const meta = calDayMeta.value[key] || {}
    return {
      key,
      dayNum: d.getDate(),
      inMonth: d.getFullYear() === y && d.getMonth() === m,
      isToday: key === today,
      isOff: !!meta.is_off,
      isHoliday: !!meta.is_holiday,
      isMakeup: !!meta.is_makeup_workday,
      label: meta.label || null,
      items: calByDate.value[key] || [],
    }
  })
})

function scheduleLabel(s: string) {
  return (
    ({ none: '未排', drafted: '有草稿', partial: '部分', scheduled: '已排' } as Record<string, string>)[s] ||
    s ||
    '—'
  )
}

function onSelect(rows: any[]) {
  selectedIds.value = rows.filter((r) => r.order_id != null).map((r) => Number(r.order_id))
  selectedHeaderIds.value = rows
    .filter((r) => r.header_id != null && r.order_id == null)
    .map((r) => Number(r.header_id))
}

function applyPendingSelection() {
  const ids = new Set(pendingSelectIds.value)
  if (!ids.size || !tableRef.value) return
  const table = tableRef.value as any
  for (const row of pool.value) {
    if (ids.has(row.order_id)) {
      table.toggleRowSelection?.(row, true)
    }
  }
  pendingSelectIds.value = []
}

async function loadMergeBatchOptions() {
  try {
    const res: any = await http.get('/merge-batches', { params: { status: 'open', limit: 100 } })
    const raw = res?.data
    mergeBatchOptions.value = Array.isArray(raw) ? raw : raw?.items || []
  } catch {
    mergeBatchOptions.value = []
  }
}

async function loadPool() {
  loading.value = true
  try {
    const res: any = await http.get('/schedule/pool', {
      params: {
        keyword: filters.keyword || undefined,
        rush_only: filters.rush_only || undefined,
        hide_first_kit_blocked: filters.hide_first_kit_blocked || undefined,
        hide_scheduled: !filters.show_scheduled,
        merge_batch_id: filters.merge_batch_id || undefined,
        page: page.value,
        page_size: pageSize.value,
      },
    })
    pool.value = res.data?.items || []
    poolTotal.value = Number(res.data?.total || 0)
    void nextTick(() => {
      measureTableHeight()
      applyPendingSelection()
    })
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  void loadPool()
}

function onPageSizeChange() {
  page.value = 1
  void loadPool()
}

async function loadDraftList() {
  draftListLoading.value = true
  try {
    const res: any = await http.get('/schedule/drafts', { params: { status: 'draft' } })
    draftList.value = res.data?.items || []
  } catch {
    draftList.value = []
  } finally {
    draftListLoading.value = false
  }
}

function formatDt(v: string | null | undefined) {
  if (!v) return '—'
  return String(v).replace('T', ' ').slice(0, 19)
}

async function openDraftPicker() {
  draftPickerVisible.value = true
  await loadDraftList()
}

async function openDraft(draftId: number) {
  saving.value = true
  try {
    const res: any = await http.get(`/schedule/drafts/${draftId}`)
    draft.value = res.data
    draftPickerVisible.value = false
    draftDrawerVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '打开失败')
  } finally {
    saving.value = false
  }
}

function onDraftDrawerOpened() {
  Object.keys(assignExpanded).forEach((k) => delete assignExpanded[Number(k)])
  void ensureDraftCapacityCfg()
  void nextTick(() => {
    relayoutDraftTable()
    setTimeout(() => relayoutDraftTable(), 50)
  })
}

function onDraftDrawerClosed() {
  Object.keys(assignExpanded).forEach((k) => delete assignExpanded[Number(k)])
  if (draft.value?.status !== 'draft') {
    draft.value = null
  }
}

async function ensureDraftCapacityCfg() {
  try {
    const res: any = await http.get('/schedule/settings')
    const d = res?.data || res || {}
    const raw = d.daily_capacity_by_process || {}
    const byProcess: Record<string, number> = {}
    for (const [k, v] of Object.entries(raw)) {
      const n = Number(v)
      if (Number.isFinite(n) && n > 0) byProcess[String(k)] = n
    }
    const def = d.default_daily_capacity
    draftCapacityCfg.value = {
      byProcess,
      defaultCap: def != null && Number(def) > 0 ? Number(def) : null,
    }
  } catch {
    /* 摘要负荷峰可降级为仅展示数量 */
  }
}

function toggleAssignExpand(lineId: number) {
  assignExpanded[lineId] = !assignExpanded[lineId]
}

function capacityForProcess(processId: number | null | undefined) {
  if (processId == null) return draftCapacityCfg.value.defaultCap
  const hit = draftCapacityCfg.value.byProcess[String(processId)]
  if (hit != null) return hit
  return draftCapacityCfg.value.defaultCap
}

function datesBetween(start: string, end: string): string[] {
  const a = new Date(start.slice(0, 10) + 'T00:00:00')
  const b = new Date(end.slice(0, 10) + 'T00:00:00')
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime()) || a > b) return []
  const out: string[] = []
  for (let d = new Date(a); d <= b; d.setDate(d.getDate() + 1)) {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    out.push(`${y}-${m}-${day}`)
  }
  return out
}

/** 单行相对交期：整单最晚完工（同单纳入行）— 行级提示用本行完工。 */
function orderLateHint(row: any) {
  const end = row?.end_date ? String(row.end_date).slice(0, 10) : ''
  const delivery = row?.delivery_date ? String(row.delivery_date).slice(0, 10) : ''
  if (!end || !delivery) return ''
  const days = Math.round(
    (new Date(end + 'T00:00:00').getTime() - new Date(delivery + 'T00:00:00').getTime()) / 86400000,
  )
  if (days > 0) return `晚${days}天`
  if (days >= -2) return '偏紧'
  return ''
}

const draftSummary = computed(() => {
  const lines: any[] = (draft.value?.lines || []).filter((ln: any) => ln.included)
  if (!lines.length) {
    return { text: '未勾选纳入工序', warn: true }
  }
  const byOrder = new Map<number, { order_no: string; delivery: string; finish: string; is_rush: boolean }>()
  for (const ln of lines) {
    const oid = ln.order_id
    const end = ln.end_date ? String(ln.end_date).slice(0, 10) : ''
    const cur = byOrder.get(oid)
    if (!cur) {
      byOrder.set(oid, {
        order_no: ln.order_no || String(oid),
        delivery: ln.delivery_date ? String(ln.delivery_date).slice(0, 10) : '',
        finish: end,
        is_rush: !!ln.is_rush,
      })
    } else if (end && (!cur.finish || end > cur.finish)) {
      cur.finish = end
    }
  }
  let lateCount = 0
  const lateNos: string[] = []
  for (const o of byOrder.values()) {
    if (o.finish && o.delivery && o.finish > o.delivery) {
      lateCount += 1
      lateNos.push(o.order_no)
    }
  }

  // 本草稿纳入行粗算日负荷峰（数量均摊到开工～完工各自然日）
  const loadMap = new Map<string, { qty: number; process_id: number; process_name: string; date: string }>()
  for (const ln of lines) {
    const start = ln.start_date ? String(ln.start_date).slice(0, 10) : ''
    const end = ln.end_date ? String(ln.end_date).slice(0, 10) : start
    if (!start) continue
    const days = datesBetween(start, end || start)
    if (!days.length) continue
    const each = Number(ln.plan_qty || 0) / days.length
    for (const d of days) {
      const key = `${ln.process_id}|${d}`
      const cur = loadMap.get(key)
      if (cur) cur.qty += each
      else {
        loadMap.set(key, {
          qty: each,
          process_id: ln.process_id,
          process_name: ln.process_name || '',
          date: d,
        })
      }
    }
  }
  let peak: { util: number | null; qty: number; process_name: string; date: string } | null = null
  for (const row of loadMap.values()) {
    const cap = capacityForProcess(row.process_id)
    const util = cap ? row.qty / cap : null
    if (
      !peak ||
      (util != null && (peak.util == null || util > peak.util)) ||
      (util == null && peak.util == null && row.qty > peak.qty)
    ) {
      peak = { util, qty: row.qty, process_name: row.process_name, date: row.date }
    }
  }

  const parts = [
    `纳入 ${lines.length} 工序 / ${byOrder.size} 单`,
    `预计逾期 ${lateCount}`,
  ]
  if (lateNos.length) {
    parts[1] += `（${lateNos.slice(0, 2).join('、')}${lateNos.length > 2 ? '…' : ''}）`
  }
  if (peak) {
    const peakPct = peak.util != null ? `${Math.round(peak.util * 100)}%` : `${Math.round(peak.qty)}双`
    parts.push(`负荷峰 ${peak.process_name} ${shortDate(peak.date)} ${peakPct}`)
  }
  const warn = lateCount > 0 || (peak?.util != null && peak.util > 1)
  return { text: parts.join(' · '), warn }
})

function goWeeklyFromDraft() {
  draftDrawerVisible.value = false
  mainTab.value = 'weekly'
  void loadWeekly()
}

async function loadCalendar() {
  calLoading.value = true
  try {
    const from = toYmd(monthGridStart(monthCursor.value))
    const to = toYmd(monthGridEnd(monthCursor.value))
    const res: any = await http.get('/schedule/calendar', {
      params: { date_from: from, date_to: to },
    })
    calByDate.value = res.data?.by_date || {}
    calDayMeta.value = res.data?.day_meta || {}
  } catch (e: any) {
    const d = e?.response?.data?.detail
    ElMessage.error(typeof d === 'object' ? d.message || JSON.stringify(d) : d || e?.message || '加载失败')
    calByDate.value = {}
    calDayMeta.value = {}
  } finally {
    calLoading.value = false
  }
}

function shiftMonth(delta: number) {
  monthCursor.value = addMonths(monthCursor.value, delta)
  void loadCalendar()
}

function goThisMonth() {
  monthCursor.value = startOfMonth(new Date())
  void loadCalendar()
}

function onTabChange(name: string | number) {
  if (name === 'calendar') void loadCalendar()
  if (name === 'weekly') void loadWeekly()
  if (name === 'pool') void nextTick(measureTableHeight)
  if (name === 'color') {
    void loadColorPool()
    void loadGanttBoard()
  }
}

async function loadWeekly() {
  weeklyLoading.value = true
  try {
    const res: any = await http.get('/schedule/load/weekly', { params: { weeks: 4 } })
    const d = res?.data || res || {}
    weeklyItems.value = d.items || []
    weeklyWarnUtil.value = Number(d.warn_utilization ?? 0.9)
  } catch (e: any) {
    weeklyItems.value = []
    ElMessage.error(e?.message || '加载周负荷失败')
  } finally {
    weeklyLoading.value = false
  }
}

const weeklyHeadline = computed(() => {
  const items = weeklyItems.value
  if (!items.length) return ''
  const thisWeek = items[0]
  const nextWeek = items[1]
  const parts: string[] = []
  if (thisWeek) {
    parts.push(
      thisWeek.over_days > 0
        ? `本周超载 ${thisWeek.over_days} 天`
        : '本周无超载'
    )
  }
  if (nextWeek) {
    parts.push(
      nextWeek.over_days > 0
        ? `下周超载 ${nextWeek.over_days} 天`
        : '下周无超载'
    )
  }
  return parts.join('；') + `（预警阈值 ${Math.round(weeklyWarnUtil.value * 100)}%）`
})

function openOrder(orderId: number) {
  router.push({ path: '/admin/executions', query: { shop_order_id: String(orderId) } })
}

async function loadWorkers() {
  if (workers.value.length) return
  try {
    const res: any = await http.get('/workers', { params: { is_active: true, page_size: 500 } })
    workers.value = res.data?.items || res.data || []
  } catch {
    workers.value = []
  }
}

async function loadTeams() {
  try {
    const res: any = await http.get('/teams')
    teams.value = res.data?.items || res.data || []
  } catch {
    teams.value = []
  }
}

function onAssignTeamChange() {
  if (!assignTeamId.value) return
  const team = teams.value.find((t) => t.id === assignTeamId.value)
  if (!team) return
  if (assignTeamMode.value === 'leader') {
    assignWorkerIds.value = team.leader_worker_id ? [team.leader_worker_id] : []
  } else {
    const members = team.members || []
    const ids = members.map((m: any) => m.id)
    if (team.leader_worker_id && !ids.includes(team.leader_worker_id)) {
      ids.unshift(team.leader_worker_id)
    }
    assignWorkerIds.value = ids
  }
  assignEqualSplit.value = true
}

async function createDraft() {
  creating.value = true
  try {
    const res: any = await http.post('/schedule/drafts', {
      order_ids: selectedIds.value,
      header_ids: selectedHeaderIds.value,
      auto_assign: true,
    })
    draft.value = res.data
    draftDrawerVisible.value = true
    ElMessage.success('已生成倒排草稿（含派工建议）')
    await Promise.all([loadPool(), loadDraftList()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '生成失败')
  } finally {
    creating.value = false
  }
}

function shortDate(v?: string) {
  if (!v) return ''
  const s = String(v)
  return s.length >= 10 ? s.slice(5, 10).replace('-', '/') : s
}

/** 工序窗口的排产依据小字（A'档：实测/标准/手动覆盖）。 */
function capacityNote(w: any): string {
  if (!w) return ''
  const days = w.days ?? '?'
  const num = (v: any) => (v == null ? '?' : Number(v) % 1 === 0 ? String(Number(v)) : Number(v).toFixed(1))
  const pct = (v: any) => (v == null ? '?' : `${Math.round(Number(v) * 100)}%`)
  const heads = `${num(w.active_workers)} 人 × ${num(w.avg_per_head)} 双/人/天 排 ${days} 天`
  if (w.source === 'override') return `按 ${heads}（手动覆盖）`
  if (w.source === 'actual_product') {
    const lb = settingsForm.actual_capacity_lookback_days || 7
    return `按 ${heads}（近${lb}天款级实测，效率 ${pct(w.efficiency)}）`
  }
  if (w.source === 'actual_process') {
    const lb = settingsForm.actual_capacity_lookback_days || 7
    return `按 ${heads}（近${lb}天工序实测，效率 ${pct(w.efficiency)}）`
  }
  if (w.source === 'standard') return `按 ${heads}（标准人力）`
  return ''
}

/** 方案对比指标：逾期与产能冲突分列；负荷峰按利用率。 */
function proposalHeadline(p: any) {
  const risks = p?.risks || {}
  const load: any[] = Array.isArray(p?.load) ? p.load : []
  let peak: any = null
  let overDays = 0
  for (const row of load) {
    if (row?.over_capacity) overDays += 1
    if (row?.utilization == null) continue
    if (!peak || row.utilization > peak.utilization) peak = row
  }
  return {
    lateCount: risks.late || 0,
    capacityCount: risks.capacity_blocked || 0,
    peakUtilPct: peak ? Math.round(peak.utilization * 100) : null,
    peakLabel: peak ? `${peak.process_name || ''} ${shortDate(peak.date)}`.trim() : '—',
    overDays,
  }
}

/** 逾期代表单：最多 2 个，附最长晚几天，方便拍板。 */
function lateSample(p: any) {
  const orders: any[] = Array.isArray(p?.orders) ? p.orders : []
  const late = orders
    .filter((o) => o?.risk === 'late')
    .map((o) => {
      const finish = o.projected_finish ? String(o.projected_finish).slice(0, 10) : ''
      const delivery = o.delivery_date ? String(o.delivery_date).slice(0, 10) : ''
      let daysLate = 0
      if (finish && delivery) {
        const a = new Date(finish + 'T00:00:00')
        const b = new Date(delivery + 'T00:00:00')
        daysLate = Math.max(0, Math.round((a.getTime() - b.getTime()) / 86400000))
      }
      return { order_no: o.order_no || String(o.order_id), daysLate, is_rush: !!o.is_rush }
    })
    .sort((a, b) => (b.is_rush ? 1 : 0) - (a.is_rush ? 1 : 0) || b.daysLate - a.daysLate)
  if (!late.length) return { text: '', items: [] as typeof late }
  const top = late.slice(0, 2)
  const more = late.length > 2 ? `等${late.length}单` : ''
  const text =
    top.map((x) => `${x.order_no}${x.daysLate ? `(晚${x.daysLate}天)` : ''}`).join('、') +
    (more ? ` ${more}` : '')
  return { text, items: top }
}

/**
 * 软推荐：优先负荷峰≤100%，再比逾期少、产能冲突少、超产天少。
 * 并列或全员超产严重时标「需人工选」。
 */
const proposalRecommend = computed(() => {
  const list = proposals.value
  if (list.length < 2) return { id: '', text: '', tie: false, title: '' }

  const scored = list.map((p) => {
    const h = proposalHeadline(p)
    const peak = h.peakUtilPct
    const loadOk = peak == null || peak <= 100 ? 1 : 0
    return {
      p,
      loadOk,
      late: h.lateCount || 0,
      cap: h.capacityCount || 0,
      over: h.overDays || 0,
      peak: peak == null ? 9999 : peak,
    }
  })
  scored.sort(
    (a, b) =>
      b.loadOk - a.loadOk ||
      a.late - b.late ||
      a.cap - b.cap ||
      a.over - b.over ||
      a.peak - b.peak,
  )
  const best = scored[0]
  const second = scored[1]
  const tied =
    !!second &&
    best.loadOk === second.loadOk &&
    best.late === second.late &&
    best.cap === second.cap &&
    best.over === second.over

  if (tied) {
    return {
      id: '',
      title: '',
      tie: true,
      text: '建议：指标接近，需人工选（可先看逾期代表单与负荷条）',
    }
  }

  const why: string[] = []
  if (best.loadOk) why.push('负荷可控')
  else why.push('相对少挤产能')
  if (best.late === 0) why.push('无逾期')
  else why.push(`逾期 ${best.late} 单（方案中最少）`)
  return {
    id: best.p.proposal_id,
    title: best.p.title,
    tie: false,
    text: `建议采用：${best.p.title} — ${why.join('，')}；可忽略后自选`,
  }
})

function proposalSummaryShort(p: any) {
  const s = String(p?.summary || '')
  const cut = s.indexOf('待料未排')
  return cut >= 0 ? s.slice(0, cut).trim() : s
}

function toggleSkipKit(id: string) {
  skipKitOpen[id] = !skipKitOpen[id]
}

/** 近 14 个自然日：取当日各工序利用率最大值 → 迷你柱 */
function proposalSpark(p: any) {
  const load: any[] = Array.isArray(p?.load) ? p.load : []
  const byDay: Record<string, number> = {}
  for (const row of load) {
    const d = String(row?.date || '').slice(0, 10)
    if (!d) continue
    const u = Number(row?.utilization)
    if (!Number.isFinite(u)) continue
    byDay[d] = Math.max(byDay[d] || 0, u)
  }
  const days = Object.keys(byDay).sort().slice(0, 14)
  if (!days.length) {
    return Array.from({ length: 7 }, () => ({ height: 8, tone: 'is-empty', label: '—' }))
  }
  return days.map((d) => {
    const u = byDay[d]
    const pct = Math.round(u * 100)
    const height = Math.max(10, Math.min(100, pct))
    let tone = 'is-ok'
    if (u >= 1) tone = 'is-over'
    else if (u >= 0.85) tone = 'is-warn'
    return { height, tone, label: `${d} 峰 ${pct}%` }
  })
}

const proposalDiffHint = computed(() => {
  const list = proposals.value
  if (list.length < 2) return ''
  const base = list.find((p) => p.strategy === 'delivery_first') || list[0]
  const alt = list.find((p) => p.strategy === 'capacity_first')
  if (!base || !alt) return ''
  const b = proposalHeadline(base)
  const a = proposalHeadline(alt)
  const dLate = (a.lateCount || 0) - (b.lateCount || 0)
  const dOver = (a.overDays || 0) - (b.overDays || 0)
  const dPeak = (a.peakUtilPct || 0) - (b.peakUtilPct || 0)
  const parts = [
    `相对「${base.title}」：保现场逾期 ${dLate >= 0 ? '+' : ''}${dLate}`,
    `超产天 ${dOver >= 0 ? '+' : ''}${dOver}`,
    `负荷峰 ${dPeak >= 0 ? '+' : ''}${dPeak}pt`,
  ]
  const kit = list.find((p) => p.strategy === 'kit_ready')
  if (kit) {
    parts.push(`只排齐套少排 ${Math.max(0, (base.orders || []).length - (kit.orders || []).length)} 单`)
  }
  return parts.join('；')
})

async function generateProposals() {
  proposing.value = true
  proposalVisible.value = true
  proposals.value = []
  proposalScopeNote.value = ''
  Object.keys(skipKitOpen).forEach((k) => delete skipKitOpen[k])
  try {
    const res: any = await http.post('/schedule/proposals', {
      order_ids: selectedIds.value.length ? selectedIds.value : undefined,
      hide_scheduled: !filters.show_scheduled,
    })
    proposals.value = res.data?.items || []
    const scope = res.data?.scope
    proposalScopeNote.value = scope?.note || ''
    if (!proposals.value.length) ElMessage.warning('没有可排订单')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '方案生成失败')
  } finally {
    proposing.value = false
  }
}

async function adoptProposal(p: any) {
  adopting.value = true
  try {
    const res: any = await http.post('/schedule/proposals/adopt', {
      proposal: p,
      auto_assign: true,
    })
    draft.value = res.data
    proposalVisible.value = false
    draftDrawerVisible.value = true
    ElMessage.success('已采用方案并进入草稿')
    await Promise.all([loadPool(), loadDraftList()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '采用失败')
  } finally {
    adopting.value = false
  }
}

async function goAssistant() {
  const query: Record<string, string> = {}
  if (selectedIds.value.length) {
    query.order_ids = selectedIds.value.join(',')
    query.ask = 'selected'
  } else {
    query.ask = 'pool'
  }
  router.push({ path: '/admin/schedule-assistant', query })
}

async function openSettings() {
  settingsVisible.value = true
}

async function openMergeSuggest() {
  mergeSuggestVisible.value = true
}

async function loadMergeSuggest() {
  mergeSuggestLoading.value = true
  try {
    const res: any = await http.get('/merge-batches/suggestions')
    const d = res?.data || res || {}
    mergeSuggestItems.value = d.items || []
    Object.assign(mergeSuggestParams, d.params || {})
    mergeSuggestSkipped.value = d.skipped || null
  } catch (e: any) {
    ElMessage.error(e?.message || '加载合批推荐失败')
  } finally {
    mergeSuggestLoading.value = false
  }
}

async function adoptMergeSuggest(_g: any, _idx: number) {
  ElMessage.warning('合批组批已停用；生产单合单暂未开放')
}

async function loadSettings() {
  settingsLoading.value = true
  try {
    const res: any = await http.get('/schedule/settings')
    const d = res?.data || res || {}
    settingsForm.allow_schedule_on_non_workdays = !!d.allow_schedule_on_non_workdays
    settingsForm.merge_delivery_window_days = Number(d.merge_delivery_window_days ?? 7)
    settingsForm.merge_require_same_color = d.merge_require_same_color !== false
    settingsForm.merge_min_qty = Number(d.merge_min_qty ?? 0)
    settingsForm.load_warn_utilization = Number(d.load_warn_utilization ?? 0.9)
    settingsForm.actual_capacity_lookback_days = Number(d.actual_capacity_lookback_days ?? 7)
    settingsForm.schedule_blackout_dates = (d.schedule_blackout_dates || []).map((x: any) => ({
      date: x.date || '',
      note: x.note || '',
    }))
  } catch (e: any) {
    ElMessage.error(e?.message || '加载计划设置失败')
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings() {
  settingsSaving.value = true
  try {
    const blackout = settingsForm.schedule_blackout_dates
      .filter((x) => x.date)
      .map((x) => ({ date: x.date, note: x.note || undefined }))
    await http.patch('/schedule/settings', {
      allow_schedule_on_non_workdays: settingsForm.allow_schedule_on_non_workdays,
      merge_delivery_window_days: settingsForm.merge_delivery_window_days,
      merge_require_same_color: settingsForm.merge_require_same_color,
      merge_min_qty: settingsForm.merge_min_qty,
      load_warn_utilization: settingsForm.load_warn_utilization,
      schedule_blackout_dates: blackout,
      actual_capacity_lookback_days: settingsForm.actual_capacity_lookback_days,
    })
    ElMessage.success('计划设置已保存')
    settingsVisible.value = false
    await loadGanttBoard()
    if (colorPlanDraft.value) {
      ElMessage.info('日历已改，请重新出方案')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    settingsSaving.value = false
  }
}

async function patchLine(row: any, payload: Record<string, unknown>) {
  if (!draft.value || draft.value.status !== 'draft') return
  saving.value = true
  try {
    const res: any = await http.patch(`/schedule/drafts/${draft.value.id}/lines/${row.id}`, payload)
    draft.value = res.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '修改失败')
  } finally {
    saving.value = false
  }
}

async function suggestAssignments() {
  if (!draft.value) return
  saving.value = true
  try {
    const res: any = await http.post(`/schedule/drafts/${draft.value.id}/suggest-assignments`)
    draft.value = res.data
    ElMessage.success('已重算派工建议')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '重算失败')
  } finally {
    saving.value = false
  }
}

async function openAssign(row: any) {
  await Promise.all([loadWorkers(), loadTeams()])
  assignLine.value = row
  assignWorkerIds.value = (row.assignments || []).map((a: any) => a.worker_id)
  assignTeamId.value = row.team_id || null
  assignTeamMode.value = row.team_assign_mode === 'leader' ? 'leader' : 'members'
  assignEqualSplit.value = true
  assignVisible.value = true
}

async function clearAssign() {
  assignWorkerIds.value = []
  assignTeamId.value = null
  await saveAssign()
}

async function saveAssign() {
  if (!draft.value || !assignLine.value) return
  saving.value = true
  try {
    const payload: any = {
      equal_split: assignEqualSplit.value,
      assignments: assignWorkerIds.value.map((id) => ({ worker_id: id })),
    }
    // 选了班组且当前工人列表仍对应该班 → 走 team_id，便于服务端校验集体工序
    if (assignTeamId.value) {
      const team = teams.value.find((t) => t.id === assignTeamId.value)
      const expected =
        assignTeamMode.value === 'leader'
          ? team?.leader_worker_id
            ? [team.leader_worker_id]
            : []
          : (team?.members || []).map((m: any) => m.id)
      const cur = [...assignWorkerIds.value].sort((a, b) => a - b)
      const exp = [...expected].sort((a, b) => a - b)
      if (cur.length && cur.join(',') === exp.join(',')) {
        payload.team_id = assignTeamId.value
        payload.team_mode = assignTeamMode.value
        payload.assignments = []
        payload.equal_split = true
      }
    }
    const res: any = await http.put(
      `/schedule/drafts/${draft.value.id}/lines/${assignLine.value.id}/assignments`,
      payload,
    )
    draft.value = res.data
    assignVisible.value = false
    ElMessage.success('已保存派工建议')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDraft() {
  const withAssign = (draft.value?.lines || []).filter(
    (ln: any) => ln.included && (ln.assignments || []).length,
  ).length
  const tip =
    withAssign > 0
      ? `确认后将写入工序开工/完工日，并对 ${withAssign} 道工序落派工。首道缺料会阻断。`
      : '确认后将写入工序开工/完工日。当前无派工建议，确认后仍可在订单里派人。首道缺料会阻断。'
  try {
    await ElMessageBox.confirm(tip, '确认排产', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    const res: any = await http.post(`/schedule/drafts/${draft.value.id}/confirm`, {
      require_first_kit: true,
      apply_assignments: true,
    })
    draft.value = res.data
    ElMessage.success('已确认排产')
    draftDrawerVisible.value = false
    await Promise.all([loadPool(), loadDraftList()])
    if (mainTab.value === 'calendar') await loadCalendar()
  } catch (e: any) {
    const d = e?.response?.data?.detail
    ElMessage.error(typeof d === 'object' ? d.message || JSON.stringify(d) : d || e?.message || '确认失败')
  } finally {
    saving.value = false
  }
}

async function discardDraft() {
  try {
    await ElMessageBox.confirm('作废当前草稿？', '作废', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    await http.post(`/schedule/drafts/${draft.value.id}/discard`)
    draft.value = null
    draftDrawerVisible.value = false
    ElMessage.success('已作废')
    await Promise.all([loadPool(), loadDraftList()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.message || e?.message || '作废失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const raw = String(route.query.order_ids || '')
  pendingSelectIds.value = raw
    .split(',')
    .map((x) => Number(x.trim()))
    .filter((n) => Number.isFinite(n) && n > 0)
  const autoPropose =
    route.query.propose === '1' || route.query.propose === 'true' || route.query.propose === 'yes'
  const soId = Number(route.query.sales_order_id || 0)
  const legacyTab = String(route.query.tab || '')
  pendingItemIds.value = parseItemIds(route.query.item_ids)
  pendingAutoPropose.value =
    pendingItemIds.value.length > 0 &&
    (route.query.propose === '1' || route.query.propose === 'true' || route.query.propose === 'yes')
  if (String(route.query.from || '') === 'supplement') {
    colorAsRush.value = false
  }
  if (legacyMode.value && legacyTab === 'calendar') {
    mainTab.value = 'calendar'
    void loadCalendar()
  } else if (legacyMode.value && legacyTab === 'weekly') {
    mainTab.value = 'weekly'
    void loadWeekly()
  } else if (
    legacyMode.value &&
    (legacyTab === 'pool' || (autoPropose && !pendingItemIds.value.length))
  ) {
    mainTab.value = 'pool'
  } else {
    mainTab.value = 'color'
  }
  if (Number.isFinite(soId) && soId > 0) {
    colorFilterSalesOrderId.value = soId
    colorFilterSalesOrderNo.value = String(route.query.sales_order_no || '')
    colorPoolTouched.value = true
    colorPoolOpen.value = true
    mainTab.value = 'color'
  }
  if (pendingItemIds.value.length) {
    colorPoolTouched.value = true
    colorPoolOpen.value = true
    mainTab.value = 'color'
  }
  if (mainTab.value === 'color') {
    await Promise.all([loadColorPool(), loadGanttBoard(), loadSettings()])
    const rescheduleId = Number(route.query.reschedule || 0)
    if (rescheduleId > 0) openReschedule(rescheduleId)
    if (autoPropose && !legacyMode.value && !pendingItemIds.value.length) {
      colorPoolTouched.value = true
      colorPoolOpen.value = true
      ElMessage.info('请勾选待排款后出方案。确认前不下发。')
    } else if (!colorFilterSalesOrderId.value && !pendingItemIds.value.length) {
      maybeAutoOpenColorPool()
    }
  } else {
    await loadPool()
    void loadSettings()
  }
  if (legacyMode.value) {
    void loadDraftList()
    void loadMergeBatchOptions()
  }
  if (legacyMode.value && autoPropose) {
    mainTab.value = 'pool'
    if (pendingSelectIds.value.length) {
      selectedIds.value = [...pendingSelectIds.value]
    }
    await nextTick()
    await generateProposals()
  }
})

watch(legacyMode, (on) => {
  if (on || mainTab.value === 'color') return
  mainTab.value = 'color'
  void loadColorPool()
  void loadGanttBoard()
})

watch(
  () => route.query.item_ids,
  (v) => {
    pendingItemIds.value = parseItemIds(v)
    pendingAutoPropose.value =
      pendingItemIds.value.length > 0 &&
      (route.query.propose === '1' || route.query.propose === 'true' || route.query.propose === 'yes')
    if (pendingItemIds.value.length) {
      mainTab.value = 'color'
      colorPoolOpen.value = true
      void loadColorPool()
    }
  },
)

watch(
  () => route.query.order_ids,
  (v) => {
    const raw = String(v || '')
    pendingSelectIds.value = raw
      .split(',')
      .map((x) => Number(x.trim()))
      .filter((n) => Number.isFinite(n) && n > 0)
    if (legacyMode.value && pendingSelectIds.value.length) {
      mainTab.value = 'pool'
      void loadPool()
    }
  },
)

watch(
  () =>
    [route.path, String(route.query.sales_order_id || ''), String(route.query.sales_order_no || '')] as const,
  async ([path, id, no]) => {
    if (path !== '/admin/schedule') return
    const soId = Number(id || 0)
    if (!(Number.isFinite(soId) && soId > 0)) return
    colorFilterSalesOrderId.value = soId
    colorFilterSalesOrderNo.value = no
    colorPoolTouched.value = true
    colorPoolOpen.value = true
    mainTab.value = 'color'
    if (colorPool.value.length) await applySalesOrderFocus()
    else await loadColorPool()
  },
)

onActivated(() => {
  if (route.path !== '/admin/schedule') return
  const soId = Number(route.query.sales_order_id || 0)
  if (Number.isFinite(soId) && soId > 0) {
    colorFilterSalesOrderId.value = soId
    const no = String(route.query.sales_order_no || '')
    if (no) colorFilterSalesOrderNo.value = no
    colorPoolTouched.value = true
    colorPoolOpen.value = true
    void applySalesOrderFocus()
    return
  }
  if (colorFilterSalesOrderId.value) {
    colorFilterSalesOrderId.value = null
    colorFilterSalesOrderNo.value = ''
  }
})
</script>

<style scoped>
.schedule-page {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.schedule-hero {
  margin-bottom: 4px;
  padding-bottom: 4px;
  flex-shrink: 0;
}
.schedule-hero .page-title {
  font-size: 18px;
}
.schedule-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.schedule-workbench {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  overflow: hidden;
}
.schedule-stage-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.schedule-stage {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 6px;
  padding: 8px 14px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
  color: #0f172a;
}
.schedule-stage.is-on {
  border-color: #0076ff;
  background: #e8f3ff;
  color: #005fcc;
}
.schedule-stage-n {
  margin-left: 6px;
  color: #64748b;
  font-weight: 500;
}
.schedule-stage.is-on .schedule-stage-n {
  color: #005fcc;
}
.schedule-stage-arrow {
  color: #94a3b8;
  font-size: 14px;
}
.schedule-stage-more {
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.schedule-inner-tabs {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.schedule-inner-tabs :deep(.el-tabs__header) {
  display: none;
}
.schedule-inner-tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.schedule-inner-tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.schedule-panel :deep(.admin-table-host) {
  flex: 1 1 auto;
  min-height: 0;
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
.muted {
  color: var(--el-text-color-secondary);
}
.tip {
  font-size: 12px;
}
.color-draft-preview {
  margin-top: 16px;
}
.color-draft-preview .section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.draft-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  font-size: 13px;
  color: #0f172a;
  font-weight: 500;
}
.draft-summary.is-warn {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}
.draft-order-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.3;
}
.draft-order-delivery {
  font-size: 11px;
  color: #64748b;
}
.assign-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.assign-team-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.assign-fold-toggle {
  border: none;
  background: transparent;
  padding: 0;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
}
.assign-fold-toggle:hover {
  color: #2563eb;
}
.assign-fold-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  width: 100%;
}
.assign-tag {
  margin: 0;
}
.cal-legend {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}
.cal-leg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.cal-leg::before {
  content: '';
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.cal-leg.holiday::before {
  background: #fecaca;
  border: 1px solid #f87171;
}
.cal-leg.off::before {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
}
.cal-leg.makeup::before {
  background: #dbeafe;
  border: 1px solid #60a5fa;
}
.cal-month {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 1px;
  background: var(--el-border-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  min-height: 560px;
}
.cal-dow {
  background: #f8fafc;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  text-align: center;
}
.cal-cell {
  background: #fff;
  min-height: 110px;
  display: flex;
  flex-direction: column;
  padding: 6px;
  gap: 4px;
}
.cal-cell.is-other {
  background: #fafafa;
  opacity: 0.55;
}
.cal-cell.is-off {
  background: #f8fafc;
}
.cal-cell.is-holiday {
  background: #fff1f2;
}
.cal-cell.is-makeup {
  background: #eff6ff;
}
.cal-cell.is-today {
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
}
.cal-cell-head {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 20px;
}
.cal-date {
  font-size: 13px;
  color: #0f172a;
}
.cal-cell.is-holiday .cal-date {
  color: #dc2626;
}
.cal-badge {
  font-size: 11px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 3px;
  background: #e2e8f0;
  color: #475569;
}
.cal-badge.holiday {
  background: #fecaca;
  color: #b91c1c;
}
.cal-badge.makeup {
  background: #bfdbfe;
  color: #1d4ed8;
}
.cal-count {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}
.cal-cell-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  overflow: hidden;
}
.cal-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  text-align: left;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 4px;
  padding: 2px 5px;
  cursor: pointer;
  min-width: 0;
  transition: background 0.15s ease;
}
.cal-chip:hover {
  background: #eff6ff;
  border-color: #bfdbfe;
}
.cal-chip.rush {
  background: #fff7ed;
  border-color: #fed7aa;
}
.cal-chip-name {
  font-size: 11px;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cal-chip-meta {
  font-size: 10px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.cal-more {
  font-size: 11px;
  color: #64748b;
  padding: 0 2px;
}
.proposal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 12px;
  min-height: 120px;
  align-items: stretch;
}
.proposal-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}
.proposal-card.is-recommended {
  border-color: #86efac;
  background: #f0fdf4;
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.2);
}
.proposal-scope {
  margin: 0 0 8px;
  font-size: 12px;
  color: #475569;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 6px 10px;
}
.proposal-recommend {
  margin: 0 0 8px;
  font-size: 13px;
  color: #166534;
  background: #ecfdf5;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
  padding: 8px 10px;
  font-weight: 600;
}
.proposal-recommend.is-tie {
  color: #92400e;
  background: #fffbeb;
  border-color: #fde68a;
}
.proposal-diff-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #0f172a;
  font-weight: 500;
}
.proposal-head-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.proposal-spark {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 36px;
  margin-bottom: 4px;
  padding: 4px 2px 0;
}
.proposal-spark-cell {
  flex: 1;
  min-width: 4px;
  height: 100%;
  display: flex;
  align-items: flex-end;
}
.proposal-spark-cell :deep(.el-tooltip__trigger) {
  display: flex;
  align-items: flex-end;
  width: 100%;
  height: 100%;
}
.proposal-spark-legend {
  margin: 0 0 10px;
  font-size: 11px;
  color: #94a3b8;
  line-height: 1.3;
}
.proposal-spark-bar {
  display: block;
  width: 100%;
  border-radius: 2px 2px 0 0;
  background: #94a3b8;
  cursor: default;
}
.proposal-spark-bar.is-ok {
  background: #34d399;
}
.proposal-spark-bar.is-warn {
  background: #fbbf24;
}
.proposal-spark-bar.is-over {
  background: #f87171;
}
.proposal-spark-bar.is-empty {
  background: #e2e8f0;
}
.proposal-skip {
  margin: 0 0 8px;
  font-size: 12px;
}
.proposal-skip-toggle {
  border: 0;
  background: transparent;
  color: #64748b;
  padding: 0;
  cursor: pointer;
  font-size: 12px;
}
.proposal-skip-toggle:hover {
  color: #0f172a;
}
.proposal-skip-list {
  margin-top: 4px;
  color: #64748b;
  line-height: 1.4;
  word-break: break-all;
}
.proposal-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: auto;
  padding-top: 10px;
}
.proposal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.proposal-compare {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e2e8f0;
}
.proposal-compare-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.proposal-compare-label {
  font-size: 11px;
  color: #94a3b8;
}
.proposal-compare-value {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}
.proposal-compare-value.is-bad {
  color: #dc2626;
}
.proposal-compare-sub {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.proposal-summary {
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
  margin: 0 0 10px;
  min-height: 54px;
}
.proposal-risks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}
@media (max-width: 1100px) {
  .cal-month {
    min-height: 0;
  }
  .cal-cell {
    min-height: 88px;
  }
}
.blackout-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.blackout-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.blackout-add-row {
  margin-left: -4px;
}
.merge-suggest-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
  background: #fff;
}
.merge-suggest-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.merge-suggest-orders {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.merge-suggest-tag {
  margin: 0;
}
.merge-suggest-actions {
  display: flex;
  justify-content: flex-end;
}
.is-bad-num {
  color: #dc2626;
  font-weight: 700;
}
.weekly-headline {
  margin: 12px 0 0;
  font-size: 13px;
  color: #334155;
}
.tip {
  font-size: 12px;
}
.color-draft-preview {
  flex-shrink: 0;
  margin-top: 12px;
  padding: 12px;
  background: #fff;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
}
.color-draft-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.color-draft-preview .section-label {
  font-size: 13px;
  font-weight: 600;
  margin: 0;
}
.color-plan-preview {
  flex-shrink: 0;
  margin-top: 12px;
  padding: 12px;
  background: #fff;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
}
.color-plan-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.color-plan-preview .section-label {
  font-size: 13px;
  font-weight: 600;
  margin: 0;
}
.color-plan-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.color-plan-strategies {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}
.color-board {
  gap: 8px;
  overflow: hidden;
}
.gantt-host {
  position: relative;
  flex: 1 1 auto;
  min-height: 160px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.gantt-host :deep(.gantt) {
  flex: 1 1 auto;
  min-height: 0;
}
.gantt-settings-hint {
  font-size: 12px;
  font-weight: 600;
  color: #005fcc;
}
.gantt-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.gantt-nav-chevron {
  width: 28px;
  height: 28px;
  border: 1px solid #d0d7e2;
  border-radius: 6px;
  background: #fff;
  font-size: 18px;
  line-height: 1;
  color: #334155;
  cursor: pointer;
}
.gantt-nav-chevron:hover {
  border-color: #0076ff;
  color: #005fcc;
}
.gantt-nav-range {
  min-width: 108px;
  padding: 4px 8px;
  border: 0;
  background: transparent;
  text-align: center;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
  cursor: pointer;
}
.gantt-nav-range:hover {
  color: #005fcc;
}
.gantt-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}
.strategy-seg {
  display: inline-flex;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}
.strategy-seg button {
  border: 0;
  border-right: 1px solid #d0d7e2;
  background: #fff;
  padding: 6px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #0f172a;
  cursor: pointer;
}
.strategy-seg button:last-child {
  border-right: 0;
}
.strategy-seg button.is-on {
  background: #0076ff;
  color: #fff;
}
.strategy-seg .n {
  margin-left: 4px;
  font-weight: 500;
  font-size: 12px;
  opacity: 0.75;
}
.strategy-seg button.is-on .n {
  opacity: 0.9;
}
.gantt-alert {
  flex-shrink: 0;
  margin: 0;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
}
.gantt-alert.is-warn {
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
}
.gantt-alert.is-bad {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}
.color-pool-fab {
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 4;
  border: 0;
  border-radius: 999px;
  padding: 10px 16px;
  background: #0076ff;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 8px 20px rgba(0, 118, 255, 0.28);
  cursor: pointer;
}
.color-pool-fab:hover {
  background: #005fcc;
}
.merge-ask-block {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #eef2f7;
}
.merge-ask-block:last-of-type {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: 0;
}
.merge-ask-title {
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 6px;
}
.merge-ask-label {
  font-size: 12px;
  color: #64748b;
  margin: 0 0 2px;
}
.merge-ask-label.is-left {
  color: #c2410c;
  margin-top: 8px;
}
.merge-ask-cust {
  margin: 0 0 8px;
  padding-left: 18px;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
}
.merge-ask-cust.is-left {
  color: #9a3412;
}
.merge-ask-gap {
  margin: 0 0 8px;
  color: #c2410c;
  font-size: 13px;
}
.color-pool-scrim {
  position: absolute;
  inset: 0;
  z-index: 5;
  background: rgba(15, 23, 42, 0.18);
}
.color-pool-overlay {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 6;
  height: 45vh;
  min-height: 280px;
  max-height: 72%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-top: 1px solid #d0d7e2;
  border-radius: 12px 12px 0 0;
  box-shadow: 0 -10px 28px rgba(15, 23, 42, 0.12);
}
.color-pool-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px 8px;
  flex-shrink: 0;
}
.color-pool-body {
  padding: 0 14px 12px;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.color-pool-body .admin-toolbar {
  margin-bottom: 8px;
  flex-shrink: 0;
}
.color-pool-table {
  flex: 1 1 auto;
  min-height: 0;
}
.color-pool-toggle {
  align-self: flex-start;
  border: 0;
  background: transparent;
  padding: 4px 0;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  cursor: pointer;
}
.color-pool-toggle .muted {
  margin-left: 8px;
  font-weight: 400;
}
:deep(.el-table .is-from-sales > td.el-table__cell) {
  background: #e8f3ff;
}
.confirm-windows {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 2px 0;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
}
.confirm-window {
  white-space: nowrap;
}
.confirm-window__note {
  margin-top: 1px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  white-space: normal;
  line-height: 1.35;
}
.assign-btn-unset {
  font-weight: 600;
}
</style>
