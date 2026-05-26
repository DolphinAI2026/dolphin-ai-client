<!-- DictEditorPanel.vue — Native 字典编辑器 (master-detail layout).

  2026-05-26 design-v3 P1-N4: 数据 tab + 字典 sub-tab 选中, 右侧主区域显本面板.
  视觉跟原 apaas 字典页对齐: 左侧字典列表 + 右侧选项 table.

  数据源:
  - 左 list: section-content/dicts (已有)
  - 右 options: list_apaas_app_dicts with_options=True 一次拉 — 前端从 items[i].extra
    或现 fetch 时直接 with_options 拿. 走 /section-content/dicts 不传 with_options
    会拿空 options, 这里我们补一次 fetch 拿完整字典.

  CRUD P2: + 添加选项 / 编辑 disabled, 提示用配置助手.
-->
<template>
  <section class="dep" aria-label="字典管理">
    <div class="dep-master">
      <header class="dep-master-head">
        <span class="dep-master-title">数据字典</span>
        <span v-if="dicts.length" class="dep-master-count">{{ dicts.length }}</span>
      </header>

      <div class="dep-master-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input v-model="masterSearch" placeholder="搜索字典名" />
      </div>

      <div v-if="loadingMaster" class="dep-state">加载字典…</div>
      <div v-else-if="masterErr" class="dep-state dep-state-err">{{ masterErr }}</div>
      <ul v-else-if="filteredDicts.length" class="dep-master-list" role="list">
        <li
          v-for="d in filteredDicts"
          :key="d.id"
          class="dep-master-item"
          :class="{ active: d.id === selectedDictId }"
          @click="selectDict(d.id)"
        >
          <span class="dep-master-item-name">{{ d.name || '(未命名字典)' }}</span>
          <span v-if="d.code" class="dep-master-item-code">{{ d.code }}</span>
        </li>
      </ul>
      <div v-else class="dep-state dep-state-empty">
        <p v-if="masterSearch">无匹配「{{ masterSearch }}」</p>
        <p v-else>暂无字典</p>
        <p class="hint">用配置助手对话新建</p>
      </div>
    </div>

    <div class="dep-detail">
      <div v-if="!selectedDictId" class="dep-detail-empty">
        <div class="dep-detail-empty-icon">📚</div>
        <p>从左侧选择一个字典, 这里显该字典的选项</p>
      </div>
      <template v-else>
        <header class="dep-detail-head">
          <div>
            <h2 class="dep-detail-title">{{ selectedDictName || '字典' }}</h2>
            <p v-if="selectedDictCode" class="dep-detail-sub">
              <span class="dep-code">{{ selectedDictCode }}</span>
            </p>
          </div>
          <button class="dep-btn dep-btn-primary" @click="onAddOption">+ 添加选项</button>
        </header>

        <div v-if="loadingOptions" class="dep-state">加载选项…</div>
        <div v-else-if="optionsErr" class="dep-state dep-state-err">{{ optionsErr }}</div>
        <div v-else class="dep-table-wrap">
          <table class="dep-table">
            <thead>
              <tr>
                <th class="num">#</th>
                <th>选项名称</th>
                <th>选项编码</th>
                <th>显示顺序</th>
                <th>描述</th>
                <th class="ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="options.length === 0">
                <td colspan="6" class="empty">
                  <p>暂无选项</p>
                  <p class="hint">点击「+ 添加选项」, 或用配置助手对话新增</p>
                </td>
              </tr>
              <tr v-for="(o, i) in options" :key="o.code || i">
                <td class="num">{{ i + 1 }}</td>
                <td>
                  <span class="dep-opt-chip" :style="{ background: chipColor(i) }">
                    {{ o.name || '—' }}
                  </span>
                </td>
                <td class="mono">{{ o.code || '—' }}</td>
                <td class="muted">{{ i + 1 }}</td>
                <td class="muted">{{ o.description || '—' }}</td>
                <td class="ops">
                  <button class="dep-icon-btn" disabled title="P2 编辑选项">⋯</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import request from '@/utils/request'

interface DictRow {
  id: string
  name: string
  code: string
  extra?: any
}
interface OptionRow {
  code?: string
  name?: string
  description?: string
}

const props = defineProps<{
  appId: number
  apaasAppId?: string
  envId?: number
}>()

const dicts = ref<DictRow[]>([])
const loadingMaster = ref(false)
const masterErr = ref('')
const masterSearch = ref('')

const selectedDictId = ref<string>('')
const options = ref<OptionRow[]>([])
const loadingOptions = ref(false)
const optionsErr = ref('')

const filteredDicts = computed(() => {
  const kw = masterSearch.value.trim().toLowerCase()
  if (!kw) return dicts.value
  return dicts.value.filter(d =>
    (d.name || '').toLowerCase().includes(kw)
    || (d.code || '').toLowerCase().includes(kw),
  )
})

const selectedDict = computed(() => dicts.value.find(d => d.id === selectedDictId.value))
const selectedDictName = computed(() => selectedDict.value?.name || '')
const selectedDictCode = computed(() => selectedDict.value?.code || '')

// 简单 chip 配色循环 — 跟 design 字典页一致 (蓝/橙/绿/紫等)
const CHIP_COLORS = [
  'rgba(31, 114, 212, 0.12)',
  'rgba(245, 158, 11, 0.14)',
  'rgba(16, 163, 74, 0.14)',
  'rgba(168, 85, 247, 0.14)',
  'rgba(220, 38, 38, 0.10)',
]
function chipColor(i: number): string {
  return CHIP_COLORS[i % CHIP_COLORS.length]
}

function onAddOption() {
  alert('添加选项 — 当前请用右侧配置助手对话:\n"借阅状态字典加一个待审批选项"')
}

async function loadMaster() {
  if (!props.appId) return
  loadingMaster.value = true
  masterErr.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/dicts`,
    )
    if (resp?.ok) {
      dicts.value = (resp.items || []) as DictRow[]
      // auto-select first
      if (!selectedDictId.value && dicts.value.length > 0) {
        selectDict(dicts.value[0].id)
      }
    } else {
      masterErr.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    masterErr.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loadingMaster.value = false
  }
}

async function selectDict(dictId: string) {
  selectedDictId.value = dictId
  // P1 简化: options 暂时从 dict.extra 里读 (如果 backend 返了); 没返就空表
  // P2: 单独 endpoint /section-content/dicts/{dict_id}/options 拉完整
  const d = dicts.value.find(x => x.id === dictId)
  const raw = d?.extra || {}
  if (Array.isArray(raw.options)) {
    options.value = raw.options.map((o: any) => ({
      code: o.code || o.valueCode,
      name: o.name || o.valueName,
      description: o.description || o.desc,
    }))
  } else {
    // P0 兜底: 显空, 提示用 AI
    options.value = []
  }
  optionsErr.value = ''
}

watch(() => props.appId, () => loadMaster(), { immediate: true })
</script>

<style scoped>
.dep {
  display: flex;
  font-family: var(--font-sans);
  background: var(--bg);
  height: 100%;
  overflow: hidden;
  font-feature-settings: 'cv11', 'ss01';
}

.dep-master {
  width: 260px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dep-master-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.dep-master-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.dep-master-count {
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-2);
  padding: 1px 8px;
  border-radius: 999px;
}

.dep-master-search {
  position: relative;
  padding: 8px 12px;
  flex-shrink: 0;
}
.dep-master-search input {
  width: 100%;
  height: 30px;
  padding: 0 12px 0 32px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.dep-master-search input:focus { border-color: var(--brand); }
.dep-master-search svg {
  position: absolute;
  left: 22px;
  top: 16px;
  color: var(--text-4);
  pointer-events: none;
}

.dep-master-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px;
  flex: 1;
  overflow-y: auto;
}
.dep-master-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  margin-bottom: 1px;
}
.dep-master-item:hover {
  background: var(--surface-2);
}
.dep-master-item.active {
  background: var(--brand-soft);
}
.dep-master-item.active .dep-master-item-name {
  color: var(--brand);
  font-weight: 600;
}
.dep-master-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dep-master-item-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dep-detail {
  flex: 1;
  min-width: 0;
  padding: 28px 36px;
  overflow-y: auto;
}

.dep-detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
}
.dep-detail-empty-icon { font-size: 48px; line-height: 1; }
.dep-detail-empty p { margin: 0; font-size: 14px; }

.dep-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.dep-detail-title {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}
.dep-detail-sub {
  margin: 0;
}
.dep-code {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
}

.dep-btn {
  height: 32px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: background 0.12s;
}
.dep-btn-primary {
  background: var(--brand);
  color: #fff;
}
.dep-btn-primary:hover { background: var(--brand-hover); }

.dep-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.dep-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.dep-table th {
  text-align: left;
  padding: 11px 16px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.dep-table th.num { width: 50px; }
.dep-table th.ops { width: 60px; text-align: center; }
.dep-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.dep-table tr:last-child td { border-bottom: none; }
.dep-table .num { color: var(--text-4); }
.dep-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.dep-table .ops { text-align: center; }
.dep-table .muted { color: var(--text-3); }
.dep-table .empty {
  text-align: center;
  padding: 48px 16px;
  color: var(--text-4);
}
.dep-table .empty .hint { margin-top: 8px; font-size: 12px; }

.dep-opt-chip {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--brand);
}

.dep-icon-btn {
  width: 26px; height: 26px;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.dep-icon-btn:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.dep-icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.dep-state {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
}
.dep-state-err { color: var(--err); }
.dep-state-empty .hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-4);
}
</style>
