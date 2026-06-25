<!-- 终端面板:多 tab PTY 终端管理器。一个 tab 一个独立 shell(跑 server / 敲命令互不干扰)。
     切 tab 不断连(server 继续跑);关 tab 杀该 shell;清屏/重连 作用于当前 tab。 -->
<template>
  <div class="term-panel">
    <div class="term-toolbar">
      <div class="term-tabs">
        <button
          v-for="t in tabs"
          :key="t.id"
          class="term-tab"
          :class="{ active: t.id === activeId }"
          @click="activate(t.id)"
        >
          <span class="term-tab-dot" :class="'is-' + (states[t.id] || 'idle')" />
          <span class="term-tab-name">终端 {{ t.n }}</span>
          <span v-if="tabs.length > 1" class="term-tab-x" title="关闭" @click.stop="closeTab(t.id)">×</span>
        </button>
        <button class="term-add" title="新建终端" @click="addTab()">＋</button>
      </div>
      <span class="term-spacer" />
      <span class="term-state" :class="'is-' + (states[activeId] || 'idle')">{{ stateLabel }}</span>
      <button class="term-tbtn" title="清屏" @click="activeTab?.clear()">清屏</button>
      <button class="term-tbtn" title="重连" @click="activeTab?.reconnect()">重连</button>
    </div>
    <div class="term-bodies">
      <div v-for="t in tabs" :key="t.id" v-show="t.id === activeId" class="term-body-slot">
        <TerminalTab
          :ref="(el) => setTabRef(t.id, el)"
          :ws-id="wsId"
          @state="(s) => (states[t.id] = s)"
          @server-detected="(p) => emit('server-detected', p)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick } from 'vue'
import TerminalTab from './TerminalTab.vue'

defineProps<{ wsId: string }>()
const emit = defineEmits<{ (e: 'server-detected', p: { url: string; port: number }): void }>()

interface Tab { id: number; n: number }
let seq = 0
const tabs = ref<Tab[]>([{ id: ++seq, n: 1 }])
const activeId = ref(tabs.value[0].id)
const states = reactive<Record<number, 'idle' | 'open' | 'closed'>>({})
const tabRefs = reactive<Record<number, any>>({})

function setTabRef(id: number, el: any) {
  if (el) tabRefs[id] = el
  else delete tabRefs[id]
}
const activeTab = computed(() => tabRefs[activeId.value])
const stateLabel = computed(() => {
  const s = states[activeId.value]
  return s === 'open' ? '已连接' : s === 'closed' ? '已断开' : '未连接'
})

function activate(id: number) {
  activeId.value = id
  nextTick(() => tabRefs[id]?.refit())
}
function addTab() {
  const t = { id: ++seq, n: tabs.value.length + 1 }
  tabs.value.push(t)
  activate(t.id)
}
function closeTab(id: number) {
  const idx = tabs.value.findIndex((t) => t.id === id)
  if (idx < 0 || tabs.value.length <= 1) return
  tabs.value.splice(idx, 1) // TerminalTab 卸载 → 其 onBeforeUnmount 关 WS 杀 shell
  delete states[id]
  delete tabRefs[id]
  if (activeId.value === id) activate(tabs.value[Math.max(0, idx - 1)].id)
}
</script>

<style scoped>
.term-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--cx-bg-0); }
.term-toolbar {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 10px 0; border-bottom: 1px solid var(--cx-border);
  font-size: 12px; flex-shrink: 0;
}
.term-tabs { display: flex; align-items: flex-end; gap: 2px; }
.term-tab {
  display: inline-flex; align-items: center; gap: 6px;
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: var(--cx-text-3); font-size: 12px; padding: 6px 10px; cursor: pointer;
}
.term-tab:hover { color: var(--cx-text-1); }
.term-tab.active { color: var(--cx-text-1); border-bottom-color: var(--cx-brand); }
.term-tab-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cx-text-3); }
.term-tab-dot.is-open { background: var(--cx-green); }
.term-tab-dot.is-closed { background: var(--cx-red); }
.term-tab-x { color: var(--cx-text-3); font-size: 14px; line-height: 1; padding: 0 2px; border-radius: 3px; }
.term-tab-x:hover { background: var(--cx-bg-3); color: var(--cx-text-1); }
.term-add {
  background: transparent; border: none; color: var(--cx-text-2);
  font-size: 15px; cursor: pointer; padding: 4px 8px; border-radius: 4px;
}
.term-add:hover { background: var(--cx-bg-3); color: var(--cx-text-1); }
.term-spacer { flex: 1; }
.term-state { font-family: var(--cx-mono); font-size: 11px; color: var(--cx-text-3); }
.term-state.is-open { color: var(--cx-green); }
.term-state.is-closed { color: var(--cx-red); }
.term-tbtn {
  background: transparent; border: 1px solid var(--cx-border); color: var(--cx-text-2);
  border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; margin-bottom: 4px;
}
.term-tbtn:hover { background: var(--cx-bg-3); color: var(--cx-text-1); }
.term-bodies { flex: 1; min-height: 0; position: relative; }
.term-body-slot { position: absolute; inset: 0; }
</style>
