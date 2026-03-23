<template>
  <div class="form-config-item form-config-avatar-upload-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="110px">
        <!-- 头像尺寸 -->
        <el-form-item label="头像显示尺寸">
          <el-input-number
            v-model="localConfig.avatarSize"
            :min="30"
            :max="300"
            :step="10"
            size="mini"
            controls-position="right"
            @change="saveConfig"
          />
          <span class="unit-label">px（圆形）</span>
        </el-form-item>

        <!-- 最大文件大小 -->
        <el-form-item label="最大文件大小">
          <el-input-number
            v-model="localConfig.maxFileSize"
            :min="1"
            :max="50"
            :step="1"
            size="mini"
            controls-position="right"
            @change="saveConfig"
          />
          <span class="unit-label">MB</span>
        </el-form-item>

        <!-- 允许的文件格式 -->
        <el-form-item label="允许格式">
          <el-checkbox-group v-model="localConfig.allowTypes" @change="saveConfig">
            <el-checkbox label="jpg">JPG</el-checkbox>
            <el-checkbox label="jpeg">JPEG</el-checkbox>
            <el-checkbox label="png">PNG</el-checkbox>
            <el-checkbox label="gif">GIF</el-checkbox>
            <el-checkbox label="webp">WEBP</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <!-- 是否显示裁剪功能 -->
        <el-form-item label="启用裁剪">
          <el-switch
            v-model="localConfig.enableCrop"
            active-text="是"
            inactive-text="否"
            @change="saveConfig"
          />
        </el-form-item>

        <!-- 裁剪预览圆角 -->
        <el-form-item v-if="localConfig.enableCrop" label="裁剪形状">
          <el-radio-group v-model="localConfig.cropShape" size="mini" @change="saveConfig">
            <el-radio label="circle">圆形</el-radio>
            <el-radio label="square">方形</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 上传提示文字 -->
        <el-form-item label="提示文字">
          <el-input
            v-model="localConfig.tipText"
            size="mini"
            placeholder="自定义上传提示"
            maxlength="50"
            show-word-limit
            @change="saveConfig"
          />
        </el-form-item>
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
        avatarSize: 100,
        maxFileSize: 5,
        allowTypes: ['jpg', 'jpeg', 'png'],
        enableCrop: true,
        cropShape: 'circle',
        tipText: '支持 JPG/PNG，建议 200×200'
      }
    }
  },
  computed: {
    widgetObj() {
      return this.componentConfig || this.widget || {}
    }
  },
  created() {
    const saved = this.widgetObj.customComponentConfig || {}
    Object.keys(this.localConfig).forEach(key => {
      if (saved[key] !== undefined) {
        this.localConfig[key] = saved[key]
      }
    })
  },
  methods: {
    saveConfig() {
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    }
  }
}
</script>

<style lang="scss">
.form-config-avatar-upload-setting {
  .setting-panel {
    padding: 12px;
  }

  .unit-label {
    margin-left: 6px;
    font-size: 12px;
    color: #909399;
  }
}
</style>
