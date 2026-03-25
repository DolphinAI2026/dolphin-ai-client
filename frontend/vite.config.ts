import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  css: {
    preprocessorOptions: {
      less: {
        additionalData: '@import (reference) "@/styles/tokens.less";'
      }
    }
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/platform': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/backend': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/plugin': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/xdap-open': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/smartbi': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/apaas': {
        target: 'http://localhost:8001',
        changeOrigin: true
      }
    }
  }
})
