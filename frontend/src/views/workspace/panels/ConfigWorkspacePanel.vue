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
      <div v-if="!appId" class="cwp-empty">未绑定应用</div>
      <div v-else-if="!menuId" class="cwp-empty">
        <p>选择左侧菜单开始配置</p>
      </div>
      <div v-else-if="menuType === 'CUSTOM'" class="cwp-empty">自定义页菜单请到低代码后台编辑</div>
      <InAppBrowser
        v-else-if="editorUrl"
        mode="trusted-url"
        :url="editorUrl"
        :title="menuName || '配置'"
      />
      <div v-else class="cwp-empty">
        <p>{{ editorMsg || '正在加载配置页…' }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ApaasMenuSidebar from '@/components/ApaasMenuSidebar.vue'
import InAppBrowser from '@/components/common/InAppBrowser.vue'
import { getEditorUrl } from '@/api/editorUrl'
import type { Binding } from '../binding'

const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()

const appId = computed(() => (props.binding.kind === 'app' ? props.binding.appId : null))

const menuId = ref<string | null>(null)
const menuName = ref('')
const formId = ref('')
const menuType = ref('')

const editorUrl = ref('')
const editorMsg = ref('')

async function loadEditorUrl() {
  editorUrl.value = ''
  editorMsg.value = ''
  if (!appId.value || !menuId.value) return
  if (menuType.value === 'CUSTOM') return
  try {
    const resp = await getEditorUrl(appId.value, {
      menu_type: menuType.value || 'MODEL',
      menu_id: menuId.value,
      form_id: formId.value || '',
    })
    if (resp?.ok && resp.url) {
      editorUrl.value = resp.url
    } else {
      editorMsg.value = resp?.message || '应用尚未部署到 aPaaS，无法打开配置页'
    }
  } catch (e: any) {
    editorMsg.value = e?.message || '加载配置页失败'
  }
}

function onMenuSelected(menu: any) {
  menuId.value = menu.menu_id
  menuName.value = menu.menu_name || ''
  formId.value = String(menu.form_id || '')
  menuType.value = (menu.menu_type || menu.menu_display || '').toUpperCase()
  loadEditorUrl()
}

function onMenusLoaded(_menus: any[], firstFormMenu: any | null) {
  if (firstFormMenu && !menuId.value) onMenuSelected(firstFormMenu)
}

watch(appId, () => {
  menuId.value = null
  menuName.value = ''
  formId.value = ''
  menuType.value = ''
  editorUrl.value = ''
  editorMsg.value = ''
})
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
.cwp-empty {
  padding: 24px;
  opacity: 0.5;
}
</style>
