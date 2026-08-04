<template>
  <div class="page">
    <div class="page-title">登录</div>
    <p class="muted" style="margin: 0 4px 16px">微信里的 AI 车间管家 · 接单-派工-报工-算薪</p>
    <van-form @submit="onSubmit">
      <van-cell-group inset>
        <van-field v-model="username" name="username" label="账号" placeholder="admin" />
        <van-field v-model="password" type="password" name="password" label="密码" placeholder="密码" />
      </van-cell-group>
      <div class="big-btn" style="margin: 24px 16px">
        <van-button round block type="primary" native-type="submit" :loading="loading">登录</van-button>
      </div>
    </van-form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    showToast('登录成功')
    router.push('/')
  } finally {
    loading.value = false
  }
}
</script>
