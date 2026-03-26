<template>
  <el-dialog
    v-model="visible"
    title="选择部署环境"
    width="500px"
    :close-on-click-modal="false"
    class="env-select-dialog"
  >
    <p class="env-select-hint">请选择将应用部署到哪个平台环境：</p>

    <div class="env-list" v-if="envs.length > 0">
      <div
        v-for="env in envs"
        :key="env.id"
        class="env-option"
        :class="{ selected: selected === env.id, disabled: env.status !== 'connected' }"
        @click="env.status === 'connected' && (selected = env.id)"
      >
        <div class="env-status-dot" :class="env.status"></div>
        <div class="env-detail">
          <div class="env-name">
            {{ env.env_name }}
            <span v-if="env.is_default" class="default-tag">默认</span>
          </div>
          <div class="env-url">{{ env.base_url }}</div>
        </div>
        <div v-if="selected === env.id" class="env-check">&#10003;</div>
      </div>
    </div>

    <div v-if="loading" class="no-env">加载中...</div>
    <div v-else-if="envs.length === 0" class="no-env">
      还没有配置环境，<button class="link-btn" @click="goToEnvs">去添加</button>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!selected" @click="confirm">确认</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'

const router = useRouter()

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{
  (e: 'selected', envId: number): void
}>()

const envs = ref<PlatformEnv[]>([])
const selected = ref<number | null>(null)
const loading = ref(false)

async function loadEnvs() {
  loading.value = true
  try {
    const list = await platformEnvApi.list()
    envs.value = Array.isArray(list) ? list : []
    // Auto-select default env
    const defaultEnv = envs.value.find(e => e.is_default && e.status === 'connected')
    if (defaultEnv) {
      selected.value = defaultEnv.id
    } else {
      const firstConnected = envs.value.find(e => e.status === 'connected')
      if (firstConnected) selected.value = firstConnected.id
    }
  } catch {
    envs.value = []
  }
  loading.value = false
}

watch(visible, (val) => {
  if (val) {
    selected.value = null
    loadEnvs()
  }
})

function confirm() {
  if (selected.value) {
    emit('selected', selected.value)
    visible.value = false
  }
}

function goToEnvs() {
  visible.value = false
  router.push('/platform-envs')
}
</script>

<style scoped>
.env-select-hint {
  color: var(--t-text-secondary);
  font-size: 13px;
  margin: 0 0 16px;
}

.env-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.env-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}
.env-option:hover:not(.disabled) {
  background: var(--t-bg-panel-hover);
  border-color: var(--t-brand-glow);
}
.env-option.selected {
  border-color: var(--t-brand);
  background: var(--t-brand-subtle);
}
.env-option.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.env-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.env-status-dot.connected {
  background: var(--t-success);
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.4);
}
.env-status-dot.disconnected {
  background: rgba(255, 255, 255, 0.3);
}

.env-detail {
  flex: 1;
  min-width: 0;
}

.env-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--t-text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.default-tag {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  font-weight: 500;
}

.env-url {
  font-size: 12px;
  color: var(--t-text-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-check {
  color: var(--t-brand);
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}

.no-env {
  text-align: center;
  color: var(--t-text-muted);
  font-size: 13px;
  padding: 32px 0;
}

.link-btn {
  background: none;
  border: none;
  color: var(--t-brand-light);
  cursor: pointer;
  font-size: 13px;
  text-decoration: underline;
  padding: 0;
}
.link-btn:hover {
  color: var(--t-brand-light);
}

/* Scrollbar */
.env-list::-webkit-scrollbar {
  width: 5px;
}
.env-list::-webkit-scrollbar-track {
  background: transparent;
}
.env-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
}
</style>

<style>
.el-dialog.env-select-dialog {
  background: var(--t-bg-panel) !important;
  color: var(--t-text-primary);
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
}
.el-dialog.env-select-dialog .el-dialog__header {
  border-bottom: 1px solid var(--t-border-subtle);
  padding: 16px 20px;
}
.el-dialog.env-select-dialog .el-dialog__title {
  color: var(--t-text-primary) !important;
  font-size: 15px;
  font-weight: 600;
}
.el-dialog.env-select-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--t-text-muted);
}
.el-dialog.env-select-dialog .el-dialog__body {
  padding: 20px;
}
.el-dialog.env-select-dialog .el-dialog__footer {
  border-top: 1px solid var(--t-border-subtle);
  padding: 14px 20px;
}
</style>
