import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import http from 'http'

const backendTarget = process.env.VITE_API_TARGET || 'http://localhost:8004'

// https://vite.dev/config/
export default defineConfig({
  base: process.env.VITE_BASE_URL || '/',
  plugins: [
    vue(),
    {
      name: 'platform-plugin-proxy',
      configureServer(server) {
        // 平台插件资源：/{32位hex}/... → 代理到本地后端
        server.middlewares.use((req, res, next) => {
          if (req.url && /^\/[0-9a-f]{32}\//.test(req.url)) {
            const proxyReq = http.request(
              `${backendTarget}${req.url}`,
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
        target: backendTarget,
        changeOrigin: true
      },
      '/admin': {
        target: backendTarget,
        changeOrigin: true
      },
      '^/platform(/|$)': {
        target: backendTarget,
        changeOrigin: true
      },
      '/backend': {
        target: backendTarget,
        changeOrigin: true
      },
      '/plugin': {
        target: backendTarget,
        changeOrigin: true
      },
      '/xdap-admin': {
        target: backendTarget,
        changeOrigin: true
      },
      '/xdap-plugin': {
        target: backendTarget,
        changeOrigin: true
      },
      '/xdap-open': {
        target: backendTarget,
        changeOrigin: true
      },
      '/smartbi': {
        target: backendTarget,
        changeOrigin: true
      },
      '/apaas': {
        target: backendTarget,
        changeOrigin: true
      }
    }
  }
})
