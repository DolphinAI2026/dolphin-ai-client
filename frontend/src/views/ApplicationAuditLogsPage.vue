<template>
  <BuilderFrame :breadcrumbs="[{ label: '应用设置' }, { label: '审计日志' }]">
    <main class="page">
      <h1>应用审计日志</h1>
      <AuditLogExplorer :application-id="applicationId" />
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import AuditLogExplorer from '@/components/audit/AuditLogExplorer.vue'

const route = useRoute()
const applicationId = computed(() => Number(route.params.id))
</script>

<style scoped>
.page {
  display: flex;
  height: 100%;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
}

h1 {
  margin: 0;
  font-size: 20px;
  letter-spacing: 0;
}

@media (max-width: 640px) {
  .page {
    gap: 12px;
    padding: 14px 12px;
  }
}
</style>
