<template>
  <div class="form-widget form-component-screenshot-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="screenshot-widget">
        <!-- 截图按钮 -->
        <div class="screenshot-actions">
          <el-button
            type="primary"
            size="small"
            :icon="isMobile ? 'el-icon-picture-outline' : 'el-icon-scissors'"
            @click="handleCapture"
            :loading="capturing"
            :disabled="capturing || uploading"
          >
            {{ buttonText }}
          </el-button>
          <el-button
            v-if="previewImage && showPreview"
            size="small"
            @click="showPreviewDialog = true"
          >
            预览截图
          </el-button>
          <el-button
            v-if="previewImage"
            type="danger"
            size="small"
            icon="el-icon-delete"
            @click="handleClear"
            :disabled="uploading"
          >
            清除
          </el-button>
        </div>

        <!-- 隐藏的文件输入框（移动端使用） -->
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          capture="user"
          style="display: none"
          @change="handleFileSelect"
        />

        <!-- 隐藏的画布（用于截图） -->
        <canvas ref="captureCanvas" style="display: none"></canvas>

        <!-- 截图预览缩略图 -->
        <div v-if="previewImage" class="screenshot-preview">
          <img :src="previewImage" alt="截图预览" />
          <div class="screenshot-info">
            <span class="file-name">{{ fileName }}</span>
            <span class="file-size">{{ fileSize }}</span>
          </div>
        </div>

        <!-- 上传进度 -->
        <div v-if="uploading" class="upload-progress">
          <el-progress :percentage="uploadProgress" :stroke-width="6"></el-progress>
          <span class="progress-text">上传中... {{ uploadProgress }}%</span>
        </div>

        <!-- 上传结果 -->
        <div v-if="uploadSuccess" class="upload-success">
          <i class="el-icon-success"></i>
          <span>上传成功</span>
        </div>

        <!-- 平台附件ID -->
        <input type="hidden" :value="formValue" />
      </div>
    </x-proxy-form-item>

    <!-- 预览弹窗 -->
    <el-dialog
      title="截图预览"
      :visible.sync="showPreviewDialog"
      width="80%"
      append-to-body
    >
      <div class="preview-container">
        <img v-if="previewImage" :src="previewImage" alt="截图预览" style="max-width: 100%;" />
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="showPreviewDialog = false">关闭</el-button>
        <el-button type="primary" @click="handleReCapture">重新截图</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentAiImageCompareEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      capturing: false,
      uploading: false,
      uploadProgress: 0,
      uploadSuccess: false,
      previewImage: null,
      fileName: '',
      fileSize: '',
      attachmentId: null,
      showPreviewDialog: false,
      // 移动端检测
      isMobile: false
    }
  },
  computed: {
    // 从配置中获取按钮文字
    buttonText() {
      return this.widget.customComponentConfig?.buttonText || '截图'
    },
    // 是否显示预览
    showPreview() {
      return this.widget.customComponentConfig?.showPreview !== false
    },
    // 最大文件大小（MB）
    maxSize() {
      return this.widget.customComponentConfig?.maxSize || 10
    },
    // 允许的文件类型
    fileTypes() {
      return this.widget.customComponentConfig?.fileTypes || '.jpg,.jpeg,.png'
    }
  },
  created() {
    // 检测是否为移动端
    this.detectMobile()
    // 监听窗口大小变化
    window.addEventListener('resize', this.detectMobile)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.detectMobile)
    // 清理预览图片
    if (this.previewImage && this.previewImage.startsWith('data:')) {
      this.previewImage = null
    }
  },
  methods: {
    // 检测是否为移动端
    detectMobile() {
      const userAgent = navigator.userAgent || navigator.vendor || window.opera
      this.isMobile = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent) ||
        (navigator.maxTouchPoints && navigator.maxTouchPoints > 2)
    },

    // 处理截图按钮点击
    handleCapture() {
      if (this.isMobile) {
        // 移动端：打开文件选择器
        this.$refs.fileInput.click()
      } else {
        // PC端：使用 html2canvas 截取页面
        this.captureScreen()
      }
    },

    // PC端截图
    async captureScreen() {
      if (typeof window.html2canvas === 'undefined') {
        this.$message.error('截图功能需要加载 html2canvas 库')
        return
      }

      this.capturing = true
      try {
        // 获取当前页面内容进行截图
        const canvas = await window.html2canvas(document.body, {
          useCORS: true,
          allowTaint: true,
          backgroundColor: '#ffffff',
          scale: window.devicePixelRatio || 1,
          logging: false
        })

        // 转换为 blob
        const blob = await new Promise(resolve => {
          canvas.toBlob(resolve, 'image/png', 0.9)
        })

        // 检查文件大小
        const sizeInMB = (blob.size / (1024 * 1024)).toFixed(2)
        if (blob.size > this.maxSize * 1024 * 1024) {
          this.$message.warning(`截图大小（${sizeInMB}MB）超过限制（${this.maxSize}MB）`)
          this.capturing = false
          return
        }

        // 生成文件名
        const timestamp = this.formatDate(new Date())
        this.fileName = `screenshot_${timestamp}.png`
        this.fileSize = sizeInMB + 'MB'

        // 显示预览
        this.previewImage = canvas.toDataURL('image/png')

        // 上传截图
        await this.uploadImage(blob)
      } catch (error) {
        console.error('截图失败:', error)
        this.$message.error('截图失败，请重试')
      } finally {
        this.capturing = false
      }
    },

    // 移动端文件选择处理
    handleFileSelect(event) {
      const file = event.target.files[0]
      if (!file) return

      // 检查文件类型
      const allowedTypes = this.fileTypes.split(',').map(t => t.trim().toLowerCase())
      const fileType = '.' + file.name.split('.').pop().toLowerCase()
      if (!allowedTypes.includes(fileType)) {
        this.$message.error(`不支持的文件类型，请上传 ${this.fileTypes} 格式的图片`)
        event.target.value = ''
        return
      }

      // 检查文件大小
      const sizeInMB = (file.size / (1024 * 1024)).toFixed(2)
      if (file.size > this.maxSize * 1024 * 1024) {
        this.$message.warning(`文件大小（${sizeInMB}MB）超过限制（${this.maxSize}MB）`)
        event.target.value = ''
        return
      }

      this.fileName = file.name
      this.fileSize = sizeInMB + 'MB'

      // 读取文件并显示预览
      const reader = new FileReader()
      reader.onload = (e) => {
        this.previewImage = e.target.result
        this.uploadImage(file)
      }
      reader.readAsDataURL(file)

      // 清空 input 以允许重复选择同一文件
      event.target.value = ''
    },

    // 上传图片到平台附件
    async uploadImage(file) {
      this.uploading = true
      this.uploadProgress = 0
      this.uploadSuccess = false

      try {
        // 调用平台附件上传 API
        const formData = new FormData()
        formData.append('file', file, this.fileName)
        formData.append('fileName', this.fileName)

        const response = await this.$request({
          url: '/xdap-app/attachment/v1/upload',
          method: 'POST',
          data: formData,
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          onUploadProgress: (progressEvent) => {
            if (progressEvent.total) {
              this.uploadProgress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            }
          }
        }).asyncThen(res => {
          return res
        }).asyncErrorCatch(err => {
          throw err
        })

        // 处理上传结果
        if (response && response.data) {
          this.attachmentId = response.data.attachmentId || response.data.id
          this.formValue = this.attachmentId
          this.uploadSuccess = true
          this.$message.success('截图上传成功')
        } else {
          throw new Error('上传响应格式错误')
        }
      } catch (error) {
        console.error('上传失败:', error)
        this.$message.error('上传失败，请重试')
        this.uploadSuccess = false
      } finally {
        this.uploading = false
        this.uploadProgress = 0
      }
    },

    // 清除截图
    handleClear() {
      this.$confirm('确定要清除截图吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => {
        this.previewImage = null
        this.fileName = ''
        this.fileSize = ''
        this.attachmentId = null
        this.uploadSuccess = false
        this.formValue = ''
        this.$message.success('已清除截图')
      }).catch(() => {})
    },

    // 重新截图
    handleReCapture() {
      this.showPreviewDialog = false
      this.handleCapture()
    },

    // 格式化日期
    formatDate(date) {
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hours = String(date.getHours()).padStart(2, '0')
      const minutes = String(date.getMinutes()).padStart(2, '0')
      const seconds = String(date.getSeconds()).padStart(2, '0')
      return `${year}${month}${day}${hours}${minutes}${seconds}`
    }
  }
}
</script>

<style lang="scss">
.form-component-screenshot-edit {
  .screenshot-widget {
    .screenshot-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }

    .screenshot-preview {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: #f5f7fa;
      border-radius: 4px;
      margin-top: 12px;

      img {
        max-width: 120px;
        max-height: 80px;
        border-radius: 4px;
        border: 1px solid #e4e7ed;
      }

      .screenshot-info {
        display: flex;
        flex-direction: column;
        gap: 4px;

        .file-name {
          font-size: 12px;
          color: #303133;
          max-width: 150px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .file-size {
          font-size: 11px;
          color: #909399;
        }
      }
    }

    .upload-progress {
      margin-top: 12px;

      .progress-text {
        display: block;
        text-align: center;
        font-size: 12px;
        color: #909399;
        margin-top: 4px;
      }
    }

    .upload-success {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 12px;
      padding: 8px 12px;
      background: #f0f9eb;
      border-radius: 4px;
      color: #67c23a;
      font-size: 13px;

      i {
        font-size: 16px;
      }
    }
  }

  .preview-container {
    text-align: center;
    background: #f5f7fa;
    padding: 12px;
    border-radius: 4px;

    img {
      max-width: 100%;
      max-height: 60vh;
      border-radius: 4px;
    }
  }

  // 移动端适配
  @media screen and (max-width: 768px) {
    .screenshot-widget {
      .screenshot-actions {
        flex-direction: column;

        .el-button {
          width: 100%;
        }
      }

      .screenshot-preview {
        flex-direction: column;
        text-align: center;

        img {
          max-width: 100%;
        }

        .screenshot-info {
          align-items: center;
        }
      }
    }
  }
}
</style>
