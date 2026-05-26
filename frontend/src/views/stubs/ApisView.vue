<template>
  <main class="stub">
    <div class="stub-head">
      <h1>接口</h1>
      <p>P3 接入 — 当前为占位页面</p>
    </div>
    <div class="stub-body">
      <p>这里将管理应用对外暴露的 REST / GraphQL 接口, 以及外部 API 引用.</p>
      <p>包含接口编排、参数 mapping、鉴权策略、调用日志.</p>
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
