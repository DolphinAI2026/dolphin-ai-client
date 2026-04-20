<template>
  <div class="be-spec">
    <section v-if="spec.package_name" class="block">
      <h3>包名</h3>
      <code>{{ spec.package_name }}</code>
    </section>

    <section v-if="endpoints.length" class="block">
      <h3>接口（{{ endpoints.length }}）</h3>
      <ul class="list">
        <li v-for="(ep, i) in endpoints" :key="i">
          <div class="ep-head">
            <span class="method" :class="'m-' + ep.method.toLowerCase()">{{ ep.method }}</span>
            <code class="path">{{ ep.path }}</code>
          </div>
          <div class="desc">{{ ep.description }}</div>
          <div v-if="ep.request && Object.keys(ep.request).length" class="params">
            <span class="k">入参：</span>
            <span v-for="(v, k) in ep.request" :key="k" class="param-chip">
              {{ k }}<span class="ty">:{{ v.type }}</span><span v-if="v.required">*</span>
            </span>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="tables.length" class="block">
      <h3>MpaaS 表使用</h3>
      <ul class="list">
        <li v-for="(t, i) in tables" :key="i">
          <code>{{ t.name }}</code>
          <span class="tag" :class="'access-' + t.access">{{ t.access }}</span>
        </li>
      </ul>
    </section>

    <section v-if="permissions.length" class="block">
      <h3>权限</h3>
      <ul class="dep-list">
        <li v-for="p in permissions" :key="p"><code>{{ p }}</code></li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  spec: Record<string, any>
}>()

const endpoints = computed<any[]>(() => props.spec?.endpoints || [])
const tables = computed<any[]>(() => props.spec?.mpaas_tables || [])
const permissions = computed<string[]>(() => props.spec?.permissions || [])
</script>

<style scoped>
.be-spec { display: flex; flex-direction: column; gap: 16px; }
.block h3 {
  font-size: 14px;
  margin: 0 0 8px;
  color: #1f2937;
  font-weight: 600;
}
.list { list-style: none; padding: 0; margin: 0; font-size: 13px; }
.list li {
  padding: 8px 0;
  border-top: 1px dashed #e5e7eb;
}
.list li:first-child { border-top: none; }
.ep-head { display: flex; align-items: center; gap: 8px; }
.method {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: white;
}
.m-get { background: #3b82f6; }
.m-post { background: #10b981; }
.m-put { background: #f59e0b; }
.m-delete { background: #ef4444; }
.path { font-size: 13px; }
.desc { margin-top: 4px; color: #374151; font-size: 12px; }
.params {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
}
.k { color: #6b7280; }
.param-chip {
  padding: 1px 6px;
  background: #f3f4f6;
  border-radius: 3px;
}
.ty { color: #6b7280; }
.tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}
.access-read { background: #dbeafe; color: #1d4ed8; }
.access-write { background: #fee2e2; color: #b91c1c; }
.access-readwrite { background: #fef3c7; color: #92400e; }
code {
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.dep-list { margin: 0; padding-left: 20px; }
</style>
