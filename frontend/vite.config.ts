import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import http from 'http'

// https://vite.dev/config/
export default defineConfig({
  base: process.env.VITE_BASE_URL || '/',
  plugins: [
    vue(),
    {
      name: 'platform-plugin-proxy',
      configureServer(server) {
        // 平台插件资源：/{32位hex}/... → 代理到本地后端 8000
        server.middlewares.use((req, res, next) => {
          if (req.url && /^\/[0-9a-f]{32}\//.test(req.url)) {
            const proxyReq = http.request(
              `http://localhost:8000${req.url}`,
              { method: req.method, headers: req.headers },
              (proxyRes) => {
                res.writeHead(proxyRes.statusCode || 200, proxyRes.headers)
                proxyRes.pipe(res)
              }
            )
            proxyReq.on('error', () => { res.writeHead(502); res.end('Proxy Error') })
            req.pipe(proxyReq)
          } else {
            next()
          }
        })
      }
    }
  ],
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
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ai-builder/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ai-builder\/api/, '/api')
      },
      '^/admin(/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '^/platform(/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      // 2026-05-28: apaas 应用运行态 (自开发整页 Vue 预览) — /app/{tenantCode}/{appCode}/
      '^/app(/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '^/m(/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/backend': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/plugin': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/xdap-admin': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/xdap-plugin': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/xdap-open': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/smartbi': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/apaas': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('/element-plus/')) return 'vendor-element-plus'
          if (id.includes('/@antv/x6/')) return 'vendor-x6'
          if (id.includes('/marked/') || id.includes('/highlight.js/')) return 'vendor-markdown'
          if (
            id.includes('/vue/') ||
            id.includes('/vue-router/') ||
            id.includes('/pinia/') ||
            id.includes('/@vue/')
          ) {
            return 'vendor-vue'
          }
          return 'vendor'
        }
      }
    }
  }
})
