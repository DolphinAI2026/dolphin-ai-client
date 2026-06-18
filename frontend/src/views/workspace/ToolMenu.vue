<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="tool-menu-trigger" title="工具面板"><AppIcon name="layout" :size="16" /></button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item
          v-for="item in items" :key="item.id"
          :command="item.id" :disabled="!item.enabled"
          :class="{ 'is-disabled': !item.enabled }">
          <AppIcon :name="item.icon" :size="14" /> {{ item.label }}
          <span class="sc" v-if="item.shortcut">{{ item.shortcut }}</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { buildToolMenuItems } from './panelRegistry'
import type { Binding } from './binding'

const props = defineProps<{ binding: Binding }>()
const emit = defineEmits<{ (e: 'open', panelId: string): void }>()

const items = computed(() => buildToolMenuItems(props.binding))

function onCommand(id: string) {
  const item = items.value.find(i => i.id === id)
  if (!item || !item.enabled) return   // 守卫: 禁用项不触发
  emit('open', id)
}
</script>
