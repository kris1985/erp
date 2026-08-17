<template>
  <div class="admin-login">
    <div class="admin-login__card">
      <div class="admin-login__mark" aria-hidden="true">
        <span class="admin-login__petal" />
        <span class="admin-login__petal admin-login__petal--2" />
        <span class="admin-login__core" />
      </div>
      <h1 class="admin-login__brand">铁玉兰管家</h1>
      <p class="admin-login__sub">后台管理 · 经营 · 生产 · 财务</p>

      <!-- 第一步：账号密码（用户名或手机号，与手机端同一账号体系） -->
      <el-form v-if="!needSelect" :model="form" label-position="top" size="large" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.identifier" placeholder="用户名或手机号" clearable autofocus>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" show-password @keyup.enter="onSubmit">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="admin-login__submit"
          :loading="loading"
          native-type="submit"
        >
          登 录
        </el-button>
      </el-form>

      <!-- 第二步：多工厂选择 -->
      <div v-else class="admin-login__tenants">
        <p class="admin-login__tenants-title">该账号属于以下工厂，请选择：</p>
        <el-radio-group v-model="pickedTenant" class="admin-login__tenant-list">
          <el-radio v-for="t in tenants" :key="t.tenant_id" :value="t.tenant_id" border>
            {{ t.tenant_name }}
          </el-radio>
        </el-radio-group>
        <el-button
          type="primary"
          size="large"
          class="admin-login__submit"
          :loading="loading"
          @click="onSelectTenant"
        >
          进入后台
        </el-button>
        <button type="button" class="admin-login__back" @click="backToLogin">← 返回重新登录</button>
      </div>

      <p class="admin-login__hint">
        需要手机端？<RouterLink to="/login" class="admin-login__link">前往手机端入口</RouterLink>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore, type TenantChoice } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''

const form = reactive({ identifier: 'admin', password: 'admin123' })
const loading = ref(false)
const needSelect = ref(false)
const tenants = ref<TenantChoice[]>([])
const pickedTenant = ref<number | null>(null)

/** 后台入口：只跟随后台路径，纯员工（无后台角色）送回手机端。 */
function afterLogin() {
  if (auth.isPureStaff) {
    ElMessage.warning('该账号没有后台权限，已进入手机端')
    router.replace('/home')
    return
  }
  if (redirect && redirect.startsWith('/admin')) {
    router.replace(redirect)
    return
  }
  router.replace('/admin')
}

async function onSubmit() {
  loading.value = true
  try {
    const need = await auth.login(form.identifier, form.password)
    if (need?.need_select) {
      needSelect.value = true
      tenants.value = need.tenants
      pickedTenant.value = need.tenants[0]?.tenant_id ?? null
      return
    }
    ElMessage.success('登录成功')
    afterLogin()
  } catch {
    // 错误提示由 http 拦截器统一弹出（如“账号或密码错误”）
  } finally {
    loading.value = false
  }
}

async function onSelectTenant() {
  if (!pickedTenant.value) {
    ElMessage.warning('请选择工厂')
    return
  }
  loading.value = true
  try {
    await auth.selectTenant(form.identifier, form.password, pickedTenant.value)
    ElMessage.success('登录成功')
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
.admin-login {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(1200px 600px at 15% -10%, var(--ws-primary-soft), transparent 60%),
    radial-gradient(900px 500px at 110% 110%, var(--ws-brass-soft), transparent 55%),
    var(--ws-bg);
}

.admin-login__card {
  width: 100%;
  max-width: 420px;
  background: var(--ws-bg-elevated);
  border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius-lg);
  box-shadow: var(--ws-shadow-float);
  padding: 40px 36px 28px;
  animation: admin-login-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes admin-login-rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.admin-login__mark {
  width: 64px;
  height: 64px;
  margin: 0 auto 18px;
  position: relative;
}

.admin-login__petal {
  position: absolute;
  inset: 0;
  border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(77, 160, 255, 0.55));
  transform: rotate(-28deg) translateY(-4px);
  box-shadow: 0 4px 16px rgba(0, 118, 255, 0.2);
}

.admin-login__petal--2 {
  transform: rotate(28deg) translateY(-4px);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(0, 95, 204, 0.7));
  opacity: 0.92;
}

.admin-login__core {
  position: absolute;
  inset: 22px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #ffe8a8, #b08d57 70%);
  box-shadow: 0 2px 8px rgba(176, 141, 87, 0.45);
}

.admin-login__brand {
  font-family: var(--ws-font-display);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.04em;
  text-align: center;
  margin: 0 0 4px;
  color: var(--ws-ink);
}

.admin-login__sub {
  margin: 0 0 28px;
  text-align: center;
  font-size: 13px;
  letter-spacing: 0.08em;
  color: var(--ws-muted);
}

.admin-login__submit {
  width: 100%;
  margin-top: 8px;
  border-radius: 10px;
  font-weight: 600;
  letter-spacing: 0.2em;
}

.admin-login__tenants-title {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ws-ink);
}

.admin-login__tenant-list {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  margin-bottom: 20px;
}

.admin-login__tenant-list :deep(.el-radio) {
  height: auto;
  margin-right: 0;
  padding: 12px 16px;
}

.admin-login__back {
  display: block;
  margin: 18px auto 0;
  border: none;
  background: transparent;
  color: var(--ws-muted);
  font-size: 13px;
  cursor: pointer;
}

.admin-login__hint {
  margin: 24px 0 0;
  text-align: center;
  font-size: 13px;
  color: var(--ws-muted);
}

.admin-login__link {
  color: var(--ws-primary);
  text-decoration: none;
  font-weight: 600;
}

.admin-login__link:hover {
  text-decoration: underline;
}
</style>
