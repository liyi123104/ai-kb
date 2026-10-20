import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端统一用 /api 前缀访问后端；这里把 /api 代理到 FastAPI（8000），
// 同时去掉 /api，这样后端路由保持计划书 6.2 的原样（/chat、/files…），前端也不会跨域。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
