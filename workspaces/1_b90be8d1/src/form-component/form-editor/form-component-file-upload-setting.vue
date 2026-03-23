<template>
  <div class="form-config-item ai-image-recognition-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="120px">
        <!-- AI配置区域 -->
        <div class="setting-section">
          <div class="section-title">
            <i class="el-icon-magic-stick"></i>
            <span>AI分析配置</span>
          </div>

          <el-form-item label="AI接口地址">
            <el-input
              v-model="localConfig.aiApiUrl"
              placeholder="请输入AI接口地址"
              @change="saveConfig"
              clearable
            >
              <template slot="append">
                <el-tooltip content="AI图像识别接口的URL地址，留空则使用模拟分析">
                  <i class="el-icon-question"></i>
                </el-tooltip>
              </template>
            </el-input>
            <div class="form-tip">留空则使用模拟分析功能</div>
          </el-form-item>

          <el-form-item label="API密钥">
            <el-input
              v-model="localConfig.aiApiKey"
              placeholder="请输入API密钥"
              @change="saveConfig"
              type="password"
              show-password
              clearable
            ></el-input>
          </el-form-item>

          <el-form-item label="AI提示词">
            <el-input
              v-model="localConfig.aiPrompt"
              type="textarea"
              :rows="3"
              placeholder="请输入AI分析提示词"
              @change="saveConfig"
            ></el-input>
            <div class="form-tip">指导AI如何分析图片内容的提示语</div>
          </el-form-item>

          <el-form-item label="置信度阈值">
            <el-slider
              v-model="localConfig.confidenceThreshold"
              :min="0"
              :max="1"
              :step="0.1"
              :marks="{ 0: '0%', 0.5: '50%', 1: '100%' }"
              @change="saveConfig"
            ></el-slider>
            <div class="form-tip">高于此阈值的分析结果将被视为"通过"</div>
          </el-form-item>
        </div>

        <!-- 结果映射区域 -->
        <div class="setting-section">
          <div class="section-title">
            <i class="el-icon-connection"></i>
            <span>结果字段映射</span>
          </div>

          <el-form-item label="结果字段">
            <el-select
              v-model="localConfig.resultField"
              placeholder="请选择字段"
              @change="saveConfig"
              clearable
              filterable
            >
              <el-option
                v-for="field in availableFields"
                :key="field.uuid"
                :label="field.label"
                :value="field.uuid"
              ></el-option>
            </el-select>
            <div class="form-tip">AI分析结果（通过/不通过）将赋值到此字段</div>
          </el-form-item>

          <el-form-item label="原因字段">
            <el-select
              v-model="localConfig.reasonField"
              placeholder="请选择字段"
              @change="saveConfig"
              clearable
              filterable
            >
              <el-option
                v-for="field in availableFields"
                :key="field.uuid"
                :label="field.label"
                :value="field.uuid"
              ></el-option>
            </el-select>
            <div class="form-tip">AI分析原因将赋值到此字段</div>
          </el-form-item>
        </div>

        <!-- 上传配置区域 -->
        <div class="setting-section">
          <div class="section-title">
            <i class="el-icon-upload2"></i>
            <span>上传配置</span>
          </div>

          <el-form-item label="启用摄像头">
            <el-switch
              v-model="localConfig.enableCamera"
              @change="saveConfig"
            ></el-switch>
            <div class="form-tip">允许使用设备摄像头拍照上传</div>
          </el-form-item>

          <el-form-item label="启用文件上传">
            <el-switch
              v-model="localConfig.enableFileUpload"
              @change="saveConfig"
            ></el-switch>
            <div class="form-tip">允许从相册选择图片上传</div>
          </el-form-item>

          <el-form-item label="最大图片大小">
            <el-input-number
              v-model="localConfig.maxImageSize"
              :min="1"
              :max="20"
              :step="1"
              @change="saveConfig"
            ></el-input-number>
            <span class="unit">MB</span>
          </el-form-item>

          <el-form-item label="图片格式">
            <el-checkbox-group v-model="selectedFormats" @change="handleFormatChange">
              <el-checkbox label="jpg">JPG</el-checkbox>
              <el-checkbox label="jpeg">JPEG</el-checkbox>
              <el-checkbox label="png">PNG</el-checkbox>
              <el-checkbox label="bmp">BMP</el-checkbox>
              <el-checkbox label="webp">WEBP</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
        </div>

        <!-- 预览效果 -->
        <div class="setting-section preview-section">
          <div class="section-title">
            <i class="el-icon-view"></i>
            <span>效果预览</span>
          </div>
          <div class="preview-box">
            <div class="preview-icon">
              <i class="el-icon-picture-outline"></i>
            </div>
            <p class="preview-text">AI图片识别组件</p>
            <div class="preview-features">
              <span v-if="localConfig.enableCamera" class="feature-tag">
                <i class="el-icon-camera"></i> 摄像头
              </span>
              <span v-if="localConfig.enableFileUpload" class="feature-tag">
                <i class="el-icon-upload2"></i> 文件上传
              </span>
              <span class="feature-tag">
                <i class="el-icon-magic-stick"></i> AI分析
              </span>
            </div>
          </div>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentFileUploadSetting',
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
        aiApiUrl: '',
        aiApiKey: '',
        aiPrompt: '请分析这张图片，判断是否合格。如果合格返回"通过"，如果不合格返回"不通过"并说明原因。',
        resultField: '',
        reasonField: '',
        confidenceThreshold: 0.8,
        enableCamera: true,
        enableFileUpload: true,
        maxImageSize: 5,
        acceptedFormats: ['jpg', 'jpeg', 'png', 'bmp', 'webp']
      },
      selectedFormats: ['jpg', 'jpeg', 'png', 'bmp', 'webp']
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
    },
    availableFields() {
      // 获取所有可用字段，排除当前组件本身
      if (!this.engine || !this.engine.formDataControl) return []
      const allFields = this.engine.formDataControl.allTileFormItemList || []
      return allFields.filter(field =>
        field.uuid !== this.widgetObj.uuid &&
        field.componentType &&
        !field.componentType.includes('SON_TABLE') &&
        !field.componentType.includes('TAB')
      ).map(field => ({
        uuid: field.uuid,
        label: field.label || field.fieldName || field.uuid,
        fieldName: field.fieldName
      }))
    }
  },
  created() {
    this.loadConfig()
  },
  methods: {
    loadConfig() {
      const saved = this.widgetObj.customComponentConfig || {}
      Object.keys(this.localConfig).forEach(key => {
        if (saved[key] !== undefined) {
          this.localConfig[key] = saved[key]
        }
      })
      // 同步格式选择
      if (saved.acceptedFormats) {
        this.selectedFormats = [...saved.acceptedFormats]
      }
    },
    saveConfig() {
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    },
    handleFormatChange(val) {
      this.localConfig.acceptedFormats = [...val]
      this.saveConfig()
    }
  }
}
</script>

<style lang="scss" scoped>
.ai-image-recognition-setting {
  .setting-panel {
    padding: 12px;
    max-height: 600px;
    overflow-y: auto;
  }

  .setting-section {
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #ebeef5;

    &:last-child {
      border-bottom: none;
      margin-bottom: 0;
    }

    .section-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
      font-weight: 600;
      color: #303133;
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 2px solid #409eff;

      i {
        color: #409eff;
      }
    }
  }

  .form-tip {
    font-size: 12px;
    color: #909399;
    line-height: 1.4;
    margin-top: 4px;
  }

  .unit {
    margin-left: 8px;
    color: #606266;
  }

  .preview-section {
    .preview-box {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border-radius: 8px;
      padding: 24px;
      text-align: center;
      color: #fff;

      .preview-icon {
        font-size: 48px;
        margin-bottom: 8px;
        opacity: 0.9;
      }

      .preview-text {
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 12px;
      }

      .preview-features {
        display: flex;
        justify-content: center;
        gap: 8px;
        flex-wrap: wrap;

        .feature-tag {
          background: rgba(255, 255, 255, 0.2);
          padding: 4px 10px;
          border-radius: 12px;
          font-size: 12px;
          display: flex;
          align-items: center;
          gap: 4px;

          i {
            font-size: 14px;
          }
        }
      }
    }
  }

  ::v-deep {
    .el-slider__marks {
      font-size: 11px;
    }

    .el-checkbox-group {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
  }
}
</style>
