<template>
  <div class="config-ws-panel">
    <ApaasMenuSidebar
      class="cwp-menus"
      :app-id="appId"
      :selected-menu-id="menuId"
      @menu-selected="onMenuSelected"
      @menus-loaded="onMenusLoaded"
    />
    <div class="cwp-main">
      <header class="cwp-bar">
        <nav class="cwp-subtabs">
          <button
            v-for="t in subtabs"
            :key="t.key"
            :class="{ on: sub === t.key }"
            :disabled="t.key === 'perm' && !formId"
            @click="sub = t.key"
          >{{ t.label }}</button>
        </nav>
        <div class="cwp-bar-right">
          <button class="cwp-refresh" title="刷新" @click="refreshNonce++">刷新</button>
          <OpenLowcodeBackendButton
            v-if="appId"
            :app-id="appId"
            :menu-type="menuType || 'MODEL'"
            :menu-id="menuId || ''"
            :form-id="formId || null"
          />
        </div>
      </header>
      <div class="cwp-body">
        <div v-if="!appId" class="cwp-empty">未绑定应用</div>
        <div v-else-if="menuType === 'CUSTOM'" class="cwp-empty">自定义页菜单请到低代码后台编辑</div>
        <FormDesignerPanel
          v-else-if="sub === 'form'"
          :key="`form-${menuId}`"
          :app-id="appId"
          :menu-id="menuId || undefined"
          :menu-name="menuName"
          :form-id="formId || undefined"
          :refresh-nonce="refreshNonce"
        />
        <DataSchemaEditor
          v-else-if="sub === 'data'"
          :key="`data-${menuId}`"
          :app-id="appId"
          :menu-id="menuId || undefined"
          :menu-name="menuName"
          :form-id="formId || undefined"
          :refresh-nonce="refreshNonce"
        />
        <ProcessDesignerPanel
          v-else-if="sub === 'process'"
          :key="`proc-${menuId}-${refreshNonce}`"
          :app-id="appId"
          :menu-id="menuId || undefined"
          :menu-name="menuName"
          :form-id="formId || undefined"
          :hide-lowcode-btn="true"
        />
        <FormPermPanel
          v-else-if="sub === 'perm' && formId"
          :app-id="appId"
          :form-id="formId"
          :menu-name="menuName"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ApaasMenuSidebar from '@/components/ApaasMenuSidebar.vue'
import FormDesignerPanel from '@/components/v3/FormDesignerPanel.vue'
import DataSchemaEditor from '@/components/v3/DataSchemaEditor.vue'
import ProcessDesignerPanel from '@/components/v3/ProcessDesignerPanel.vue'
import FormPermPanel from '@/components/v3/FormPermPanel.vue'
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
import type { Binding } from '../binding'

const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()

const appId = computed(() => (props.binding.kind === 'app' ? props.binding.appId : null))

const subtabs = [
  { key: 'form' as const, label: '表单' },
  { key: 'data' as const, label: '数据' },
  { key: 'process' as const, label: '流程' },
  { key: 'perm' as const, label: '权限' },
]

const sub = ref<'form' | 'data' | 'process' | 'perm'>('form')
const menuId = ref<string | null>(null)
const menuName = ref('')
const formId = ref('')
const menuType = ref('')
const refreshNonce = ref(0)

function onMenuSelected(menu: any) {
  menuId.value = menu.menu_id
  menuName.value = menu.menu_name
  formId.value = String(menu.form_id || '')
  menuType.value = menu.menu_type || ''
  if (sub.value === 'perm' && !formId.value) sub.value = 'form'
}

function onMenusLoaded(_menus: any[], firstFormMenu: any | null) {
  if (firstFormMenu && !menuId.value) onMenuSelected(firstFormMenu)
}
</script>

<style scoped>
.config-ws-panel {
  display: flex;
  height: 100%;
  min-height: 0;
}
.cwp-menus {
  width: 200px;
  min-width: 180px;
  border-right: 1px solid var(--line);
  overflow: auto;
  flex-shrink: 0;
}
.cwp-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.cwp-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.cwp-subtabs {
  display: flex;
  gap: 2px;
}
.cwp-subtabs button {
  padding: 4px 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  color: var(--text-3);
}
.cwp-subtabs button.on {
  background: var(--brand-soft, rgba(99, 102, 241, 0.1));
  color: var(--brand);
}
.cwp-subtabs button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.cwp-bar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cwp-refresh {
  padding: 4px 8px;
  border: 1px solid var(--line);
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  color: var(--text-2);
  font-size: 12px;
}
.cwp-refresh:hover {
  background: var(--surface-1);
}
.cwp-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.cwp-empty {
  padding: 24px;
  opacity: 0.5;
}
</style>
