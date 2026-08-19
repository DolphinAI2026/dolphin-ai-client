<template>
  <WorkbenchShell>
    <main class="tenant-git-page">
      <header class="page-header">
        <div>
          <span class="eyebrow">系统配置</span>
          <h1>Git 平台连接</h1>
          <p>当前组织的默认连接。系统助手会用它在指定 Git 组中创建、绑定并推送系统资产仓库。</p>
        </div>
        <button class="ghost-button" type="button" @click="router.push('/settings?section=system')">返回设置</button>
      </header>

      <section class="connection-card">
        <div class="card-heading">
          <div>
            <h2>默认连接</h2>
            <p>令牌只以加密形式保存，配置后不会再显示。</p>
          </div>
          <span class="status" :class="connection ? 'connected' : 'empty'">{{ connection ? '已连接' : '未配置' }}</span>
        </div>

        <div v-if="loading" class="muted">正在读取配置…</div>
        <template v-else-if="connection">
          <dl class="summary-grid">
            <div><dt>平台</dt><dd>{{ providerLabel(connection.provider) }}</dd></div>
            <div><dt>地址</dt><dd>{{ connection.host }}</dd></div>
            <div><dt>{{ connection.provider === 'gitlab' ? 'GitLab Group' : 'GitHub Organization' }}</dt><dd>{{ connection.group_id_or_org }}</dd></div>
          </dl>
          <div class="notice">系统助手将优先使用这条租户默认连接；项目可继续保留各自独立的 Git 连接。</div>
        </template>

        <form class="connection-form" @submit.prevent="save">
          <h3>{{ connection ? '更新默认连接' : '配置默认连接' }}</h3>
          <div class="form-grid">
            <label>Git 平台
              <select v-model="form.provider">
                <option value="gitlab">GitLab</option>
                <option value="github">GitHub</option>
              </select>
            </label>
            <label>服务地址
              <input v-model.trim="form.host" required :placeholder="form.provider === 'gitlab' ? 'https://gitlab.example.com' : 'https://github.com'">
            </label>
            <label>{{ form.provider === 'gitlab' ? 'GitLab Group 路径' : 'GitHub Organization' }}
              <input v-model.trim="form.group_id_or_org" required :placeholder="form.provider === 'gitlab' ? 'platform/capabilities' : 'my-organization'">
            </label>
            <label>Personal Access Token
              <input v-model="form.access_token" type="password" required placeholder="保存后不会展示；需具备建仓和推送权限">
            </label>
          </div>
          <p class="form-help">GitLab 建议使用具备 API、write_repository 权限的 Token；GitHub 需能在目标 Organization 建仓并写入。</p>
          <p v-if="error" class="error">{{ error }}</p>
          <div class="actions">
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : connection ? '更新连接' : '保存连接' }}</button>
            <button v-if="connection" class="danger-button" type="button" :disabled="saving || deleting" @click="remove">{{ deleting ? '删除中…' : '移除连接' }}</button>
          </div>
        </form>
      </section>
    </main>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { gitConnectionApi, type ConnectGitPATRequest, type TenantGitConnection } from '@/api/gitConnection'

const router = useRouter()
const connection = ref<TenantGitConnection | null>(null)
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const error = ref('')
const form = reactive<ConnectGitPATRequest>({ provider: 'gitlab', host: '', group_id_or_org: '', access_token: '' })

function providerLabel(provider: string) { return provider === 'gitlab' ? 'GitLab' : 'GitHub' }
function messageOf(error: any) { return error?.response?.data?.detail || error?.message || '保存失败，请检查连接信息后重试' }

async function load() {
  loading.value = true
  try {
    connection.value = await gitConnectionApi.getTenant()
    if (connection.value) {
      form.provider = connection.value.provider
      form.host = connection.value.host
      form.group_id_or_org = connection.value.group_id_or_org
    }
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    loading.value = false
  }
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    connection.value = await gitConnectionApi.connectTenant({ ...form })
    form.access_token = ''
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    saving.value = false
  }
}

async function remove() {
  error.value = ''
  deleting.value = true
  try {
    await gitConnectionApi.disconnectTenant()
    connection.value = null
    form.access_token = ''
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.tenant-git-page { min-height: 100%; padding: 34px clamp(20px, 4vw, 56px) 56px; background: var(--bg, #f8fafc); color: var(--text); }
.page-header, .connection-card { width: min(820px, 100%); margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 24px; }
.eyebrow { color: var(--brand); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 5px 0 7px; font-size: 26px; line-height: 1.2; } .page-header p { max-width: 620px; margin: 0; color: var(--text-3); font-size: 13px; line-height: 1.7; }
.connection-card { padding: 24px; border: 1px solid var(--line); border-radius: var(--r-4, 12px); background: var(--surface); box-shadow: var(--sh-1); }
.card-heading { display: flex; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line); padding-bottom: 18px; } .card-heading h2 { margin: 0; font-size: 16px; } .card-heading p, .muted { margin: 6px 0 0; color: var(--text-3); font-size: 12px; }
.status { align-self: start; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; } .status.connected { color: var(--ok); background: var(--ok-soft); } .status.empty { color: var(--text-3); background: var(--surface-2); }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 18px 0; } .summary-grid div { min-width: 0; } dt { color: var(--text-3); font-size: 11px; } dd { margin: 5px 0 0; color: var(--text); font-size: 13px; overflow-wrap: anywhere; }
.notice { margin: 0 0 20px; padding: 10px 12px; color: var(--text-2); background: var(--brand-soft); border-radius: var(--r-2, 6px); font-size: 12px; line-height: 1.6; }
.connection-form { margin-top: 20px; } .connection-form h3 { margin: 0 0 14px; font-size: 14px; } .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; } label { display: grid; gap: 6px; color: var(--text-2); font-size: 12px; font-weight: 500; }
input, select { min-width: 0; padding: 8px 10px; color: var(--text); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-2, 6px); font: inherit; } input:focus, select:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.form-help { margin: 12px 0; color: var(--text-3); font-size: 12px; line-height: 1.6; }.error { margin: 12px 0; color: var(--err); font-size: 12px; }.actions { display: flex; gap: 8px; }.primary-button, .danger-button, .ghost-button { border: 1px solid var(--line); border-radius: var(--r-2, 6px); padding: 8px 13px; cursor: pointer; font: inherit; font-size: 13px; }.primary-button { color: var(--text-inverse, #fff); background: var(--brand); border-color: var(--brand); }.danger-button { color: var(--err); background: transparent; border-color: var(--err); }.ghost-button { color: var(--text-2); background: var(--surface); }.primary-button:disabled, .danger-button:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 680px) { .page-header { flex-direction: column; }.summary-grid, .form-grid { grid-template-columns: 1fr; } }
</style>
