<template>
  <div class="form-config-item form-config-screenshot-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="100px">
        <!-- 按钮文字 -->
        <el-form-item label="按钮文字">
          <el-input
            v-model="localConfig.buttonText"
            placeholder="请输入按钮文字"
            @change="saveConfig"
            maxlength="20"
            show-word-limit
          />
        </el-form-item>

        <!-- 最大文件大小 -->
        <el-form-item label="文件大小限制">
          <el-input-number
            v-model="localConfig.maxSize"
            :min="1"
            :max="50"
            :step="1"
            @change="saveConfig"
            controls-position="right"
            style="width: 100%;"
          />
          <span class="input-suffix">MB</span>
        </el-form-item>

        <!-- 允许的文件类型 -->
        <el-form-item label="文件类型">
          <el-checkbox-group v-model="selectedFileTypes" @change="handleFileTypeChange">
            <el-checkbox label=".jpg,.jpeg">JPG/JPEG</el-checkbox>
            <el-checkbox label=".png">PNG</el-checkbox>
            <el-checkbox label=".gif">GIF</el-checkbox>
            <el-checkbox label=".webp">WEBP</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <!-- 是否显示预览 -->
        <el-form-item label="显示预览">
          <el-switch
            v-model="localConfig.showPreview"
            @change="saveConfig"
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>

        <!-- 帮助说明 -->
        <el-form-item>
          <div class="setting-tips">
            <i class="el-icon-info"></i>
            <span>PC端点击截图将截取当前页面内容；移动端将调用系统相机或相册选择图片</span>
          </div>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentAiImageCompareSetting',
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
        buttonText: '截图',
        maxSize: 10,
        fileTypes: '.jpg,.jpeg,.png',
        showPreview: true
      },
      selectedFileTypes: ['.jpg,.jpeg', '.png']
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
  created() {
    // 恢复保存的配置
    const saved = this.widgetObj.customComponentConfig || {}
    Object.keys(this.localConfig).forEach(key => {
      if (saved[key] !== undefined) this.localConfig[key] = saved[key]
    })
    // 解析文件类型
    this.parseFileTypes()
  },
  methods: {
    saveConfig() {
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    },

    // 解析文件类型到复选框
    parseFileTypes() {
      const types = this.localConfig.fileTypes.split(',').map(t => t.trim().toLowerCase())
      this.selectedFileTypes = []
      // 预设的组合类型
      if (types.includes('.jpg') && types.includes('.jpeg')) {
        this.selectedFileTypes.push('.jpg,.jpeg')
      }
      if (types.includes('.png') && !this.selectedFileTypes.includes('.png')) {
        this.selectedFileTypes.push('.png')
      }
      if (types.includes('.gif') && !this.selectedFileTypes.includes('.gif')) {
        this.selectedFileTypes.push('.gif')
      }
      if (types.includes('.webp') && !this.selectedFileTypes.includes('.webp')) {
        this.selectedFileTypes.push('.webp')
      }
    },

    // 处理文件类型变化
    handleFileTypeChange(values) {
      const types = []
      values.forEach(v => {
        if (v === '.jpg,.jpeg') {
          types.push('.jpg', '.jpeg')
        } else {
          types.push(v)
        }
      })
      this.localConfig.fileTypes = types.join(',')
      this.saveConfig()
    }
  }
}
</script>

<style lang="scss">
.form-config-screenshot-setting {
  .setting-panel {
    padding: 12px;

    .input-suffix {
      margin-left: 8px;
      color: #909399;
      font-size: 12px;
    }

    .setting-tips {
      display: flex;
      align-items: flex-start;
      gap: 6px;
      padding: 8px 12px;
      background: #fdf6ec;
      border-radius: 4px;
      color: #e6a23c;
      font-size: 12px;
      line-height: 1.4;

      i {
        margin-top: 2px;
        flex-shrink: 0;
      }
    }

    .el-checkbox-group {
      .el-checkbox {
        margin-right: 16px;
        margin-bottom: 8px;
      }
    }
  }
}
</style>
