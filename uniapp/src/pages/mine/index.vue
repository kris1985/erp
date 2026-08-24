<template>
  <view class="page">
    <view class="profile-hero-native">
      <view class="avatar">{{ (profile?.name || cached?.displayName || '?').slice(0, 1) }}</view>
      <view><text class="profile-name">{{ profile?.name || cached?.displayName || '—' }}</text><text class="profile-role">{{ roleLabel }}</text></view>
    </view>
    <view class="card profile-card">
      <view v-if="profile?.mobile" class="profile-row"><text>手机号</text><text>{{ profile.mobile }}</text></view>
      <view v-if="profile?.username" class="profile-row"><text>账号</text><text>{{ profile.username }}</text></view>
      <view v-if="profile?.department_name" class="profile-row"><text>部门</text><text>{{ profile.department_name }}</text></view>
      <view class="profile-row"><text>所属工厂</text><text>{{ profile?.tenant_name || cached?.tenantName || '—' }}</text></view>
      <view v-if="salaryLabel" class="profile-row"><text>计薪方式</text><text>{{ salaryLabel }}</text></view>
    </view>
    <button class="logout-button" @click="confirmLogout">退出登录</button>
    <MobileTabBar active="mine" />
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { logout } from '../../services/auth'
import { get } from '../../services/http'
import { getProfile } from '../../services/storage'
import MobileTabBar from '../../components/MobileTabBar.vue'

const cached = ref(getProfile())
const profile = ref<any>(null)
const roleLabel = computed(() => profile.value?.role_name || ({ admin: '管理员', manager: '经理', leader: '组长', worker: '员工' } as any)[profile.value?.role || cached.value?.role] || '员工')
const salaryLabel = computed(() => ({ pure_piece: '纯计件', base_plus_piece: '底薪+计件', hourly: '计时', fixed: '固定' } as any)[profile.value?.salary_model] || '')

async function load() {
  try { profile.value = await get('/auth/me') } catch { /* 登录拦截器统一处理 */ }
}

function confirmLogout() {
  uni.showModal({ title: '退出登录', content: '确定退出当前账号？', success: (result) => { if (result.confirm) logout() } })
}

onShow(load)
</script>
