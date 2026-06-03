<script setup lang="ts">
/**
 * WorkspaceIdeDrawer — 全屏内嵌 IDE 抽屉(code-server)。
 *
 * 用法(命令式):
 *   const ideDrawer = ref<InstanceType<typeof WorkspaceIdeDrawer>>()
 *   <WorkspaceIdeDrawer ref="ideDrawer" />
 *   ideDrawer.value?.openWorkspace(ws.id)
 *
 * 取代"跳 /coding 工作台"的旧入口:点工作区直接在当前页全屏打开它的 Web IDE,
 * 关掉即回原页面。逻辑复用 useIdeManager(加载/重试/主题/30s 超时)。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { codingApi } from '@/api/coding'
import { useIdeManager } from '@/views/coding/useIdeManager'

const open = ref(false)
const {
  ideUrl,
  ideLoaded,
  ideLoadError,
  ideLoadingText,
  setIdeUrl,
  onIdeFrameLoad,
  onIdeFrameError,
  retryIdeLoad,
} = useIdeManager()

/** 打开指定工作区的 Web IDE。先弹抽屉显示 loading,再取 ide_url。 */
async function openWorkspace(workspaceId: string, conversationId?: number | null) {
  if (!workspaceId) return
  open.value = true
  try {
    const res = await codingApi.getIdeUrl(workspaceId, conversationId ?? null)
    const url = res?.ide_url
    if (!url) {
      ElMessage.error('该工作区暂无可用的 Web IDE')
      open.value = false
      return
    }
    await setIdeUrl(url)
  } catch (e: any) {
    ElMessage.error(e?.message || '打开 IDE 失败')
    open.value = false
  }
}

defineExpose({ openWorkspace })
</script>

<template>
  <el-drawer
    v-model="open"
    title="IDE 编辑器"
    direction="rtl"
    size="100%"
    body-class="workspace-ide-drawer-body"
    :append-to-body="true"
    :destroy-on-close="false"
  >
    <div class="ide-pane">
      <iframe
        v-if="ideUrl"
        :key="ideUrl"
        :src="ideUrl"
        class="ide-frame"
        allow="clipboard-read; clipboard-write"
        @load="onIdeFrameLoad"
        @error="onIdeFrameError"
      ></iframe>
      <div v-if="!ideLoaded" class="ide-loading-overlay">
        <div class="ide-loading-content">
          <template v-if="ideLoadError">
            <div class="ide-error-icon">⚠️</div>
            <span>{{ ideLoadError }}</span>
            <button class="ide-retry-btn" @click="retryIdeLoad">重新加载</button>
          </template>
          <template v-else>
            <div class="ide-loading-spinner"></div>
            <span>{{ ideLoadingText }}</span>
          </template>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<!-- 非 scoped:el-drawer append-to-body teleport 到 body 外,scoped 选择器触不到。 -->
<style>
.workspace-ide-drawer-body {
  padding: 0 !important;
  display: flex !important;
  flex-direction: column;
  overflow: hidden;
}
.workspace-ide-drawer-body .ide-pane {
  flex: 1 1 auto;
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.workspace-ide-drawer-body .ide-frame {
  width: 100% !important;
  height: 100% !important;
  border: 0;
}
.workspace-ide-drawer-body .ide-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--t-bg-base);
}
.workspace-ide-drawer-body .ide-loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--t-text-secondary);
  font-size: 14px;
}
.workspace-ide-drawer-body .ide-loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--t-border-subtle);
  border-top-color: var(--t-brand);
  border-radius: 50%;
  animation: workspace-ide-spin 0.8s linear infinite;
}
@keyframes workspace-ide-spin { to { transform: rotate(360deg); } }
.workspace-ide-drawer-body .ide-error-icon { font-size: 32px; margin-bottom: 4px; }
.workspace-ide-drawer-body .ide-retry-btn {
  margin-top: 12px;
  padding: 8px 24px;
  border: 1px solid var(--t-brand, #646cff);
  border-radius: 8px;
  background: transparent;
  color: var(--t-brand, #646cff);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.workspace-ide-drawer-body .ide-retry-btn:hover { background: var(--t-brand, #646cff); color: #fff; }
</style>
