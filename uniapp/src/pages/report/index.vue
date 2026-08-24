<template>
  <view class="page native-report-page">
    <view v-if="loadingPage" class="empty-state">正在加载扫码信息…</view>
    <view v-else-if="errorMessage" class="card report-error">{{ errorMessage }}</view>

    <template v-else-if="kind === 'station' && station">
      <view class="report-heading"><text>扫码报工</text><text>{{ station.name }}</text></view>
      <view class="card report-info"><strong>{{ station.name }}</strong><text>编码 {{ station.code }} · 工序 {{ station.process_name }}</text><text v-if="station.location">{{ station.location }}</text></view>
      <view v-if="candidates.length" class="card report-info" @click="candidatePicker = true"><text class="field-label">当前任务</text><strong>{{ selected?.order_no || '请选择' }}</strong><text>{{ selected?.customer_name || '' }} · {{ selected?.completed_qty || 0 }}/{{ selected?.plan_qty || 0 }}　›</text></view>
      <view class="form-card-native">
        <view v-if="!selected" class="native-field"><text>单号</text><input v-model.trim="orderNo" placeholder="请输入生产单号" /></view>
        <view class="native-field"><text>颜色</text><input v-model.trim="colorName" placeholder="可选" /></view>
        <view class="native-field"><text>尺码</text><input v-model.trim="sizeValue" placeholder="可选" /></view>
        <view class="native-field"><text>数量</text><input v-model="qty" type="number" placeholder="双" /></view>
        <picker :range="reportTypes" range-key="label" @change="pickReportType"><view class="native-field"><text>类型</text><text>{{ reportTypeLabel }}　›</text></view></picker>
      </view>
      <button class="primary-button" :loading="submitting" @click="submitStation">提交报工</button>
    </template>

    <template v-else-if="kind === 'trace' && unit">
      <view class="report-heading"><text>框码 / 捆码报工</text><text>{{ unit.code }}</text></view>
      <view class="card report-info"><strong>{{ unit.code }}</strong><text>{{ unit.unit_type === 'basket' ? '筐卡' : '扎捆' }} · {{ unit.qty }} 双 · {{ unit.status }}</text><text>订单 {{ unit.order_no || unit.header_no }}</text><text>{{ unit.customer_name || '—' }} · {{ unit.product_code || '—' }}</text><text>色码 {{ [unit.color_name, unit.size_value].filter(Boolean).join(' / ') || '—' }}</text></view>
      <view v-if="unit.reported" class="card report-warning"><strong>该框码已完成报工</strong><text>{{ unit.reported_process_name || '工序' }} · {{ unit.reported_worker_name || '员工' }} · {{ unit.reported_qty || 0 }} 双</text><text>{{ formatTime(unit.reported_at) }}</text><text>一个框码只能报工一次，不可重复提交。</text></view>
      <view v-else class="form-card-native">
        <view class="native-field"><text>工序</text><input v-model.trim="processName" placeholder="请输入本次工序" /></view>
        <view class="native-field"><text>数量</text><input v-model="qty" type="number" placeholder="双" /></view>
        <picker :range="reportTypes" range-key="label" @change="pickReportType"><view class="native-field"><text>类型</text><text>{{ reportTypeLabel }}　›</text></view></picker>
      </view>
      <view v-if="canProxy && !unit.reported" class="card proxy-card-native">
        <view class="proxy-switch"><view><strong>组长代报</strong><text>数量均分给所选成员</text></view><switch :checked="proxy" color="#0076ff" @change="proxy = $event.detail.value" /></view>
        <checkbox-group v-if="proxy" @change="changeProxyWorkers"><label v-for="worker in proxyWorkers" :key="worker.id"><checkbox :value="String(worker.id)" :checked="beneficiaryIds.includes(worker.id)" color="#0076ff" />{{ worker.name }}</label></checkbox-group>
      </view>
      <button v-if="!unit.reported" class="primary-button" :loading="submitting" @click="submitTrace">报本工序</button>
      <view v-if="unit.logs?.length" class="card report-history"><strong>过站历程</strong><view v-for="row in unit.logs" :key="row.id"><text>{{ row.process_name || row.action }} · {{ row.qty || '' }}</text><text>{{ formatTime(row.created_at) }}</text></view></view>
    </template>

    <template v-else-if="kind === 'carton' && carton">
      <view class="report-heading"><text>箱唛作业</text><text>{{ carton.code }}</text></view>
      <view class="card report-info"><strong>{{ carton.code }}</strong><text>共 {{ carton.total_qty }} 双</text><text>{{ carton.header_no || carton.order_no }}</text><text>{{ carton.product_code || '—' }}{{ carton.customer_name ? ` · ${carton.customer_name}` : '' }}</text></view>
      <view v-if="carton.reported_work_log_id" class="card report-warning">该箱已经报工，请勿重复扫描</view>
      <template v-else><view class="card report-tip">装完一箱扫一下箱唛，系统自动按箱内双数记包装计件。</view><button class="primary-button" :loading="submitting" @click="submitCarton">确认报工 {{ carton.total_qty }} 双</button></template>
      <template v-if="canWarehouse">
        <button v-if="carton.reported_work_log_id && !carton.warehoused_at" class="primary-button" :loading="submitting" @click="warehouseCarton">确认本箱入库</button>
        <button v-if="carton.warehoused_at && !carton.shipment_id" class="primary-button danger-button" :loading="submitting" @click="shipCarton">验箱并确认出库</button>
        <view v-if="carton.shipment_id" class="card report-warning">该箱已出库，请勿重复扫描</view>
      </template>
    </template>

    <template v-else-if="kind === 'flow-card' && flowCard">
      <view class="cut-page-head"><text class="cut-back" @click="goBack">‹</text><strong>现场任务单</strong><text>裁断</text></view>
      <view class="card cut-order-card">
        <view class="cut-order-top"><strong>生产流转卡</strong><text class="cut-role-pill">{{ cuttingRoleLabel }}</text><text class="cut-batch-label">{{ displayBatchLabel }}</text></view>
        <text class="cut-order-no">{{ flowCard.header_no }}</text>
        <view class="cut-order-meta"><text>{{ flowCard.product_code || '—' }}　|　{{ flowCard.color_name || '—' }}　|　{{ flowCard.total_qty || 0 }}双</text><text>交期：{{ flowCard.delivery_date || '—' }}</text></view>
      </view>

      <view class="card cut-stage-strip">
        <view :class="['cut-stage', { active: cuttingStage === 1, done: cuttingStage > 1 }]"><text class="cut-stage-index">1</text><view><strong>{{ cuttingStage > 1 ? '已领料' : '未领料' }}</strong><text>{{ cuttingStage > 1 ? '裁断料已确认' : '输入双数算料' }}</text></view></view>
        <text class="cut-stage-arrow">›</text>
        <view :class="['cut-stage', { active: cuttingStage === 2, done: cuttingStage > 2 }]"><text class="cut-stage-index">2</text><view><strong>{{ cuttingStage === 1 ? '待开裁' : '开裁中' }}</strong><text>{{ cuttingStage === 2 ? '当前步骤' : cuttingStage > 2 ? '已完成' : '领料后进行' }}</text></view></view>
        <text class="cut-stage-arrow">›</text>
        <view :class="['cut-stage', { active: cuttingStage === 3 }]"><text class="cut-stage-index">3</text><view><strong>报工</strong><text>{{ cuttingStage === 3 ? '填写本批双数' : '待完成' }}</text></view></view>
      </view>

      <view v-if="flowCard.status === 'confirmed'" class="card cut-task-panel">
        <view class="cut-task-title"><strong>待领料</strong><text>当前步骤</text></view>
        <view class="cut-task-body">
          <view class="cut-batch-row"><text>当前批次：<strong>{{ displayBatchLabel }}</strong></text><text>整单剩余 {{ remainingOrderQty }} 双</text></view>
          <text class="cut-qty-label">本批计划开裁数量</text>
          <view class="cut-stepper"><button @click="adjustIssuePairs(-1)">−</button><view><input :value="issuePairs" type="number" @input="onIssuePairsInput" /><text>双</text></view><button @click="adjustIssuePairs(1)">＋</button></view>
          <text class="cut-stepper-hint">输入双数后，系统自动按裁断工序段计算用料</text>
          <view v-if="issuePairsError" class="cut-inline-warning">{{ issuePairsError }}</view>
          <view class="cut-material-head"><strong>本批领料汇总</strong><text>{{ issueLoading ? '计算中…' : `按 ${Number(issuePairs || 0)} 双计算` }}</text></view>
          <view v-for="row in issueRows" :key="row.id" class="cut-material-row">
            <image v-if="row.image_url" class="cut-material-image" :src="row.image_url" mode="aspectFill" />
            <view class="cut-material-copy"><strong>{{ row.supplier_product_name || row.supplier_product_code || '未命名物料' }}</strong><text>{{ row.size_value ? `尺码 ${row.size_value}` : '通用尺码' }}　·　{{ row.pricing_unit_name || '未设置单位' }}</text></view>
            <view class="cut-material-qty"><strong>{{ issueDraft[row.id] || row.suggested_qty || 0 }}</strong><text>{{ row.pricing_unit_name || '' }}</text></view>
          </view>
          <view v-if="issueLoaded && !issueLoading && Number(issuePairs) > 0 && !issueRows.length" class="cut-inline-note">当前裁断工序段没有需领物料，可直接开始开裁。</view>
        </view>
      </view>
      <view v-if="issueNotice" class="card report-warning">{{ issueNotice }}</view>
      <view v-if="flowCard.status === 'confirmed'" class="cut-action-row"><button class="cut-secondary-button" @click="goHome">暂存</button><button v-if="hasIssuedMaterials" class="cut-primary-button" :loading="submitting" @click="startCutting">开始开裁</button><button v-else class="cut-primary-button" :loading="issueSubmitting" :disabled="!canSubmitIssue" @click="submitIssue">确认领料</button></view>

      <view v-else-if="['cut', 'in_progress'].includes(flowCard.status) && !cutReportVisible" class="card cut-task-panel">
        <view class="cut-task-title"><strong>开裁中</strong><text>当前步骤</text></view>
        <view class="cut-task-body"><view class="cut-batch-row"><text>当前批次：<strong>{{ displayBatchLabel }}</strong></text><text>剩余可报 {{ remainingOrderQty }} 双</text></view><button class="cut-primary-button cut-full-button" @click="openCutReport">填写本批报工双数</button></view>
      </view>
      <view v-if="cutReportVisible" class="cut-report-native">
        <view class="cut-report-title"><strong>本批裁断报工</strong><text>手工填写本批实际双数</text></view>
        <view class="card report-tip cut-batch-tip">本次提交会新建一个裁断批次；请只填写本批实际完成数量，不要填写整单计划数。</view>
        <view v-for="row in cutRows" :key="row.id || row.size_value" class="card cut-size-card">
          <view class="cut-size-head"><strong>{{ row.size_value || '未分码' }} 码</strong><text>计划 {{ row.qty || 0 }} · 已报 {{ row.cut_reported_qty || 0 }} · 剩余 {{ remainingCutQty(row) }}</text></view>
          <view class="native-field"><text>本批合格</text><input v-model="row.qualified_qty" type="number" placeholder="手工输入双数" /></view>
          <view class="native-field"><text>本批不良</text><input v-model="row.defect_qty" type="number" placeholder="手工输入双数" /></view>
        </view>
        <view class="form-card-native"><view class="native-field"><text>每框双数</text><input v-model="basketPairs" type="number" placeholder="40" /></view></view>
        <button class="primary-button" :loading="submitting" @click="submitCutReport">确认裁断报工</button>
        <button class="text-button" :disabled="submitting" @click="cutReportVisible = false">取消</button>
      </view>
      <view v-if="flowCard.baskets?.length" class="card report-history"><strong>已生成框码 · {{ flowCard.baskets.length }} 框</strong><view v-for="row in flowCard.baskets" :key="row.id"><text>{{ row.code }}</text><text>{{ row.qty || 0 }} 双</text></view></view>
    </template>

    <view v-if="successResult" class="card report-success-native"><strong>报工成功</strong><text>暂估 ¥{{ money(successResult.amount) }}</text><text>{{ successResult.process_name || '' }} · {{ successResult.qualified_qty || carton?.total_qty || qty }} 双</text></view>

    <view v-if="candidatePicker" class="native-sheet-mask" @click="candidatePicker = false"><view class="native-sheet" @click.stop><strong>选择任务</strong><view v-for="row in candidates" :key="row.header_id || row.order_id" class="sheet-option" @click="chooseCandidate(row)"><view><text>{{ row.order_no }}</text><text>{{ row.customer_name || '' }} · {{ row.completed_qty }}/{{ row.plan_qty }}</text></view><text>›</text></view></view></view>
    <view v-if="issueVisible" class="native-sheet-mask" @click="issueVisible = false"><view class="native-sheet issue-sheet-native" @click.stop>
      <strong>本次领料申请</strong>
      <text class="issue-sheet-hint">输入本次计划生产双数，系统按 BOM 单耗、尺码系数和损耗率自动计算建议领料量。</text>
      <view class="issue-pairs-row"><view><text>本次生产双数</text><input :value="issuePairs" type="number" placeholder="请输入双数" @input="onIssuePairsInput" /></view><text>{{ issueLoading ? '正在计算…' : '输入后自动算料' }}</text></view>
      <view v-for="row in issueRows" :key="row.id" class="issue-material-row">
        <image v-if="row.image_url" class="issue-material-image" :src="row.image_url" mode="aspectFill" />
        <view v-else class="issue-material-image issue-material-image--empty">暂无图片</view>
        <view class="issue-material-copy">
          <strong>{{ row.supplier_product_name || row.supplier_product_code || '未命名物料' }}</strong>
          <text>{{ row.size_value ? `尺码 ${row.size_value}` : '通用尺码' }} · 单位 {{ row.pricing_unit_name || '未设置' }}</text>
          <text>已领 {{ row.issued_qty || 0 }} {{ row.pricing_unit_name || '' }} · 剩余 {{ row.remain_need_qty || 0 }} · 可领 {{ row.max_issue_qty || 0 }}</text>
        </view>
        <view class="issue-material-input"><input v-model="issueDraft[row.id]" type="digit" :placeholder="`建议 ${row.suggested_qty || 0}`" /><text>{{ row.pricing_unit_name || '' }}</text></view>
      </view>
      <view v-if="!issueLoading && !issueRows.length" class="empty-state issue-empty">没有可领物料，可能尚未生成用料需求或已经领完。</view>
      <button class="primary-button" :loading="issueSubmitting" @click="submitIssue">提交领料申请</button>
      <button class="text-button" :disabled="issueSubmitting" @click="issueVisible = false">取消</button>
    </view></view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'
import { getProfile } from '../../services/storage'
import { decodeTarget, type ScanKind } from '../../services/scanner'

const kind = ref<ScanKind | ''>(''), code = ref(''), station = ref<any>(null), unit = ref<any>(null), carton = ref<any>(null), flowCard = ref<any>(null)
const candidates = ref<any[]>([]), selectedOrderNo = ref(''), candidatePicker = ref(false), orderNo = ref(''), colorName = ref(''), sizeValue = ref(''), qty = ref(''), processName = ref('')
const loadingPage = ref(true), submitting = ref(false), errorMessage = ref(''), successResult = ref<any>(null), reportType = ref('normal')
const proxy = ref(false), proxyEnabled = ref(true), proxyWorkers = ref<any[]>([]), beneficiaryIds = ref<number[]>([])
const cutReportVisible = ref(false), cutRows = ref<any[]>([]), basketPairs = ref('40')
const issueVisible = ref(false), issueLoading = ref(false), issueSubmitting = ref(false), issueRows = ref<any[]>([]), issueDraft = ref<Record<number, string>>({}), issueNotice = ref(''), issuePairs = ref('')
const issueLoaded = ref(false)
let issueCalcTimer: any = null
let issueCalcSeq = 0
const reportTypes = [{ value: 'normal', label: '正常' }, { value: 'rework', label: '返修' }, { value: 'supplement', label: '补数' }, { value: 'tail', label: '尾数' }]
const reportTypeLabel = computed(() => reportTypes.find(x => x.value === reportType.value)?.label || '正常')
const selected = computed(() => candidates.value.find(x => x.order_no === selectedOrderNo.value) || null)
const canProxy = computed(() => (getProfile()?.role === 'leader' || getProfile()?.isLeader) && proxyEnabled.value)
const canWarehouse = computed(() => ['admin', 'manager', 'leader', 'warehouse'].includes(getProfile()?.role || ''))
const cuttingRoleLabel = computed(() => getProfile()?.name ? `${getProfile()?.name}` : '裁断负责人')
const reportedCutQty = computed(() => (flowCard.value?.items || []).reduce((sum: number, row: any) => sum + Number(row.cut_reported_qty || 0), 0))
const remainingOrderQty = computed(() => Math.max(0, Number(flowCard.value?.total_qty || 0) - reportedCutQty.value))
const displayBatchLabel = computed(() => flowCard.value?.current_cut_batch?.batch_no || `第${Number(flowCard.value?.cut_batches?.length || 0) + 1}批`)
const cuttingStage = computed(() => cutReportVisible.value ? 3 : ['cut', 'in_progress'].includes(flowCard.value?.status) ? 2 : 1)
const issuePairsError = computed(() => Number(issuePairs.value) > remainingOrderQty.value ? `本批最多可安排 ${remainingOrderQty.value} 双` : '')
const canSubmitIssue = computed(() => Number(issuePairs.value) > 0 && !issuePairsError.value && issueRows.value.length > 0 && !issueLoading.value)
const hasIssuedMaterials = computed(() => issueLoaded.value && (issueRows.value.length === 0 || issueRows.value.every((row: any) => Number(row.issued_qty || 0) > 0)))
const money = (v: unknown) => Number(v || 0).toFixed(2)
const formatTime = (v?: string) => String(v || '').replace('T', ' ').slice(0, 16)
const batchStatusLabel = (value?: string) => ({ open: '待生产', in_production: '生产中', confirmed: '已确认' } as Record<string, string>)[String(value || '')] || value || '—'
function reportSucceeded(content: string) {
  uni.showModal({
    title: '报工成功',
    content,
    showCancel: false,
    confirmText: '返回首页',
    success: result => { if (result.confirm) uni.reLaunch({ url: '/pages/home/index' }) },
  })
}

onLoad(async query => {
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
    else if (target.kind === 'flow-card') {
      flowCard.value = await get(`/executions/headers/${target.code}/flow-card`)
      if (flowCard.value?.status === 'confirmed') {
        issuePairs.value = String(Math.max(0, Number(flowCard.value?.total_qty || 0) - Number(flowCard.value?.completed_qty || 0)) || '')
        await loadIssueCandidates()
      }
    }
  } catch (e: any) { errorMessage.value = e?.message || '扫码信息加载失败' }
  finally { loadingPage.value = false }
})

function applyCandidate() { const row = selected.value; if (!row) return; orderNo.value = row.order_no; const sku = row.items?.length === 1 ? row.items[0] : null; colorName.value = sku?.color_name || row.last_color_name || ''; sizeValue.value = sku?.size_value || row.last_size_value || '' }
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
async function startCutting() { submitting.value = true; try { await post(`/executions/headers/${flowCard.value.header_id}/start-cutting`, {}); flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`); uni.showToast({ title: '已开裁', icon: 'success' }) } catch (e: any) { uni.showToast({ title: e?.message || '开裁失败', icon: 'none' }) } finally { submitting.value = false } }
function goBack() { uni.navigateBack({ fail: () => goHome() }) }
function goHome() { uni.reLaunch({ url: '/pages/home/index' }) }
function adjustIssuePairs(delta: number) {
  const next = Math.min(remainingOrderQty.value, Math.max(0, Number(issuePairs.value || 0) + delta))
  onIssuePairsInput({ detail: { value: String(next || '') } })
}
async function openIssue() {
  issueVisible.value = true
  issuePairs.value = String(Math.max(0, Number(flowCard.value?.total_qty || 0) - Number(flowCard.value?.processes?.[0]?.completed_qty || 0)) || '')
  await loadIssueCandidates()
}
function onIssuePairsInput(event: any) {
  issuePairs.value = String(event?.detail?.value || '')
  if (issueCalcTimer) clearTimeout(issueCalcTimer)
  if (Number(issuePairs.value) <= 0) {
    issueRows.value = []
    issueDraft.value = {}
    return
  }
  issueCalcTimer = setTimeout(() => { void loadIssueCandidates() }, 350)
}
async function loadIssueCandidates() {
  if (Number(issuePairs.value) <= 0) return uni.showToast({ title: '请输入本次生产双数', icon: 'none' })
  const requestSeq = ++issueCalcSeq
  issueLoading.value = true
  issueLoaded.value = false
  try {
    const cuttingProcess = (flowCard.value?.processes || []).find((row: any) => /裁|冲|下料/.test(String(row.process_name || row.label || ''))) || flowCard.value?.processes?.[0]
    const segmentId = Number(cuttingProcess?.segment_id || 0)
    if (!segmentId) throw new Error('裁断工序未配置工序段，请先在基础资料中维护')
    const data: any = await get('/stock-issues/candidates', {
      header_id: flowCard.value.header_id,
      consume_segment_id: segmentId,
      pairs: Number(issuePairs.value),
    })
    if (requestSeq !== issueCalcSeq) return
    issueRows.value = data?.lines || []
    issueLoaded.value = true
    const draft: Record<number, string> = {}
    for (const row of issueRows.value) draft[row.id] = Number(row.suggested_qty || 0) > 0 ? String(row.suggested_qty) : ''
    issueDraft.value = draft
  } catch (e: any) {
    if (requestSeq !== issueCalcSeq) return
    issueVisible.value = false
    uni.showToast({ title: e?.message || '领料数据加载失败', icon: 'none' })
  } finally { if (requestSeq === issueCalcSeq) issueLoading.value = false }
}
async function submitIssue() {
  if (issuePairsError.value) return uni.showToast({ title: issuePairsError.value, icon: 'none' })
  const lines = issueRows.value.map((row: any) => ({ requirement_id: row.id, qty: Number(issueDraft.value[row.id] || 0) })).filter((row: any) => row.qty > 0)
  if (!lines.length) return uni.showToast({ title: '请填写领料数量', icon: 'none' })
  const invalid = lines.find((line: any) => line.qty > Number(issueRows.value.find((row: any) => row.id === line.requirement_id)?.max_issue_qty || 0))
  if (invalid) return uni.showToast({ title: '领料数量超过当前可领数量', icon: 'none' })
  issueSubmitting.value = true
  try {
    const data: any = await post('/stock-issues', { doc_type: 'issue', header_id: flowCard.value.header_id, lines })
    issueNotice.value = `领料申请 ${data?.doc_no || ''} 已提交，等待仓管确认过账`
    uni.showModal({ title: '领料申请已提交', content: '仓管确认过账后，请重新扫码进入本任务单开始开裁。未过账前不能开裁或报工。', showCancel: false, confirmText: '返回首页', success: result => { if (result.confirm) goHome() } })
  } catch (e: any) { uni.showToast({ title: e?.message || '领料申请提交失败', icon: 'none' }) }
  finally { issueSubmitting.value = false }
}
function openCutReport() {
  cutRows.value = (flowCard.value?.items || []).map((row: any) => ({
    ...row,
    qualified_qty: '',
    defect_qty: '',
  }))
  if (!cutRows.value.length) return uni.showToast({ title: '流转卡没有可报尺码', icon: 'none' })
  cutReportVisible.value = true
}
function remainingCutQty(row: any) { return Math.max(0, Number(row.qty || 0) - Number(row.cut_reported_qty || 0)) }
async function submitCutReport() {
  const rows = cutRows.value.filter((row: any) => Number(row.qualified_qty) > 0 || Number(row.defect_qty) > 0)
  if (!rows.length) return uni.showToast({ title: '请填写报工数量', icon: 'none' })
  const overRow = rows.find((row: any) => Number(row.qualified_qty || 0) > remainingCutQty(row))
  if (overRow) return uni.showToast({ title: `${overRow.size_value || '该尺码'}最多可报 ${remainingCutQty(overRow)} 双`, icon: 'none' })
  const cuttingProcess = (flowCard.value?.processes || []).find((row: any) => /裁|冲|下料/.test(String(row.process_name || row.label || ''))) || flowCard.value?.processes?.[0]
  if (!cuttingProcess?.process_name) return uni.showToast({ title: '未找到裁断工序', icon: 'none' })
  submitting.value = true
  try {
    const reportIds: number[] = []
    let totalAmount = 0
    for (const row of rows) {
      const result: any = await post('/reports', {
        worker_id: getProfile()?.id || 0,
        header_id: flowCard.value.header_id,
        process_name: cuttingProcess.process_name,
        color_name: row.color_name || flowCard.value.color_name || null,
        size_value: row.size_value || null,
        qualified_qty: Number(row.qualified_qty || 0),
        defect_qty: Number(row.defect_qty || 0),
        source: 'flow_card_cutting',
        confirm_over_plan: false,
        create_trace_bundle: false,
      })
      if (result?.need_confirm) throw new Error(result.message || '报工数量超过计划')
      reportIds.push(...(result?.work_log_ids || [result?.work_log_id]).filter(Boolean))
      totalAmount += Number(result?.amount || result?.total_amount || 0)
    }
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    const targets: Record<number, number> = {}
    for (const row of flowCard.value?.items || []) if (row.size_id) targets[Number(row.size_id)] = Number(row.cut_reported_qty || 0)
    const pairs = Math.max(1, Number(basketPairs.value) || 40)
    const result: any = await post(`/executions/headers/${flowCard.value.header_id}/cut-cards?dry_run=false&only_missing=true&bundle_size=${pairs}`, {
      target_qty_by_size: targets,
      new_batch: true,
      report_ids: reportIds,
    })
    flowCard.value = await get(`/executions/headers/${flowCard.value.header_id}/flow-card`)
    cutReportVisible.value = false
    successResult.value = { process_name: cuttingProcess.process_name, qualified_qty: rows.reduce((sum: number, row: any) => sum + Number(row.qualified_qty || 0), 0), amount: totalAmount }
    const batchNo = result?.batches?.[0]?.batch_no || result?.batch_no || ''
    reportSucceeded(`裁断 · ${successResult.value.qualified_qty} 双${batchNo ? `\n批次 ${batchNo}` : ''}\n新增 ${result?.to_create || 0} 个框码`)
  } catch (e: any) { uni.showToast({ title: e?.message || '裁断报工失败', icon: 'none' }) }
  finally { submitting.value = false }
}
</script>
