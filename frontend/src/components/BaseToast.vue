<template>
  <Teleport to="body">
    <transition name="toast">
      <div v-if="visible" :class="['bt-toast', `bt-${type ?? 'info'}`]" role="status">
        {{ message }}
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  message: string
  type?: 'info' | 'success' | 'warn' | 'error'
}>()
</script>

<style scoped>
.bt-toast { position: fixed; top: 24px; right: 24px; padding: 12px 20px; border-radius: 8px; z-index: 3000; box-shadow: var(--sh-pop, 0 6px 18px rgba(0,0,0,.18)); font-size: 13px; }
.bt-info { background: var(--brand-soft, #e6f4ff); color: var(--brand, #0a66c2); }
.bt-success { background: var(--t-success-subtle, #ecfdf3); color: var(--t-success, #1f9254); }
.bt-warn { background: var(--t-warning-subtle, #fffaeb); color: var(--t-warning, #b54708); }
.bt-error { background: var(--t-danger-subtle, #fee4e2); color: var(--t-danger, #b42318); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(-8px); }
.toast-enter-active, .toast-leave-active { transition: all .2s; }
</style>
