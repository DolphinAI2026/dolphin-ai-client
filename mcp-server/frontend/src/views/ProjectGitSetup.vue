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

    <BaseDialog
      :visible="disconnectDialogVisible"
      title="断开 Git 连接"
      message="确定要断开 git 连接吗？已初始化的 repo 不会被删除。"
      dangerous
      confirm-text="断开"
      @confirm="confirmDisconnect"
      @cancel="disconnectDialogVisible = false"
    />

    <BaseDialog
      :visible="oauthDialogVisible"
      :title="oauthDialogTitle"
      confirm-text="继续"
      @confirm="confirmOauthDialog"
      @cancel="cancelOauthDialog"
    >
      <div class="oauth-dialog-body">
        <label>
          {{ oauthOrgLabel }}
          <input v-model="oauthOrgInput" type="text" :placeholder="oauthOrgPlaceholder" />
        </label>
        <label v-if="oauthDialogProvider === 'gitlab'">
          GitLab Host（自建实例填完整 URL；公网 GitLab 留空）
          <input v-model="oauthHostInput" type="text" placeholder="https://gitlab.example.com" />
        </label>
      </div>
    </BaseDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/utils/request'
import { projectsApi, type Project } from '@/api/projects'
import { applicationApi } from '@/api/application'
import { gitConnectionApi, type GitConnection, type ConnectGitPATRequest } from '@/api/gitConnection'
import type { MergedApplication } from '@/types'
import BaseDialog from '@/components/BaseDialog.vue'

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

// Phase F Task 12b: BaseDialog 替原生 confirm
const disconnectDialogVisible = ref(false)
function onDisconnect() {
  disconnectDialogVisible.value = true
}
async function confirmDisconnect() {
  disconnectDialogVisible.value = false
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

// Phase F Task 12b: BaseDialog 替原生 prompt（OAuth org/host 输入）
const oauthDialogVisible = ref(false)
const oauthDialogProvider = ref<'github' | 'gitlab'>('github')
const oauthOrgInput = ref('')
const oauthHostInput = ref('')
const oauthDialogTitle = computed(() =>
  oauthDialogProvider.value === 'github' ? 'GitHub OAuth 连接' : 'GitLab OAuth 连接',
)
const oauthOrgLabel = computed(() =>
  oauthDialogProvider.value === 'github'
    ? 'GitHub Org/Username（OAuth 完成后将作为 group_id_or_org 写入连接）'
    : 'GitLab Group path（OAuth 完成后将作为 group_id_or_org 写入连接）',
)
const oauthOrgPlaceholder = computed(() =>
  oauthDialogProvider.value === 'github' ? 'my-org 或 my-username' : 'mygroup/subgroup',
)

function oauthConnect(provider: 'github' | 'gitlab') {
  oauthError.value = ''
  oauthDialogProvider.value = provider
  oauthOrgInput.value = ''
  oauthHostInput.value = ''
  oauthDialogVisible.value = true
}

function cancelOauthDialog() {
  oauthDialogVisible.value = false
}

async function confirmOauthDialog() {
  const provider = oauthDialogProvider.value
  const groupOrOrg = oauthOrgInput.value.trim()
  if (!groupOrOrg) return
  const host = provider === 'gitlab' ? (oauthHostInput.value.trim() || null) : null
  oauthDialogVisible.value = false

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
/* v3 redesign · 2026-05-20 — token migration, template/script untouched.
   Legacy v2 alias chain (--bg-base / --bg-panel / --bg-inset / --fg /
   --fg-muted / --fg-on-ink / --t-success / --t-warning / --t-danger /
   --b-mono) → v3 (--surface / --surface-2 / --text / --text-3 /
   --ok / --warn / --err / --font-mono). Replaced raw rgba(0,0,0,0.06)
   with --surface-3. Added :focus-visible rings on all clickables.
*/
.oauth-dialog-body { display: flex; flex-direction: column; gap: 12px; min-width: 360px; }
.oauth-dialog-body label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-2); font-weight: var(--fw-medium, 500); }
.oauth-dialog-body input {
  padding: 6px 8px;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  font-size: 13px;
  font-family: inherit;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.oauth-dialog-body input:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }

.git-setup {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans, inherit);
}

.gs-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: 10;
}

.back-btn {
  width: 36px; height: 36px;
  border-radius: var(--r-3, 8px);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.back-btn:hover { background: var(--brand-soft); border-color: var(--brand-ring); color: var(--brand); }
.back-btn:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 2px; }

.hd-info { min-width: 0; }
.hd-title { font-size: 18px; font-weight: var(--fw-semibold, 600); margin: 0; color: var(--text); letter-spacing: -0.005em; }
.hd-sub { font-size: 12px; color: var(--text-3); margin: 2px 0 0; }

.gs-scroll { flex: 1; overflow-y: auto; padding: 24px; }
.gs-content { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }

.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 20px 22px;
  box-shadow: var(--sh-1);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-head h2 { font-size: 15px; font-weight: var(--fw-semibold, 600); margin: 0; color: var(--text); letter-spacing: -0.005em; }

.conn-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: var(--r-full, 12px);
  font-weight: var(--fw-medium, 500);
}
.conn-pill.connected { color: var(--ok); background: var(--ok-soft); }
.conn-pill.disconnected { color: var(--text-3); background: var(--surface-2); }
.pill-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.kv-grid { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.kv-row { display: grid; grid-template-columns: 120px 1fr; gap: 12px; font-size: 13px; }
.kv-row label { color: var(--text-3); font-weight: var(--fw-medium, 500); }
.kv-row span { color: var(--text); word-break: break-all; }

.form-grid { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { font-size: 12px; color: var(--text-3); font-weight: var(--fw-medium, 500); }
.form-row input,
.form-row select {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.form-row input:focus,
.form-row select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}

.form-actions, .card-actions { margin-top: 8px; display: flex; gap: 8px; }

.btn {
  padding: 7px 14px;
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.btn:hover:not(:disabled) { background: var(--brand-soft); border-color: var(--brand-ring); color: var(--brand); }
.btn:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 2px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--brand); border-color: var(--brand); color: var(--text-inverse, #fff); }
.btn-primary:hover:not(:disabled) { background: var(--brand-hover); border-color: var(--brand-hover); color: var(--text-inverse, #fff); }
.btn-danger { background: transparent; border-color: var(--err); color: var(--err); }
.btn-danger:hover:not(:disabled) { background: var(--err-soft); border-color: var(--err); color: var(--err); }
.btn-ghost { background: transparent; border-color: transparent; color: var(--text-3); }
.btn-ghost:hover:not(:disabled) { color: var(--brand); background: var(--brand-soft); }

.apps-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.apps-table th, .apps-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  font-size: 13px;
}
.apps-table th { color: var(--text-3); font-weight: var(--fw-medium, 500); background: var(--surface-2); }
.apps-table td { color: var(--text); }
.apps-table td strong { color: var(--text); font-weight: var(--fw-semibold, 600); }
.apps-table .ta-right { text-align: right; }

.link-mono {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  color: var(--brand);
  text-decoration: none;
  word-break: break-all;
  font-size: var(--t-mono, 12px);
}
.link-mono:hover { text-decoration: underline; color: var(--brand-hover); }

.state-pill {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--r-3, 8px);
  font-weight: var(--fw-medium, 500);
}
.state-pill.ok { color: var(--ok); background: var(--ok-soft); }
.state-pill.pending { color: var(--warn); background: var(--warn-soft); }

.muted { color: var(--text-3); }
.small { font-size: 12px; }
.error-text { color: var(--err); font-size: 12px; margin-top: 8px; }
.hint { color: var(--warn); font-size: 12px; margin-top: 12px; }

.oauth-section {
  margin: 12px 0 16px;
  padding: 14px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring);
  border-radius: var(--r-3, 8px);
}
.section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: -0.005em;
}
.oauth-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.oauth-section .hint {
  margin-top: 8px;
  color: var(--text-3);
}
.oauth-section .hint code {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  background: var(--surface);
  border: 1px solid var(--line);
  padding: 1px 4px;
  border-radius: var(--r-1, 3px);
  font-size: 11px;
  color: var(--text);
}

.pat-section {
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  padding: 0 12px;
}
.pat-section > summary {
  cursor: pointer;
  padding: 10px 0;
  font-size: 13px;
  color: var(--text-3);
  user-select: none;
  font-weight: var(--fw-medium, 500);
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.pat-section > summary:hover { color: var(--brand); }
.pat-section[open] > summary {
  border-bottom: 1px solid var(--line);
  margin-bottom: 8px;
  color: var(--text);
}
.pat-section .form-grid { padding-bottom: 12px; }
</style>
