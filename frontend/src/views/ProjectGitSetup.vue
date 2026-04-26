<template>
  <div class="git-setup">
    <header class="gs-header">
      <button class="back-btn" @click="goBack" title="返回 Project Overview">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div class="hd-info">
        <h1 class="hd-title">{{ project?.name || '加载中...' }}</h1>
        <p class="hd-sub">Git 集成（PAT 模式）</p>
      </div>
    </header>

    <div class="gs-scroll">
      <div class="gs-content">
        <!-- 卡片 1：连接状态 -->
        <section class="card">
          <div class="card-head">
            <h2>连接状态</h2>
            <span v-if="conn" class="conn-pill connected">
              <span class="pill-dot"></span> 已连接
            </span>
            <span v-else class="conn-pill disconnected">
              <span class="pill-dot"></span> 未连接
            </span>
          </div>

          <div v-if="loadingConn" class="muted">正在加载连接状态…</div>

          <template v-else-if="conn">
            <div class="kv-grid">
              <div class="kv-row"><label>Provider</label><span>{{ conn.provider }}</span></div>
              <div class="kv-row"><label>Host</label><span>{{ conn.host }}</span></div>
              <div class="kv-row">
                <label>{{ conn.provider === 'gitlab' ? 'Group' : 'Org' }}</label>
                <span>{{ conn.group_id_or_org }}</span>
              </div>
              <div class="kv-row"><label>状态</label><span>{{ conn.status }}</span></div>
            </div>
            <div class="card-actions">
              <button class="btn btn-danger" :disabled="disconnecting" @click="onDisconnect">
                {{ disconnecting ? '处理中…' : '断开连接' }}
              </button>
            </div>
            <p v-if="connectError" class="error-text">{{ connectError }}</p>
          </template>

          <template v-else>
            <p class="muted small">尚未连接 git。推荐使用 OAuth 授权；自建 GitLab 或不便走 OAuth 的场景可用 PAT。</p>

            <div class="oauth-section">
              <h4 class="section-title">OAuth 连接（推荐）</h4>
              <div class="oauth-buttons">
                <button class="btn btn-primary" type="button" :disabled="oauthLoading" @click="oauthConnect('github')">
                  用 GitHub OAuth 连接
                </button>
                <button class="btn btn-primary" type="button" :disabled="oauthLoading" @click="oauthConnect('gitlab')">
                  用 GitLab OAuth 连接
                </button>
              </div>
              <p class="muted small hint">
                需后端配置 <code>GITHUB_CLIENT_ID</code> / <code>GITHUB_CLIENT_SECRET</code>
                或 <code>GITLAB_CLIENT_ID</code> / <code>GITLAB_CLIENT_SECRET</code> 环境变量
              </p>
              <p v-if="oauthError" class="error-text">{{ oauthError }}</p>
            </div>

            <details class="pat-section">
              <summary>或者用 Personal Access Token (PAT) 手动连接</summary>
              <form class="form-grid" @submit.prevent="onConnect">
                <div class="form-row">
                  <label>Provider</label>
                  <select v-model="form.provider" required>
                    <option value="gitlab">GitLab</option>
                    <option value="github">GitHub</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>Host</label>
                  <input v-model="form.host" required
                         :placeholder="form.provider === 'gitlab' ? 'https://gitlab.com' : 'https://api.github.com'" />
                </div>
                <div class="form-row">
                  <label>{{ form.provider === 'gitlab' ? 'Group ID 或 path' : 'Organization 名称' }}</label>
                  <input v-model="form.group_id_or_org" required
                         :placeholder="form.provider === 'gitlab' ? '例：my-group 或 1234' : '例：my-org'" />
                </div>
                <div class="form-row">
                  <label>Personal Access Token</label>
                  <input v-model="form.access_token" type="password" required
                         placeholder="只在创建/转发时使用，不会展示" />
                </div>
                <div class="form-actions">
                  <button type="submit" class="btn btn-primary" :disabled="connecting">
                    {{ connecting ? '连接中…' : '连接 git' }}
                  </button>
                </div>
                <p v-if="connectError" class="error-text">{{ connectError }}</p>
              </form>
            </details>
          </template>
        </section>

        <!-- 卡片 2：应用 repo 初始化 -->
        <section class="card">
          <div class="card-head">
            <h2>应用 repo 初始化</h2>
            <button class="btn btn-ghost" @click="loadApps" :disabled="loadingApps">刷新</button>
          </div>
          <p class="muted small">为该 project 下的应用在 git 平台创建 repo，并推首版 SPEC。</p>

          <div v-if="loadingApps" class="muted">正在加载应用列表…</div>
          <table v-else-if="apps.length" class="apps-table">
            <thead>
              <tr>
                <th>应用</th>
                <th>仓库 URL</th>
                <th>状态</th>
                <th class="ta-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="app in apps" :key="app.id">
                <td><strong>{{ app.app_name }}</strong></td>
                <td>
                  <a v-if="app.git_repo_url" :href="app.git_repo_url" target="_blank" class="link-mono">
                    {{ app.git_repo_url }}
                  </a>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <span v-if="app.git_repo_url" class="state-pill ok">已初始化</span>
                  <span v-else class="state-pill pending">未初始化</span>
                </td>
                <td class="ta-right">
                  <button v-if="!app.git_repo_url" class="btn btn-primary"
                          :disabled="!conn || initing[app.id]" @click="onInitRepo(app)">
                    {{ initing[app.id] ? '创建中…' : '为应用创建 repo' }}
                  </button>
                  <span v-else class="muted small">已就绪</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">该 project 下暂无应用。先去 Project Overview 创建应用，再回来初始化 repo。</p>

          <p v-if="!conn" class="hint">提示：未连接 git 时无法创建 repo，先在上方完成连接。</p>
          <p v-if="initError" class="error-text">{{ initError }}</p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/utils/request'
import { projectsApi, type Project } from '@/api/projects'
import { applicationApi } from '@/api/application'
import { gitConnectionApi, type GitConnection, type ConnectGitPATRequest } from '@/api/gitConnection'
import type { MergedApplication } from '@/types'

const route = useRoute()
const router = useRouter()

const projectId = Number(route.params.id)

const project = ref<Project | null>(null)
const conn = ref<GitConnection | null>(null)
const loadingConn = ref(true)
const connecting = ref(false)
const disconnecting = ref(false)
const connectError = ref('')

const apps = ref<MergedApplication[]>([])
const loadingApps = ref(true)
const initing = reactive<Record<string, boolean>>({})
const initError = ref('')

const oauthLoading = ref(false)
const oauthError = ref('')

const form = reactive<ConnectGitPATRequest>({
  provider: 'gitlab',
  host: '',
  access_token: '',
  group_id_or_org: '',
})

function goBack() {
  router.push(`/project/${projectId}`)
}

async function loadProject() {
  try {
    project.value = await projectsApi.get(projectId)
  } catch (e: any) {
    console.error(e)
  }
}

async function loadConnection() {
  loadingConn.value = true
  try {
    conn.value = await gitConnectionApi.get(projectId)
  } catch (e: any) {
    console.error(e)
    conn.value = null
  } finally {
    loadingConn.value = false
  }
}

async function loadApps() {
  loadingApps.value = true
  try {
    const list = await applicationApi.list({ include_remote: false })
    apps.value = (list as MergedApplication[]).filter(a => Number(a.project_id) === projectId)
  } catch (e: any) {
    console.error(e)
    apps.value = []
  } finally {
    loadingApps.value = false
  }
}

async function onConnect() {
  connectError.value = ''
  connecting.value = true
  try {
    conn.value = await gitConnectionApi.connectPAT(projectId, { ...form })
    form.access_token = ''
  } catch (e: any) {
    connectError.value = e?.response?.data?.detail || e?.message || '连接失败'
  } finally {
    connecting.value = false
  }
}

async function onDisconnect() {
  if (!confirm('确定要断开 git 连接吗？已初始化的 repo 不会被删除。')) return
  connectError.value = ''
  disconnecting.value = true
  try {
    await gitConnectionApi.disconnect(projectId)
    conn.value = null
  } catch (e: any) {
    connectError.value = e?.response?.data?.detail || e?.message || '断开失败（可能仅 owner 可断开）'
  } finally {
    disconnecting.value = false
  }
}

async function onInitRepo(app: MergedApplication) {
  initError.value = ''
  const appId = Number(app.id)
  if (!Number.isFinite(appId)) {
    initError.value = '应用 ID 不合法（远程应用无法 init）'
    return
  }
  initing[app.id] = true
  try {
    const res = await gitConnectionApi.initRepo(appId)
    app.git_repo_url = res.git_repo_url
  } catch (e: any) {
    initError.value = e?.response?.data?.detail || e?.message || '创建 repo 失败'
  } finally {
    initing[app.id] = false
  }
}

async function oauthConnect(provider: 'github' | 'gitlab') {
  oauthError.value = ''
  const promptLabel = provider === 'github'
    ? '输入 GitHub Org/Username（OAuth 完成后将作为 group_id_or_org 写入连接）'
    : '输入 GitLab Group path（OAuth 完成后将作为 group_id_or_org 写入连接）'
  const groupOrOrg = prompt(promptLabel)
  if (!groupOrOrg) return

  let host: string | null = null
  if (provider === 'gitlab') {
    host = prompt('GitLab Host（自建实例填完整 URL；公网 GitLab 留空）', '') || null
  }

  sessionStorage.setItem(`git-oauth-${provider}-org`, groupOrOrg)
  sessionStorage.setItem('git-oauth-project', String(projectId))
  if (host) {
    sessionStorage.setItem(`git-oauth-${provider}-host`, host)
  } else {
    sessionStorage.removeItem(`git-oauth-${provider}-host`)
  }

  oauthLoading.value = true
  try {
    const params: Record<string, string> = { provider }
    if (host) params.host = host
    const qs = new URLSearchParams(params).toString()
    const res = await request.get<any, { authorize_url: string }>(
      `/projects/${projectId}/git-oauth/start?${qs}`
    )
    if (!res?.authorize_url) {
      oauthError.value = 'OAuth start 未返回 authorize_url'
      oauthLoading.value = false
      return
    }
    window.location.href = res.authorize_url
    // 不重置 oauthLoading：本页面即将卸载
  } catch (e: any) {
    oauthError.value = e?.response?.data?.detail
      || e?.message
      || `OAuth start 失败：可能后端未配置 ${provider.toUpperCase()}_CLIENT_ID`
    oauthLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadProject(), loadConnection(), loadApps()])
})
</script>

<style scoped>
.git-setup {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-base, var(--t-bg-base));
  color: var(--fg, var(--t-text-primary));
}

.gs-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--line, var(--t-border-subtle));
  background: var(--bg-base, var(--t-bg-base));
  position: sticky;
  top: 0;
  z-index: 10;
}

.back-btn {
  width: 36px; height: 36px;
  border-radius: 8px;
  border: 1px solid var(--line, var(--t-border-subtle));
  background: transparent;
  color: var(--fg-muted, var(--t-text-secondary));
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.back-btn:hover { background: var(--bg-hover, var(--t-bg-elevated)); color: var(--fg, var(--t-text-primary)); }

.hd-info { min-width: 0; }
.hd-title { font-size: 18px; font-weight: 600; margin: 0; }
.hd-sub { font-size: 12px; color: var(--fg-muted, var(--t-text-muted)); margin: 2px 0 0; }

.gs-scroll { flex: 1; overflow-y: auto; padding: 24px; }
.gs-content { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }

.card {
  background: var(--bg-panel, var(--t-bg-panel));
  border: 1px solid var(--line, var(--t-border-subtle));
  border-radius: 12px;
  padding: 20px 22px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-head h2 { font-size: 15px; font-weight: 600; margin: 0; }

.conn-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  font-weight: 500;
}
.conn-pill.connected { color: var(--t-success); background: var(--t-success-subtle, rgba(16,185,129,0.1)); }
.conn-pill.disconnected { color: var(--fg-muted, var(--t-text-muted)); background: var(--bg-inset, var(--t-bg-subtle)); }
.pill-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.kv-grid { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.kv-row { display: grid; grid-template-columns: 120px 1fr; gap: 12px; font-size: 13px; }
.kv-row label { color: var(--fg-muted, var(--t-text-muted)); }
.kv-row span { color: var(--fg, var(--t-text-primary)); word-break: break-all; }

.form-grid { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { font-size: 12px; color: var(--fg-muted, var(--t-text-muted)); }
.form-row input,
.form-row select {
  background: var(--bg-inset, var(--t-bg-subtle));
  color: var(--fg, var(--t-text-primary));
  border: 1px solid var(--line, var(--t-border-subtle));
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
}
.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: var(--brand);
}

.form-actions, .card-actions { margin-top: 8px; display: flex; gap: 8px; }

.btn {
  padding: 7px 14px;
  border-radius: 6px;
  border: 1px solid var(--line, var(--t-border-subtle));
  background: var(--bg-panel, var(--t-bg-panel));
  color: var(--fg, var(--t-text-primary));
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.btn:hover:not(:disabled) { background: var(--bg-hover, var(--t-bg-elevated)); border-color: var(--brand); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--brand); border-color: var(--brand); color: var(--fg-on-ink, #fff); }
.btn-primary:hover:not(:disabled) { background: var(--brand); filter: brightness(1.05); }
.btn-danger { background: transparent; border-color: var(--t-danger); color: var(--t-danger); }
.btn-danger:hover:not(:disabled) { background: var(--t-danger-subtle, rgba(248,113,113,0.1)); }
.btn-ghost { background: transparent; border-color: transparent; color: var(--fg-muted, var(--t-text-muted)); }
.btn-ghost:hover:not(:disabled) { color: var(--fg, var(--t-text-primary)); }

.apps-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.apps-table th, .apps-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line, var(--t-border-subtle));
  text-align: left;
  font-size: 13px;
}
.apps-table th { color: var(--fg-muted, var(--t-text-muted)); font-weight: 500; background: var(--bg-inset, var(--t-bg-subtle)); }
.apps-table .ta-right { text-align: right; }

.link-mono {
  font-family: var(--b-mono, ui-monospace, SFMono-Regular, monospace);
  color: var(--brand);
  text-decoration: none;
  word-break: break-all;
}
.link-mono:hover { text-decoration: underline; }

.state-pill {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 8px;
  font-weight: 500;
}
.state-pill.ok { color: var(--t-success); background: var(--t-success-subtle, rgba(16,185,129,0.1)); }
.state-pill.pending { color: var(--t-warning); background: var(--t-warning-subtle, rgba(251,191,36,0.1)); }

.muted { color: var(--fg-muted, var(--t-text-muted)); }
.small { font-size: 12px; }
.error-text { color: var(--t-danger); font-size: 12px; margin-top: 8px; }
.hint { color: var(--t-warning); font-size: 12px; margin-top: 12px; }

.oauth-section {
  margin: 12px 0 16px;
  padding: 14px;
  background: var(--bg-inset, var(--t-bg-subtle));
  border-radius: 8px;
}
.section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg, var(--t-text-primary));
}
.oauth-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.oauth-section .hint {
  margin-top: 8px;
  color: var(--fg-muted, var(--t-text-muted));
}
.oauth-section .hint code {
  font-family: var(--b-mono, ui-monospace, SFMono-Regular, monospace);
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
}

.pat-section {
  margin-top: 8px;
  border: 1px solid var(--line, var(--t-border-subtle));
  border-radius: 8px;
  padding: 0 12px;
}
.pat-section > summary {
  cursor: pointer;
  padding: 10px 0;
  font-size: 13px;
  color: var(--fg-muted, var(--t-text-muted));
  user-select: none;
}
.pat-section[open] > summary {
  border-bottom: 1px solid var(--line, var(--t-border-subtle));
  margin-bottom: 8px;
  color: var(--fg, var(--t-text-primary));
}
.pat-section .form-grid { padding-bottom: 12px; }
</style>
