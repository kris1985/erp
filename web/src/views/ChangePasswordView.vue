<template>
  <div class="h5-shell">
    <div class="page page--solo">
      <p class="page-kicker">账户安全</p>
      <h1 class="page-title">修改密码</h1>
      <p class="page-subtitle">首次登录或管理员重置后，请设置新密码（至少 6 位）</p>
      <van-form @submit="onSubmit">
        <van-cell-group inset>
          <van-field v-model="oldPassword" type="password" label="原密码" placeholder="默认密码或当前密码" />
          <van-field v-model="newPassword" type="password" label="新密码" placeholder="至少 6 位" />
          <van-field v-model="confirm" type="password" label="确认密码" placeholder="再输入一次" />
        </van-cell-group>
        <div class="big-btn" style="margin: 28px 0 0">
          <van-button round block type="primary" native-type="submit" :loading="loading">保存并进入</van-button>
        </div>
      </van-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const oldPassword = ref('123456')
const newPassword = ref('')
const confirm = ref('')
const loading = ref(false)

async function onSubmit() {
  if (newPassword.value.length < 6) {
    showToast('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirm.value) {
    showToast('两次密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    showToast('密码已修改')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    router.replace(redirect || '/home')
  } finally {
    loading.value = false
  }
}
</script>
