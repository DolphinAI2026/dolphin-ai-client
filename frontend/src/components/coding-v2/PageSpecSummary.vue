<template>
  <div class="page-spec">

    <!-- ── 路由 ── -->
    <section v-if="route" class="doc-section">
      <div class="sec-heading">路由</div>
      <table class="kv-table">
        <tbody>
          <tr>
            <td class="kv-key">router_name</td>
            <td><code>{{ route.router_name }}</code></td>
          </tr>
          <tr v-if="route.menu_title">
            <td class="kv-key">菜单标题</td>
            <td>{{ route.menu_title }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── 布局 ── -->
    <section v-if="layout" class="doc-section">
      <div class="sec-heading">布局</div>
      <code>{{ layout }}</code>
    </section>

    <!-- ── 数据源 ── -->
    <section v-if="dataSources.length" class="doc-section">
      <div class="sec-heading">数据源（{{ dataSources.length }}）</div>
      <ul class="item-list">
        <li v-for="(ds, i) in dataSources" :key="i" class="item-row">
          <span class="item-name">{{ ds.name }}</span>
          <span class="tag">{{ ds.type }}</span>
          <span v-if="ds.type === 'api'" class="item-detail">
            <code>{{ ds.method || 'GET' }} {{ ds.endpoint }}</code>
          </span>
        </li>
      </ul>
    </section>

    <!-- ── UI 区块 ── -->
    <section v-if="sections.length" class="doc-section">
      <div class="sec-heading">UI 区块（{{ sections.length }}）</div>
      <ul class="item-list">
        <li v-for="(s, i) in sections" :key="i" class="item-row">
          <span class="item-name">{{ s.name }}</span>
          <code class="type-code">{{ s.type }}</code>
          <span v-if="s.is_custom_type" class="custom-tag">自定义</span>
          <div v-if="s.config && Object.keys(s.config).length" class="cfg">
            <code>{{ fmtConfig(s.config) }}</code>
          </div>
        </li>
      </ul>
    </section>

    <!-- ── 三方依赖 ── -->
    <section v-if="thirdPartyDeps.length" class="doc-section">
      <div class="sec-heading">三方依赖</div>
      <div class="dep-row">
        <code v-for="d in thirdPartyDeps" :key="d" class="dep-chip">{{ d }}</code>
      </div>
    </section>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  spec: Record<string, any>
}>()

const route = computed(() => props.spec?.route)
const layout = computed(() => props.spec?.layout)
const dataSources = computed<any[]>(() => props.spec?.data_sources || [])
const sections = computed<any[]>(() => props.spec?.ui_sections || [])
const thirdPartyDeps = computed<string[]>(() => props.spec?.third_party_deps || [])

function fmtConfig(c: Record<string, any>): string {
  const s = JSON.stringify(c)
  return s.length > 160 ? s.slice(0, 160) + '…' : s
}
</script>

<style scoped>
.page-spec {
  display: flex;
  flex-direction: column;
}

/* ── Section ── */
.doc-section {
  padding: 20px 24px;
  border-bottom: 1px solid #f0f0f0;
}
.doc-section:last-child {
  border-bottom: none;
}
.sec-heading {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 14px;
}

/* ── 键值表 ── */
.kv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.kv-table tr:last-child td { border-bottom: none; }
.kv-table td {
  padding: 5px 10px 5px 0;
  border-bottom: 1px solid #f9fafb;
  vertical-align: top;
  color: #1f2937;
}
.kv-key {
  color: #6b7280;
  font-size: 12px;
  width: 90px;
  white-space: nowrap;
}

/* ── 列表 ── */
.item-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.item-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.item-name { font-weight: 500; color: #1f2937; font-size: 13px; }
.item-detail { color: #6b7280; }

.tag {
  padding: 1px 7px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 11px;
}
.type-code {
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
}
.custom-tag {
  padding: 1px 5px;
  border-radius: 3px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
}
.cfg {
  width: 100%;
  padding-left: 4px;
  color: #6b7280;
  font-size: 12px;
}

/* ── 依赖 ── */
.dep-row { display: flex; gap: 8px; flex-wrap: wrap; }
.dep-chip {
  font-size: 12px;
  background: #f3f4f6;
  color: #374151;
}

/* ── code 通用 ── */
code {
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  color: #374151;
}
</style>
