/**
 * 录制演示视频：用「定时截图」代替 screencast（后者在无头环境会卡死）。
 *
 * 用法：node scripts/record_demo2.mjs <sessionCookie值> [输出目录]
 * 环境：CDP_PORT（默认 9360）
 *
 * 产物：<输出目录>/frame-000001.jpg ... + frames.json（每帧相对时间戳）
 */
import fs from 'node:fs'
import path from 'node:path'

const session = process.argv[2]
const outDir = process.argv[3] || 'data/demo-frames'
const PORT = Number(process.env.CDP_PORT || 9360)
const FPS_MS = 250
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

fs.mkdirSync(outDir, { recursive: true })

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
const page = targets?.find((t) => t.type === 'page')
if (!page) {
  console.error('找不到页面目标')
  process.exit(1)
}
const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m.result)
    pending.delete(m.id)
  }
})
await new Promise((r) => ws.addEventListener('open', r))

const send = (method, params = {}, timeoutMs = 15000) =>
  new Promise((resolve) => {
    const id = ++seq
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        resolve(null)
      }
    }, timeoutMs)
    pending.set(id, (v) => {
      clearTimeout(timer)
      resolve(v)
    })
    ws.send(JSON.stringify({ id, method, params }))
  })

const evalJs = async (expression, timeoutMs = 15000) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true }, timeoutMs)
  return r?.result?.value
}

// ---------------- 截图循环 ----------------
const frames = []
let recording = false
async function captureLoop() {
  const t0 = Date.now()
  while (recording) {
    const start = Date.now()
    const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: 82 }, 8000)
    if (r?.data) {
      const idx = frames.length + 1
      const name = `frame-${String(idx).padStart(6, '0')}.jpg`
      fs.writeFileSync(path.join(outDir, name), Buffer.from(r.data, 'base64'))
      frames.push({ name, t: Date.now() - t0 })
    }
    const wait = FPS_MS - (Date.now() - start)
    if (wait > 0) await sleep(wait)
  }
}

// ---------------- 界面操作 ----------------
async function ask(question) {
  await evalJs(`(() => {
    const input = document.querySelector('.input-area input')
    if (!input) return 'no-input'
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, ${JSON.stringify(question)})
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return 'ok'
  })()`)
  await sleep(600)
  await evalJs(`(() => {
    const btn = [...document.querySelectorAll('.input-area button')].pop()
    if (btn && !btn.className.includes('is-disabled')) { btn.click(); return 'clicked' }
    return 'disabled'
  })()`)
}

async function waitAnswer(minLen = 40, timeout = 60000) {
  const start = Date.now()
  let last = -1
  let stable = 0
  while (Date.now() - start < timeout) {
    await sleep(800)
    const len = (await evalJs(`(() => {
      const nodes = [...document.querySelectorAll('.msg.assistant .content')]
      return nodes.length ? nodes[nodes.length - 1].innerText.length : 0
    })()`)) || 0
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
  await sleep(800)
  return evalJs(`(() => {
    const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    const cloud = items.find((i) => i.innerText.includes('云端'))
    if (cloud) { cloud.click(); return cloud.innerText.trim() }
    return null
  })()`)
}

async function main() {
  await send('Page.enable')
  await send('DOM.enable')
  await send('Network.enable')
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  })
  await send('Network.setCookie', {
    name: 'ai_kb_session', value: session, domain: '127.0.0.1', path: '/', httpOnly: true,
  })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/' })
  await sleep(5500)

  // 清掉上一轮的会话，画面从干净状态开始
  await evalJs(`(() => { const b = document.querySelector('.files .refresh, .list-head .el-button'); return true })()`)

  recording = true
  const loop = captureLoop()
  console.log('开始录制')

  // 场景 1：首页与文件列表
  await sleep(4000)

  // 场景 2：提一个中文问题
  console.log('提问 1:', await ask('什么是自注意力机制？'))
  console.log('答案长度:', await waitAnswer(60))
  await sleep(3000)

  // 场景 3：切云端模型
  console.log('切换模型:', await pickCloudModel())
  await sleep(1500)
  console.log('提问 2:', await ask('RAG 相比纯参数化模型有什么优势？'))
  console.log('云端答案:', await waitAnswer(60))
  await sleep(3000)

  // 场景 4：无关问题，展示拒答
  console.log('提问 3:', await ask('今天北京天气怎么样？'))
  console.log('拒答长度:', await waitAnswer(6))
  await sleep(3500)

  recording = false
  await loop
  const total = frames.length ? frames[frames.length - 1].t / 1000 : 0
  fs.writeFileSync(
    path.join(outDir, 'frames.json'),
    JSON.stringify({ frames, durationSec: total }, null, 2),
  )
  console.log(`录制结束：${frames.length} 帧，约 ${total.toFixed(1)} 秒`)
  ws.close()
}

main().catch((e) => {
  recording = false
  console.error('录制失败:', e.message)
  process.exit(1)
})
