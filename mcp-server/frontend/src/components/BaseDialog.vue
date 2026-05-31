<template>
  <Teleport to="body">
    <div v-if="visible" class="bd-backdrop" @click.self="onCancel">
      <div class="bd-modal" role="dialog" aria-modal="true">
        <h4 v-if="title" class="bd-title">{{ title }}</h4>
        <p v-if="message" class="bd-message">{{ message }}</p>
        <slot></slot>
        <div class="bd-actions">
          <button v-if="cancelText" class="builder-btn" type="button" @click="onCancel">{{ cancelText }}</button>
          <button :class="['builder-btn', dangerous ? 'builder-btn-danger' : 'builder-btn-primary']" type="button" @click="onConfirm">
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  visible: boolean
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  dangerous?: boolean
}>(), {
  confirmText: '确认',
  cancelText: '取消',
  dangerous: false,
})

const emit = defineEmits<{ confirm: []; cancel: [] }>()

function onConfirm() { emit('confirm') }
function onCancel() { emit('cancel') }
</script>

<style scoped>
.bd-backdrop { position: fixed; inset: 0; background: var(--t-bg-overlay, rgba(0,0,0,.5)); display: flex; align-items: center; justify-content: center; z-index: 2000; }
.bd-modal { background: var(--bg-panel, var(--t-bg-elevated, #fff)); color: var(--fg, var(--t-text-primary, #1a1a1a)); padding: 24px; border-radius: 8px; min-width: 320px; max-width: 600px; box-shadow: var(--sh-pop, 0 8px 24px rgba(0,0,0,.18)); }
.bd-title { margin: 0 0 12px; font-size: 16px; }
.bd-message { color: var(--fg-muted, var(--t-text-secondary, #6a6a6a)); margin: 8px 0; }
.bd-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
