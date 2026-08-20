<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  title: string
  canGenerate?: boolean
  generating?: boolean
  saving?: boolean
}>(), {
  canGenerate: false,
  generating: false,
  saving: false,
})

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'update:title', value: string): void
  (event: 'generate'): void
  (event: 'save'): void
}>()

const titleInput = ref<{ focus: () => void } | null>(null)
const busy = computed(() => props.generating || props.saving)
const canSave = computed(() => Boolean(props.title.trim()) && !busy.value)

watch(
  () => props.modelValue,
  (open) => {
    if (open) void nextTick(() => titleInput.value?.focus())
  },
)

function close() {
  if (!busy.value) emit('update:modelValue', false)
}

function save() {
  if (canSave.value) emit('save')
}

function updateVisible(value: boolean) {
  if (!value) close()
}

function updateTitle(value: string) {
  emit('update:title', value)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="修改会话标题"
    width="460px"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @update:model-value="updateVisible"
  >
    <div class="session-title-field">
      <label for="session-title-input">会话标题</label>
      <div class="session-title-controls">
        <el-input
          id="session-title-input"
          ref="titleInput"
          :model-value="title"
          maxlength="80"
          show-word-limit
          placeholder="输入会话标题"
          @update:model-value="updateTitle"
          @keyup.enter="save"
        />
        <el-button
          v-if="canGenerate"
          class="session-title-generate"
          :loading="generating"
          :disabled="saving"
          @click="emit('generate')"
        >
          <AppIcon v-if="!generating" name="sparkles" :size="15" />
          AI 生成
        </el-button>
      </div>
    </div>

    <template #footer>
      <el-button :disabled="busy" @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSave" @click="save">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.session-title-field {
  display: grid;
  gap: 8px;
}

.session-title-field label {
  color: var(--text-2, #475569);
  font-size: 13px;
  font-weight: 600;
}

.session-title-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.session-title-generate {
  min-width: 96px;
}

.session-title-generate :deep(.app-icon) {
  margin-right: 6px;
}
</style>
