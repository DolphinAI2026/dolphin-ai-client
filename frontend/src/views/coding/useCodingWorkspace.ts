/**
 * useCodingWorkspace — 工作区列表 / 过滤 / 展示名和类型标签。
 *
 * 职责：
 * - `allWorkspaces` 全量列表，`existingWorkspaces` 按 app 过滤，`workspaceShowcaseItems` 取前 6
 * - `workspaceDisplayName` / `workspaceCodeName` / `workspaceTooltip` / `workspaceTypeLabel` 展示 formatter
 * - 下载工作区 zip（dist / src）
 *
 * 不包含：upload-to-platform 流程（带有模态框 UI 状态，保留在 CodingPage.vue）。
 */

import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import { codingApi, type WorkspaceInfo } from '@/api/coding'

const WS_TYPE_GROUP_MAP: Record<string, { key: string; icon: string; label: string; order: number }> = {
  'form-component-dual': { key: 'component-pc',     icon: '🧩', label: '双端组件',      order: 1 },
  'menu-page':           { key: 'page-pc',          icon: '🖥️', label: 'PC 页面',       order: 2 },
  'form-page':           { key: 'page-pc',          icon: '🖥️', label: 'PC 页面',       order: 2 },
  'mobile-page':         { key: 'page-mobile',      icon: '📱', label: 'Mobile 页面',   order: 4 },
  'backend-api':         { key: 'backend',          icon: '⚙️', label: '后端接口',      order: 5 },
  'backend-feign':       { key: 'backend',          icon: '⚙️', label: '后端接口',      order: 5 },
  'backend-scheduled':   { key: 'backend',          icon: '⚙️', label: '后端接口',      order: 5 },
}

export function useCodingWorkspace() {
  const route = useRoute()

  const allWorkspaces = ref<WorkspaceInfo[]>([])
  const isDownloading = ref(false)
  /** 正在下载的工作区 id（卡片级 loading 标记，防止重复点击） */
  const downloadingWsId = ref<string | null>(null)

  const embeddedProjectId = computed(() => {
    const raw = route.query.project_id
    return Array.isArray(raw) ? (raw[0] || '') : (raw || '')
  })

  const embeddedAppId = computed(() => {
    const embeddedApp = route.query.app_id as string
    return embeddedApp || ''
  })

  const existingWorkspaces = computed(() => {
    if (!embeddedProjectId.value) return allWorkspaces.value
    return allWorkspaces.value.filter((ws: any) => String(ws.project_id || '') === embeddedProjectId.value)
  })

  const workspaceShowcaseItems = computed(() => existingWorkspaces.value.slice(0, 6))

  function workspaceDisplayName(ws: WorkspaceInfo | null | undefined) {
    if (!ws) return ''
    const raw = ws.display_name?.trim() || ''
    // 防御 display_name 是 chat 消息片段（"[" 开头、"项。"、"-"、长篇 markdown 等）
    const looksLikeChatFragment =
      /^[\[【（]/.test(raw) ||
      /^项[。.]/.test(raw) ||
      /^[-*]\s/.test(raw) ||
      raw.length > 30
    if (!raw || looksLikeChatFragment) {
      return ws.project_name || `工作区 ${ws.id}`
    }
    return raw
  }

  function workspaceCodeName(ws: WorkspaceInfo | null | undefined) {
    if (!ws || !ws.project_name) return ''
    const displayName = workspaceDisplayName(ws)
    return displayName !== ws.project_name ? ws.project_name : ''
  }

  function workspaceTooltip(ws: WorkspaceInfo | null | undefined) {
    if (!ws) return ''
    const displayName = workspaceDisplayName(ws)
    const codeName = workspaceCodeName(ws)
    return codeName ? `${displayName}\n${codeName}` : displayName
  }

  function workspaceTypeLabel(projectType: string) {
    return WS_TYPE_GROUP_MAP[projectType]?.label || '其他'
  }

  async function downloadWorkspaceArtifact(ws: WorkspaceInfo, type: 'dist' | 'src') {
    if (downloadingWsId.value === ws.id) return  // 防止重复点击
    downloadingWsId.value = ws.id
    try {
      await codingApi.downloadZip(ws.id, type)
    } catch (e: any) {
      ElMessage.error(e?.message || '下载失败')
    } finally {
      downloadingWsId.value = null
    }
  }

  return {
    // state
    allWorkspaces,
    isDownloading,
    downloadingWsId,
    embeddedProjectId,
    embeddedAppId,
    // computed
    existingWorkspaces,
    workspaceShowcaseItems,
    // methods
    workspaceDisplayName,
    workspaceCodeName,
    workspaceTooltip,
    workspaceTypeLabel,
    downloadWorkspaceArtifact,
  }
}
