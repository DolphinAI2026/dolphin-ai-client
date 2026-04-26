<template>
  <div class="chat-panel">
    <div v-if="!conversationId" class="empty">
      <p class="muted">还没有对话</p>
      <button class="builder-btn builder-btn-primary" @click="onCreateConversation">开始对话</button>
    </div>
    <iframe
      v-else
      :src="iframeSrc"
      class="chat-iframe"
      sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { conversationApi } from '@/api/conversation'
import { useWorkspaceStore } from '@/stores/workspace'

const store = useWorkspaceStore()
const conversationId = ref<number | null>(null)

const iframeSrc = computed(() => {
  if (!conversationId.value) return ''
  return `/chat/${conversationId.value}?embed=true`
})

async function onCreateConversation() {
  if (!store.application) return
  // v1: 简化为每次手动开启新对话（application_id ↔ conversation_id 关联待 Phase F.1.5）
  const conv = await conversationApi.create({
    agent_type: 'builder',
  })
  conversationId.value = conv.id
}
</script>

<style scoped>
.chat-panel { height: 100%; display: flex; flex-direction: column; }
.empty { padding: 32px; text-align: center; }
.empty p { color: var(--fg-muted); margin-bottom: 16px; }
.chat-iframe { flex: 1; border: 0; width: 100%; }
</style>
