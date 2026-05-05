<template>
  <iframe
    v-if="prefetchSrc"
    :src="prefetchSrc"
    class="dolphin-prefetcher-iframe"
    aria-hidden="true"
    tabindex="-1"
  />
</template>

<script setup lang="ts">
/**
 * Dolphin SPA 预热器：
 *
 * 用户进 ai-builder 后 5 秒（让首屏先 settle），后台 mount 一个 1×1 离屏 iframe
 * 加载 dolphin embed URL，把 dolphin SPA 的 vendor / vue / element-plus 等
 * chunks 全部拉进浏览器 HTTP cache。等用户切到 /requirements-assistant 时新
 * iframe 加载 cache 命中，几秒内可见（vs 冷启动 ~10-30s）。
 *
 * 只 warmup 一次：组件 mount 一次拉一次，之后不再触发；用户切账号 / 切租户
 * 时也不重新预热（dolphin chunks 跨账号共用浏览器 cache）。
 */
import { computed, onMounted, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import request from '@/utils/request'

const userStore = useUserStore()
const agentCode = ref('')
const ready = ref(false)

const prefetchSrc = computed(() => {
  if (!ready.value || !agentCode.value) return ''
  // 直接命中 dolphin embed 入口，dolphin SPA 会进入 chunk 加载流程
  return `https://dolphin-trial.definesys.cn/embed/agent/${agentCode.value}/chat`
})

onMounted(() => {
  // 用户没登录就不预热（避免无意义请求 + 拿不到 agent_code）
  if (!localStorage.getItem('token')) return

  // 延 5 秒：让 ai-builder 自己首屏先 settle，再把带宽让给 dolphin 预热
  setTimeout(async () => {
    if (!userStore.user) return
    try {
      const cfg = await request.get<unknown, { requirements_agent_code?: string }>(
        '/dolphin/config',
      )
      if (cfg?.requirements_agent_code) {
        agentCode.value = cfg.requirements_agent_code
        ready.value = true
      }
    } catch {
      // 静默 — 拉不到就不预热，不影响主流程
    }
  }, 5000)
})
</script>

<style scoped>
.dolphin-prefetcher-iframe {
  position: fixed;
  top: -9999px;
  left: -9999px;
  width: 1px;
  height: 1px;
  border: 0;
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
}
</style>
