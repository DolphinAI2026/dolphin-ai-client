<!-- CustomPagePreviewPanel.vue — design-v4 R (2026-05-27) / 信息卡重写 (2026-05-28)
  CUSTOM 菜单 (apaas 自开发整页 Vue) 预览 + 编辑入口.

  apaas menu_type=CUSTOM 菜单 link_url = 注册到运行态的 Vue 组件名
  (例: apaas-custom-library-home-dashboard). 平台运行时按组件名扫描加载渲染.

  2026-05-28: 之前 preview 用 iframe 塞 apaas runtime URL — 但 apaas 是 SPA, 运行态
  路由我们拿不到精确 pattern (且 app 没发布到生产时运行页根本不存在) → iframe 空白.
  改成信息卡 + 双入口 (用户决策): 显组件名 + 在 apaas 打开真应用 + 去 IDE 改源码.
  比空白 iframe 诚实可用.
-->
<template>
  <section class="cpp">
    <header class="cpp-head">
      <div class="cpp-head-meta">
        <h1 class="cpp-title">{{ menuName || '自开发页面' }}</h1>
        <span class="cpp-chip">🎨 自开发</span>
      </div>
    </header>

    <div class="cpp-body">
      <div class="cpp-card">
        <div class="cpp-card-icon">🧩</div>
        <h2>自开发整页 Vue 组件</h2>
        <p>
          这个菜单挂的是自开发的 Vue 页面, 在 apaas 应用运行时由平台
          <strong>按组件名扫描加载</strong>渲染 — 不是数据驱动表单, 设计器无法静态
          模拟它的交互.
        </p>

        <div v-if="pageCode" class="cpp-code-row">
          <span class="cpp-code-label">组件名 / 页面码</span>
          <code class="cpp-code-val">{{ pageCode }}</code>
        </div>

        <div class="cpp-actions">
          <button type="button" class="cpp-cta cpp-cta-primary" @click="onOpenInApaas">
            <span>🚀</span> 在 apaas 平台打开
          </button>
          <button type="button" class="cpp-cta cpp-cta-ghost" @click="onGoToCoding">
            <span>💻</span> 去 IDE 改源码
          </button>
        </div>

        <p class="cpp-hint">
          “在 apaas 平台打开” 新开标签进该应用的平台页, 从菜单进这个自开发页看运行
          效果; “去 IDE 改源码” 进 Vibe Coding 改这个组件的 Vue / TS 源码.
        </p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { buildPlatformProxyEntryUrl } from '@/utils/platformIframe'

const props = defineProps<{
  appId: number
  menuId: string
  menuName?: string
  /** apaas CUSTOM 菜单 link_url — 注册的 Vue 组件名 (apaas-custom-*). 可选. */
  pageCode?: string
}>()

const router = useRouter()
const userStore = useUserStore()

function onGoToCoding() {
  router.push({ path: '/coding', query: { app_id: String(props.appId) } })
}

function onOpenInApaas() {
  const token = userStore.token || localStorage.getItem('token') || ''
  // 2026-05-28: 用 entry (不带 menu) 落 apaas 应用总览页 — 可靠. CUSTOM 菜单的
  // runtime 单页路由 (/platform/{tid}/{app_code}/page/{menu_id}) apaas SPA 不认 →
  // 白屏, 所以不再直跳运行态; 落总览页让用户从菜单自己进运行态看效果.
  const url = buildPlatformProxyEntryUrl(props.appId, token)
  window.open(url, '_blank', 'noopener')
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

.cpp-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  overflow-y: auto;
}
.cpp-card {
  max-width: 520px;
  text-align: center;
  padding: 36px 32px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
}
.cpp-card-icon {
  font-size: 48px;
  margin-bottom: 14px;
}
.cpp-card h2 {
  font-size: 19px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 10px;
}
.cpp-card p {
  font-size: 13.5px;
  color: var(--text-2);
  line-height: 1.65;
  margin: 0 0 10px;
}
.cpp-card p strong {
  color: var(--text-1);
  font-weight: 600;
}

.cpp-code-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 16px 0;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.cpp-code-label {
  font-size: 12px;
  color: var(--text-3);
  flex-shrink: 0;
}
.cpp-code-val {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12.5px;
  color: var(--ai, #1D89A8);
  word-break: break-all;
}

.cpp-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin: 20px 0 14px;
  flex-wrap: wrap;
}
.cpp-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: opacity 0.15s, background 0.15s;
}
.cpp-cta-primary {
  background: var(--brand);
  color: #fff;
  border: none;
}
.cpp-cta-primary:hover { opacity: 0.88; }
.cpp-cta-ghost {
  background: var(--surface);
  color: var(--text-1);
  border: 1px solid var(--line-strong, var(--line));
}
.cpp-cta-ghost:hover { background: var(--surface-2); }

.cpp-hint {
  font-size: 12px !important;
  color: var(--text-3) !important;
  line-height: 1.6;
  margin: 0 !important;
}
</style>
