<!-- Codex 风命令面板浮层。⌘K 触发,↑↓Enter/Esc 键盘可达。
     Teleport 到 body → 根节点挂 .codex-skin 让 codex-tokens.css 的 --cx-* 生效。 -->
<template>
  <Teleport to="body">
    <Transition name="cmdp-fade">
      <div v-if="open" class="cmdp-mask codex-skin" @click.self="$emit('close')">
        <div class="cmdp-card" role="dialog" aria-label="命令面板">
          <input
            ref="inputEl"
            v-model="query"
            class="cmdp-input"
            type="text"
            placeholder="跳转到面板…"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="choose()"
            @keydown.esc.prevent="$emit('close')"
          />
          <div class="cmdp-list">
            <button
              v-for="(c, i) in filtered"
              :key="c.id"
              class="cmdp-row"
              :class="{ 'is-active': i === activeIdx }"
              @click="$emit('select', c.id)"
              @mousemove="activeIdx = i"
            >
              <AppIcon :name="c.icon" :size="15" class="cmdp-row-icon" />
              <span class="cmdp-row-label">{{ c.label }}</span>
              <span v-if="c.hotkeyLabel" class="cmdp-hotkey">
                <span v-for="(seg, si) in hotkeySegs(c.hotkeyLabel)" :key="si" class="cmdp-key">{{ seg }}</span>
              </span>
            </button>
            <p v-if="!filtered.length" class="cmdp-empty">无匹配命令</p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { CodexCommand, CodexCommandId } from './useCodexPanels'

const props = defineProps<{ open: boolean; commands: CodexCommand[] }>()
const emit = defineEmits<{ (e: 'select', id: CodexCommandId): void; (e: 'close'): void }>()

const query = ref('')
const activeIdx = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.commands
  return props.commands.filter(
    (c) => c.label.toLowerCase().includes(q) || c.id.toLowerCase().includes(q),
  )
})

function move(delta: number) {
  const n = filtered.value.length
  if (!n) return
  activeIdx.value = (activeIdx.value + delta + n) % n
}
function choose() {
  const c = filtered.value[activeIdx.value]
  if (c) emit('select', c.id)
}
/** '⌃⇧G' → ['⌃','⇧','G'];'⌘T' → ['⌘','T'];'⌥⌘S' → ['⌥','⌘','S']。 */
function hotkeySegs(label: string): string[] {
  return Array.from(label)
}

watch(
  () => props.open,
  (v) => {
    if (v) {
      query.value = ''
      activeIdx.value = 0
      nextTick(() => inputEl.value?.focus())
    }
  },
)
watch(filtered, () => {
  if (activeIdx.value >= filtered.value.length) activeIdx.value = 0
})
</script>

<style scoped>
.cmdp-mask {
  position: fixed;
  inset: 0;
  z-index: 4000;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14vh;
}
.cmdp-card {
  width: 480px;
  max-width: 90vw;
  background: var(--cx-bg-2);
  border: 1px solid var(--cx-border-hi);
  border-radius: 12px;
  box-shadow: var(--cx-shadow-pop);
  overflow: hidden;
}
.cmdp-input {
  width: 100%;
  box-sizing: border-box;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--cx-border);
  color: var(--cx-text-1);
  font-size: 14px;
  padding: 14px 16px;
  outline: none;
}
.cmdp-input::placeholder { color: var(--cx-text-3); }
.cmdp-list { padding: 6px; max-height: 320px; overflow-y: auto; }
.cmdp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: transparent;
  border: none;
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--cx-text-1);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}
.cmdp-row.is-active { background: var(--cx-bg-3); }
.cmdp-row-icon { color: var(--cx-text-2); flex-shrink: 0; }
.cmdp-row-label { flex: 1; }
.cmdp-hotkey { display: inline-flex; gap: 3px; }
.cmdp-key {
  font-family: var(--cx-mono);
  font-size: 11px;
  color: var(--cx-text-3);
  background: var(--cx-bg-1);
  border: 1px solid var(--cx-border-hi);
  border-radius: 4px;
  min-width: 16px;
  text-align: center;
  padding: 1px 4px;
}
.cmdp-empty { color: var(--cx-text-3); font-size: 13px; padding: 12px; margin: 0; text-align: center; }
.cmdp-fade-enter-active, .cmdp-fade-leave-active { transition: opacity 0.15s ease; }
.cmdp-fade-enter-from, .cmdp-fade-leave-to { opacity: 0; }
</style>
