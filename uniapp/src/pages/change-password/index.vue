<template>
  <view class="page change-password-native">
    <view class="brand-mark">锁</view>
    <text class="change-title">设置新密码</text>
    <text class="change-subtitle">首次登录或管理员重置后，需要先修改密码</text>
    <view class="card form-card">
      <input v-model="oldPassword" class="field" password placeholder="原密码" />
      <input v-model="newPassword" class="field" password placeholder="新密码，至少 6 位" />
      <input v-model="confirmation" class="field" password placeholder="再次输入新密码" />
      <button class="primary-button" :loading="loading" @click="submit">保存并进入</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { changePassword } from '../../services/auth'
import { clearSavedCredentials } from '../../services/storage'

const oldPassword = ref('123456'), newPassword = ref(''), confirmation = ref(''), loading = ref(false)
async function submit() {
  if (newPassword.value.length < 6) return uni.showToast({ title: '新密码至少 6 位', icon: 'none' })
  if (newPassword.value !== confirmation.value) return uni.showToast({ title: '两次密码不一致', icon: 'none' })
  loading.value = true
  try { await changePassword(oldPassword.value, newPassword.value); clearSavedCredentials(); uni.showToast({ title: '密码已修改', icon: 'success' }); setTimeout(() => uni.reLaunch({ url: '/pages/home/index' }), 400) }
  catch (e: any) { uni.showToast({ title: e?.message || '修改失败', icon: 'none' }) }
  finally { loading.value = false }
}
</script>
