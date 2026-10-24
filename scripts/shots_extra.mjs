/**
 * 补拍：更易读的回答 + 上传进度。
 * 用法：node scripts/shots_extra.mjs <会话Cookie> [输出目录]
 */
import fs from 'node:fs'
import path from 'node:path'

const session = process.argv[2]
const outDir = process.argv[3] || 'docs/screenshots/resume'
const PORT = Number(process.env.CDP_PORT || 9371)
const W = 1600
const H = 1000
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

fs.mkdirSync(outDir, { recursive: true })

let targets = null
for (let i = 0; i < 30; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await res.json()
    if (targets?.some((t) => t.type === 'page')) break
  } catch {
    /* 等 */
  }
  await sleep(500)
}
const page = targets?.find((t) => t.type === 'page')
if (!page) {
  console.error('找不到页面')
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
const send = (method, params = {}, t = 15000) =>
  new Promise((res) => {
    const id = ++seq
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        res(null)
      }
    }, t)
    pending.set(id, (v) => {
      clearTimeout(timer)
      res(v)
    })
    ws.send(JSON.stringify({ id, method, params }))
  })
const evalJs = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true })
  return r?.result?.value
}

async function shot(name, retries = 3) {
  for (let i = 0; i < retries; i++) {
    const r = await send('Page.captureScreenshot', { format: 'png' }, 25000)
    if (r?.data) {
      fs.writeFileSync(path.join(outDir, name), Buffer.from(r.data, 'base64'))
      console.log('  已保存', name)
      return true
    }
    await sleep(800)
  }
  console.log('  截图失败:', name)
  return false
}

async function ask(q) {
  await evalJs(`(() => {
    const input = document.querySelector('.input-area input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, ${JSON.stringify(q)})
    input.dispatchEvent(new Event('input', { bubbles: true }))
    return true
  })()`)
  await sleep(500)
  await evalJs(`(() => {
    const btn = [...document.querySelectorAll('.input-area button')].pop()
    if (btn && !btn.className.includes('is-disabled')) btn.click()
    return true
  })()`)
}

const lastLen = () =>
  evalJs(`(() => {
    const n = [...document.querySelectorAll('.msg.assistant .content')]
    return n.length ? n[n.length - 1].innerText.length : 0
  })()`)

async function waitStable(minLen = 60, timeout = 90000) {
  const start = Date.now()
  let last = -1
  let stable = 0
  while (Date.now() - start < timeout) {
    await sleep(700)
    const len = (await lastLen()) || 0
    if (len >= minLen && len === last) {
      stable += 1
      if (stable >= 3) return len
    } else stable = 0
    last = len
  }
  return last
}

async function main() {
  await send('Page.enable')
  await send('DOM.enable')
  await send('Network.enable')
  await send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: 1.5, mobile: false,
  })
  await send('Network.setCookie', {
    name: 'ai_kb_session', value: session, domain: '127.0.0.1', path: '/', httpOnly: true,
  })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/' })
  await sleep(6000)

  // A. 更易读的回答
  console.log('A 易读回答')
  await ask('RAG 相比纯参数化模型有什么优势？')
  console.log('  长度', await waitStable(60))
  await sleep(1500)
  await evalJs(`(() => { const el = document.querySelector('.chat-scroll, main'); if (el) el.scrollTop = el.scrollHeight; return true })()`)
  await sleep(700)
  await shot('02b-answer-rag.png')

  // B. 上传进度
  console.log('B 上传进度')
  const tmpA = path.join(outDir, '_up-a.md')
  const tmpB = path.join(outDir, '_up-b.md')
  fs.writeFileSync(tmpA, '# 上传演示 A\n\n检索增强生成（RAG）把检索到的外部知识拼进上下文。\n'.repeat(60))
  fs.writeFileSync(tmpB, '# 上传演示 B\n\n自注意力机制让模型可以并行处理序列。\n'.repeat(60))
  const doc = await send('DOM.getDocument', { depth: -1 }, 8000)
  const q = doc?.root
    ? await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' }, 8000)
    : null
  if (q?.nodeId) {
    await send('DOM.setFileInputFiles', { nodeId: q.nodeId, files: [tmpA, tmpB] }, 10000)
    for (let i = 0; i < 8; i++) {
      await sleep(700)
      const busy = await evalJs(`!!document.querySelector('.progress') || !!document.querySelector('.ingest-label') || /上传|入库/.test(document.body.innerText)`)
      if (busy) break
    }
    await sleep(900)
    await shot('06-upload.png')
  } else {
    console.log('  没有文件输入框')
  }
  fs.rmSync(tmpA, { force: true })
  fs.rmSync(tmpB, { force: true })

  ws.close()
  console.log('完成')
}

main().catch((e) => {
  console.error('失败:', e.message)
  process.exit(1)
})
