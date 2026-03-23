<template>
  <div class="form-widget form-component-avatar-upload-list">
    <div
      v-if="formValue"
      class="list-avatar"
      :style="avatarStyle"
    >
      <img :src="formValue" class="list-avatar-img" />
    </div>
    <span v-else>-</span>
  </div>
</template>

<script>
export default {
  name: 'FormComponentFileUploadList',
  props: {
    componentConfig: { type: Object, default() { return {} } },
    formValue: { type: [String, Object, Array], default: '' },
    propKey: { type: String, default: '' }
  },
  computed: {
    avatarStyle() {
      const size = this.componentConfig?.customComponentConfig?.avatarSize || 40
      return {
        width: size + 'px',
        height: size + 'px',
        borderRadius: '50%',
        overflow: 'hidden',
        display: 'inline-block',
        verticalAlign: 'middle'
      }
    }
  }
}
</script>

<style lang="scss">
.form-component-avatar-upload-list {
  .list-avatar {
    border: 1px solid #ebeef5;
    background: #f5f7fa;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .list-avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}
</style>
