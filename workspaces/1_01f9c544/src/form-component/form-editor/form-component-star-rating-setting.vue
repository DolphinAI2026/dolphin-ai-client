<template>
  <div class="form-config-item form-config-star-rating-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="100px">
        <!-- 最大星数 -->
        <el-form-item label="最大星数">
          <el-input-number
            v-model="localConfig.maxStars"
            :min="1"
            :max="10"
            :step="1"
            controls-position="right"
            style="width: 100%;"
            @change="saveConfig"
          />
        </el-form-item>

        <!-- 支持半星 -->
        <el-form-item label="支持半星">
          <el-switch v-model="localConfig.allowHalf" @change="saveConfig" />
        </el-form-item>

        <!-- 选中颜色 -->
        <el-form-item label="选中颜色">
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-color-picker v-model="localConfig.activeColor" @change="saveConfig" size="mini" />
            <el-input v-model="localConfig.activeColor" size="mini" style="flex: 1;" @change="saveConfig" />
          </div>
        </el-form-item>

        <!-- 未选中颜色 -->
        <el-form-item label="未选中颜色">
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-color-picker v-model="localConfig.inactiveColor" @change="saveConfig" size="mini" />
            <el-input v-model="localConfig.inactiveColor" size="mini" style="flex: 1;" @change="saveConfig" />
          </div>
        </el-form-item>

        <!-- 尺寸 -->
        <el-form-item label="尺寸">
          <el-radio-group v-model="localConfig.size" @change="saveConfig" size="mini">
            <el-radio-button label="small">小</el-radio-button>
            <el-radio-button label="medium">中</el-radio-button>
            <el-radio-button label="large">大</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- 显示文字 -->
        <el-form-item label="显示文字">
          <el-switch v-model="localConfig.showText" @change="saveConfig" />
        </el-form-item>

        <!-- 评语文字 -->
        <el-form-item v-if="localConfig.showText" label="评语文字">
          <div style="width: 100%;">
            <div
              v-for="(text, index) in localTexts"
              :key="index"
              style="display: flex; align-items: center; margin-bottom: 4px; gap: 4px;"
            >
              <span style="min-width: 24px; color: #909399; font-size: 12px;">{{ index + 0.5 }}星:</span>
              <el-input
                v-model="localTexts[index]"
                size="mini"
                style="flex: 1;"
                @change="syncTexts"
              />
            </div>
          </div>
        </el-form-item>

        <!-- 预览 -->
        <el-form-item label="预览">
          <div style="padding: 8px; border: 1px dashed #dcdfe6; border-radius: 4px; background: #fafafa;">
            <span style="font-size: 12px; color: #909399;">
              预览将在设计器中显示实际效果
            </span>
          </div>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>
<script>
export default {
  name: 'FormComponentStarRatingSetting',
  props: {
    componentConfig: { default: null },
    formEngine: { default: null },
    widget: { default: null },
    editConfig: { default: null },
    configProperty: { default: null },
    formItemList: { default: null },
    formRule: { default: null },
    globalData: { default: null },
    widgetConfig: { default: null },
    disabled: { default: false }
  },
  inject: {
    renderGlobal: { default: null },
    getPreviewLanguage: { default: null },
    getI18nShowStatus: { default: null },
    filterTableFromNodeFields: { default: null }
  },
  data() {
    return {
      localConfig: {
        maxStars: 5,
        allowHalf: true,
        activeColor: '#FF9900',
        inactiveColor: '#E0E0E0',
        size: 'medium',
        showText: false,
        texts: ['极差', '差', '一般', '良好', '优秀']
      },
      localTexts: []
    }
  },
  computed: {
    widgetObj() {
      return this.componentConfig || this.widget || {}
    },
    engine() {
      if (this.formEngine) return this.formEngine
      if (this.renderGlobal) return this.renderGlobal
      return null
    },
    subTableList() {
      if (!this.engine || !this.engine.formDataControl) return []
      return (this.engine.formDataControl.allTileFormItemList || [])
        .filter(item => item.componentType === 'FORM_WIDGET_SON_TABLE')
    }
  },
  watch: {
    'localConfig.maxStars': function(newVal) {
      this.adjustTexts(newVal)
    }
  },
  created() {
    const saved = this.widgetObj.customComponentConfig || {}
    const defaultConfig = {
      maxStars: 5,
      allowHalf: true,
      activeColor: '#FF9900',
      inactiveColor: '#E0E0E0',
      size: 'medium',
      showText: false,
      texts: ['极差', '差', '一般', '良好', '优秀']
    }
    const merged = { ...defaultConfig, ...saved }
    Object.keys(this.localConfig).forEach(key => {
      this.localConfig[key] = merged[key]
    })
    this.localTexts = [...(this.localConfig.texts || [])]
  },
  methods: {
    adjustTexts(maxStars) {
      while (this.localTexts.length < maxStars) {
        this.localTexts.push('')
      }
      while (this.localTexts.length > maxStars) {
        this.localTexts.pop()
      }
      this.syncTexts()
    },
    syncTexts() {
      this.localConfig.texts = [...this.localTexts]
      this.saveConfig()
    },
    saveConfig() {
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    }
  }
}
</script>
<style lang="scss">
.form-config-star-rating-setting {
  .setting-panel {
    padding: 12px;
  }
}
</style>
