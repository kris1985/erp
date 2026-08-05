<template>
  <div class="h5-shell">
    <div class="page page--solo login">
      <header class="login-hero">
        <div class="login-mark" aria-hidden="true">
          <span class="login-mark__petal" />
          <span class="login-mark__petal login-mark__petal--2" />
          <span class="login-mark__core" />
        </div>
        <h1 class="login-brand">铁玉兰管家</h1>
        <p class="login-tagline">接单 · 派工 · 报工 · 算薪</p>
      </header>

      <div class="login-segment" role="tablist">
        <button
          type="button"
          role="tab"
          class="login-segment__btn"
          :class="{ active: tab === 'user' }"
          :aria-selected="tab === 'user'"
          @click="tab = 'user'"
        >
          后台账号
        </button>
        <button
          type="button"
          role="tab"
          class="login-segment__btn"
          :class="{ active: tab === 'worker' }"
          :aria-selected="tab === 'worker'"
          @click="tab = 'worker'"
        >
          员工登录
        </button>
      </div>

      <van-form v-if="tab === 'user'" class="login-form" @submit="onUserSubmit">
        <van-cell-group inset>
          <van-field v-model="username" name="username" label="账号" placeholder="admin" />
          <van-field v-model="password" type="password" name="password" label="密码" placeholder="请输入密码" />
        </van-cell-group>
        <div class="big-btn login-submit">
          <van-button round block type="primary" native-type="submit" :loading="loading">登录</van-button>
        </div>
      </van-form>

      <van-form v-else class="login-form" @submit="onWorkerSubmit">
        <van-cell-group inset>
          <van-field v-model="mobile" name="mobile" label="手机号" placeholder="11 位手机号" />
          <van-field
            v-model="workerPassword"
            type="password"
            name="password"
            label="密码"
            placeholder="默认 123456"
          />
        </van-cell-group>
        <p class="login-hint">首次登录须修改默认密码</p>
        <div class="big-btn login-submit">
          <van-button round block type="primary" native-type="submit" :loading="loading">登录</van-button>
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
const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
const tab = ref<'user' | 'worker'>(redirect.startsWith('/scan/') ? 'worker' : 'user')
const username = ref('admin')
const password = ref('admin123')
const mobile = ref('13800138001')
const workerPassword = ref('123456')
const loading = ref(false)

function afterLogin() {
  if (redirect) {
    router.replace(redirect)
    return
  }
  if (auth.actor === 'worker') {
    router.push(auth.mustChangePassword ? '/change-password' : '/home')
  } else {
    router.push('/admin')
  }
}

async function onUserSubmit() {
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    showToast('登录成功')
    afterLogin()
  } finally {
    loading.value = false
  }
}

async function onWorkerSubmit() {
  loading.value = true
  try {
    await auth.workerLogin(mobile.value, workerPassword.value)
    showToast('登录成功')
    if (auth.mustChangePassword) {
      router.push({ path: '/change-password', query: redirect ? { redirect } : {} })
    } else {
      afterLogin()
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 24px);
  min-height: calc(100dvh - 24px);
  padding-top: 48px;
}

.login-hero {
  text-align: center;
  margin-bottom: 36px;
  animation: h5-rise 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.login-mark {
  width: 72px;
  height: 72px;
  margin: 0 auto 20px;
  position: relative;
  display: grid;
  place-items: center;
}

.login-mark__petal {
  position: absolute;
  width: 28px;
  height: 40px;
  border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(77, 160, 255, 0.55));
  transform: rotate(-28deg) translateY(-6px);
  box-shadow: 0 4px 16px rgba(0, 118, 255, 0.2);
}

.login-mark__petal--2 {
  transform: rotate(28deg) translateY(-6px);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(0, 95, 204, 0.7));
  opacity: 0.92;
}

.login-mark__core {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #ffe8a8, #b08d57 70%);
  box-shadow: 0 2px 8px rgba(176, 141, 87, 0.45);
  z-index: 1;
}

.login-brand {
  font-family: var(--ws-font-display);
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.04em;
  margin: 0 0 8px;
  color: var(--ws-ink);
}

.login-tagline {
  margin: 0;
  font-size: 15px;
  color: var(--ws-muted);
  font-weight: 500;
  letter-spacing: 0.06em;
}

.login-segment {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  background: rgba(118, 118, 128, 0.12);
  border-radius: 12px;
  margin-bottom: 20px;
  animation: h5-rise 0.55s cubic-bezier(0.22, 1, 0.36, 1) 0.06s both;
}

.login-segment__btn {
  border: none;
  background: transparent;
  height: 36px;
  border-radius: 9px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ws-ink);
  opacity: 0.55;
  cursor: pointer;
  transition: background 0.2s ease, opacity 0.2s ease, box-shadow 0.2s ease;
  -webkit-tap-highlight-color: transparent;
}

.login-segment__btn.active {
  background: #fff;
  opacity: 1;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
}

.login-form {
  animation: h5-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) 0.1s both;
}

.login-hint {
  margin: 14px 8px 0;
  font-size: 13px;
  color: var(--ws-muted);
}

.login-submit {
  margin: 28px 0 0;
}
</style>
