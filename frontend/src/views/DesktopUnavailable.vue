<template>
  <div class="du-wrap">
    <h2>此功能在桌面版不可用</h2>
    <p>该功能依赖在线平台管理控制台，桌面版未包含。请在浏览器中使用在线版，或返回主界面继续配置/二次开发。</p>
    <el-button type="primary" @click="$router.replace('/')">返回主界面</el-button>
  </div>
</template>
<script setup lang="ts"></script>
<style scoped>
.du-wrap { max-width: 520px; margin: 96px auto; text-align: center; }
.du-wrap p { color: var(--el-text-color-secondary); margin: 16px 0 24px; }
</style>
