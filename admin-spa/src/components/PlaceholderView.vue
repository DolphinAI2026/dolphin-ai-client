<template>
  <div class="placeholder-view">
    <el-empty :description="description">
      <template #image>
        <el-icon :size="80" color="#909399"><component :is="icon" /></el-icon>
      </template>
      <h2 class="placeholder-title">{{ title }}</h2>
      <p v-if="subtitle" class="placeholder-sub">{{ subtitle }}</p>
      <el-alert
        v-if="todoHint"
        :title="todoHint"
        type="info"
        show-icon
        :closable="false"
        style="margin-top: 16px; text-align: left; max-width: 720px"
      />
    </el-empty>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
  description?: string
  icon: any
  todoHint?: string
}>()
</script>

<style scoped>
.placeholder-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 200px);
}
.placeholder-title {
  margin: 12px 0 6px;
  font-size: 18px;
  color: #303133;
}
.placeholder-sub {
  margin: 0;
  font-size: 13px;
  color: #909399;
}
</style>
