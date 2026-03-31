const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const md5 = require('md5')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
    https: {  key: fs.readFileSync('./https/server.key'),  cert: fs.readFileSync('./https/server.crt')},
    headers: {  'Access-Control-Allow-Origin': '*'},
    client: {
      overlay: false
    }
  },
  configureWebpack: {
    output: {
      library: md5(apaasJson.code),
      libraryTarget: 'umd'
    }
  },
  css: {
    loaderOptions: {
      sass: {
        implementation: require('sass'), // 使用 dart-sass 的方式
      }
    }
  }
})
