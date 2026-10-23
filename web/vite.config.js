import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端统一用 /api 前缀访问后端；这里把 /api 代理到 FastAPI（8000），
// 同时去掉 /api，这样后端路由保持计划书 6.2 的原样（/chat、/files…），前端也不会跨域。
export default defineConfig({
  plugins: [vue()],
  server: {
    // 显式绑 IPv4：Vite 默认 host 是 "localhost"，在部分 Windows 环境只会监听 ::1，
    // 导致浏览器输 127.0.0.1:5173 打不开（实测踩到过）。
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
