const path = require('path')
const { defineConfig } = require('@vue/cli-service')
const apaasJson = require('./src/apaas.json')
const { VantResolver } = require('unplugin-vue-components/resolvers');
const ComponentsPlugin = require('unplugin-vue-components/webpack');

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8081',
    hot: true,
    allowedHosts: 'all',
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: {
      overlay: false
    }
  },
  configureWebpack: {
    resolve: {
      alias: {
        '@shared': path.resolve(__dirname, '../shared')
      }
    },
    output: {
      library: apaasJson.outputName,
      libraryTarget: 'umd'
    },
    plugins: [
      ComponentsPlugin({
        resolvers: [VantResolver()],
      }),
    ]
  },
  css: {
    loaderOptions: {
      sass: {
        implementation: require('sass')
      }
    }
  }
})
