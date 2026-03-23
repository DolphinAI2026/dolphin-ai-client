/**
 * 模拟平台 $request：通过 devServer proxy 转发到后端
 * 支持 .asyncThen().asyncErrorCatch() 链式调用（与平台行为一致）
 */
export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    const ctrl = {}

    const promise = fetch(config.url, {
      method: (config.method || 'GET').toUpperCase(),
      headers: { 'Content-Type': 'application/json' },
      body: config.params != null ? JSON.stringify(config.params) : undefined
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status)
      return res.json()
    })

    ctrl.asyncThen = function (onSuccess, onError) {
      promise.then(onSuccess).catch(onError || function () {})
      return ctrl
    }

    ctrl.asyncErrorCatch = function (onError) {
      promise.catch(onError)
      return ctrl
    }

    return ctrl
  }
}
