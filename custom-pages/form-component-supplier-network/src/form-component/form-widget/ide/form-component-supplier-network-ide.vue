<template>
  <x-proxy-form-item
    :widget="widget"
    :validate-info="validateInfo"
    :validate-key="validateKey"
    :form-data="formData"
    :rules="[]"
    :render-scene="renderScene"
  >
    <div class="supplier-network-ide">
      <div class="supplier-network-ide__preview">
        <div class="ide-placeholder">
          <div class="ide-placeholder__icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24">
              <circle cx="12" cy="6" r="2.5" fill="#409EFF"/>
              <circle cx="5" cy="17" r="2.5" fill="#67C23A"/>
              <circle cx="19" cy="17" r="2.5" fill="#E6A23C"/>
              <circle cx="12" cy="17" r="2" fill="#F56C6C"/>
              <line x1="12" y1="8.5" x2="5" y2="14.5" stroke="#DCDFE6" stroke-width="1.2"/>
              <line x1="12" y1="8.5" x2="19" y2="14.5" stroke="#DCDFE6" stroke-width="1.2"/>
              <line x1="12" y1="8.5" x2="12" y2="15" stroke="#DCDFE6" stroke-width="1.2"/>
              <line x1="7.5" y1="17" x2="10" y2="17" stroke="#DCDFE6" stroke-width="1"/>
              <line x1="14" y1="17" x2="16.5" y2="17" stroke="#DCDFE6" stroke-width="1"/>
            </svg>
          </div>
          <div class="ide-placeholder__text">
            {{ widget.label || '供应商网络图' }}
          </div>
          <div class="ide-placeholder__desc">
            供应商关系网络可视化（设计态预览）
          </div>
        </div>
      </div>
    </div>
  </x-proxy-form-item>
</template>

<script>
import FormWidgetMixin from '../../../mixin/form-widget.mixin'

export default {
  name: 'FormComponentSupplierNetworkIde',
  mixins: [FormWidgetMixin]
}
</script>

<style lang="scss" scoped>
.supplier-network-ide {
  width: 100%;

  &__preview {
    border: 2px dashed #DCDFE6;
    border-radius: 8px;
    background: #FAFBFC;
    padding: 24px;
  }

  .ide-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 120px;

    &__icon {
      margin-bottom: 12px;
      opacity: 0.8;
    }

    &__text {
      font-size: 14px;
      font-weight: 500;
      color: #606266;
      margin-bottom: 4px;
    }

    &__desc {
      font-size: 12px;
      color: #C0C4CC;
    }
  }
}
</style>
