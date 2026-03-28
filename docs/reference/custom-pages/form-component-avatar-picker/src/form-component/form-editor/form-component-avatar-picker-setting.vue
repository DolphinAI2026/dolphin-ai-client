<template>
  <div class="form-config-item form-config-avatar-picker-setting">
    <div class="label-wrapper">
      <el-form-item label="头像尺寸(px)">
        <el-input-number
          v-model="avatarSize"
          :min="24"
          :max="120"
          :step="4"
          size="mini"
        />
      </el-form-item>

      <el-form-item label="头像形状">
        <el-radio-group v-model="avatarShape" size="mini">
          <el-radio-button label="circle">圆形</el-radio-button>
          <el-radio-button label="square">方形</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="最大显示数量">
        <el-input-number
          v-model="maxDisplay"
          :min="1"
          :max="20"
          :step="1"
          size="mini"
        />
      </el-form-item>

      <el-form-item label="选择模式">
        <el-radio-group v-model="selectMode" size="mini">
          <el-radio-button label="single">单选</el-radio-button>
          <el-radio-button label="multiple">多选</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="显示姓名">
        <el-switch v-model="showName" />
      </el-form-item>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentAvatarPickerSetting',
  props: {
    widget: {
      type: Object,
      default() {
        return {}
      }
    }
  },
  computed: {
    customConfig() {
      if (!this.widget.customComponentConfig) {
        this.$set(this.widget, 'customComponentConfig', {})
      }
      return this.widget.customComponentConfig
    },
    avatarSize: {
      get() { return this.customConfig.avatarSize || 36 },
      set(val) { this.$set(this.customConfig, 'avatarSize', val) }
    },
    avatarShape: {
      get() { return this.customConfig.avatarShape || 'circle' },
      set(val) { this.$set(this.customConfig, 'avatarShape', val) }
    },
    maxDisplay: {
      get() { return this.customConfig.maxDisplay || 5 },
      set(val) { this.$set(this.customConfig, 'maxDisplay', val) }
    },
    selectMode: {
      get() { return this.customConfig.selectMode || 'single' },
      set(val) { this.$set(this.customConfig, 'selectMode', val) }
    },
    showName: {
      get() { return this.customConfig.showName !== false },
      set(val) { this.$set(this.customConfig, 'showName', val) }
    }
  }
}
</script>

<style lang="scss">
.form-config-avatar-picker-setting {
  .label-wrapper {
    padding: 0 8px;
  }
}
</style>
