import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { readFileSync } from 'fs'
import http from 'http'

// 应用版本号取自 src-tauri/tauri.conf.json(发版脚本会 bump 它), 编译期注入。
const __APP_VERSION__ = (() => {
  try {
    return JSON.parse(readFileSync(resolve(__dirname, '../src-tauri/tauri.conf.json'), 'utf-8')).version || ''
  } catch {
    return ''
  }
})()
const backendProxyTarget = process.env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  base: process.env.VITE_BASE_URL || '/',
  define: {
    __DESKTOP__: JSON.stringify(process.env.VITE_DESKTOP === '1'),
    __DESKTOP_WEB_PREVIEW__: JSON.stringify(process.env.VITE_DESKTOP_WEB_PREVIEW === '1'),
    __APP_VERSION__: JSON.stringify(__APP_VERSION__),
  },
  plugins: [
    vue(),
    {
      name: 'platform-plugin-proxy',
      configureServer(server) {
        // 平台插件资源：/{32位hex}/... → 代理到本地后端 8000
        server.middlewares.use((req, res, next) => {
          if (req.url && /^\/[0-9a-f]{32}\//.test(req.url)) {
            const proxyReq = http.request(
              `${backendProxyTarget}${req.url}`,
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
        target: backendProxyTarget,
        changeOrigin: true,
        ws: true
      },
      '/ai-builder/api': {
        target: backendProxyTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/ai-builder\/api/, '/api')
      },
      '/ai-builder/admin': {
        target: backendProxyTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ai-builder\/admin/, '/admin')
      },
      '^/admin(/|$)': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '^/platform(/|$)': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      // 2026-05-28: apaas 应用运行态 (自开发整页 Vue 预览) — /app/{tenantCode}/{appCode}/
      '^/app(/|$)': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '^/m(/|$)': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '/backend': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '/plugin': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '/xdap-admin': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '/xdap-plugin': {
        target: backendProxyTarget,
        changeOrigin: true
      },
      '/xdap-open': {
        target: backendProxyTarget,
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
