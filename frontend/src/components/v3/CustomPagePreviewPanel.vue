<!-- CustomPagePreviewPanel.vue — design-v4 R (2026-05-27)
  CUSTOM 菜单 (apaas 自开发 Vue 页) 预览 + 编辑入口.

  - 默认 preview: iframe runtime URL (apaas 部署后的真运行页)
  - 编辑: 跳 /coding?app_id=N (Vibe Coding / IDE 改源码)

  apaas menu_type=CUSTOM 菜单 link_url 是 dev workspace 的 page code
  (例: apaas-custom-library-home-dashboard). runtime 走 apaas 应用域名.
-->
<template>
  <section class="cpp">
    <header class="cpp-head">
      <div class="cpp-head-meta">
        <h1 class="cpp-title">{{ menuName || '自开发页面' }}</h1>
        <span class="cpp-chip">🎨 自开发</span>
      </div>
      <div class="cpp-head-actions">
        <div class="cpp-view-toggle" role="group" aria-label="切换查看模式">
          <button
            type="button"
            class="cpp-toggle-btn"
            :class="{ active: viewMode === 'preview' }"
            @click="viewMode = 'preview'"
          >
            <span class="cpp-toggle-icon">👁</span>
            预览
          </button>
          <button
            type="button"
            class="cpp-toggle-btn"
            :class="{ active: viewMode === 'edit' }"
            @click="viewMode = 'edit'"
          >
            <span class="cpp-toggle-icon">✏️</span>
            编辑
          </button>
        </div>
      </div>
    </header>

    <div v-if="viewMode === 'preview'" class="cpp-banner">
      <span class="cpp-banner-icon">✨</span>
      <span>业务视角预览 — 跟最终用户看的真页面一致. 改 UI 请去 IDE 改 Vue 源码.</span>
    </div>

    <ApaasEmbedIframe
      v-if="viewMode === 'preview'"
      class="cpp-frame"
      :app-id="props.appId"
      :menu-id="props.menuId"
      menu-type="CUSTOM"
      mode="runtime"
    />

    <div v-else class="cpp-edit">
      <div class="cpp-edit-card">
        <div class="cpp-edit-icon">💻</div>
        <h2>自开发 Vue 组件</h2>
        <p>这个页面是用 Vue / TypeScript 写的, apaas 平台没有可视化编辑器.</p>
        <p class="cpp-edit-hint">改 UI / 加交互 / 调样式 → 去 Vibe Coding / 在线 IDE 改源码.</p>
        <button type="button" class="cpp-edit-cta" @click="onGoToCoding">
          去 IDE 修改源码 →
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import ApaasEmbedIframe from './ApaasEmbedIframe.vue'

const props = defineProps<{
  appId: number
  menuId: string
  menuName?: string
}>()

const viewMode = ref<'preview' | 'edit'>('preview')
const router = useRouter()

function onGoToCoding() {
  router.push({ path: '/coding', query: { app_id: String(props.appId) } })
}
</script>

<style scoped>
.cpp {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  font-family: var(--font-sans);
}

.cpp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}

.cpp-head-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.cpp-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0;
}

.cpp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.cpp-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cpp-view-toggle {
  display: inline-flex;
  background: var(--surface-2);
  border-radius: 8px;
  padding: 2px;
  border: 1px solid var(--line);
}

.cpp-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--text-3);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}

.cpp-toggle-btn:hover {
  color: var(--text-1);
}

.cpp-toggle-btn.active {
  background: var(--surface);
  color: var(--brand);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.cpp-toggle-icon {
  font-size: 13px;
}

.cpp-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 13px;
  flex-shrink: 0;
}

.cpp-banner-icon {
  font-size: 14px;
}

.cpp-frame {
  flex: 1;
  min-height: 400px;
}

.cpp-edit {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.cpp-edit-card {
  max-width: 480px;
  text-align: center;
  padding: 40px 32px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
}

.cpp-edit-icon {
  font-size: 56px;
  margin-bottom: 16px;
}

.cpp-edit-card h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 8px;
}

.cpp-edit-card p {
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.6;
  margin: 0 0 6px;
}

.cpp-edit-hint {
  color: var(--text-3);
  font-size: 13px;
  margin-bottom: 24px !important;
}

.cpp-edit-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: var(--brand);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: opacity 0.15s;
}

.cpp-edit-cta:hover {
  opacity: 0.85;
}
</style>
