<template>
  <section class="panel-host">
    <header v-if="active" class="panel-host-head">
      <span>{{ active.label }}</span>
      <button @click="emit('close')" title="关闭面板"><AppIcon name="x" :size="14" /></button>
    </header>
    <div v-if="!active" class="panel-empty" style="padding:24px;opacity:.5">从右上角工具菜单打开一个面板</div>
    <div v-else-if="failed" class="panel-error" style="padding:24px;color:#dc2626">面板加载失败,请重试</div>
    <component v-else :is="active.component" :session-id="sessionId" :artifact="artifact" :binding="binding" />
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch, onErrorCaptured } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { getPanel } from './panelRegistry'
import type { Binding } from './binding'

const props = defineProps<{ activePanelId: string | null; binding: Binding; sessionId: number | null; artifact?: any }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const active = computed(() => (props.activePanelId ? getPanel(props.activePanelId) : undefined))
const failed = ref(false)

watch(() => props.activePanelId, () => { failed.value = false })
onErrorCaptured(() => { failed.value = true; return false })  // 降级, 不冒泡崩外壳
</script>
