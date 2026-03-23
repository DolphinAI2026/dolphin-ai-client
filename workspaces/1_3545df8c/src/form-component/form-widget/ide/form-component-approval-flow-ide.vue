<template>
  <div class="form-widget form-component-approval-flow-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :titleDescription="widget.titleDescription"
      :renderScene="renderScene"
      :processTitle="widget.processTitle"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
      :webFormSettings="webFormSettings"
    >
      <!-- 设计态预览 -->
      <div class="approval-flow-ide-preview">
        <div class="flow-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L12 6M12 18L12 22M6 12L2 12M22 12L18 12M19.07 4.93L16.24 7.76M7.76 16.24L4.93 19.07M19.07 19.07L16.24 16.24M7.76 7.76L4.93 4.93" stroke="#409EFF" stroke-width="2" stroke-linecap="round"/>
            <circle cx="12" cy="12" r="4" fill="#409EFF" opacity="0.3"/>
          </svg>
        </div>
        <div class="flow-nodes">
          <div class="flow-node node-start">
            <div class="node-icon"><i class="el-icon-s-unfold"></i></div>
            <div class="node-info">
              <span class="node-label">发起申请</span>
              <span class="node-name">张三</span>
            </div>
          </div>
          <div class="flow-line"></div>
          <div class="flow-node node-approval">
            <div class="node-icon"><i class="el-icon-s-check"></i></div>
            <div class="node-info">
              <span class="node-label">审批节点</span>
              <span class="node-name">待处理</span>
            </div>
          </div>
          <div class="flow-line"></div>
          <div class="flow-node node-end">
            <div class="node-icon"><i class="el-icon-success"></i></div>
            <div class="node-info">
              <span class="node-label">流程结束</span>
              <span class="node-name">-</span>
            </div>
          </div>
        </div>
        <span class="preview-label">审批流程（设计态预览）</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentApprovalFlowIde',
  mixins: [FormWidgetMixin]
}
</script>

<style lang="scss">
.form-component-approval-flow-ide {
  .approval-flow-ide-preview {
    padding: 16px;
    background: linear-gradient(135deg, #f0f9ff 0%, #e8f4fd 100%);
    border: 1px dashed #409EFF;
    border-radius: 8px;

    .flow-icon {
      text-align: center;
      margin-bottom: 12px;
    }

    .flow-nodes {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;

      .flow-node {
        display: flex;
        align-items: center;
        padding: 8px 16px;
        background: #fff;
        border-radius: 20px;
        border: 1px solid #DCDFE6;
        min-width: 140px;

        .node-icon {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          margin-right: 8px;
          font-size: 14px;
        }

        .node-info {
          display: flex;
          flex-direction: column;

          .node-label {
            font-size: 12px;
            color: #909399;
          }

          .node-name {
            font-size: 14px;
            color: #303133;
            font-weight: 500;
          }
        }

        &.node-start {
          .node-icon {
            background-color: #ecf5ff;
            color: #409EFF;
          }
        }

        &.node-approval {
          .node-icon {
            background-color: #fdf6ec;
            color: #E6A23C;
          }
        }

        &.node-end {
          .node-icon {
            background-color: #f0f9eb;
            color: #67C23A;
          }
        }
      }

      .flow-line {
        width: 2px;
        height: 16px;
        background-color: #DCDFE6;
      }
    }

    .preview-label {
      display: block;
      text-align: center;
      font-size: 12px;
      color: #909399;
      margin-top: 12px;
    }
  }
}
</style>
