import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import http from 'http'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'platform-plugin-proxy',
      configureServer(server) {
        // 平台插件资源：/{32位hex}/... → 代理到后端 8001
        server.middlewares.use((req, res, next) => {
          if (req.url && /^\/[0-9a-f]{32}\//.test(req.url)) {
            const proxyReq = http.request(
              `http://localhost:8001${req.url}`,
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
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '^/platform(/|$)': {
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
      '/xdap-admin': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/xdap-plugin': {
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
