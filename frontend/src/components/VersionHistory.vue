<template>
  <div class="version-history">
    <div class="vh-header">
      <h3>版本历史</h3>
      <button class="btn-refresh" @click="loadVersions" :disabled="loading">
        {{ loading ? '加载中...' : '刷新' }}
      </button>
    </div>

    <div v-if="versions.length === 0 && !loading" class="empty">
      暂无版本记录
    </div>

    <div v-else class="version-list">
      <div
        v-for="ver in versions"
        :key="ver.version"
        class="version-item"
        :class="{ current: ver.version === currentVersion }"
      >
        <div class="version-info">
          <span class="version-badge">v{{ ver.version }}</span>
          <span class="version-source" :class="ver.source">{{ sourceLabel(ver.source) }}</span>
          <span class="version-summary">{{ ver.summary }}</span>
        </div>
        <div class="version-meta">
          <span class="version-time">{{ formatTime(ver.created_at) }}</span>
          <div class="version-actions">
            <button
              class="btn-sm"
              @click="$emit('preview', ver.version)"
            >预览</button>
            <button
              v-if="ver.version !== currentVersion"
              class="btn-sm btn-rollback"
              @click="$emit('rollback', ver.version)"
            >回滚</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface VersionInfo {
  id: number
  version: number
  source: string
  summary: string
  created_at: string
}

interface Props {
  versions: VersionInfo[]
  currentVersion?: number
  loading?: boolean
}

withDefaults(defineProps<Props>(), {
  currentVersion: 0,
  loading: false,
})

defineEmits<{
  preview: [version: number]
  rollback: [version: number]
}>()

const sourceLabel = (source: string): string => {
  const map: Record<string, string> = {
    chat: '对话',
    document: '文档',
    sync: '同步',
    rollback: '回滚',
    generation: '生成',
    incremental: '增量',
  }
  return map[source] || source
}

const formatTime = (iso: string): string => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped lang="less">
.version-history {
  background: #1a1a2e;
  border-radius: 12px;
  padding: 16px;
  color: #e0e0e0;
}

.vh-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;

  h3 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }
}

.btn-refresh {
  background: rgba(255,255,255,0.08);
  border: none;
  color: #888;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  &:hover { color: #fff; background: rgba(255,255,255,0.12); }
  &:disabled { opacity: 0.5; cursor: not-allowed; }
}

.empty {
  text-align: center;
  color: #666;
  padding: 24px;
  font-size: 13px;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
}

.version-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.04);
  border-radius: 8px;
  border-left: 3px solid transparent;
  transition: all 0.2s;

  &:hover { background: rgba(255,255,255,0.07); }
  &.current { border-left-color: #6366f1; background: rgba(99, 102, 241, 0.08); }
}

.version-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-badge {
  font-size: 12px;
  font-weight: 600;
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
  min-width: 36px;
  text-align: center;
}

.version-source {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  &.chat { background: rgba(74, 222, 128, 0.15); color: #4ade80; }
  &.document { background: rgba(96, 165, 250, 0.15); color: #60a5fa; }
  &.sync { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
  &.rollback { background: rgba(248, 113, 113, 0.15); color: #f87171; }
  &.generation { background: rgba(167, 139, 250, 0.15); color: #a78bfa; }
  &.incremental { background: rgba(45, 212, 191, 0.15); color: #2dd4bf; }
}

.version-summary {
  font-size: 13px;
  color: #ccc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.version-time {
  font-size: 11px;
  color: #666;
}

.version-actions {
  display: flex;
  gap: 6px;
}

.btn-sm {
  background: rgba(255,255,255,0.08);
  border: none;
  color: #aaa;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  &:hover { color: #fff; background: rgba(255,255,255,0.15); }
}

.btn-rollback {
  color: #f87171;
  &:hover { background: rgba(248, 113, 113, 0.15); color: #fca5a5; }
}
</style>
