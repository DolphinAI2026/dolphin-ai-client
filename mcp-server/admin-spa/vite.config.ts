import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const backendTarget = process.env.VITE_API_TARGET || 'http://localhost:8004'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5174,
    host: '127.0.0.1',  // 必须 bind IPv4 — iframe src 用 127.0.0.1，默认 vite 只 ::1 会被浏览器拒连
    proxy: {
      '/api': backendTarget
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})
