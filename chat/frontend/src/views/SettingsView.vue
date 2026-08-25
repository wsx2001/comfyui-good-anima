<template>
  <div class="settings-view">
    <h2 class="page-title">设置</h2>

    <!-- Health summary banner -->
    <el-alert
      v-if="health"
      :type="healthBanner.type"
      :title="healthBanner.title"
      :description="healthBanner.description"
      show-icon
      :closable="false"
      class="health-banner"
    />

    <!-- LLM settings card -->
    <el-card class="settings-card" header="LLM 配置">
      <el-form
        ref="llmFormRef"
        :model="form.llm"
        label-width="140px"
        label-position="right"
        v-loading="loading.llm"
      >
        <el-form-item label="Base URL" prop="base_url">
          <el-input
            v-model="form.llm.base_url"
            placeholder="https://api.deepseek.com/v1"
          >
            <template #append>
              <el-select v-model="providerPreset" style="width: 140px" @change="applyPreset">
                <el-option label="DeepSeek" value="deepseek" />
                <el-option label="OpenAI" value="openai" />
                <el-option label="通义千问" value="qwen" />
                <el-option label="Ollama" value="ollama" />
                <el-option label="LM Studio" value="lmstudio" />
              </el-select>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.llm.api_key"
            type="password"
            show-password
            placeholder="sk-..."
          />
        </el-form-item>

        <el-form-item label="Model" prop="model">
          <el-input v-model="form.llm.model" placeholder="deepseek-chat" />
        </el-form-item>

        <el-form-item label="Temperature">
          <el-slider
            v-model="form.llm.temperature"
            :min="0"
            :max="2"
            :step="0.1"
            show-input
            style="max-width: 360px"
          />
        </el-form-item>

        <el-form-item label="Max Tokens">
          <el-input-number
            v-model="form.llm.max_tokens"
            :min="512"
            :max="8192"
            :step="256"
          />
        </el-form-item>

        <el-form-item label="思维深度">
          <el-radio-group v-model="form.llm.reasoning_effort">
            <el-radio-button value="off">off</el-radio-button>
            <el-radio-button value="low">low</el-radio-button>
            <el-radio-button value="medium">medium</el-radio-button>
            <el-radio-button value="high">high</el-radio-button>
          </el-radio-group>
          <el-text size="small" type="info" class="ml-2">
            仅支持思维链的模型生效（Claude / DeepSeek-R1），其他模型静默忽略
          </el-text>
        </el-form-item>

        <el-form-item label="上下文轮数">
          <el-input-number
            v-model="form.llm.context_window"
            :min="0"
            :max="50"
          />
          <el-text size="small" type="info" class="ml-2">
            每次发给 LLM 的最近消息轮数；0 表示不携带历史
          </el-text>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save" :loading="loading.save">
            保存
          </el-button>
          <el-button @click="test" :loading="loading.test">测试调用</el-button>
        </el-form-item>
      </el-form>

      <div v-if="testResult" class="test-result">
        <el-alert
          :type="testResult.ok ? 'success' : 'error'"
          :title="testResult.ok ? `调用成功 · 模型 ${testResult.model} · ${testResult.latency_ms} ms` : `调用失败 · ${testResult.error_code}`"
          :description="testResult.error_message || ''"
          show-icon
          :closable="true"
          @close="testResult = null"
        />
      </div>
    </el-card>

    <!-- ComfyUI settings card -->
    <el-card class="settings-card" header="ComfyUI 配置（v2mini）">
      <el-form :model="form.comfyui" label-width="140px" label-position="right">
        <el-form-item label="技能根目录">
          <el-input
            v-model="form.comfyui.skills_root"
            placeholder="C:/skills"
          />
          <el-text size="small" type="info" class="hint">
            必须包含 comfyui-animatool/、danbooru-tags/、comfyui-manager/ 三个子目录
          </el-text>
        </el-form-item>

        <el-form-item label="Manager 工作区">
          <el-input
            v-model="form.comfyui.workspace"
            placeholder="C:/skills/comfyui-manager/workspace"
          />
        </el-form-item>

        <el-form-item label="Config JSON">
          <el-input
            v-model="form.comfyui.config_json"
            placeholder="C:/skills/comfyui-manager/workspace/config.json"
          />
          <el-text size="small" type="info" class="hint">
            v2mini 的 ComfyUI server 配置；健康检查会探测 servers[0].url
          </el-text>
        </el-form-item>

        <el-form-item>
          <el-button @click="save" :loading="loading.save">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type Settings, type HealthInfo, type TestLLMResult, type ReasoningEffort } from '../api/client'

const form = reactive<Settings>({
  server: { host: '127.0.0.1', port: 8787 },
  comfyui: { skills_root: '', workspace: '', config_json: '' },
  llm: {
    base_url: 'https://api.deepseek.com/v1',
    api_key: '',
    model: 'deepseek-chat',
    temperature: 0.7,
    max_tokens: 4096,
    reasoning_effort: 'off' as ReasoningEffort,
    context_window: 5,
  },
  storage: { db_path: 'backend/runtime/chat.db', outputs_dir: 'backend/runtime/outputs' },
  system_prompt: {
    v2mini_animatool_path: '{skills_root}/comfyui-animatool/SKILL.md',
    v2mini_danbooru_path: '{skills_root}/danbooru-tags/SKILL.md',
    v2mini_manager_path: '{skills_root}/comfyui-manager/SKILL.md',
  },
})

const loading = reactive({ save: false, test: false, llm: false })
const health = ref<HealthInfo | null>(null)
const testResult = ref<TestLLMResult | null>(null)
const providerPreset = ref<string>('')

const healthBanner = computed(() => {
  if (!health.value) return { type: 'info' as const, title: '加载中…', description: '' }
  const h = health.value
  const lines = [
    `后端 ${h.version}`,
    `数据库 ${h.db_ok ? '✓' : '✗'}`,
    `ComfyUI ${h.comfyui_reachable ? '✓ 可达' : '✗ 未启动或不可达'}`,
    `LLM ${h.llm_configured ? '✓ 已配置' : '✗ 未配置'}`,
  ]
  if (h.status === 'degraded') {
    return { type: 'error' as const, title: '后端异常', description: lines.join(' · ') }
  }
  if (!h.comfyui_reachable || !h.llm_configured) {
    return { type: 'warning' as const, title: '部分依赖未就绪', description: lines.join(' · ') }
  }
  return { type: 'success' as const, title: '一切就绪', description: lines.join(' · ') }
})

const PROVIDER_PRESETS: Record<string, { base_url: string; model: string }> = {
  deepseek: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  qwen: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  ollama: { base_url: 'http://127.0.0.1:11434/v1', model: 'llama3.1' },
  lmstudio: { base_url: 'http://127.0.0.1:1234/v1', model: 'local-model' },
}

function applyPreset(name: string) {
  const preset = PROVIDER_PRESETS[name]
  if (!preset) return
  form.llm.base_url = preset.base_url
  form.llm.model = preset.model
  providerPreset.value = ''
  ElMessage.info(`已填入 ${name} 预设（请填入 API Key 后保存）`)
}

async function loadAll() {
  loading.llm = true
  try {
    const [s, h] = await Promise.all([api.getSettings(), api.getHealth()])
    Object.assign(form, s)
    health.value = h
  } catch (e: any) {
    ElMessage.error(`加载失败：${e.message}`)
  } finally {
    loading.llm = false
  }
}

async function save() {
  loading.save = true
  try {
    await api.putSettings(form)
    ElMessage.success('已保存')
    // Refresh health after save (LLM config might have changed).
    health.value = await api.getHealth()
  } catch (e: any) {
    ElMessage.error(`保存失败：${e.message}`)
  } finally {
    loading.save = false
  }
}

async function test() {
  loading.test = true
  testResult.value = null
  try {
    testResult.value = await api.testLLM({
      base_url: form.llm.base_url,
      api_key: form.llm.api_key || undefined,
      model: form.llm.model,
    })
  } catch (e: any) {
    testResult.value = { ok: false, error_code: 'client', error_message: e.message }
  } finally {
    loading.test = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.settings-view {
  max-width: 900px;
}
.page-title {
  margin-top: 0;
  margin-bottom: 16px;
  font-weight: 600;
}
.health-banner {
  margin-bottom: 16px;
}
.hint {
  margin-left: 12px;
  display: inline-block;
}
.ml-2 {
  margin-left: 8px;
}
</style>
