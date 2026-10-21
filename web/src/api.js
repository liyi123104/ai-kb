/**
 * 前端 API 层：统一走 /api 前缀（由 vite 代理到 FastAPI 8000），不发跨域请求。
 * 所有异常在调用处转成用户能看懂的提示（T3.5）。
 */
import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 600000 })

export function getHealth() {
  return http.get('/health')
}

export function getProviders() {
  return http.get('/providers')
}

export function getFiles() {
  return http.get('/files')
}

export function deleteFile(name) {
  return http.delete(`/files/${encodeURIComponent(name)}`)
}

export function uploadFile(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return http.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    }
  })
}

/**
 * 流式问答：用 fetch + ReadableStream 解析 SSE（T3.4）。
 * 事件格式与后端一致：event: sources / token / done / error
 * @param {string} question
 * @param {{onSources:Function, onToken:Function, onDone:Function, signal?:AbortSignal}} handlers
 */
export async function streamChat(question, { provider, onSources, onToken, onDone, signal }) {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, provider }),
    signal
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`后端返回 ${resp.status}：${detail || '无详情'}`)
  }
  if (!resp.body) throw new Error('当前浏览器不支持流式响应')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trimStart()
      }
      if (!data) continue
      try {
        const payload = JSON.parse(data)
        if (event === 'sources') onSources?.(payload)
        else if (event === 'token') onToken?.(payload)
        else if (event === 'done') onDone?.(payload)
        else if (event === 'error') throw new Error(String(payload))
      } catch (err) {
        if (event === 'error') throw err
        // 其他事件解析失败不致命，跳过即可
      }
    }
  }
}
