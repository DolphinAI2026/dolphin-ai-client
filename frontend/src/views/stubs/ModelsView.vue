<template>
  <main class="stub">
    <div class="stub-head">
      <h1>模型</h1>
      <p>P3 接入 — 当前为占位页面</p>
    </div>
    <div class="stub-body">
      <p>这里将集中管理跨应用的业务对象与数据模型 (实体、关系、字典、枚举).</p>
      <p>支持模型仓库、复用、版本化, 以及与 [构建] 中表单 / 流程的双向绑定.</p>
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
