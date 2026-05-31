<template>
  <div v-if="open" class="builder-command-backdrop" @mousedown.self="close">
    <section class="builder-command-palette" role="dialog" aria-label="命令面板">
      <div class="builder-command-input">
        <Search />
        <input
          ref="inputRef"
          v-model="query"
          placeholder="搜索页面、应用、仓库、设置..."
          @keydown.enter="goFirst"
          @keydown.esc="close"
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
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  ChatDotRound,
  DataAnalysis,
  Grid,
  HomeFilled,
  Monitor,
  Promotion,
  Search,
  Setting,
} from '@element-plus/icons-vue'

const router = useRouter()
const open = ref(false)
const query = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const commandItems = [
  { icon: HomeFilled, title: '新建应用', meta: '回到首页，用 AI Builder 生成设计文档', to: '/' },
  { icon: ChatDotRound, title: 'AI Builder', meta: '继续现有搭建对话和部署流程', to: '/chat' },
  { icon: Grid, title: '应用资产库', meta: '查看已生成应用和平台导入入口', to: '/apps' },
  { icon: Setting, title: '模型配置', meta: '真实模型供应商、API Key、默认模型管理', to: '/platform-envs?tab=llm' },
  { icon: DataAnalysis, title: '平台环境', meta: '真实得帆云连接、租户环境、默认环境管理', to: '/platform-envs?tab=envs' },
  { icon: Setting, title: '成员管理', meta: '真实组织成员、角色和启停状态管理', to: '/tenant-users' },
  { icon: Monitor, title: 'AI Coding', meta: '进入真实代码开发工作区', to: '/coding' },
  { icon: Promotion, title: 'DevOps 总览', meta: '第一阶段 mock：流水线、环境、审批', to: '/devops' },
]

const filteredItems = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commandItems
  return commandItems.filter(item => `${item.title} ${item.meta}`.toLowerCase().includes(q))
})

watch(open, async value => {
  if (!value) return
  query.value = ''
  await nextTick()
  inputRef.value?.focus()
})

function close() {
  open.value = false
}

function show() {
  open.value = true
}

function go(to: string) {
  close()
  router.push(to)
}

function goFirst() {
  if (filteredItems.value[0]) go(filteredItems.value[0].to)
}

function onKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    show()
  }
  if (event.key === 'Escape') close()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('builder:open-command', show)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('builder:open-command', show)
})
</script>
