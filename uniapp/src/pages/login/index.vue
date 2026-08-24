<template>
  <view class="page login-page">
    <view class="brand-mark">玉</view>
    <text class="brand">铁玉兰管家</text>
    <text class="tagline">接单 · 派工 · 报工 · 算薪</text>

    <view v-if="!tenants.length" class="card form-card">
      <input v-model.trim="identifier" class="field" placeholder="用户名或手机号" />
      <input v-model="password" class="field" password placeholder="请输入密码" />
      <label class="remember-row" @click="remember = !remember">
        <checkbox :checked="remember" color="#0076ff" />
        <text>记住密码</text>
      </label>
      <button class="primary-button" :loading="loading" @click="submit">登录</button>
    </view>

    <view v-else class="card form-card">
      <text class="section-title">请选择工厂</text>
      <radio-group @change="pickTenant">
        <label v-for="item in tenants" :key="item.tenant_id" class="tenant-row">
          <text>{{ item.tenant_name }}</text>
          <radio :value="String(item.tenant_id)" :checked="tenantId === item.tenant_id" color="#1769e0" />
        </label>
      </radio-group>
      <button class="primary-button" :loading="loading" @click="enterTenant">进入</button>
      <button class="text-button" @click="tenants = []">返回重新登录</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { login, selectTenant } from '../../services/auth'
import { clearSavedCredentials, getProfile, getSavedCredentials, saveCredentials } from '../../services/storage'

const saved = getSavedCredentials()
const identifier = ref(saved?.identifier || '')
const password = ref(saved?.password || '')
const remember = ref(Boolean(saved))
const loading = ref(false)
const tenants = ref<Array<{ tenant_id: number; tenant_name: string }>>([])
const tenantId = ref(0)

function toast(title: string) {
  uni.showToast({ title, icon: 'none' })
}

async function submit() {
  if (!identifier.value || !password.value) return toast('请输入账号和密码')
  loading.value = true
  try {
    const result = await login(identifier.value, password.value)
    if (result.needSelect) {
      tenants.value = result.tenants
      tenantId.value = result.tenants[0]?.tenant_id || 0
      return
    }
    persistCredentials()
    enterApp()
  } catch (error: any) {
    toast(error?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

function pickTenant(event: any) {
  tenantId.value = Number(event.detail.value)
}

async function enterTenant() {
  if (!tenantId.value) return toast('请选择工厂')
  loading.value = true
  try {
    await selectTenant(identifier.value, password.value, tenantId.value)
    persistCredentials()
    enterApp()
  } catch (error: any) {
    toast(error?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

function persistCredentials() {
  if (remember.value) saveCredentials(identifier.value, password.value)
  else clearSavedCredentials()
}

function enterApp() {
  uni.reLaunch({ url: getProfile()?.mustChangePassword ? '/pages/change-password/index' : '/pages/home/index' })
}
</script>
