<template>
  <view :class="['page', 'native-report-page', { 'cut-flow-mode': kind === 'flow-card' && flowCard, 'report-sticky-mode': reportStickyMode }]">
    <view v-if="issueNotice" class="cut-success-popup">
      <text class="cut-success-icon">✓</text>
      <text>{{ issueNotice }}</text>
    </view>
    <view v-if="loadingPage" class="report-loading">
      <view class="report-loading-pulse" />
      <view class="report-loading-lines">
        <view class="report-loading-line report-loading-line--wide" />
        <view class="report-loading-line" />
        <view class="report-loading-line report-loading-line--short" />
      </view>
      <text>正在加载扫码信息…</text>
    </view>
    <view v-else-if="errorMessage" class="card report-error-card">
      <text class="report-error-icon">!</text>
      <strong>加载失败</strong>
      <text>{{ errorMessage }}</text>
      <button class="report-retry-button" @click="retryLoad">重试</button>
    </view>

    <template v-else-if="kind === 'station' && station">
      <view class="report-heading"><text>扫码报工</text><text>{{ station.name }}</text></view>
      <view class="card report-info-card">
        <view class="report-info-badge">{{ station.process_name || '工序' }}</view>
        <strong>{{ station.name }}</strong>
        <text>编码 {{ station.code }}<text v-if="station.location"> · {{ station.location }}</text></text>
      </view>
      <view v-if="candidates.length" class="card report-task-picker" @click="candidatePicker = true">
        <view><text class="field-label">当前任务</text><strong>{{ selected?.order_no || '请选择' }}</strong><text>{{ selected?.customer_name || '' }} · {{ selected?.completed_qty || 0 }}/{{ selected?.plan_qty || 0 }}</text></view>
        <text class="report-task-picker__chev">›</text>
      </view>
      <view class="form-card-native">
        <view v-if="!selected" class="native-field"><text>单号</text><input v-model.trim="orderNo" placeholder="请输入生产单号" /></view>
        <view class="native-field"><text>颜色</text><input v-model.trim="colorName" placeholder="可选" /></view>
        <view class="native-field"><text>尺码</text><input v-model.trim="sizeValue" placeholder="可选" /></view>
        <view class="native-field native-field--qty"><text>数量</text><view class="report-qty-stepper report-qty-stepper--inline"><button class="report-qty-stepper__btn" @click="stepQty('qty', -1)">−</button><input v-model="qty" type="number" placeholder="0" /><button class="report-qty-stepper__btn" @click="stepQty('qty', 1)">+</button><text>双</text></view></view>
        <view v-for="row in workshopCounts" :key="workshopKey(row)" class="native-field native-field--qty"><text>{{ row.label }}</text><input :value="workshopQtyDraft[workshopKey(row)]" type="digit" :placeholder="row.last_qty != null ? `上次 ${row.last_qty}` : '车间剩余'" @input="onWorkshopQty(row, $event)" /><text>{{ row.unit_name || '' }}</text></view>
        <picker :range="reportTypes" range-key="label" @change="pickReportType"><view class="native-field"><text>类型</text><text>{{ reportTypeLabel }}　›</text></view></picker>
      </view>
      <view class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="submitting" @click="submitStation">提交报工{{ Number(qty) > 0 ? ` · ${qty} 双` : '' }}</button>
      </view>
    </template>

    <template v-else-if="kind === 'trace' && unit">
      <view class="report-heading"><text>框码 / 捆码报工</text><text>{{ unit.code }}</text></view>
      <view class="card report-info-card">
        <view class="report-info-badge">{{ unit.unit_type === 'basket' ? '筐卡' : '扎捆' }}</view>
        <strong>{{ unit.code }}</strong>
        <text>{{ unit.qty }} 双 · {{ unit.status }}</text>
        <text>订单 {{ unit.order_no || unit.header_no }} · {{ unit.customer_name || '—' }}</text>
        <text>{{ unit.product_code || '—' }} · 色码 {{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }}</text>
      </view>
      <view v-if="unit.reported" class="card report-warning"><strong>该框码已完成报工</strong><text>{{ unit.reported_process_name || '工序' }} · {{ unit.reported_worker_name || '员工' }} · {{ unit.reported_qty || 0 }} 双</text><text>{{ formatTime(unit.reported_at) }}</text><text>一个框码只能报工一次，不可重复提交。</text></view>
      <view v-else class="form-card-native">
        <view class="native-field"><text>报工员工</text><text>{{ currentEmployeeName }}</text></view>
        <view class="native-field"><text>员工工序</text><text>{{ processName || '未匹配' }}</text></view>
        <view class="native-field native-field--qty"><text>数量</text><view class="report-qty-stepper report-qty-stepper--inline"><button class="report-qty-stepper__btn" @click="stepQty('qty', -1)">−</button><input v-model="qty" type="number" placeholder="0" /><button class="report-qty-stepper__btn" @click="stepQty('qty', 1)">+</button><text>双</text></view></view>
        <view v-for="row in workshopCounts" :key="workshopKey(row)" class="native-field native-field--qty"><text>{{ row.label }}</text><input :value="workshopQtyDraft[workshopKey(row)]" type="digit" :placeholder="row.last_qty != null ? `上次 ${row.last_qty}` : '车间剩余'" @input="onWorkshopQty(row, $event)" /><text>{{ row.unit_name || '' }}</text></view>
        <picker :range="reportTypes" range-key="label" @change="pickReportType"><view class="native-field"><text>类型</text><text>{{ reportTypeLabel }}　›</text></view></picker>
      </view>
      <view v-if="!unit.reported" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="submitting" @click="submitTrace">报本工序{{ Number(qty) > 0 ? ` · ${qty} 双` : '' }}</button>
      </view>
      <view v-if="unit.logs?.length" class="card report-history"><strong>过站历程</strong><view v-for="row in unit.logs" :key="row.id"><text>{{ row.process_name || row.action }} · {{ row.qty || '' }}</text><text>{{ formatTime(row.created_at) }}</text></view></view>
    </template>

    <template v-else-if="kind === 'carton' && carton">
      <view class="report-heading"><text>箱唛作业</text><text>{{ carton.code }}</text></view>
      <view class="card report-info-card">
        <view class="report-info-badge">包装计件</view>
        <strong>{{ carton.code }}</strong>
        <text>{{ carton.header_no || carton.order_no }}</text>
        <text>{{ carton.product_code || '—' }}{{ carton.customer_name ? ` · ${carton.customer_name}` : '' }}</text>
      </view>
      <view v-if="carton.reported_work_log_id" class="card report-warning">该箱已经报工，请勿重复扫描</view>
      <view v-else class="card carton-action-card">
        <text class="carton-action-card__qty">{{ carton.total_qty }}</text>
        <text class="carton-action-card__unit">双</text>
        <text class="carton-action-card__hint">装完一箱扫一下箱唛，系统自动按箱内双数记包装计件</text>
      </view>
      <view v-if="canWarehouse">
        <view v-if="carton.shipment_id" class="card report-warning">该箱已出库，请勿重复扫描</view>
      </view>
      <view v-if="showCartonSticky" class="cut-sticky-bar">
        <button v-if="!carton.reported_work_log_id" class="primary-button cut-sticky-button" :loading="submitting" @click="submitCarton">确认报工 · {{ carton.total_qty }} 双</button>
        <button v-else-if="canWarehouse && carton.reported_work_log_id && !carton.warehoused_at" class="primary-button cut-sticky-button" :loading="submitting" @click="warehouseCarton">确认本箱入库</button>
        <button v-else-if="canWarehouse && carton.warehoused_at && !carton.shipment_id" class="primary-button cut-sticky-button danger-button" :loading="submitting" @click="shipCarton">验箱并确认出库</button>
      </view>
    </template>

    <template v-else-if="kind === 'basket' && basketInfo">
      <view class="report-heading"><text>永久框码</text><text>{{ basketInfo.basket_code }}</text></view>
      <view class="card report-info-card">
        <view class="report-info-badge">{{ basketStatusLabel(basketInfo.status) }}</view>
        <strong>{{ basketInfo.basket_code }}</strong>
        <text v-if="basketInfo.journey">{{ basketInfo.journey.header_no }} · {{ basketInfo.journey.brand_name || '未指定品牌' }} · {{ basketInfo.journey.qty }}双</text>
        <text v-else>当前空闲，可绑定生产任务</text>
      </view>
      <view v-if="!basketInfo.journey" class="card report-tip">该框当前空闲。报工请扫描生产流转卡，填写数量。</view>
      <button v-else class="primary-button" @click="openBasketTask">打开当前生产任务</button>
    </template>

    <template v-else-if="kind === 'subcontract' && subcontractReceipt">
      <view class="report-heading"><text>外发验收登记</text><text>{{ subcontractReceipt.subcontract_no }}</text></view>
      <view class="card report-info-card">
        <view class="report-info-badge">{{ subcontractReceipt.status === 'received' ? '已完工' : '外发中' }}</view>
        <strong>{{ subcontractReceipt.linked_no || '—' }}</strong>
        <text>{{ subcontractReceipt.product_code || '—' }} · {{ subcontractReceipt.color_name || '—' }}</text>
        <text>{{ subcontractReceipt.process_name || '—' }} · 外发 {{ subcontractReceipt.total_qty || 0 }} 双</text>
        <text>已完工 {{ subcontractReceipt.received_qty || 0 }} 双 · 待完工 {{ subcontractReceipt.outstanding_qty || 0 }} 双</text>
        <text>废品 {{ subcontractReceipt.loss_qty || 0 }} 双</text>
      </view>
      <view v-if="subcontractReceipt.status === 'received'" class="card report-warning">该外发单已全部完工，无需重复登记。</view>
      <view v-else class="form-card-native">
        <view class="native-field native-field--qty"><text>完工数量</text><view class="subcontract-number-input"><input v-model="subcontractReceiptQty" type="number" placeholder="0" /><text>双</text></view></view>
        <view class="native-field native-field--qty"><text>废品</text><text>{{ subcontractReceipt.loss_qty || 0 }} 双</text></view>
        <view class="native-field"><text>送货单号</text><input v-model.trim="subcontractReceiptDeliveryNote" maxlength="80" placeholder="选填" /></view>
        <view class="native-field"><text>备注</text><input v-model.trim="subcontractReceiptNote" placeholder="可选" /></view>
      </view>
      <view v-if="subcontractReceipt.status !== 'received'" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="submitting" @click="submitSubcontractReceipt">确认验收</button>
      </view>
    </template>

    <template v-else-if="kind === 'flow-card' && flowCard">
      <view v-if="flowAction && flowAction !== 'defect' && flowAction !== 'report'" class="cut-order-strip">
        <view class="cut-order-strip__main">
          <text class="cut-order-strip__no">{{ flowCard.header_no }}</text>
          <text class="cut-order-strip__meta">{{ flowCard.product_code || '—' }} · {{ flowCard.color_name || '—' }}</text>
        </view>
        <text class="cut-order-strip__status">{{ flowStatusLabel }}</text>
      </view>

      <view v-if="!flowAction" class="card cut-order-card">
        <view class="cut-order-body">
          <image v-if="orderProductImageUrl" class="cut-order-image" :src="orderProductImageUrl" mode="aspectFill" @click="previewOrderProductImage" />
          <view v-else class="cut-order-image cut-order-image--empty">暂无图片</view>
          <view class="cut-order-copy">
            <view class="cut-order-top">
              <text class="cut-order-tag">生产单</text>
              <text class="cut-batch-label">{{ flowStatusLabel }}</text>
            </view>
            <text class="cut-order-no">{{ flowCard.header_no }}</text>
          </view>
        </view>
        <view class="cut-order-meta-grid">
          <view><text>工厂型号</text><strong>{{ flowCard.product_code || '—' }}</strong></view>
          <view><text>颜色</text><strong>{{ flowCard.color_name || '—' }}</strong></view>
          <view><text>计划</text><strong>{{ asReportPairs(flowCard.total_qty) }} 双</strong></view>
          <view><text>交期</text><strong>{{ flowCard.delivery_date || '—' }}</strong></view>
        </view>
      </view>

      <view v-if="flowAction === 'report'" class="card cut-progress-card report-floor-head">
        <view class="cut-order-strip cut-order-strip--merged">
          <view class="cut-order-strip__main">
            <text class="cut-order-strip__no">{{ flowCard.header_no }}</text>
            <text class="cut-order-strip__meta">{{ flowCard.product_code || '—' }} · {{ flowCard.color_name || '—' }}</text>
          </view>
        </view>
        <view class="cut-progress-section">
          <view class="cut-progress-inline">
            <text>已报 {{ asReportPairs(reportedSegmentQty) }} / {{ asReportPairs(segmentPlanQty) }} 双</text>
            <view class="cut-progress-track"><view class="cut-progress-fill" :style="{ width: `${segmentProgressPct}%` }" /></view>
          </view>
        </view>
      </view>

      <view v-if="!flowAction" class="flow-action-grid flow-action-grid--secondary">
        <button class="flow-action-card flow-action-card--report" @click="openFlowAction('report')">
          <text class="flow-action-icon">工</text><strong>报工</strong><text>登记本次合格产量</text>
        </button>
        <button class="flow-action-card flow-action-card--report" @click="openFlowAction('report-history')">
          <text class="flow-action-icon">录</text><strong>报工记录</strong><text>查看本段报工明细</text>
        </button>
        <button class="flow-action-card flow-action-card--task" :disabled="!hasFlowFeature('claim_task')" @click="openFlowAction('claim')">
          <text class="flow-action-icon">任</text><strong>领任务</strong><text>{{ hasFlowFeature('claim_task') ? `领取${segmentLabel}任务双数` : '后台未开通' }}</text>
        </button>
        <button class="flow-action-card flow-action-card--task" @click="openFlowAction('claim-history')">
          <text class="flow-action-icon">录</text><strong>领任务记录</strong><text>查看已领取人员</text>
        </button>
        <button class="flow-action-card flow-action-card--defect" :disabled="!hasFlowFeature('register_defect')" @click="openFlowAction('defect')">
          <text class="flow-action-icon">废</text><strong>报废</strong><text>{{ hasFlowFeature('register_defect') ? '登记报废数量与损失' : '后台未开通' }}</text>
        </button>
        <button class="flow-action-card flow-action-card--defect" @click="openFlowAction('defect-history')">
          <text class="flow-action-icon">录</text><strong>报废记录</strong><text>查看报废数量与损失</text>
        </button>
        <button class="flow-action-card flow-action-card--issue" :disabled="!hasFlowFeature('material_issue')" @click="openFlowAction('issue')">
          <text class="flow-action-icon">料</text><strong>领料</strong><text>{{ hasFlowFeature('material_issue') ? '提交本段领料申请' : '后台未开通' }}</text>
        </button>
        <button class="flow-action-card flow-action-card--issue" @click="openFlowAction('issue-history')">
          <text class="flow-action-icon">录</text><strong>领料记录</strong><text>查看本段领料明细</text>
        </button>
        <button class="flow-action-card flow-action-card--subcontract" :disabled="!canCreateSubcontract" @click="openFlowAction('subcontract')">
          <text class="flow-action-icon">发</text><strong>外发</strong><text>{{ canCreateSubcontract ? '创建外发加工单' : '后台未开通' }}</text>
        </button>
        <button class="flow-action-card flow-action-card--subcontract" @click="openFlowAction('subcontract-history')">
          <text class="flow-action-icon">录</text><strong>外发记录</strong><text>查看外发加工单</text>
        </button>
      </view>

      <view v-if="flowAction === 'report-history'" class="card flow-history-panel">
        <view v-if="!cutHistory.length" class="cut-history-empty">本单暂无报工记录</view>
        <view v-for="row in cutHistory" :key="row.id" class="cut-history-report"><view><strong>{{ row.worker_name || '—' }}</strong><text>{{ formatTime(row.created_at) }}</text></view><text>{{ row.qualified_qty || 0 }}双{{ row.defect_qty ? ` · 不良${row.defect_qty}` : '' }}</text></view>
      </view>
      <view v-if="flowAction === 'claim-history'" class="card flow-history-panel">
        <view v-if="!claimHistory.length" class="cut-history-empty">本单暂无领任务记录</view>
        <view v-for="row in claimHistory" :key="row.worker_id" class="cut-history-report">
          <view>
            <strong>{{ row.worker_name || '—' }}</strong>
            <text>{{ formatTime(row.created_at) }}{{ row.process_name ? ` · ${row.process_name}` : '' }}</text>
          </view>
          <text>{{ row.quota_qty != null ? `${row.quota_qty}双` : '不限' }}</text>
        </view>
      </view>
      <view v-if="flowAction === 'defect-history'" class="card flow-history-panel">
        <view v-if="!defectHistory.length" class="cut-history-empty">本单暂无报废记录</view>
        <view v-for="row in defectHistory" :key="row.id" class="cut-history-report">
          <view>
            <strong>{{ row.size_value || '—' }}码 · 共 {{ row.qty || 0 }}</strong>
            <text>{{ formatTime(row.created_at) }} · {{ row.found_by_worker_name || row.found_by_user_name || '—' }}</text>
          </view>
          <text>{{ defectHistoryPartyLabel(row) }} · {{ defectHistoryStatusLabel(row) }} · ¥{{ money(row.loss_amount) }}</text>
        </view>
      </view>
      <view v-if="flowAction === 'issue-history'" class="card flow-history-panel">
        <view v-if="!issueHistory.length" class="cut-history-empty">本单暂无领料记录</view>
        <view v-for="doc in issueHistory" :key="doc.id" class="cut-history-block">
          <view class="cut-history-head"><view><strong>{{ doc.issue_kind || '领料' }}</strong><text>{{ formatTime(doc.posted_at || doc.created_at) }} · {{ doc.created_by_name || '—' }}</text></view><text :class="['cut-doc-status', doc.status]">{{ stockDocStatusLabel(doc.status) }}</text></view>
          <view v-for="line in doc.lines || []" :key="line.id" class="cut-history-line"><text>{{ materialName(line) }}</text><text>{{ formatQty(line.qty) }} {{ line.pricing_unit_name || '' }} · {{ formatQty(line.pairs ?? line.derived_pairs) }}双</text></view>
        </view>
      </view>
      <view v-if="flowAction === 'subcontract-history'" class="card flow-history-panel">
        <view v-if="!subcontractHistory.length" class="cut-history-empty">本单暂无外发记录</view>
        <view v-for="row in subcontractHistory" :key="row.id" class="cut-history-report">
          <view>
            <strong>{{ row.subcontract_no }} · {{ row.partner_name || '—' }}</strong>
            <text>{{ row.process_name || '—' }} · {{ formatTime(row.created_at) }}</text>
          </view>
          <text>{{ subcontractStatusLabel(row.status) }} · {{ row.total_qty || 0 }}双</text>
        </view>
      </view>

      <view v-if="flowAction === 'claim'" class="card flow-single-panel claim-form-panel">
        <text class="flow-single-kicker">{{ segmentLabel }}任务</text>
        <strong>领取当前{{ segmentLabel }}任务</strong>
        <text>领取数量会计入你的当前任务。剩余双数其他人还可以继续领取。</text>
        <view class="claim-qty-stats">
          <view><text>计划</text><strong>{{ claimPlanQty }} 双</strong></view>
          <view><text>已领</text><strong>{{ claimTakenQty }} 双</strong></view>
          <view><text>可领</text><strong>{{ claimRemainingQty }} 双</strong></view>
        </view>
        <text v-if="claimMyQty > 0">你当前已领 {{ claimMyQty }} 双，提交后会改成新数量。</text>
        <text v-else-if="claimRemainingQty <= 0">该段任务数量已被领完。</text>
        <view class="native-field native-field--qty">
          <text>领取数量</text>
          <view class="report-qty-stepper report-qty-stepper--inline">
            <button class="report-qty-stepper__btn" @click="stepQty('claimQty', -1)">−</button>
            <input v-model="claimQty" type="number" placeholder="0" />
            <button class="report-qty-stepper__btn" @click="stepQty('claimQty', 1)">+</button>
            <text>双</text>
          </view>
        </view>
      </view>
      <view v-if="flowAction === 'claim'" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :disabled="claimRemainingQty <= 0" :loading="claimSubmitting" @click="claimTask">确认领取{{ Number(claimQty) > 0 ? ` · ${claimQty} 双` : '' }}</button>
      </view>

      <view v-if="flowAction === 'subcontract'" class="card flow-single-panel subcontract-form-panel">
        <view class="subcontract-form-section">
          <text class="subcontract-field-label">外发工序（可多选）</text>
          <view class="subcontract-process-list">
            <view
              v-for="row in defectProcessOptions"
              :key="row.id"
              :class="['subcontract-process-option', { selected: subcontractProcessIds.includes(Number(row.id)) }]"
              @click="toggleSubcontractProcess(row)"
            >
              <text class="subcontract-process-check">{{ subcontractProcessIds.includes(Number(row.id)) ? '✓' : '' }}</text>
              <view><strong>{{ row.label || row.process_name }}</strong><text>已完成 {{ row.completed_qty || 0 }} / {{ row.plan_qty || flowCard.total_qty || 0 }}</text></view>
            </view>
          </view>
        </view>
        <picker :range="subcontractPartners" range-key="display_name" @change="pickSubcontractPartner">
          <view class="native-field"><text>外加工厂</text><text>{{ selectedSubcontractPartner?.display_name || '请选择' }}　›</text></view>
        </picker>
        <view class="native-field"><text>外发数量</text><view class="subcontract-number-input"><input v-model="subcontractQty" type="number" placeholder="0" /><text>双</text></view></view>
        <picker mode="date" :value="subcontractDeliveryDate" @change="pickSubcontractDeliveryDate">
          <view class="native-field"><text>交货时间</text><text>{{ subcontractDeliveryDate || '请选择' }}　›</text></view>
        </picker>
        <view class="native-field"><text>材料单价</text><view class="subcontract-number-input"><text>¥</text><input v-model="subcontractMaterialUnitPrice" type="digit" placeholder="0.00" @input="subcontractMaterialPriceManual = true" /></view></view>
        <text class="subcontract-price-hint">{{ subcontractMaterialPriceHint }}</text>
        <view class="native-field"><text>工价</text><view class="subcontract-number-input"><text>¥</text><input v-model="subcontractUnitPrice" type="digit" placeholder="0.00" /></view></view>
        <view class="native-field"><text>备注</text><input v-model.trim="subcontractNotes" placeholder="可选" /></view>
      </view>
      <view v-if="flowAction === 'subcontract'" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="subcontractSubmitting" @click="submitSubcontract">创建外发单</button>
      </view>

      <view v-if="flowAction === 'defect'" class="card flow-single-panel defect-form-panel">
        <picker v-if="defectResponsiblePartyType !== 'subcontractor' && departmentRouteProcesses.length" class="defect-found-process" :range="departmentRouteProcesses" range-key="label" @change="pickDefectProcess">
          <view class="defect-attention">
            <view class="native-field defect-loss-head defect-attention__head">
              <text>发现工序</text>
              <text class="defect-loss-toggle defect-loss-toggle--end">{{ selectedDefectProcess?.label || '请选择' }} ›</text>
            </view>
          </view>
        </picker>
        <view v-else-if="defectResponsiblePartyType === 'subcontractor'" class="defect-attention defect-found-process">
          <view class="native-field defect-loss-head defect-attention__head">
            <text>发现工序</text>
            <text class="defect-loss-toggle defect-loss-toggle--end">{{ factoryDefectProcessLabel }}</text>
          </view>
        </view>
        <view v-else class="defect-attention defect-found-process">
          <view class="native-field defect-loss-head defect-attention__head">
            <text>发现工序</text>
            <text class="defect-loss-toggle defect-loss-toggle--end">暂无可选工序</text>
          </view>
        </view>
        <view class="defect-sizes-section">
          <scroll-view scroll-x class="defect-size-matrix-scroll" :show-scrollbar="true">
            <view class="defect-size-matrix" :style="defectSizeMatrixStyle">
              <view class="defect-size-matrix-row defect-size-matrix-row--head">
                <text class="defect-size-matrix-axis">码数</text>
                <text v-for="(line, index) in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-size">{{ defectSizeLineLabel(line) || `码${index + 1}` }}</text>
              </view>
              <view class="defect-size-matrix-row">
                <text class="defect-size-matrix-axis">左脚</text>
                <view v-for="line in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-input"><input v-model="line.left_qty" type="number" placeholder="" /></view>
              </view>
              <view class="defect-size-matrix-row">
                <text class="defect-size-matrix-axis">右脚</text>
                <view v-for="line in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-input"><input v-model="line.right_qty" type="number" placeholder="" /></view>
              </view>
            </view>
          </scroll-view>
        </view>
        <view v-if="groupReport && defectSupervisorProcesses.length" class="defect-supervisor-report">
          <view class="defect-supervisor-head">
          <view class="defect-loss-detail__title">
            <text>主管报工</text>
            <text>报废 {{ standaloneDefectTotalQty }} 只，最多 {{ defectScrapReportMaxText }} 双</text>
          </view>
          <view class="floor-dial">
            <button class="floor-dial__btn" @click="stepDefectReport(-1)">−</button>
            <view class="floor-dial__value">
              <input :value="defectScrapReportQty" type="digit" placeholder="0" @input="onDefectReportQty" />
              <text>双</text>
            </view>
            <button class="floor-dial__btn" @click="stepDefectReport(1)">+</button>
          </view>
          </view>
          <view v-for="row in defectSupervisorProcesses" :key="row.orderProcessId" class="defect-supervisor-process">
            <strong>{{ row.name }}</strong>
            <view v-if="!row.workers.length" class="floor-note">本部门没有可报工人员</view>
            <view v-for="worker in row.workers" :key="worker.id" class="floor-person">
              <view class="floor-person-main"><text class="floor-person-name">{{ worker.name }}</text></view>
              <view class="floor-person-qty">
                <input :value="worker.pairs" type="digit" placeholder="0" @input="onWorkerPairsInput(worker, $event)" />
                <text>双</text>
              </view>
            </view>
          </view>
        </view>
        <view class="defect-loss-section">
          <view v-if="defectResponsiblePartyType !== 'subcontractor' && defectCurrentMaterialLines.length" class="defect-manual-materials defect-attention">
            <view class="native-field defect-loss-head defect-attention__head" @click="defectManualMaterialsOpen = !defectManualMaterialsOpen">
              <text>物料报损</text>
              <text class="defect-loss-toggle defect-loss-toggle--end">{{ defectManualMaterialsOpen ? '收起' : '展开' }}</text>
            </view>
            <view v-if="defectManualMaterialsOpen">
              <view v-for="row in defectCurrentMaterialLines" :key="row.supplier_product_id" :class="['defect-manual-material', { 'defect-manual-material--sizes': !!row.sizes?.length }]">
                <view class="defect-manual-material__head">
                  <text class="defect-manual-material__name">{{ row.name }}</text>
                <view v-if="!row.sizes?.length" class="defect-inline-input">
                  <input :key="defectManualInputKey(row.supplier_product_id)" :value="defectManualMaterialQty[defectManualQtyKey(row.supplier_product_id)] || ''" type="digit" placeholder="" @input="onDefectManualMaterial(defectManualQtyKey(row.supplier_product_id), $event)" />
                  <text>{{ row.unit_name }}</text>
                </view>
              </view>
              <scroll-view v-if="row.sizes?.length" :key="`${row.supplier_product_id}-${defectManualMaterialFillTick}`" scroll-x class="defect-manual-size-scroll" :show-scrollbar="true">
                <view class="defect-manual-sizes">
                  <view v-for="size in row.sizes" :key="size.size_id" class="defect-manual-size">
                    <text>{{ size.size_value }}</text>
                    <input :key="defectManualInputKey(row.supplier_product_id, size.size_id)" :value="defectManualMaterialQty[defectManualQtyKey(row.supplier_product_id, size.size_id)] || ''" type="digit" placeholder="" @input="onDefectManualMaterial(defectManualQtyKey(row.supplier_product_id, size.size_id), $event)" />
                    <text>{{ row.unit_name }}</text>
                  </view>
                </view>
              </scroll-view>
              </view>
            </view>
          </view>
          <view class="native-field defect-loss-head">
            <text>损失金额</text>
            <strong class="defect-loss-total">共 ¥{{ defectLossAmount }}</strong>
            <text class="defect-loss-toggle" @click="defectLossDetailOpen = !defectLossDetailOpen">{{ defectLossDetailOpen ? '收起' : '明细' }}</text>
          </view>
          <view v-if="defectLossDetailOpen" class="defect-loss-detail">
            <view class="defect-loss-detail__group">
              <view class="defect-loss-detail__title"><text>材料</text><text>{{ defectLossDetailMoney(defectMaterialLossAmount, defectMaterialUnitAmount) }}</text></view>
              <view v-if="defectMaterialDetailGroups.length" class="defect-labor-table">
                <view class="defect-labor-table__head"><text>工序段</text><text>材料</text><text>金额</text></view>
                <view v-for="group in defectMaterialDetailGroups" :key="group.key" class="defect-labor-group">
                  <view class="defect-labor-group__segment"><text>{{ group.segmentName }}</text></view>
                  <view class="defect-labor-group__lines">
                    <view v-for="row in group.lines" :key="row.key" class="defect-labor-group__line">
                      <text>{{ row.name }}</text>
                      <text>{{ row.money }}</text>
                    </view>
                  </view>
                </view>
              </view>
              <text v-else class="defect-loss-detail__empty">暂无前段材料</text>
            </view>
            <view class="defect-loss-detail__group">
              <view class="defect-loss-detail__title"><text>计件工资</text><text>{{ defectLaborSummaryMoney }}</text></view>
              <view v-if="defectLaborDetailGroups.length" class="defect-labor-table">
                <view class="defect-labor-table__head"><text>工序段</text><text>工序</text><text>金额</text></view>
                <view v-for="group in defectLaborDetailGroups" :key="group.key" class="defect-labor-group">
                  <view class="defect-labor-group__segment">
                    <text>{{ group.segmentName }}</text>
                    <text v-if="group.departmentName && group.departmentName !== group.segmentName">{{ group.departmentName }}</text>
                  </view>
                  <view class="defect-labor-group__lines">
                    <view v-for="row in group.lines" :key="row.key" class="defect-labor-group__line">
                      <text>{{ row.name }}</text>
                      <text>{{ defectLaborLineMoney(row) }}</text>
                    </view>
                  </view>
                </view>
              </view>
              <text v-else class="defect-loss-detail__empty">暂无计件工资</text>
            </view>
          </view>
          <text class="defect-loss-hint" :class="{ 'defect-loss-hint--error': !!defectLossQuoteError, 'defect-loss-hint--empty': !defectLossHintText }">{{ defectLossHintText || ' ' }}</text>
          <view class="native-field defect-responsibility-line">
            <text class="defect-responsibility-name">公司承担</text>
            <view class="defect-responsibility-controls">
              <text v-if="defectResponsiblePartyType !== 'subcontractor'" class="defect-share-text">¥{{ defectCompanyShareText }}</text>
              <view v-else class="defect-inline-input"><text>¥</text><input v-model="defectCompanyLossAmount" type="digit" placeholder="0" /></view>
              <text class="defect-delete-slot" />
            </view>
          </view>
          <view v-if="defectSubcontractOrders.length" class="defect-party-switch">
            <text>责任人</text>
            <view class="segment defect-party-segment">
              <view class="segment__item" :class="{ active: defectResponsiblePartyType === 'employee' }" hover-class="none" @click="setDefectResponsibleParty('employee')">员工</view>
              <view class="segment__item" :class="{ active: defectResponsiblePartyType === 'subcontractor' }" hover-class="none" @click="setDefectResponsibleParty('subcontractor')">外发厂</view>
            </view>
          </view>
          <view v-if="defectResponsiblePartyType === 'subcontractor'">
            <template v-if="defectSubcontractOrders.length > 1">
              <picker :range="defectPartnerOptions" range-key="label" @change="pickDefectPartner">
                <view class="native-field"><text>外加工厂</text><text>{{ selectedDefectPartnerLabel }}　›</text></view>
              </picker>
              <picker :range="defectOrdersForPartner" range-key="label" @change="pickDefectSubcontractOrder" :disabled="!defectSubcontractPartnerId">
                <view class="native-field"><text>外发单</text><text>{{ selectedDefectSubcontractLabel }}　›</text></view>
              </picker>
            </template>
            <view class="native-field defect-responsibility-line">
              <text class="defect-responsibility-name">{{ selectedDefectPartnerLabel === '请选择' ? '外发厂承担' : selectedDefectPartnerLabel }}</text>
              <view class="defect-responsibility-controls">
                <view class="defect-inline-input"><text>¥</text><input :value="defectFactoryLossAmount" disabled /><text></text></view>
                <text class="defect-delete-slot" />
              </view>
            </view>
          </view>
          <view v-else>
            <view v-for="(row, index) in defectResponsibilities" :key="row.key" class="defect-responsibility-row">
              <view class="native-field defect-responsibility-line">
                <text class="defect-responsibility-name">{{ defectResponsibilityWorkerLabel(row) }}</text>
                <view class="defect-responsibility-controls">
                  <view class="defect-inline-input"><text>¥</text><input v-model="row.share_amount" type="digit" placeholder="0" /></view>
                  <text class="defect-size-remove defect-delete-slot" @click="removeDefectResponsibility(index)">删除</text>
                </view>
              </view>
            </view>
            <button class="defect-worker-select" hover-class="none" @click="openDefectResponsibilityPicker">
              <text class="defect-worker-select__icon">人</text>
              <view class="defect-worker-select__copy"><strong>选择责任人</strong><text>支持多选</text></view>
              <view class="defect-worker-select__meta"><text v-if="defectResponsibilities.length">已选 {{ defectResponsibilities.length }} 人</text><text class="defect-worker-select__chev">›</text></view>
            </button>
          </view>
        </view>
        <view class="defect-photo-section">
          <view class="defect-photo-head"><text>现场照片</text><text>可选</text></view>
          <view class="defect-photo-grid">
            <view v-for="(photo, index) in defectPhotos" :key="photo.localPath" class="defect-photo-item">
              <image :src="photo.localPath" mode="aspectFill" />
              <text v-if="photo.uploading" class="defect-photo-status">上传中</text>
              <text class="defect-photo-remove" @click="removeDefectPhoto(index)">×</text>
            </view>
            <button v-if="defectPhotos.length < 3" class="defect-photo-add" :disabled="defectPhotoUploading" @click="chooseDefectPhotos">＋</button>
          </view>
        </view>
        <view class="native-field"><text>备注</text><input v-model.trim="standaloneDefectNote" placeholder="可选，说明发现位置或原因" /></view>
      </view>
      <view v-if="flowAction === 'defect'" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="defectSubmitting" @click="submitStandaloneDefect">提交报废</button>
      </view>

      <view v-if="flowAction === 'issue' || flowAction === 'report'" :class="['cut-tab-pane', 'cut-tab-pane--sticky', { 'report-floor': flowAction === 'report' }]">
        <template v-if="flowAction === 'issue'">
          <button class="cut-add-button" :loading="issueLoading" @click="openMaterialPicker">＋ 添加物料</button>
          <view v-if="!selectedIssueRows.length" class="card cut-empty-card">
            <strong>还没有物料</strong>
            <text>点击上方添加，从本段可领物料中选择本次要领的料。</text>
          </view>
          <view v-for="row in selectedIssueRows" :key="row.id" class="card cut-material-edit-card">
            <view class="cut-material-edit-row">
              <image v-if="row.image_url" class="cut-material-image cut-material-image--sm" :src="row.image_url" mode="aspectFill" />
              <view v-else class="cut-material-image cut-material-image--sm cut-material-image--empty">无图</view>
              <view class="cut-material-copy">
                <view class="cut-material-title">
                  <strong>{{ materialName(row) }}</strong>
                  <text>每双用量 {{ formatQty(effectivePerPair(row)) }} {{ row.pricing_unit_name || '' }}</text>
                </view>
                <text>已领 {{ formatQty(row.issued_qty) }} · 上限 {{ formatQty(row.max_issue_qty) }} {{ row.pricing_unit_name || '' }}</text>
              </view>
              <view class="cut-material-qty-inline">
                <input :value="issueQtyDraft[row.id]" type="digit" placeholder="0" @input="onMaterialQtyInput(row, $event)" />
                <text>{{ row.pricing_unit_name || '' }}</text>
              </view>
              <text class="cut-material-pairs">≈{{ issuePairDraft[row.id] || '0' }}双</text>
              <view class="cut-remove-hit cut-remove-hit--icon" @click="removeIssueMaterial(row.id)">
                <image class="cut-remove-icon" src="/static/icons/trash.svg" mode="aspectFit" />
              </view>
            </view>
          </view>

          <view class="cut-sticky-bar">
            <text v-if="!canSubmitIssue && issueSubmitHint" class="cut-sticky-hint">{{ issueSubmitHint }}</text>
            <button class="primary-button cut-sticky-button" :loading="issueSubmitting" :disabled="!canSubmitIssue" @click="submitIssue">提交领料{{ selectedIssueRows.length ? ` · ${selectedIssueRows.length} 项` : '' }}</button>
          </view>
        </template>

        <template v-else-if="flowAction === 'report'">
          <view class="floor-who">
            <text>{{ groupReport ? '主管报工' : '个人报工' }}</text>
            <strong v-if="!groupReport">{{ currentEmployeeName }}</strong>
          </view>

          <view v-if="isMultiInlineReport" class="card floor-card">
            <view class="floor-dial">
              <button class="floor-dial__btn" @click="stepOverall(-1)">−</button>
              <view class="floor-dial__value">
                <input v-model="multiReportTotal" type="number" placeholder="0" />
                <text>双</text>
              </view>
              <button class="floor-dial__btn" @click="stepOverall(1)">+</button>
            </view>
          </view>

          <template v-if="isMultiInlineReport">
            <view v-for="row in segmentProcesses" :key="row.id" class="card floor-card">
              <view class="floor-card-head floor-card-head--center">
                <strong>{{ row.label }}</strong>
              </view>
              <view v-if="!groupReport" class="floor-dial floor-dial--compact">
                <button class="floor-dial__btn" @click="stepMultiQty(row.id, -1)">−</button>
                <view class="floor-dial__value">
                  <input :value="multiProcessDrafts[row.id]?.qualified || ''" type="digit" placeholder="0" @input="onMultiQualifiedInput(row.id, $event)" />
                  <text>双</text>
                </view>
                <button class="floor-dial__btn" @click="stepMultiQty(row.id, 1)">+</button>
              </view>
              <template v-if="groupReport">
                <view v-if="!(multiProcessDrafts[row.id]?.workers?.length)" class="floor-note">本部门没有可报工人员</view>
                <view v-for="worker in multiProcessDrafts[row.id]?.workers || []" :key="worker.id" class="floor-person">
                  <view class="floor-person-main">
                    <text class="floor-person-name">{{ worker.name }}</text>
                  </view>
                  <view class="floor-person-qty">
                    <input :value="worker.pairs" type="digit" placeholder="0" @input="onWorkerPairsInput(worker, $event)" />
                    <text>双</text>
                  </view>
                </view>
              </template>
            </view>
          </template>

          <template v-else-if="selectedSegmentProcess">
            <view class="card floor-card">
              <view class="floor-card-head floor-card-head--center">
                <strong>{{ selectedSegmentProcess.label }}</strong>
              </view>
              <view class="floor-dial">
                <button class="floor-dial__btn" @click="stepQty('cutQualified', -1)">−</button>
                <view class="floor-dial__value">
                  <input v-model="cutQualified" type="digit" placeholder="0" />
                  <text>双</text>
                </view>
                <button class="floor-dial__btn" @click="stepQty('cutQualified', 1)">+</button>
              </view>
              <text class="floor-note">{{ cutWorkerHint }}</text>
              <template v-if="groupReport">
                <view v-if="!cutWorkers.length" class="floor-note">本部门没有可报工人员</view>
                <view v-for="worker in cutWorkers" :key="worker.id" class="floor-person">
                  <view class="floor-person-main">
                    <text class="floor-person-name">{{ worker.name }}</text>
                  </view>
                  <view class="floor-person-qty">
                    <input :value="worker.pairs" type="digit" placeholder="0" @input="onWorkerPairsInput(worker, $event)" />
                    <text>双</text>
                  </view>
                </view>
              </template>
            </view>
          </template>

          <view v-if="workshopCounts.length" class="card floor-card">
            <view class="floor-card-head">
              <strong>车间剩余</strong>
              <text>填完才能提交</text>
            </view>
            <view v-for="row in workshopCounts" :key="workshopKey(row)" class="floor-remain">
              <text class="floor-remain-name">{{ row.label }}</text>
              <text class="floor-remain-last">{{ row.last_qty != null ? row.last_qty : '—' }}</text>
              <view class="floor-remain-input">
                <input :value="workshopQtyDraft[workshopKey(row)]" type="digit" placeholder="" @input="onWorkshopQty(row, $event)" />
                <text>{{ row.unit_name || '' }}</text>
              </view>
            </view>
          </view>

          <view class="cut-sticky-bar">
            <text v-if="reportSubmitError || (!canSubmitCutReport && reportSubmitHint)" class="cut-sticky-error">{{ reportSubmitError || reportSubmitHint }}</text>
            <button class="primary-button cut-sticky-button report-submit-button" :loading="submitting" :disabled="!canSubmitCutReport" @click="submitCutReport">提交报工{{ reportSubmitQtyLabel }}</button>
          </view>
        </template>
      </view>
    </template>

    <view v-if="candidatePicker" class="native-sheet-mask" @click="candidatePicker = false"><view class="native-sheet" @click.stop><strong>选择任务</strong><view v-for="row in candidates" :key="row.header_id || row.order_id" class="sheet-option" @click="chooseCandidate(row)"><view><text>{{ row.order_no }}</text><text>{{ row.customer_name || '' }} · {{ row.completed_qty }}/{{ row.plan_qty }}</text></view><text>›</text></view></view></view>
    <view v-if="materialPickerVisible" class="native-sheet-mask" @click="materialPickerVisible = false"><view class="native-sheet" @click.stop><strong>添加物料</strong><view v-if="!availableIssueCandidates.length" class="cut-history-empty">没有其他可领物料</view><view v-for="row in availableIssueCandidates" :key="row.id" class="sheet-option" @click="selectIssueMaterial(row)"><view><text>{{ materialName(row) }}</text><text>可领 {{ formatQty(row.max_issue_qty) }} {{ row.pricing_unit_name || '' }}</text></view><text>＋</text></view></view></view>
    <view v-if="defectWorkerPickerVisible" class="native-sheet-mask" @click="defectWorkerPickerVisible = false">
      <view class="native-sheet native-worker-sheet" @click.stop>
        <view class="native-worker-sheet-head"><strong>选择责任员工</strong><text @click="defectWorkerPickerVisible = false">关闭</text></view>
        <scroll-view scroll-y class="native-worker-list" :show-scrollbar="false">
          <view v-if="defectWorkerLoadError" class="cut-history-empty">{{ defectWorkerLoadError }}</view>
          <view v-else-if="!defectResponsibleWorkers.length" class="cut-history-empty">暂无在职人员</view>
          <view v-for="worker in defectResponsibleWorkers" :key="worker.id" class="sheet-option" @click="toggleDefectResponsibilityWorker(worker)"><view><text>{{ worker.name }}</text><text>{{ defectWorkerMeta(worker) }}</text></view><text>{{ isDefectResponsibilitySelected(worker.id) ? '✓' : '＋' }}</text></view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { get, post, uploadFile } from '../../services/http'
import { getProfile } from '../../services/storage'
import { decodeTarget, type ScanKind } from '../../services/scanner'

const kind = ref<ScanKind | ''>(''), code = ref(''), station = ref<any>(null), unit = ref<any>(null), carton = ref<any>(null), basketInfo = ref<any>(null), flowCard = ref<any>(null)
const currentEmployee = ref<any>(null)
const subcontractReceipt = ref<any>(null), subcontractReceiptQty = ref(''), subcontractReceiptNote = ref(''), subcontractReceiptDeliveryNote = ref('')
const loadQuery = ref<Record<string, string | undefined> | null>(null)
const candidates = ref<any[]>([]), selectedOrderNo = ref(''), candidatePicker = ref(false), orderNo = ref(''), colorName = ref(''), sizeValue = ref(''), qty = ref(''), processName = ref('')
const loadingPage = ref(true), submitting = ref(false), errorMessage = ref(''), successResult = ref<any>(null), reportType = ref('normal')
const proxyWorkers = ref<any[]>([])
const reportWorkerOptions = ref<any[]>([])
const processWorkerOptions = ref<Record<number, any[]>>({})
const flowAction = ref<'' | 'issue' | 'report' | 'claim' | 'defect' | 'subcontract' | 'report-history' | 'claim-history' | 'defect-history' | 'issue-history' | 'subcontract-history'>('')
const flowFeaturePermissions = ref<string[]>(getProfile()?.featurePermissions || [])
const activeSegmentId = ref(0)
const activeSegmentCode = ref('')
const activeSegmentName = ref('')
const selectedOrderProcessId = ref<number | null>(null)
const claimSubmitting = ref(false), defectSubmitting = ref(false)
const claimQty = ref('')
const defectTypes = ref<{ code: string; name: string }[]>([]), standaloneDefectType = ref(''), standaloneDefectNote = ref('')
const standaloneDefectBrand = ref('')
type DefectSizeLine = { key: number; size_id: number | null; left_qty: string; right_qty: string }
type DefectPhoto = { localPath: string; url?: string; uploading?: boolean }
let defectSizeLineKey = 0
const defectSizeLines = ref<DefectSizeLine[]>([])
const defectPhotos = ref<DefectPhoto[]>([])
const defectPhotoUploading = ref(false)
const defectDispositionOptions = [
  { value: 'rework', label: '内部沟通' },
  { value: 'scrap', label: '报废' },
  { value: 'concession', label: '让步' },
]
const standaloneDefectDisposition = ref('scrap')
const standaloneDefectScrapSource = ref('internal')
const standaloneDefectReplacementSource = ref('internal')
const defectResponsiblePartyType = ref<'employee' | 'subcontractor'>('employee')
const defectSubcontractOrders = ref<any[]>([])
const defectSubcontractPartnerId = ref<number | null>(null)
const defectSubcontractOrderId = ref<number | null>(null)
type DefectResponsibilityRow = { key: number; worker_id: number | null; share_amount: string }
let defectResponsibilityKey = 0
const defectLossQuote = ref<any>(null)
const defectLossQuoteLoading = ref(false)
const defectLossQuoteError = ref('')
const defectLossDetailOpen = ref(false)
const defectManualMaterialsOpen = ref(false)
const defectManualMaterialQty = ref<Record<string, string>>({})
const defectManualMaterialTouched = ref<Record<string, boolean>>({})
const defectManualMaterialFillTick = ref(0)
const defectCompanyLossAmount = ref('0')
const defectResponsibilities = ref<DefectResponsibilityRow[]>([])
const defectWorkers = ref<any[]>([])
const defectResponsibleWorkers = ref<any[]>([])
const defectWorkerPickerVisible = ref(false)
const defectWorkerLoadError = ref('')
const subcontractPartners = ref<any[]>([])
const subcontractPartnerId = ref<number | null>(null)
const subcontractProcessIds = ref<number[]>([])
const subcontractQty = ref('')
const subcontractUnitPrice = ref('')
const subcontractMaterialUnitPrice = ref('')
const subcontractMaterialPriceManual = ref(false)
const subcontractMaterialPriceQuote = ref<{ material_amount?: number; labor_amount?: number } | null>(null)
const subcontractDeliveryDate = ref('')
const subcontractNotes = ref('')
const subcontractSubmitting = ref(false)
const issueLoading = ref(false), issueSubmitting = ref(false), issueNotice = ref('')
let issueNoticeTimer: ReturnType<typeof setTimeout> | undefined
const issueCandidates = ref<any[]>([]), selectedIssueRows = ref<any[]>([]), issueHistory = ref<any[]>([])
const issueQtyDraft = ref<Record<number, string>>({}), issuePairDraft = ref<Record<number, string>>({})
const materialPickerVisible = ref(false)
const defectHistory = ref<any[]>([]), subcontractHistory = ref<any[]>([])
const reportSubmitError = ref('')
const cutWorkerLoadError = ref('')
const cutQualified = ref(''), cutWorkers = ref<any[]>([]), cutHistory = ref<any[]>([])
const workshopCounts = ref<any[]>([])
const workshopQtyDraft = ref<Record<string, string>>({})
function workshopKey(row: any) { return `${row.supplier_product_id}-${row.size_id || 0}` }
function onWorkshopQty(row: any, event: any) { workshopQtyDraft.value[workshopKey(row)] = String(event?.detail?.value ?? '') }
function workshopCountPayload(rows = workshopCounts.value) {
  return rows.map((row: any) => ({ supplier_product_id: row.supplier_product_id, size_id: row.size_id ?? null, qty: workshopQtyDraft.value[workshopKey(row)] }))
}
function workshopCountsFilled(rows = workshopCounts.value) {
  return rows.every((row: any) => String(workshopQtyDraft.value[workshopKey(row)] ?? '') !== '')
}
function clearWorkshopDrafts() {
  workshopQtyDraft.value = Object.fromEntries(workshopCounts.value.map((row: any) => [workshopKey(row), '']))
}
const needsWorkshopCount = computed(() => Boolean(currentEmployee.value?.process_segment_is_first))
async function loadWorkshopCounts(headerId?: number, params: Record<string, unknown> = {}) {
  workshopCounts.value = []
  workshopQtyDraft.value = {}
  if (!headerId || !needsWorkshopCount.value) return
  try {
    const data: any = await get('/reports/workshop-counts', { header_id: headerId, ...params })
    workshopCounts.value = data?.items || []
    workshopQtyDraft.value = Object.fromEntries(workshopCounts.value.map((row: any) => [workshopKey(row), '']))
  } catch { workshopCounts.value = [] }
}
const multiReportTotal = ref('')
type WorkerSplitMode = 'average' | 'individual'
type MultiProcessDraft = { qualified: string; workers: any[]; splitMode: WorkerSplitMode; unitPrice: number }
const workerSplitMode = ref<WorkerSplitMode>('average')
const multiProcessDrafts = ref<Record<number, MultiProcessDraft>>({})
const cutCompletionMode = ref<'complete' | 'quantity_split' | 'component'>('complete')
const cutUnitPrice = ref(0), cutPriceError = ref('')
const cutCompletionModes = [{ value: 'complete', label: '一人完整完成' }, { value: 'quantity_split', label: '多人按数量分工' }, { value: 'component', label: '多人按不同部件分工' }]
const cutCompletionModeLabel = computed(() => cutCompletionModes.find(row => row.value === cutCompletionMode.value)?.label || '一人完整完成')
const reportSegmentId = computed(() => Number((selectedSegmentProcess.value || segmentProcesses.value[0])?.segment_id || 0))
const ledDepartmentIds = computed<number[]>(() => {
  const rows = currentEmployee.value?.led_segment_departments || []
  const row = rows.find((item: any) => Number(item.segment_id) === reportSegmentId.value)
  return (row?.department_ids || []).map((id: unknown) => Number(id)).filter(Boolean)
})
// 工序段对应部门的负责人：集体报工。其他人只报自己。
const groupReport = computed(() => ledDepartmentIds.value.length > 0)
const cutWorkerHint = computed(() => {
  if (!groupReport.value) return '加减或直接输入本次双数'
  if (!cutWorkers.value.length) return '本部门没有可报工人员'
  if (cutWorkers.value.length <= 1) return '加减或直接输入本次双数'
  return cutCompletionMode.value === 'component'
    ? '按部件分工时，每人双数都不能少于本次数量'
    : '每人双数加起来要等于上面的数量'
})
const reportTypes = [{ value: 'normal', label: '正常' }, { value: 'rework', label: '返修' }, { value: 'supplement', label: '补数' }, { value: 'tail', label: '尾数' }]
const reportTypeLabel = computed(() => reportTypes.find(x => x.value === reportType.value)?.label || '正常')
const currentEmployeeId = computed(() => Number(currentEmployee.value?.id || 0))
const currentEmployeeName = computed(() => String(currentEmployee.value?.display_name || currentEmployee.value?.name || '当前员工'))
const currentDepartmentName = computed(() => String(currentEmployee.value?.department_name || '').trim())
const currentEmployeeProcessIds = computed<number[]>(() => Array.isArray(currentEmployee.value?.process_ids) ? currentEmployee.value.process_ids.map(Number).filter(Boolean) : [])
const currentEmployeeProcessNames = computed<string[]>(() => Array.isArray(currentEmployee.value?.process_names) ? currentEmployee.value.process_names.map(String).filter(Boolean) : [])
const selected = computed(() => candidates.value.find(x => x.order_no === selectedOrderNo.value) || null)
const canCreateSubcontract = computed(() => ['admin', 'manager'].includes(getProfile()?.role || '') || getProfile()?.isLeader || hasFlowFeature('subcontract_out'))
const canWarehouse = computed(() => ['admin', 'manager', 'leader', 'warehouse'].includes(getProfile()?.role || ''))
const segmentLabel = computed(() => activeSegmentName.value || '本段')
const reportDepartmentIds = computed(() => {
  const employee = currentEmployee.value || {}
  const ids = new Set<number>()
  const own = Number(employee.department_id || 0)
  if (own) ids.add(own)
  const segmentId = activeSegmentId.value
  for (const row of employee.led_segment_departments || []) {
    if (segmentId && Number(row.segment_id) !== segmentId) continue
    for (const id of row.department_ids || []) {
      const depId = Number(id)
      if (depId) ids.add(depId)
    }
  }
  return ids
})
const segmentProcesses = computed<any[]>(() => {
  const processes = flowCard.value?.processes || []
  const id = activeSegmentId.value
  const name = activeSegmentName.value
  const inSegment = id
    ? processes.filter((row: any) => Number(row.segment_id) === id)
    : name
      ? processes.filter((row: any) => String(row.segment_name || '') === name)
      : []
  const mine = reportDepartmentIds.value
  const onRouteDepartment = (row: any) => {
    const routeIds = new Set((row.route_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean))
    if (row.route_department_shared || !routeIds.size) return true
    return (row.assigned_department_ids || []).some((depId: unknown) => {
      const id = Number(depId)
      return mine.has(id) && routeIds.has(id)
    })
  }
  const dispatched = inSegment.filter((row: any) =>
    (row.assigned_department_ids || []).some((depId: unknown) => mine.has(Number(depId)))
    && onRouteDepartment(row)
  )
  if (dispatched.length) return dispatched
  const sentElsewhere = inSegment.some((row: any) => (row.assigned_department_ids || []).length > 0)
  return sentElsewhere ? [] : inSegment
})
const reportDepartmentName = computed(() => {
  const names = new Set<string>()
  for (const row of segmentProcesses.value) {
    const name = String(row.assigned_department_name || '').trim()
    if (name) names.add(name)
  }
  if (names.size === 1) return [...names][0]
  return currentDepartmentName.value
})
const selectedSegmentProcess = computed(() => segmentProcesses.value.find((row: any) => Number(row.id) === Number(selectedOrderProcessId.value)) || null)
const defectProcessOptions = computed<any[]>(() => flowCard.value?.processes || [])
const departmentRouteProcesses = computed(() => [...segmentProcesses.value].sort((a: any, b: any) =>
  Number(a.segment_sort_order ?? 1e9) - Number(b.segment_sort_order ?? 1e9)
  || Number(a.route_sort_order ?? 1e9) - Number(b.route_sort_order ?? 1e9)
  || Number(a.id) - Number(b.id)
))
const selectedDefectProcess = computed(() => departmentRouteProcesses.value.find((row: any) => Number(row.id) === Number(selectedOrderProcessId.value)) || null)
const selectedSubcontractPartner = computed(() => subcontractPartners.value.find((row: any) => Number(row.id) === Number(subcontractPartnerId.value)) || null)
const isMultiInlineReport = computed(() => segmentProcesses.value.length > 1)
const flowActionLabel = computed(() => ({
  issue: '领料',
  report: '报工',
  claim: '领任务',
  defect: '报废',
  subcontract: '外发',
  'report-history': '报工记录',
  'claim-history': '领任务记录',
  'defect-history': '报废记录',
  'issue-history': '领料记录',
  'subcontract-history': '外发记录',
} as Record<string, string>)[flowAction.value] || '')
const flowActionTitle = computed(() =>
  flowAction.value === 'report' && reportDepartmentName.value
    ? `报工 · ${reportDepartmentName.value}`
    : flowActionLabel.value
)
const defectTypeLabel = computed(() => defectTypes.value.find(row => row.code === standaloneDefectType.value)?.name || '')
const subcontractMaterialPriceHint = computed(() => {
  const quote = subcontractMaterialPriceQuote.value
  if (!quote) return '选工序后按材料+外发前工资计算，可改'
  const material = Number(quote.material_amount || 0).toFixed(2)
  const labor = Number(quote.labor_amount || 0).toFixed(2)
  return `材料 ¥${material} + 工资 ¥${labor} / 双${subcontractMaterialPriceManual.value ? '（已手改）' : ''}`
})
const defectPartnerOptions = computed(() => {
  const seen = new Map<number, { id: number; label: string }>()
  const options: { id: number; label: string }[] = []
  for (const row of defectSubcontractOrders.value) {
    const partnerId = Number(row.partner_id || 0)
    if (!partnerId || seen.has(partnerId)) continue
    const option = { id: partnerId, label: row.partner_name || `工厂${partnerId}` }
    seen.set(partnerId, option)
    options.push(option)
  }
  return options
})
const selectedDefectPartnerLabel = computed(() => {
  if (!defectSubcontractPartnerId.value) return '请选择'
  return defectPartnerOptions.value.find(row => Number(row.id) === Number(defectSubcontractPartnerId.value))?.label || '请选择'
})
const selectedDefectSubcontractOrder = computed(() =>
  defectSubcontractOrders.value.find((row: any) => Number(row.id) === Number(defectSubcontractOrderId.value)) || null
)
const factoryDefectProcessLabel = computed(() => {
  const order = selectedDefectSubcontractOrder.value
  if (selectedDefectProcess.value?.label) return selectedDefectProcess.value.label
  const names = String(order?.process_name || '').split('、').filter(Boolean)
  return names[0] || '外发第一道工序'
})
const defectLossHintText = computed(() => {
  if (defectResponsiblePartyType.value === 'subcontractor') {
    const price = Number(selectedDefectSubcontractOrder.value?.material_unit_price || 0).toFixed(2)
    return `按外发材料单价 ¥${price} / 双`
  }
  if (defectLossQuoteLoading.value) return '正在按发现工序计算…'
  return defectLossQuoteError.value || ''
})
const defectOrdersForPartner = computed(() => {
  if (!defectSubcontractPartnerId.value) return []
  return defectSubcontractOrders.value
    .filter((row: any) => Number(row.partner_id) === Number(defectSubcontractPartnerId.value))
    .map((row: any) => ({
      id: Number(row.id),
      label: `${row.subcontract_no} · ${row.total_qty || 0}`,
    }))
})
const selectedDefectSubcontractLabel = computed(() => {
  if (!defectSubcontractPartnerId.value) return '请先选择外加工厂'
  if (!defectSubcontractOrderId.value) return '请选择'
  return defectOrdersForPartner.value.find(row => Number(row.id) === Number(defectSubcontractOrderId.value))?.label || '请选择'
})
const defectDispositionLabel = computed(() => defectDispositionOptions.find(row => row.value === standaloneDefectDisposition.value)?.label || '')
function defectResponsibilityWorkerLabel(row: DefectResponsibilityRow) {
  return defectWorkers.value.find((worker: any) => Number(worker.id) === Number(row.worker_id))?.name || ''
}
function defectWorkerMeta(worker: any) {
  const department = String(worker?.department_name || '').trim() || '未分部门'
  const processes = Array.isArray(worker?.process_names) ? worker.process_names.filter(Boolean).join('、') : ''
  return `${department} · ${processes || '未配置工序'}`
}
const defectBrandOptions = computed<string[]>(() => {
  const values = (flowCard.value?.allocation_rows || []).map((row: any) => String(row.brand_name || '').trim()).filter(Boolean)
  const fallback = String(flowCard.value?.brand_name || '').trim()
  return [...new Set(fallback ? [...values, fallback] : values)]
})
function resolveDisplayImageUrl(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || /^(https?:|data:|blob:)/i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  const apiOrigin = String(import.meta.env.VITE_API_BASE_URL || '').match(/^https?:\/\/[^/]+/i)?.[0]
  return apiOrigin ? `${apiOrigin}${path}` : path
}
const defectProductImageUrl = computed(() => {
  const requirements = flowCard.value?.work_requirements || []
  const selectedBrand = String(standaloneDefectBrand.value || '').trim()
  const matching = requirements.find((row: any) => String(row.brand_name || '').trim() === selectedBrand)
  const source = matching?.image_url
    || flowCard.value?.product_image_url
    || flowCard.value?.work_requirement?.image_url
    || requirements.find((row: any) => row.image_url)?.image_url
  return resolveDisplayImageUrl(source)
})
const orderProductImageUrl = computed(() => {
  const requirements = flowCard.value?.work_requirements || []
  const source = flowCard.value?.product_image_url
    || flowCard.value?.work_requirement?.image_url
    || requirements.find((row: any) => row.image_url)?.image_url
  return resolveDisplayImageUrl(source)
})
function previewOrderProductImage() {
  if (!orderProductImageUrl.value) return
  uni.previewImage({ urls: [orderProductImageUrl.value] })
}
const defectSizeOptions = computed<any[]>(() => {
  const merged = [
    ...(flowCard.value?.size_lines || []),
    ...(flowCard.value?.items || []),
  ].filter((row: any) => Number(row.size_id || 0) > 0)
  return [...new Map(merged.map((row: any) => [Number(row.size_id), row])).values()]
    .sort((a: any, b: any) => String(a.size_value || '').localeCompare(String(b.size_value || ''), 'zh-CN', { numeric: true }))
})
const defectSizeMatrixStyle = computed(() => {
  const count = Math.max(defectSizeLines.value.length, 1)
  return { width: `${64 + count * 72}rpx` }
})
function defectSizeLineLabel(line: DefectSizeLine) {
  return defectSizeOptions.value.find((row: any) => Number(row.size_id) === Number(line.size_id))?.size_value || ''
}
function defectSizeLineTotal(line: DefectSizeLine) {
  return Number(line.left_qty || 0) + Number(line.right_qty || 0)
}
const standaloneDefectTotalQty = computed(() => defectSizeLines.value.reduce((sum, line) => sum + defectSizeLineTotal(line), 0))
function defectSizeMaterialUnitLoss(line: DefectSizeLine) {
  if (defectResponsiblePartyType.value === 'subcontractor') {
    return Number(selectedDefectSubcontractOrder.value?.material_unit_price || 0) / 2
  }
  return Number(defectLossQuote.value?.by_size?.[String(line.size_id)]?.material_per_piece ?? defectLossQuote.value?.material_per_piece ?? 0)
}
function defectSizeLineLoss(line: DefectSizeLine) {
  const labor = defectResponsiblePartyType.value === 'subcontractor'
    ? 0
    : standaloneDefectScrapSource.value === 'internal'
      ? Number(defectLossQuote.value?.labor_per_piece || 0)
      : Number(defectLossQuote.value?.labor_before_process_per_piece || 0)
  const unit = defectSizeMaterialUnitLoss(line) + labor
  return Number((defectSizeLineTotal(line) * unit).toFixed(2))
}
function defectPieceRate(row: any, sizeId: number | null) {
  if (sizeId != null && row?.by_size && row.by_size[String(sizeId)] != null) return Number(row.by_size[String(sizeId)] || 0)
  return Number(row?.amount_per_piece || 0)
}
function defectLossDetailMoney(amount: string, unit: string) {
  return standaloneDefectTotalQty.value > 0 ? `¥${amount}` : `¥${unit}/只`
}
function defectLaborUnitPrice(row: any) {
  if (row?.amount_per_piece != null && row.amount_per_piece !== '') return Number(row.amount_per_piece || 0)
  return Number(row?.unit_price || 0) / 2
}
function defectLaborLineMoney(row: { priced?: boolean; amount: string; unit: string }) {
  return row.priced ? `¥${row.amount}` : `¥${row.unit}/只`
}
const defectMaterialDetailLines = computed(() => {
  if (defectResponsiblePartyType.value === 'subcontractor') {
    const unit = Number(selectedDefectSubcontractOrder.value?.material_unit_price || 0) / 2
    const qty = standaloneDefectTotalQty.value
    return [{ key: 'subcontract-material', segmentId: 0, segmentName: '', name: '外发材料', unit: unit.toFixed(2), amount: (unit * qty).toFixed(2) }]
  }
  return (defectLossQuote.value?.material_lines || []).map((row: any) => {
    const amount = defectSizeLines.value.reduce((sum, line) => sum + defectPieceRate(row, line.size_id) * defectSizeLineTotal(line), 0)
    return {
      key: `${row.segment_id || 0}-${row.supplier_product_id}`,
      segmentId: Number(row.segment_id || 0),
      segmentName: row.segment_name || '未分段',
      segmentSort: Number(row.segment_sort ?? 999999),
      name: row.name || '材料',
      unit: Number(row.amount_per_piece || 0).toFixed(2),
      amount: amount.toFixed(2),
    }
  })
})
const defectPriorMaterialGroups = computed(() => {
  const groups: { key: string; name: string; lines: any[] }[] = []
  for (const row of defectMaterialDetailLines.value) {
    const last = groups[groups.length - 1]
    if (last && last.key === String(row.segmentId)) last.lines.push(row)
    else groups.push({ key: String(row.segmentId || row.key), name: row.segmentName || '未分段', lines: [row] })
  }
  return groups
})
const defectCurrentSegmentName = computed(() => String(defectLossQuote.value?.current_segment_name || activeSegmentName.value || ''))
const defectCurrentMaterialLines = computed(() => defectResponsiblePartyType.value === 'subcontractor'
  ? []
  : (defectLossQuote.value?.current_material_lines || []))
function defectManualQtyKey(productId: number, sizeId?: number | null) {
  return sizeId ? `${productId}:${sizeId}` : String(productId)
}
function defectManualInputKey(productId: number, sizeId?: number | null) {
  return `${defectManualQtyKey(productId, sizeId)}-${defectManualMaterialFillTick.value}`
}
function defectManualQtyOf(row: any) {
  if (row?.sizes?.length) {
    return row.sizes.reduce((sum: number, size: any) => sum + Number(defectManualMaterialQty.value[defectManualQtyKey(row.supplier_product_id, size.size_id)] || 0), 0)
  }
  return Number(defectManualMaterialQty.value[defectManualQtyKey(row.supplier_product_id)] || 0)
}
function defectSizeMaxFill(sizeId: number) {
  const line = defectSizeLines.value.find(row => Number(row.size_id) === Number(sizeId))
  if (!line) return ''
  const qty = Math.max(Number(line.left_qty || 0), Number(line.right_qty || 0))
  return qty > 0 ? String(qty) : ''
}
function defectScrapPieceFill() {
  const qty = defectSizeLines.value.reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0)
  return qty > 0 ? String(qty) : ''
}
function applyDefectManualDefault(next: Record<string, string>, key: string, value: string) {
  if (defectManualMaterialTouched.value[key]) return false
  if ((next[key] || '') === value) return false
  if (value) next[key] = value
  else delete next[key]
  return true
}
function syncDefectManualMaterialDefaults() {
  if (defectResponsiblePartyType.value === 'subcontractor') return
  const next = { ...defectManualMaterialQty.value }
  let changed = false
  const pieceFill = defectScrapPieceFill()
  for (const row of defectCurrentMaterialLines.value) {
    if (row.sizes?.length) {
      for (const size of row.sizes) {
        changed = applyDefectManualDefault(next, defectManualQtyKey(row.supplier_product_id, size.size_id), defectSizeMaxFill(Number(size.size_id))) || changed
      }
      continue
    }
    changed = applyDefectManualDefault(next, defectManualQtyKey(row.supplier_product_id), pieceFill) || changed
  }
  if (changed) {
    defectManualMaterialQty.value = next
    defectManualMaterialFillTick.value += 1
  }
}
function onDefectManualMaterial(key: string, event: any) {
  const raw = String(event?.detail?.value ?? '').replace(/[^\d.]/g, '')
  const [integer = '', ...decimalParts] = raw.split('.')
  const decimal = decimalParts.join('').slice(0, 4)
  const normalizedInteger = integer.replace(/^0+(?=\d)/, '')
  const value = raw.includes('.') ? `${normalizedInteger || '0'}.${decimal}` : normalizedInteger
  defectManualMaterialTouched.value = { ...defectManualMaterialTouched.value, [key]: true }
  defectManualMaterialQty.value = { ...defectManualMaterialQty.value, [key]: value }
  return value
}
const defectFilledMaterialLines = computed(() => defectCurrentMaterialLines.value.flatMap((row: any) => {
  const qty = defectManualQtyOf(row)
  if (qty <= 0) return []
  return [{
    key: row.supplier_product_id,
    name: row.name || '材料',
    amount: (qty * Number(row.unit_price || 0)).toFixed(2),
  }]
}))
const defectManualMaterialAmount = computed(() => defectFilledMaterialLines.value.reduce((sum, row) => sum + Number(row.amount || 0), 0))
const defectMaterialDetailGroups = computed(() => {
  const groups = defectPriorMaterialGroups.value.map(group => ({
    key: group.key,
    segmentName: group.name || '未分段',
    lines: group.lines.map(row => ({
      key: row.key,
      name: row.name,
      money: defectLossDetailMoney(row.amount, row.unit),
    })),
  }))
  if (defectFilledMaterialLines.value.length) {
    groups.push({
      key: 'current-segment',
      segmentName: defectCurrentSegmentName.value || '本部门',
      lines: defectFilledMaterialLines.value.map(row => ({
        key: String(row.key),
        name: row.name,
        money: `¥${row.amount}`,
      })),
    })
  }
  return groups
})
watch([defectSizeLines, defectCurrentMaterialLines, defectResponsiblePartyType], syncDefectManualMaterialDefaults, { deep: true })
function defectLaborDetailFromQuote(row: any, pieces: number, pairQty?: number | null) {
  const usePairs = pairQty != null
  const unitPrice = usePairs
    ? (Number(row.unit_price || 0) || defectLaborUnitPrice(row) * 2)
    : defectLaborUnitPrice(row)
  const qty = usePairs ? Number(pairQty) : pieces
  return {
    key: row.order_process_id,
    name: row.process_name || '工序',
    segmentId: Number(row.segment_id || 0),
    segmentName: row.segment_name || '未分段',
    segmentSort: Number(row.segment_sort ?? 999999),
    processId: Number(row.process_id || 0),
    departmentId: Number(row.department_id || 0),
    departmentName: row.department_name || '',
    unit: unitPrice.toFixed(2),
    amount: (unitPrice * qty).toFixed(2),
    priced: qty > 0,
  }
}
function defectReportedPairs(orderProcessId: number) {
  if (!groupReport.value) return null
  const known = defectSupervisorLaborLines.value.some(row => Number(row.key) === Number(orderProcessId))
  if (!known) return null
  const workers = defectReportDrafts.value[Number(orderProcessId)]?.workers || []
  return workers.reduce((sum: number, worker: any) => sum + Number(worker.pairs || 0), 0)
}
const defectLaborDetailLines = computed(() => {
  if (defectResponsiblePartyType.value === 'subcontractor') return []
  const pieces = standaloneDefectTotalQty.value
  const includeFound = standaloneDefectScrapSource.value === 'internal'
  const quoteLines = (defectLossQuote.value?.labor_lines || [])
    .filter((row: any) => includeFound || !row.is_found_process)
    .slice()
    .sort((a: any, b: any) => Number(a.segment_sort ?? 999999) - Number(b.segment_sort ?? 999999) || Number(a.route_sort ?? 999999) - Number(b.route_sort ?? 999999) || Number(a.order_process_id || 0) - Number(b.order_process_id || 0))
  return quoteLines.flatMap((row: any) => {
    const pairs = defectReportedPairs(Number(row.order_process_id || 0))
    if (pairs != null && pairs <= 0) return []
    return [defectLaborDetailFromQuote(row, pieces, pairs)]
  })
})
const defectLaborSummaryMoney = computed(() => {
  const lines = defectLaborDetailLines.value
  if (lines.some(row => row.priced)) return `¥${defectLaborLossAmount.value}`
  if (!lines.length) return '¥0'
  return `¥${defectLaborUnitAmount.value}/只`
})
const defectLaborDetailGroups = computed(() => {
  const groups: { key: string; segmentName: string; departmentName: string; lines: any[] }[] = []
  for (const row of defectLaborDetailLines.value) {
    const last = groups[groups.length - 1]
    const sameGroup = last
      && last.lines[0]?.segmentId === row.segmentId
      && last.lines[0]?.departmentId === row.departmentId
    if (sameGroup) last.lines.push(row)
    else groups.push({
      key: `${row.segmentId}-${row.departmentId}-${row.key}`,
      segmentName: row.segmentName,
      departmentName: row.departmentName,
      lines: [row],
    })
  }
  return groups
})
const defectScrapReportQty = ref('')
const defectReportDrafts = ref<Record<number, any>>({})
const defectScrapReportMax = computed(() => standaloneDefectTotalQty.value / 2)
const defectScrapReportMaxText = computed(() => formatPairAmount(defectScrapReportMax.value))
function formatPairAmount(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0'
  return (Math.round(value * 100) / 100).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
}
const defectSupervisorLaborLines = computed(() => {
  const route = departmentRouteProcesses.value
  const foundId = Number(selectedDefectProcess.value?.id || 0)
  const foundIndex = route.findIndex((row: any) => Number(row.id) === foundId)
  if (foundIndex < 0) return []
  return route.slice(0, foundIndex + 1).map((row: any) => {
    const routeIds = new Set((row.route_department_ids || []).map((id: unknown) => Number(id)).filter(Boolean))
    const assigned = (row.assigned_department_ids || []).map((id: unknown) => Number(id)).filter((id: number) => id > 0)
    const departmentId = assigned.find((id: number) => routeIds.has(id)) || assigned[0] || 0
    return {
      key: Number(row.id),
      name: row.process_name || row.label || '工序',
      processId: Number(row.process_id || 0),
      departmentId,
      segmentId: Number(row.segment_id || 0),
      segmentName: row.segment_name || '未分段',
      segmentSort: Number(row.segment_sort_order ?? 1e9),
      departmentName: String(row.assigned_department_name || ''),
    }
  })
})
const defectSupervisorProcesses = computed(() => defectSupervisorLaborLines.value
  .map(row => defectReportDrafts.value[Number(row.key)])
  .filter(Boolean))
const defectReportProcessKey = computed(() => defectSupervisorLaborLines.value
  .map(row => `${row.key}:${row.processId}:${row.departmentId}`)
  .join('|'))
function distributeDefectReport() {
  const total = defectScrapReportQty.value
  for (const draft of Object.values(defectReportDrafts.value)) {
    if (!draft.workers?.length) continue
    if (draft.workers.length === 1) draft.workers[0].pairs = Number(total || 0) > 0 ? String(total) : ''
    else distributeEvenly(draft.workers, total)
  }
}
function stepDefectReport(delta: number) {
  const next = Math.max(0, Math.round((Number(defectScrapReportQty.value || 0) + delta * 0.5) * 100) / 100)
  if (next - defectScrapReportMax.value > 0.001) {
    uni.showToast({ title: '不能超过报废数量', icon: 'none' })
    defectScrapReportQty.value = defectScrapReportMax.value > 0 ? formatPairAmount(defectScrapReportMax.value) : ''
  } else {
    defectScrapReportQty.value = next > 0 ? formatPairAmount(next) : ''
  }
  distributeDefectReport()
}
function onDefectReportQty(event: any) {
  const value = normalizePairDecimal(event?.detail?.value)
  const numeric = Number(value || 0)
  if (numeric - defectScrapReportMax.value > 0.001) {
    uni.showToast({ title: '不能超过报废数量', icon: 'none' })
    defectScrapReportQty.value = defectScrapReportMax.value > 0 ? formatPairAmount(defectScrapReportMax.value) : ''
  } else {
    defectScrapReportQty.value = value
  }
  distributeDefectReport()
  return defectScrapReportQty.value
}
let defectReportLoadToken = 0
async function loadDefectReportWorkers() {
  const token = ++defectReportLoadToken
  const lines = defectSupervisorLaborLines.value.filter(row => Number(row.key) > 0 && Number(row.processId) > 0)
  if (!groupReport.value || !lines.length) {
    defectReportDrafts.value = {}
    return
  }
  const entries = await Promise.all(lines.map(async row => {
    const params: Record<string, string | number> = { process_id: row.processId }
    if (row.departmentId) params.department_id = row.departmentId
    const data: any = await get('/shop-floor-settings/workers', params)
    const workers = workersInDepartments(Array.isArray(data) ? data : data?.items || [], row.departmentId ? [row.departmentId] : [])
    const previous = defectReportDrafts.value[Number(row.key)]?.workers || []
    return {
      orderProcessId: Number(row.key),
      name: row.name,
      workers: listedReportWorkers(workers, previous, defectScrapReportQty.value),
    }
  }))
  if (token !== defectReportLoadToken) return
  const drafts: Record<number, any> = {}
  for (const entry of entries) drafts[entry.orderProcessId] = entry
  defectReportDrafts.value = drafts
  distributeDefectReport()
}
watch(defectScrapReportMax, max => {
  if (!groupReport.value) return
  defectScrapReportQty.value = max > 0 ? formatPairAmount(max) : ''
  distributeDefectReport()
})
watch(defectReportProcessKey, () => { void loadDefectReportWorkers() })
const defectMaterialLossAmount = computed(() => (defectMaterialDetailLines.value.reduce((sum, row) => sum + Number(row.amount || 0), 0) + defectManualMaterialAmount.value).toFixed(2))
const defectLaborLossAmount = computed(() => defectLaborDetailLines.value.reduce((sum, row) => sum + Number(row.amount || 0), 0).toFixed(2))
const defectMaterialUnitAmount = computed(() => defectMaterialDetailLines.value.reduce((sum, row) => sum + Number(row.unit || 0), 0).toFixed(2))
const defectLaborUnitAmount = computed(() => defectLaborDetailLines.value.reduce((sum, row) => sum + Number(row.unit || 0), 0).toFixed(2))
const defectLossAmount = computed(() => (Number(defectMaterialLossAmount.value || 0) + Number(defectLaborLossAmount.value || 0)).toFixed(2))
const defectPersonalShareAmount = computed(() => defectResponsibilities.value.reduce((sum, row) => sum + Number(row.share_amount || 0), 0))
const defectCompanyShareAmount = computed(() => Math.max(0, Number(defectLossAmount.value || 0) - defectPersonalShareAmount.value))
const defectCompanyShareText = computed(() => formatPairAmount(defectCompanyShareAmount.value))
const defectFactoryLossAmount = computed(() => Math.max(0, Number(defectLossAmount.value || 0) - Number(defectCompanyLossAmount.value || 0)).toFixed(2))
const defectAllocationTotal = computed(() => (
  defectResponsiblePartyType.value === 'subcontractor'
    ? Number(defectCompanyLossAmount.value || 0) + Number(defectFactoryLossAmount.value)
    : defectCompanyShareAmount.value + defectPersonalShareAmount.value
).toFixed(2))
const defectAllocationDifference = computed(() => Math.abs(Number(defectLossAmount.value) - Number(defectAllocationTotal.value)).toFixed(2))
const defectAllocationBalanced = computed(() => Math.abs(Number(defectLossAmount.value) - Number(defectAllocationTotal.value)) < 0.005)
function asReportPairs(value: unknown) {
  const qty = Number(value || 0)
  if (!flowCard.value?.is_recut) return qty
  return Math.round(qty * 50) / 100
}
const reportedSegmentQty = computed(() => {
  const row = segmentProcess()
  if (!flowCard.value?.is_recut && row?.base_completed_qty != null) return Number(row.base_completed_qty)
  return Number(row?.completed_qty || 0)
})
const segmentPlanQty = computed(() => {
  const row = segmentProcess()
  if (!flowCard.value?.is_recut && row?.base_plan_qty != null) return Number(row.base_plan_qty)
  return Number(row?.plan_qty || flowCard.value?.total_qty || 0)
})
const remainingOrderQty = computed(() => Math.max(0, segmentPlanQty.value - reportedSegmentQty.value))
const claimProcesses = computed(() => segmentProcesses.value.filter((row: any) => row.status !== 'completed'))
const claimPlanQty = computed(() => {
  const plans = claimProcesses.value.map((row: any) => Number(row.plan_qty || 0))
  if (!plans.length) return Number(flowCard.value?.total_qty || 0)
  return Math.min(...plans)
})
const claimMyQty = computed(() => {
  const me = currentEmployeeId.value
  for (const process of claimProcesses.value) {
    const mine = (process.assignments || []).find((row: any) => Number(row.worker_id) === me)
    if (mine && mine.quota_qty != null) return Number(mine.quota_qty)
  }
  return 0
})
const claimRemainingQty = computed(() => {
  const me = currentEmployeeId.value
  const remainings = claimProcesses.value.map((process: any) => {
    const taken = (process.assignments || []).reduce((sum: number, row: any) => {
      if (Number(row.worker_id) === me) return sum
      if (row.quota_qty == null) return sum
      return sum + Number(row.quota_qty)
    }, 0)
    return Math.max(0, Number(process.plan_qty || 0) - taken)
  })
  if (!remainings.length) return 0
  return Math.min(...remainings)
})
const claimTakenQty = computed(() => Math.max(0, claimPlanQty.value - claimRemainingQty.value))
const claimHistory = computed(() => {
  const seen = new Set<number>()
  const rows: { worker_id: number; worker_name: string; quota_qty: number | null; created_at?: string; process_name?: string }[] = []
  for (const process of segmentProcesses.value) {
    for (const row of process.assignments || []) {
      const workerId = Number(row.worker_id)
      if (!workerId || seen.has(workerId)) continue
      seen.add(workerId)
      rows.push({
        worker_id: workerId,
        worker_name: row.worker_name,
        quota_qty: row.quota_qty == null ? null : Number(row.quota_qty),
        created_at: row.created_at,
        process_name: process.label || process.process_name,
      })
    }
  }
  return rows
})
const segmentProgressPct = computed(() => {
  const plan = segmentPlanQty.value
  if (plan <= 0) return 0
  return Math.min(100, Math.round((reportedSegmentQty.value / plan) * 100))
})
const flowStatusLabel = computed(() => ({ confirmed: '待领料', cut: '生产中', in_progress: '生产中', completed: '已完成' } as Record<string, string>)[flowCard.value?.status] || flowCard.value?.status || '—')
const availableIssueCandidates = computed(() => issueCandidates.value.filter(row => !selectedIssueRows.value.some(selectedRow => selectedRow.id === row.id) && Number(row.max_issue_qty || 0) > 0))
const cutReportedQty = computed(() => cutWorkers.value.reduce((sum, row) => sum + toPairCents(row.pairs), 0) / 100)
const canSubmitIssue = computed(() => selectedIssueRows.value.length > 0 && selectedIssueRows.value.every(row => Number(issueQtyDraft.value[row.id] || 0) > 0 && Number(issueQtyDraft.value[row.id] || 0) <= Number(row.max_issue_qty || 0)) && !issueLoading.value)
const issueSubmitHint = computed(() => {
  if (issueLoading.value) return '物料加载中…'
  if (!selectedIssueRows.value.length) return '请先添加物料'
  if (selectedIssueRows.value.some(row => Number(issueQtyDraft.value[row.id] || 0) <= 0)) return '请填写物料数量'
  if (selectedIssueRows.value.some(row => Number(issueQtyDraft.value[row.id] || 0) > Number(row.max_issue_qty || 0))) return '领料数量超过可领上限'
  return ''
})
const canSubmitCutReport = computed(() => {
  if (cutPriceError.value) return false
  if (isMultiInlineReport.value) {
    const drafts = segmentProcesses.value.map((row: any) => multiProcessDrafts.value[row.id]).filter(draft => Number(draft?.qualified || 0) > 0)
    return drafts.length > 0 && drafts.every(draft => {
      const workers = draft.workers.filter(worker => Number(worker.pairs || 0) > 0)
      return workers.length > 0
        && workers.reduce((sum, worker) => sum + toPairCents(worker.pairs), 0) === toPairCents(draft.qualified)
    }) && workshopCountsFilled()
  }
  if (!selectedSegmentProcess.value) return false
  const qualified = Number(cutQualified.value || 0)
  const workers = cutWorkers.value.filter(row => Number(row.pairs || 0) > 0)
  if (qualified <= 0 || !workers.length) return false
  const workerOk = cutCompletionMode.value === 'component'
    ? workers.every(row => toPairCents(row.pairs) >= toPairCents(qualified))
    : workers.reduce((sum, row) => sum + toPairCents(row.pairs), 0) === toPairCents(qualified)
  if (!workshopCountsFilled()) return false
  return workerOk
})
const reportSubmitHint = computed(() => {
  if (cutPriceError.value) return cutPriceError.value
  if (isMultiInlineReport.value) {
    const drafts = segmentProcesses.value.map((row: any) => multiProcessDrafts.value[row.id]).filter(draft => Number(draft?.qualified || 0) > 0)
    if (!drafts.length) return '请至少填写一道工序的本次合格数'
    if (drafts.some(draft => draft.workers.reduce((sum, worker) => sum + Math.max(0, toPairCents(worker.pairs)), 0) !== toPairCents(draft.qualified))) return '每道工序的人员双数合计须等于本次合格数'
    if (!workshopCountsFilled()) return '请清点车间剩余'
    return ''
  }
  if (!selectedSegmentProcess.value) {
    return activeSegmentName.value
      ? `这张单没有派到你部门的${activeSegmentName.value}工序`
      : '当前员工部门未关联工序段'
  }
  if (Number(cutQualified.value || 0) <= 0) return '请填写本次合格双数'
  const activeWorkers = cutWorkers.value.filter(row => Number(row.pairs || 0) > 0)
  if (!activeWorkers.length) return '请填写实际计件人员的数量'
  const qualified = Number(cutQualified.value || 0)
  const totalCents = activeWorkers.reduce((sum, row) => sum + toPairCents(row.pairs), 0)
  if (cutCompletionMode.value === 'component') {
    if (activeWorkers.some(row => toPairCents(row.pairs) < toPairCents(qualified))) return '每位人员可配双数不能少于合格双数'
  } else if (totalCents !== toPairCents(qualified)) {
    return '人员双数合计须等于本次合格双数'
  }
  if (!workshopCountsFilled()) return '请清点车间剩余'
  return ''
})
const reportSubmitQtyLabel = computed(() => {
  if (isMultiInlineReport.value) {
    const count = segmentProcesses.value.filter((row: any) => Number(multiProcessDrafts.value[row.id]?.qualified || 0) > 0).length
    return count > 0 ? ` · ${count} 道工序` : ''
  }
  const qty = Number(cutQualified.value || 0)
  return qty > 0 ? ` · ${qty} 双` : ''
})
const showCartonSticky = computed(() => {
  const row = carton.value
  if (!row) return false
  if (!row.reported_work_log_id) return true
  if (!canWarehouse.value) return false
  if (!row.warehoused_at) return true
  return !row.shipment_id
})
const reportStickyMode = computed(() => {
  if (loadingPage.value || errorMessage.value) return false
  if (kind.value === 'station') return true
  if (kind.value === 'trace') return Boolean(unit.value && !unit.value.reported)
  if (kind.value === 'carton') return showCartonSticky.value
  if (kind.value === 'subcontract') return subcontractReceipt.value?.status !== 'received'
  return false
})
function distributeEvenly(workers: any[], rawTotal: unknown) {
  const totalCents = Math.max(0, Math.round(Number(rawTotal || 0) * 100))
  if (!workers.length || totalCents <= 0) {
    workers.forEach(worker => { worker.pairs = '' })
    return
  }
  const baseCents = Math.floor(totalCents / workers.length)
  const remainderCents = totalCents - baseCents * workers.length
  workers.forEach((worker, index) => {
    const cents = baseCents + (index === workers.length - 1 ? remainderCents : 0)
    worker.pairs = cents > 0 ? formatPairDecimal(cents) : ''
  })
}
function formatPairDecimal(cents: number) {
  return (cents / 100).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
}
function toPairCents(value: unknown) {
  return Math.round(Number(value || 0) * 100)
}
function normalizePairDecimal(rawValue: unknown) {
  const raw = String(rawValue ?? '').replace(/[^\d.]/g, '')
  const [integer = '', ...decimalParts] = raw.split('.')
  const decimal = decimalParts.join('').slice(0, 2)
  const normalizedInteger = integer.replace(/^0+(?=\d)/, '')
  return raw.includes('.') ? `${normalizedInteger || '0'}.${decimal}` : normalizedInteger
}
function onWorkerPairsInput(worker: any, event: any) {
  const value = normalizePairDecimal(event?.detail?.value)
  worker.pairs = value
  return value
}
function applySingleWorkerDistribution() {
  const total = Number(cutQualified.value || 0)
  if (cutWorkers.value.length === 1) {
    cutWorkers.value[0].pairs = Number(total || 0) > 0 ? String(total) : ''
  } else if (workerSplitMode.value === 'average') {
    distributeEvenly(cutWorkers.value, total)
  }
}
watch([cutQualified, () => cutWorkers.value.length], () => {
  applySingleWorkerDistribution()
})
watch(multiReportTotal, total => {
  for (const draft of Object.values(multiProcessDrafts.value)) {
    draft.qualified = String(total || '')
    if (draft.workers.length === 1) draft.workers[0].pairs = String(total || '')
    else if (draft.splitMode === 'average') distributeEvenly(draft.workers, total)
  }
  if (canSubmitCutReport.value) reportSubmitError.value = ''
})
watch([cutReportedQty, cutPriceError, cutWorkers, cutQualified], () => {
  if (canSubmitCutReport.value) reportSubmitError.value = ''
})
watch(defectLossAmount, total => {
  if (defectResponsiblePartyType.value !== 'subcontractor') return
  if (Number(defectCompanyLossAmount.value || 0) > Number(total || 0)) defectCompanyLossAmount.value = formatPairAmount(Number(total || 0))
})
function hasFlowFeature(code: string) { return flowFeaturePermissions.value.includes(code) }
function openFlowAction(action: 'issue' | 'report' | 'claim' | 'defect' | 'subcontract' | 'report-history' | 'claim-history' | 'defect-history' | 'issue-history' | 'subcontract-history') {
  if (action === 'subcontract' && !canCreateSubcontract.value) return uni.showToast({ title: '你没有外发权限，请联系后台管理员', icon: 'none' })
  const required = ({ issue: 'material_issue', claim: 'claim_task', defect: 'register_defect' } as Record<string, string>)[action]
  if (required && !hasFlowFeature(required)) return uni.showToast({ title: '该功能未开通，请联系后台管理员', icon: 'none' })
  const target = encodeURIComponent(JSON.stringify({ kind: 'flow-card', code: code.value, h5Path: `/flow-card/${code.value}`, label: '生产流转卡', segmentCode: activeSegmentCode.value }))
  uni.navigateTo({ url: `/pages/report/index?target=${target}&segment=${activeSegmentCode.value}&action=${action}` })
}
function toggleSubcontractProcess(row: any) {
  const id = Number(row?.id)
  if (!id) return
  subcontractProcessIds.value = subcontractProcessIds.value.includes(id)
    ? subcontractProcessIds.value.filter(value => value !== id)
    : [...subcontractProcessIds.value, id]
  void refreshSubcontractMaterialPrice()
}
async function refreshSubcontractMaterialPrice() {
  const headerId = Number(flowCard.value?.header_id || 0)
  if (!headerId || !subcontractProcessIds.value.length) {
    subcontractMaterialPriceQuote.value = null
    if (!subcontractMaterialPriceManual.value) subcontractMaterialUnitPrice.value = ''
    return
  }
  try {
    const quote: any = await get('/subcontract-orders/price-quote', {
      header_id: headerId,
      order_process_ids: subcontractProcessIds.value.join(','),
    })
    subcontractMaterialPriceQuote.value = quote
    if (!subcontractMaterialPriceManual.value) {
      subcontractMaterialUnitPrice.value = Number(quote?.material_unit_price || 0).toFixed(2)
    }
  } catch {
    subcontractMaterialPriceQuote.value = null
  }
}
function pickSubcontractPartner(e: any) {
  subcontractPartnerId.value = Number(subcontractPartners.value[Number(e.detail.value)]?.id || 0) || null
}
function pickSubcontractDeliveryDate(e: any) {
  subcontractDeliveryDate.value = String(e.detail.value || '')
}
async function loadSubcontractForm() {
  const data: any = await get('/partners', { role: 'subcontractor', page_size: 500 })
  subcontractPartners.value = (data?.items || []).map((row: any) => ({
    ...row,
    display_name: row.short_name || row.name || `外加工厂 ${row.id}`,
  }))
  if (!subcontractQty.value) subcontractQty.value = String(flowCard.value?.total_qty || '')
  if (!subcontractDeliveryDate.value) subcontractDeliveryDate.value = String(flowCard.value?.delivery_date || '')
  subcontractMaterialPriceManual.value = false
  void refreshSubcontractMaterialPrice()
}
async function submitSubcontract() {
  if (!subcontractProcessIds.value.length) return uni.showToast({ title: '请选择外发工序', icon: 'none' })
  if (!subcontractPartnerId.value) return uni.showToast({ title: '请选择外加工厂', icon: 'none' })
  const totalQty = Number(subcontractQty.value || 0)
  if (!Number.isInteger(totalQty) || totalQty <= 0) return uni.showToast({ title: '外发数量须为大于 0 的整数', icon: 'none' })
  const unitPrice = Number(subcontractUnitPrice.value || 0)
  const materialUnitPrice = Number(subcontractMaterialUnitPrice.value || 0)
  if (unitPrice < 0 || materialUnitPrice < 0) return uni.showToast({ title: '单价不能小于 0', icon: 'none' })
  subcontractSubmitting.value = true
  try {
    const result: any = await post('/subcontract-orders', {
      header_id: flowCard.value.header_id,
      partner_id: subcontractPartnerId.value,
      order_process_ids: subcontractProcessIds.value,
      total_qty: totalQty,
      unit_price: unitPrice,
      material_unit_price: materialUnitPrice,
      delivery_date: subcontractDeliveryDate.value || null,
      notes: subcontractNotes.value || null,
    })
    uni.showModal({
      title: '外发单已创建',
      content: `${result?.subcontract_no || ''}\n${result?.process_name || ''} · ${totalQty} 双`,
      showCancel: false,
      confirmText: '返回',
      success: () => backToFlowActions(),
    })
  } catch (e: any) {
    uni.showToast({ title: e?.message || '创建外发单失败', icon: 'none' })
  } finally {
    subcontractSubmitting.value = false
  }
}
function backToFlowActions() {
  const pages = getCurrentPages()
  if (pages.length > 1) {
    uni.navigateBack()
    return
  }
  const target = encodeURIComponent(JSON.stringify({
    kind: 'flow-card',
    code: code.value,
    h5Path: `/flow-card/${code.value}`,
    label: '生产流转卡',
    segmentCode: activeSegmentCode.value,
  }))
  uni.redirectTo({ url: `/pages/report/index?target=${target}&segment=${activeSegmentCode.value}` })
}
function stepOverall(delta: number) {
  const next = Math.max(0, Number(multiReportTotal.value || 0) + delta)
  multiReportTotal.value = next > 0 ? String(next) : ''
}
function stepMultiQty(processId: number, delta: number) {
  const draft = multiProcessDrafts.value[processId]
  if (!draft) return
  const next = Math.round(Math.max(0, Number(draft.qualified || 0) + delta * (flowCard.value?.is_recut ? 0.5 : 1)) * 100) / 100
  draft.qualified = next > 0 ? String(next) : ''
  if (draft.workers.length === 1) draft.workers[0].pairs = draft.qualified
  else if (draft.splitMode === 'average') distributeEvenly(draft.workers, draft.qualified)
  if (canSubmitCutReport.value) reportSubmitError.value = ''
}
function stepQty(field: 'qty' | 'cutQualified' | 'claimQty', delta: number) {
  const holder = field === 'qty'
    ? qty
    : field === 'claimQty'
      ? claimQty
      : cutQualified
  const max = field === 'claimQty' ? claimRemainingQty.value : Number.POSITIVE_INFINITY
  const step = field === 'cutQualified' && flowCard.value?.is_recut ? 0.5 : 1
  const next = Math.round(Math.min(max, Math.max(0, Number(holder.value || 0) + delta * step)) * 100) / 100
  holder.value = next > 0 ? String(next) : ''
}
function initializeClaimQty() {
  if (claimMyQty.value > 0) {
    claimQty.value = String(Math.min(claimMyQty.value, claimRemainingQty.value || claimMyQty.value))
    return
  }
  claimQty.value = claimRemainingQty.value > 0 ? String(claimRemainingQty.value) : ''
}
function pickDefectType(e: any) { standaloneDefectType.value = defectTypes.value[Number(e.detail.value)]?.code || '' }
function pickDefectBrand(e: any) { standaloneDefectBrand.value = defectBrandOptions.value[Number(e.detail.value)] || '' }
function pickDefectDisposition(e: any) {
  standaloneDefectDisposition.value = defectDispositionOptions[Number(e.detail.value)]?.value || 'rework'
  if (standaloneDefectDisposition.value === 'scrap') initializeDefectResponsibilities()
}
function createDefectResponsibilityRow(amount = ''): DefectResponsibilityRow {
  defectResponsibilityKey += 1
  return { key: defectResponsibilityKey, worker_id: null, share_amount: amount }
}
function removeDefectResponsibility(index: number) {
  defectResponsibilities.value.splice(index, 1)
}
function initializeDefectResponsibilities() {
  defectResponsibilities.value = []
}
function openDefectResponsibilityPicker() {
  if (!defectResponsibleWorkers.value.length) {
    void loadDefectResponsibleWorkers().finally(() => { defectWorkerPickerVisible.value = true })
    return
  }
  defectWorkerPickerVisible.value = true
}
function isDefectResponsibilitySelected(workerId: number) {
  return defectResponsibilities.value.some(row => Number(row.worker_id) === Number(workerId))
}
function toggleDefectResponsibilityWorker(worker: any) {
  const index = defectResponsibilities.value.findIndex(row => Number(row.worker_id) === Number(worker.id))
  if (index >= 0) defectResponsibilities.value.splice(index, 1)
  else {
    const row = createDefectResponsibilityRow('')
    row.worker_id = Number(worker.id)
    defectResponsibilities.value.push(row)
  }
}
function defectAllocationPercentages() {
  const total = Number(defectLossAmount.value || 0)
  if (total <= 0) return { company: 100, workers: [] as { worker_id: number; share_percent: number }[] }
  if (defectResponsiblePartyType.value === 'subcontractor') {
    const company = Math.round(Number(defectCompanyLossAmount.value || 0) * 100 / total)
    return { company: Math.min(100, Math.max(0, company)), workers: [] }
  }
  const entries = [
    { kind: 'company', amount: defectCompanyShareAmount.value, worker_id: 0 },
    ...defectResponsibilities.value.map(row => ({ kind: 'worker', amount: Number(row.share_amount || 0), worker_id: Number(row.worker_id || 0) })),
  ].filter(row => row.amount > 0)
  const allocated = entries.map(row => {
    const exact = row.amount / total * 100
    return { ...row, percent: Math.floor(exact), remainder: exact - Math.floor(exact) }
  })
  let remaining = 100 - allocated.reduce((sum, row) => sum + row.percent, 0)
  for (const row of [...allocated].sort((a, b) => b.remainder - a.remainder)) {
    if (remaining <= 0) break
    row.percent += 1
    remaining -= 1
  }
  return {
    company: allocated.find(row => row.kind === 'company')?.percent || 0,
    workers: allocated
      .filter(row => row.kind === 'worker' && row.worker_id > 0)
      .map(row => ({ worker_id: row.worker_id, share_percent: row.percent })),
  }
}
async function loadDefectWorkers() {
  defectWorkerLoadError.value = ''
  try {
    const workers: any = await get('/shop-floor-settings/workers')
    defectWorkers.value = Array.isArray(workers) ? workers : workers?.items || []
  } catch (e: any) {
    defectWorkers.value = []
    defectWorkerLoadError.value = e?.message || '无法加载员工列表'
  }
}
async function loadDefectLossQuote() {
  const orderProcessId = Number(selectedDefectProcess.value?.id || 0)
  if (!flowCard.value?.header_id || !orderProcessId) {
    defectLossQuote.value = null
    return
  }
  const hasQuote = Boolean(defectLossQuote.value)
  if (!hasQuote) defectLossQuoteLoading.value = true
  defectLossQuoteError.value = ''
  try {
    const params: Record<string, number> = {
      header_id: flowCard.value.header_id,
      order_process_id: orderProcessId,
    }
    if (activeSegmentId.value) params.department_segment_id = activeSegmentId.value
    defectLossQuote.value = await get('/defect-events/loss-quote', params)
    defectManualMaterialQty.value = {}
    defectManualMaterialTouched.value = {}
    syncDefectManualMaterialDefaults()
  } catch (e: any) {
    defectLossQuote.value = null
    defectLossQuoteError.value = e?.message || '无法计算损失金额'
  } finally {
    defectLossQuoteLoading.value = false
  }
}
function dispatchedRouteWorkerTargets() {
  const targets = new Map<string, { processId: number; departmentId: number; segmentSort: number; routeSort: number; processName: string }>()
  const processes = [...(flowCard.value?.processes || [])].sort((a: any, b: any) =>
    Number(a.segment_sort_order ?? 1e9) - Number(b.segment_sort_order ?? 1e9)
    || Number(a.route_sort_order ?? 1e9) - Number(b.route_sort_order ?? 1e9)
    || Number(a.id) - Number(b.id)
  )
  for (const row of processes) {
    const processId = Number(row.process_id || 0)
    if (!processId) continue
    const assigned = (row.assigned_department_ids || []).map((id: unknown) => Number(id)).filter((id: number) => id > 0)
    const routeIds = new Set((row.route_department_ids || []).map((id: unknown) => Number(id)).filter((id: number) => id > 0))
    const shared = Boolean(row.route_department_shared) || !routeIds.size
    const departments = shared ? assigned : assigned.filter((id: number) => routeIds.has(id))
    for (const departmentId of departments) {
      targets.set(`${processId}:${departmentId}`, {
        processId,
        departmentId,
        segmentSort: Number(row.segment_sort_order ?? 1e9),
        routeSort: Number(row.route_sort_order ?? 1e9),
        processName: String(row.process_name || ''),
      })
    }
  }
  return [...targets.values()]
}
function defectWorkerRank(left: any, right: any) {
  return Number(left.segmentSort ?? 1e9) - Number(right.segmentSort ?? 1e9)
    || Number(left.routeSort ?? 1e9) - Number(right.routeSort ?? 1e9)
    || String(left.processName || '').localeCompare(String(right.processName || ''), 'zh-CN')
    || String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN')
}
let defectResponsibleLoadToken = 0
async function loadDefectResponsibleWorkers() {
  const token = ++defectResponsibleLoadToken
  defectWorkerLoadError.value = ''
  const targets = dispatchedRouteWorkerTargets()
  try {
    const batches = targets.length
      ? await Promise.all(targets.map(target => get('/shop-floor-settings/workers', {
        process_id: target.processId,
        department_id: target.departmentId,
      })))
      : [await get('/shop-floor-settings/workers', selectedDefectProcess.value?.process_id ? { process_id: Number(selectedDefectProcess.value.process_id) } : {})]
    if (token !== defectResponsibleLoadToken) return
    const byId = new Map<number, any>()
    batches.forEach((data, index) => {
      const target = targets[index]
      const rows = Array.isArray(data) ? data : (data as any)?.items || []
      for (const worker of rows) {
        const ranked = {
          ...worker,
          segmentSort: target?.segmentSort ?? 1e9,
          routeSort: target?.routeSort ?? 1e9,
          processName: target?.processName || '',
        }
        const previous = byId.get(Number(worker.id))
        if (!previous || defectWorkerRank(ranked, previous) < 0) byId.set(Number(worker.id), ranked)
      }
    })
    defectResponsibleWorkers.value = [...byId.values()].sort(defectWorkerRank)
  } catch (e: any) {
    if (token !== defectResponsibleLoadToken) return
    defectResponsibleWorkers.value = []
    defectWorkerLoadError.value = e?.message || '无法加载责任员工'
  }
}
function createDefectSizeLine(sizeId: number | null = null): DefectSizeLine {
  defectSizeLineKey += 1
  return { key: defectSizeLineKey, size_id: sizeId, left_qty: '', right_qty: '' }
}
async function loadDefectSubcontractOrders() {
  const headerId = flowCard.value?.header_id
  if (!headerId) {
    defectSubcontractOrders.value = []
    return
  }
  try {
    const rows: any = await get('/subcontract-orders', { header_id: headerId, page_size: 50 })
    defectSubcontractOrders.value = (rows?.items || []).filter((row: any) => row.status !== 'cancelled')
    if (defectResponsiblePartyType.value === 'subcontractor') applyFactoryDefectDefaults()
  } catch {
    defectSubcontractOrders.value = []
  }
}
function applyFactoryDefectDefaults() {
  if (!defectSubcontractOrders.value.length) return
  if (!defectSubcontractOrderId.value) {
    const first = defectSubcontractOrders.value[0]
    defectSubcontractPartnerId.value = Number(first.partner_id)
    defectSubcontractOrderId.value = Number(first.id)
  } else if (!defectSubcontractPartnerId.value) {
    const order = selectedDefectSubcontractOrder.value
    if (order) defectSubcontractPartnerId.value = Number(order.partner_id)
  }
  const order = selectedDefectSubcontractOrder.value
  const routeId = Number(order?.order_process_ids?.[0] || 0)
  if (routeId && defectProcessOptions.value.some((row: any) => Number(row.id) === routeId)) {
    selectedOrderProcessId.value = routeId
    return
  }
  const processId = Number(order?.process_id || 0)
  const match = defectProcessOptions.value.find((row: any) => Number(row.process_id) === processId)
  if (match) selectedOrderProcessId.value = Number(match.id)
}
function pickDefectPartner(e: any) {
  const option = defectPartnerOptions.value[Number(e.detail.value)]
  defectSubcontractPartnerId.value = option?.id ? Number(option.id) : null
  defectSubcontractOrderId.value = null
  const orders = defectOrdersForPartner.value
  if (orders.length === 1) defectSubcontractOrderId.value = Number(orders[0].id)
  standaloneDefectScrapSource.value = 'subcontract'
  applyFactoryDefectDefaults()
}
function pickDefectSubcontractOrder(e: any) {
  const option = defectOrdersForPartner.value[Number(e.detail.value)]
  defectSubcontractOrderId.value = option?.id ? Number(option.id) : null
  standaloneDefectScrapSource.value = 'subcontract'
  applyFactoryDefectDefaults()
}
function setDefectResponsibleParty(type: 'employee' | 'subcontractor') {
  if (defectResponsiblePartyType.value === type) return
  defectResponsiblePartyType.value = type
  if (type === 'subcontractor') {
    standaloneDefectScrapSource.value = 'subcontract'
    defectCompanyLossAmount.value = '0'
    applyFactoryDefectDefaults()
  } else {
    standaloneDefectScrapSource.value = 'internal'
    standaloneDefectReplacementSource.value = 'internal'
    defectCompanyLossAmount.value = formatPairAmount(Number(defectLossAmount.value || 0))
  }
}
function initializeDefectContext() {
  standaloneDefectBrand.value = defectBrandOptions.value[0] || ''
  selectedOrderProcessId.value = null
  standaloneDefectDisposition.value = 'scrap'
  standaloneDefectScrapSource.value = 'internal'
  standaloneDefectReplacementSource.value = 'internal'
  defectResponsiblePartyType.value = 'employee'
  defectSubcontractPartnerId.value = null
  defectSubcontractOrderId.value = null
  defectLossQuote.value = null
  defectLossQuoteError.value = ''
  defectLossDetailOpen.value = false
  defectManualMaterialsOpen.value = false
  defectManualMaterialQty.value = {}
  defectManualMaterialTouched.value = {}
  defectCompanyLossAmount.value = '0'
  initializeDefectResponsibilities()
  const options = defectSizeOptions.value
  defectSizeLines.value = options.length
    ? options.map((row: any) => createDefectSizeLine(Number(row.size_id)))
    : [createDefectSizeLine(null)]
  defectPhotos.value = []
  void Promise.all([loadDefectResponsibleWorkers(), loadDefectLossQuote(), loadDefectSubcontractOrders()])
}
async function chooseDefectPhotos() {
  if (defectPhotoUploading.value || defectPhotos.value.length >= 3) return
  try {
    const result = await uni.chooseImage({ count: Math.min(3 - defectPhotos.value.length, 3), sizeType: ['compressed'], sourceType: ['camera', 'album'] })
    const paths = result?.tempFilePaths || []
    for (const localPath of paths) {
      const photo: DefectPhoto = { localPath, uploading: true }
      defectPhotos.value.push(photo)
      defectPhotoUploading.value = true
      try {
        const uploaded: any = await uploadFile('/defect-events/upload-photo', localPath)
        photo.url = uploaded?.url || ''
        if (!photo.url) throw new Error('上传失败')
      } catch (e: any) {
        defectPhotos.value = defectPhotos.value.filter(item => item !== photo)
        uni.showToast({ title: e?.message || '照片上传失败', icon: 'none' })
      } finally {
        photo.uploading = false
        defectPhotoUploading.value = defectPhotos.value.some(item => item.uploading)
      }
    }
  } catch {
    /* user cancelled */
  }
}
function removeDefectPhoto(index: number) {
  defectPhotos.value.splice(index, 1)
  defectPhotoUploading.value = defectPhotos.value.some(item => item.uploading)
}
function initializeSelectedProcess() {
  if (segmentProcesses.value.length === 1) {
    selectedOrderProcessId.value = Number(segmentProcesses.value[0].id)
  } else if (!segmentProcesses.value.some((row: any) => Number(row.id) === Number(selectedOrderProcessId.value))) {
    selectedOrderProcessId.value = null
  }
}
function initializeMultiProcessDrafts() {
  const current = multiProcessDrafts.value
  const next: Record<number, MultiProcessDraft> = {}
  for (const row of segmentProcesses.value) {
    next[row.id] = current[row.id] || { qualified: '', workers: [], splitMode: 'average', unitPrice: 0 }
    next[row.id].splitMode = 'average'
  }
  multiProcessDrafts.value = next
}
async function pickSegmentProcess(e: any) {
  const row = segmentProcesses.value[Number(e.detail.value)]
  selectedOrderProcessId.value = row ? Number(row.id) : null
  if (flowAction.value === 'defect') {
    defectResponsibilities.value = []
    await Promise.all([loadDefectResponsibleWorkers(), loadDefectLossQuote()])
  }
}
async function pickDefectProcess(e: any) {
  const row = departmentRouteProcesses.value[Number(e.detail.value)]
  selectedOrderProcessId.value = row ? Number(row.id) : null
  defectResponsibilities.value = []
  await Promise.all([loadDefectResponsibleWorkers(), loadDefectLossQuote()])
}
async function selectReportProcess(row: any) {
  if (Number(row?.id) === Number(selectedOrderProcessId.value)) return
  selectedOrderProcessId.value = row ? Number(row.id) : null
  cutQualified.value = ''
  cutWorkers.value = []
  workerSplitMode.value = 'individual'
  reportSubmitError.value = ''
  if (flowAction.value === 'report') {
    await Promise.all([
      loadCutWorkers(selectedOrderProcessId.value),
      loadCutQuote(),
      loadWorkshopCounts(Number(flowCard.value?.header_id || 0), {
        order_process_ids: isMultiInlineReport.value
          ? segmentProcesses.value.map((row: any) => row.id).join(',')
          : String(row?.id || ''),
      }),
    ])
  }
}
const money = (v: unknown) => Number(v || 0).toFixed(2)
const formatTime = (v?: string) => String(v || '').replace('T', ' ').slice(0, 16)
const formatQty = (v: unknown) => Number(v || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const materialName = (row: any) => row?.supplier_product_name || row?.supplier_product_code || '未命名物料'
const stockDocStatusLabel = (value?: string) => ({ pending: '待仓库确认', posted: '已过账', void: '已作废' } as Record<string, string>)[String(value || '')] || value || '—'
const subcontractStatusLabel = (value?: string) => ({ draft: '草稿', issued: '外发中', partial_received: '部分完工', received: '已完工', cancelled: '已取消' } as Record<string, string>)[String(value || '')] || value || '—'
const defectHistoryStatusLabel = (row: any) => row?.status === 'closed' ? '已确认' : row?.needs_my_confirm ? '待确认' : '已登记'
const defectHistoryPartyLabel = (row: any) => {
  if (row?.responsible_party_type === 'subcontractor') return row.subcontract_partner_name || '外发厂'
  const names = (row?.responsibilities || []).map((item: any) => item.worker_name).filter(Boolean)
  if (names.length) return names.join('、')
  return row?.responsible_worker_name || '公司'
}
const batchStatusLabel = (value?: string) => ({ open: '待生产', in_production: '生产中', confirmed: '已确认' } as Record<string, string>)[String(value || '')] || value || '—'
const basketStatusLabel = (value?: string) => ({ idle: '空闲', bound: '装框中', in_transit: '待下游接收', on_line: '产线上', waiting_qc: '待质检', maintenance: '维修', lost: '丢失', disabled: '停用' } as Record<string, string>)[String(value || '')] || value || '—'
function reportSucceeded(content: string) {
  uni.showModal({
    title: '报工成功',
    content,
    showCancel: false,
    confirmText: '返回首页',
    success: result => { if (result.confirm) uni.reLaunch({ url: '/pages/home/index' }) },
  })
}

function showIssueSuccess() {
  issueNotice.value = '领料申请成功'
  if (issueNoticeTimer) clearTimeout(issueNoticeTimer)
  issueNoticeTimer = setTimeout(() => { issueNotice.value = '' }, 2000)
}

onUnmounted(() => {
  if (issueNoticeTimer) clearTimeout(issueNoticeTimer)
})

async function refreshCurrent() {
  if (!kind.value || !code.value) return
  if (kind.value === 'station') {
    station.value = await get(`/stations/by-code/${encodeURIComponent(code.value)}`)
    const data: any = await get(`/stations/by-code/${encodeURIComponent(code.value)}/report-candidates`)
    candidates.value = data?.items || []
    if (!selectedOrderNo.value || !candidates.value.some(row => row.order_no === selectedOrderNo.value)) {
      selectedOrderNo.value = data?.default_order_no || candidates.value[0]?.order_no || ''
    }
    applyCandidate()
    return
  }
  if (kind.value === 'trace') {
    unit.value = await get(`/trace-units/by-code/${encodeURIComponent(code.value)}`)
    return
  }
  if (kind.value === 'carton') {
    carton.value = await get(`/packing-cartons/by-code/${encodeURIComponent(code.value)}`)
    return
  }
  if (kind.value === 'basket') {
    basketInfo.value = await get(`/reusable-baskets/by-code/${encodeURIComponent(code.value)}`)
    return
  }
  if (kind.value === 'subcontract') {
    subcontractReceipt.value = await get(`/subcontract-orders/${code.value}`)
    subcontractReceiptQty.value = String(subcontractReceipt.value?.outstanding_qty || '')
    subcontractReceiptDeliveryNote.value = ''
    return
  }
  if (kind.value === 'flow-card') {
    const selectedIds = new Set(selectedIssueRows.value.map((row: any) => Number(row.id)))
    const qtyDraft = { ...issueQtyDraft.value }
    const pairDraft = { ...issuePairDraft.value }
    flowCard.value = await get(`/executions/headers/${code.value}/flow-card`)
    applyEmployeeSegment()
    initializeSelectedProcess()
    if (flowAction.value === 'issue') {
      await Promise.all([loadIssueCandidates(), loadFlowHistories()])
      selectedIssueRows.value = issueCandidates.value.filter((row: any) => selectedIds.has(Number(row.id)))
      issueQtyDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, qtyDraft[row.id] ?? '']))
      issuePairDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, pairDraft[row.id] ?? '']))
    } else if (flowAction.value === 'report') {
      await Promise.all([loadFlowHistories(), loadCutWorkers(selectedOrderProcessId.value), loadCutQuote(), loadFlowWorkshopCounts()])
    } else {
      await loadFlowHistories()
    }
  }
}

onPullDownRefresh(async () => {
  try {
    await refreshCurrent()
  } catch (e: any) {
    uni.showToast({ title: e?.message || '刷新失败', icon: 'none' })
  } finally {
    uni.stopPullDownRefresh()
  }
})

onLoad(async query => {
  loadQuery.value = query as Record<string, string | undefined>
  await initializePage(query)
})

async function retryLoad() {
  if (!loadQuery.value) return
  errorMessage.value = ''
  loadingPage.value = true
  await initializePage(loadQuery.value)
}

async function initializePage(query: any) {
  const target = decodeTarget(query?.target)
  if (!target) { errorMessage.value = '扫码内容无效'; loadingPage.value = false; return }
  kind.value = target.kind; code.value = target.code
  try {
    currentEmployee.value = await get('/auth/me')
    flowFeaturePermissions.value = Array.isArray(currentEmployee.value?.feature_permissions) ? currentEmployee.value.feature_permissions : []
    if (target.kind === 'station') {
      station.value = await get(`/stations/by-code/${encodeURIComponent(target.code)}`)
      const data: any = await get(`/stations/by-code/${encodeURIComponent(target.code)}/report-candidates`)
      candidates.value = data?.items || []; selectedOrderNo.value = data?.default_order_no || candidates.value[0]?.order_no || ''; applyCandidate()
    } else if (target.kind === 'trace') {
      unit.value = await get(`/trace-units/by-code/${encodeURIComponent(target.code)}`)
      orderNo.value = unit.value.order_no || unit.value.header_no || ''; colorName.value = unit.value.color_name || ''; sizeValue.value = unit.value.size_value || ''; qty.value = String(unit.value.qty || '')
      const processIds = currentEmployeeProcessIds.value
      const processNames = currentEmployeeProcessNames.value
      const mine = (unit.value.order_processes || []).filter((row: any) =>
        processIds.includes(Number(row.process_id)) || processNames.includes(String(row.process_name || ''))
      )
      const next = mine.find((row: any) => row.status !== 'completed') || mine[0]
      processName.value = next?.process_name || ''
      if (!processName.value) throw new Error(processNames.length ? `该码不包含你的员工工序（${processNames.join('、')}）` : '当前员工未配置工序')
      await loadWorkshopCounts(Number(unit.value.header_id || 0), next?.id ? { order_process_ids: String(next.id) } : { process_id: next?.process_id })
    } else if (target.kind === 'carton') carton.value = await get(`/packing-cartons/by-code/${encodeURIComponent(target.code)}`)
    else if (target.kind === 'basket') basketInfo.value = await get(`/reusable-baskets/by-code/${encodeURIComponent(target.code)}`)
    else if (target.kind === 'subcontract') {
      subcontractReceipt.value = await get(`/subcontract-orders/${target.code}`)
      subcontractReceiptQty.value = String(subcontractReceipt.value?.outstanding_qty || '')
      subcontractReceiptDeliveryNote.value = ''
      uni.setNavigationBarTitle({ title: '外发验收登记' })
    }
    else if (target.kind === 'flow-card') {
      flowCard.value = await get(`/executions/headers/${target.code}/flow-card`)
      applyEmployeeSegment()
      initializeSelectedProcess()
      const requestedAction = String(query?.action || '')
      const allowedActions = ['issue', 'report', 'claim', 'defect', 'subcontract', 'report-history', 'claim-history', 'defect-history', 'issue-history', 'subcontract-history']
      flowAction.value = allowedActions.includes(requestedAction) ? requestedAction as any : ''
      uni.setNavigationBarTitle({ title: flowAction.value ? flowActionTitle.value : '选择手机功能' })
      if (flowAction.value === 'issue') {
        await Promise.all([loadIssueCandidates(), loadFlowHistories()])
        restoreLastIssueMaterials()
      } else if (flowAction.value === 'report') {
        if (!selectedSegmentProcess.value) {
          const defaultProcess = segmentProcesses.value.find((row: any) => row.status !== 'completed') || segmentProcesses.value[0]
          selectedOrderProcessId.value = defaultProcess ? Number(defaultProcess.id) : null
        }
        await Promise.all([loadFlowHistories(), loadCutWorkers(selectedOrderProcessId.value), loadCutQuote(), loadFlowWorkshopCounts()])
      } else if (flowAction.value === 'defect') {
        const data: any = await get('/defect-types')
        defectTypes.value = data?.items || []
        standaloneDefectType.value = defectTypes.value[0]?.code || ''
        await Promise.all([loadDefectWorkers(), loadFlowHistories()])
        initializeDefectContext()
      } else if (flowAction.value === 'subcontract') {
        if (!canCreateSubcontract.value) throw new Error('你没有外发权限，请联系后台管理员')
        await Promise.all([loadSubcontractForm(), loadFlowHistories()])
      } else if (flowAction.value === 'claim') {
        initializeClaimQty()
      } else if (flowAction.value.endsWith('-history')) {
        await loadFlowHistories()
      }
    }
  } catch (e: any) { errorMessage.value = e?.message || '扫码信息加载失败' }
  finally { loadingPage.value = false }
}

function applyCandidate() { const row = selected.value; if (!row) return; orderNo.value = row.order_no; const sku = row.items?.length === 1 ? row.items[0] : null; colorName.value = sku?.color_name || row.last_color_name || ''; sizeValue.value = sku?.size_value || row.last_size_value || ''; void loadWorkshopCounts(Number(row.header_id || 0), { process_id: station.value?.process_id || undefined }) }
async function submitSubcontractReceipt() {
  const quantity = Number(subcontractReceiptQty.value || 0)
  const outstanding = Number(subcontractReceipt.value?.outstanding_qty || 0)
  if (!Number.isInteger(quantity) || quantity <= 0) return uni.showToast({ title: '请输入完工数量', icon: 'none' })
  if (quantity > outstanding) return uni.showToast({ title: `完工数量不能超过 ${outstanding} 双`, icon: 'none' })
  submitting.value = true
  try {
    subcontractReceipt.value = await post(`/subcontract-orders/${subcontractReceipt.value.id}/receipts`, {
      qty: quantity,
      delivery_note_no: subcontractReceiptDeliveryNote.value || null,
      note: subcontractReceiptNote.value || null,
    })
    subcontractReceiptQty.value = String(subcontractReceipt.value?.outstanding_qty || '')
    subcontractReceiptNote.value = ''
    subcontractReceiptDeliveryNote.value = ''
    uni.showToast({ title: '验收登记成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e?.message || '验收登记失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
function chooseCandidate(row: any) { selectedOrderNo.value = row.order_no; applyCandidate(); candidatePicker.value = false }
function pickReportType(e: any) { reportType.value = reportTypes[Number(e.detail.value)]?.value || 'normal' }
function validate() { if (!orderNo.value || !processName.value || Number(qty.value) <= 0) { uni.showToast({ title: '请填写单号、工序和数量', icon: 'none' }); return false } if (!workshopCountsFilled()) { uni.showToast({ title: '请清点车间剩余', icon: 'none' }); return false } return true }
async function submit(payload: any) { submitting.value = true; successResult.value = null; try { const data: any = await post('/reports', payload); if (data?.need_confirm) throw new Error(data.message || '报工数量超过计划'); successResult.value = data; clearWorkshopDrafts(); reportSucceeded(`${data?.process_name || processName.value || '本工序'} · ${data?.qualified_qty ?? qty.value} 双`) } catch (e: any) { uni.showToast({ title: e?.message || '报工失败', icon: 'none' }) } finally { submitting.value = false } }
function commonPayload() { return { worker_id: currentEmployeeId.value, order_no: orderNo.value, process_name: processName.value, color_name: colorName.value || null, size_value: sizeValue.value || null, qualified_qty: Number(qty.value), source: 'qrcode', confirm_over_plan: true, report_type: reportType.value, workshop_counts: workshopCountPayload() } }
function loadFlowWorkshopCounts() {
  if (!needsWorkshopCount.value) {
    workshopCounts.value = []
    workshopQtyDraft.value = {}
    return
  }
  const headerId = Number(flowCard.value?.header_id || 0)
  if (activeSegmentId.value) {
    return loadWorkshopCounts(headerId, { consume_segment_id: activeSegmentId.value })
  }
  const ids = isMultiInlineReport.value
    ? segmentProcesses.value.map((row: any) => row.id)
    : [selectedOrderProcessId.value].filter(Boolean)
  return loadWorkshopCounts(headerId, { order_process_ids: ids.join(',') })
}
function submitStation() { processName.value = station.value?.process_name || ''; if (!selected.value) orderNo.value = orderNo.value.trim(); if (!validate()) return; void submit({ ...commonPayload(), station_id: station.value.id }) }
function submitTrace() { if (!validate()) return; void submit({ ...commonPayload(), header_id: unit.value.header_id || undefined, trace_unit_id: unit.value.id, create_trace_bundle: false, proxy: false }) }
async function submitCarton() { submitting.value = true; try { const data: any = await post('/carton-reports', { carton_code: carton.value.code, confirm_over_plan: true }); successResult.value = data; carton.value.reported_work_log_id = data.work_log_id; reportSucceeded(`包装 · ${carton.value.total_qty || 0} 双`) } catch (e: any) { uni.showToast({ title: e?.message || '报工失败', icon: 'none' }) } finally { submitting.value = false } }
async function warehouseCarton() { submitting.value = true; try { const data: any = await post(`/packing-cartons/${carton.value.id}/warehouse`, {}); carton.value.warehoused_at = data.warehoused_at; uni.showToast({ title: '入库成功', icon: 'success' }) } catch (e: any) { uni.showToast({ title: e?.message || '入库失败', icon: 'none' }) } finally { submitting.value = false } }
async function shipCarton() { submitting.value = true; try { const data: any = await post(`/packing-cartons/${carton.value.id}/ship`, {}); carton.value.shipment_id = data.shipment_id; uni.showToast({ title: '出库成功', icon: 'success' }) } catch (e: any) { uni.showToast({ title: e?.message || '出库失败', icon: 'none' }) } finally { submitting.value = false } }
function goHome() { uni.reLaunch({ url: '/pages/home/index' }) }
function openBasketTask() {
  const headerId = Number(basketInfo.value?.journey?.header_id || 0)
  if (!headerId) return
  const target = encodeURIComponent(JSON.stringify({ kind: 'flow-card', code: String(headerId), h5Path: `/flow-card/${headerId}`, label: '生产流转卡' }))
  uni.redirectTo({ url: `/pages/report/index?target=${target}` })
}
function pickCutCompletionMode(e: any) {
  cutCompletionMode.value = (cutCompletionModes[Number(e.detail.value)]?.value || 'complete') as any
}

/** 报工段跟员工部门上的工序段走，不写死裁断、针车、成型。 */
function applyEmployeeSegment() {
  const employee = currentEmployee.value || {}
  activeSegmentId.value = Number(employee.process_segment_id || 0)
  activeSegmentCode.value = String(employee.process_segment_code || '')
  activeSegmentName.value = String(employee.process_segment_name || '')
}

function flowCardReportSource() {
  if (activeSegmentCode.value === 'stitch') return 'flow_card_stitching'
  if (activeSegmentCode.value === 'forming') return 'flow_card_forming'
  if (activeSegmentCode.value === 'cut') return 'flow_card_cutting'
  return 'flow_card'
}

function segmentProcess() {
  return selectedSegmentProcess.value || segmentProcesses.value.find((row: any) => row.status !== 'completed') || segmentProcesses.value[0]
}

function effectivePerPair(row: any) {
  return Number(row?.effective_qty_per_pair || 0) || Number(row?.qty_per_pair || 0) * Number(row?.size_coeff || 1) * (1 + Number(row?.loss_rate || 0))
}

async function loadIssueCandidates() {
  issueLoading.value = true
  try {
    const segmentId = Number(segmentProcess()?.segment_id || 0)
    if (!segmentId) throw new Error(`${segmentLabel.value}工序未配置工序段，请先在基础资料中维护`)
    const data: any = await get('/stock-issues/candidates', {
      header_id: flowCard.value.header_id,
      consume_segment_id: segmentId,
      pairs: remainingOrderQty.value || Number(flowCard.value?.total_qty || 0),
    })
    issueCandidates.value = data?.lines || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '领料数据加载失败', icon: 'none' })
  } finally { issueLoading.value = false }
}

async function loadFlowHistories() {
  const headerId = flowCard.value?.header_id
  if (!headerId) return
  const action = flowAction.value
  const tasks: Promise<void>[] = []
  if (action === 'issue' || action === 'issue-history') {
    tasks.push((async () => {
      const issues: any = await get('/stock-issues', { header_id: headerId, doc_type: 'issue', page_size: 100 })
      issueHistory.value = issues?.items || []
    })())
  }
  if (action === 'report' || action === 'report-history') {
    tasks.push((async () => {
      const logs: any = await get(`/executions/headers/${headerId}/segment-report-history`, {
        segment_id: activeSegmentId.value || undefined,
        segment_code: activeSegmentCode.value || undefined,
      })
      cutHistory.value = logs?.items || []
    })())
  }
  if (action === 'defect' || action === 'defect-history') {
    tasks.push((async () => {
      const defects: any = await get('/defect-events', { header_id: headerId, page_size: 50 })
      defectHistory.value = defects?.items || []
    })())
  }
  if (action === 'subcontract' || action === 'subcontract-history') {
    tasks.push((async () => {
      const rows: any = await get('/subcontract-orders', { header_id: headerId, page_size: 50 })
      subcontractHistory.value = rows?.items || []
    })())
  }
  if (tasks.length) await Promise.all(tasks)
}

async function claimTask() {
  const quantity = Number(claimQty.value || 0)
  if (!Number.isInteger(quantity) || quantity <= 0) return uni.showToast({ title: '请填写领取双数', icon: 'none' })
  if (quantity > claimRemainingQty.value) return uni.showToast({ title: `还可领 ${claimRemainingQty.value} 双`, icon: 'none' })
  claimSubmitting.value = true
  try {
    const result: any = await post(`/executions/headers/${flowCard.value.header_id}/claim-task`, {
      segment_code: activeSegmentCode.value || undefined,
      qty: quantity,
    })
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    initializeClaimQty()
    uni.showModal({
      title: result?.claimed ? '任务已领取' : '任务数量已更新',
      content: `${result?.segment_name || segmentLabel.value} · ${result?.qty || quantity} 双`,
      showCancel: false,
    })
  } catch (e: any) { uni.showToast({ title: e?.message || '领取任务失败', icon: 'none' }) }
  finally { claimSubmitting.value = false }
}

async function submitStandaloneDefect() {
  if (!standaloneDefectType.value) return uni.showToast({ title: '请选择不良类型', icon: 'none' })
  if (!selectedDefectProcess.value) return uni.showToast({ title: '请选择发现工序', icon: 'none' })
  if (!standaloneDefectDisposition.value) return uni.showToast({ title: '请选择损失判定', icon: 'none' })
  if (defectPhotoUploading.value) return uni.showToast({ title: '照片上传中，请稍候', icon: 'none' })
  const sizeLines = defectSizeLines.value
    .map(line => ({
      size_id: Number(line.size_id || 0),
      left_qty: Number(line.left_qty || 0),
      right_qty: Number(line.right_qty || 0),
      loss_amount: defectSizeLineLoss(line),
    }))
    .filter(line => line.left_qty + line.right_qty > 0)
  if (!sizeLines.length) return uni.showToast({ title: '请至少填写一个码数的左脚或右脚数量', icon: 'none' })
  if (sizeLines.some(line => line.size_id <= 0)) return uni.showToast({ title: '请选择码数', icon: 'none' })
  if (defectLossQuoteLoading.value) return uni.showToast({ title: '损失金额计算中，请稍候', icon: 'none' })
  if (defectLossQuoteError.value) return uni.showToast({ title: defectLossQuoteError.value, icon: 'none' })
  const companyShare = defectResponsiblePartyType.value === 'subcontractor'
    ? Number(defectCompanyLossAmount.value || 0)
    : defectCompanyShareAmount.value
  if (companyShare < 0 || defectResponsibilities.value.some(row => Number(row.share_amount || 0) < 0)) {
    return uni.showToast({ title: '分摊金额不能小于 0', icon: 'none' })
  }
  if (!defectAllocationBalanced.value) return uni.showToast({ title: `分摊合计须等于 ¥${defectLossAmount.value}`, icon: 'none' })
  const seen = new Set<number>()
  for (const line of sizeLines) {
    if (seen.has(line.size_id)) return uni.showToast({ title: '同一码数请勿重复登记', icon: 'none' })
    seen.add(line.size_id)
  }
  if (defectResponsiblePartyType.value === 'subcontractor') {
    if (!defectSubcontractPartnerId.value) return uni.showToast({ title: '请选择外发厂', icon: 'none' })
    if (!defectSubcontractOrderId.value) return uni.showToast({ title: '请选择对应的外发单', icon: 'none' })
  }
  if (companyShare > Number(defectLossAmount.value || 0)) {
    return uni.showToast({ title: '公司承担不能大于损失金额', icon: 'none' })
  }
  if (defectResponsiblePartyType.value === 'employee' && defectResponsibilities.value.some(row => !row.worker_id)) {
    return uni.showToast({ title: '请选择责任员工', icon: 'none' })
  }
  if (defectResponsiblePartyType.value !== 'subcontractor') {
    for (const row of defectCurrentMaterialLines.value) {
      if (!row.usage_by_size) continue
      for (const size of row.sizes || []) {
        const materialQty = Number(defectManualMaterialQty.value[defectManualQtyKey(row.supplier_product_id, size.size_id)] || 0)
        const scrapQty = defectSizeLines.value
          .filter(line => Number(line.size_id) === Number(size.size_id))
          .reduce((sum, line) => sum + Number(line.left_qty || 0) + Number(line.right_qty || 0), 0)
        if (materialQty > 0 && scrapQty <= 0) return uni.showToast({ title: `请先填写 ${size.size_value} 码的报废数量`, icon: 'none' })
      }
    }
  }
  const reportQty = Number(defectScrapReportQty.value || 0)
  let supervisorReport: Record<string, unknown> | null = null
  if (groupReport.value && defectSupervisorLaborLines.value.length) {
    if (reportQty - defectScrapReportMax.value > 0.001) return uni.showToast({ title: '不能超过报废数量', icon: 'none' })
    const processes = defectSupervisorLaborLines.value.map(row => {
      const workers = defectReportDrafts.value[Number(row.key)]?.workers || []
      const shares = workers
        .map((worker: any) => ({ worker_id: Number(worker.id), pairs: Number(worker.pairs || 0) }))
        .filter((share: any) => share.pairs > 0)
      return { order_process_id: Number(row.key), process_name: row.name, shares }
    }).filter(row => row.order_process_id > 0)
    for (const row of processes) {
      const sum = row.shares.reduce((total: number, share: any) => total + share.pairs, 0)
      if (sum - defectScrapReportMax.value > 0.001) return uni.showToast({ title: `${row.process_name}不能超过报废数量`, icon: 'none' })
    }
    supervisorReport = {
      qualified_qty: reportQty,
      color_name: flowCard.value?.color_name || null,
      processes,
    }
  }
  const photoUrls = defectPhotos.value.map(photo => photo.url).filter((url): url is string => Boolean(url))
  defectSubmitting.value = true
  try {
    const allocation = defectAllocationPercentages()
    const payload: Record<string, unknown> = {
      header_id: flowCard.value.header_id,
      brand_name: standaloneDefectBrand.value || null,
      found_process_id: selectedDefectProcess.value.process_id,
      defect_type: standaloneDefectType.value,
      size_lines: sizeLines,
      disposition: standaloneDefectDisposition.value,
      scrap_source: defectResponsiblePartyType.value === 'subcontractor' ? 'subcontract' : 'internal',
      subcontract_order_id: defectResponsiblePartyType.value === 'subcontractor' ? defectSubcontractOrderId.value : null,
      responsible_party_type: defectResponsiblePartyType.value,
      replacement_source: standaloneDefectReplacementSource.value,
      note: standaloneDefectNote.value || null,
      photo_urls: photoUrls.length ? photoUrls : null,
      auto_suggest_worker: false,
      company_share_percent: allocation.company,
      responsibilities: defectResponsiblePartyType.value === 'subcontractor' ? [] : allocation.workers,
      department_segment_id: activeSegmentId.value || null,
      manual_materials: defectResponsiblePartyType.value === 'subcontractor'
        ? []
        : defectCurrentMaterialLines.value.flatMap((row: any) => {
          if (row.usage_by_size) {
            return (row.sizes || []).map((size: any) => ({
              supplier_product_id: Number(row.supplier_product_id),
              size_id: Number(size.size_id),
              qty: Number(defectManualMaterialQty.value[defectManualQtyKey(row.supplier_product_id, size.size_id)] || 0),
            }))
          }
          return [{
            supplier_product_id: Number(row.supplier_product_id),
            qty: Number(defectManualMaterialQty.value[defectManualQtyKey(row.supplier_product_id)] || 0),
          }]
        }).filter((row: any) => row.qty > 0),
      supervisor_report: supervisorReport,
    }
    const result: any = await post('/defect-events', payload)
    const items = Array.isArray(result?.items) ? result.items : [result]
    const summary = items.map((item: any) => {
      const sideText = [`左脚${Number(item.left_qty || 0)}`, `右脚${Number(item.right_qty || 0)}`]
        .filter((text, index) => (index === 0 ? Number(item.left_qty || 0) : Number(item.right_qty || 0)) > 0)
        .join('、')
      return `${item.size_value || '—'}码 · ${sideText}`
    }).join('\n')
    initializeDefectContext()
    standaloneDefectNote.value = ''
    await loadFlowHistories()
    uni.showModal({
      title: '报废已登记',
      content: summary,
      showCancel: false,
    })
  } catch (e: any) { uni.showToast({ title: e?.message || '报废登记失败', icon: 'none' }) }
  finally { defectSubmitting.value = false }
}

function restoreLastIssueMaterials() {
  const currentWorkerId = currentEmployeeId.value
  if (!currentWorkerId) return
  const currentSegmentRequirementIds = new Set(issueCandidates.value.map((row: any) => Number(row.id)))
  const lastMine = issueHistory.value.find((doc: any) =>
    Number(doc.created_by || 0) === currentWorkerId
    && doc.status !== 'void'
    && (doc.lines || []).some((line: any) => currentSegmentRequirementIds.has(Number(line.order_material_requirement_id || 0)))
  )
  if (!lastMine) return
  const requirementIds = new Set(
    (lastMine.lines || []).map((line: any) => Number(line.order_material_requirement_id || 0))
  )
  selectedIssueRows.value = issueCandidates.value.filter((row: any) => requirementIds.has(Number(row.id)))
  const qtyDraft: Record<number, string> = {}
  const pairDraft: Record<number, string> = {}
  for (const row of selectedIssueRows.value) {
    qtyDraft[row.id] = ''
    pairDraft[row.id] = ''
  }
  issueQtyDraft.value = qtyDraft
  issuePairDraft.value = pairDraft
}

function selfReportWorker(pool: any[] = []) {
  const found = pool.find((worker: any) => Number(worker.id) === currentEmployeeId.value)
  return found
    ? { ...found, pairs: '' }
    : { id: currentEmployeeId.value, name: currentEmployeeName.value, pairs: '' }
}
function collectiveWorkerPool(workers: any[]) {
  const deptIds = new Set(ledDepartmentIds.value)
  const me = currentEmployeeId.value
  const pool = workers.filter((worker: any) => Number(worker.id) === me || deptIds.has(Number(worker.department_id)))
  if (!pool.some((worker: any) => Number(worker.id) === me)) pool.unshift(selfReportWorker(workers))
  return pool
}
function assignedDepartmentIds(row: any): number[] {
  return [...new Set((row?.assigned_department_ids || []).map((id: unknown) => Number(id)).filter((id: number) => id > 0))]
}
function workersInDepartments(workers: any[], departmentIds: number[]) {
  if (!departmentIds.length) return workers
  const allow = new Set(departmentIds)
  return workers.filter((worker: any) => allow.has(Number(worker.department_id)))
}
function listedReportWorkers(options: any[], previous: any[], qualified: unknown) {
  const oldPairs = new Map(previous.map((worker: any) => [Number(worker.id), worker.pairs]))
  const chosen = options.map((worker: any) => ({
    ...worker,
    pairs: oldPairs.get(Number(worker.id)) || '',
  }))
  if (chosen.length === 1) chosen[0].pairs = Number(qualified || 0) > 0 ? String(qualified) : ''
  return chosen
}
async function loadCutWorkers(orderProcessId?: number | null) {
  cutWorkerLoadError.value = ''
  try {
    if (isMultiInlineReport.value) {
      initializeMultiProcessDrafts()
      const entries = await Promise.all(segmentProcesses.value.map(async row => {
        const departmentIds = assignedDepartmentIds(row)
        const params: Record<string, string | number> = { process_id: Number(row.process_id) }
        if (activeSegmentCode.value) params.segment_code = activeSegmentCode.value
        if (departmentIds.length === 1) params.department_id = departmentIds[0]
        const data: any = await get('/shop-floor-settings/workers', params)
        const listed = workersInDepartments(Array.isArray(data) ? data : data?.items || [], departmentIds)
        return [Number(row.id), listed, departmentIds] as const
      }))
      const allWorkers = new Map<number, any>()
      const options: Record<number, any[]> = {}
      for (const [processRowId, workers, departmentIds] of entries) {
        const draft = multiProcessDrafts.value[processRowId]
        const pool = groupReport.value
          ? (departmentIds.length ? workers : collectiveWorkerPool(workers))
          : [selfReportWorker(workers)]
        options[processRowId] = pool
        if (draft) {
          draft.workers = groupReport.value
            ? listedReportWorkers(pool, draft.workers, draft.qualified)
            : [{ ...selfReportWorker(workers), pairs: Number(draft.qualified || 0) > 0 ? String(draft.qualified) : '' }]
          if (draft.workers.length > 1 && draft.splitMode === 'average') distributeEvenly(draft.workers, draft.qualified)
        }
        for (const worker of pool) allWorkers.set(Number(worker.id), worker)
      }
      processWorkerOptions.value = options
      proxyWorkers.value = [...allWorkers.values()]
      return
    }

    const processRow = orderProcessId != null
      ? segmentProcesses.value.find(item => Number(item.id) === Number(orderProcessId))
      : selectedSegmentProcess.value
    const departmentIds = assignedDepartmentIds(processRow)
    const processId = resolveWorkerProcessId(orderProcessId)
    const params: Record<string, string | number> = {}
    if (activeSegmentCode.value) params.segment_code = activeSegmentCode.value
    if (processId) params.process_id = processId
    if (departmentIds.length === 1) params.department_id = departmentIds[0]
    const data: any = await get('/shop-floor-settings/workers', params)
    const workers = workersInDepartments(Array.isArray(data) ? data : data?.items || [], departmentIds)
    const pool = groupReport.value
      ? (departmentIds.length ? workers : collectiveWorkerPool(workers))
      : [selfReportWorker(workers)]
    reportWorkerOptions.value = pool
    proxyWorkers.value = pool
    cutWorkers.value = groupReport.value
      ? listedReportWorkers(pool, cutWorkers.value, cutQualified.value)
      : [{ ...selfReportWorker(workers), pairs: '' }]
    applySingleWorkerDistribution()
  } catch (e: any) {
    proxyWorkers.value = []
    cutWorkers.value = []
    reportWorkerOptions.value = []
    cutWorkerLoadError.value = e?.message ? `人员加载失败：${e.message}` : '人员加载失败，请重试'
  }
}

function resolveWorkerProcessId(orderProcessId?: number | null): number | undefined {
  if (orderProcessId != null) {
    const row = segmentProcesses.value.find(item => Number(item.id) === Number(orderProcessId))
    if (row?.process_id) return Number(row.process_id)
  }
  const selected = selectedSegmentProcess.value
  return selected?.process_id ? Number(selected.process_id) : undefined
}

async function loadCutQuote() {
  cutPriceError.value = ''
  try {
    if (isMultiInlineReport.value) {
      initializeMultiProcessDrafts()
      const quotes = await Promise.all(segmentProcesses.value.map(async row => {
        const quote: any = await get('/reports/quote', {
          header_id: flowCard.value.header_id,
          order_process_id: row.id,
        })
        return [Number(row.id), Number(quote?.unit_price || 0)] as const
      }))
      for (const [processId, unitPrice] of quotes) {
        const draft = multiProcessDrafts.value[processId]
        if (draft) draft.unitPrice = unitPrice
      }
      return
    }
    if (!selectedSegmentProcess.value) return
    const quote: any = await get('/reports/quote', {
      header_id: flowCard.value.header_id,
      order_process_id: selectedSegmentProcess.value.id,
    })
    cutUnitPrice.value = Number(quote?.unit_price || 0)
  } catch (e: any) {
    cutUnitPrice.value = 0
    cutPriceError.value = e?.message || '计件工价加载失败'
  }
}

function openMaterialPicker() {
  if (!issueCandidates.value.length && !issueLoading.value) void loadIssueCandidates()
  materialPickerVisible.value = true
}

function selectIssueMaterial(row: any) {
  if (!selectedIssueRows.value.some(item => item.id === row.id)) selectedIssueRows.value.push(row)
  const pairs = remainingOrderQty.value || Number(flowCard.value?.total_qty || 0)
  issuePairDraft.value[row.id] = pairs > 0 ? String(pairs) : ''
  issueQtyDraft.value[row.id] = Number(row.suggested_qty || 0) > 0 ? String(row.suggested_qty) : ''
  materialPickerVisible.value = false
}

function removeIssueMaterial(id: number) {
  selectedIssueRows.value = selectedIssueRows.value.filter(row => row.id !== id)
  delete issueQtyDraft.value[id]
  delete issuePairDraft.value[id]
}

function onMaterialQtyInput(row: any, event: any) {
  const value = String(event?.detail?.value || '')
  issueQtyDraft.value[row.id] = value
  const perPair = effectivePerPair(row)
  issuePairDraft.value[row.id] = perPair > 0 && Number(value) > 0 ? String(Math.round(Number(value) / perPair)) : ''
}

async function submitIssue() {
  const lines = selectedIssueRows.value.map((row: any) => ({ requirement_id: row.id, qty: Number(issueQtyDraft.value[row.id] || 0), pairs: Number(issuePairDraft.value[row.id] || 0) || undefined })).filter((row: any) => row.qty > 0)
  if (!lines.length) return uni.showToast({ title: '请填写领料数量', icon: 'none' })
  const invalid = lines.find((line: any) => line.qty > Number(selectedIssueRows.value.find((row: any) => row.id === line.requirement_id)?.max_issue_qty || 0))
  if (invalid) return uni.showToast({ title: '领料数量超过当前可领数量', icon: 'none' })
  issueSubmitting.value = true
  try {
    await post('/stock-issues', { doc_type: 'issue', header_id: flowCard.value.header_id, lines })
    showIssueSuccess()
    const selectedIds = new Set(selectedIssueRows.value.map((row: any) => Number(row.id)))
    await Promise.all([loadIssueCandidates(), loadFlowHistories()])
    selectedIssueRows.value = issueCandidates.value.filter((row: any) => selectedIds.has(Number(row.id)))
    issueQtyDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, '']))
    issuePairDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, '']))
  } catch (e: any) { uni.showToast({ title: e?.message || '领料申请提交失败', icon: 'none' }) }
  finally { issueSubmitting.value = false }
}

function onMultiQualifiedInput(processId: number, event: any) {
  const draft = multiProcessDrafts.value[processId]
  if (!draft) return
  draft.qualified = String(event?.detail?.value || '')
  if (draft.workers.length === 1) draft.workers[0].pairs = draft.qualified
  else if (draft.splitMode === 'average') distributeEvenly(draft.workers, draft.qualified)
  if (canSubmitCutReport.value) reportSubmitError.value = ''
}

async function submitCutReport() {
  reportSubmitError.value = ''
  if (isMultiInlineReport.value) return submitMultiProcessReports()
  const qualified = Number(cutQualified.value || 0)
  const shares = groupReport.value
    ? cutWorkers.value
      .map(row => ({ worker_id: Number(row.id), pairs: Number(row.pairs || 0) }))
      .filter(row => row.pairs > 0)
    : [{ worker_id: currentEmployeeId.value, pairs: qualified }]
  const fail = (msg: string) => {
    reportSubmitError.value = msg
    uni.showToast({ title: msg, icon: 'none' })
  }
  if (qualified <= 0) return fail('请填写本次合格双数')
  if (flowCard.value?.is_recut && Math.round(qualified * 100) % 50 !== 0) return fail('补单报工最少半双')
  if (!shares.length || !shares[0].worker_id) return fail(groupReport.value ? '请填写报工人员的双数' : '当前员工不能报工')
  if (groupReport.value && cutCompletionMode.value === 'component') {
    if (shares.some(row => toPairCents(row.pairs) < toPairCents(qualified))) return fail('每位人员可配双数不能少于本次合格双数')
  } else if (groupReport.value && shares.reduce((sum, row) => sum + toPairCents(row.pairs), 0) !== toPairCents(qualified)) {
    return fail('人员双数合计须等于本次合格双数')
  }
  const process = selectedSegmentProcess.value
  if (!process?.process_name) return fail(`未找到${segmentLabel.value}工序`)
  submitting.value = true
  try {
    const result: any = await post('/reports', {
      worker_id: currentEmployeeId.value || shares[0].worker_id,
      header_id: flowCard.value.header_id,
      process_name: process.process_name,
      order_process_id: process.id,
      color_name: flowCard.value.color_name || null,
      qualified_qty: qualified,
      defect_qty: 0,
      source: flowCardReportSource(),
      confirm_over_plan: false,
      create_trace_bundle: false,
      proxy: true,
      beneficiary_worker_ids: shares.map(row => row.worker_id),
      shares,
      workshop_counts: workshopCountPayload(),
    })
    if (result?.need_confirm) throw new Error(result.message || '报工数量超过计划')
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    await loadFlowHistories()
    cutQualified.value = ''
    cutWorkers.value = cutWorkers.value.map(row => ({ ...row, pairs: '' }))
    clearWorkshopDrafts()
    reportSubmitError.value = ''
    reportSucceeded(`${segmentLabel.value} · ${qualified} 双`)
  } catch (e: any) {
    const msg = e?.message || `${segmentLabel.value}报工失败`
    reportSubmitError.value = msg
    uni.showToast({ title: msg, icon: 'none' })
  }
  finally { submitting.value = false }
}

async function submitMultiProcessReports() {
  const rows = segmentProcesses.value
    .map((process: any) => ({ process, draft: multiProcessDrafts.value[process.id] }))
    .filter(row => Number(row.draft?.qualified || 0) > 0)
  const invalidHint = reportSubmitHint.value
  if (invalidHint) {
    reportSubmitError.value = invalidHint
    return uni.showToast({ title: invalidHint, icon: 'none' })
  }
  submitting.value = true
  try {
    const items = rows.map(({ process, draft }) => {
      const qualified = Number(draft.qualified || 0)
      const shares = groupReport.value
        ? draft.workers
          .map(worker => ({ worker_id: Number(worker.id), pairs: Number(worker.pairs || 0) }))
          .filter(row => row.pairs > 0)
        : [{ worker_id: currentEmployeeId.value, pairs: qualified }]
      return {
        worker_id: currentEmployeeId.value || shares[0].worker_id,
        header_id: flowCard.value.header_id,
        process_name: process.process_name,
        order_process_id: process.id,
        color_name: flowCard.value.color_name || null,
        qualified_qty: qualified,
        defect_qty: 0,
        source: flowCardReportSource(),
        confirm_over_plan: false,
        create_trace_bundle: false,
        proxy: true,
        beneficiary_worker_ids: shares.map(row => row.worker_id),
        shares,
        workshop_counts: workshopCountPayload(),
      }
    })
    const result: any = await post('/reports/batch', { items })
    if (result?.need_confirm) throw new Error(result.message || '报工数量超过计划')
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    await loadFlowHistories()
    multiReportTotal.value = ''
    for (const { draft } of rows) {
      draft.qualified = ''
      draft.workers = draft.workers.map(worker => ({ ...worker, pairs: '' }))
    }
    clearWorkshopDrafts()
    reportSubmitError.value = ''
    reportSucceeded(`${segmentLabel.value} · 已提交 ${result?.count || items.length} 道工序`)
  } catch (e: any) {
    const msg = e?.message || `${segmentLabel.value}报工失败`
    reportSubmitError.value = msg
    uni.showToast({ title: msg, icon: 'none' })
  } finally { submitting.value = false }
}
</script>
