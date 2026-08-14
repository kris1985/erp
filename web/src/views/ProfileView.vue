<template>
  <div class="page profile">
    <section class="profile-hero">
      <div class="profile-hero__avatar">{{ avatarLetter }}</div>
      <div class="profile-hero__info">
        <div class="profile-hero__name">{{ profile.name }}</div>
        <div class="profile-hero__role">{{ profile.roleLabel }}</div>
      </div>
    </section>

    <p class="h5-section-label">个人信息</p>
    <van-cell-group inset class="profile-group">
      <van-cell title="姓名" :value="profile.name" />
      <van-cell v-if="auth.actor === 'worker'" title="手机号" :value="profile.mobile || '—'" />
      <van-cell v-else title="账号" :value="profile.username || '—'" />
      <van-cell title="角色" :value="profile.roleLabel" />
      <van-cell v-if="profile.positionName" title="岗位" :value="profile.positionName" />
      <van-cell v-if="profile.salaryLabel" title="计薪方式" :value="profile.salaryLabel" />
      <van-cell title="所属" :value="profile.tenantName || `租户 #${auth.tenantId || '—'}`" />
      <van-cell v-if="auth.actor === 'worker'" title="工号" :value="String(auth.workerId || profile.id || '—')" />
    </van-cell-group>

    <p class="h5-section-label">账户</p>
    <van-cell-group inset class="profile-group">
      <van-cell
        v-if="auth.actor === 'worker' && auth.role === 'leader'"
        title="组员管理"
        is-link
        @click="router.push('/my-team')"
      />
      <van-cell title="修改密码" is-link @click="pwdShow = true" />
    </van-cell-group>

    <div class="big-btn profile-logout">
      <van-button round block plain type="danger" @click="onLogout">退出登录</van-button>
    </div>

    <van-popup v-model:show="pwdShow" position="bottom" round :style="{ padding: '20px 16px 28px' }">
      <div class="pwd-sheet">
        <div class="pwd-sheet__title">修改密码</div>
        <p class="muted pwd-sheet__hint">新密码至少 6 位</p>
        <van-form @submit="onChangePassword">
          <van-cell-group inset>
            <van-field v-model="oldPassword" type="password" label="原密码" placeholder="当前密码" />
            <van-field v-model="newPassword" type="password" label="新密码" placeholder="至少 6 位" />
            <van-field v-model="confirmPassword" type="password" label="确认密码" placeholder="再输入一次" />
          </van-cell-group>
          <div class="big-btn" style="margin-top: 20px">
            <van-button round block type="primary" native-type="submit" :loading="pwdLoading">保存</van-button>
          </div>
        </van-form>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  manager: '经理',
  leader: '组长',
  worker: '员工',
}

const SALARY_LABELS: Record<string, string> = {
  pure_piece: '纯计件',
  base_plus_piece: '底薪+计件',
  hourly: '计时',
  fixed: '固定',
}

const profile = reactive({
  id: 0,
  name: auth.displayName || '—',
  username: '',
  mobile: '',
  role: auth.role || '',
  roleLabel: ROLE_LABELS[auth.role] || auth.role || '—',
  positionName: '',
  salaryLabel: '',
  tenantName: '',
})

const avatarLetter = computed(() => (profile.name || '?').trim().slice(0, 1))

const pwdShow = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const pwdLoading = ref(false)

async function loadProfile() {
  try {
    if (auth.actor === 'worker') {
      const res: any = await http.get('/auth/worker/me')
      const d = res.data || {}
      profile.id = d.id || auth.workerId
      profile.name = d.name || auth.displayName
      profile.mobile = d.mobile || ''
      profile.role = d.role || auth.role
      profile.roleLabel = ROLE_LABELS[profile.role] || profile.role || '员工'
      profile.positionName = d.position_name || ''
      profile.salaryLabel = SALARY_LABELS[d.salary_model] || ''
      profile.tenantName = d.tenant_name || ''
      if (d.name) {
        auth.displayName = d.name
      }
    } else {
      const res: any = await http.get('/auth/me')
      const d = res.data || {}
      profile.id = d.id || 0
      profile.name = d.display_name || auth.displayName
      profile.username = d.username || ''
      profile.role = d.role || auth.role
      profile.roleLabel = d.role_name || ROLE_LABELS[profile.role] || profile.role || '—'
      profile.tenantName = d.tenant_name || ''
      if (d.display_name) {
        auth.displayName = d.display_name
      }
      if (d.role) {
        auth.role = d.role
      }
    }
  } catch {
    profile.name = auth.displayName || '—'
    profile.roleLabel = ROLE_LABELS[auth.role] || auth.role || '—'
  }
}

async function onChangePassword() {
  if (newPassword.value.length < 6) {
    showToast('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    showToast('两次密码不一致')
    return
  }
  pwdLoading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    showToast('密码已修改')
    pwdShow.value = false
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '修改失败')
  } finally {
    pwdLoading.value = false
  }
}

async function onLogout() {
  await showConfirmDialog({
    title: '退出登录',
    message: '确定退出当前账号？',
  })
  auth.logout()
  router.push('/login')
}

onMounted(loadProfile)
</script>

<style scoped>
.profile-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 4px 18px;
  animation: h5-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.profile-hero__avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(145deg, #4da0ff, #005fcc);
  color: #fff;
  font-size: 26px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: -0.02em;
  box-shadow: 0 8px 20px rgba(0, 118, 255, 0.28);
  flex-shrink: 0;
}

.profile-hero__name {
  font-family: var(--ws-font-display);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ws-ink);
  line-height: 1.2;
}

.profile-hero__role {
  margin-top: 4px;
  font-size: 14px;
  font-weight: 500;
  color: var(--ws-muted);
}

.profile-group {
  margin-bottom: 4px;
}

.profile-logout {
  margin-top: 28px;
}

.pwd-sheet__title {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  text-align: center;
  margin-bottom: 4px;
}

.pwd-sheet__hint {
  text-align: center;
  margin: 0 0 14px;
}
</style>
