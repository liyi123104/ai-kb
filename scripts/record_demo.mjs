/**
 * 录制演示视频的取帧脚本：用 CDP 的 screencast 逐帧抓取真实界面。
 *
 * 用法：node scripts/record_demo.mjs <token> [输出目录]
 * 产物：<输出目录>/frame-000001.jpg ... 以及 frames.json（记录每帧时间戳）
 *
 * 说明：无头浏览器抓不到 PDF 阅读器，所以「出处高亮」那一屏由
 * scripts/build_demo_video.py 用后端真实返回的 PDF 页面图合成，字幕里会注明。
 */
import fs from 'node:fs'
import path from 'node:path'

const session = process.argv[2]   // 会话 cookie 值（避免用 ?token= 触发刷新）
const outDir = process.argv[3] || 'data/demo-frames'
const PORT = Number(process.env.CDP_PORT || 9360)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

fs.mkdirSync(outDir, { recursive: true })

// 连上浏览器
let targets = null
for (let i = 0; i < 30; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await res.json()
    if (targets.some((t) => t.type === 'page')) break
  } catch {
    /* 等浏览器起来 */
  }
  await sleep(500)
}
const page = targets.find((t) => t.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
const frames = []
let recording = false

ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data)
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg.result)
    pending.delete(msg.id)
    return
  }
  if (msg.method === 'Page.screencastFrame') {
    const { data, sessionId, metadata } = msg.params
    if (recording) {
      const idx = frames.length + 1
      const name = `frame-${String(idx).padStart(6, '0')}.jpg`
      fs.writeFileSync(path.join(outDir, name), Buffer.from(data, 'base64'))
      frames.push({ name, t: Date.now(), deviceTs: metadata?.timestamp || 0 })
    }
    send('Page.screencastFrameAck', { sessionId })
  }
})

await new Promise((r) => ws.addEventListener('open', r))
const send = (method, params = {}, timeoutMs = 20000) =>
  new Promise((resolve) => {
    const id = ++seq
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        console.log(`  [超时] ${method}`)
        resolve(null)
      }
    }, timeoutMs)
    pending.set(id, (v) => {
      clearTimeout(timer)
      resolve(v)
    })
    ws.send(JSON.stringify({ id, method, params }))
  })

const evalJs = async (expression, byValue = true) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: byValue, awaitPromise: true })
  return r?.result?.value
}

async function clickSend() {
  await evalJs(`(() => {
    const input = document.querySelector('.input-area input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, ${JSON.stringify('')})
    return true
  })()`)
}

async function ask(question) {
  await evalJs(`(() => {
    const input = document.querySelector('.input-area input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, ${JSON.stringify(question)})
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return input.value
  })()`)
  await sleep(500)
  await evalJs(`(() => {
    const btn = [...document.querySelectorAll('.input-area button')].pop()
    if (btn && !btn.className.includes('is-disabled')) btn.click()
    return true
  })()`)
}

async function waitAnswer(minLen = 40, timeout = 60000) {
  const start = Date.now()
  let last = -1
  let stable = 0
  while (Date.now() - start < timeout) {
    await sleep(700)
    const len = (await evalJs(`document.querySelector('.msg.assistant .content')?.innerText?.length || 0`)) || 0
    if (len >= minLen && len === last) {
      stable += 1
      if (stable >= 2) return len
    } else {
      stable = 0
    }
    last = len
  }
  return last
}

async function pickCloudModel() {
  await evalJs(`document.querySelector('.model-picker .el-select')?.click()`)
  await sleep(700)
  await evalJs(`(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    const cloud = items.find((i) => i.innerText.includes('云端'))
    if (cloud) { cloud.click(); return cloud.innerText }
    return null
  })()`)
  await sleep(500)
}

async function uploadFiles(files) {
  // el-upload 内部有一个隐藏的 file input，直接给它塞文件
  const doc = await send('DOM.getDocument', { depth: -1 }, 8000)
  if (!doc || !doc.root) return false
  const root = doc.root
  const q = await send('DOM.querySelector', { nodeId: root.nodeId, selector: 'input[type=file]' }, 8000)
  const nodeId = q && q.nodeId
  if (!nodeId) return false
  await send('DOM.setFileInputFiles', { nodeId, files }, 10000)
  return true
}

async function main() {
  await send('Page.enable')
  await send('DOM.enable')
  await send('Network.enable')
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  })
  // 直接注入会话 Cookie：页面一打开就是已登录，避免 ?token= 触发 reload（reload 会让 CDP 评估超时）
  await send('Network.setCookie', {
    name: 'ai_kb_session', value: session, domain: '127.0.0.1', path: '/', httpOnly: true,
  })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/' })
  await sleep(6000)   // 首屏加载

  // 开始录制
  await send('Page.startScreencast', {
    format: 'jpeg', quality: 82, maxWidth: 1440, maxHeight: 900, everyNthFrame: 1,
  })
  recording = true
  const t0 = Date.now()
  console.log('开始录制')

  // 场景 1：首页 + 文件列表（4 秒）
  await sleep(4000)

  // 场景 2：上传两个文件
  const tmpA = path.join(outDir, '_demo-a.md')
  const tmpB = path.join(outDir, '_demo-b.md')
  fs.writeFileSync(tmpA, '# RAG 演示文件 A\n\n检索增强生成把检索与生成结合起来，能显著减少幻觉。\n'.repeat(12))
  fs.writeFileSync(tmpB, '# RAG 演示文件 B\n\n自注意力机制让模型可以并行处理序列中的每个位置。\n'.repeat(12))
  try {
    const ok = await uploadFiles([tmpA, tmpB])
    console.log('选择文件:', ok)
    await sleep(1500)
    // 等入库完成（进度条消失），最多 40 秒
    for (let i = 0; i < 20; i++) {
      const busy = await evalJs(`!!document.querySelector('.progress') || !!document.querySelector('.ingest-label')`)
      if (!busy && i > 2) break
      await sleep(2000)
    }
  } catch (e) {
    console.log('上传场景跳过:', e.message)
  }
  await sleep(1500)
  const fileCount = await evalJs(`document.body.innerText.match(/已入库文件（(\\d+)）/)?.[1] || '?'`)
  console.log('文件数:', fileCount)

  // 场景 3：提问
  await ask('什么是自注意力机制？')
  const len1 = await waitAnswer(60)
  console.log('答案长度:', len1)
  await sleep(2500)

  // 场景 4：切云端模型再问
  await pickCloudModel()
  await sleep(1200)
  await ask('RAG 相比纯参数化模型有什么优势？')
  const len2 = await waitAnswer(60)
  console.log('云端答案长度:', len2)
  await sleep(2500)

  // 场景 5：无关问题（展示拒答）
  await ask('今天北京天气怎么样？')
  const len3 = await waitAnswer(8)
  console.log('拒答长度:', len3)
  await sleep(3000)

  recording = false
  await send('Page.stopScreencast')
  const total = (Date.now() - t0) / 1000
  const meta = { session: '(injected)', startedAt: t0, durationSec: total, frames: frames.map((f) => ({ name: f.name, t: f.t - t0 })) }
  fs.writeFileSync(path.join(outDir, 'frames.json'), JSON.stringify(meta, null, 2))
  console.log(`录制结束：${frames.length} 帧，${total.toFixed(1)} 秒`)
  ws.close()
}

main().catch((e) => {
  console.error('录制失败:', e.message)
  process.exit(1)
})
