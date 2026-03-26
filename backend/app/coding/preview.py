"""
Preview Sandbox Generator - 生成组件预览的沙箱 HTML

为 aPaaS 自开发组件生成一个独立的预览页面:
- 加载 Vue 2 + Element UI + Lodash CDN
- Mock aPaaS SDK 环境 (APaaSSDK, FormEngine, df)
- 加载编译后的 UMD bundle
- 渲染组件预览
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_preview_html(
    template_type: str,
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
) -> str:
    """根据模板类型生成预览沙箱 HTML"""
    if template_type in ("FORM_COMPONENT", "form-component"):
        return _generate_form_component_preview(apaas_config, dist_base_url, output_name)
    elif template_type in ("MENU_PAGE", "FORM_PAGE", "menu-page", "form-page"):
        return _generate_page_preview(apaas_config, dist_base_url, output_name)
    elif template_type in ("MOBILE_COMPONENT", "mobile-component"):
        return _generate_form_component_preview(apaas_config, dist_base_url, output_name, mobile=True)
    else:
        return _generate_generic_preview(apaas_config, dist_base_url, output_name, template_type)


def _get_mock_sdk_script() -> str:
    """生成 Mock aPaaS SDK 的 JavaScript"""
    return """
    // ===== Mock aPaaS SDK =====
    window._ = window._;  // lodash already loaded from CDN

    // Mock XEventBus
    const _eventHandlers = {};
    const XEventBus = {
      emit: function(event, data) {
        console.log('[Preview] Event:', event, data);
        const handlers = _eventHandlers[event] || [];
        handlers.forEach(function(h) { try { h(data); } catch(e) {} });
      },
      on: function(event, handler) {
        if (!_eventHandlers[event]) _eventHandlers[event] = [];
        _eventHandlers[event].push(handler);
      },
      off: function(event, handler) {
        if (_eventHandlers[event]) {
          _eventHandlers[event] = _eventHandlers[event].filter(function(h) { return h !== handler; });
        }
      }
    };

    // Mock APaaSSDK
    window.APaaSSDK = {
      context: { XEventBus: XEventBus },
      getFormFieldValue: function() { return ''; },
      setFormFieldValue: function() {},
      openAPI: {
        getFormData: function() { return {}; },
        setFormData: function() {},
        getContext: function() { return { tenantId: 'mock', appId: 'mock' }; }
      }
    };

    // Mock df
    window.df = {
      getI18n: function() {
        return {
          mergeLocaleMessage: function() {},
          t: function(key) { return key; },
          locale: 'zh-CN'
        };
      }
    };

    // Mock FormEngine on Vue
    var _noop = function() {};
    var _customComponentEffectMap = new Map();

    // We need to setup FormEngine AFTER Vue is loaded but BEFORE component UMD
    function setupFormEngine() {
      if (!window.Vue) return;

      window.Vue.FormEngine = {
        WidgetControl: {
          registerEditorConfig: _noop,
          customComponentEffectMap: _customComponentEffectMap,
          getComponentByType: function() { return null; }
        },
        AbilityControl: {
          batchRegisterComponentTypeConfig: _noop,
          batchRegisterFieldValueConvert: _noop,
          formatFiledValue: function() { return ''; },
          batchRegisterCustomComponentValidator: _noop
        },
        registerCustomGroupWidgetConfig: _noop,
        registerCustomGroupFormListConfig: _noop
      };
    }
    """


def _get_mock_form_wrapper() -> str:
    """生成 Mock 表单容器组件"""
    return """
    // Mock form wrapper - provides renderGlobal inject
    Vue.component('x-proxy-form-item', {
      props: ['label', 'prop', 'rules'],
      template: '<div class="mock-form-item"><label v-if="label" class="mock-form-label">{{ label }}</label><slot></slot></div>'
    });

    var mockFormDataControl = {
      componentMap: new Map(),
      ctlComponentMap: new Map(),
      allTileFormItemList: [],
      ctlFormDataChanged: false,
      dataMaskingValue: {},
      dataFilterComponentList: { triggerComponents: [], dataSelectors: [] },
      getCompByKey: function() { return null; }
    };

    var mockEngineContext = {
      instance: { documentId: 'preview-doc', instanceId: 'preview-instance' },
      formConfig: {},
      platform: { tenantId: 'preview-tenant', appId: 'preview-app' }
    };

    var mockBsEventControl = {
      triggerEventValueChange: function() {},
      triggerEvent: function() {}
    };
    """


def _generate_form_component_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
    mobile: bool = False
) -> str:
    """生成表单组件预览 HTML"""
    widget_list = apaas_config.get("customWidgetList", [])
    component_code = widget_list[0]["code"] if widget_list else "UNKNOWN"
    component_text = widget_list[0].get("text", "Preview") if widget_list else "Preview"

    # 组件标签名 = outputName + "-edit"
    edit_tag = f"{output_name}-edit"
    read_tag = f"{output_name}-read"

    viewport_width = "375px" if mobile else "100%"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>组件预览 - {component_text}</title>
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <link rel="stylesheet" href="{dist_base_url}/{output_name}.css" onerror="console.log('No CSS file')">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f5f7fa;
      padding: 16px;
      max-width: {viewport_width};
      margin: 0 auto;
    }}
    .preview-header {{
      background: #fff;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 16px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .preview-header h3 {{
      font-size: 14px;
      color: #303133;
      font-weight: 500;
    }}
    .preview-tabs {{
      display: flex;
      gap: 8px;
    }}
    .preview-tabs button {{
      padding: 4px 12px;
      border: 1px solid #dcdfe6;
      border-radius: 4px;
      background: #fff;
      cursor: pointer;
      font-size: 12px;
      color: #606266;
      transition: all 0.2s;
    }}
    .preview-tabs button.active {{
      background: #409eff;
      color: #fff;
      border-color: #409eff;
    }}
    .preview-container {{
      background: #fff;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.08);
      min-height: 200px;
    }}
    .mock-form-item {{
      margin-bottom: 16px;
    }}
    .mock-form-label {{
      display: block;
      font-size: 14px;
      color: #606266;
      margin-bottom: 8px;
      font-weight: 500;
    }}
    .preview-error {{
      color: #f56c6c;
      padding: 16px;
      background: #fef0f0;
      border-radius: 4px;
      font-size: 13px;
    }}
    .preview-mode-label {{
      font-size: 12px;
      color: #909399;
      margin-top: 12px;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div id="app">
    <div class="preview-header">
      <h3>📦 {{{{ componentText }}}}</h3>
      <div class="preview-tabs">
        <button :class="{{active: mode === 'edit'}}" @click="mode='edit'">编辑</button>
        <button :class="{{active: mode === 'read'}}" @click="mode='read'">只读</button>
      </div>
    </div>
    <div class="preview-container">
      <component
        v-if="editComp && mode === 'edit'"
        :is="editComp"
        :widget="widget"
        :render-scene="'edit'"
        :form-data="formData"
        :global-form-data="formData"
        :prop-key="'preview_field'"
        :form-item-list="[]"
        :value-validated-status="{{}}"
      ></component>
      <component
        v-if="readComp && mode === 'read'"
        :is="readComp"
        :widget="widget"
        :render-scene="'read'"
        :form-data="formData"
        :global-form-data="formData"
        :prop-key="'preview_field'"
        :form-item-list="[]"
        :value-validated-status="{{}}"
      ></component>
      <div v-if="error" class="preview-error">⚠️ {{{{ error }}}}</div>
    </div>
    <div class="preview-mode-label">当前模式: {{{{ mode === 'edit' ? '编辑模式' : '只读模式' }}}}</div>
  </div>

  <!-- CDN Dependencies -->
  <script src="https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.min.js"></script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"></script>

  <script>
    {_get_mock_sdk_script()}
    setupFormEngine();
    {_get_mock_form_wrapper()}
  </script>

  <!-- Load built component UMD -->
  <script src="{dist_base_url}/{output_name}.umd.js"></script>

  <script>
    // Install component
    try {{
      var lib = window['{output_name}'] || window['{output_name.replace("-", "_")}'];
      if (lib && lib.default && lib.default.install) {{
        lib.default.install(Vue);
        console.log('[Preview] Component installed successfully');
      }} else if (lib && lib.install) {{
        lib.install(Vue);
        console.log('[Preview] Component installed (direct)');
      }} else {{
        console.warn('[Preview] No install method found, trying manual registration');
      }}
    }} catch (e) {{
      console.error('[Preview] Install error:', e);
    }}

    // Create app
    new Vue({{
      el: '#app',
      provide: function() {{
        return {{
          formEngine: {{
            formDataControl: mockFormDataControl,
            engineContext: mockEngineContext,
            bsEventControl: mockBsEventControl
          }},
          renderGlobal: {{
            formDataControl: mockFormDataControl,
            engineContext: mockEngineContext,
            bsEventControl: mockBsEventControl
          }},
          themeConfig: {{ theme: 'light' }}
        }};
      }},
      data: function() {{
        return {{
          mode: 'edit',
          componentText: '{component_text}',
          error: null,
          editComp: null,
          readComp: null,
          formData: {{ preview_field: '' }},
          widget: {{
            label: '{component_text}',
            uuid: 'preview-' + Date.now(),
            componentType: '{component_code}',
            customComponentConfig: {{}},
            visible: true,
            readOnly: false,
            required: false,
            placeholder: '请输入...'
          }}
        }};
      }},
      created: function() {{
        // Try to find registered components
        var editName = '{edit_tag}';
        var readName = '{read_tag}';

        this.editComp = Vue.options.components[editName] ||
                        Vue.options.components[editName.replace(/-/g, '')] ||
                        null;
        this.readComp = Vue.options.components[readName] ||
                        Vue.options.components[readName.replace(/-/g, '')] ||
                        null;

        if (!this.editComp) {{
          // Try to find any component that was registered
          var keys = Object.keys(Vue.options.components);
          var customKeys = keys.filter(function(k) {{ return k.indexOf('form-component') !== -1 || k.indexOf('FormComponent') !== -1; }});
          console.log('[Preview] Available components:', customKeys);
          if (customKeys.length > 0) {{
            this.editComp = Vue.options.components[customKeys[0]];
            if (customKeys.length > 1) {{
              this.readComp = Vue.options.components[customKeys[1]];
            }}
          }}
        }}

        if (!this.editComp) {{
          this.error = '未找到组件 "' + editName + '"，请检查组件是否正确注册。可用组件: ' + Object.keys(Vue.options.components).join(', ');
        }}
      }}
    }});
  </script>
</body>
</html>"""


def _generate_page_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
) -> str:
    """生成页面组件预览 HTML"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>页面预览 - {output_name}</title>
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <link rel="stylesheet" href="{dist_base_url}/{output_name}.css" onerror="console.log('No CSS file')">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
    #app {{ width: 100%; height: 100vh; }}
    .preview-error {{ color: #f56c6c; padding: 24px; text-align: center; }}
  </style>
</head>
<body>
  <div id="app">
    <component v-if="pageComp" :is="pageComp"></component>
    <div v-if="error" class="preview-error">⚠️ {{{{ error }}}}</div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.min.js"></script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"></script>

  <script>
    {_get_mock_sdk_script()}
    setupFormEngine();
  </script>

  <script src="{dist_base_url}/{output_name}.umd.js"></script>

  <script>
    try {{
      var lib = window['{output_name}'] || window['{output_name.replace("-", "_")}'];
      if (lib && lib.default && lib.default.install) {{
        lib.default.install(Vue);
      }} else if (lib && lib.install) {{
        lib.install(Vue);
      }}
    }} catch(e) {{
      console.error('[Preview] Install error:', e);
    }}

    new Vue({{
      el: '#app',
      provide: function() {{
        return {{
          renderGlobal: {{ formDataControl: {{}}, engineContext: {{}}, bsEventControl: {{}} }},
          themeConfig: {{ theme: 'light' }}
        }};
      }},
      data: function() {{
        return {{ pageComp: null, error: null }};
      }},
      created: function() {{
        var keys = Object.keys(Vue.options.components);
        var pageKeys = keys.filter(function(k) {{ return k !== 'ElAlert' && k.indexOf('El') !== 0; }});
        if (pageKeys.length > 0) {{
          this.pageComp = Vue.options.components[pageKeys[pageKeys.length - 1]];
        }} else {{
          this.error = '未找到页面组件';
        }}
      }}
    }});
  </script>
</body>
</html>"""


def _generate_generic_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
    template_type: str,
) -> str:
    """通用预览 - 尝试加载和渲染"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>预览 - {output_name}</title>
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <link rel="stylesheet" href="{dist_base_url}/{output_name}.css" onerror="">
  <style>
    body {{ font-family: -apple-system, sans-serif; padding: 24px; background: #f5f7fa; }}
    .info {{ background: #fff; padding: 24px; border-radius: 8px; text-align: center; color: #909399; }}
  </style>
</head>
<body>
  <div id="app">
    <div class="info">
      <h3>📦 {output_name}</h3>
      <p style="margin-top:12px">组件类型: {template_type}</p>
      <p style="margin-top:8px;color:#e6a23c">此类型组件暂不支持内联预览，请使用「在 IDE 中打开」后手动构建测试。</p>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.min.js"></script>
  <script>new Vue({{ el: '#app' }});</script>
</body>
</html>"""
