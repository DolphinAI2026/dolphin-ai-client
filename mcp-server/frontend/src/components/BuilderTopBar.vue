<template>
  <header class="builder-topbar">
    <div class="builder-breadcrumbs">
      <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb.label}-${index}`">
        <span v-if="index > 0" class="builder-breadcrumb-sep">/</span>
        <button
          v-if="crumb.to"
          class="builder-breadcrumb-link"
          :class="{ current: index === breadcrumbs.length - 1 }"
          @click="router.push(crumb.to)"
        >
          {{ crumb.label }}
        </button>
        <span v-else class="builder-breadcrumb-link current">{{ crumb.label }}</span>
      </template>
    </div>

    <slot name="center" />

    <div class="builder-topbar-spacer" />

    <span v-if="userStore.tenantName" class="builder-current-tenant" :title="`当前激活租户：${userStore.tenantName}`">
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect x="2" y="3" width="5" height="11" rx="1" stroke="currentColor" stroke-width="1.4" />
        <rect x="9" y="6" width="5" height="8" rx="1" stroke="currentColor" stroke-width="1.4" />
      </svg>
      {{ userStore.tenantName }}
    </span>

    <button class="builder-global-search" type="button" @click="commandOpen = true">
      <Search />
      <span>搜索应用、仓库、模型、对话...</span>
      <kbd>⌘K</kbd>
    </button>

    <slot name="actions" />

    <div v-if="commandOpen" class="builder-command-backdrop" @mousedown.self="commandOpen = false">
      <section class="builder-command-palette" role="dialog" aria-label="命令面板">
        <div class="builder-command-input">
          <Search />
          <input
            ref="commandInput"
            v-model="query"
            placeholder="搜索页面、应用、仓库、设置..."
            @keydown.enter="goFirst"
            @keydown.esc="commandOpen = false"
          >
          <kbd>esc</kbd>
        </div>
        <div class="builder-command-list">
          <button v-for="item in filteredItems" :key="item.title" class="builder-command-item" @click="go(item.to)">
            <span class="builder-command-icon"><component :is="item.icon" /></span>
            <span class="builder-command-main">
              <span class="builder-command-title">{{ item.title }}</span>
              <span class="builder-command-meta">{{ item.meta }}</span>
            </span>
            <ArrowRight />
          </button>
          <div v-if="!filteredItems.length" class="builder-command-empty">没有匹配结果</div>
        </div>
      </section>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
import {
  ArrowRight,
  ChatDotRound,
  DataAnalysis,
  Grid,
  HomeFilled,
  Monitor,
  Search,
} from '@element-plus/icons-vue'

interface Breadcrumb {
  label: string
  to?: string
}

defineProps<{
  breadcrumbs: Breadcrumb[]
}>()

const router = useRouter()
const commandOpen = ref(false)
const query = ref('')
const commandInput = ref<HTMLInputElement | null>(null)

const commandItems = [
  { icon: HomeFilled, title: '新建智能搭建', meta: 'Builder 默认入口，从需求生成 SPEC', to: '/' },
  { icon: ChatDotRound, title: '继续搭建对话', meta: '设备巡检管理 · SPEC v0.1', to: '/chat' },
  { icon: Grid, title: '我的应用', meta: '5 个应用 · 3 个进行中', to: '/apps' },
  { icon: DataAnalysis, title: '查看模型和表单', meta: '模型、表单、流程、权限', to: '/chat?tab=models' },
  { icon: Monitor, title: 'AI Coding', meta: '平台组件、页面和接口开发', to: '/coding' },
]

const filteredItems = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commandItems
  return commandItems.filter(item => `${item.title} ${item.meta}`.toLowerCase().includes(q))
})

watch(commandOpen, async open => {
  if (!open) return
  query.value = ''
  await nextTick()
  commandInput.value?.focus()
})

function go(to: string) {
  commandOpen.value = false
  router.push(to)
}

function goFirst() {
  if (filteredItems.value[0]) go(filteredItems.value[0].to)
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    commandOpen.value = true
  }
  if (event.key === 'Escape') commandOpen.value = false
}

function openFromEvent() {
  commandOpen.value = true
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('builder:open-command', openFromEvent)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('builder:open-command', openFromEvent)
})
</script>
