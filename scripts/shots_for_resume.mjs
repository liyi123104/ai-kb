/**
 * 拍简历用的界面截图。用真实交互，不用假数据。
 *
 * 用法：node scripts/shots_for_resume.mjs <会话Cookie> [输出目录]
 * 环境：CDP_PORT（默认 9370）
 *
 * 产出：
 *  01-home.png          首页：文件库 + 输入区
 *  02-answer.png        完整回答 + 出处列表
 *  03-streaming.png     生成中（带「停止」按钮）
 *  04-model-picker.png  模型下拉（本地 / 云端）
 *  05-refusal.png       无关问题拒答
 *  06-upload.png        多文件上传进度
 */
import fs from 'node:fs'
import path from 'node:path'

const session = process.argv[2]
const outDir = process.argv[3] || 'docs/screenshots/resume'
const PORT = Number(process.env.CDP_PORT || 9370)
const W = 1600
const H = 1000
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

fs.mkdirSync(outDir, { recursive: true })

let targets = null
for (let i = 0; i < 30; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await res.json()
    if (targets.some((t) => t.type === 'page')) break
  } catch {
    /* 等浏览器 */
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

async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' }, 20000)
  if (!r?.data) {
    console.log('  截图失败:', name)
    return
  }
  const file = path.join(outDir, name)
  fs.writeFileSync(file, Buffer.from(r.data, 'base64'))
  console.log('  已保存', name)
}

async function ask(question) {
  await evalJs(`(() => {
    const input = document.querySelector('.input-area input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, ${JSON.stringify(question)})
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

const lastAnswerLen = () =>
  evalJs(`(() => {
    const nodes = [...document.querySelectorAll('.msg.assistant .content')]
    return nodes.length ? nodes[nodes.length - 1].innerText.length : 0
  })()`)

async function waitStable(minLen = 40, timeout = 90000) {
  const start = Date.now()
  let last = -1
  let stable = 0
  while (Date.now() - start < timeout) {
    await sleep(700)
    const len = (await lastAnswerLen()) || 0
    if (len >= minLen && len === last) {
      stable += 1
      if (stable >= 3) return len
    } else {
      stable = 0
    }
    last = len
  }
  return last
}

async function scrollToBottom() {
  await evalJs(`(() => {
    const el = document.querySelector('.chat-scroll, .messages, main')
    if (el) el.scrollTop = el.scrollHeight
    window.scrollTo(0, document.body.scrollHeight)
    return true
  })()`)
  await sleep(600)
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

  // 01 首页
  console.log('01 首页')
  await shot('01-home.png')

  // 03 生成中（先拍，避免先有答案而打断）
  console.log('03 生成中')
  await ask('什么是自注意力机制？')
  await sleep(1800)
  await shot('03-streaming.png')

  // 02 完整答案 + 出处
  console.log('02 完整回答')
  const len = await waitStable(120)
  console.log('  答案长度', len)
  await sleep(1200)
  await scrollToBottom()
  await sleep(800)
  await shot('02-answer.png')

  // 04 模型下拉
  console.log('04 模型下拉')
  await evalJs(`document.querySelector('.model-picker .el-select')?.click()`)
  await sleep(900)
  await shot('04-model-picker.png')
  await evalJs(`document.body.click()`)
  await sleep(500)

  // 05 拒答
  console.log('05 拒答')
  await ask('今天北京天气怎么样？')
  const len2 = await waitStable(6)
  console.log('  拒答长度', len2)
  await sleep(1500)
  await scrollToBottom()
  await sleep(600)
  await shot('05-refusal.png')

  // 06 上传进度（失败就跳过）
  console.log('06 上传进度')
  try {
    const tmpA = path.join(outDir, '_shot-a.md')
    const tmpB = path.join(outDir, '_shot-b.md')
    fs.writeFileSync(tmpA, '# 演示文档 A\n\n检索增强生成把外部知识引入生成过程，可减少幻觉。\n'.repeat(40))
    fs.writeFileSync(tmpB, '# 演示文档 B\n\n自注意力机制让模型并行处理序列中的每个位置。\n'.repeat(40))
    const doc = await send('DOM.getDocument', { depth: -1 }, 8000)
    const q = doc?.root
      ? await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' }, 8000)
      : null
    if (q?.nodeId) {
      await send('DOM.setFileInputFiles', { nodeId: q.nodeId, files: [tmpA, tmpB] }, 10000)
      await sleep(1600)
      await shot('06-upload.png')
    } else {
      console.log('  没找到文件输入框，跳过')
    }
    fs.rmSync(tmpA, { force: true })
    fs.rmSync(tmpB, { force: true })
  } catch (e) {
    console.log('  上传截图跳过:', e.message)
  }

  ws.close()
  console.log('完成')
}

main().catch((e) => {
  console.error('失败:', e.message)
  process.exit(1)
})
