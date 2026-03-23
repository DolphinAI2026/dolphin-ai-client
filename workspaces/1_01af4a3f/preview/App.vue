<template>
  <div style="min-height: 100vh;">
    <apaas-custom-map-view ref="mapView" />
  </div>
</template>

<script>
export default {
  name: 'PreviewApp',
  mounted() {
    // 暴露组件实例供信息窗体事件使用
    if (typeof window !== 'undefined') {
      window._mapViewInstance = this.$refs.mapView
    }
  },
}
</script>
