<template>
  <BuilderFrame :breadcrumbs="[{ label: '桌面设置' }]">
    <main class="desktop-settings-page">
      <div class="desktop-settings-content">
        <header class="desktop-settings-header">
          <h1>桌面设置</h1>
          <p>管理登录服务并查看本地运行目录。</p>
        </header>

        <div v-if="loading" class="desktop-settings-loading" aria-live="polite">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>读取桌面配置</span>
        </div>

        <el-alert
          v-else-if="loadError"
          type="error"
          :closable="false"
          show-icon
          :title="loadError"
        />

        <div v-else class="desktop-settings-form">
          <section class="desktop-settings-section">
            <div class="desktop-settings-section-copy">
              <h2>登录服务</h2>
              <p>保存后将退出当前会话，并由桌面启动流程重启本地服务。</p>
            </div>

            <div class="desktop-service-options" role="radiogroup" aria-label="登录模式">
              <button
                v-for="service in loginServices"
                :key="service.mode"
                type="button"
                class="desktop-service-option"
                :class="{ selected: service.mode === mode }"
                :disabled="saving"
                role="radio"
                :aria-checked="service.mode === mode"
                @click="selectService(service)"
              >
                {{ service.label }}
              </button>
            </div>

            <el-form label-position="top" class="desktop-field-form">
              <el-form-item label="服务地址" :error="urlTouched ? urlError : ''">
                <el-input
                  v-model="baseUrl"
                  :disabled="saving"
                  autocomplete="url"
                  placeholder="https://example.com"
                  @input="rememberServiceUrl"
                  @blur="urlTouched = true"
                />
              </el-form-item>
            </el-form>
          </section>

          <section class="desktop-settings-section">
            <div class="desktop-settings-section-copy">
              <h2>本地存储</h2>
              <p>本地根目录由首次初始化确定，此处不提供编辑或迁移操作。</p>
            </div>

            <el-form label-position="top" class="desktop-field-form">
              <el-form-item label="本地根目录">
                <el-input :model-value="rootDir" readonly />
              </el-form-item>
            </el-form>

            <div class="desktop-path-actions">
              <el-button
                :icon="FolderOpened"
                native-type="button"
                :loading="openingPath === 'root'"
                :disabled="saving || Boolean(openingPath)"
                @click="openPath('root')"
              >
                打开根目录
              </el-button>
              <el-button
                :icon="Document"
                native-type="button"
                :loading="openingPath === 'logs'"
                :disabled="saving || Boolean(openingPath)"
                @click="openPath('logs')"
              >
                打开日志目录
              </el-button>
            </div>
          </section>

          <p v-if="operationError" class="desktop-settings-error" aria-live="polite">
            {{ operationError }}
          </p>

          <footer class="desktop-settings-actions">
            <el-button
              type="primary"
              :loading="saving"
              :disabled="saving || Boolean(urlError)"
              @click="saveLoginSettings"
            >
              保存并重新登录
            </el-button>
          </footer>
        </div>
      </div>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Document, FolderOpened, Loading } from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { useUserStore } from '@/stores/user'
import {
  DESKTOP_LOGIN_SERVICES,
  getDesktopState,
  openDesktopPath,
  updateDesktopLogin,
  type DesktopLoginMode,
  type DesktopLoginServiceOption,
  type DesktopPathKind,
} from '@/utils/desktop'

const user = useUserStore()
const loginServices = DESKTOP_LOGIN_SERVICES.filter(service => (
  service.enabled && (service.mode === 'control_plane' || service.mode === 'apaas')
))
const mode = ref<DesktopLoginMode>('control_plane')
const baseUrl = ref('')
const rootDir = ref('')
const loading = ref(true)
const saving = ref(false)
const openingPath = ref<DesktopPathKind | null>(null)
const loadError = ref('')
const operationError = ref('')
const urlTouched = ref(false)
const serviceUrls: Record<DesktopLoginMode, string> = {
  control_plane: DESKTOP_LOGIN_SERVICES.find(service => service.mode === 'control_plane')?.defaultUrl || '',
  apaas: DESKTOP_LOGIN_SERVICES.find(service => service.mode === 'apaas')?.defaultUrl || '',
}

const urlError = computed(() => validateServiceUrl(baseUrl.value))

function validateServiceUrl(value: string): string {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol)
      || !url.hostname
      || url.username
      || url.password
      || url.hash) {
      return '请输入无凭据、无 fragment 的 HTTP(S) 绝对 URL'
    }
    return ''
  } catch {
    return '请输入有效的 HTTP(S) 绝对 URL'
  }
}

function selectService(service: DesktopLoginServiceOption) {
  if (service.mode !== 'control_plane' && service.mode !== 'apaas') return
  serviceUrls[mode.value] = baseUrl.value
  mode.value = service.mode
  baseUrl.value = serviceUrls[service.mode]
  urlTouched.value = false
  operationError.value = ''
}

function rememberServiceUrl(value: string) {
  serviceUrls[mode.value] = value
  operationError.value = ''
}

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  try {
    const snapshot = await getDesktopState()
    if (!snapshot.config) {
      loadError.value = '桌面配置尚未完成，请先完成首次初始化'
      return
    }
    mode.value = snapshot.config.login.mode
    baseUrl.value = snapshot.config.login.base_url
    serviceUrls[mode.value] = baseUrl.value
    rootDir.value = snapshot.config.root_dir || snapshot.default_root_dir
  } catch {
    loadError.value = '无法读取桌面配置，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function openPath(kind: DesktopPathKind) {
  openingPath.value = kind
  operationError.value = ''
  try {
    await openDesktopPath(kind)
  } catch {
    operationError.value = kind === 'root' ? '无法打开本地根目录' : '无法打开日志目录'
  } finally {
    openingPath.value = null
  }
}

async function saveLoginSettings() {
  urlTouched.value = true
  if (urlError.value || saving.value) return

  saving.value = true
  operationError.value = ''
  try {
    user.logout()
    await updateDesktopLogin({
      mode: mode.value,
      base_url: baseUrl.value.trim(),
    })
  } catch {
    operationError.value = '无法保存登录服务，请重新登录后再试'
    saving.value = false
  }
}

onMounted(() => {
  void loadSettings()
})
</script>

<style scoped>
.desktop-settings-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 32px 28px 48px;
  color: var(--text);
  background: var(--bg);
}

.desktop-settings-content {
  width: min(760px, 100%);
  margin: 0 auto;
}

.desktop-settings-header h1,
.desktop-settings-header p,
.desktop-settings-section-copy h2,
.desktop-settings-section-copy p,
.desktop-settings-error {
  margin: 0;
}

.desktop-settings-header h1 {
  font-size: 22px;
  line-height: 30px;
  font-weight: 650;
  letter-spacing: 0;
}

.desktop-settings-header p,
.desktop-settings-section-copy p {
  margin-top: 4px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 18px;
}

.desktop-settings-loading {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}

.desktop-settings-form {
  margin-top: 28px;
  border-top: 1px solid var(--line);
}

.desktop-settings-section {
  padding: 24px 0;
  border-bottom: 1px solid var(--line);
}

.desktop-settings-section-copy h2 {
  font-size: 15px;
  line-height: 22px;
  font-weight: 650;
  letter-spacing: 0;
}

.desktop-service-options {
  width: min(360px, 100%);
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
}

.desktop-service-option {
  min-height: 34px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.desktop-service-option:hover:not(:disabled) {
  color: var(--brand);
}

.desktop-service-option.selected {
  color: var(--brand);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.desktop-service-option:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 1px;
}

.desktop-service-option:disabled {
  cursor: wait;
  opacity: 0.6;
}

.desktop-field-form {
  width: min(560px, 100%);
  margin-top: 16px;
}

.desktop-field-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.desktop-path-actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.desktop-settings-error {
  margin-top: 16px;
  color: var(--danger, #ef4444);
  font-size: 12px;
  line-height: 18px;
}

.desktop-settings-actions {
  padding-top: 20px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 640px) {
  .desktop-settings-page {
    padding: 24px 18px 36px;
  }

  .desktop-settings-actions :deep(.el-button) {
    width: 100%;
  }
}
</style>
