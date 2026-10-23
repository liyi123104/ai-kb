<template>
  <el-container class="layout">
    <!-- 左侧：文件管理 -->
    <el-aside width="320px" class="aside">
      <div class="brand">📚 AI 学习资料知识库</div>

      <div class="model-picker">
        <div class="picker-label">回答模型</div>
        <el-select v-model="provider" size="small" style="width: 100%">
          <el-option
            v-for="p in providers"
            :key="p.id"
            :label="p.label"
            :value="p.id"
            :disabled="!p.available"
          />
        </el-select>
      </div>

      <el-upload
        class="uploader"
        drag
        multiple
        :show-file-list="false"
        :auto-upload="false"
        accept=".pdf,.docx,.md,.txt"
        :on-change="handleFileChange"
      >
        <div class="upload-tip">
          <div>把 PDF / Word / MD / TXT 拖到这里（可多选）</div>
          <div class="sub">或点击选择文件，支持一次选多个</div>
        </div>
      </el-upload>

      <el-progress
        v-if="uploading"
        :percentage="uploadPercent"
        :stroke-width="10"
        class="progress"
      />
      <div v-if="uploading && ingestLabel" class="ingest-label">{{ ingestLabel }}</div>

      <div class="list-head">
        <span>已入库文件（{{ files.length }}）</span>
        <el-button link type="primary" size="small" @click="loadFiles">刷新</el-button>
      </div>

      <div class="file-list">
        <div v-for="f in files" :key="f.name" class="file-item">
          <div class="file-name" :title="`打开 ${f.name}`" @click="openFile(f.name)">
            {{ f.name }} <span class="open-hint">↗</span>
          </div>
          <div class="file-meta">
            {{ f.chunks }} 片 · {{ formatSize(f.size) }}
            <el-popconfirm title="删除该文件及其向量？" @confirm="removeFile(f.name)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
        <el-empty v-if="!files.length" description="还没有文件，先上传一份" :image-size="60" />
      </div>
    </el-aside>

    <!-- 右侧：聊天区 -->
    <el-main class="main">
      <div ref="scrollRef" class="messages">
        <div v-if="!messages.length" class="placeholder">
          <h2>问我关于这些资料的问题</h2>
          <p>答案会附带出处（文件名 + PDF 页码）</p>
          <div class="examples">
            <el-tag
              v-for="q in examples"
              :key="q"
              class="example"
              @click="askExample(q)"
            >{{ q }}</el-tag>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
          <div class="bubble">
            <div class="content">{{ m.content }}</div>

            <div v-if="m.sources && m.sources.length" class="sources">
              <div class="sources-title">出处</div>
              <div
                v-for="s in m.sources"
                :key="s.index"
                class="source-item clickable"
                :title="`打开 ${s.file} 第 ${s.page_start} 页`"
                @click="openSource(s, m.question)"
              >
                <span class="file">{{ s.file }}</span>
                <span class="page">PDF p.{{ s.page_label }}</span>
                <span class="score">相似度 {{ s.score }}</span>
                <span class="open-hint">打开 ↗</span>
                <div class="snippet">{{ s.snippet }}</div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="streaming && !currentAnswer" class="msg assistant">
          <div class="bubble typing">检索中…</div>
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="question"
          placeholder="问点什么，例如：什么是自注意力机制？（Enter 发送）"
          :disabled="streaming"
          @keyup.enter="send"
        >
          <template #append>
            <el-button v-if="streaming" type="danger" plain @click="stopStreaming">停止</el-button>
            <el-button v-else :disabled="!question.trim()" @click="send">发送</el-button>
          </template>
        </el-input>
        <div class="hint">当前会话：{{ sessionId || '（新会话）' }}<a class="logout" @click="signOut">退出登录</a></div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authStatus, deleteFile, fileUrl, getFiles, login, logout,
         getProviders, getUploadProgress, streamChat, uploadFiles } from '../api'

const files = ref([])
const messages = ref([])
const question = ref('')
const sessionId = ref('')
const streaming = ref(false)
const currentAnswer = ref('')
const uploading = ref(false)
const uploadPercent = ref(0)
const ingestLabel = ref('')
let streamCtrl = null
const scrollRef = ref(null)
const providers = ref([])
// provider 下拉框里存的是 "provider:model" 形式的 id（如 ollama:qwen2.5:7b）
const provider = ref('')
const selectedProvider = computed(() => {
  const id = provider.value || ''
  return id.includes(':') ? id.split(':')[0] : (id || undefined)
})
const selectedModel = computed(() => {
  const id = provider.value || ''
  const i = id.indexOf(':')
  return i >= 0 ? id.slice(i + 1) : undefined
})

const examples = [
  '什么是自注意力机制？',
  'RAG 相比只用参数化知识有什么优势？',
  'bge-m3 输出多少维向量？'
]

function openSource(source, question) {
  // 浏览器内置 PDF 阅读器支持 #page=N，直接跳转到该页
  window.open(fileUrl(source.file, source.page_start, source.text || source.snippet, question, source.page_end), '_blank')
}

function openFile(name) {
  window.open(fileUrl(name), '_blank')
}

function formatSize(bytes) {
  if (!bytes) return '未知'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function scrollToBottom() {
  await nextTick()
  if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight
}

// 登录一次即可：成功后后端下发会话 Cookie，后续请求与文件链接都不用再带令牌
async function doLogin(token) {
  await login(String(token).trim())
  window.location.reload()
}

async function promptToken() {
  try {
    const { value } = await ElMessageBox.prompt(
      '请输入访问令牌（.env 文件里的 AUTH_TOKEN）。登录一次后不再需要输入。',
      '登录', { confirmButtonText: '登录', cancelButtonText: '取消', inputPlaceholder: 'AUTH_TOKEN' }
    )
    if (value) await doLogin(value)
  } catch (e) {
    /* 用户取消 */
  }
}

async function signOut() {
  try {
    await logout()
  } finally {
    window.location.reload()
  }
}

async function loadFiles() {
  try {
    const { data } = await getFiles()
    files.value = data
  } catch (err) {
    if (err?.response?.status === 401) {
      await promptToken()
      return
    }
    const detail = err?.response?.data?.detail || err.message
    ElMessage.error(`读取文件列表失败：${detail}（HTTP ${err?.response?.status || '?'}）`)
  }
}

// 多选文件时 el-upload 会逐个触发 on-change，这里攒 400ms 一起提交，
// 后端会把这批文件放进同一个入库任务里顺序处理（只切一次模型）
const pendingFiles = ref([])
let flushTimer = null

function handleFileChange(uploadFileObj) {
  const raw = uploadFileObj.raw
  if (!raw) return
  if (raw.size > 100 * 1024 * 1024) {
    ElMessage.error(`${raw.name} 超过 100MB，已跳过`)
    return
  }
  pendingFiles.value.push(raw)
  if (flushTimer) clearTimeout(flushTimer)
  flushTimer = setTimeout(flushUploads, 400)
}

async function flushUploads() {
  const files = pendingFiles.value.splice(0)
  if (!files.length) return
  uploading.value = true
  uploadPercent.value = 0
  ingestLabel.value = files.length > 1 ? `${files.length} 个文件上传中…` : `${files[0].name} 上传中…`
  try {
    // 上传只负责把文件传上去，入库在后台跑；随后轮询进度，界面不会一直卡住
    const { data } = await uploadFiles(files, (p) => (uploadPercent.value = p))
    const jobId = data.job_id
    if (!jobId) {
      // 旧后端：同步返回结果
      ElMessage.success(`${data.filename} 入库 ${data.chunks} 片`)
      await loadFiles()
      return
    }
    const started = Date.now()
    for (;;) {
      await new Promise((r) => setTimeout(r, 600))
      const { data: job } = await getUploadProgress(jobId)
      const which = job.total_files > 1
        ? `第 ${Math.min(job.done_files + 1, job.total_files)}/${job.total_files} 个`
        : ''
      if (job.state === 'running') {
        uploadPercent.value = job.total
          ? Math.min(99, Math.round((job.processed / job.total) * 100))
          : 1
        ingestLabel.value = job.total
          ? `${which}${job.current}：${job.processed}/${job.total} 片`
          : `${which}${job.current} 解析中…`
        continue
      }
      if (job.state === 'error') throw new Error(job.error || '入库失败')
      const sec = ((Date.now() - started) / 1000).toFixed(1)
      const names = job.total_files > 1 ? `${job.total_files} 个文件` : job.filename
      ElMessage.success(`${names} 入库 ${job.chunks} 片，用时 ${sec}s`)
      break
    }
    await loadFiles()
  } catch (err) {
    const detail = err?.response?.data?.detail || err.message
    ElMessage.error(`上传失败：${detail}`)
  } finally {
    uploading.value = false
    uploadPercent.value = 0
    ingestLabel.value = ''
  }
}

async function removeFile(name) {
  try {
    await deleteFile(name)
    ElMessage.success('已删除')
    await loadFiles()
  } catch (err) {
    ElMessage.error(`删除失败：${err.message}`)
  }
}

function askExample(q) {
  question.value = q
  send()
}

function stopStreaming() {
  if (streamCtrl) streamCtrl.abort()
}

async function send() {
  const q = question.value.trim()
  if (!q) {
    ElMessage.warning('问题不能为空')
    return
  }

  messages.value.push({ role: 'user', content: q })
  question.value = ''
  streaming.value = true
  currentAnswer.value = ''

  const reply = { role: 'assistant', content: '', sources: [], question: q }
  messages.value.push(reply)
  await scrollToBottom()

  try {
    await streamChat(q, {
      // 把界面选择器里的模型传给后端：'ollama' 本地 / 'deepseek' 云端
      provider: selectedProvider.value,
      model: selectedModel.value,
      onSources: (src) => {
        reply.sources = src
      },
      onToken: (t) => {
        reply.content += t
        currentAnswer.value = reply.content
        scrollToBottom()
      },
      onDone: (info) => {
        if (info?.session_id) sessionId.value = info.session_id
      }
    })
  } catch (err) {
    const msg = String(err?.message || '')
    if (err?.name === 'AbortError') {
      reply.content = reply.content || '（已停止生成）'
    } else if (msg.includes('401')) {
      // 令牌缺失或错误：清掉气泡里的报错，提示重新输入
      reply.content = ''
      await promptToken()
    } else {
      reply.content = `请求失败：${msg}`
      ElMessage.error(`问答失败：${msg}`)
    }
  } finally {
    streaming.value = false
    currentAnswer.value = ''
    await scrollToBottom()
  }
}

async function loadProviders() {
  try {
    const { data } = await getProviders()
    providers.value = data.items
    provider.value = data.default
  } catch (err) {
    // 旧后端没有 /providers 时不影响主流程
  }
}

onMounted(async () => {
  // 支持用链接直接登录：http://127.0.0.1:5173/?token=xxx
  const params = new URLSearchParams(window.location.search)
  const urlToken = params.get('token')
  if (urlToken) {
    params.delete('token')
    const qs = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''))
    try {
      await doLogin(urlToken)   // 成功后 reload
      return
    } catch (e) {
      ElMessage.error('链接里的令牌不正确')
    }
  }
  try {
    const { data } = await authStatus()
    if (data.auth_required && !data.logged_in) {
      await promptToken()
      return
    }
  } catch (e) {
    /* 没有该接口就跳过 */
  }
  loadProviders()
  loadFiles()
})
</script>

<style scoped>
.model-picker {
  margin-bottom: 12px;
}
.picker-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.layout {
  height: 100vh;
}
.aside {
  border-right: 1px solid #ebeef5;
  padding: 16px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.brand {
  font-weight: 600;
  font-size: 16px;
  margin-bottom: 12px;
}
.upload-tip {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.upload-tip .sub {
  color: #909399;
  font-size: 12px;
}
.ingest-label {
  font-size: 12px;
  color: #909399;
  margin: 4px 0 8px;
}
.progress {
  margin: 8px 0;
}
.list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 16px 0 8px;
  font-size: 13px;
  color: #606266;
}
.file-list {
  flex: 1;
  overflow-y: auto;
}
.file-item {
  padding: 8px;
  border-radius: 6px;
  background: #fff;
  margin-bottom: 8px;
  border: 1px solid #ebeef5;
}
.file-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-meta {
  font-size: 12px;
  color: #909399;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
}
.main {
  display: flex;
  flex-direction: column;
  padding: 0;
  background: #fff;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.placeholder {
  text-align: center;
  color: #606266;
  margin-top: 15vh;
}
.examples {
  margin-top: 16px;
}
.example {
  margin: 4px;
  cursor: pointer;
}
.msg {
  display: flex;
  margin-bottom: 16px;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f4f4f5;
  white-space: pre-wrap;
  line-height: 1.7;
}
.msg.user .bubble {
  background: #409eff;
  color: #fff;
}
.typing {
  color: #909399;
}
.sources {
  margin-top: 10px;
  border-top: 1px dashed #dcdfe6;
  padding-top: 8px;
}
.sources-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.source-item {
  font-size: 12px;
  color: #606266;
  margin-bottom: 6px;
  padding: 4px 6px;
  border-radius: 4px;
}
.source-item.clickable {
  cursor: pointer;
}
.source-item.clickable:hover {
  background: #f0f7ff;
}
.open-hint {
  color: #409eff;
  font-size: 11px;
  margin-left: 4px;
}
.source-item .page {
  color: #409eff;
  margin: 0 6px;
}
.source-item .score {
  color: #909399;
}
.snippet {
  color: #909399;
  margin-top: 2px;
}
.input-area {
  border-top: 1px solid #ebeef5;
  padding: 12px 24px 16px;
}
.logout {
  margin-left: 12px;
  color: #909399;
  cursor: pointer;
  text-decoration: underline;
}
.hint {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
</style>
