<template>
  <div class="form-config-item form-config-approval-flow-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="100px">
        <!-- 审批流程配置 -->

        <!-- 显示模式 -->
        <el-form-item label="显示模式">
          <el-select v-model="localConfig.displayMode" placeholder="请选择显示模式" @change="saveConfig">
            <el-option label="时间线" value="timeline" />
            <el-option label="卡片" value="card" />
            <el-option label="简洁" value="simple" />
          </el-select>
        </el-form-item>

        <!-- 是否显示头像 -->
        <el-form-item label="显示头像">
          <el-switch v-model="localConfig.showAvatar" @change="saveConfig" />
        </el-form-item>

        <!-- 是否显示时间 -->
        <el-form-item label="显示时间">
          <el-switch v-model="localConfig.showTime" @change="saveConfig" />
        </el-form-item>

        <!-- 是否显示审批意见 -->
        <el-form-item label="显示审批意见">
          <el-switch v-model="localConfig.showComment" @change="saveConfig" />
        </el-form-item>

        <!-- 节点类型筛选 -->
        <el-form-item label="显示节点类型">
          <el-checkbox-group v-model="localConfig.showNodeTypes" @change="saveConfig">
            <el-checkbox label="start">发起申请</el-checkbox>
            <el-checkbox label="approval">审批</el-checkbox>
            <el-checkbox label="cc">抄送</el-checkbox>
            <el-checkbox label="end">流程结束</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <!-- 默认展开状态 -->
        <el-form-item label="默认展开">
          <el-switch v-model="localConfig.defaultExpanded" @change="saveConfig" />
        </el-form-item>

        <!-- 流程方向 -->
        <el-form-item label="流程方向">
          <el-radio-group v-model="localConfig.flowDirection" @change="saveConfig">
            <el-radio label="vertical">垂直</el-radio>
            <el-radio label="horizontal">水平</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 空状态文本 -->
        <el-form-item label="空状态文本">
          <el-input
            v-model="localConfig.emptyText"
            placeholder="请输入空状态文本"
            @change="saveConfig"
            clearable
          />
        </el-form-item>

        <!-- 主题颜色 -->
        <el-form-item label="主题颜色">
          <el-color-picker v-model="localConfig.themeColor" @change="saveConfig" />
        </el-form-item>

      </el-form>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FormComponentApprovalFlowSetting',
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
        displayMode: 'timeline',      // 显示模式
        showAvatar: true,             // 是否显示头像
        showTime: true,              // 是否显示时间
        showComment: true,           // 是否显示审批意见
        showNodeTypes: ['start', 'approval', 'cc', 'end'], // 显示的节点类型
        defaultExpanded: true,       // 默认展开
        flowDirection: 'vertical',    // 流程方向
        emptyText: '暂无审批记录',    // 空状态文本
        themeColor: '#409EFF'         // 主题颜色
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
.form-config-approval-flow-setting {
  .setting-panel {
    padding: 12px;

    .el-form-item {
      margin-bottom: 12px;

      &:last-child {
        margin-bottom: 0;
      }
    }

    .el-checkbox-group,
    .el-radio-group {
      .el-checkbox,
      .el-radio {
        margin-right: 12px;
        margin-bottom: 4px;
      }
    }
  }
}
</style>
