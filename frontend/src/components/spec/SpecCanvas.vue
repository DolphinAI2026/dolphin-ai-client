<script setup lang="ts">
import { computed } from 'vue'
import { useSpecStore } from '@/stores/spec'
import GoalCard from './SpecCanvas/GoalCard.vue'
import RoleCard from './SpecCanvas/RoleCard.vue'
import ObjectCard from './SpecCanvas/ObjectCard.vue'
import DictCard from './SpecCanvas/DictCard.vue'
import PermissionCard from './SpecCanvas/PermissionCard.vue'

const spec = useSpecStore()

const sections = computed(() => [
  { key: 'goal', label: '🎯 业务目标', count: spec.current?.goal ? 1 : 0 },
  { key: 'roles', label: '👥 角色', count: spec.current?.roles.length ?? 0 },
  { key: 'objects', label: '📋 数据对象', count: spec.current?.objects.length ?? 0 },
  { key: 'dicts', label: '📚 数据字典', count: spec.current?.dicts.length ?? 0 },
  { key: 'permissions', label: '🔒 权限', count: spec.current?.permissions.length ?? 0 },
])
</script>

<template>
  <div class="spec-canvas">
    <header v-if="!spec.current" class="empty-state">
      <p>尚未开始 SPEC 设计 — 在左侧聊天框输入需求开始</p>
    </header>
    <template v-else>
      <section v-for="sec in sections" :key="sec.key" class="canvas-section">
        <header class="section-header">
          <h3>{{ sec.label }} <span class="section-count">{{ sec.count }}</span></h3>
        </header>
        <div class="section-body">
          <GoalCard v-if="sec.key === 'goal' && spec.current.goal" :goal="spec.current.goal" />
          <template v-else-if="sec.key === 'roles'">
            <RoleCard v-for="role in spec.current.roles" :key="role.code" :role="role" />
          </template>
          <template v-else-if="sec.key === 'objects'">
            <ObjectCard v-for="obj in spec.current.objects" :key="obj.code" :object="obj" />
          </template>
          <template v-else-if="sec.key === 'dicts'">
            <DictCard v-for="dict in spec.current.dicts" :key="dict.code" :dict="dict" />
          </template>
          <template v-else-if="sec.key === 'permissions'">
            <PermissionCard v-for="perm in spec.current.permissions" :key="perm.object_code" :permission="perm" />
          </template>
          <p v-else class="empty-section">暂无</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.spec-canvas {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  background: var(--t-bg-base);
}
.empty-state {
  text-align: center;
  color: var(--t-text-muted);
  margin-top: 60px;
  font-size: 14px;
}
.canvas-section { margin-bottom: 24px; }
.section-header h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: var(--t-text-primary);
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.section-count {
  font-size: 12px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  padding: 1px 8px;
  border-radius: 10px;
}
.section-body { display: flex; flex-direction: column; gap: 8px; }
.empty-section { color: var(--t-text-muted); font-size: 13px; padding: 8px 0; }
</style>
