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
        <view class="native-field"><text>工序</text><input v-model.trim="processName" placeholder="请输入本次工序" /></view>
        <view class="native-field native-field--qty"><text>数量</text><view class="report-qty-stepper report-qty-stepper--inline"><button class="report-qty-stepper__btn" @click="stepQty('qty', -1)">−</button><input v-model="qty" type="number" placeholder="0" /><button class="report-qty-stepper__btn" @click="stepQty('qty', 1)">+</button><text>双</text></view></view>
        <picker :range="reportTypes" range-key="label" @change="pickReportType"><view class="native-field"><text>类型</text><text>{{ reportTypeLabel }}　›</text></view></picker>
      </view>
      <view v-if="canProxy && !unit.reported" class="card proxy-card-native">
        <view class="proxy-switch"><view><strong>组长代报</strong><text>数量均分给所选成员</text></view><switch :checked="proxy" color="#0076ff" @change="proxy = $event.detail.value" /></view>
        <checkbox-group v-if="proxy" @change="changeProxyWorkers"><label v-for="worker in proxyWorkers" :key="worker.id"><checkbox :value="String(worker.id)" :checked="beneficiaryIds.includes(worker.id)" color="#0076ff" />{{ worker.name }}</label></checkbox-group>
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
      <view v-if="!basketInfo.journey" class="card report-tip">该框当前空闲。请先扫描生产流转卡进入裁断报工，再点击“扫码装框”绑定此框。</view>
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
        <view class="native-field"><text>备注</text><input v-model.trim="subcontractReceiptNote" placeholder="可选" /></view>
      </view>
      <view v-if="subcontractReceipt.status !== 'received'" class="cut-sticky-bar">
        <button class="primary-button cut-sticky-button" :loading="submitting" @click="submitSubcontractReceipt">确认验收</button>
      </view>
    </template>

    <template v-else-if="kind === 'flow-card' && flowCard">
      <view v-if="flowAction && flowAction !== 'defect'" class="cut-order-strip">
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
          <view><text>计划</text><strong>{{ flowCard.total_qty || 0 }} 双</strong></view>
          <view><text>交期</text><strong>{{ flowCard.delivery_date || '—' }}</strong></view>
        </view>
      </view>

      <view v-if="flowAction === 'report'" class="card cut-progress-card">
        <view class="cut-progress-head">
          <strong>{{ segmentLabel }}进度</strong>
          <text>已报 {{ reportedSegmentQty }} / {{ segmentPlanQty }} 双</text>
        </view>
        <view class="cut-progress-track"><view class="cut-progress-fill" :style="{ width: `${segmentProgressPct}%` }" /></view>
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
        <view class="defect-product-context">
          <image v-if="defectProductImageUrl" class="defect-product-image" :src="defectProductImageUrl" mode="aspectFill" />
          <view v-else class="defect-product-image defect-product-image--empty">暂无图片</view>
          <view class="defect-product-fields">
            <picker v-if="defectBrandOptions.length > 1" :range="defectBrandOptions" @change="pickDefectBrand">
              <view class="native-field"><text>品牌</text><text>{{ standaloneDefectBrand || '请选择' }}　›</text></view>
            </picker>
            <view v-else class="native-field"><text>品牌</text><text>{{ standaloneDefectBrand || defectBrandOptions[0] || '未指定' }}</text></view>
            <picker v-if="defectResponsiblePartyType !== 'subcontractor' && defectProcessOptions.length" :range="defectProcessOptions" range-key="label" @change="pickDefectProcess">
              <view class="native-field"><text>发现工序</text><text>{{ selectedDefectProcess?.label || '请选择' }}　›</text></view>
            </picker>
            <view v-else-if="defectResponsiblePartyType === 'subcontractor'" class="native-field"><text>发现工序</text><text>{{ factoryDefectProcessLabel }}</text></view>
            <view v-else class="native-field"><text>发现工序</text><text>暂无可选工序</text></view>
          </view>
        </view>
        <view class="defect-sizes-section">
          <scroll-view scroll-x class="defect-size-matrix-scroll" :show-scrollbar="false">
            <view class="defect-size-matrix">
              <view class="defect-size-matrix-row defect-size-matrix-row--head">
                <text class="defect-size-matrix-axis">码数</text>
                <text v-for="(line, index) in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-size">{{ defectSizeLineLabel(line) || `码${index + 1}` }}</text>
              </view>
              <view class="defect-size-matrix-row">
                <text class="defect-size-matrix-axis">左脚</text>
                <view v-for="line in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-input"><input v-model="line.left_qty" type="number" placeholder="0" /></view>
              </view>
              <view class="defect-size-matrix-row">
                <text class="defect-size-matrix-axis">右脚</text>
                <view v-for="line in defectSizeLines" :key="line.key" class="defect-size-matrix-cell defect-size-matrix-input"><input v-model="line.right_qty" type="number" placeholder="0" /></view>
              </view>
            </view>
          </scroll-view>
          <text v-if="standaloneDefectTotalQty" class="defect-total defect-total--all">合计 {{ standaloneDefectTotalQty }}</text>
        </view>
        <view class="defect-loss-section">
          <view class="native-field"><text>损失金额</text><strong class="defect-loss-total">单只 ¥{{ defectUnitLossAmount }} · 共 ¥{{ defectLossAmount }}</strong></view>
          <text class="defect-loss-hint" :class="{ 'defect-loss-hint--error': !!defectLossQuoteError, 'defect-loss-hint--empty': !defectLossHintText }">{{ defectLossHintText || ' ' }}</text>
          <view class="native-field defect-responsibility-line">
            <text class="defect-responsibility-name">公司承担</text>
            <view class="defect-responsibility-controls">
              <view class="defect-inline-input"><text>¥</text><input v-model="defectCompanyLossAmount" type="digit" placeholder="0.00" /></view>
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
                  <view class="defect-inline-input"><text>¥</text><input v-model="row.share_amount" type="digit" placeholder="0.00" /></view>
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
          <text :class="['defect-loss-hint', { 'defect-loss-hint--error': !defectAllocationBalanced }]">当前合计 ¥{{ defectAllocationTotal }}{{ defectAllocationBalanced ? '' : `，差额 ¥${defectAllocationDifference}` }}</text>
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

      <view v-if="flowAction === 'issue' || flowAction === 'report'" class="cut-tab-pane cut-tab-pane--sticky">
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
          <template v-if="isMultiInlineReport">
            <view v-for="row in segmentProcesses" :key="row.id" class="card multi-process-report-card">
              <view class="multi-process-report-head">
                <view class="multi-process-report-copy">
                  <view class="multi-process-report-title"><strong>{{ row.label }}</strong><text v-if="row.status === 'completed'">已完成</text></view>
                  <text>已报 {{ row.completed_qty || 0 }} / {{ row.plan_qty || 0 }} 双</text>
                </view>
                <view class="multi-process-qualified">
                  <text>本次合格</text>
                  <view class="cut-qty-input cut-qty-input--qualified">
                    <input :value="multiProcessDrafts[row.id]?.qualified || ''" type="number" placeholder="0" @input="onMultiQualifiedInput(row.id, $event)" />
                    <text>双</text>
                  </view>
                </view>
              </view>
              <view class="cut-step-title cut-step-title--section">
                <strong>计件人员</strong>
                <button class="cut-inline-add" @click="openWorkerPicker(row.id)">＋ 添加</button>
              </view>
              <view v-for="worker in multiProcessDrafts[row.id]?.workers || []" :key="worker.id" class="cut-qty-row">
                <text class="cut-qty-label-text">{{ worker.name }}</text>
                <view class="cut-qty-input"><input v-model="worker.pairs" type="number" placeholder="0" /><text>双</text></view>
                <text class="cut-remove-hit" @click="removeMultiProcessWorker(row.id, worker.id)">删除</text>
              </view>
              <view v-if="!multiProcessDrafts[row.id]?.workers?.length" class="cut-history-empty">请选择实际{{ segmentLabel }}人员</view>
            </view>
          </template>

          <template v-else>
          <view v-if="segmentProcesses.length > 1" class="card process-choice-card">
            <text class="process-choice-label">报工工序</text>
            <view class="process-choice-list">
              <view
                v-for="row in segmentProcesses"
                :key="row.id"
                :class="['process-choice-field', { active: Number(row.id) === Number(selectedOrderProcessId), completed: row.status === 'completed' }]"
                @click="selectReportProcess(row)"
              >
                <view>
                  <strong>{{ row.label }}</strong>
                  <text>已报 {{ row.completed_qty || 0 }} / {{ row.plan_qty || 0 }} 双</text>
                </view>
                <text>{{ Number(row.id) === Number(selectedOrderProcessId) ? '当前' : row.status === 'completed' ? '已完成' : '报工' }}</text>
              </view>
            </view>
          </view>

          <template v-if="selectedSegmentProcess">
          <template v-if="activeSegmentCode === 'cut'">
            <view class="card cut-step-card">
              <view class="cut-step-title"><strong>{{ selectedSegmentProcess.label }}</strong><text>¥{{ money(cutUnitPrice) }}/双</text></view>
              <button class="cut-scan-cta" @click="scanCutBasket">
                <image class="cut-scan-cta__icon" src="/static/icons/qrcode.svg" mode="aspectFit" />
                <text class="cut-scan-cta__main">{{ scannedCutBaskets.length ? '继续扫码' : '扫码框码' }}</text>
                <text class="cut-scan-cta__sub">可扫多个永久框</text>
              </button>

              <template v-if="scannedCutBaskets.length">
                <view class="cut-step-title cut-step-title--section">
                  <strong>装框明细</strong>
                  <text class="cut-sum-pill">合计 {{ cutBasketTotalQty }} 双</text>
                </view>
                <view v-for="(basket, index) in scannedCutBaskets" :key="basket.basket_code" class="cut-qty-row">
                  <text class="cut-qty-label-text">{{ basket.basket_code }}</text>
                  <view class="cut-qty-input"><input v-model="basket.qty" type="number" placeholder="0" /><text>双</text></view>
                  <text class="cut-remove-hit" @click="removeScannedCutBasket(index)">删除</text>
                </view>

                <view class="cut-step-title cut-step-title--section">
                  <strong>计件人员</strong>
                  <button class="cut-inline-add" @click="openWorkerPicker()">＋ 添加</button>
                </view>
                <view v-if="!cutWorkers.length" class="cut-history-empty">请添加计件人员</view>
                <view v-for="worker in cutWorkers" :key="worker.id" class="cut-person-pay-row">
                  <view class="cut-person-pay-head"><strong>{{ worker.name }}</strong><text class="cut-remove-hit" @click="removeCutWorker(worker.id)">删除</text></view>
                  <view class="cut-person-pay-body">
                    <text>工价 ¥{{ money(cutUnitPrice) }}/双</text>
                    <view class="cut-qty-input cut-qty-input--compact">
                      <text v-if="cutWorkers.length === 1" class="cut-auto-pairs">{{ cutBasketTotalQty }}</text>
                      <input v-else v-model="worker.pairs" type="number" placeholder="0" />
                      <text>双</text>
                    </view>
                    <strong>¥{{ money(Number(worker.pairs || 0) * cutUnitPrice) }}</strong>
                  </view>
                </view>
              </template>
            </view>
          </template>

          <template v-else>
            <view class="card cut-step-card">
              <view class="cut-step-title"><strong>{{ selectedSegmentProcess.label }}</strong></view>
              <view class="report-qty-stepper">
                <text class="report-qty-stepper__label">本次合格</text>
                <view class="report-qty-stepper__controls">
                  <button class="report-qty-stepper__btn report-qty-stepper__btn--lg" @click="stepQty('cutQualified', -1)">−</button>
                  <input v-model="cutQualified" type="number" placeholder="0" />
                  <button class="report-qty-stepper__btn report-qty-stepper__btn--lg" @click="stepQty('cutQualified', 1)">+</button>
                  <text class="report-qty-stepper__unit">双</text>
                </view>
              </view>
              <view class="cut-step-title cut-step-title--section">
                <strong>计件人员</strong>
                <button class="cut-inline-add" @click="openWorkerPicker()">＋ 添加</button>
              </view>
              <view v-for="worker in cutWorkers" :key="worker.id" class="cut-qty-row">
                <text class="cut-qty-label-text">{{ worker.name }}</text>
                <view class="cut-qty-input"><input v-model="worker.pairs" type="number" placeholder="0" /><text>双</text></view>
                <text class="cut-remove-hit" @click="removeCutWorker(worker.id)">删除</text>
              </view>
              <view v-if="!cutWorkers.length" class="cut-history-empty">请选择实际{{ segmentLabel }}人员</view>
              <text class="cut-worker-hint">{{ cutWorkerHint }}</text>
            </view>
          </template>
          </template>
          </template>

          <view class="cut-sticky-bar">
            <text v-if="reportSubmitError || (!canSubmitCutReport && reportSubmitHint)" class="cut-sticky-error">{{ reportSubmitError || reportSubmitHint }}</text>
            <button class="primary-button cut-sticky-button report-submit-button" :loading="submitting" :disabled="!canSubmitCutReport" @click="submitCutReport">提交报工{{ reportSubmitQtyLabel }}</button>
          </view>
        </template>
      </view>
    </template>

    <view v-if="candidatePicker" class="native-sheet-mask" @click="candidatePicker = false"><view class="native-sheet" @click.stop><strong>选择任务</strong><view v-for="row in candidates" :key="row.header_id || row.order_id" class="sheet-option" @click="chooseCandidate(row)"><view><text>{{ row.order_no }}</text><text>{{ row.customer_name || '' }} · {{ row.completed_qty }}/{{ row.plan_qty }}</text></view><text>›</text></view></view></view>
    <view v-if="materialPickerVisible" class="native-sheet-mask" @click="materialPickerVisible = false"><view class="native-sheet" @click.stop><strong>添加物料</strong><view v-if="!availableIssueCandidates.length" class="cut-history-empty">没有其他可领物料</view><view v-for="row in availableIssueCandidates" :key="row.id" class="sheet-option" @click="selectIssueMaterial(row)"><view><text>{{ materialName(row) }}</text><text>可领 {{ formatQty(row.max_issue_qty) }} {{ row.pricing_unit_name || '' }}</text></view><text>＋</text></view></view></view>
    <view v-if="workerPickerVisible" class="native-sheet-mask" @click="workerPickerVisible = false">
      <view class="native-sheet native-worker-sheet" @click.stop>
        <view class="native-worker-sheet-head"><strong>添加计件人员</strong><text @click="workerPickerVisible = false">关闭</text></view>
        <scroll-view scroll-y class="native-worker-list" :show-scrollbar="false">
          <view v-if="cutWorkerLoadError" class="cut-history-empty">{{ cutWorkerLoadError }}</view>
          <view v-else-if="!availableCutWorkers.length" class="cut-history-empty">暂无可添加人员</view>
          <view v-for="worker in availableCutWorkers" :key="worker.id" class="sheet-option" @click="selectCutWorker(worker)"><view><text>{{ worker.name }}</text><text>{{ worker.role || '员工' }}</text></view><text>＋</text></view>
        </scroll-view>
      </view>
    </view>
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
import { decodeTarget, parseScanText, type ScanKind } from '../../services/scanner'

const kind = ref<ScanKind | ''>(''), code = ref(''), station = ref<any>(null), unit = ref<any>(null), carton = ref<any>(null), basketInfo = ref<any>(null), flowCard = ref<any>(null)
const subcontractReceipt = ref<any>(null), subcontractReceiptQty = ref(''), subcontractReceiptNote = ref('')
const loadQuery = ref<Record<string, string | undefined> | null>(null)
const candidates = ref<any[]>([]), selectedOrderNo = ref(''), candidatePicker = ref(false), orderNo = ref(''), colorName = ref(''), sizeValue = ref(''), qty = ref(''), processName = ref('')
const loadingPage = ref(true), submitting = ref(false), errorMessage = ref(''), successResult = ref<any>(null), reportType = ref('normal')
const proxy = ref(false), proxyEnabled = ref(true), proxyWorkers = ref<any[]>([]), beneficiaryIds = ref<number[]>([])
const flowAction = ref<'' | 'issue' | 'report' | 'claim' | 'defect' | 'subcontract' | 'report-history' | 'claim-history' | 'defect-history' | 'issue-history' | 'subcontract-history'>('')
const flowFeaturePermissions = ref<string[]>(getProfile()?.featurePermissions || [])
const activeSegmentCode = ref<'cut' | 'stitch' | 'forming'>('cut')
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
const defectCompanyLossAmount = ref('0.00')
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
const materialPickerVisible = ref(false), workerPickerVisible = ref(false)
const workerPickerProcessId = ref<number | null>(null)
const defectHistory = ref<any[]>([]), subcontractHistory = ref<any[]>([])
const reportSubmitError = ref('')
const cutWorkerLoadError = ref('')
const cutQualified = ref(''), cutWorkers = ref<any[]>([]), cutHistory = ref<any[]>([])
const multiProcessDrafts = ref<Record<number, { qualified: string; workers: any[] }>>({})
const cutOutput = ref<any>(null), cutCompletionMode = ref<'complete' | 'quantity_split' | 'component'>('complete')
const scannedCutBaskets = ref<any[]>([]), cutUnitPrice = ref(0), cutPriceError = ref('')
const cutCompletionModes = [{ value: 'complete', label: '一人完整完成' }, { value: 'quantity_split', label: '多人按数量分工' }, { value: 'component', label: '多人按不同部件分工' }]
const cutCompletionModeLabel = computed(() => cutCompletionModes.find(row => row.value === cutCompletionMode.value)?.label || '一人完整完成')
const cutWorkerHint = computed(() => cutCompletionMode.value === 'component'
  ? '按不同部件分工时，每位人员的可配双数都不能少于本次合格双数。'
  : '多人报工时，各人员双数合计必须等于本次合格双数。')
const reportTypes = [{ value: 'normal', label: '正常' }, { value: 'rework', label: '返修' }, { value: 'supplement', label: '补数' }, { value: 'tail', label: '尾数' }]
const reportTypeLabel = computed(() => reportTypes.find(x => x.value === reportType.value)?.label || '正常')
const selected = computed(() => candidates.value.find(x => x.order_no === selectedOrderNo.value) || null)
const canProxy = computed(() => (getProfile()?.role === 'leader' || getProfile()?.isLeader) && proxyEnabled.value)
const canCreateSubcontract = computed(() => ['admin', 'manager'].includes(getProfile()?.role || '') || getProfile()?.isLeader || hasFlowFeature('subcontract_out'))
const canWarehouse = computed(() => ['admin', 'manager', 'leader', 'warehouse'].includes(getProfile()?.role || ''))
const segmentLabel = computed(() => ({ cut: '裁断', stitch: '针车', forming: '成型' } as Record<string, string>)[activeSegmentCode.value] || '裁断')
const segmentProcesses = computed<any[]>(() => {
  const matcher = activeSegmentCode.value === 'stitch'
    ? /针车|车缝/
    : activeSegmentCode.value === 'forming'
      ? /成型|成形/
      : /裁断|截断|裁剪|下料/
  return (flowCard.value?.processes || []).filter((row: any) => matcher.test(String(row.segment_name || '')))
})
const selectedSegmentProcess = computed(() => segmentProcesses.value.find((row: any) => Number(row.id) === Number(selectedOrderProcessId.value)) || null)
const defectProcessOptions = computed<any[]>(() => flowCard.value?.processes || [])
const selectedDefectProcess = computed(() => defectProcessOptions.value.find((row: any) => Number(row.id) === Number(selectedOrderProcessId.value)) || null)
const selectedSubcontractPartner = computed(() => subcontractPartners.value.find((row: any) => Number(row.id) === Number(subcontractPartnerId.value)) || null)
const isMultiInlineReport = computed(() => activeSegmentCode.value !== 'cut' && segmentProcesses.value.length > 1)
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
const defectLossAmount = computed(() => defectSizeLines.value.reduce((sum, line) => sum + defectSizeLineLoss(line), 0).toFixed(2))
const defectUnitLossAmount = computed(() => standaloneDefectTotalQty.value > 0
  ? (Number(defectLossAmount.value) / standaloneDefectTotalQty.value).toFixed(2)
  : '0.00')
const defectFactoryLossAmount = computed(() => Math.max(0, Number(defectLossAmount.value || 0) - Number(defectCompanyLossAmount.value || 0)).toFixed(2))
const defectAllocationTotal = computed(() => (
  defectResponsiblePartyType.value === 'subcontractor'
    ? Number(defectCompanyLossAmount.value || 0) + Number(defectFactoryLossAmount.value)
    : Number(defectCompanyLossAmount.value || 0) + defectResponsibilities.value.reduce((sum, row) => sum + Number(row.share_amount || 0), 0)
).toFixed(2))
const defectAllocationDifference = computed(() => Math.abs(Number(defectLossAmount.value) - Number(defectAllocationTotal.value)).toFixed(2))
const defectAllocationBalanced = computed(() => Math.abs(Number(defectLossAmount.value) - Number(defectAllocationTotal.value)) < 0.005)
const reportedSegmentQty = computed(() => Number(segmentProcess()?.completed_qty || 0))
const segmentPlanQty = computed(() => Number(segmentProcess()?.plan_qty || flowCard.value?.total_qty || 0))
const remainingOrderQty = computed(() => Math.max(0, segmentPlanQty.value - reportedSegmentQty.value))
const claimProcesses = computed(() => segmentProcesses.value.filter((row: any) => row.status !== 'completed'))
const claimPlanQty = computed(() => {
  const plans = claimProcesses.value.map((row: any) => Number(row.plan_qty || 0))
  if (!plans.length) return Number(flowCard.value?.total_qty || 0)
  return Math.min(...plans)
})
const claimMyQty = computed(() => {
  const me = Number(getProfile()?.id || 0)
  for (const process of claimProcesses.value) {
    const mine = (process.assignments || []).find((row: any) => Number(row.worker_id) === me)
    if (mine && mine.quota_qty != null) return Number(mine.quota_qty)
  }
  return 0
})
const claimRemainingQty = computed(() => {
  const me = Number(getProfile()?.id || 0)
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
const availableCutWorkers = computed(() => {
  const selectedWorkers = workerPickerProcessId.value
    ? multiProcessDrafts.value[workerPickerProcessId.value]?.workers || []
    : cutWorkers.value
  return proxyWorkers.value.filter(row => !selectedWorkers.some((selectedRow: any) => selectedRow.id === row.id))
})
const cutReportedQty = computed(() => cutWorkers.value.reduce((sum, row) => sum + Number(row.pairs || 0), 0))
const cutBasketTotalQty = computed(() => scannedCutBaskets.value.reduce((sum, row) => sum + Number(row.qty || 0), 0))
const canSubmitIssue = computed(() => selectedIssueRows.value.length > 0 && selectedIssueRows.value.every(row => Number(issueQtyDraft.value[row.id] || 0) > 0 && Number(issueQtyDraft.value[row.id] || 0) <= Number(row.max_issue_qty || 0)) && !issueLoading.value)
const issueSubmitHint = computed(() => {
  if (issueLoading.value) return '物料加载中…'
  if (!selectedIssueRows.value.length) return '请先添加物料'
  if (selectedIssueRows.value.some(row => Number(issueQtyDraft.value[row.id] || 0) <= 0)) return '请填写物料数量'
  if (selectedIssueRows.value.some(row => Number(issueQtyDraft.value[row.id] || 0) > Number(row.max_issue_qty || 0))) return '领料数量超过可领上限'
  return ''
})
const canSubmitCutReport = computed(() => {
  if (isMultiInlineReport.value) {
    const drafts = segmentProcesses.value.map((row: any) => multiProcessDrafts.value[row.id]).filter(draft => Number(draft?.qualified || 0) > 0)
    return drafts.length > 0 && drafts.every(draft => draft.workers.length > 0
      && draft.workers.every(worker => Number(worker.pairs || 0) > 0)
      && draft.workers.reduce((sum, worker) => sum + Number(worker.pairs || 0), 0) === Number(draft.qualified || 0))
  }
  if (!selectedSegmentProcess.value) return false
  if (activeSegmentCode.value === 'cut') {
    return Boolean(
      scannedCutBaskets.value.length
      && scannedCutBaskets.value.every(row => Number(row.qty || 0) > 0)
      && cutWorkers.value.length
      && cutWorkers.value.every(row => Number(row.pairs || 0) > 0)
      && cutBasketTotalQty.value === cutReportedQty.value
      && !cutPriceError.value
    )
  }
  const qualified = Number(cutQualified.value || 0)
  if (qualified <= 0 || !cutWorkers.value.length) return false
  const workerOk = cutCompletionMode.value === 'component'
    ? cutWorkers.value.every(row => Number(row.pairs || 0) >= qualified)
    : cutWorkers.value.reduce((sum, row) => sum + Number(row.pairs || 0), 0) === qualified
  return workerOk
})
const reportSubmitHint = computed(() => {
  if (isMultiInlineReport.value) {
    const drafts = segmentProcesses.value.map((row: any) => multiProcessDrafts.value[row.id]).filter(draft => Number(draft?.qualified || 0) > 0)
    if (!drafts.length) return '请至少填写一道工序的本次合格数'
    if (drafts.some(draft => !draft.workers.length)) return '请为已填写的工序添加计件人员'
    if (drafts.some(draft => draft.workers.some(worker => Number(worker.pairs || 0) <= 0))) return '请填写每位计件人员的双数'
    if (drafts.some(draft => draft.workers.reduce((sum, worker) => sum + Number(worker.pairs || 0), 0) !== Number(draft.qualified || 0))) return '每道工序的人员双数合计须等于本次合格数'
    return ''
  }
  if (!selectedSegmentProcess.value) return '请先选择本次报工工序'
  if (activeSegmentCode.value === 'cut') {
    if (cutPriceError.value) return cutPriceError.value
    if (!scannedCutBaskets.value.length) return '请先扫描框码'
    if (scannedCutBaskets.value.some(row => Number(row.qty || 0) <= 0)) return '请填写每个框的数量'
    if (!cutWorkers.value.length) return '请添加计件人员'
    if (cutWorkers.value.some(row => Number(row.pairs || 0) <= 0)) return '请填写每个人的数量'
    if (cutBasketTotalQty.value !== cutReportedQty.value) return '装框数量与人员计件数量必须一致'
    return ''
  }
  if (Number(cutQualified.value || 0) <= 0) return '请填写本次合格双数'
  if (!cutWorkers.value.length) return '请添加计件人员'
  const qualified = Number(cutQualified.value || 0)
  const total = cutWorkers.value.reduce((sum, row) => sum + Number(row.pairs || 0), 0)
  if (cutCompletionMode.value === 'component') {
    if (cutWorkers.value.some(row => Number(row.pairs || 0) < qualified)) return '每位人员可配双数不能少于合格双数'
  } else if (total !== qualified) {
    return '人员双数合计须等于本次合格双数'
  }
  return ''
})
const reportSubmitQtyLabel = computed(() => {
  if (isMultiInlineReport.value) {
    const count = segmentProcesses.value.filter((row: any) => Number(multiProcessDrafts.value[row.id]?.qualified || 0) > 0).length
    return count > 0 ? ` · ${count} 道工序` : ''
  }
  const qty = activeSegmentCode.value === 'cut' ? cutBasketTotalQty.value : Number(cutQualified.value || 0)
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
watch([cutBasketTotalQty, () => cutWorkers.value.length], ([total, workerCount]) => {
  if (activeSegmentCode.value !== 'cut' || workerCount !== 1) return
  cutWorkers.value[0].pairs = Number(total || 0) > 0 ? String(total) : ''
})
watch([cutBasketTotalQty, cutReportedQty, cutPriceError, scannedCutBaskets, cutWorkers, cutQualified], () => {
  if (canSubmitCutReport.value) reportSubmitError.value = ''
})
watch(defectLossAmount, total => {
  if (defectResponsiblePartyType.value === 'subcontractor') {
    if (Number(defectCompanyLossAmount.value || 0) > Number(total || 0)) defectCompanyLossAmount.value = total
    return
  }
  if (!defectResponsibilities.value.length) defectCompanyLossAmount.value = total
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
function stepQty(field: 'qty' | 'cutQualified' | 'claimQty', delta: number) {
  const holder = field === 'qty' ? qty : field === 'claimQty' ? claimQty : cutQualified
  const max = field === 'claimQty' ? claimRemainingQty.value : Number.POSITIVE_INFINITY
  const next = Math.min(max, Math.max(0, Number(holder.value || 0) + delta))
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
    { kind: 'company', amount: Number(defectCompanyLossAmount.value || 0), worker_id: 0 },
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
    defectLossQuote.value = await get('/defect-events/loss-quote', {
      header_id: flowCard.value.header_id,
      order_process_id: orderProcessId,
    })
  } catch (e: any) {
    defectLossQuote.value = null
    defectLossQuoteError.value = e?.message || '无法计算损失金额'
  } finally {
    defectLossQuoteLoading.value = false
  }
}
async function loadDefectResponsibleWorkers() {
  defectWorkerLoadError.value = ''
  const processId = Number(selectedDefectProcess.value?.process_id || 0)
  try {
    const params: Record<string, string | number> = {}
    if (processId) params.process_id = processId
    const workers: any = await get('/shop-floor-settings/workers', params)
    const rows = Array.isArray(workers) ? workers : workers?.items || []
    const processRow = selectedDefectProcess.value
    const assignedIds = new Set((processRow?.assignments || []).map((row: any) => Number(row.worker_id)))
    defectResponsibleWorkers.value = assignedIds.size
      ? rows.filter((row: any) => assignedIds.has(Number(row.id)))
      : rows
  } catch (e: any) {
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
    defectCompanyLossAmount.value = '0.00'
    applyFactoryDefectDefaults()
  } else {
    standaloneDefectScrapSource.value = 'internal'
    standaloneDefectReplacementSource.value = 'internal'
    defectCompanyLossAmount.value = defectLossAmount.value
  }
}
function initializeDefectContext() {
  standaloneDefectBrand.value = defectBrandOptions.value[0] || ''
  if (!selectedDefectProcess.value) {
    const preferred = segmentProcesses.value.find((row: any) => row.status !== 'completed')
      || segmentProcesses.value[0]
      || defectProcessOptions.value.find((row: any) => row.status !== 'completed')
      || defectProcessOptions.value[0]
    selectedOrderProcessId.value = preferred ? Number(preferred.id) : null
  }
  standaloneDefectDisposition.value = 'scrap'
  standaloneDefectScrapSource.value = 'internal'
  standaloneDefectReplacementSource.value = 'internal'
  defectResponsiblePartyType.value = 'employee'
  defectSubcontractPartnerId.value = null
  defectSubcontractOrderId.value = null
  defectLossQuote.value = null
  defectLossQuoteError.value = ''
  defectCompanyLossAmount.value = '0.00'
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
  const me = proxyWorkers.value.find(row => Number(row.id) === Number(getProfile()?.id))
  const next: Record<number, { qualified: string; workers: any[] }> = {}
  for (const row of segmentProcesses.value) {
    next[row.id] = current[row.id] || { qualified: '', workers: me ? [{ ...me, pairs: '' }] : [] }
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
  const row = defectProcessOptions.value[Number(e.detail.value)]
  selectedOrderProcessId.value = row ? Number(row.id) : null
  defectResponsibilities.value = []
  await Promise.all([loadDefectResponsibleWorkers(), loadDefectLossQuote()])
}
async function selectReportProcess(row: any) {
  if (Number(row?.id) === Number(selectedOrderProcessId.value)) return
  selectedOrderProcessId.value = row ? Number(row.id) : null
  cutQualified.value = ''
  scannedCutBaskets.value = []
  cutWorkers.value = []
  reportSubmitError.value = ''
  if (flowAction.value === 'report') await Promise.all([loadCutWorkers(selectedOrderProcessId.value), loadCutQuote()])
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
  const amount = successResult.value?.amount
  uni.showModal({
    title: '报工成功',
    content: amount != null ? `${content}\n暂估 ¥${money(amount)}` : content,
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
    return
  }
  if (kind.value === 'flow-card') {
    const selectedIds = new Set(selectedIssueRows.value.map((row: any) => Number(row.id)))
    const qtyDraft = { ...issueQtyDraft.value }
    const pairDraft = { ...issuePairDraft.value }
    flowCard.value = await get(`/executions/headers/${code.value}/flow-card`)
    initializeSelectedProcess()
    if (flowAction.value === 'issue') {
      await Promise.all([loadIssueCandidates(), loadFlowHistories()])
      selectedIssueRows.value = issueCandidates.value.filter((row: any) => selectedIds.has(Number(row.id)))
      issueQtyDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, qtyDraft[row.id] ?? '']))
      issuePairDraft.value = Object.fromEntries(selectedIssueRows.value.map((row: any) => [row.id, pairDraft[row.id] ?? '']))
    } else if (flowAction.value === 'report') {
      await Promise.all([loadFlowHistories(), loadCutWorkers(selectedOrderProcessId.value), loadCutQuote()])
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
    if (target.kind === 'station') {
      station.value = await get(`/stations/by-code/${encodeURIComponent(target.code)}`)
      const data: any = await get(`/stations/by-code/${encodeURIComponent(target.code)}/report-candidates`)
      candidates.value = data?.items || []; selectedOrderNo.value = data?.default_order_no || candidates.value[0]?.order_no || ''; applyCandidate()
    } else if (target.kind === 'trace') {
      unit.value = await get(`/trace-units/by-code/${encodeURIComponent(target.code)}`)
      orderNo.value = unit.value.order_no || unit.value.header_no || ''; colorName.value = unit.value.color_name || ''; sizeValue.value = unit.value.size_value || ''; qty.value = String(unit.value.qty || '')
      const next = (unit.value.order_processes || []).find((x: any) => x.status !== 'completed') || unit.value.order_processes?.[0]; processName.value = unit.value.current_process_name || next?.process_name || ''
      if (getProfile()?.role === 'leader' || getProfile()?.isLeader) {
        try { const settings: any = await get('/shop-floor-settings'); proxyEnabled.value = settings?.stitch_leader_proxy_report !== false } catch { proxyEnabled.value = true }
        try { const mine: any = await get('/teams/mine'); const map = new Map<number, any>(); for (const team of mine?.items || []) for (const worker of team.members || []) map.set(worker.id, worker); proxyWorkers.value = [...map.values()] } catch { proxyWorkers.value = [] }
        if (!proxyWorkers.value.length) { try { const workers: any = await get('/shop-floor-settings/workers'); proxyWorkers.value = Array.isArray(workers) ? workers : workers?.items || [] } catch { proxyWorkers.value = [] } }
      }
    } else if (target.kind === 'carton') carton.value = await get(`/packing-cartons/by-code/${encodeURIComponent(target.code)}`)
    else if (target.kind === 'basket') basketInfo.value = await get(`/reusable-baskets/by-code/${encodeURIComponent(target.code)}`)
    else if (target.kind === 'subcontract') {
      subcontractReceipt.value = await get(`/subcontract-orders/${target.code}`)
      subcontractReceiptQty.value = String(subcontractReceipt.value?.outstanding_qty || '')
      uni.setNavigationBarTitle({ title: '外发验收登记' })
    }
    else if (target.kind === 'flow-card') {
      const me: any = await get('/auth/me')
      flowFeaturePermissions.value = Array.isArray(me?.feature_permissions) ? me.feature_permissions : []
      flowCard.value = await get(`/executions/headers/${target.code}/flow-card`)
      activeSegmentCode.value = await resolveWorkbenchSegment(query?.segment || target.segmentCode)
      initializeSelectedProcess()
      const requestedAction = String(query?.action || '')
      const allowedActions = ['issue', 'report', 'claim', 'defect', 'subcontract', 'report-history', 'claim-history', 'defect-history', 'issue-history', 'subcontract-history']
      flowAction.value = allowedActions.includes(requestedAction) ? requestedAction as any : ''
      uni.setNavigationBarTitle({ title: flowAction.value ? flowActionLabel.value : '选择现场功能' })
      if (flowAction.value === 'issue') {
        await Promise.all([loadIssueCandidates(), loadFlowHistories()])
        restoreLastIssueMaterials()
      } else if (flowAction.value === 'report') {
        if (!selectedSegmentProcess.value) {
          const defaultProcess = segmentProcesses.value.find((row: any) => row.status !== 'completed') || segmentProcesses.value[0]
          selectedOrderProcessId.value = defaultProcess ? Number(defaultProcess.id) : null
        }
        await Promise.all([loadFlowHistories(), loadCutWorkers(selectedOrderProcessId.value), loadCutQuote()])
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

function applyCandidate() { const row = selected.value; if (!row) return; orderNo.value = row.order_no; const sku = row.items?.length === 1 ? row.items[0] : null; colorName.value = sku?.color_name || row.last_color_name || ''; sizeValue.value = sku?.size_value || row.last_size_value || '' }
async function submitSubcontractReceipt() {
  const quantity = Number(subcontractReceiptQty.value || 0)
  const outstanding = Number(subcontractReceipt.value?.outstanding_qty || 0)
  if (!Number.isInteger(quantity) || quantity <= 0) return uni.showToast({ title: '请输入完工数量', icon: 'none' })
  if (quantity > outstanding) return uni.showToast({ title: `完工数量不能超过 ${outstanding} 双`, icon: 'none' })
  submitting.value = true
  try {
    subcontractReceipt.value = await post(`/subcontract-orders/${subcontractReceipt.value.id}/receipts`, {
      qty: quantity,
      note: subcontractReceiptNote.value || null,
    })
    subcontractReceiptQty.value = String(subcontractReceipt.value?.outstanding_qty || '')
    subcontractReceiptNote.value = ''
    uni.showToast({ title: '验收登记成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e?.message || '验收登记失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
function chooseCandidate(row: any) { selectedOrderNo.value = row.order_no; applyCandidate(); candidatePicker.value = false }
function pickReportType(e: any) { reportType.value = reportTypes[Number(e.detail.value)]?.value || 'normal' }
function changeProxyWorkers(e: any) { beneficiaryIds.value = (e.detail.value || []).map(Number) }
function validate() { if (!orderNo.value || !processName.value || Number(qty.value) <= 0) { uni.showToast({ title: '请填写单号、工序和数量', icon: 'none' }); return false } return true }
async function submit(payload: any) { submitting.value = true; successResult.value = null; try { const data: any = await post('/reports', payload); if (data?.need_confirm) throw new Error(data.message || '报工数量超过计划'); successResult.value = data; reportSucceeded(`${data?.process_name || processName.value || '本工序'} · ${data?.qualified_qty ?? qty.value} 双`) } catch (e: any) { uni.showToast({ title: e?.message || '报工失败', icon: 'none' }) } finally { submitting.value = false } }
function commonPayload() { return { worker_id: getProfile()?.id || 0, order_no: orderNo.value, process_name: processName.value, color_name: colorName.value || null, size_value: sizeValue.value || null, qualified_qty: Number(qty.value), source: 'qrcode', confirm_over_plan: true, report_type: reportType.value } }
function submitStation() { processName.value = station.value?.process_name || ''; if (!selected.value) orderNo.value = orderNo.value.trim(); if (!validate()) return; void submit({ ...commonPayload(), station_id: station.value.id }) }
function submitTrace() { if (!validate()) return; if (proxy.value && !beneficiaryIds.value.length) return uni.showToast({ title: '请选择代报成员', icon: 'none' }); void submit({ ...commonPayload(), header_id: unit.value.header_id || undefined, trace_unit_id: unit.value.id, create_trace_bundle: false, proxy: canProxy.value && proxy.value, beneficiary_worker_id: proxy.value ? beneficiaryIds.value[0] : undefined, beneficiary_worker_ids: proxy.value ? beneficiaryIds.value : undefined }) }
async function submitCarton() { submitting.value = true; try { const data: any = await post('/carton-reports', { carton_code: carton.value.code, confirm_over_plan: true }); successResult.value = data; carton.value.reported_work_log_id = data.work_log_id; reportSucceeded(`包装 · ${carton.value.total_qty || 0} 双`) } catch (e: any) { uni.showToast({ title: e?.message || '报工失败', icon: 'none' }) } finally { submitting.value = false } }
async function warehouseCarton() { submitting.value = true; try { const data: any = await post(`/packing-cartons/${carton.value.id}/warehouse`, {}); carton.value.warehoused_at = data.warehoused_at; uni.showToast({ title: '入库成功', icon: 'success' }) } catch (e: any) { uni.showToast({ title: e?.message || '入库失败', icon: 'none' }) } finally { submitting.value = false } }
async function shipCarton() { submitting.value = true; try { const data: any = await post(`/packing-cartons/${carton.value.id}/ship`, {}); carton.value.shipment_id = data.shipment_id; uni.showToast({ title: '出库成功', icon: 'success' }) } catch (e: any) { uni.showToast({ title: e?.message || '出库失败', icon: 'none' }) } finally { submitting.value = false } }
function goHome() { uni.reLaunch({ url: '/pages/home/index' }) }
function openBasketTask() {
  const headerId = Number(basketInfo.value?.journey?.header_id || 0)
  if (!headerId) return
  const target = encodeURIComponent(JSON.stringify({ kind: 'flow-card', code: String(headerId), h5Path: `/flow-card/${headerId}`, label: '生产流转卡', segmentCode: 'cut' }))
  uni.redirectTo({ url: `/pages/report/index?target=${target}&segment=cut` })
}
function pickCutCompletionMode(e: any) {
  cutCompletionMode.value = (cutCompletionModes[Number(e.detail.value)]?.value || 'complete') as any
}

async function resolveWorkbenchSegment(explicit?: string): Promise<'cut' | 'stitch' | 'forming'> {
  if (explicit === 'stitch' || explicit === 'cut' || explicit === 'forming') return explicit
  try {
    const mine: any = await get('/teams/mine')
    const names = (mine?.items || []).map((row: any) => String(row.segment_name || ''))
    if (names.some((name: string) => /成型|成形/.test(name))) return 'forming'
    if (names.some((name: string) => /针车|车缝/.test(name))) return 'stitch'
    if (names.some((name: string) => /裁断|截断|裁剪|下料/.test(name))) return 'cut'
  } catch { /* 管理员或非组长默认进入裁断工作台 */ }
  return 'cut'
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
      const logs: any = await get(`/executions/headers/${headerId}/segment-report-history`, { segment_code: activeSegmentCode.value })
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
      segment_code: activeSegmentCode.value,
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
  if (Number(defectCompanyLossAmount.value || 0) < 0 || defectResponsibilities.value.some(row => Number(row.share_amount || 0) < 0)) {
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
  if (Number(defectCompanyLossAmount.value || 0) > Number(defectLossAmount.value || 0)) {
    return uni.showToast({ title: '公司承担不能大于损失金额', icon: 'none' })
  }
  if (defectResponsiblePartyType.value === 'employee' && defectResponsibilities.value.some(row => !row.worker_id)) {
    return uni.showToast({ title: '请选择责任员工', icon: 'none' })
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
  const currentWorkerId = Number(getProfile()?.id || 0)
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

async function loadCutWorkers(orderProcessId?: number | null) {
  cutWorkerLoadError.value = ''
  const processId = resolveWorkerProcessId(orderProcessId)
  try {
    const params: Record<string, string | number> = { segment_code: activeSegmentCode.value }
    if (processId) params.process_id = processId
    const workers: any = await get('/shop-floor-settings/workers', params)
    proxyWorkers.value = Array.isArray(workers) ? workers : workers?.items || []
    const me = proxyWorkers.value.find(row => Number(row.id) === Number(getProfile()?.id))
    if (isMultiInlineReport.value) initializeMultiProcessDrafts()
    else if (me && !cutWorkers.value.length) cutWorkers.value = [{ ...me, pairs: '' }]
    if (!proxyWorkers.value.length) {
      const procLabel = processId
        ? (segmentProcesses.value.find(row => Number(row.process_id) === Number(processId))?.label || '该工序')
        : segmentLabel.value
      cutWorkerLoadError.value = `${procLabel}暂无在职人员，请在员工管理中配置工序`
    }
  } catch (e: any) {
    proxyWorkers.value = []
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
  if (activeSegmentCode.value !== 'cut') return
  if (!selectedSegmentProcess.value) return
  cutPriceError.value = ''
  try {
    const quote: any = await get('/cut-outputs/quote', {
      header_id: flowCard.value.header_id,
      order_process_id: selectedSegmentProcess.value.id,
    })
    cutUnitPrice.value = Number(quote?.unit_price || 0)
  } catch (e: any) {
    cutUnitPrice.value = 0
    cutPriceError.value = e?.message || '计件工价加载失败'
  }
}

async function openWorkerPicker(orderProcessId?: number) {
  workerPickerProcessId.value = orderProcessId ?? null
  workerPickerVisible.value = true
  await loadCutWorkers(orderProcessId ?? null)
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

function selectCutWorker(worker: any) {
  const processId = workerPickerProcessId.value
  if (processId) {
    const draft = multiProcessDrafts.value[processId]
    if (draft && !draft.workers.some(row => row.id === worker.id)) draft.workers.push({ ...worker, pairs: '' })
  } else if (!cutWorkers.value.some(row => row.id === worker.id)) cutWorkers.value.push({ ...worker, pairs: '' })
  workerPickerVisible.value = false
  workerPickerProcessId.value = null
}

function removeCutWorker(id: number) { cutWorkers.value = cutWorkers.value.filter(row => row.id !== id) }
function removeMultiProcessWorker(processId: number, workerId: number) {
  const draft = multiProcessDrafts.value[processId]
  if (draft) draft.workers = draft.workers.filter(row => Number(row.id) !== Number(workerId))
}
function onMultiQualifiedInput(processId: number, event: any) {
  const draft = multiProcessDrafts.value[processId]
  if (!draft) return
  draft.qualified = String(event?.detail?.value || '')
  if (draft.workers.length === 1) draft.workers[0].pairs = draft.qualified
  if (canSubmitCutReport.value) reportSubmitError.value = ''
}

function scanCutBasket() {
  uni.scanCode({
    scanType: ['qrCode', 'barCode'],
    success: async result => {
      const target = parseScanText(result.result)
      const basketCode = target?.kind === 'basket'
        ? target.code
        : String(result.result || '').trim().toUpperCase()
      if (!basketCode || basketCode.includes('/')) return uni.showToast({ title: '请扫描永久框码', icon: 'none' })
      if (scannedCutBaskets.value.some(row => row.basket_code === basketCode)) return uni.showToast({ title: '该框码已扫描', icon: 'none' })
      scannedCutBaskets.value.push({ basket_code: basketCode, qty: '' })
      if (!cutWorkers.value.length) {
        const me = proxyWorkers.value.find(row => Number(row.id) === Number(getProfile()?.id))
        if (me) cutWorkers.value = [{ ...me, pairs: '' }]
      }
      uni.showToast({ title: `${basketCode}扫码成功`, icon: 'success' })
    },
  })
}

function removeScannedCutBasket(index: number) {
  scannedCutBaskets.value.splice(index, 1)
}

async function cancelOwnCutDrafts(headerId: number) {
  const data: any = await get(`/execution-headers/${headerId}/cut-outputs`)
  const items = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []
  const me = Number(getProfile()?.id || 0)
  const drafts = items.filter((row: any) => row.status === 'draft' && (!me || Number(row.reported_by || 0) === me))
  for (const draft of drafts) {
    try {
      await post(`/cut-outputs/${draft.id}/cancel`, {})
    } catch {
      // 草稿可能已被并发清理；继续按本次扫码重新装框
    }
  }
  cutOutput.value = null
  return drafts.length
}

async function submitCutReport() {
  reportSubmitError.value = ''
  if (isMultiInlineReport.value) return submitMultiProcessReports()
  if (activeSegmentCode.value === 'cut') {
    const shares = cutWorkers.value.map(row => ({ worker_id: Number(row.id), pairs: Number(row.pairs || 0) }))
    const qualified = cutBasketTotalQty.value
    const fail = (msg: string) => {
      reportSubmitError.value = msg
      uni.showToast({ title: msg, icon: 'none' })
    }
    if (!scannedCutBaskets.value.length) return fail('请先扫描框码')
    if (scannedCutBaskets.value.some(row => Number(row.qty || 0) <= 0)) return fail('请填写每个框的数量')
    if (!shares.length) return fail('请添加计件人员')
    if (shares.some(row => row.pairs <= 0)) return fail('请填写每个人的数量')
    if (qualified !== shares.reduce((sum, row) => sum + row.pairs, 0)) return fail('装框数量与人员计件数量必须一致')
    if (cutPriceError.value) return fail(cutPriceError.value)
    submitting.value = true
    try {
      const completionMode = shares.length > 1 ? 'quantity_split' : 'complete'
      const cleared = await cancelOwnCutDrafts(flowCard.value.header_id)
      if (cleared > 0) uni.showToast({ title: '已清理未完成草稿', icon: 'none', duration: 1200 })
      for (const basket of scannedCutBaskets.value) {
        cutOutput.value = await post('/cut-outputs/bind-basket', {
          header_id: flowCard.value.header_id,
          basket_code: basket.basket_code,
          qualified_pairs: qualified,
          qty: Number(basket.qty),
          defect_pairs: 0,
          completion_mode: completionMode,
        })
      }
      const result: any = await post(`/cut-outputs/${cutOutput.value.id}/confirm`, {
        qualified_pairs: qualified,
        defect_pairs: 0,
        completion_mode: completionMode,
        contributions: shares.map(row => ({
          worker_id: row.worker_id,
          credited_pairs: row.pairs,
          process_id: selectedSegmentProcess.value?.process_id,
        })),
      })
      flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
      await loadFlowHistories()
      scannedCutBaskets.value = []
      cutOutput.value = null
      cutWorkers.value = cutWorkers.value.map(row => ({ ...row, pairs: '' }))
      reportSubmitError.value = ''
      reportSucceeded(`${result?.output_no || '裁断'} · ${qualified} 双`)
    } catch (e: any) {
      const msg = e?.message || '截断报工失败'
      reportSubmitError.value = msg
      uni.showToast({ title: msg, icon: 'none' })
    }
    finally { submitting.value = false }
    return
  }
  const qualified = Number(cutQualified.value || 0)
  const shares = cutWorkers.value.map(row => ({ worker_id: Number(row.id), pairs: Number(row.pairs || 0) }))
  const fail = (msg: string) => {
    reportSubmitError.value = msg
    uni.showToast({ title: msg, icon: 'none' })
  }
  if (qualified <= 0) return fail('请填写本次合格双数')
  if (!shares.length) return fail('请添加计件人员')
  if (cutCompletionMode.value === 'component') {
    if (shares.some(row => row.pairs < qualified)) return fail('每位人员可配双数不能少于本次合格双数')
  } else if (shares.reduce((sum, row) => sum + row.pairs, 0) !== qualified) {
    return fail('人员双数合计须等于本次合格双数')
  }
  const process = selectedSegmentProcess.value
  if (!process?.process_name) return fail(`未找到${segmentLabel.value}工序`)
  submitting.value = true
  try {
    const result: any = await post('/reports', {
      worker_id: getProfile()?.id || shares[0].worker_id,
      header_id: flowCard.value.header_id,
      process_name: process.process_name,
      order_process_id: process.id,
      color_name: flowCard.value.color_name || null,
      qualified_qty: qualified,
      defect_qty: 0,
      source: ({ cut: 'flow_card_cutting', stitch: 'flow_card_stitching', forming: 'flow_card_forming' } as Record<string, string>)[activeSegmentCode.value],
      confirm_over_plan: false,
      create_trace_bundle: false,
      proxy: true,
      beneficiary_worker_ids: shares.map(row => row.worker_id),
      shares,
    })
    if (result?.need_confirm) throw new Error(result.message || '报工数量超过计划')
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    await loadFlowHistories()
    cutQualified.value = ''
    cutWorkers.value = cutWorkers.value.map(row => ({ ...row, pairs: '' }))
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
  let submitted = 0
  try {
    for (const { process, draft } of rows) {
      const qualified = Number(draft.qualified || 0)
      const shares = draft.workers.map(worker => ({ worker_id: Number(worker.id), pairs: Number(worker.pairs || 0) }))
      const result: any = await post('/reports', {
        worker_id: getProfile()?.id || shares[0].worker_id,
        header_id: flowCard.value.header_id,
        process_name: process.process_name,
        order_process_id: process.id,
        color_name: flowCard.value.color_name || null,
        qualified_qty: qualified,
        defect_qty: 0,
        source: ({ stitch: 'flow_card_stitching', forming: 'flow_card_forming' } as Record<string, string>)[activeSegmentCode.value],
        confirm_over_plan: false,
        create_trace_bundle: false,
        proxy: true,
        beneficiary_worker_ids: shares.map(row => row.worker_id),
        shares,
      })
      if (result?.need_confirm) throw new Error(result.message || `${process.label}报工数量超过计划`)
      draft.qualified = ''
      draft.workers = draft.workers.map(worker => ({ ...worker, pairs: '' }))
      submitted += 1
    }
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    await loadFlowHistories()
    reportSubmitError.value = ''
    reportSucceeded(`${segmentLabel.value} · 已提交 ${submitted} 道工序`)
  } catch (e: any) {
    if (submitted > 0) {
      flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
      await loadFlowHistories()
    }
    const msg = `${submitted > 0 ? `已提交 ${submitted} 道；` : ''}${e?.message || `${segmentLabel.value}报工失败`}`
    reportSubmitError.value = msg
    uni.showToast({ title: msg, icon: 'none' })
  } finally { submitting.value = false }
}
</script>
