<template>
  <section class="code-application-recovery" aria-live="polite" aria-label="应用位置恢复">
    <div>
      <h2>{{ title }}</h2>
      <p>{{ reason }}</p>
      <dl>
        <div><dt>原运行位置</dt><dd>{{ locationName(originalLocation) }}</dd></div>
        <div v-if="alternativeLocation"><dt>可用位置</dt><dd>{{ locationName(alternativeLocation) }}</dd></div>
      </dl>
    </div>
    <div class="code-application-recovery-actions">
      <button type="button" class="btn btn-secondary" :disabled="opening" @click="emit('retry')">重试原位置</button>
      <button v-if="alternativeLocation" type="button" class="btn btn-primary" :disabled="opening" @click="emit('open-other')">
        明确打开{{ locationName(alternativeLocation) }}位置
      </button>
      <button type="button" class="btn btn-ghost" :disabled="opening" @click="emit('back')">返回应用</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CodeExecutionLocation } from '@/api/codeRuntime'

export type CodeApplicationRecoveryState = 'local_missing' | 'remote_unavailable' | 'remembered_unavailable' | 'all_unavailable'
const props = defineProps<{ state: CodeApplicationRecoveryState; originalLocation: CodeExecutionLocation; alternativeLocation?: CodeExecutionLocation | null; opening?: boolean }>()
const emit = defineEmits<{ retry: []; 'open-other': []; back: [] }>()
const title = computed(() => props.state === 'local_missing' ? '本机应用目录不可用' : props.state === 'remote_unavailable' ? '远程应用位置暂不可用' : props.state === 'all_unavailable' ? '应用当前位置都不可用' : '已记住的运行位置不可用')
const reason = computed(() => props.state === 'local_missing' ? '本机目录缺失或当前没有读取权限。' : props.state === 'remote_unavailable' ? '远程环境当前无法提供这个应用。' : props.state === 'all_unavailable' ? '本机与远程位置当前都无法打开，应用和已有会话会保留。' : '系统不会自动切换位置，请由你确认后再打开另一位置。')
function locationName(location: CodeExecutionLocation) { return location === 'local' ? '本机' : '远程' }
</script>

<style scoped>
.code-application-recovery { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px; border: 1px solid var(--warn-border, #f5cf81); border-radius: var(--r-3, 8px); background: var(--warn-soft, #fffaeb); color: var(--text-2); }
.code-application-recovery h2, .code-application-recovery p { margin: 0; }
.code-application-recovery h2 { color: var(--text); font-size: 15px; font-weight: var(--fw-semibold, 600); line-height: 22px; }
.code-application-recovery p { margin-top: 4px; font-size: 13px; line-height: 20px; }
.code-application-recovery dl { display: flex; flex-wrap: wrap; gap: 12px 20px; margin: 10px 0 0; font-size: 12px; }
.code-application-recovery dl > div { display: flex; gap: 6px; }
.code-application-recovery dt { color: var(--text-3); }.code-application-recovery dd { margin: 0; color: var(--text); }
.code-application-recovery-actions { display: flex; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }.code-application-recovery-actions .btn { min-height: 30px; white-space: nowrap; }
@media (max-width: 760px) { .code-application-recovery { align-items: stretch; flex-direction: column; }.code-application-recovery-actions { justify-content: flex-start; } }
</style>
