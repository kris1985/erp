<template>
  <view class="page line-report-native">
    <view class="mobile-page-head"><view><text>线产量报工</text><text>组长报一次，按参与成员拆分计件</text></view></view>
    <view v-if="error" class="card report-error">{{ error }}</view>
    <view v-else class="form-card-native">
      <picker :range="teams" range-key="name" @change="chooseTeam"><view class="native-field"><text>线 / 班组</text><text>{{ selectedTeam?.name || '请选择 ›' }}</text></view></picker>
      <picker :range="headers" range-key="header_no" @change="chooseHeader"><view class="native-field"><text>执行单</text><text>{{ selectedHeader?.header_no || '请选择 ›' }}</text></view></picker>
      <view class="native-field"><text>颜色</text><input v-model.trim="colorName" placeholder="可选" /></view>
      <view class="native-field"><text>合格</text><input v-model="qualifiedQty" type="number" placeholder="双" /></view>
      <view class="native-field"><text>不良</text><input v-model="defectQty" type="number" placeholder="0" /></view>
      <view class="native-field"><text>返修</text><input v-model="reworkQty" type="number" placeholder="0" /></view>
      <view class="native-field"><text>备注</text><input v-model.trim="note" placeholder="可选" /></view>
    </view>
    <view v-if="members.length" class="card member-card-native">
      <strong>本次参与成员</strong><text>请取消勾选请假或缺勤人员</text>
      <checkbox-group @change="changeMembers"><label v-for="member in members" :key="member.id"><checkbox :value="String(member.id)" :checked="memberIds.includes(member.id)" color="#0076ff" />{{ member.name }}</label></checkbox-group>
    </view>
    <view v-if="selectedHeader" class="card selected-header-card"><strong>{{ selectedHeader.header_no }} · {{ selectedHeader.product_code || '—' }}</strong><text>{{ selectedHeader.customer_name || '—' }} · 完工 {{ selectedHeader.completed_qty || 0 }}/{{ selectedHeader.total_qty || 0 }}</text></view>
    <button class="primary-button" :loading="submitting" @click="submit(false)">提交线产量</button>
    <view v-if="result" class="card report-success-native"><strong>报工成功</strong><text>¥{{ Number(result.amount || 0).toFixed(2) }}</text><text>已拆给 {{ result.work_log_count || memberIds.length }} 名成员</text></view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post } from '../../services/http'

const teams = ref<any[]>([]), headers = ref<any[]>([]), selectedTeamId = ref<number | null>(null), selectedHeaderId = ref<number | null>(null), memberIds = ref<number[]>([])
const colorName = ref(''), qualifiedQty = ref(''), defectQty = ref(''), reworkQty = ref(''), note = ref(''), error = ref(''), submitting = ref(false), result = ref<any>(null), presetHeaderId = ref(0)
const selectedTeam = computed(() => teams.value.find(x => x.id === selectedTeamId.value))
const selectedHeader = computed(() => headers.value.find(x => x.id === selectedHeaderId.value))
const members = computed(() => { const map = new Map<number, any>(); for (const x of selectedTeam.value?.members || []) map.set(x.id, x); if (selectedTeam.value?.leader_worker_id) map.set(selectedTeam.value.leader_worker_id, { id: selectedTeam.value.leader_worker_id, name: selectedTeam.value.leader_name || '组长' }); return [...map.values()] })
async function loadTeams() { try { const data: any = await get('/teams/mine'); teams.value = (data?.items || []).filter((x: any) => x.segment_id != null); if (teams.value.length === 1) selectTeam(teams.value[0]) } catch (e: any) { error.value = e?.message || '仅组长可报线产量' } }
async function loadHeaders() { if (!selectedTeamId.value) return; try { const data: any = await get('/executions', { status: 'in_progress', page_size: 100 }); headers.value = data?.items || []; const hit = headers.value.find(x => x.id === presetHeaderId.value); if (hit) { selectedHeaderId.value = hit.id; colorName.value = hit.color_name || '' } } catch (e: any) { error.value = e?.message || '在制单加载失败' } }
function selectTeam(team: any) { selectedTeamId.value = team.id; memberIds.value = [...new Set([...(team.members || []).map((x: any) => x.id), ...(team.leader_worker_id ? [team.leader_worker_id] : [])])]; loadHeaders() }
function chooseTeam(e: any) { selectTeam(teams.value[Number(e.detail.value)]) }
function chooseHeader(e: any) { const row = headers.value[Number(e.detail.value)]; selectedHeaderId.value = row?.id || null; colorName.value = row?.color_name || '' }
function changeMembers(e: any) { memberIds.value = (e.detail.value || []).map(Number) }
async function submit(confirmOverPlan: boolean) {
  if (!selectedTeamId.value || !selectedHeaderId.value) return uni.showToast({ title: '请选择班组和执行单', icon: 'none' })
  if (Number(qualifiedQty.value || 0) <= 0 && Number(defectQty.value || 0) <= 0) return uni.showToast({ title: '请填写合格或不良数量', icon: 'none' })
  if (!memberIds.value.length) return uni.showToast({ title: '至少选择一名参与成员', icon: 'none' })
  submitting.value = true; result.value = null
  try { const data: any = await post('/line-reports', { header_id: selectedHeaderId.value, team_id: selectedTeamId.value, qualified_qty: Number(qualifiedQty.value || 0), defect_qty: Number(defectQty.value || 0), rework_qty: Number(reworkQty.value || 0), defect_type: '质检不良', color_name: colorName.value || null, note: note.value || null, member_ids: memberIds.value, confirm_over_plan: confirmOverPlan }); if (data?.need_confirm) return uni.showModal({ title: '将超计划', content: data.message || '确认继续？', success: x => { if (x.confirm) submit(true) } }); result.value = data; qualifiedQty.value = ''; defectQty.value = ''; reworkQty.value = ''; note.value = ''; uni.showToast({ title: '线产量已报', icon: 'success' }) }
  catch (e: any) { uni.showToast({ title: e?.message || '报工失败', icon: 'none' }) }
  finally { submitting.value = false }
}
onLoad(query => { presetHeaderId.value = Number(query?.header_id || 0); loadTeams() })
</script>
