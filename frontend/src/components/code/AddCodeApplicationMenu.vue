<template>
  <el-dropdown v-if="desktop" trigger="click" placement="bottom-end" @command="handleCommand">
    <button class="btn btn-primary apps-toolbar-action" type="button">
      <el-icon><Plus /></el-icon>
      <span>添加应用</span>
      <el-icon><ArrowDown /></el-icon>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="new_directory">新建本地项目</el-dropdown-item>
        <el-dropdown-item command="existing_directory">打开已有项目</el-dropdown-item>
        <el-dropdown-item command="remote" divided>添加远程应用</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
  <button v-else class="btn btn-primary apps-toolbar-action" type="button" @click="$emit('remote')">
    <el-icon><Plus /></el-icon>
    <span>添加应用</span>
  </button>
</template>

<script setup lang="ts">
import { ArrowDown, Plus } from '@element-plus/icons-vue'
import type { LocalApplicationDirectoryMode } from '@/api/codeRuntime'

defineProps<{ desktop: boolean }>()
const emit = defineEmits<{
  local: [mode: LocalApplicationDirectoryMode]
  remote: []
}>()

function handleCommand(command: LocalApplicationDirectoryMode | 'remote') {
  if (command === 'remote') emit('remote')
  else emit('local', command)
}
</script>

<style scoped>
.apps-toolbar-action {
  height: 36px;
  border: 1px solid var(--brand);
  border-radius: var(--r-3, 8px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  padding: 0 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font: inherit;
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
}
</style>
