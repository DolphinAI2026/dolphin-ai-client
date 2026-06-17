<template>
  <div class="wiz-wrap">
    <el-steps :active="step" finish-status="success" simple>
      <el-step title="连接 aPaaS 环境" />
      <el-step title="配置 LLM 模型" />
      <el-step title="完成" />
    </el-steps>

    <div v-if="step === 0" class="wiz-step">
      <el-form label-width="120px">
        <el-form-item label="环境名称"><el-input v-model="env.env_name" placeholder="如 Trail-mars" /></el-form-item>
        <el-form-item label="aPaaS 地址"><el-input v-model="env.base_url" placeholder="https://..." /></el-form-item>
        <el-form-item label="平台租户ID"><el-input v-model="env.platform_tenant_id" /></el-form-item>
        <el-form-item label="账号"><el-input v-model="env.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="env.password" type="password" show-password /></el-form-item>
      </el-form>
      <div class="wiz-foot">
        <el-button @click="skip">稍后配置</el-button>
        <el-button type="primary" :loading="busy" @click="saveEnv">保存并测试连通</el-button>
      </div>
      <p v-if="msg" class="wiz-msg" :class="{ err: msgErr }">{{ msg }}</p>
    </div>

    <div v-else-if="step === 1" class="wiz-step">
      <el-form label-width="120px">
        <el-form-item label="配置名称"><el-input v-model="llm.config_name" placeholder="如 Dolphin-默认" /></el-form-item>
        <el-form-item label="供应商">
          <el-select v-model="llm.provider" @change="onProvider">
            <el-option label="Dolphin" value="dolphin" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 地址"><el-input v-model="llm.base_url" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="llm.model" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="llm.api_key" placeholder="你的 omnigate 令牌" /></el-form-item>
      </el-form>
      <div class="wiz-foot">
        <el-button @click="skip">稍后配置</el-button>
        <el-button type="primary" :loading="busy" @click="saveLlm">保存</el-button>
      </div>
      <p v-if="msg" class="wiz-msg" :class="{ err: msgErr }">{{ msg }}</p>
    </div>

    <div v-else class="wiz-step wiz-done">
      <h3>配置完成</h3>
      <p>已连接 aPaaS 环境并配好模型，可以开始智能配置 / 二次开发了。</p>
      <el-button type="primary" @click="$router.replace('/')">进入工作台</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { platformEnvApi } from '@/api/platformEnv'
import { llmConfigApi } from '@/api/llmConfig'
import type { LlmConfigForm } from '@/api/llmConfig'

const step = ref(0)
const busy = ref(false)
const msg = ref('')
const msgErr = ref(false)

const env = reactive({
  env_name: '',
  base_url: '',
  platform_tenant_id: '',
  username: '',
  password: '',
})

const llm = reactive<LlmConfigForm>({
  config_name: 'Dolphin-默认',
  provider: 'dolphin',
  base_url: 'http://ai-agent.dfy.definesys.cn/omnigate/0',
  model: 'gpt-5.5',
  api_key: '',
  purpose: 'builder',
  max_tokens: 4096,
  temperature: 0.7,
  is_default: true,
})

function onProvider() {
  if (llm.provider === 'dolphin') {
    llm.base_url = 'http://ai-agent.dfy.definesys.cn/omnigate/0'
    llm.model = 'gpt-5.5'
    llm.config_name = 'Dolphin-默认'
  }
}

async function saveEnv() {
  busy.value = true
  msg.value = ''
  msgErr.value = false
  try {
    const { id } = await platformEnvApi.create({
      env_name: env.env_name,
      base_url: env.base_url,
      platform_tenant_id: env.platform_tenant_id,
      username: env.username,
      password: env.password,
    })
    const r = await platformEnvApi.test(id)
    if (!r.ok) {
      msg.value = `连通测试失败: ${r.error || r.status}`
      msgErr.value = true
      return
    }
    await platformEnvApi.setDefault(id)
    msg.value = '环境已连接'
    step.value = 1
  } catch (e: any) {
    msg.value = `保存失败: ${e?.message || e}`
    msgErr.value = true
  } finally {
    busy.value = false
  }
}

async function saveLlm() {
  busy.value = true
  msg.value = ''
  msgErr.value = false
  try {
    await llmConfigApi.create(llm)
    step.value = 2
  } catch (e: any) {
    msg.value = `保存失败: ${e?.message || e}`
    msgErr.value = true
  } finally {
    busy.value = false
  }
}

function skip() {
  ElMessage.info('已跳过，稍后可在「平台配置」继续设置')
  if (step.value === 0) step.value = 1
  else step.value = 2
}
</script>

<style scoped>
.wiz-wrap { max-width: 640px; margin: 48px auto; }
.wiz-step { margin-top: 32px; }
.wiz-foot { display: flex; justify-content: flex-end; gap: 12px; margin-top: 8px; }
.wiz-msg { margin-top: 12px; color: var(--el-color-success); }
.wiz-msg.err { color: var(--el-color-danger); }
.wiz-done { text-align: center; }
</style>
