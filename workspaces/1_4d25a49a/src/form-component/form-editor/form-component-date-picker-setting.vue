<template>
  <div class="form-config-item form-config-date-picker-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="100px">
        <!-- 占位符文本 -->
        <el-form-item label="占位提示">
          <el-input
            v-model="localConfig.placeholder"
            placeholder="请输入占位提示文本"
            @change="saveConfig"
          />
        </el-form-item>

        <!-- 日期显示格式 -->
        <el-form-item label="日期格式">
          <el-select
            v-model="localConfig.dateFormat"
            placeholder="请选择日期显示格式"
            style="width: 100%;"
            @change="saveConfig"
          >
            <el-option label="yyyy-MM-dd（2024-01-01）" value="yyyy-MM-dd" />
            <el-option label="yyyy/MM/dd（2024/01/01）" value="yyyy/MM/dd" />
            <el-option label="yyyy.MM.dd（2024.01.01）" value="yyyy.MM.dd" />
            <el-option label="yyyy年MM月dd日（2024年01月01日）" value="yyyy年MM月dd日" />
            <el-option label="MM-dd（01-01）" value="MM-dd" />
            <el-option label="MM/dd（01/01）" value="MM/dd" />
          </el-select>
        </el-form-item>

        <!-- 值格式 -->
        <el-form-item label="值格式">
          <el-select
            v-model="localConfig.valueFormat"
            placeholder="请选择值格式"
            style="width: 100%;"
            @change="saveConfig"
          >
            <el-option label="yyyy-MM-dd（2024-01-01）" value="yyyy-MM-dd" />
            <el-option label="yyyy/MM/dd（2024/01/01）" value="yyyy/MM/dd" />
            <el-option label="yyyyMMdd（20240101）" value="yyyyMMdd" />
            <el-option label="时间戳" value="timestamp" />
          </el-select>
        </el-form-item>

        <!-- 是否显示快捷选项 -->
        <el-form-item label="快捷选项">
          <el-switch
            v-model="localConfig.showShortcuts"
            @change="saveConfig"
          />
        </el-form-item>

        <!-- 快捷选项配置 -->
        <el-form-item v-if="localConfig.showShortcuts" label="快捷项">
          <div class="shortcuts-container">
            <el-checkbox
              v-model="localConfig.shortcutsConfig.week"
              label="本周"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.month"
              label="本月"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.quarter"
              label="本季度"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.year"
              label="本年"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.lastWeek"
              label="上周"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.lastMonth"
              label="上月"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.lastQuarter"
              label="上季度"
              @change="saveConfig"
            />
            <el-checkbox
              v-model="localConfig.shortcutsConfig.lastYear"
              label="去年"
              @change="saveConfig"
            />
          </div>
        </el-form-item>

        <!-- 是否可清空 -->
        <el-form-item label="可清空">
          <el-switch
            v-model="localConfig.clearable"
            @change="saveConfig"
          />
        </el-form-item>

        <!-- 是否禁用 -->
        <el-form-item label="是否禁用">
          <el-switch
            v-model="localConfig.disabled"
            @change="saveConfig"
          />
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>
<script>
export default {
  name: 'FormComponentDatePickerSetting',
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
        placeholder: '请选择日期范围',
        dateFormat: 'yyyy-MM-dd',
        valueFormat: 'yyyy-MM-dd',
        showShortcuts: true,
        shortcutsConfig: {
          week: true,
          month: true,
          quarter: true,
          year: true,
          lastWeek: false,
          lastMonth: false,
          lastQuarter: false,
          lastYear: false
        },
        clearable: true,
        disabled: false
      }
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
    const saved = this.widgetObj.customComponentConfig || {}
    // 合并保存的配置
    Object.keys(this.localConfig).forEach(key => {
      if (saved[key] !== undefined) {
        if (typeof saved[key] === 'object') {
          this.localConfig[key] = { ...this.localConfig[key], ...saved[key] }
        } else {
          this.localConfig[key] = saved[key]
        }
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
.form-config-date-picker-setting {
  .setting-panel {
    padding: 12px;
  }

  .shortcuts-container {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;

    .el-checkbox {
      margin-right: 0;
    }
  }
}
</style>
