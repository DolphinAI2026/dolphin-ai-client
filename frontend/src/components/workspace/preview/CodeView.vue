<template>
  <iframe
    :src="iframeSrc"
    class="code-iframe"
    sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
const iframeSrc = computed(() => `${import.meta.env.BASE_URL}coding?embed=true&embed_nav=0`)
</script>

<style scoped>
.code-iframe { width: 100%; height: 100%; border: 0; display: block; }
</style>
