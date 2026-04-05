<template>
  <WorkbenchShell>
    <div class="platform-shell-page">
      <TopBar title="辅助搭建" :show-home="true">
        <template #actions>
          <button class="shell-action-btn" @click="reloadPlatform">刷新</button>
        </template>
      </TopBar>

      <div class="platform-shell-body">
        <div v-if="platformError" class="shell-error">
          <p>{{ platformError }}</p>
          <button class="shell-retry-btn" @click="reloadPlatform">重新加载</button>
        </div>
        <iframe
          v-else-if="platformIframeUrl"
          ref="platformIframeRef"
          :src="platformIframeUrl"
          class="platform-shell-frame"
          frameborder="0"
          allow="clipboard-read; clipboard-write"
          @load="onPlatformIframeLoad"
          @error="onPlatformIframeError"
        ></iframe>
        <div v-else class="shell-loading">正在加载平台配置...</div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import TopBar from '@/components/TopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { buildPlatformProxyEntryUrl, repairPlatformIframe } from '@/utils/platformIframe'

const route = useRoute()
const userStore = useUserStore()

const platformIframeRef = ref<HTMLIFrameElement | null>(null)
const platformIframeUrl = ref('')
const platformError = ref('')
const repairTimer = ref<number | null>(null)

const appId = computed(() => {
  const value = Number(route.query.app_id || 0)
  return Number.isFinite(value) ? value : 0
})

const stopRepairTimer = () => {
  if (repairTimer.value !== null) {
    window.clearInterval(repairTimer.value)
    repairTimer.value = null
  }
}

const restorePlatformHeader = () => {
  const restored = repairPlatformIframe(platformIframeRef.value)
  if (!restored && platformIframeRef.value) {
    stopRepairTimer()
  }
}

const onPlatformIframeLoad = () => {
  stopRepairTimer()
  restorePlatformHeader()

  let attempts = 0
  repairTimer.value = window.setInterval(() => {
    attempts += 1
    restorePlatformHeader()
    if (attempts >= 24) {
      stopRepairTimer()
    }
  }, 500)
}

const loadPlatform = () => {
  stopRepairTimer()
  platformError.value = ''

  if (!appId.value) {
    platformIframeUrl.value = ''
    platformError.value = '缺少应用 ID，无法打开平台配置页'
    return
  }

  const token = userStore.token || localStorage.getItem('token') || ''
  platformIframeUrl.value = buildPlatformProxyEntryUrl(appId.value, token)
}

const reloadPlatform = () => {
  loadPlatform()
}

const onPlatformIframeError = () => {
  stopRepairTimer()
  platformError.value = '平台页面加载失败，请刷新后重试'
}

watch(() => route.query.app_id, () => {
  loadPlatform()
})

onMounted(() => {
  loadPlatform()
})

onBeforeUnmount(() => {
  stopRepairTimer()
})
</script>

<style scoped>
.platform-shell-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-base);
}

.platform-shell-body {
  flex: 1;
  min-height: 0;
  display: flex;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,248,255,0.98));
}

.platform-shell-frame {
  width: 100%;
  height: 100%;
  border: none;
  flex: 1;
  background: #fff;
}

.shell-loading,
.shell-error {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  color: var(--t-text-secondary);
  font-size: 14px;
}

.shell-action-btn,
.shell-retry-btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  border: 1px solid rgba(128, 145, 255, 0.16);
  background: rgba(248, 250, 255, 0.96);
  color: var(--t-text-primary);
  cursor: pointer;
  transition: all 0.18s ease;
}

.shell-action-btn:hover,
.shell-retry-btn:hover {
  background: rgba(241, 245, 255, 1);
  border-color: rgba(92, 115, 255, 0.22);
}

.shell-retry-btn {
  background: linear-gradient(135deg, #4f78ff, #6a7cff);
  color: #fff;
  border-color: transparent;
}
</style>
