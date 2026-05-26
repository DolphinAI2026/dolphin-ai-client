<template>
  <main class="stub">
    <div class="stub-head">
      <h1>文档</h1>
      <p>P3 接入 — 当前为占位页面</p>
    </div>
    <div class="stub-body">
      <p>这里将集中存放应用设计文档、需求文档、API 文档、运维手册等.</p>
      <p>支持版本对比与协同编辑.</p>
    </div>
  </main>
</template>

<script setup lang="ts">
</script>

<style scoped>
.stub {
  padding: 48px 64px;
  max-width: 1200px;
  margin: 0 auto;
  color: var(--t-text-primary);
}
.stub-head {
  padding-bottom: 24px;
  border-bottom: 1px solid var(--t-border-subtle);
  margin-bottom: 24px;
}
.stub-head h1 {
  margin: 0 0 8px;
  font-size: 32px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.stub-head p {
  margin: 0;
  font-size: 14px;
  color: var(--t-text-muted);
}
.stub-body {
  font-size: 14px;
  color: var(--t-text-secondary);
  line-height: 1.6;
}
.stub-body p {
  margin: 0 0 12px;
}
</style>
