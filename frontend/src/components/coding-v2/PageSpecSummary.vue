<template>
  <div class="page-spec">
    <section v-if="route" class="block">
      <h3>路由</h3>
      <div class="kv">
        <div><span class="k">router_name</span><code>{{ route.router_name }}</code></div>
        <div><span class="k">menu_title</span>{{ route.menu_title }}</div>
      </div>
    </section>

    <section v-if="layout" class="block">
      <h3>布局</h3>
      <code>{{ layout }}</code>
    </section>

    <section v-if="dataSources.length" class="block">
      <h3>数据源（{{ dataSources.length }}）</h3>
      <ul class="list">
        <li v-for="(ds, i) in dataSources" :key="i">
          <strong>{{ ds.name }}</strong>
          <span class="tag">{{ ds.type }}</span>
          <span v-if="ds.type === 'api'">
            <code>{{ ds.method || 'GET' }} {{ ds.endpoint }}</code>
          </span>
        </li>
      </ul>
    </section>

    <section v-if="sections.length" class="block">
      <h3>UI 区块（{{ sections.length }}）</h3>
      <ul class="list">
        <li v-for="(s, i) in sections" :key="i">
          <strong>{{ s.name }}</strong>
          <code class="type">{{ s.type }}</code>
          <span v-if="s.is_custom_type" class="custom-tag">自定义</span>
          <div v-if="s.config && Object.keys(s.config).length" class="cfg">
            <code>{{ fmtConfig(s.config) }}</code>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="thirdPartyDeps.length" class="block">
      <h3>三方依赖</h3>
      <ul class="dep-list">
        <li v-for="d in thirdPartyDeps" :key="d"><code>{{ d }}</code></li>
      </ul>
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
.page-spec { display: flex; flex-direction: column; gap: 16px; }
.block h3 {
  font-size: 14px;
  margin: 0 0 8px;
  color: #1f2937;
  font-weight: 600;
}
.kv { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.k { min-width: 110px; color: #6b7280; font-size: 12px; display: inline-block; }
.list { list-style: none; padding: 0; margin: 0; font-size: 13px; }
.list li {
  padding: 6px 0;
  border-top: 1px dashed #e5e7eb;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.list li:first-child { border-top: none; }
.tag {
  padding: 1px 6px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 11px;
}
.type { background: #f3f4f6; padding: 1px 6px; border-radius: 3px; font-size: 12px; }
.custom-tag {
  padding: 1px 6px;
  border-radius: 3px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
}
.cfg {
  width: 100%;
  margin-top: 4px;
  padding-left: 10px;
  color: #6b7280;
  font-size: 12px;
}
code {
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.dep-list { margin: 0; padding-left: 20px; }
</style>
