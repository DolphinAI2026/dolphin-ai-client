const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const path = require('path')
const apaasJson = require('./src/apaas.json')

const isPreview = process.env.VUE_APP_PREVIEW === 'true'

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: isPreview ? 8090 : 8080,
    hot: true,
    allowedHosts: 'all',
    ...(isPreview ? {} : {
      https: (() => {
        const keyPath = './https/server.key'
        const certPath = './https/server.crt'
        if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
          return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
        }
        return false
      })()
    }),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false },
    proxy: {
      '/custom': {
        target: 'http://localhost:9092',
        changeOrigin: true
      }
    }
  },
  configureWebpack: (config) => {
    if (isPreview) {
      delete config.output.library
      delete config.output.libraryTarget
    } else {
      config.output.library = apaasJson.outputName
      config.output.libraryTarget = 'umd'
    }
  },
  chainWebpack: (config) => {
    if (isPreview) {
      config.plugin('html').tap(args => {
        args[0].template = path.resolve(__dirname, 'preview/index.html')
        return args
      })
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
