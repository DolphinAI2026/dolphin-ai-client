<script setup lang="ts">
import { computed } from 'vue'
import type { Spec } from '@/types/spec'
import {
  dataLabel,
  fieldMeta,
  opLabel,
  roleName,
  scopeLabel,
  specTitle,
  specUpdatedText,
} from '@/utils/specDocument'

const props = defineProps<{
  spec: Spec | null | undefined
}>()

const documentTitle = computed(() => specTitle(props.spec))
const updatedDateText = computed(() => specUpdatedText(props.spec))
const pendingDecisions = computed(() =>
  (props.spec?.decisions_pending || []).filter((decision) => !decision.resolved)
)
</script>

<template>
  <article v-if="spec" class="spec-document">
    <header class="doc-head">
      <span>AI Builder 设计文档</span>
      <h1>{{ documentTitle }}</h1>
      <p v-if="updatedDateText">更新时间：{{ updatedDateText }} · 当前为 AI 草案，可继续通过对话调整。</p>
    </header>

    <section class="doc-section">
      <h2>1. 业务目标</h2>
      <template v-if="spec.goal">
        <p><strong>业务问题：</strong>{{ spec.goal.business_problem }}</p>
        <p><strong>系统简介：</strong>{{ spec.goal.summary }}</p>
      </template>
      <p v-else class="doc-empty">暂未形成业务目标。</p>
    </section>

    <section class="doc-section">
      <h2>2. 角色与使用范围</h2>
      <div v-if="spec.roles.length" class="doc-table-wrap">
        <table>
          <thead>
            <tr>
              <th>角色</th>
              <th>数据范围</th>
              <th>职责说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="role in spec.roles" :key="role.code">
              <td><strong>{{ role.name }}</strong><code>{{ role.code }}</code></td>
              <td>{{ scopeLabel(role.scope) }}</td>
              <td>{{ role.description || '待补充' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="doc-empty">暂未定义角色。</p>
    </section>

    <section class="doc-section">
      <h2>3. 数据对象与字段</h2>
      <div v-if="spec.objects.length" class="doc-object-list">
        <section v-for="object in spec.objects" :key="object.code" class="doc-object">
          <h3>{{ object.name }} <code>{{ object.code }}</code></h3>
          <p v-if="object.description">{{ object.description }}</p>
          <ul v-if="object.fields.length" class="doc-field-list">
            <li v-for="field in object.fields" :key="field.code">
              <span>{{ field.name }}</span>
              <small>{{ fieldMeta(field) }}</small>
            </li>
          </ul>
          <p v-else class="doc-empty">字段待补充。</p>
        </section>
      </div>
      <p v-else class="doc-empty">暂未生成数据对象。</p>
    </section>

    <section class="doc-section">
      <h2>4. 字典与选项</h2>
      <div v-if="spec.dicts.length" class="doc-chip-groups">
        <div v-for="dict in spec.dicts" :key="dict.code" class="doc-chip-group">
          <h3>{{ dict.name }} <code>{{ dict.code }}</code></h3>
          <div class="doc-chips">
            <span v-for="option in dict.options" :key="option.code">{{ option.name }}</span>
          </div>
        </div>
      </div>
      <p v-else class="doc-empty">暂未生成数据字典。</p>
    </section>

    <section class="doc-section">
      <h2>5. 权限策略</h2>
      <div v-if="spec.permissions.length" class="doc-table-wrap">
        <table>
          <thead>
            <tr>
              <th>对象</th>
              <th>角色</th>
              <th>操作</th>
              <th>数据范围</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="permission in spec.permissions" :key="permission.object_code">
              <tr v-for="(rule, index) in permission.rules" :key="`${permission.object_code}-${index}`">
                <td><code>{{ permission.object_code }}</code></td>
                <td>{{ roleName(spec, rule.role) }}</td>
                <td>{{ opLabel(rule.op) }}</td>
                <td>{{ dataLabel(rule.data) }}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-else class="doc-empty">暂未生成权限策略。</p>
    </section>

    <section v-if="pendingDecisions.length" class="doc-section pending">
      <h2>待确认问题</h2>
      <ol>
        <li v-for="decision in pendingDecisions" :key="decision.id">
          <strong>{{ decision.topic }}</strong>
          <p v-if="decision.why_blocking">{{ decision.why_blocking }}</p>
        </li>
      </ol>
    </section>
  </article>
</template>

<style scoped>
.spec-document {
  max-width: 980px;
  margin: 0 auto;
  padding: 30px 34px 42px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  background: var(--t-bg-panel);
  box-shadow: 0 16px 38px rgba(15, 23, 42, 0.05);
}

.doc-head {
  padding-bottom: 18px;
  border-bottom: 1px solid var(--t-border-subtle);
}

.doc-head span {
  color: var(--t-brand);
  font-size: 12px;
  font-weight: 800;
}

.doc-head h1 {
  margin: 8px 0;
  color: var(--t-text-primary);
  font-size: 30px;
  line-height: 1.2;
}

.doc-head p,
.doc-section p,
.doc-section li,
.doc-table-wrap td {
  color: var(--t-text-secondary);
  font-size: 14px;
  line-height: 1.75;
}

.doc-section {
  padding-top: 24px;
}

.doc-section h2 {
  margin: 0 0 12px;
  color: var(--t-text-primary);
  font-size: 18px;
}

.doc-section h3 {
  margin: 0 0 8px;
  color: var(--t-text-primary);
  font-size: 15px;
}

.doc-section code {
  margin-left: 7px;
  padding: 1px 6px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: var(--t-bg-input);
  color: var(--t-text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.doc-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
}

.doc-table-wrap table {
  width: 100%;
  border-collapse: collapse;
}

.doc-table-wrap th {
  padding: 10px 12px;
  text-align: left;
  color: var(--t-text-muted);
  font-size: 12px;
  background: var(--t-bg-input);
}

.doc-table-wrap td {
  padding: 11px 12px;
  border-top: 1px solid var(--t-border-subtle);
  vertical-align: top;
}

.doc-table-wrap td strong {
  display: block;
  color: var(--t-text-primary);
  font-size: 14px;
}

.doc-object-list,
.doc-chip-groups {
  display: grid;
  gap: 12px;
}

.doc-object {
  padding: 14px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  background: var(--t-bg-subtle);
}

.doc-field-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
}

.doc-field-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 0;
  border-top: 1px dashed var(--t-border-subtle);
}

.doc-field-list span {
  color: var(--t-text-primary);
  font-weight: 700;
}

.doc-field-list small {
  color: var(--t-text-muted);
}

.doc-chip-group {
  padding: 12px 14px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
}

.doc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.doc-chips span {
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  font-size: 12px;
}

.doc-section.pending {
  margin-top: 24px;
  padding: 18px;
  border: 1px solid var(--t-warning);
  border-radius: 12px;
  background: var(--t-warning-subtle);
}

.doc-section.pending ol {
  margin: 0;
  padding-left: 20px;
}

.doc-empty {
  color: var(--t-text-muted) !important;
}

@media (max-width: 900px) {
  .spec-document {
    padding: 22px 18px 30px;
  }

  .doc-head h1 {
    font-size: 24px;
  }
}
</style>
