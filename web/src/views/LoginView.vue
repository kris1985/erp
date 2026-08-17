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

      <!-- 第一步：账号密码（用户名或手机号） -->
      <van-form v-if="!needSelect" class="login-form" @submit="onSubmit">
        <van-cell-group inset>
          <van-field v-model="identifier" name="identifier" label="账号" placeholder="用户名或手机号" />
          <van-field v-model="password" type="password" name="password" label="密码" placeholder="请输入密码" />
        </van-cell-group>
        <p class="login-hint">同一账号属于多家工厂时，登录后需选择工厂</p>
        <div class="big-btn login-submit">
          <van-button round block type="primary" native-type="submit" :loading="loading">登录</van-button>
        </div>
        <p class="login-entry-switch">
          电脑端后台？<RouterLink to="/admin/login" class="login-entry-switch__link">前往后台登录入口</RouterLink>
        </p>
      </van-form>

      <!-- 第二步：多工厂选择 -->
      <div v-else class="login-form">
        <p class="tenant-pick-title">该账号属于以下工厂，请选择</p>
        <van-radio-group v-model="pickedTenant">
          <van-cell-group inset>
            <van-cell
              v-for="t in tenants"
              :key="t.tenant_id"
              :title="t.tenant_name"
              clickable
              @click="pickedTenant = t.tenant_id"
            >
              <template #right-icon>
                <van-radio :name="t.tenant_id" />
              </template>
            </van-cell>
          </van-cell-group>
        </van-radio-group>
        <div class="big-btn login-submit">
          <van-button round block type="primary" :loading="loading" @click="onSelectTenant">进入</van-button>
        </div>
        <button type="button" class="tenant-back" @click="backToLogin">← 返回重新登录</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'
import { useAuthStore, type TenantChoice } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''

const identifier = ref('admin')
const password = ref('admin123')
const loading = ref(false)
const needSelect = ref(false)
const tenants = ref<TenantChoice[]>([])
const pickedTenant = ref<number | null>(null)

function afterLogin() {
  // 手机端入口：跟随原目标（扫码/追溯等）；无目标时按角色落点，有后台角色也留在 h5（电脑后台请走 /admin/login）
  if (redirect) {
    router.replace(redirect)
    return
  }
  if (auth.isPureStaff) {
    router.push(auth.mustChangePassword ? '/change-password' : '/home')
  } else {
    router.push('/workbench')
  }
}

async function onSubmit() {
  loading.value = true
  try {
    const need = await auth.login(identifier.value, password.value)
    if (need?.need_select) {
      needSelect.value = true
      tenants.value = need.tenants
      pickedTenant.value = need.tenants[0]?.tenant_id ?? null
      return
    }
    showToast('登录成功')
    afterLogin()
  } catch {
    // 错误提示由 http 拦截器统一弹出（如“账号或密码错误”）
  } finally {
    loading.value = false
  }
}

async function onSelectTenant() {
  if (!pickedTenant.value) {
    showToast('请选择工厂')
    return
  }
  loading.value = true
  try {
    await auth.selectTenant(identifier.value, password.value, pickedTenant.value)
    showToast('登录成功')
    afterLogin()
  } catch {
    // 错误提示由 http 拦截器统一弹出
  } finally {
    loading.value = false
  }
}

function backToLogin() {
  needSelect.value = false
  tenants.value = []
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

.login-form {
  animation: h5-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) 0.1s both;
}

.login-hint {
  margin: 14px 8px 0;
  font-size: 13px;
  color: var(--ws-muted);
}

.login-entry-switch {
  margin: 18px 8px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ws-muted);
}

.login-entry-switch__link {
  color: var(--ws-primary);
  text-decoration: none;
  font-weight: 600;
}

.tenant-pick-title {
  margin: 0 8px 14px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ws-ink);
}

.tenant-back {
  display: block;
  margin: 20px auto 0;
  border: none;
  background: transparent;
  color: var(--ws-muted);
  font-size: 14px;
  cursor: pointer;
}

.login-submit {
  margin: 28px 0 0;
}
</style>
