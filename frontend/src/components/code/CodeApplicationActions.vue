<template>
  <div class="code-application-actions">
    <button
      v-if="directLocation"
      class="apps-mini-action primary"
      type="button"
      :disabled="opening"
      @click="emitOpen(directLocation)"
    >
      {{ opening ? '打开中' : `在${locationName(directLocation)}打开` }}
    </button>

    <template v-else>
      <button
        class="apps-mini-action primary"
        type="button"
        :disabled="!primaryLocation || primaryUnavailable || opening"
        @click="primaryLocation && emitOpen(primaryLocation)"
      >
        {{ primaryLabel }}
      </button>
      <el-dropdown trigger="click" placement="bottom-end" @command="emitOpen">
        <button class="apps-mini-action code-location-more" type="button" title="选择打开位置" aria-label="选择打开位置">
          <el-icon><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item
              v-for="location in menuLocations"
              :key="location"
              :command="location"
              :disabled="application[location]?.availability !== 'ready'"
            >
              在{{ locationName(location) }}打开
            </el-dropdown-item>
            <el-dropdown-item v-if="application.association === 'remote_only'" disabled divided>
              创建本机副本（暂未开放）
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import type { CodeExecutionLocation } from '@/api/codeRuntime'
import {
  resolveCodeApplicationOpenState,
  type UnifiedCodeApplicationItem,
} from './codeApplicationLocations'

const props = defineProps<{
  application: UnifiedCodeApplicationItem
  preferredLocation?: CodeExecutionLocation | null
  opening?: boolean
}>()
const emit = defineEmits<{ open: [location: CodeExecutionLocation] }>()

const existingLocations = computed(() => (['local', 'remote'] as const)
  .filter(location => Boolean(props.application[location])))
const openState = computed(() => resolveCodeApplicationOpenState(
  props.application,
  props.preferredLocation || null,
))
const primaryLocation = computed(() => openState.value.primaryLocation)
const primaryUnavailable = computed(() => openState.value.rememberedUnavailable)
const directLocation = computed(() => existingLocations.value.length === 1 ? primaryLocation.value : null)
const menuLocations = computed(() => existingLocations.value
  .filter(location => location !== primaryLocation.value))
const primaryLabel = computed(() => {
  if (!primaryLocation.value) return '选择打开位置'
  if (primaryUnavailable.value) return `${locationName(primaryLocation.value)}位置不可用`
  return props.opening ? '打开中' : `在${locationName(primaryLocation.value)}打开`
})

function locationName(location: CodeExecutionLocation) {
  return location === 'local' ? '本机' : '远程'
}

function emitOpen(location: CodeExecutionLocation) {
  if (props.application[location]?.availability === 'ready') emit('open', location)
}
</script>

<style scoped>
.code-application-actions {
  display: inline-flex;
  align-items: stretch;
}

.code-location-more {
  width: 30px;
  min-width: 30px;
  padding: 0;
  border-left-color: color-mix(in srgb, var(--brand) 70%, white);
}

.apps-mini-action {
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.apps-mini-action.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
}

.apps-mini-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>
