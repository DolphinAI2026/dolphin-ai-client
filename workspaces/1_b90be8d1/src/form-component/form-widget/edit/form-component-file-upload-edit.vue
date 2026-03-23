<template>
  <div class="form-widget ai-image-recognition-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div class="ai-image-recognition-container">
        <!-- 上传区域 -->
        <div class="upload-section" v-if="!currentImage">
          <!-- 摄像头拍照区域 -->
          <div v-if="config.enableCamera" class="camera-section">
            <video ref="videoRef" class="camera-video" :class="{ active: isCameraActive }" playsinline></video>
            <canvas ref="canvasRef" class="camera-canvas"></canvas>
            <div class="camera-controls">
              <el-button v-if="!isCameraActive" size="small" type="primary" @click="startCamera">
                <i class="el-icon-camera"></i> 打开摄像头
              </el-button>
              <template v-else>
                <el-button size="small" type="success" @click="capturePhoto">
                  <i class="el-icon-camera-solid"></i> 拍照
                </el-button>
                <el-button size="small" @click="stopCamera">关闭</el-button>
              </template>
            </div>
          </div>

          <!-- 文件上传区域 -->
          <div v-if="config.enableFileUpload" class="file-upload-section"
               :class="{ 'drag-over': isDragOver }"
               @click="triggerFileInput"
               @dragover.prevent="isDragOver = true"
               @dragleave="isDragOver = false"
               @drop.prevent="handleDrop">
            <input ref="fileInputRef" type="file" accept="image/*" @change="handleFileChange" style="display: none;">
            <div class="upload-placeholder">
              <i class="el-icon-upload2 upload-icon"></i>
              <p class="upload-text">点击或拖拽上传图片</p>
              <p class="upload-hint">支持 {{ config.acceptedFormats.join(', ') }} 格式，最大 {{ config.maxImageSize }}MB</p>
            </div>
          </div>
        </div>

        <!-- 图片预览和分析区域 -->
        <div v-else class="image-preview-section">
          <div class="image-wrapper">
            <img :src="currentImage" alt="预览图片" class="preview-image">
            <el-button class="remove-btn" type="danger" icon="el-icon-close" circle size="small"
                       @click="removeImage" title="移除图片"></el-button>
          </div>

          <!-- 分析结果 -->
          <div class="analysis-section">
            <div v-if="isAnalyzing" class="analysis-loading">
              <i class="el-icon-loading"></i>
              <span>AI正在分析图片...</span>
            </div>
            <div v-else-if="analysisResult" class="analysis-result" :class="analysisResult.result">
              <div class="result-header">
                <i :class="analysisResult.result === 'pass' ? 'el-icon-success' : 'el-icon-error'"></i>
                <span class="result-text">{{ analysisResult.result === 'pass' ? '通过' : '不通过' }}</span>
              </div>
              <div class="result-confidence" v-if="analysisResult.confidence">
                置信度：{{ (analysisResult.confidence * 100).toFixed(1) }}%
              </div>
              <div class="result-reason" v-if="analysisResult.reason">
                {{ analysisResult.reason }}
              </div>
            </div>
            <div class="analysis-actions">
              <el-button size="small" type="primary" :loading="isAnalyzing" @click="analyzeImage">
                <i class="el-icon-magic-stick"></i> AI分析
              </el-button>
              <el-button size="small" @click="reuploadImage">
                <i class="el-icon-refresh"></i> 重新上传
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'

export default {
  name: 'FormComponentFileUploadEdit',
  mixins: [FormWidgetMixin],
  data() {
    return {
      // 摄像头相关
      isCameraActive: false,
      mediaStream: null,
      // 图片相关
      currentImage: '',
      imageBase64: '',
      // 分析相关
      isAnalyzing: false,
      analysisResult: null,
      // 拖拽相关
      isDragOver: false,
      // stream对象用于拍照
      stream: null
    }
  },
  computed: {
    config() {
      const customConfig = this.widget.customComponentConfig || {}
      return {
        aiApiUrl: customConfig.aiApiUrl || '',
        aiApiKey: customConfig.aiApiKey || '',
        aiPrompt: customConfig.aiPrompt || '请分析这张图片，判断是否合格。如果合格返回"通过"，如果不合格返回"不通过"并说明原因。',
        resultField: customConfig.resultField || '',
        reasonField: customConfig.reasonField || '',
        confidenceThreshold: customConfig.confidenceThreshold || 0.8,
        enableCamera: customConfig.enableCamera !== false,
        enableFileUpload: customConfig.enableFileUpload !== false,
        maxImageSize: customConfig.maxImageSize || 5,
        acceptedFormats: customConfig.acceptedFormats || ['jpg', 'jpeg', 'png', 'bmp', 'webp']
      }
    },
    editValue: {
      get() {
        return this.formValue || {}
      },
      set(val) {
        this.formValue = val
      }
    }
  },
  methods: {
    // 触发文件选择
    triggerFileInput() {
      this.$refs.fileInputRef && this.$refs.fileInputRef.click()
    },

    // 处理文件选择
    handleFileChange(event) {
      const file = event.target.files[0]
      if (file) {
        this.processFile(file)
      }
      // 清空input值，允许重复选择同一文件
      event.target.value = ''
    },

    // 处理拖拽
    handleDrop(event) {
      this.isDragOver = false
      const file = event.dataTransfer.files[0]
      if (file && file.type.startsWith('image/')) {
        this.processFile(file)
      } else {
        this.$message.warning('请上传图片文件')
      }
    },

    // 处理文件
    processFile(file) {
      // 检查文件类型
      const ext = file.name.split('.').pop().toLowerCase()
      if (!this.config.acceptedFormats.includes(ext)) {
        this.$message.warning(`不支持的图片格式，请上传 ${this.config.acceptedFormats.join(', ')} 格式`)
        return
      }

      // 检查文件大小
      const maxSize = this.config.maxImageSize * 1024 * 1024
      if (file.size > maxSize) {
        this.$message.warning(`图片大小不能超过 ${this.config.maxImageSize}MB`)
        return
      }

      // 读取文件为base64
      const reader = new FileReader()
      reader.onload = (e) => {
        this.currentImage = e.target.result
        this.imageBase64 = e.target.result
        this.analysisResult = null
        this.updateFormValue()
      }
      reader.readAsDataURL(file)
    },

    // 打开摄像头
    async startCamera() {
      try {
        // 停止之前的流
        this.stopCamera()

        const constraints = {
          video: {
            facingMode: 'environment', // 后置摄像头优先
            width: { ideal: 1280 },
            height: { ideal: 720 }
          }
        }

        this.stream = await navigator.mediaDevices.getUserMedia(constraints)
        this.$refs.videoRef.srcObject = this.stream
        this.isCameraActive = true
      } catch (error) {
        console.error('摄像头打开失败:', error)
        this.$message.error('无法访问摄像头，请检查权限设置或使用文件上传')
      }
    },

    // 关闭摄像头
    stopCamera() {
      if (this.stream) {
        this.stream.getTracks().forEach(track => track.stop())
        this.stream = null
      }
      if (this.$refs.videoRef) {
        this.$refs.videoRef.srcObject = null
      }
      this.isCameraActive = false
    },

    // 拍照
    capturePhoto() {
      if (!this.$refs.videoRef || !this.isCameraActive) return

      const video = this.$refs.videoRef
      const canvas = this.$refs.canvasRef

      // 设置canvas尺寸与video一致
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight

      // 绘制画面
      const ctx = canvas.getContext('2d')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

      // 转换为base64
      this.currentImage = canvas.toDataURL('image/jpeg', 0.9)
      this.imageBase64 = this.currentImage

      // 关闭摄像头
      this.stopCamera()

      // 清空分析结果
      this.analysisResult = null
      this.updateFormValue()

      this.$message.success('拍照成功')
    },

    // 移除图片
    removeImage() {
      this.currentImage = ''
      this.imageBase64 = ''
      this.analysisResult = null
      this.updateFormValue()
    },

    // 重新上传
    reuploadImage() {
      this.removeImage()
      this.$nextTick(() => {
        this.triggerFileInput()
      })
    },

    // AI分析图片
    async analyzeImage() {
      if (!this.currentImage) {
        this.$message.warning('请先上传或拍摄图片')
        return
      }

      this.isAnalyzing = true
      this.analysisResult = null

      try {
        // 如果配置了AI接口，调用AI接口
        if (this.config.aiApiUrl) {
          await this.callAiApi()
        } else {
          // 模拟AI分析（实际使用时替换为真实API）
          await this.mockAiAnalyze()
        }
      } catch (error) {
        console.error('AI分析失败:', error)
        this.$message.error('AI分析失败，请重试')
      } finally {
        this.isAnalyzing = false
      }
    },

    // 调用AI接口
    async callAiApi() {
      const requestData = {
        image: this.imageBase64,
        prompt: this.config.aiPrompt
      }

      // 使用平台的网络请求方法
      const response = await this.$request({
        url: this.config.aiApiUrl,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.config.aiApiKey ? { 'Authorization': `Bearer ${this.config.aiApiKey}` } : {})
        },
        data: requestData
      }).asyncThen(res => res).asyncErrorCatch(err => {
        throw err
      })

      // 解析AI响应
      this.parseAiResponse(response)
    },

    // 模拟AI分析（用于开发和测试）
    async mockAiAnalyze() {
      // 模拟网络延迟
      await new Promise(resolve => setTimeout(resolve, 2000))

      // 模拟分析结果 - 随机通过/不通过
      const isPass = Math.random() > 0.3
      const reasons = isPass
        ? ['图片清晰度良好，符合要求', '图片内容符合标准', '图片质量合格，无明显问题']
        : ['图片模糊，无法准确识别', '图片光线不足', '图片内容不符合要求', '图片存在遮挡']

      this.analysisResult = {
        result: isPass ? 'pass' : 'fail',
        confidence: 0.75 + Math.random() * 0.2,
        reason: reasons[Math.floor(Math.random() * reasons.length)],
        timestamp: new Date().toISOString()
      }

      // 更新表单字段
      this.updateFormValue()
      this.assignToFields()
    },

    // 解析AI响应
    parseAiResponse(response) {
      // 根据实际AI接口的返回格式进行解析
      // 这里假设返回格式为 { result: 'pass/fail', confidence: 0.9, reason: '...' }
      const data = response.data || response

      if (data.result) {
        const resultValue = String(data.result).toLowerCase()
        const isPass = resultValue.includes('pass') || resultValue.includes('通过') || resultValue === 'yes'

        this.analysisResult = {
          result: isPass ? 'pass' : 'fail',
          confidence: data.confidence || data.score || 0,
          reason: data.reason || data.message || '',
          timestamp: new Date().toISOString(),
          rawResponse: data
        }
      } else {
        // 如果无法解析，返回原始响应
        this.analysisResult = {
          result: 'unknown',
          confidence: 0,
          reason: 'AI响应格式异常，请检查配置',
          rawResponse: data
        }
      }

      // 更新表单字段
      this.updateFormValue()
      this.assignToFields()
    },

    // 更新表单值
    updateFormValue() {
      const value = {
        imageBase64: this.imageBase64,
        imageUrl: this.currentImage,
        analysisResult: this.analysisResult,
        timestamp: new Date().toISOString()
      }
      this.formValue = value
    },

    // 将结果赋值到指定字段
    assignToFields() {
      if (!this.analysisResult) return

      // 赋值结果字段（通过/不通过）
      if (this.config.resultField) {
        const resultText = this.analysisResult.result === 'pass' ? '通过' : '不通过'
        this.updatePropValue(this.config.resultField, resultText)
      }

      // 赋值原因字段
      if (this.config.reasonField && this.analysisResult.reason) {
        this.updatePropValue(this.config.reasonField, this.analysisResult.reason)
      }
    },

    // 销毁时清理
    beforeDestroy() {
      this.stopCamera()
    }
  }
}
</script>

<style lang="scss" scoped>
.ai-image-recognition-edit {
  .ai-image-recognition-container {
    width: 100%;
  }

  .upload-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .camera-section {
    background: #f5f7fa;
    border-radius: 4px;
    padding: 12px;
    text-align: center;

    .camera-video {
      width: 100%;
      max-width: 320px;
      height: 240px;
      background: #000;
      border-radius: 4px;
      display: none;

      &.active {
        display: block;
        margin: 0 auto 12px;
      }
    }

    .camera-canvas {
      display: none;
    }

    .camera-controls {
      display: flex;
      justify-content: center;
      gap: 8px;
    }
  }

  .file-upload-section {
    border: 2px dashed #dcdfe6;
    border-radius: 6px;
    padding: 32px 16px;
    cursor: pointer;
    transition: all 0.3s;
    background: #fafafa;

    &:hover, &.drag-over {
      border-color: #409eff;
      background: #ecf5ff;
    }

    .upload-placeholder {
      text-align: center;

      .upload-icon {
        font-size: 48px;
        color: #c0c4cc;
        margin-bottom: 8px;
      }

      .upload-text {
        font-size: 14px;
        color: #606266;
        margin: 0 0 4px;
      }

      .upload-hint {
        font-size: 12px;
        color: #909399;
        margin: 0;
      }
    }
  }

  .image-preview-section {
    .image-wrapper {
      position: relative;
      display: inline-block;
      max-width: 100%;

      .preview-image {
        max-width: 100%;
        max-height: 300px;
        border-radius: 6px;
        display: block;
      }

      .remove-btn {
        position: absolute;
        top: 8px;
        right: 8px;
      }
    }
  }

  .analysis-section {
    margin-top: 12px;

    .analysis-loading {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px;
      background: #f0f9eb;
      border-radius: 4px;
      color: #67c23a;
      font-size: 14px;
    }

    .analysis-result {
      padding: 16px;
      border-radius: 6px;
      margin-bottom: 12px;

      &.pass {
        background: #f0f9eb;
        border: 1px solid #e1f3d8;

        .result-header {
          color: #67c23a;
        }
      }

      &.fail {
        background: #fef0f0;
        border: 1px solid #fde2e2;

        .result-header {
          color: #f56c6c;
        }
      }

      &.unknown {
        background: #f4f4f5;
        border: 1px solid #e9e9eb;

        .result-header {
          color: #909399;
        }
      }

      .result-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 16px;
        font-weight: bold;
        margin-bottom: 8px;

        i {
          font-size: 20px;
        }
      }

      .result-confidence {
        font-size: 13px;
        color: #606266;
        margin-bottom: 4px;
      }

      .result-reason {
        font-size: 14px;
        color: #303133;
        line-height: 1.5;
      }
    }

    .analysis-actions {
      display: flex;
      gap: 8px;
    }
  }
}
</style>
