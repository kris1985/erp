<template>
  <div class="admin-app admin-login">
    <div class="admin-login__card">
      <h1 class="admin-login__brand">铁玉兰运营</h1>
      <p class="admin-login__sub">租户开通 · 续期 · 停用</p>
      <el-form :model="form" label-position="top" size="large" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="运营账号" clearable autofocus>
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" show-password @keyup.enter="onSubmit">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="admin-login__submit" :loading="loading" native-type="submit">
          登 录
        </el-button>
      </el-form>
      <button type="button" class="admin-login__ops" @click="router.push('/admin/login')">返回工厂后台</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import opsHttp from '@/api/opsHttp'
import { useOpsAuthStore } from '@/stores/opsAuth'

const ops = useOpsAuthStore()
const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function onSubmit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请填写账号和密码')
    return
  }
  loading.value = true
  try {
    const res: any = await opsHttp.post('/operators/login', {
      username: form.username.trim(),
      password: form.password,
    })
    ops.setSession(res.data)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    router.replace(redirect.startsWith('/ops') && redirect !== '/ops/login' ? redirect : '/ops')
  } catch {
    // 错误由 opsHttp 提示
  } finally {
    loading.value = false
  }
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

.admin-login__ops {
  display: block;
  margin: 22px auto 0;
  border: none;
  background: transparent;
  color: var(--ws-muted);
  font-size: 13px;
  cursor: pointer;
}

.admin-login__ops:hover {
  color: var(--ws-primary);
}
</style>
