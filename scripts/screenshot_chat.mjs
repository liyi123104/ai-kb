import fs from 'node:fs'
const question = process.argv[2] || '什么是自注意力机制？'
const out = process.argv[3] || 'docs/screenshots/ui-answer.png'
const port = process.argv[4] || '9335'
const sleep = (ms) => new Promise(r => setTimeout(r, ms))

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
const page = list.find(t => t.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0; const pending = new Map()
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id) } })
await new Promise(r => ws.addEventListener('open', r))
const send = (method, params = {}) => new Promise(res => { const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })) })

await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: 'http://127.0.0.1:5173' })
await sleep(4000)

// 填值后必须等 Vue 重渲染，否则按钮仍是 disabled
await send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
  const input = document.querySelector('.input-area input')
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(input, ${JSON.stringify(question)})
  input.dispatchEvent(new Event('input', { bubbles: true }))
  return input.value
})()` })
await sleep(800)
const click = await send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
  const btn = [...document.querySelectorAll('.input-area button')].pop()
  if (!btn || btn.className.includes('is-disabled')) return 'still-disabled'
  btn.click(); return 'clicked'
})()` })
console.log('点击结果:', click.result.value)

let last = -1, stable = 0
for (let i = 0; i < 90; i++) {
  await sleep(1000)
  const q = await send('Runtime.evaluate', { returnByValue: true,
    expression: `document.querySelector('.msg.assistant .content')?.innerText?.length || 0` })
  const len = q.result.value || 0
  if (len > 0 && len === last) { stable++; if (stable >= 2) break } else stable = 0
  last = len
}
console.log('答案字符数:', last)
const meta = await send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
  const el = document.querySelector('.sources')
  return el ? el.innerText.replace(/\\n+/g, ' | ').slice(0, 160) : 'no-sources-dom'
})()` })
console.log('出处区:', meta.result.value)

const shot = await send('Page.captureScreenshot', { format: 'png' })
fs.writeFileSync(out, Buffer.from(shot.data, 'base64'))
console.log('已保存:', out)
ws.close()
