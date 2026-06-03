<!-- CustomPagePreviewPanel.vue — design-v4 R (2026-05-27) / 自开发组件独立运行 (2026-05-28)
  CUSTOM 菜单 (apaas 自开发整页 Vue) 预览 + 编辑入口.

  apaas menu_type=CUSTOM 菜单 link_url = 注册到运行态的 Vue 组件名
  (例: apaas-custom-library-home-dashboard). 组件被打成 UMD bundle 部署在 apaas.

  2026-05-28 v3 (用户决策"自开发包都拿到了, 直接自己跑起来"):
  之前 iframe 整个 apaas 运行态 SPA → 部署应用按租户做端用户登录 → 卡在 /account/login.
  改成: iframe 指向 backend 的 custom-page-host — 它只把自开发组件的 UMD bundle 拉过来,
  在我们自己的 Vue2 + ElementUI 宿主里 install + mount, 没有登录闸, 直接渲染页面.
  数据调用走同源 /apaas 代理 (注入平台 token); 取不到数据组件也渲染骨架.
  "↗ 在 apaas 打开" 仍保留 — 跳真运行态 (用户自己的 apaas 登录态) 看带真数据的完整应用.
-->
<template>
  <section class="cpp">
    <header class="cpp-head">
      <div class="cpp-head-meta">
        <h1 class="cpp-title">{{ menuName || '自开发页面' }}</h1>
        <span class="cpp-chip">🎨 自开发</span>
      </div>
    </header>

    <!-- 自开发组件独立运行 host (backend 提供 Vue2+ElementUI 宿主 + 拉 bundle + mount) -->
    <div v-if="hostUrl" class="cpp-frame-wrap">
      <iframe
        :key="iframeKey"
        class="cpp-frame"
        :src="hostUrl"
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads"
        title="自开发整页组件预览"
      />
    </div>

    <!-- 没选菜单 / 缺 menu_id 兜底 -->
    <div v-else class="cpp-body">
      <div class="cpp-card">
        <div class="cpp-card-icon">🧩</div>
        <h2>自开发整页 Vue 组件</h2>
        <p>选中一个自开发菜单后, 这里直接运行它的组件 bundle 渲染页面预览.</p>
        <div class="cpp-actions">
          <button type="button" class="cpp-cta cpp-cta-ghost" @click="onGoToCoding">
            <span>💻</span> 去 IDE 改源码
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const props = defineProps<{
  appId: number
  menuId: string
  menuName?: string
  /** apaas CUSTOM 菜单 link_url — 注册的 Vue 组件名 (apaas-custom-*). 可选. */
  pageCode?: string
}>()

const router = useRouter()
const userStore = useUserStore()

const iframeKey = ref(0)

// 自开发组件独立运行 host — backend 解析 menu_id → bundle, 返 Vue2+ElementUI 宿主页.
// _k 用于 ↻ 刷新强制 reload; _auth 走 query 传 token (iframe src GET 带不了 header).
const hostUrl = computed(() => {
  if (!props.appId || !props.menuId) return ''
  const tok = userStore.token || localStorage.getItem('token') || ''
  return `/api/applications/${props.appId}/custom-page-host`
    + `?menu_id=${encodeURIComponent(props.menuId)}`
    + `&_auth=${encodeURIComponent(tok)}&_k=${iframeKey.value}`
})

function onGoToCoding() {
  // 结构化交接到 AI Builder（AIChatPage）在应用上下文里做二次开发，不再跳独立 /coding。
  const pageLabel = props.menuName || props.pageCode || props.menuId
  const message =
    `我要在应用（app_id=${props.appId}）上对自开发页面「${pageLabel}」做二次开发 / 改源码。`
    + `请先读这个应用的结构和该页面，再问我具体要改什么。`
  sessionStorage.setItem(
    'ai_builder_pending_app_dev',
    JSON.stringify({
      message,
      app_id: props.appId,
      app_name: '',
      page: { menu_id: props.menuId, page_code: props.pageCode || '', name: props.menuName || '' },
    }),
  )
  router.push({ path: '/ai-chat', query: { app_dev: '1' } })
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
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.cpp-head-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cpp-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cpp-mini-btn {
  padding: 5px 10px;
  border: 1px solid var(--line-strong, var(--line));
  border-radius: 6px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.cpp-mini-btn:hover { background: var(--surface-2); color: var(--text-1); }
.cpp-mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* iframe 内嵌组件 host */
.cpp-frame-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  background: var(--surface-2);
}
.cpp-frame {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: #fff;
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
  margin: 0 0 16px;
}

.cpp-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
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
.cpp-cta-ghost {
  background: var(--surface);
  color: var(--text-1);
  border: 1px solid var(--line-strong, var(--line));
}
.cpp-cta-ghost:hover { background: var(--surface-2); }
</style>
