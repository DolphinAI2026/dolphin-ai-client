<template>
  <div class="form-widget form-component-screenshot-read">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div v-if="formValue" class="screenshot-read-content">
        <div class="screenshot-badge">
          <i class="el-icon-picture-outline-round"></i>
          <span>已截图</span>
        </div>
        <el-button
          v-if="showPreview && attachmentUrl"
          type="text"
          size="small"
          @click="showPreviewDialog = true"
        >
          查看截图
        </el-button>
      </div>
      <span v-else>-</span>
    </x-proxy-form-item>

    <!-- 预览弹窗 -->
    <el-dialog
      title="截图预览"
      :visible.sync="showPreviewDialog"
      width="80%"
      append-to-body
    >
      <div class="preview-container">
        <img v-if="attachmentUrl" :src="attachmentUrl" alt="截图预览" />
        <div v-else class="preview-loading">
          <i class="el-icon-loading"></i>
          <span>加载中...</span>
        </div>
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="showPreviewDialog = false">关闭</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentAiImageCompareRead',
  mixins: [FormWidgetMixin],
  data() {
    return {
      showPreviewDialog: false,
      attachmentUrl: null
    }
  },
  computed: {
    showPreview() {
      return this.widget.customComponentConfig?.showPreview !== false
    }
  },
  watch: {
    formValue: {
      immediate: true,
      handler(val) {
        if (val) {
          this.loadAttachmentUrl(val)
        } else {
          this.attachmentUrl = null
        }
      }
    }
  },
  methods: {
    // 加载附件预览 URL
    async loadAttachmentUrl(attachmentId) {
      if (!attachmentId) return

      try {
        const response = await this.$request({
          url: '/xdap-app/attachment/v1/preview',
          method: 'GET',
          params: { attachmentId }
        }).asyncThen(res => res).asyncErrorCatch(() => null)

        if (response && response.data) {
          this.attachmentUrl = response.data.url || response.data
        }
      } catch (error) {
        console.error('加载附件预览失败:', error)
      }
    }
  }
}
</script>

<style lang="scss">
.form-component-screenshot-read {
  .screenshot-read-content {
    display: flex;
    align-items: center;
    gap: 12px;

    .screenshot-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      background: #f0f9eb;
      color: #67c23a;
      border-radius: 4px;
      font-size: 12px;

      i {
        font-size: 14px;
      }
    }
  }

  .preview-container {
    text-align: center;
    background: #f5f7fa;
    padding: 12px;
    border-radius: 4px;
    min-height: 200px;
    display: flex;
    align-items: center;
    justify-content: center;

    img {
      max-width: 100%;
      max-height: 60vh;
      border-radius: 4px;
    }

    .preview-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      color: #909399;

      i {
        font-size: 24px;
      }
    }
  }
}
</style>
