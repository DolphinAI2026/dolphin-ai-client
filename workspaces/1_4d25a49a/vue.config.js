const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const apaasJson = require('./src/apaas.json')

function loadHttps() {
  const keyPath = './https/server.key'
  const certPath = './https/server.crt'
  if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
    return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
  }
  return false
}

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
    https: loadHttps(),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: {
    output: {
      library: apaasJson.outputName,
      libraryTarget: 'umd'
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
