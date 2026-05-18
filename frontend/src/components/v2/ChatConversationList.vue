<!-- frontend/src/components/v2/ChatConversationList.vue
     Left-column conversation list for ChatPage v2 redesign.
     Pure presentation. Parent owns the data + open handler. -->
<script setup lang="ts">
defineProps<{
  conversations: { id: string; title: string; updatedAt: string }[]
  currentId?: string
}>()
defineEmits<{ (e: 'open', id: string): void }>()
</script>

<template>
  <nav class="conv-list">
    <div class="conv-head">最近对话</div>
    <button
      v-for="c in conversations"
      :key="c.id"
      class="conv-row"
      :class="{ active: c.id === currentId }"
      @click="$emit('open', c.id)"
    >
      <div class="conv-title">{{ c.title }}</div>
      <div class="conv-when">{{ c.updatedAt }}</div>
    </button>
    <div v-if="!conversations.length" class="conv-empty">还没有对话</div>
  </nav>
</template>

<style scoped>
.conv-list { width: 240px; flex-shrink: 0; background: var(--surface-2); border-right: 1px solid var(--border); padding: 12px 8px; overflow-y: auto; height: 100%; }
.conv-head { font-size: 11px; font-weight: 600; letter-spacing: 0.10em; text-transform: uppercase; color: var(--text-3); padding: 4px 10px 8px; }
.conv-row { width: 100%; display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px; background: transparent; border: none; cursor: pointer; text-align: left; color: var(--text); font-family: inherit; }
.conv-row:hover { background: var(--surface); }
.conv-row.active { background: var(--brand-soft); color: var(--brand-text); }
.conv-title { font-size: 12.5px; font-weight: 500; line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-when { font-size: 10.5px; color: var(--text-3); font-family: var(--d-font-mono); }
.conv-empty { font-size: 12px; color: var(--text-3); padding: 12px 10px; }
</style>
