<template>
  <div class="project-overview">
    <!-- #header (页内段,不抽组件) -->
    <header class="po-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')" title="返回首页">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <nav class="crumb">
          <span class="crumb-root">项目</span>
          <span class="crumb-sep">›</span>
          <b class="crumb-name">{{ project?.name || '加载中…' }}</b>
        </nav>
      </div>
      <div class="header-right">
        <span class="members-badge">成员 {{ members.length }}</span>
        <ThemeToggle />
        <button class="settings-btn" @click="openSettings" title="应用设置">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>
    </header>

    <div class="po-scroll">
      <div class="po-content">
        <!-- #hero 段 -->
        <section class="po-hero">
          <div class="hero-icon">▣</div>
          <div class="hero-body">
            <h1 class="hero-name">{{ project?.name || '加载中…' }}</h1>
            <p class="hero-desc" v-if="project?.description">{{ project.description }}</p>
            <div class="hero-meta">
              <span>{{ loading ? '—' : totalArtifacts }} 产物</span>
              <span>· {{ loading ? '—' : members.length }} 成员</span>
              <span v-if="project?.created_at">· {{ project.created_at.slice(0, 10) }} 创建</span>
            </div>
          </div>
          <div class="hero-actions">
            <button
              class="ghost"
              disabled
              title="即将支持"
            >重新部署</button>
            <button
              class="ghost"
              disabled
              title="即将支持:当前请在对话里发起多产物分解"
            >新建产物</button>
          </div>
        </section>

        <!-- 错误态 -->
        <div v-if="error === 'not_found'" class="po-empty">项目不存在或无权限。</div>

        <!-- loading 骨架 (skeleton) -->
        <template v-else-if="loading">
          <div class="ag-grid">
            <div class="skeleton-card" v-for="i in 2" :key="i" />
            <div class="skeleton-card" v-for="i in 2" :key="'b' + i" />
          </div>
        </template>

        <!-- 空态 -->
        <div v-else-if="!groups.length" class="po-empty">还没有产物。</div>

        <!-- 产物分组 + 依赖图 -->
        <template v-else>
          <ArtifactGroup
            v-for="g in groups"
            :key="g.mode"
            :label="g.label"
            :artifacts="g.artifacts"
            @open="openArtifact"
          />
          <ArtifactDependencyGraph :edges="dependencies" />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ThemeToggle from '@/components/ThemeToggle.vue'
import ArtifactGroup from '@/components/project/ArtifactGroup.vue'
import ArtifactDependencyGraph from '@/components/project/ArtifactDependencyGraph.vue'
import { useProjectArtifacts } from '@/composables/useProjectArtifacts'
import type { ArtifactVM } from '@/composables/projectVM'

const route = useRoute()
const router = useRouter()
const projectId = Number(route.params.id)

const { project, groups, members, dependencies, loading, error, load } = useProjectArtifacts(projectId)

const totalArtifacts = computed(() =>
  groups.value.reduce((n, g) => n + g.artifacts.length, 0),
)

function openArtifact(a: ArtifactVM) {
  router.push(a.target)
}

function openSettings() {
  router.push(`/project/${projectId}/git`)
}

onMounted(load)
</script>

<style scoped>
.project-overview {
  --radius-sm: var(--r-3, 8px);
  --radius-md: var(--r-4, 12px);
  --radius-lg: var(--r-5, 16px);

  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans, inherit);
}

/* ── Header ── */
.po-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  background: var(--surface-overlay, var(--surface));
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.back-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.14s, border-color 0.14s, color 0.14s;
}

.back-btn:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.back-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  min-width: 0;
}

.crumb-root {
  color: var(--text-3);
}

.crumb-sep {
  color: var(--text-4, var(--text-3));
  font-size: 12px;
}

.crumb-name {
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 300px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.members-badge {
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  color: var(--text-2);
  padding: 4px 10px;
  background: var(--surface-2);
  border-radius: var(--r-full, 20px);
  border: 1px solid var(--line);
}

.settings-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.14s, border-color 0.14s, color 0.14s;
}

.settings-btn:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.settings-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

/* ── Scroll ── */
.po-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 60px;
}

.po-scroll::-webkit-scrollbar { width: 6px; }
.po-scroll::-webkit-scrollbar-track { background: transparent; }
.po-scroll::-webkit-scrollbar-thumb { background: var(--line-strong); border-radius: 3px; }
.po-scroll::-webkit-scrollbar-thumb:hover { background: var(--text-3); }

.po-content {
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
  padding-top: 32px;
}

/* ── Hero ── */
.po-hero {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 40px;
  padding: 28px 24px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}

.hero-icon {
  font-size: 36px;
  line-height: 1;
  flex-shrink: 0;
  color: var(--brand);
}

.hero-body {
  flex: 1;
  min-width: 0;
}

.hero-name {
  font-size: 22px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  margin: 0 0 4px;
  letter-spacing: -0.02em;
}

.hero-desc {
  font-size: 13px;
  color: var(--text-2);
  margin: 0 0 10px;
}

.hero-meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--text-3);
}

.hero-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

/* ── Ghost buttons (置灰) ── */
.ghost {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  font-family: inherit;
  cursor: not-allowed;
  opacity: 0.55;
}

/* ── Skeleton (loading) ── */
.ag-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  margin-bottom: 28px;
}

.skeleton-card {
  height: 90px;
  border-radius: var(--radius-md);
  background: linear-gradient(
    90deg,
    var(--surface) 25%,
    var(--surface-2, var(--line)) 50%,
    var(--surface) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border: 1px solid var(--line);
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ── Empty / Error ── */
.po-empty {
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
  padding: 48px 20px;
  background: var(--surface);
  border: 1px dashed var(--line-strong, var(--line));
  border-radius: var(--radius-md);
  margin-bottom: 28px;
}
</style>
