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
        :show-file-list="false"
        :auto-upload="false"
        accept=".pdf,.docx,.md,.txt"
        :on-change="handleFileChange"
      >
        <div class="upload-tip">
          <div>把 PDF / Word / MD / TXT 拖到这里</div>
          <div class="sub">或点击选择文件</div>
        </div>
      </el-upload>

      <el-progress
        v-if="uploading"
        :percentage="uploadPercent"
        :stroke-width="10"
        class="progress"
      />

      <div class="list-head">
        <span>已入库文件（{{ files.length }}）</span>
        <el-button link type="primary" size="small" @click="loadFiles">刷新</el-button>
      </div>

      <div class="file-list">
        <div v-for="f in files" :key="f.name" class="file-item">
          <div class="file-name" :title="f.name">{{ f.name }}</div>
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
              <div v-for="s in m.sources" :key="s.index" class="source-item">
                <span class="file">{{ s.file }}</span>
                <span class="page">PDF p.{{ s.page_label }}</span>
                <span class="score">相似度 {{ s.score }}</span>
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
            <el-button :loading="streaming" :disabled="!question.trim()" @click="send">
              发送
            </el-button>
          </template>
        </el-input>
        <div class="hint">当前会话：{{ sessionId || '（新会话）' }}</div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { deleteFile, getFiles, getProviders, streamChat, uploadFile } from '../api'

const files = ref([])
const messages = ref([])
const question = ref('')
const sessionId = ref('')
const streaming = ref(false)
const currentAnswer = ref('')
const uploading = ref(false)
const uploadPercent = ref(0)
const scrollRef = ref(null)
const providers = ref([])
const provider = ref('')

const examples = [
  '什么是自注意力机制？',
  'RAG 相比只用参数化知识有什么优势？',
  'bge-m3 输出多少维向量？'
]

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

async function loadFiles() {
  try {
    const { data } = await getFiles()
    files.value = data
  } catch (err) {
    ElMessage.error(`读取文件列表失败：${err.message}（后端启动了吗？）`)
  }
}

async function handleFileChange(uploadFileObj) {
  const raw = uploadFileObj.raw
  if (!raw) return
  if (raw.size > 100 * 1024 * 1024) {
    ElMessage.error('文件超过 100MB，请换小一点的')
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    const { data } = await uploadFile(raw, (p) => (uploadPercent.value = p))
    ElMessage.success(`${data.filename} 入库 ${data.chunks} 片`)
    await loadFiles()
  } catch (err) {
    const detail = err?.response?.data?.detail || err.message
    ElMessage.error(`上传失败：${detail}`)
  } finally {
    uploading.value = false
    uploadPercent.value = 0
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

  const reply = { role: 'assistant', content: '', sources: [] }
  messages.value.push(reply)
  await scrollToBottom()

  try {
    await streamChat(q, {
      // 把界面选择器里的模型传给后端：'ollama' 本地 / 'deepseek' 云端
      provider: provider.value || undefined,
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
    reply.content = `请求失败：${err.message}`
    ElMessage.error(`问答失败：${err.message}`)
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

onMounted(() => {
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
.hint {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
</style>
