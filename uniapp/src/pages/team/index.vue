<template>
  <view class="page team-native-page">
    <view class="mobile-page-head"><view><text>{{ noTeams ? '我的部门' : '我的班组' }}</text><text>成员维护与现场代报范围</text></view></view>
    <view v-if="loading" class="empty-state">正在加载成员…</view>
    <view v-else-if="error" class="card report-error">{{ error }}</view>
    <template v-else-if="team">
      <view class="team-summary-native"><view><text>{{ noTeams ? '部门成员' : '我的班组' }}</text><strong>{{ team.name }}</strong><small>{{ team.segment_name || '未挂工序段' }}</small></view><view><strong>{{ members.length }}</strong><text>位成员</text></view></view>

      <view class="team-search-native"><input v-model.trim="keyword" placeholder="输入姓名或手机号" confirm-type="search" @confirm="search" /><button :loading="searching" @click="search">查找</button></view>
      <view v-if="keyword && !searching" class="team-hits">
        <view v-if="!hits.length" class="empty-inline">没有匹配的员工</view>
        <view v-for="worker in hits" :key="worker.id" class="card person-native"><view class="person-avatar-native">{{ initial(worker.name) }}</view><view><strong>{{ worker.name }}</strong><text>{{ worker.mobile || '无手机号' }}</text><small v-if="worker.status === 'other_team'">已在「{{ worker.team_name }}」</small><small v-else-if="worker.status === 'in_team'">已在本组</small></view><button v-if="worker.can_join" :loading="busyId === worker.id" @click="add(worker)">加入</button></view>
      </view>

      <view class="section-row"><text>{{ noTeams ? '部门' : '班组' }}成员</text><text>{{ members.length }} 位</text></view>
      <view v-if="!members.length" class="card clear-card"><strong>还没有成员</strong><text>可通过上方姓名或手机号搜索加入</text></view>
      <view v-else class="team-member-list">
        <view v-for="worker in orderedMembers" :key="worker.id" class="card person-native"><view class="person-avatar-native" :class="{ leader: worker.id === team.leader_worker_id }">{{ initial(worker.name) }}</view><view><strong>{{ worker.name }}<text v-if="worker.id === team.leader_worker_id" class="leader-label">我 · 组长</text></strong><text>{{ worker.mobile || '无手机号' }}</text></view><button v-if="worker.id !== team.leader_worker_id" class="remove-button" :loading="busyId === worker.id" @click="remove(worker)">移除</button></view>
      </view>
    </template>
    <view v-else class="empty-state">尚未分配班组，请联系管理员</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { del, get, post } from '../../services/http'

const loading = ref(true), searching = ref(false), error = ref(''), keyword = ref(''), team = ref<any>(null), hits = ref<any[]>([]), busyId = ref<number | null>(null), noTeams = ref(false)
const members = computed<any[]>(() => team.value?.members || [])
const orderedMembers = computed(() => [...members.value].sort((a, b) => Number(b.id === team.value?.leader_worker_id) - Number(a.id === team.value?.leader_worker_id)))
const initial = (name?: string) => String(name || '员').trim().slice(0, 1)

async function load() {
  loading.value = true; error.value = ''
  try { const [org, mine]: any[] = await Promise.all([get('/org/settings').catch(() => ({})), get('/teams/mine')]); noTeams.value = org?.enable_teams === false; team.value = mine?.items?.[0] || null }
  catch (e: any) { error.value = e?.message || '仅组长可维护班组成员' }
  finally { loading.value = false }
}
async function search() {
  if (!keyword.value || !team.value) { hits.value = []; return }
  searching.value = true
  try { const data: any = await get('/teams/mine/candidates', { q: keyword.value, team_id: team.value.id }); hits.value = data?.items || [] }
  catch (e: any) { uni.showToast({ title: e?.message || '搜索失败', icon: 'none' }); hits.value = [] }
  finally { searching.value = false }
}
async function add(worker: any) {
  busyId.value = worker.id
  try { team.value = await post('/teams/mine/members', { worker_id: worker.id, team_id: team.value.id }); uni.showToast({ title: `已加入 ${worker.name}`, icon: 'success' }); await search() }
  catch (e: any) { uni.showToast({ title: e?.message || '加入失败', icon: 'none' }) }
  finally { busyId.value = null }
}
function remove(worker: any) {
  uni.showModal({ title: '移除成员', content: `将 ${worker.name} 移出「${team.value.name}」？`, success: async result => {
    if (!result.confirm) return
    busyId.value = worker.id
    try { team.value = await del(`/teams/mine/members/${worker.id}`, { team_id: team.value.id }); uni.showToast({ title: `已移除 ${worker.name}`, icon: 'success' }); if (keyword.value) await search() }
    catch (e: any) { uni.showToast({ title: e?.message || '移除失败', icon: 'none' }) }
    finally { busyId.value = null }
  } })
}
let timer: ReturnType<typeof setTimeout> | null = null
watch(keyword, value => { if (timer) clearTimeout(timer); if (!value) { hits.value = []; return } timer = setTimeout(search, 300) })
onShow(load)
</script>
