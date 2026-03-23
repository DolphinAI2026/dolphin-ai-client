<template>
  <div class="form-config-item form-config-material-verify-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="120px">
        <!-- AI识别配置 -->
        <div class="config-section">
          <div class="section-title">
            <i class="el-icon-microphone"></i>
            AI识别配置
          </div>

          <el-form-item label="启用AI识别">
            <el-switch
              v-model="localConfig.enableAI"
              @change="saveConfig"
            />
            <span class="config-tip">开启后支持AI图像识别物料</span>
          </el-form-item>

          <el-form-item label="AI模型" v-if="localConfig.enableAI">
            <el-select v-model="localConfig.aiModel" placeholder="请选择AI模型" @change="saveConfig">
              <el-option label="通用模型" value="general" />
              <el-option label="建材专用模型" value="materials" />
              <el-option label="精细识别模型" value="precise" />
            </el-select>
          </el-form-item>

          <el-form-item label="自动识别" v-if="localConfig.enableAI">
            <el-switch
              v-model="localConfig.autoRecognize"
              @change="saveConfig"
            />
            <span class="config-tip">上传照片后自动进行识别</span>
          </el-form-item>
        </div>

        <!-- 照片上传配置 -->
        <div class="config-section">
          <div class="section-title">
            <i class="el-icon-picture-outline"></i>
            照片上传配置
          </div>

          <el-form-item label="最大照片数量">
            <el-input-number
              v-model="localConfig.maxPhotoCount"
              :min="1"
              :max="20"
              size="small"
              @change="saveConfig"
            />
            <span class="config-tip">允许上传的最大照片张数</span>
          </el-form-item>
        </div>

        <!-- 报价单配置 -->
        <div class="config-section">
          <div class="section-title">
            <i class="el-icon-document"></i>
            报价单比对配置
          </div>

          <el-form-item label="匹配阈值">
            <el-slider
              v-model="localConfig.matchThreshold"
              :min="0.5"
              :max="1"
              :step="0.05"
              show-input
              size="small"
              @change="saveConfig"
            />
            <span class="config-tip">物料名称相似度达到此值视为匹配</span>
          </el-form-item>

          <el-form-item label="报价单表单">
            <el-select
              v-model="localConfig.quoteFormId"
              placeholder="请选择报价单表单"
              clearable
              filterable
              @change="saveConfig"
            >
              <el-option
                v-for="form in availableForms"
                :key="form.id"
                :label="form.name"
                :value="form.id"
              />
            </el-select>
            <span class="config-tip">选择用于比对的报价单表单</span>
          </el-form-item>

          <el-form-item label="物料名称字段" v-if="localConfig.quoteFormId">
            <el-select
              v-model="localConfig.materialNameField"
              placeholder="请选择物料名称字段"
              clearable
              @change="saveConfig"
            >
              <el-option
                v-for="field in availableFields"
                :key="field.code"
                :label="field.name"
                :value="field.code"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="数量字段" v-if="localConfig.quoteFormId">
            <el-select
              v-model="localConfig.quantityField"
              placeholder="请选择数量字段"
              clearable
              @change="saveConfig"
            >
              <el-option
                v-for="field in availableFields"
                :key="field.code"
                :label="field.name"
                :value="field.code"
              />
            </el-select>
          </el-form-item>
        </div>

        <!-- 字段映射说明 -->
        <div class="config-section">
          <div class="section-title">
            <i class="el-icon-info"></i>
            使用说明
          </div>
          <div class="help-text">
            <p>1. 启用AI识别后，用户上传现场物料照片时将自动调用AI模型进行图像识别</p>
            <p>2. AI将自动统计识别出的物料种类和数量</p>
            <p>3. 配置报价单后，可将识别结果与报价单进行自动比对</p>
            <p>4. 比对结果将显示匹配/不匹配状态，帮助验证执行真实性</p>
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
        enableAI: true,
        aiModel: 'general',
        quoteFormId: '',
        materialNameField: '',
        quantityField: '',
        matchThreshold: 0.8,
        maxPhotoCount: 10,
        autoRecognize: false
      },
      availableForms: [],
      availableFields: []
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
    }
  },
  created() {
    // 恢复已保存的配置
    const saved = this.widgetObj.customComponentConfig || {}
    Object.keys(this.localConfig).forEach(key => {
      if (saved[key] !== undefined) this.localConfig[key] = saved[key]
    })

    // 加载可用表单列表
    this.loadAvailableForms()

    // 加载可用字段
    if (this.localConfig.quoteFormId) {
      this.loadFormFields(this.localConfig.quoteFormId)
    }
  },
  watch: {
    'localConfig.quoteFormId'(newVal) {
      if (newVal) {
        this.loadFormFields(newVal)
      } else {
        this.availableFields = []
        this.localConfig.materialNameField = ''
        this.localConfig.quantityField = ''
      }
    }
  },
  methods: {
    saveConfig() {
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    },

    // 加载可用表单列表（从平台获取所有可用的业务表单）
    async loadAvailableForms() {
      try {
        // 调用平台API获取业务表单列表
        const result = await this.$request({
          url: '/xdap-app/business/v2/query/listBusinessObject',
          method: 'POST',
          data: {
            page: 1,
            pageSize: 100
          }
        }).asyncThen(res => res).asyncErrorCatch(err => {
          console.error('获取表单列表失败:', err)
          return null
        })

        if (result && result.data) {
          // 过滤出报价单相关的表单（可根据实际业务需求调整过滤条件）
          this.availableForms = result.data
            .filter(form => form.name && (
              form.name.includes('报价') ||
              form.name.includes('物料') ||
              form.name.includes('清单') ||
              form.objectCode // 保留所有有编码的表单供选择
            ))
            .map(form => ({
              id: form.id || form.objectId,
              name: form.name || form.objectName,
              objectCode: form.objectCode
            }))

          // 如果过滤后为空，使用全部表单
          if (this.availableForms.length === 0 && result.data.length > 0) {
            this.availableForms = result.data.map(form => ({
              id: form.id || form.objectId,
              name: form.name || form.objectName,
              objectCode: form.objectCode
            }))
          }
        }
      } catch (error) {
        console.error('加载表单列表失败:', error)
        // 如果API调用失败，尝试使用备选方式获取
        this.tryAlternativeFormLoad()
      }
    },

    // 备选的表单加载方式（如果主方式失败）
    tryAlternativeFormLoad() {
      // 尝试从 formEngine 获取表单列表
      if (this.engine && this.engine.getAllForms) {
        try {
          const forms = this.engine.getAllForms()
          if (forms && forms.length > 0) {
            this.availableForms = forms.map(form => ({
              id: form.id,
              name: form.name,
              objectCode: form.objectCode
            }))
            return
          }
        } catch (e) {
          console.error('从formEngine获取表单失败:', e)
        }
      }

      // 尝试使用 df.getEnv() 获取环境信息
      const env = this.$df ? this.$df.getEnv() : null
      if (env && env.businessObjects) {
        this.availableForms = env.businessObjects.map(bo => ({
          id: bo.id,
          name: bo.name,
          objectCode: bo.objectCode
        }))
        return
      }

      // 最后尝试从全局数据获取
      if (this.globalData && this.globalData.forms) {
        this.availableForms = this.globalData.forms
        return
      }

      // 所有方式都失败时，使用空数组并提示
      this.availableForms = []
      this.$message.warning('无法获取表单列表，请检查平台配置')
    },

    // 加载表单字段（根据选择的表单获取对应字段）
    async loadFormFields(formId) {
      if (!formId) {
        this.availableFields = []
        return
      }

      try {
        // 方式1：尝试调用平台API获取表单字段
        const result = await this.$request({
          url: '/xdap-app/business/v2/query/getBusinessObjectFields',
          method: 'POST',
          data: {
            objectId: formId
          }
        }).asyncThen(res => res).asyncErrorCatch(err => {
          console.error('获取表单字段失败:', err)
          return null
        })

        if (result && result.data) {
          this.availableFields = result.data.map(field => ({
            code: field.fieldCode || field.code,
            name: field.fieldName || field.name,
            type: field.fieldType || field.type || 'TEXT'
          }))
          return
        }
      } catch (error) {
        console.error('API获取字段失败:', error)
      }

      // 方式2：从 formItemList 中查找（如果提供了 formItemList prop）
      if (this.formItemList && this.formItemList.length > 0) {
        // 尝试从 formItemList 中推断字段
        this.availableFields = this.formItemList.map(item => ({
          code: item.fieldCode || item.code,
          name: item.label || item.name,
          type: item.type || 'TEXT'
        })).filter(f => f.code)
        if (this.availableFields.length > 0) return
      }

      // 方式3：使用平台标准字段接口
      try {
        const fieldResult = await this.$request({
          url: '/xdap-app/business/v2/query/listPageBusinessData',
          method: 'POST',
          data: {
            formId: formId,
            page: 1,
            pageSize: 1
          }
        }).asyncThen(res => res).asyncErrorCatch(() => null)

        if (fieldResult && fieldResult.columns) {
          this.availableFields = fieldResult.columns.map(col => ({
            code: col.fieldCode || col.code,
            name: col.label || col.name,
            type: col.type || 'TEXT'
          }))
          return
        }
      } catch (e) {
        console.error('字段API备选方式也失败:', e)
      }

      // 所有方式都失败
      this.availableFields = []
      this.$message.warning('无法获取表单字段，请手动输入字段映射')
    }
  }
}
</script>

<style lang="scss">
.form-config-material-verify-setting {
  .setting-panel {
    padding: 12px;
  }

  .config-section {
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #EBEEF5;

    &:last-child {
      border-bottom: none;
    }

    .section-title {
      font-size: 14px;
      font-weight: 500;
      color: #303133;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 6px;

      i {
        color: #409EFF;
      }
    }

    .config-tip {
      margin-left: 8px;
      font-size: 12px;
      color: #909399;
    }

    .el-form-item {
      margin-bottom: 12px;
    }

    .el-select {
      width: 200px;
    }

    .el-slider {
      width: 200px;
      display: inline-block;
    }

    .el-input-number {
      width: 120px;
    }
  }

  .help-text {
    font-size: 12px;
    color: #606266;
    line-height: 1.8;
    padding: 8px 12px;
    background: #F5F7FA;
    border-radius: 4px;

    p {
      margin: 4px 0;
    }
  }
}
</style>
