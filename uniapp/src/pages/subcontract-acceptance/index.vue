<template>
  <view class="acceptance-page">
    <view v-if="loading" class="state-card">加载中…</view>
    <view v-else-if="errorMessage" class="state-card state-card--error">
      <text>{{ errorMessage }}</text>
      <button @click="loadDetail">重新加载</button>
    </view>

    <template v-else-if="detail">
      <view class="acceptance-hero">
        <view>
          <text class="acceptance-kicker">外发验收</text>
          <strong>{{ detail.subcontract_no || '—' }}</strong>
          <text>{{ detail.partner_name || '—' }}</text>
        </view>
        <text :class="['status-chip', { done: isFinished }]">{{ isFinished ? '已完工' : '待验收' }}</text>
      </view>

      <view class="info-card">
        <view><text>生产单号</text><strong>{{ detail.linked_no || '—' }}</strong></view>
        <view><text>工厂型号</text><strong>{{ detail.product_code || '—' }}</strong></view>
        <view><text>颜色</text><strong>{{ detail.color_name || '—' }}</strong></view>
        <view><text>工序</text><strong>{{ detail.process_name || '—' }}</strong></view>
        <view><text>外发数量</text><strong>{{ detail.total_qty || 0 }} 双</strong></view>
        <view><text>待验收</text><strong>{{ detail.outstanding_qty || 0 }} 双</strong></view>
        <view><text>废品</text><strong>{{ detail.loss_qty || 0 }} 双</strong></view>
      </view>

      <view v-if="isFinished" class="finished-card">该外发单已全部验收，无需重复登记。</view>

      <template v-else>
        <view class="form-card">
          <label>
            <text>完工数量</text>
            <view class="number-input"><input v-model="acceptanceQty" type="number" placeholder="0" /><text>双</text></view>
          </label>
          <label>
            <text>废品</text>
            <view class="number-input number-input--readonly"><strong>{{ detail.loss_qty || 0 }}</strong><text>双</text></view>
          </label>
          <label>
            <text>分担损失</text>
            <view class="number-input"><text>¥</text><input v-model="sharedLossAmount" type="digit" placeholder="0.00" /></view>
          </label>
          <label class="note-field">
            <text>送货单号</text>
            <input v-model.trim="deliveryNoteNo" maxlength="80" placeholder="选填" />
          </label>
          <label class="note-field">
            <text>备注</text>
            <input v-model.trim="note" placeholder="可选" />
          </label>
        </view>

        <view class="calculation-card">
          <view><text>完工数量</text><strong>{{ Number(acceptanceQty || 0) }} 双</strong></view>
          <view><text>废品损失</text><strong class="loss">¥{{ money(lossAmount) }}</strong></view>
          <view><text>公司承担</text><strong>¥{{ money(companyLossAmount) }}</strong></view>
          <view><text>本次应付</text><strong>¥{{ money(payableAmount) }}</strong></view>
          <text class="formula">废品来自报废记录；损失 = 废品数量 × 工价 ¥{{ money(detail.unit_price) }}；分担损失不能大于剩余损失</text>
        </view>

        <view class="cut-sticky-bar">
          <button class="primary-button cut-sticky-button" :loading="submitting" :disabled="submitting" @click="submitAcceptance">确认验收</button>
        </view>
      </template>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad, onPullDownRefresh } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const orderId = ref(0)
const detail = ref<any>(null)
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref('')
const acceptanceQty = ref('')
const sharedLossAmount = ref('')
const note = ref('')
const deliveryNoteNo = ref('')

const isFinished = computed(() => detail.value?.status === 'received' || Number(detail.value?.outstanding_qty || 0) <= 0)
const lossAmount = computed(() => Number(detail.value?.loss_qty || 0) * Number(detail.value?.unit_price || 0))
const remainingShareable = computed(() => Math.max(0, Number(detail.value?.remaining_shared_loss_amount ?? (lossAmount.value - Number(detail.value?.shared_loss_amount || 0)))))
const companyLossAmount = computed(() => Math.max(0, remainingShareable.value - Number(sharedLossAmount.value || 0)))
const payableAmount = computed(() => Math.max(0, Number(acceptanceQty.value || 0) * Number(detail.value?.unit_price || 0) - Number(sharedLossAmount.value || 0)))

function money(value: unknown) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

async function loadDetail() {
  if (!orderId.value) {
    loading.value = false
    errorMessage.value = '外发单无效'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    detail.value = await get(`/subcontract-orders/${orderId.value}/acceptance`)
    acceptanceQty.value = String(detail.value?.outstanding_qty || '')
    sharedLossAmount.value = ''
    note.value = ''
    deliveryNoteNo.value = ''
  } catch (error: any) {
    errorMessage.value = error?.message || '外发单加载失败'
  } finally {
    loading.value = false
    uni.stopPullDownRefresh()
  }
}

async function submitAcceptance() {
  const quantity = Number(acceptanceQty.value || 0)
  const sharedLoss = Number(sharedLossAmount.value || 0)
  const outstanding = Number(detail.value?.outstanding_qty || 0)
  if (!Number.isInteger(quantity) || quantity <= 0) {
    uni.showToast({ title: '请输入完工数量', icon: 'none' })
    return
  }
  if (quantity > outstanding) {
    uni.showToast({ title: `完工数量不能超过 ${outstanding} 双`, icon: 'none' })
    return
  }
  if (!Number.isFinite(sharedLoss) || sharedLoss < 0 || sharedLoss > remainingShareable.value) {
    uni.showToast({ title: '分担损失不能大于剩余损失金额', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    detail.value = await post(`/subcontract-orders/${orderId.value}/receipts`, {
      qty: quantity,
      shared_loss_amount: sharedLoss,
      delivery_note_no: deliveryNoteNo.value || null,
      note: note.value || null,
    })
    acceptanceQty.value = String(detail.value?.outstanding_qty || '')
    sharedLossAmount.value = ''
    note.value = ''
    deliveryNoteNo.value = ''
    uni.showToast({ title: '验收登记成功', icon: 'success' })
  } catch (error: any) {
    uni.showToast({ title: error?.message || '验收登记失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}

onLoad((query) => {
  orderId.value = Number(query?.id || 0)
  void loadDetail()
})

onPullDownRefresh(() => void loadDetail())
</script>

<style scoped lang="scss">
.acceptance-page { min-height: 100vh; box-sizing: border-box; padding: 28rpx 24rpx 180rpx; background: #f4f7fb; color: #172033; }
.state-card { margin-top: 120rpx; padding: 48rpx 28rpx; border-radius: 24rpx; background: #fff; color: #7a8797; text-align: center; }
.state-card button { width: 220rpx; margin-top: 28rpx; border: 0; border-radius: 16rpx; background: #1769d2; color: #fff; font-size: 26rpx; }
.state-card--error { color: #c2413b; }
.acceptance-hero { display: flex; padding: 34rpx 32rpx; align-items: flex-start; justify-content: space-between; border-radius: 28rpx; background: linear-gradient(140deg, #123f78, #1769d2); color: #fff; box-shadow: 0 18rpx 44rpx rgba(23, 105, 210, .2); }
.acceptance-hero > view { display: flex; min-width: 0; flex-direction: column; gap: 9rpx; }
.acceptance-hero strong { font-size: 38rpx; line-height: 1.15; }
.acceptance-hero view > text:last-child { opacity: .82; font-size: 24rpx; }
.acceptance-kicker { opacity: .72; font-size: 21rpx; font-weight: 700; letter-spacing: 4rpx; }
.status-chip { padding: 9rpx 17rpx; border-radius: 999rpx; background: rgba(255, 255, 255, .17); font-size: 22rpx; white-space: nowrap; }
.status-chip.done { background: rgba(52, 211, 153, .22); }
.info-card, .form-card, .calculation-card, .finished-card { margin-top: 22rpx; border-radius: 24rpx; background: #fff; box-shadow: 0 8rpx 28rpx rgba(28, 53, 84, .06); }
.info-card { display: grid; grid-template-columns: 1fr 1fr; overflow: hidden; }
.info-card > view { display: flex; min-width: 0; padding: 24rpx 26rpx; flex-direction: column; gap: 8rpx; border-right: 1rpx solid #edf1f6; border-bottom: 1rpx solid #edf1f6; }
.info-card text { color: #8a96a6; font-size: 21rpx; }
.info-card strong { overflow: hidden; font-size: 26rpx; text-overflow: ellipsis; white-space: nowrap; }
.form-card { padding: 4rpx 28rpx; }
.form-card label { display: flex; min-height: 94rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #edf1f6; }
.form-card label:last-child { border-bottom: 0; }
.form-card label > text { color: #5f6c7b; font-size: 25rpx; }
.number-input { display: flex; align-items: center; gap: 10rpx; color: #8a96a6; font-size: 23rpx; }
.number-input input { width: 190rpx; color: #172033; font-size: 30rpx; font-weight: 700; text-align: right; }
.number-input--readonly strong { color: #172033; font-size: 30rpx; font-weight: 700; }
.note-field input { width: 390rpx; color: #172033; font-size: 25rpx; text-align: right; }
.calculation-card { padding: 10rpx 28rpx 24rpx; }
.calculation-card > view { display: flex; padding: 20rpx 0; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #edf1f6; }
.calculation-card view text { color: #6f7c8c; font-size: 24rpx; }
.calculation-card strong { font-size: 29rpx; }
.calculation-card .loss { color: #d85843; }
.formula { display: block; padding-top: 20rpx; color: #98a2b1; font-size: 21rpx; line-height: 1.5; }
.finished-card { padding: 34rpx 28rpx; color: #45805e; font-size: 25rpx; text-align: center; }
</style>
