<template>
  <div style="height: 100vh; background: #f0f2f5;">
    <apaas-custom-avatar-picker ref="picker" />

    <!-- 调试按钮：模拟弹窗确认 -->
    <div class="debug-bar">
      <el-button type="primary" size="small" @click="getSelected">
        模拟弹窗确认（调用 getSelectedData）
      </el-button>
      <span v-if="debugResult" class="debug-result">
        已选 {{ debugResult.length }} 人:
        {{ debugResult.map(u => u.name).join(', ') }}
      </span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'PreviewApp',
  data() {
    return {
      debugResult: null,
    }
  },
  methods: {
    getSelected() {
      const picker = this.$refs.picker
      if (picker && typeof picker.getSelectedData === 'function') {
        this.debugResult = picker.getSelectedData()
        console.log('[debug] getSelectedData() =>', this.debugResult)
      }
    },
  },
}
</script>

<style>
.debug-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 48px;
  background: #fff;
  border-top: 2px solid #1890ff;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  z-index: 10001;
  box-shadow: 0 -2px 8px rgba(0,0,0,0.08);
}
.debug-result {
  font-size: 13px;
  color: #52c41a;
}
</style>
