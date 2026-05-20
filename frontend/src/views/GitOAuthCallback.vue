<template>
  <div class="oauth-callback">
    <div class="cb-card">
      <h1>{{ titleText }}</h1>
      <p v-if="loading" class="muted">正在与后端交换 token…</p>
      <p v-else-if="error" class="error-text">{{ error }}</p>
      <p v-else class="muted">{{ successMessage }}</p>

      <div v-if="!loading" class="cb-actions">
        <button class="btn btn-primary" @click="goBack">返回 Project Git Setup</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/utils/request'

const route = useRoute()
const router = useRouter()

const provider = computed(() => String(route.params.provider || ''))
const loading = ref(true)
const error = ref('')
const successMessage = ref('')
const projectId = ref<number | null>(null)

const titleText = computed(() => {
  if (loading.value) return `正在完成 ${provider.value.toUpperCase()} OAuth…`
  if (error.value) return 'OAuth 失败'
  return 'OAuth 成功'
})

function goBack() {
  if (projectId.value) {
    router.push(`/project/${projectId.value}/git`)
  } else {
    router.push('/')
  }
}

onMounted(async () => {
  const code = route.query.code as string | undefined
  const state = route.query.state as string | undefined
  const oauthError = route.query.error as string | undefined

  if (oauthError) {
    error.value = `OAuth 提供方拒绝授权：${route.query.error_description || oauthError}`
    loading.value = false
    return
  }

  if (!code || !state) {
    error.value = '缺少 code 或 state 参数'
    loading.value = false
    return
  }

  const projectIdRaw = sessionStorage.getItem('git-oauth-project') || state
  const groupOrOrg = sessionStorage.getItem(`git-oauth-${provider.value}-org`) || ''
  const host = sessionStorage.getItem(`git-oauth-${provider.value}-host`) || undefined

  const projectIdNum = Number(projectIdRaw)
  if (!Number.isFinite(projectIdNum)) {
    error.value = 'project_id 不合法（sessionStorage 缺失或被清空？）'
    loading.value = false
    return
  }
  projectId.value = projectIdNum

  if (!groupOrOrg) {
    error.value = `未找到 group/org 缓存值（请回到 Project Git Setup 重新发起 OAuth）`
    loading.value = false
    return
  }

  try {
    const body: Record<string, any> = {
      provider: provider.value,
      code,
      state,
      group_id_or_org: groupOrOrg,
    }
    if (host) body.host = host
    await request.post(`/projects/${projectIdNum}/git-oauth/callback`, body)

    // 清缓存
    sessionStorage.removeItem('git-oauth-project')
    sessionStorage.removeItem(`git-oauth-${provider.value}-org`)
    sessionStorage.removeItem(`git-oauth-${provider.value}-host`)

    successMessage.value = `已成功连接 ${provider.value.toUpperCase()}，3 秒后回到 Project Git Setup…`
    loading.value = false
    setTimeout(() => goBack(), 3000)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'OAuth 回调失败'
    loading.value = false
  }
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Replaces v2 --bg-base/--bg-panel/--t-* tokens with v3 surface/text/r/sh tokens. */
.oauth-callback {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  padding: var(--s-6, 24px);
}
.cb-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: var(--s-8, 32px);
  max-width: 520px;
  width: 100%;
  color: var(--text);
  box-shadow: var(--sh-3);
}
.cb-card h1 {
  font-size: var(--t-h3, 18px);
  font-weight: var(--fw-semibold, 600);
  letter-spacing: -0.01em;
  margin: 0 0 var(--s-3, 12px);
}
.muted { color: var(--text-3); font-size: var(--t-body, 14px); line-height: 1.55; }
.error-text { color: var(--err); font-size: var(--t-body, 14px); line-height: 1.55; }
.cb-actions { margin-top: var(--s-5, 20px); }
.btn {
  padding: var(--s-2, 8px) var(--s-4, 16px);
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  font-family: inherit;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.btn:hover {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}
.btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
.btn-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
  box-shadow: var(--sh-brand);
}
.btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-inverse, #fff);
}
</style>
