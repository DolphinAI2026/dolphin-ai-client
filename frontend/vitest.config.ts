import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  define: {
    __DESKTOP__: 'false',
    __DESKTOP_WEB_PREVIEW__: 'false',
    __APP_VERSION__: "'test'",
    __BUILD_REVISION__: "'test'",
    __BUILD_TARGET__: "'test'",
  },
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') },
  },
  test: {
    include: ['src/**/*.spec.ts'],
    environment: 'node',
  },
})
