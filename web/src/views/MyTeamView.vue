<template>
  <div class="page">
    <div v-if="loading" class="h5-empty">加载中…</div>
    <template v-else-if="!team">
      <div class="h5-empty">
        <div class="h5-empty__mark">◎</div>
        尚未分配班组，请联系管理员
      </div>
    </template>
    <template v-else>
      <section class="team-head">
        <div class="team-head__copy">
          <div class="team-head__eyebrow">我的班组</div>
          <div class="team-head__name">{{ team.name }}</div>
          <div class="muted">搜索姓名或手机号，将员工加入班组</div>
        </div>
        <div class="team-head__count">
          <strong>{{ team.member_count || members.length }}</strong>
          <span>位成员</span>
        </div>
      </section>

      <section class="member-search" aria-label="添加组员">
        <div class="member-search__label">快速查找并加入</div>
        <div class="h5-filter member-search__field" :class="{ 'member-search__field--active': keyword.trim() }">
          <van-icon name="search" class="h5-filter__icon" />
          <input
            v-model="keyword"
            type="search"
            class="h5-filter__input"
            placeholder="输入姓名或手机号"
            aria-label="搜索姓名或手机号"
            @keyup.enter="onSearch"
          />
          <button v-if="keyword" type="button" class="h5-filter__clear" aria-label="清除搜索" @click="clearSearch">
            <van-icon name="cross" />
          </button>
        </div>
      </section>

      <div v-if="searching" class="search-state">正在查找员工…</div>
      <div v-else-if="keyword.trim() && !hits.length" class="search-state">没有匹配的员工</div>
      <div v-else-if="hits.length" class="people">
        <article v-for="w in hits" :key="w.id" class="h5-list-card person">
          <div class="person__avatar" aria-hidden="true">{{ initials(w.name) }}</div>
          <div class="person__main">
            <div class="person__name">
              {{ w.name }}
              <span v-if="w.can_join" class="availability-tag">可加入</span>
            </div>
            <div class="muted">{{ w.mobile || '无手机号' }}</div>
            <div v-if="w.status === 'other_team'" class="person__hint">已在「{{ w.team_name }}」</div>
            <div v-else-if="w.status === 'in_team'" class="person__hint">已在本组</div>
          </div>
          <van-button
            v-if="w.can_join"
            size="small"
            round
            type="primary"
            :loading="busyId === w.id"
            @click="addMember(w)"
          >
            加入
          </van-button>
        </article>
      </div>

      <div class="member-list-head">
        <p class="h5-section-label">本组组员</p>
        <span>{{ members.length }} 位</span>
      </div>
      <div v-if="!members.length" class="h5-empty">还没有组员</div>
      <div v-else class="people">
        <article
          v-for="w in orderedMembers"
          :key="w.id"
          class="h5-list-card person"
          :class="{ 'person--leader': w.id === team.leader_worker_id }"
        >
          <div class="person__avatar" :class="{ 'person__avatar--leader': w.id === team.leader_worker_id }" aria-hidden="true">
            {{ initials(w.name) }}
          </div>
          <div class="person__main">
            <div class="person__name">
              {{ w.name }}
              <template v-if="w.id === team.leader_worker_id">
                <span class="leader-tag">我 · 组长</span>
              </template>
            </div>
            <div class="muted">{{ w.mobile || '无手机号' }}</div>
          </div>
          <van-button
            v-if="w.id !== team.leader_worker_id"
            size="small"
            round
            plain
            type="danger"
            :loading="busyId === w.id"
            @click="removeMember(w)"
          >
            移除
          </van-button>
        </article>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import http from '@/api/http'

type Member = { id: number; name: string; mobile?: string | null }
type Hit = Member & {
  status: 'available' | 'in_team' | 'other_team'
  team_name?: string | null
  can_join: boolean
}

const loading = ref(true)
const searching = ref(false)
const keyword = ref('')
const team = ref<any>(null)
const hits = ref<Hit[]>([])
const busyId = ref<number | null>(null)

const members = computed<Member[]>(() => team.value?.members || [])
const orderedMembers = computed<Member[]>(() => {
  const leaderId = team.value?.leader_worker_id
  return [...members.value].sort((a, b) => Number(b.id === leaderId) - Number(a.id === leaderId))
})

function initials(name: string) {
  return name.trim().slice(0, 1) || '员'
}

function clearSearch() {
  keyword.value = ''
  hits.value = []
}

async function loadTeam() {
  loading.value = true
  try {
    const res: any = await http.get('/teams/mine')
    const items = res.data?.items || []
    team.value = items[0] || null
  } catch {
    team.value = null
  } finally {
    loading.value = false
  }
}

async function onSearch() {
  const q = keyword.value.trim()
  if (!q || !team.value) {
    hits.value = []
    return
  }
  searching.value = true
  try {
    const res: any = await http.get('/teams/mine/candidates', {
      params: { q, team_id: team.value.id },
    })
    hits.value = res.data?.items || []
  } catch {
    hits.value = []
  } finally {
    searching.value = false
  }
}

async function addMember(w: Hit) {
  if (!team.value) return
  busyId.value = w.id
  try {
    const res: any = await http.post('/teams/mine/members', {
      worker_id: w.id,
      team_id: team.value.id,
    })
    team.value = res.data
    showToast(`已加入 ${w.name}`)
    await onSearch()
  } finally {
    busyId.value = null
  }
}

async function removeMember(w: Member) {
  if (!team.value) return
  await showConfirmDialog({
    title: '移除组员',
    message: `将 ${w.name} 移出「${team.value.name}」？`,
  })
  busyId.value = w.id
  try {
    const res: any = await http.delete(`/teams/mine/members/${w.id}`, {
      params: { team_id: team.value.id },
    })
    team.value = res.data
    showToast(`已移除 ${w.name}`)
    if (keyword.value.trim()) await onSearch()
  } finally {
    busyId.value = null
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!keyword.value.trim()) {
    hits.value = []
    return
  }
  searchTimer = setTimeout(() => {
    void onSearch()
  }, 280)
})

onMounted(loadTeam)
</script>

<style scoped>
.team-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 96px;
  margin: 4px 0 18px;
  padding: 16px 18px;
  border: 1px solid rgba(0, 118, 255, 0.08);
  border-left: 4px solid var(--ws-primary);
  border-radius: var(--ws-radius);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(245, 249, 255, 0.92));
  box-shadow: var(--ws-shadow-soft);
}

.team-head__copy {
  min-width: 0;
}

.team-head__eyebrow,
.member-search__label {
  margin-bottom: 3px;
  color: var(--ws-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.team-head__name {
  font-family: var(--ws-font-display);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ws-ink);
}

.team-head__count {
  display: grid;
  flex: 0 0 auto;
  width: 54px;
  height: 54px;
  place-content: center;
  border-radius: 14px;
  background: var(--ws-primary-soft);
  color: var(--ws-primary);
  text-align: center;
}

.team-head__count strong {
  font-family: var(--ws-font-num);
  font-size: 20px;
  line-height: 1;
}

.team-head__count span {
  margin-top: 3px;
  font-size: 10px;
  font-weight: 600;
}

.member-search {
  margin-bottom: 18px;
}

.member-search__label {
  margin-left: 4px;
  color: var(--ws-muted);
}

.member-search__field {
  margin-bottom: 0;
  border: 1px solid transparent;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.member-search__field:focus-within,
.member-search__field--active {
  border-color: rgba(0, 118, 255, 0.2);
  box-shadow: 0 0 0 4px rgba(0, 118, 255, 0.07), var(--ws-shadow-soft);
}

.member-search__field:focus-within .h5-filter__icon,
.member-search__field--active .h5-filter__icon {
  color: var(--ws-primary);
}

.search-state {
  margin: -8px 4px 18px;
  color: var(--ws-muted);
  font-size: 13px;
}

.people {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 16px;
}

.person {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 0;
  padding: 14px 16px;
}

.person--leader {
  background: linear-gradient(90deg, rgba(0, 118, 255, 0.055), var(--ws-bg-elevated) 44%);
}

.person__avatar {
  display: grid;
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 50%;
  background: rgba(0, 118, 255, 0.1);
  color: var(--ws-primary);
  font-size: 15px;
  font-weight: 700;
}

.person__avatar--leader {
  background: var(--ws-primary);
  color: #fff;
}

.person__main {
  min-width: 0;
  flex: 1;
}

.person__name {
  font-weight: 650;
  color: var(--ws-ink);
}

.person__hint {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ws-muted);
}

.availability-tag {
  display: inline-flex;
  align-items: center;
  margin-left: 6px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.2;
  vertical-align: 1px;
}

.leader-tag {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ws-primary);
  background: rgba(0, 118, 255, 0.1);
  border-radius: 999px;
  padding: 1px 7px;
}

.member-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 22px 4px 8px;
}

.member-list-head .h5-section-label {
  margin: 0;
}

.member-list-head > span {
  color: var(--ws-muted);
  font-family: var(--ws-font-num);
  font-size: 12px;
  font-weight: 600;
}

.person :deep(.van-button) {
  flex: 0 0 auto;
  min-width: 56px;
  height: 36px;
  padding: 0 12px;
  border-color: rgba(255, 59, 48, 0.24);
  color: rgba(215, 0, 21, 0.75);
}

.person :deep(.van-button--primary:not(.van-button--plain)) {
  background: var(--ws-primary);
  color: #fff;
}
</style>
