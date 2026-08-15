<template>
  <el-dialog
    :model-value="props.modelValue"
    title="关于 DolphinAI"
    width="460px"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <section class="desktop-about-dialog">
      <header class="desktop-about-header">
        <div class="desktop-about-mark" aria-hidden="true">D</div>
        <div>
          <h2>DolphinAI</h2>
          <p>桌面客户端</p>
        </div>
      </header>

      <dl class="desktop-about-details">
        <div>
          <dt>版本</dt>
          <dd>v{{ __APP_VERSION__ }}</dd>
        </div>
        <div>
          <dt>构建提交</dt>
          <dd>{{ shortRevision }}</dd>
        </div>
        <div>
          <dt>目标系统</dt>
          <dd>{{ buildTarget }}</dd>
        </div>
      </dl>

      <p v-if="errorText" class="desktop-about-error" role="alert">{{ errorText }}</p>

      <div v-if="desktopUpdateAvailable" class="desktop-about-update">
        <el-button type="primary" :loading="checking" @click="checkForUpdates">检查更新</el-button>
      </div>
      <p v-else class="desktop-about-unavailable">仅桌面客户端可用</p>
    </section>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { checkAndPromptUpdate } from '@/utils/desktop'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()

const checking = ref(false)
const errorText = ref('')
const desktopUpdateAvailable = __DESKTOP__ && !__DESKTOP_WEB_PREVIEW__
const shortRevision = computed(() => (__BUILD_REVISION__ || 'dev').slice(0, 12))
const buildTarget = computed(() => __BUILD_TARGET__ || 'unknown')

async function checkForUpdates() {
  checking.value = true
  errorText.value = ''
  try {
    await checkAndPromptUpdate({ silentIfNone: false })
  } catch (error) {
    console.warn('[desktop-about] update check failed', error)
    errorText.value = '检查更新失败，请稍后重试'
  } finally {
    checking.value = false
  }
}
</script>

<style>
.desktop-about-dialog { display: grid; gap: 20px; }
.desktop-about-header { display: flex; align-items: center; gap: 12px; }
.desktop-about-mark { display: grid; width: 44px; height: 44px; place-items: center; color: #fff; border-radius: 8px; background: #2878d4; font-size: 20px; font-weight: 700; }
.desktop-about-header h2 { margin: 0; color: var(--text); font-size: 18px; line-height: 24px; }
.desktop-about-header p { margin: 2px 0 0; color: var(--text-3); font-size: 12px; }
.desktop-about-details { display: grid; margin: 0; border-top: 1px solid var(--line); }
.desktop-about-details > div { display: flex; justify-content: space-between; gap: 16px; padding: 11px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
.desktop-about-details dt { color: var(--text-3); }
.desktop-about-details dd { margin: 0; color: var(--text); font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; text-align: right; word-break: break-word; }
.desktop-about-update { display: flex; justify-content: flex-end; }
.desktop-about-unavailable, .desktop-about-error { margin: 0; font-size: 12px; line-height: 18px; }
.desktop-about-unavailable { color: var(--text-3); }
.desktop-about-error { color: var(--danger); }
</style>
