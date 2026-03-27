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
    project_type: Optional[str] = None,
) -> str:
    """根据模板类型生成预览沙箱 HTML"""
    normalized_project_type = (project_type or "").lower()
    normalized_template_type = (template_type or "").lower()
    is_mobile_component = normalized_project_type == "mobile-component" or normalized_template_type == "mobile_component"
    is_mobile_page = normalized_project_type == "mobile-page" or normalized_template_type == "mobile_page"

    if template_type in ("FORM_COMPONENT", "form-component") or is_mobile_component:
        return _generate_form_component_preview(
            apaas_config,
            dist_base_url,
            output_name,
            mobile=is_mobile_component,
        )
    elif template_type in ("PAGE_LAYOUT", "page-layout"):
        return _generate_layout_preview(
            apaas_config,
            dist_base_url,
            output_name,
        )
    elif template_type in ("MENU_PAGE", "FORM_PAGE", "menu-page", "form-page") or is_mobile_page:
        return _generate_page_preview(
            apaas_config,
            dist_base_url,
            output_name,
            mobile=is_mobile_page,
        )
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
    var _previewLocaleMessages = { 'zh-CN': {}, 'en-US': {} };
    function _mergePreviewMessages(target, source) {
      if (!source || typeof source !== 'object') return target;
      Object.keys(source).forEach(function(key) {
        var value = source[key];
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          if (!target[key] || typeof target[key] !== 'object' || Array.isArray(target[key])) {
            target[key] = {};
          }
          _mergePreviewMessages(target[key], value);
        } else {
          target[key] = value;
        }
      });
      return target;
    }
    function _resolvePreviewMessage(locale, key) {
      var current = _previewLocaleMessages[locale] || {};
      var segments = String(key || '').split('.');
      for (var i = 0; i < segments.length; i += 1) {
        if (current && Object.prototype.hasOwnProperty.call(current, segments[i])) {
          current = current[segments[i]];
        } else {
          return null;
        }
      }
      return typeof current === 'string' ? current : null;
    }
    var _previewI18n = {
      mergeLocaleMessage: function(locale, messages) {
        if (!_previewLocaleMessages[locale]) {
          _previewLocaleMessages[locale] = {};
        }
        _mergePreviewMessages(_previewLocaleMessages[locale], messages || {});
      },
      t: function(key) {
        return _resolvePreviewMessage(this.locale, key) || key;
      },
      locale: 'zh-CN'
    };
    window.__PREVIEW_VUE_INSTANCE__ = null;
    window.df = {
      getI18n: function() {
        return _previewI18n;
      },
      getVue: function() {
        if (window.__PREVIEW_VUE_INSTANCE__) {
          return window.__PREVIEW_VUE_INSTANCE__;
        }
        if (window.Vue) {
          return {
            constructor: window.Vue,
            $t: function(key) { return _previewI18n.t(key); }
          };
        }
        return {
          constructor: {
            FormEngine: {}
          },
          $t: function(key) { return key; }
        };
      }
    };

    // Mock FormEngine on Vue
    var _noop = function() {};
    var _customComponentEffectMap = new Map();

    // We need to setup FormEngine AFTER Vue is loaded but BEFORE component UMD
    function setupFormEngine() {
      if (!window.Vue) return;

      if (!window.Vue.prototype.$t) {
        window.Vue.prototype.$t = function(key) {
          return _previewI18n.t(key);
        };
      }
      if (!window.Vue.prototype.$i18n) {
        window.Vue.prototype.$i18n = _previewI18n;
      }

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

    function createPreviewRequestControl(config) {
      var rows = [
        { id: 'row-001', name: '华东大区', code: 'EAST-001', status: '启用' },
        { id: 'row-002', name: '华南大区', code: 'SOUTH-002', status: '启用' },
        { id: 'row-003', name: '西南大区', code: 'WEST-003', status: '停用' },
        { id: 'row-004', name: '北方运营中心', code: 'NORTH-004', status: '启用' }
      ];
      var keyword = (((config || {}).params || {}).keyword || '').toLowerCase();
      var filtered = rows.filter(function(row) {
        if (!keyword) return true;
        return [row.name, row.code, row.status].some(function(value) {
          return String(value || '').toLowerCase().indexOf(keyword) !== -1;
        });
      });
      var page = Number((((config || {}).params || {}).page || 1));
      var pageSize = Number((((config || {}).params || {}).pageSize || filtered.length || 10));
      var start = Math.max(0, (page - 1) * pageSize);
      var payload = {
        data: filtered.slice(start, start + pageSize),
        total: filtered.length,
      };
      var promise = Promise.resolve(payload);
      var ctrl = {};
      ctrl.asyncThen = function(onSuccess, onError) {
        promise.then(onSuccess).catch(onError || function() {});
        return ctrl;
      };
      ctrl.asyncErrorCatch = function(onError) {
        promise.catch(onError || function() {});
        return ctrl;
      };
      return ctrl;
    }

    function setupPreviewRequest() {
      if (!window.Vue) return;
      window.Vue.prototype.$request = function(config) {
        return createPreviewRequestControl(config);
      };
    }
    """


def _get_mock_form_wrapper() -> str:
    """生成 Mock 表单容器组件"""
    return """
    // Mock form wrapper - provides renderGlobal inject
    Vue.component('x-proxy-form-item', {
      inheritAttrs: false,
      props: ['label', 'prop', 'rules', 'showRequired', 'titleDescription', 'processTitle'],
      computed: {
        displayLabel: function() {
          return this.label || this.processTitle || '';
        },
        displayDesc: function() {
          return this.titleDescription || this.$attrs.titleDescription || '';
        },
        displayRequired: function() {
          return !!(this.showRequired || this.$attrs.showRequired);
        }
      },
      template: '<div class="mock-form-item">' +
        '<label v-if="displayLabel" class="mock-form-label">' +
          '<span>{{ displayLabel }}</span>' +
          '<span v-if="displayRequired" class="mock-form-required">*</span>' +
        '</label>' +
        '<div v-if="displayDesc" class="mock-form-desc">{{ displayDesc }}</div>' +
        '<div class="mock-form-body"><slot></slot></div>' +
      '</div>'
    });

    var mockFormDataControl = {
      componentMap: new Map(),
      ctlComponentMap: new Map(),
      allTileFormItemList: [],
      ctlFormDataChanged: false,
      dataMaskingValue: {},
      dataFilterComponentList: { triggerComponents: [], dataSelectors: [] },
      getCompByKey: function() { return null; },
      getFormItemByUuid: function(uuid) {
        return this.componentMap.get(uuid) ||
          this.allTileFormItemList.find(function(item) { return item && item.uuid === uuid; }) ||
          null;
      },
      getFormItemList: function() {
        return this.allTileFormItemList;
      }
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


def _get_component_preview_setting_schema(component_code: str) -> list[dict]:
    """返回预览面板中可直出展示的组件专属配置 schema。"""
    normalized_code = (component_code or "").upper()

    if "UPLOAD" in normalized_code or "AVATAR" in normalized_code:
        return [
            {
                "key": "placeholderText",
                "label": "占位文本",
                "type": "text",
                "default": "上传头像",
                "help": "组件空状态下展示的提示文案。",
            },
            {
                "key": "maxSize",
                "label": "文件大小限制",
                "type": "number",
                "default": 5,
                "min": 1,
                "max": 20,
                "step": 1,
                "unit": "MB",
                "help": "限制单张图片上传大小。",
            },
            {
                "key": "enableCropper",
                "label": "启用裁剪",
                "type": "boolean",
                "default": True,
            },
            {
                "key": "circleCrop",
                "label": "圆形裁剪",
                "type": "boolean",
                "default": True,
            },
            {
                "key": "showPreview",
                "label": "显示预览",
                "type": "boolean",
                "default": True,
            },
            {
                "key": "previewShape",
                "label": "预览形状",
                "type": "select",
                "default": "both",
                "options": [
                    {"label": "圆形", "value": "circle"},
                    {"label": "方形", "value": "square"},
                    {"label": "两者", "value": "both"},
                ],
            },
        ]

    return []


def _generate_form_component_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
    mobile: bool = False
) -> str:
    """生成表单组件预览 HTML（按设计器通用属性结构映射）"""
    widget_list = apaas_config.get("customWidgetList", [])
    component_code = widget_list[0]["code"] if widget_list else "UNKNOWN"
    component_text = widget_list[0].get("text", "Preview") if widget_list else "Preview"

    edit_tag = f"{output_name}-edit"
    read_tag = f"{output_name}-read"
    placeholder = "请选择..." if mobile else "请输入..."
    width_options = [
        {"key": "quarter", "label": "1/4", "displayWidth": 6, "mobileWidth": 6, "styleWidth": "25%"},
        {"key": "third", "label": "1/3", "displayWidth": 8, "mobileWidth": 8, "styleWidth": "33.3333%"},
        {"key": "half", "label": "1/2", "displayWidth": 12, "mobileWidth": 12, "styleWidth": "50%"},
        {"key": "twothirds", "label": "2/3", "displayWidth": 16, "mobileWidth": 16, "styleWidth": "66.6667%"},
        {"key": "threequarters", "label": "3/4", "displayWidth": 18, "mobileWidth": 18, "styleWidth": "75%"},
        {"key": "full", "label": "整行", "displayWidth": 24, "mobileWidth": 24, "styleWidth": "100%"},
    ]
    component_setting_schema = _get_component_preview_setting_schema(component_code)

    widget_defaults = {
        "label": component_text,
        "uuid": "preview-widget",
        "componentType": component_code,
        "visible": True,
        "readOnly": False,
        "required": False,
        "titleDescription": "",
        "placeholder": placeholder,
        "display": {
            "label": component_text,
            "width": 24,
            "mobileWidth": 24,
            "height": 1,
            "hidden": False,
            "readOnly": False,
            "required": False,
            "onlyCreateEdit": False,
        },
        "allow": {
            "formulaRule": False,
        },
        "validator": {
            "uniqueCheck": False,
        },
        "validatorList": [],
        "special": {
            "saveWithHidden": False,
            "hiddenTrigger": False,
            "triggerBusinessEvents": [],
        },
        "customComponentConfig": {
            "placeholder": placeholder,
        },
    }
    widget_defaults_json = json.dumps(widget_defaults, ensure_ascii=False)
    widget_custom_config_json = json.dumps(
        widget_defaults["customComponentConfig"],
        ensure_ascii=False,
        indent=2,
    )
    width_options_json = json.dumps(width_options, ensure_ascii=False)
    component_setting_schema_json = json.dumps(component_setting_schema, ensure_ascii=False)
    preview_shell_class = "mobile" if mobile else "desktop"

    template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>组件预览 - __COMPONENT_TEXT__</title>
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <link rel="stylesheet" href="__DIST_BASE_URL__/__OUTPUT_NAME__.css" onerror="console.log('No CSS file')">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f4f7fb;
      padding: 18px;
      color: #1f2937;
    }
    .preview-shell {
      min-height: calc(100vh - 36px);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .preview-header {
      background: #ffffff;
      border-radius: 18px;
      padding: 16px 18px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .preview-header-main {
      min-width: 0;
    }
    .preview-header h3 {
      font-size: 16px;
      color: #0f172a;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .preview-header p {
      font-size: 12px;
      color: #64748b;
      line-height: 1.6;
    }
    .preview-tabs {
      display: flex;
      gap: 8px;
    }
    .preview-tabs button {
      padding: 8px 16px;
      border: 1px solid #d5dce7;
      border-radius: 999px;
      background: #ffffff;
      cursor: pointer;
      font-size: 13px;
      color: #475569;
      font-weight: 600;
      transition: all 0.2s;
    }
    .preview-tabs button.active {
      background: #2f80ed;
      color: #fff;
      border-color: #2f80ed;
    }
    .preview-workbench {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 16px;
      align-items: start;
    }
    .preview-stage,
    .preview-inspector {
      background: #ffffff;
      border-radius: 20px;
      border: 1px solid #e2e8f0;
      box-shadow: 0 16px 32px rgba(15, 23, 42, 0.05);
    }
    .preview-stage {
      padding: 18px;
    }
    .preview-stage-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    .preview-stage-title {
      font-size: 13px;
      font-weight: 700;
      color: #111827;
    }
    .preview-stage-meta {
      font-size: 12px;
      color: #64748b;
      margin-top: 4px;
    }
    .preview-canvas-shell {
      border-radius: 18px;
      border: 1px dashed #cad5f5;
      background: #f8fbff;
      padding: 18px;
      min-height: 360px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .preview-canvas {
      width: min(100%, 860px);
      background: #fff;
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 16px 30px rgba(15, 23, 42, 0.06);
      border: 1px solid #e8eef7;
    }
    .preview-canvas.mobile {
      width: min(100%, 390px);
      min-height: 220px;
      padding: 18px;
      border-radius: 28px;
    }
    .preview-field-shell {
      width: 100%;
      max-width: 100%;
      margin-right: auto;
      transition: width 0.2s ease;
    }
    .preview-hidden-state {
      display: flex;
      flex-direction: column;
      gap: 8px;
      align-items: center;
      justify-content: center;
      min-height: 220px;
      text-align: center;
      color: #64748b;
    }
    .preview-hidden-state strong {
      color: #111827;
      font-size: 15px;
    }
    .preview-inspector {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: sticky;
      top: 18px;
      max-height: calc(100vh - 36px);
      overflow: auto;
    }
    .inspector-section {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .inspector-title {
      font-size: 13px;
      font-weight: 700;
      color: #4f46e5;
    }
    .inspector-field {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .inspector-field span {
      font-size: 12px;
      color: #475569;
      font-weight: 600;
    }
    .inspector-field input,
    .inspector-field textarea {
      width: 100%;
      border: 1px solid #d7e0eb;
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 13px;
      color: #111827;
      background: #ffffff;
      outline: none;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
      resize: vertical;
    }
    .inspector-field input:focus,
    .inspector-field textarea:focus {
      border-color: #7aa9ff;
      box-shadow: 0 0 0 3px rgba(47, 128, 237, 0.14);
    }
    .inspector-field textarea {
      min-height: 150px;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    .inspector-widths {
      display: flex;
      border: 1px solid #d7e0eb;
      border-radius: 10px;
      overflow: hidden;
    }
    .inspector-widths button {
      flex: 1 1 0;
      border: none;
      border-right: 1px solid #d7e0eb;
      background: #ffffff;
      padding: 11px 0;
      cursor: pointer;
      color: #94a3b8;
      font-size: 13px;
      font-weight: 600;
      transition: background 0.2s ease, color 0.2s ease;
    }
    .inspector-widths button:last-child {
      border-right: none;
    }
    .inspector-widths button.active {
      background: #2f80ed;
      color: #fff;
    }
    .rule-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 36px;
    }
    .rule-label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #1f2937;
      font-size: 13px;
      font-weight: 600;
    }
    .rule-label .hint {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 999px;
      border: 1px solid #cfd8e3;
      color: #94a3b8;
      font-size: 12px;
    }
    .switch {
      width: 46px;
      height: 28px;
      border-radius: 999px;
      background: #d1d5db;
      position: relative;
      border: none;
      cursor: pointer;
      transition: background 0.2s ease;
    }
    .switch::after {
      content: '';
      position: absolute;
      top: 3px;
      left: 3px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
      transition: transform 0.2s ease;
    }
    .switch.active {
      background: #2f80ed;
    }
    .switch.active::after {
      transform: translateX(18px);
    }
    .business-events {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .business-events-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .icon-button {
      width: 32px;
      height: 32px;
      border-radius: 999px;
      border: 1px solid #d7e0eb;
      background: #fff;
      color: #64748b;
      font-size: 18px;
      line-height: 1;
      cursor: pointer;
    }
    .business-event-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .business-event-item input {
      flex: 1;
    }
    .business-empty {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.6;
    }
    .inspector-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .inspector-actions button {
      border: none;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.2s ease, opacity 0.2s ease;
    }
    .inspector-actions button:hover {
      transform: translateY(-1px);
    }
    .inspector-actions .primary {
      background: #2f80ed;
      color: #fff;
    }
    .inspector-actions .secondary {
      background: #eef3f8;
      color: #334155;
    }
    .inspector-inline-input {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .inspector-inline-input .unit {
      font-size: 12px;
      color: #94a3b8;
      white-space: nowrap;
    }
    .collapsible-panel {
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 12px;
      background: #fafcff;
    }
    .collapsible-panel summary {
      list-style: none;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      color: #334155;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .collapsible-panel summary::-webkit-details-marker {
      display: none;
    }
    .collapsible-panel summary::after {
      content: '展开';
      font-size: 12px;
      font-weight: 600;
      color: #94a3b8;
    }
    .collapsible-panel[open] summary::after {
      content: '收起';
    }
    .collapsible-panel-body {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .inspector-error {
      font-size: 12px;
      color: #dc2626;
      line-height: 1.6;
    }
    .inspector-help {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.7;
    }
    .preview-error {
      color: #f56c6c;
      padding: 16px;
      background: #fef0f0;
      border-radius: 12px;
      font-size: 13px;
    }
    .preview-mode-label {
      font-size: 12px;
      color: #64748b;
    }
    @media (max-width: 980px) {
      .preview-workbench {
        grid-template-columns: 1fr;
      }
      .preview-inspector {
        position: static;
        top: auto;
        max-height: none;
      }
    }
    @media (max-width: 640px) {
      body {
        padding: 12px;
      }
      .preview-header {
        padding: 12px;
        border-radius: 16px;
        align-items: flex-start;
        flex-direction: column;
      }
      .preview-stage,
      .preview-inspector {
        border-radius: 18px;
        padding: 14px;
      }
      .preview-canvas {
        padding: 16px;
      }
      .inspector-widths {
        overflow-x: auto;
      }
      .inspector-widths button {
        min-width: 58px;
      }
    }
  </style>
</head>
<body>
  <div id="app">
    <div class="preview-shell __PREVIEW_SHELL_CLASS__">
        <div class="preview-header">
          <div class="preview-header-main">
            <h3>组件预览 · {{ componentText }}</h3>
            <p>默认只展示当前预览里会直接生效的通用属性和组件专属配置；更完整的平台级能力收在高级属性中，避免为了对齐结构而干扰调试。</p>
          </div>
        <div class="preview-tabs">
          <button :class="{ active: mode === 'edit' }" @click="mode='edit'">编辑</button>
          <button :class="{ active: mode === 'read' }" @click="mode='read'">只读</button>
        </div>
      </div>

      <div class="preview-workbench">
        <section class="preview-stage">
          <div class="preview-stage-head">
            <div>
              <div class="preview-stage-title">实时效果</div>
              <div class="preview-stage-meta">当前模式: {{ mode === 'edit' ? '编辑模式' : '只读模式' }}</div>
            </div>
            <div class="preview-mode-label">{{ widget.visible === false ? '当前字段已隐藏' : (widget.required ? '已开启必填' : '未开启必填') }}</div>
          </div>
          <div class="preview-canvas-shell">
            <div class="preview-canvas" :class="{ mobile: isMobile }">
              <div v-if="widget.visible !== false">
                <div class="preview-field-shell" :style="fieldShellStyle">
                  <component
                    v-if="editComp && mode === 'edit'"
                    :is="editComp"
                    :widget="widget"
                    :render-scene="'edit'"
                    :form-data="formData"
                    :global-form-data="formData"
                    :prop-key="'preview_field'"
                    :form-item-list="[]"
                    :value-validated-status="{}"
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
                    :value-validated-status="{}"
                  ></component>
                </div>
                <div v-if="error" class="preview-error">⚠️ {{ error }}</div>
              </div>
              <div v-else class="preview-hidden-state">
                <strong>当前字段处于隐藏状态</strong>
                <span>关闭“是否隐藏”后，字段会重新出现在预览区域。</span>
              </div>
            </div>
          </div>
        </section>

        <aside class="preview-inspector">
          <div class="inspector-section">
            <div class="inspector-title">基础属性</div>
            <label class="inspector-field">
              <span>字段标题</span>
              <input v-model="widget.display.label" placeholder="请输入字段标题">
            </label>
            <label class="inspector-field">
              <span>说明文案</span>
              <input v-model="widget.titleDescription" placeholder="例如：支持选择开始和结束日期">
            </label>
            <div class="inspector-field">
              <span>宽度</span>
              <div class="inspector-widths">
                <button
                  v-for="option in widthOptions"
                  :key="option.key"
                  type="button"
                  :class="{ active: widthKey === option.key }"
                  @click="setWidth(option.key)"
                >{{ option.label }}</button>
              </div>
            </div>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">规则配置</div>
            <div class="rule-row">
              <div class="rule-label">是否隐藏</div>
              <button type="button" class="switch" :class="{ active: widget.display.hidden }" @click="toggleDisplayFlag('hidden')"></button>
            </div>
            <div class="rule-row">
              <div class="rule-label">是否只读</div>
              <button type="button" class="switch" :class="{ active: widget.display.readOnly }" @click="toggleDisplayFlag('readOnly')"></button>
            </div>
            <div class="rule-row">
              <div class="rule-label">是否必填</div>
              <button type="button" class="switch" :class="{ active: widget.display.required }" @click="toggleDisplayFlag('required')"></button>
            </div>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">组件专属配置</div>
            <template v-if="componentSettingSchema.length">
              <template v-for="field in componentSettingSchema">
                <label v-if="field.type === 'text'" :key="field.key" class="inspector-field">
                  <span>{{ field.label }}</span>
                  <input
                    :value="getComponentSettingValue(field)"
                    :placeholder="field.default || ''"
                    @input="updateComponentSetting(field, $event.target.value)"
                  >
                  <div v-if="field.help" class="inspector-help">{{ field.help }}</div>
                </label>
                <label v-else-if="field.type === 'number'" :key="field.key" class="inspector-field">
                  <span>{{ field.label }}</span>
                  <div class="inspector-inline-input">
                    <input
                      type="number"
                      :min="field.min"
                      :max="field.max"
                      :step="field.step || 1"
                      :value="getComponentSettingValue(field)"
                      @input="updateComponentSetting(field, $event.target.value)"
                    >
                    <span v-if="field.unit" class="unit">{{ field.unit }}</span>
                  </div>
                  <div v-if="field.help" class="inspector-help">{{ field.help }}</div>
                </label>
                <div v-else-if="field.type === 'boolean'" :key="field.key" class="rule-row">
                  <div class="rule-label">{{ field.label }}</div>
                  <button type="button" class="switch" :class="{ active: !!getComponentSettingValue(field) }" @click="updateComponentSetting(field, !getComponentSettingValue(field))"></button>
                </div>
                <div v-else-if="field.type === 'select'" :key="field.key" class="inspector-field">
                  <span>{{ field.label }}</span>
                  <div class="inspector-widths">
                    <button
                      v-for="option in field.options"
                      :key="option.value"
                      type="button"
                      :class="{ active: getComponentSettingValue(field) === option.value }"
                      @click="updateComponentSetting(field, option.value)"
                    >{{ option.label }}</button>
                  </div>
                </div>
              </template>
            </template>
            <div v-else class="inspector-help">当前没有识别到组件专属配置 schema，可以直接通过下面的 JSON 补充。</div>
            <details class="collapsible-panel">
              <summary>查看 JSON 配置</summary>
              <div class="collapsible-panel-body">
                <label class="inspector-field">
                  <span>customComponentConfig JSON</span>
                  <textarea v-model="customConfigText" spellcheck="false"></textarea>
                </label>
                <div class="inspector-help">这里用来补充组件专属配置。应用后会同步到 `widget.customComponentConfig`。</div>
                <div class="inspector-actions">
                  <button type="button" class="primary" @click="applyCustomConfig">应用配置</button>
                  <button type="button" class="secondary" @click="resetPreviewConfig">重置属性</button>
                </div>
                <div v-if="configError" class="inspector-error">{{ configError }}</div>
              </div>
            </details>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">调试数据</div>
            <label class="inspector-field">
              <span>预览值</span>
              <input v-model="formData.preview_field" placeholder="给组件一个预览值">
            </label>
            <div class="inspector-help">这里的值只用于当前预览沙箱，不会回写到组件配置本身。</div>
          </div>

          <div class="inspector-section">
            <details class="collapsible-panel">
              <summary>高级平台属性</summary>
              <div class="collapsible-panel-body">
                <div class="inspector-help">以下字段在平台结构里真实存在，但当前预览不会完整模拟公式、校验、隐藏触发和业务事件引擎行为，所以默认折叠。</div>
                <div class="rule-row">
                  <div class="rule-label">公式规则 <span class="hint">?</span></div>
                  <button type="button" class="switch" :class="{ active: widget.allow.formulaRule }" @click="toggleFormulaRule()"></button>
                </div>
                <div class="rule-row">
                  <div class="rule-label">仅新建可编辑</div>
                  <button type="button" class="switch" :class="{ active: widget.display.onlyCreateEdit }" @click="toggleDisplayFlag('onlyCreateEdit')"></button>
                </div>
                <div class="rule-row">
                  <div class="rule-label">唯一性校验</div>
                  <button type="button" class="switch" :class="{ active: widget.validator.uniqueCheck }" @click="toggleUniqueCheck()"></button>
                </div>
                <div class="rule-row">
                  <div class="rule-label">隐藏时提交 <span class="hint">?</span></div>
                  <button type="button" class="switch" :class="{ active: widget.special.saveWithHidden }" @click="toggleSpecialFlag('saveWithHidden')"></button>
                </div>
                <div class="rule-row">
                  <div class="rule-label">隐藏时触发 <span class="hint">?</span></div>
                  <button type="button" class="switch" :class="{ active: widget.special.hiddenTrigger }" @click="toggleSpecialFlag('hiddenTrigger')"></button>
                </div>
                <div class="business-events">
                  <div class="business-events-head">
                    <div class="rule-label">触发业务事件</div>
                    <button type="button" class="icon-button" @click="addBusinessEvent()">+</button>
                  </div>
                  <div v-if="!widget.special.triggerBusinessEvents.length" class="business-empty">暂未添加业务事件，点击右侧加号可追加一条预览用事件编码。</div>
                  <div v-for="(eventName, index) in widget.special.triggerBusinessEvents" :key="index" class="business-event-item">
                    <input v-model="widget.special.triggerBusinessEvents[index]" placeholder="例如：onValueChange">
                    <button type="button" class="icon-button" @click="removeBusinessEvent(index)">-</button>
                  </div>
                </div>
              </div>
            </details>
          </div>
        </aside>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.min.js"></script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"></script>

  <script>
    __MOCK_SDK_SCRIPT__
    setupFormEngine();
    __MOCK_FORM_WRAPPER__
  </script>

  <script src="__DIST_BASE_URL__/__OUTPUT_NAME__.umd.js"></script>

  <script>
    try {
      var lib = window['__OUTPUT_NAME__'] || window['__OUTPUT_NAME_UNDERSCORE__'];
      if (lib && lib.default && lib.default.install) {
        lib.default.install(Vue);
        console.log('[Preview] Component installed successfully');
      } else if (lib && lib.install) {
        lib.install(Vue);
        console.log('[Preview] Component installed (direct)');
      } else {
        console.warn('[Preview] No install method found, trying manual registration');
      }
    } catch (e) {
      console.error('[Preview] Install error:', e);
    }

    window.__PREVIEW_VUE_INSTANCE__ = new Vue({
      el: '#app',
      provide: function() {
        return {
          formEngine: {
            formDataControl: mockFormDataControl,
            engineContext: mockEngineContext,
            bsEventControl: mockBsEventControl
          },
          renderGlobal: {
            formDataControl: mockFormDataControl,
            engineContext: mockEngineContext,
            bsEventControl: mockBsEventControl
          },
          themeConfig: { theme: 'light' }
        };
      },
      data: function() {
        return {
          mode: 'edit',
          isMobile: __IS_MOBILE__,
          componentText: __COMPONENT_TEXT_JSON__,
          componentSettingSchema: __COMPONENT_SETTING_SCHEMA_JSON__,
          error: null,
          editComp: null,
          readComp: null,
          formData: { preview_field: '' },
          configError: '',
          widthOptions: __WIDTH_OPTIONS_JSON__,
          widthKey: 'full',
          widgetDefaults: __WIDGET_DEFAULTS_JSON__,
          customConfigText: __CUSTOM_CONFIG_TEXT__,
          widget: JSON.parse(JSON.stringify(__WIDGET_DEFAULTS_JSON__))
        };
      },
      computed: {
        currentWidthOption: function() {
          var matched = this.widthOptions.find(function(option) {
            return option.key === this.widthKey;
          }, this);
          return matched || this.widthOptions[this.widthOptions.length - 1];
        },
        fieldShellStyle: function() {
          return {
            width: this.currentWidthOption.styleWidth
          };
        }
      },
      watch: {
        'widget.display.label': function(value) {
          this.$set(this.widget, 'label', value || '');
        },
        'widget.display.required': function(value) {
          this.$set(this.widget, 'required', !!value);
        },
        'widget.display.readOnly': function(value) {
          this.$set(this.widget, 'readOnly', !!value);
        },
        'widget.display.hidden': function(value) {
          this.$set(this.widget, 'visible', !value);
        },
        'widget.customComponentConfig': {
          handler: function(value) {
            if (value && Object.prototype.hasOwnProperty.call(value, 'placeholder')) {
              this.$set(this.widget, 'placeholder', value.placeholder || '');
            }
            this.customConfigText = JSON.stringify(value || {}, null, 2);
          },
          deep: true
        }
      },
      methods: {
        normalizeWidget: function(source) {
          var widget = source || {};
          if (!widget.display || typeof widget.display !== 'object') {
            this.$set(widget, 'display', {});
          }
          if (!widget.allow || typeof widget.allow !== 'object') {
            this.$set(widget, 'allow', {});
          }
          if (!widget.validator || typeof widget.validator !== 'object') {
            this.$set(widget, 'validator', {});
          }
          if (!widget.special || typeof widget.special !== 'object') {
            this.$set(widget, 'special', {});
          }
          if (!widget.customComponentConfig || typeof widget.customComponentConfig !== 'object') {
            this.$set(widget, 'customComponentConfig', {});
          }
          if (!Array.isArray(widget.special.triggerBusinessEvents)) {
            this.$set(widget.special, 'triggerBusinessEvents', []);
          }
          this.$set(widget.display, 'label', widget.display.label || widget.label || this.componentText);
          this.$set(widget.display, 'width', Number(widget.display.width || 24));
          this.$set(widget.display, 'mobileWidth', Number(widget.display.mobileWidth || widget.display.width || 24));
          this.$set(widget.display, 'height', Number(widget.display.height || 1));
          this.$set(widget.display, 'hidden', !!widget.display.hidden);
          this.$set(widget.display, 'readOnly', !!widget.display.readOnly || !!widget.readOnly);
          this.$set(widget.display, 'required', !!widget.display.required || !!widget.required);
          this.$set(widget.display, 'onlyCreateEdit', !!widget.display.onlyCreateEdit);
          this.$set(widget.allow, 'formulaRule', !!widget.allow.formulaRule);
          this.$set(widget.validator, 'uniqueCheck', !!widget.validator.uniqueCheck);
          this.$set(widget.special, 'saveWithHidden', !!widget.special.saveWithHidden);
          this.$set(widget.special, 'hiddenTrigger', !!widget.special.hiddenTrigger);
          this.$set(widget, 'label', widget.display.label || '');
          this.$set(widget, 'required', !!widget.display.required);
          this.$set(widget, 'readOnly', !!widget.display.readOnly);
          this.$set(widget, 'visible', !widget.display.hidden);
          this.$set(widget, 'titleDescription', widget.titleDescription || '');
          this.$set(widget, 'placeholder', widget.placeholder || widget.customComponentConfig.placeholder || '');
          return widget;
        },
        ensureComponentConfigDefaults: function() {
          if (!this.widget.customComponentConfig || typeof this.widget.customComponentConfig !== 'object') {
            this.$set(this.widget, 'customComponentConfig', {});
          }
          this.componentSettingSchema.forEach(function(field) {
            if (
              field &&
              field.key &&
              this.widget.customComponentConfig[field.key] === undefined &&
              Object.prototype.hasOwnProperty.call(field, 'default')
            ) {
              this.$set(this.widget.customComponentConfig, field.key, field.default);
            }
          }, this);
        },
        getComponentSettingValue: function(field) {
          if (!field || !field.key) {
            return '';
          }
          var current = (this.widget.customComponentConfig || {})[field.key];
          if (current === undefined && Object.prototype.hasOwnProperty.call(field, 'default')) {
            return field.default;
          }
          return current;
        },
        updateComponentSetting: function(field, rawValue) {
          if (!field || !field.key) {
            return;
          }
          var nextValue = rawValue;
          if (field.type === 'number') {
            if (rawValue === '' || rawValue === null || rawValue === undefined) {
              nextValue = field.default || 0;
            } else {
              nextValue = Number(rawValue);
              if (Number.isNaN(nextValue)) {
                nextValue = field.default || 0;
              }
            }
          }
          this.$set(this.widget.customComponentConfig, field.key, nextValue);
        },
        resolveWidthKey: function(width) {
          var target = Number(width || 24);
          var matched = this.widthOptions.find(function(option) {
            return Number(option.displayWidth) === target;
          });
          return matched ? matched.key : 'full';
        },
        setWidth: function(key) {
          var matched = this.widthOptions.find(function(option) {
            return option.key === key;
          });
          if (!matched) {
            return;
          }
          this.widthKey = matched.key;
          this.$set(this.widget.display, 'width', matched.displayWidth);
          this.$set(this.widget.display, 'mobileWidth', matched.mobileWidth);
        },
        toggleDisplayFlag: function(key) {
          this.$set(this.widget.display, key, !this.widget.display[key]);
        },
        toggleFormulaRule: function() {
          this.$set(this.widget.allow, 'formulaRule', !this.widget.allow.formulaRule);
        },
        toggleUniqueCheck: function() {
          this.$set(this.widget.validator, 'uniqueCheck', !this.widget.validator.uniqueCheck);
        },
        toggleSpecialFlag: function(key) {
          this.$set(this.widget.special, key, !this.widget.special[key]);
        },
        addBusinessEvent: function() {
          this.widget.special.triggerBusinessEvents.push('');
        },
        removeBusinessEvent: function(index) {
          this.widget.special.triggerBusinessEvents.splice(index, 1);
        },
        applyCustomConfig: function() {
          try {
            var parsed = this.customConfigText ? JSON.parse(this.customConfigText) : {};
            this.$set(this.widget, 'customComponentConfig', parsed || {});
            this.ensureComponentConfigDefaults();
            if (Object.prototype.hasOwnProperty.call(parsed || {}, 'placeholder')) {
              this.$set(this.widget, 'placeholder', parsed.placeholder || '');
            }
            this.configError = '';
          } catch (error) {
            this.configError = 'JSON 解析失败：' + error.message;
          }
        },
        syncCustomConfigText: function() {
          this.customConfigText = JSON.stringify(this.widget.customComponentConfig || {}, null, 2);
        },
        resetPreviewConfig: function() {
          var clonedDefaults = JSON.parse(JSON.stringify(this.widgetDefaults));
          clonedDefaults.uuid = this.widget.uuid;
          this.widget = this.normalizeWidget(clonedDefaults);
          this.ensureComponentConfigDefaults();
          this.widthKey = this.resolveWidthKey(this.widget.display.width);
          this.formData = { preview_field: '' };
          this.configError = '';
          this.syncCustomConfigText();
        }
      },
      created: function() {
        var editName = '__EDIT_TAG__';
        var readName = '__READ_TAG__';
        var registry = Vue.options.components || {};
        this.widget.uuid = 'preview-' + Date.now();
        this.widgetDefaults = this.normalizeWidget(JSON.parse(JSON.stringify(this.widgetDefaults)));
        this.widget = this.normalizeWidget(this.widget);
        this.ensureComponentConfigDefaults();
        this.widthKey = this.resolveWidthKey(this.widget.display.width);
        mockFormDataControl.componentMap.set(this.widget.uuid, this.widget);
        mockFormDataControl.ctlComponentMap.set('preview_field', this.widget);
        mockFormDataControl.allTileFormItemList = [this.widget];
        var normalizeName = function(name) {
          return String(name || '').replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
        };
        var toPascalCase = function(name) {
          return String(name || '')
            .split(/[^a-zA-Z0-9]+/)
            .filter(Boolean)
            .map(function(part) {
              return part.charAt(0).toUpperCase() + part.slice(1);
            })
            .join('');
        };
        var resolveComponent = function(candidates) {
          for (var i = 0; i < candidates.length; i += 1) {
            if (registry[candidates[i]]) return registry[candidates[i]];
          }
          var normalizedCandidates = candidates.map(normalizeName);
          var keys = Object.keys(registry);
          for (var j = 0; j < keys.length; j += 1) {
            if (normalizedCandidates.indexOf(normalizeName(keys[j])) !== -1) {
              return registry[keys[j]];
            }
          }
          var suffixes = candidates.map(function(candidate) {
            var normalized = normalizeName(candidate);
            if (normalized.endsWith('edit')) return 'edit';
            if (normalized.endsWith('read')) return 'read';
            if (normalized.endsWith('ide')) return 'ide';
            if (normalized.endsWith('searchide')) return 'searchide';
            if (normalized.endsWith('search')) return 'search';
            if (normalized.endsWith('list')) return 'list';
            if (normalized.endsWith('print')) return 'print';
            if (normalized.endsWith('setting')) return 'setting';
            return '';
          }).filter(Boolean);
          var preferredSuffix = suffixes[0] || '';
          if (preferredSuffix) {
            var rankedKeys = keys
              .filter(function(key) {
                var normalizedKey = normalizeName(key);
                if (preferredSuffix === 'edit') return normalizedKey.endsWith('edit') && !normalizedKey.includes('search');
                if (preferredSuffix === 'read') return normalizedKey.endsWith('read');
                return normalizedKey.endsWith(preferredSuffix);
              })
              .sort(function(a, b) {
                return normalizeName(a).length - normalizeName(b).length;
              });
            if (rankedKeys.length > 0) {
              return registry[rankedKeys[0]];
            }
          }
          return null;
        };

        var editCandidates = [
          editName,
          editName.replace(/-/g, ''),
          toPascalCase(editName),
          toPascalCase('__OUTPUT_NAME__') + 'Edit'
        ];
        var readCandidates = [
          readName,
          readName.replace(/-/g, ''),
          toPascalCase(readName),
          toPascalCase('__OUTPUT_NAME__') + 'Read'
        ];

        this.editComp = resolveComponent(editCandidates);
        this.readComp = resolveComponent(readCandidates);

        if (!this.editComp) {
          var keys = Object.keys(registry);
          var customKeys = keys.filter(function(k) {
            return k.indexOf('form-component') !== -1 || k.indexOf('FormComponent') !== -1;
          });
          console.log('[Preview] Available components:', customKeys);
          if (customKeys.length > 0) {
            this.editComp = Vue.options.components[customKeys[0]];
            if (customKeys.length > 1) {
              this.readComp = Vue.options.components[customKeys[1]];
            }
          }
        }

        if (!this.editComp) {
          this.error = '未找到组件 "' + editName + '"，请检查组件是否正确注册。可用组件: ' + Object.keys(Vue.options.components).join(', ');
        }

        this.syncCustomConfigText();
      }
    });
  </script>
</body>
</html>"""

    return (
        template
        .replace("__OUTPUT_NAME_UNDERSCORE__", output_name.replace("-", "_"))
        .replace("__OUTPUT_NAME__", output_name)
        .replace("__DIST_BASE_URL__", dist_base_url)
        .replace("__PREVIEW_SHELL_CLASS__", preview_shell_class)
        .replace("__MOCK_SDK_SCRIPT__", _get_mock_sdk_script())
        .replace("__MOCK_FORM_WRAPPER__", _get_mock_form_wrapper())
        .replace("__COMPONENT_TEXT_JSON__", json.dumps(component_text, ensure_ascii=False))
        .replace("__COMPONENT_TEXT__", component_text)
        .replace("__WIDGET_DEFAULTS_JSON__", widget_defaults_json)
        .replace("__CUSTOM_CONFIG_TEXT__", json.dumps(widget_custom_config_json, ensure_ascii=False))
        .replace("__COMPONENT_SETTING_SCHEMA_JSON__", component_setting_schema_json)
        .replace("__WIDTH_OPTIONS_JSON__", width_options_json)
        .replace("__IS_MOBILE__", str(mobile).lower())
        .replace("__EDIT_TAG__", edit_tag)
        .replace("__READ_TAG__", read_tag)
    )


def _generate_form_component_preview_legacy(
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

    widget_defaults = {
        "label": component_text,
        "uuid": "preview-widget",
        "componentType": component_code,
        "customComponentConfig": {
            "placeholder": "请选择..." if mobile else "请输入...",
        },
        "visible": True,
        "readOnly": False,
        "required": False,
        "titleDescription": "",
        "placeholder": "请选择..." if mobile else "请输入...",
    }
    widget_defaults_json = json.dumps(widget_defaults, ensure_ascii=False)
    widget_custom_config_json = json.dumps(widget_defaults["customComponentConfig"], ensure_ascii=False, indent=2)
    preview_shell_class = "mobile" if mobile else "desktop"

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
      background:
        radial-gradient(circle at top, rgba(99, 102, 241, 0.12), transparent 36%),
        linear-gradient(180deg, #eef2f8 0%, #e7edf5 100%);
      padding: 18px;
      color: #1f2937;
    }}
    .preview-shell {{
      min-height: calc(100vh - 36px);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .preview-header {{
      background: #fff;
      border-radius: 18px;
      padding: 14px 16px;
      box-shadow: 0 14px 32px rgba(15, 23, 42, 0.08);
      border: 1px solid rgba(148, 163, 184, 0.22);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .preview-header-main {{
      min-width: 0;
    }}
    .preview-header h3 {{
      font-size: 15px;
      color: #111827;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .preview-header p {{
      font-size: 12px;
      color: #6b7280;
    }}
    .preview-tabs {{
      display: flex;
      gap: 8px;
    }}
    .preview-tabs button {{
      padding: 7px 14px;
      border: 1px solid rgba(148, 163, 184, 0.32);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      cursor: pointer;
      font-size: 12px;
      color: #475569;
      font-weight: 600;
      transition: all 0.2s;
    }}
    .preview-tabs button.active {{
      background: linear-gradient(135deg, #4f46e5, #6366f1);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 10px 20px rgba(79, 70, 229, 0.22);
    }}
    .preview-workbench {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 16px;
      align-items: start;
    }}
    .preview-stage,
    .preview-inspector {{
      background: rgba(255, 255, 255, 0.9);
      border-radius: 22px;
      border: 1px solid rgba(148, 163, 184, 0.24);
      box-shadow: 0 16px 36px rgba(15, 23, 42, 0.09);
      backdrop-filter: blur(12px);
    }}
    .preview-stage {{
      padding: 18px;
    }}
    .preview-stage-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .preview-stage-title {{
      font-size: 13px;
      font-weight: 700;
      color: #111827;
    }}
    .preview-stage-meta {{
      font-size: 12px;
      color: #64748b;
    }}
    .preview-canvas-shell {{
      border-radius: 18px;
      border: 1px dashed rgba(99, 102, 241, 0.28);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(248, 250, 252, 0.96)),
        radial-gradient(circle at top, rgba(99, 102, 241, 0.08), transparent 48%);
      padding: 18px;
      min-height: 360px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .preview-canvas {{
      width: min(100%, 760px);
      background: #fff;
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 20px 44px rgba(15, 23, 42, 0.10);
      border: 1px solid rgba(226, 232, 240, 0.85);
    }}
    .preview-canvas.mobile {{
      width: min(100%, 390px);
      min-height: 220px;
      padding: 18px;
      border-radius: 28px;
    }}
    .preview-hidden-state {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      align-items: center;
      justify-content: center;
      min-height: 220px;
      text-align: center;
      color: #64748b;
    }}
    .preview-hidden-state strong {{
      color: #111827;
      font-size: 15px;
    }}
    .preview-inspector {{
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      position: sticky;
      top: 18px;
    }}
    .inspector-section {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .inspector-title {{
      font-size: 12px;
      font-weight: 700;
      color: #4f46e5;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .inspector-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .inspector-field {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .inspector-field.full {{
      grid-column: 1 / -1;
    }}
    .inspector-field span {{
      font-size: 12px;
      color: #64748b;
      font-weight: 600;
    }}
    .inspector-field input,
    .inspector-field textarea {{
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.32);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 13px;
      color: #111827;
      background: rgba(255, 255, 255, 0.92);
      outline: none;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
      resize: vertical;
    }}
    .inspector-field input:focus,
    .inspector-field textarea:focus {{
      border-color: rgba(99, 102, 241, 0.55);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
    }}
    .inspector-field textarea {{
      min-height: 126px;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}
    .inspector-chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .inspector-chip {{
      border: 1px solid rgba(148, 163, 184, 0.28);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.78);
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 600;
      color: #475569;
      cursor: pointer;
      transition: all 0.2s ease;
    }}
    .inspector-chip.active {{
      color: #fff;
      border-color: transparent;
      background: linear-gradient(135deg, #4f46e5, #6366f1);
      box-shadow: 0 10px 20px rgba(79, 70, 229, 0.16);
    }}
    .inspector-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .inspector-actions button {{
      border: none;
      border-radius: 12px;
      padding: 9px 12px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.2s ease, opacity 0.2s ease;
    }}
    .inspector-actions button:hover {{
      transform: translateY(-1px);
    }}
    .inspector-actions .primary {{
      background: linear-gradient(135deg, #2563eb, #4f46e5);
      color: #fff;
    }}
    .inspector-actions .secondary {{
      background: rgba(148, 163, 184, 0.14);
      color: #334155;
    }}
    .inspector-error {{
      font-size: 12px;
      color: #dc2626;
      line-height: 1.6;
    }}
    .mock-form-item {{
      margin-bottom: 16px;
    }}
    .mock-form-label {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 14px;
      color: #334155;
      margin-bottom: 6px;
      font-weight: 600;
    }}
    .mock-form-required {{
      color: #ef4444;
      font-size: 13px;
    }}
    .mock-form-desc {{
      font-size: 12px;
      line-height: 1.6;
      color: #64748b;
      margin-bottom: 8px;
    }}
    .mock-form-body {{
      min-width: 0;
    }}
    .preview-error {{
      color: #f56c6c;
      padding: 16px;
      background: #fef0f0;
      border-radius: 12px;
      font-size: 13px;
    }}
    .preview-mode-label {{
      font-size: 12px;
      color: #64748b;
    }}
    .preview-json-hint {{
      font-size: 11px;
      color: #94a3b8;
      line-height: 1.6;
    }}
    @media (max-width: 980px) {{
      .preview-workbench {{
        grid-template-columns: 1fr;
      }}
      .preview-inspector {{
        position: static;
      }}
    }}
    @media (max-width: 640px) {{
      body {{
        padding: 12px;
      }}
      .preview-header {{
        padding: 12px;
        border-radius: 16px;
        align-items: flex-start;
        flex-direction: column;
      }}
      .preview-stage,
      .preview-inspector {{
        border-radius: 18px;
      }}
      .preview-stage,
      .preview-inspector {{
        padding: 14px;
      }}
      .preview-canvas {{
        padding: 16px;
      }}
      .inspector-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div id="app">
    <div class="preview-shell {preview_shell_class}">
      <div class="preview-header">
        <div class="preview-header-main">
          <h3>📦 {{{{ componentText }}}}</h3>
          <p>这里可以直接调试低代码配置属性，预览会即时反映组件的字段标题、必填、只读、隐藏和自定义配置。</p>
        </div>
        <div class="preview-tabs">
          <button :class="{{active: mode === 'edit'}}" @click="mode='edit'">编辑</button>
          <button :class="{{active: mode === 'read'}}" @click="mode='read'">只读</button>
        </div>
      </div>
      <div class="preview-workbench">
        <section class="preview-stage">
          <div class="preview-stage-head">
            <div>
              <div class="preview-stage-title">实时效果</div>
              <div class="preview-stage-meta">当前模式: {{{{ mode === 'edit' ? '编辑模式' : '只读模式' }}}}</div>
            </div>
            <div class="preview-mode-label">{{{{ widget.visible === false ? '当前字段已隐藏' : (widget.required ? '已开启必填' : '未开启必填') }}}}</div>
          </div>
          <div class="preview-canvas-shell">
            <div class="preview-canvas" :class="{{ mobile: isMobile }}">
              <div v-if="widget.visible !== false">
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
              <div v-else class="preview-hidden-state">
                <strong>当前字段处于隐藏状态</strong>
                <span>打开“显示字段”后，就会重新出现在预览区。</span>
              </div>
            </div>
          </div>
        </section>

        <aside class="preview-inspector">
          <div class="inspector-section">
            <div class="inspector-title">基础属性</div>
            <div class="inspector-grid">
              <label class="inspector-field">
                <span>字段标题</span>
                <input v-model="widget.label" placeholder="请输入字段标题">
              </label>
              <label class="inspector-field">
                <span>提示文案</span>
                <input v-model="widget.placeholder" placeholder="请输入 placeholder">
              </label>
              <label class="inspector-field full">
                <span>说明文案</span>
                <input v-model="widget.titleDescription" placeholder="例如：支持选择开始和结束日期">
              </label>
              <label class="inspector-field full">
                <span>示例值</span>
                <input v-model="formData.preview_field" placeholder="给组件一个预览值">
              </label>
            </div>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">开关属性</div>
            <div class="inspector-chip-row">
              <button type="button" class="inspector-chip" :class="{{ active: widget.required }}" @click="toggleFlag('required')">必填</button>
              <button type="button" class="inspector-chip" :class="{{ active: widget.readOnly }}" @click="toggleFlag('readOnly')">只读</button>
              <button type="button" class="inspector-chip" :class="{{ active: widget.visible !== false }}" @click="toggleVisible()">显示字段</button>
            </div>
          </div>

          <div class="inspector-section">
            <div class="inspector-title">自定义配置</div>
            <label class="inspector-field full">
              <span>customComponentConfig JSON</span>
              <textarea v-model="customConfigText" spellcheck="false"></textarea>
            </label>
            <div class="preview-json-hint">可以直接填写组件自己的配置项。点击“应用配置”后，会实时同步到 `widget.customComponentConfig`。</div>
            <div class="inspector-actions">
              <button type="button" class="primary" @click="applyCustomConfig">应用配置</button>
              <button type="button" class="secondary" @click="resetPreviewConfig">重置属性</button>
            </div>
            <div v-if="configError" class="inspector-error">{{{{ configError }}}}</div>
          </div>
        </aside>
      </div>
    </div>
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
    window.__PREVIEW_VUE_INSTANCE__ = new Vue({{
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
          isMobile: {str(mobile).lower()},
          componentText: '{component_text}',
          error: null,
          editComp: null,
          readComp: null,
          formData: {{ preview_field: '' }},
          configError: '',
          widgetDefaults: {widget_defaults_json},
          customConfigText: {json.dumps(widget_custom_config_json, ensure_ascii=False)},
          widget: Object.assign({{}}, {widget_defaults_json})
        }};
      }},
      watch: {{
        'widget.placeholder': function(value) {{
          if (!this.widget.customComponentConfig || typeof this.widget.customComponentConfig !== 'object') {{
            this.$set(this.widget, 'customComponentConfig', {{}});
          }}
          this.$set(this.widget.customComponentConfig, 'placeholder', value || '');
        }}
      }},
      methods: {{
        toggleFlag: function(key) {{
          this.$set(this.widget, key, !this.widget[key]);
        }},
        toggleVisible: function() {{
          this.$set(this.widget, 'visible', this.widget.visible === false);
        }},
        applyCustomConfig: function() {{
          try {{
            var parsed = this.customConfigText ? JSON.parse(this.customConfigText) : {{}};
            this.$set(this.widget, 'customComponentConfig', parsed || {{}});
            if (Object.prototype.hasOwnProperty.call(parsed || {{}}, 'placeholder')) {{
              this.$set(this.widget, 'placeholder', parsed.placeholder || '');
            }}
            this.configError = '';
          }} catch (error) {{
            this.configError = 'JSON 解析失败：' + error.message;
          }}
        }},
        syncCustomConfigText: function() {{
          this.customConfigText = JSON.stringify(this.widget.customComponentConfig || {{}}, null, 2);
        }},
        resetPreviewConfig: function() {{
          var clonedDefaults = JSON.parse(JSON.stringify(this.widgetDefaults));
          clonedDefaults.uuid = this.widget.uuid;
          this.widget = clonedDefaults;
          this.formData = {{ preview_field: '' }};
          this.configError = '';
          this.syncCustomConfigText();
        }}
      }},
      created: function() {{
        // Try to find registered components
        var editName = '{edit_tag}';
        var readName = '{read_tag}';
        var registry = Vue.options.components || {{}};
        this.widget.uuid = 'preview-' + Date.now();
        mockFormDataControl.componentMap.set(this.widget.uuid, this.widget);
        mockFormDataControl.ctlComponentMap.set('preview_field', this.widget);
        mockFormDataControl.allTileFormItemList = [this.widget];
        var normalizeName = function(name) {{
          return String(name || '').replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
        }};
        var toPascalCase = function(name) {{
          return String(name || '')
            .split(/[^a-zA-Z0-9]+/)
            .filter(Boolean)
            .map(function(part) {{
              return part.charAt(0).toUpperCase() + part.slice(1);
            }})
            .join('');
        }};
        var resolveComponent = function(candidates) {{
          for (var i = 0; i < candidates.length; i += 1) {{
            if (registry[candidates[i]]) return registry[candidates[i]];
          }}
          var normalizedCandidates = candidates.map(normalizeName);
          var keys = Object.keys(registry);
          for (var j = 0; j < keys.length; j += 1) {{
            if (normalizedCandidates.indexOf(normalizeName(keys[j])) !== -1) {{
              return registry[keys[j]];
            }}
          }}
          var suffixes = candidates.map(function(candidate) {{
            var normalized = normalizeName(candidate);
            if (normalized.endsWith('edit')) return 'edit';
            if (normalized.endsWith('read')) return 'read';
            if (normalized.endsWith('ide')) return 'ide';
            if (normalized.endsWith('searchide')) return 'searchide';
            if (normalized.endsWith('search')) return 'search';
            if (normalized.endsWith('list')) return 'list';
            if (normalized.endsWith('print')) return 'print';
            if (normalized.endsWith('setting')) return 'setting';
            return '';
          }}).filter(Boolean);
          var preferredSuffix = suffixes[0] || '';
          if (preferredSuffix) {{
            var rankedKeys = keys
              .filter(function(key) {{
                var normalizedKey = normalizeName(key);
                if (preferredSuffix === 'edit') return normalizedKey.endsWith('edit') && !normalizedKey.includes('search');
                if (preferredSuffix === 'read') return normalizedKey.endsWith('read');
                return normalizedKey.endsWith(preferredSuffix);
              }})
              .sort(function(a, b) {{
                return normalizeName(a).length - normalizeName(b).length;
              }});
            if (rankedKeys.length > 0) {{
              return registry[rankedKeys[0]];
            }}
          }}
          return null;
        }};

        var editCandidates = [
          editName,
          editName.replace(/-/g, ''),
          toPascalCase(editName),
          toPascalCase('{output_name}') + 'Edit'
        ];
        var readCandidates = [
          readName,
          readName.replace(/-/g, ''),
          toPascalCase(readName),
          toPascalCase('{output_name}') + 'Read'
        ];

        this.editComp = resolveComponent(editCandidates);
        this.readComp = resolveComponent(readCandidates);

        if (!this.editComp) {{
          // Try to find any component that was registered
          var keys = Object.keys(registry);
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

        this.syncCustomConfigText();
      }}
    }});
  </script>
</body>
</html>"""


def _generate_page_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
    mobile: bool = False,
) -> str:
    """生成页面组件预览 HTML"""
    body_style = (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
        "background: linear-gradient(180deg, #f4f7fb 0%, #eef2f7 100%); "
        "padding: 18px;"
    )
    app_style = (
        "width: 100%; height: calc(100vh - 36px);"
    )
    page_frame = ""
    if mobile:
        body_style = (
            "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; "
            "background: linear-gradient(180deg, #eef2f9 0%, #e7ecf4 100%); "
            "padding: 18px;"
        )
        app_style = (
            "width: min(100%, 390px); height: calc(100vh - 36px); margin: 0 auto; "
            "background: #fff; border-radius: 28px; overflow: hidden; "
            "box-shadow: 0 18px 48px rgba(15, 23, 42, 0.16); border: 1px solid rgba(148, 163, 184, 0.22);"
    )
        page_frame = """
    .preview-device-bar {
      width: 120px;
      height: 6px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.12);
      margin: 12px auto 8px;
    }
"""
    device_bar_html = '<div class="preview-device-bar"></div>' if mobile else ""

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
    body {{ {body_style} }}
    #app {{ {app_style} }}
    .preview-error {{ color: #f56c6c; padding: 24px; text-align: center; }}
    {page_frame}
  </style>
</head>
<body>
  {device_bar_html}
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
    setupPreviewRequest();
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


def _generate_layout_preview(
    apaas_config: dict,
    dist_base_url: str,
    output_name: str,
) -> str:
    """页面布局预览"""
    layout_items = apaas_config.get("layout") or []
    layout_name = output_name
    if isinstance(layout_items, list):
        for item in layout_items:
            if isinstance(item, dict) and item.get("name"):
                layout_name = item["name"]
                break

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>布局预览 - {output_name}</title>
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <link rel="stylesheet" href="{dist_base_url}/{output_name}.css" onerror="">
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: 100%; height: 100%; overflow: hidden; background: #0f1224; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }}
    body {{ padding: 18px; }}
    .layout-preview-shell {{
      width: 100%;
      height: 100%;
      border-radius: 24px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.08);
      background: linear-gradient(180deg, rgba(18,21,41,0.98) 0%, rgba(24,28,53,0.98) 100%);
      box-shadow: 0 24px 56px rgba(5,8,20,0.35);
    }}
    .layout-preview-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 18px;
      color: #f3f5ff;
      background: rgba(255,255,255,0.04);
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .layout-preview-title {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .layout-preview-title strong {{ font-size: 16px; }}
    .layout-preview-title span {{ font-size: 12px; color: rgba(243,245,255,0.68); }}
    #app {{
      height: calc(100% - 62px);
      padding: 16px;
      background: linear-gradient(180deg, #f5f7fb 0%, #eef2f8 100%);
    }}
    .layout-runtime {{
      height: 100%;
      border-radius: 20px;
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 20px 40px rgba(17, 24, 39, 0.12);
    }}
    .x-app-layout-mock {{
      display: flex;
      flex-direction: column;
      width: 100%;
      height: 100%;
      background: #f6f8fc;
    }}
    .x-app-layout-announcement {{
      flex: 0 0 auto;
      border-bottom: 1px solid #e7ebf3;
      background: linear-gradient(90deg, #fff7e6 0%, #fff2d9 100%);
    }}
    .x-app-layout-header {{
      flex: 0 0 64px;
      padding: 0 20px;
      border-bottom: 1px solid #e7ebf3;
      background: #ffffff;
    }}
    .x-app-layout-main {{
      flex: 1;
      min-height: 0;
      display: flex;
    }}
    .x-app-layout-menu {{
      width: 220px;
      min-width: 220px;
      padding: 16px;
      border-right: 1px solid #e7ebf3;
      background: linear-gradient(180deg, #f8faff 0%, #f3f6fd 100%);
      overflow: auto;
    }}
    .x-app-layout-content {{
      flex: 1;
      min-width: 0;
      min-height: 0;
      overflow: auto;
      background: #ffffff;
    }}
    .x-app-header-mock {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 100%;
    }}
    .x-app-header-brand strong {{
      display: block;
      color: #1f2347;
      font-size: 18px;
      line-height: 1.2;
    }}
    .x-app-header-brand span {{
      display: block;
      margin-top: 4px;
      color: #7b819f;
      font-size: 12px;
    }}
    .x-app-header-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .x-app-header-chip {{
      padding: 6px 10px;
      border-radius: 999px;
      background: #eef2ff;
      color: #4765ff;
      font-size: 12px;
      font-weight: 600;
    }}
    .x-app-menu-mock {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .x-app-menu-item {{
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(255,255,255,0.82);
      color: #394062;
      font-size: 14px;
      font-weight: 500;
      box-shadow: inset 0 0 0 1px rgba(71, 101, 255, 0.06);
    }}
    .preview-error {{
      margin: 24px;
      padding: 16px 18px;
      border-radius: 12px;
      background: #fff3f0;
      color: #d14343;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <div class="layout-preview-shell">
    <div class="layout-preview-toolbar">
      <div class="layout-preview-title">
        <strong>布局预览</strong>
        <span>{layout_name}</span>
      </div>
      <span>Mock aPaaS Runtime</span>
    </div>
    <div id="app"></div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/vue@2.7.14/dist/vue.min.js"></script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"></script>

  <script>
    {_get_mock_sdk_script()}
    setupPreviewRequest();

    Vue.prototype.$route = {{ name: 'workbench-page' }};

    Vue.component('x-app-layout', {{
      props: {{
        layoutEngine: {{ type: Object, default: function() {{ return {{}}; }} }},
        isCollapse: {{ type: Boolean, default: false }},
      }},
      template: `
        <div class="x-app-layout-mock">
          <div class="x-app-layout-announcement"><slot name="announcement"></slot></div>
          <div class="x-app-layout-header"><slot name="header"></slot></div>
          <div class="x-app-layout-main">
            <div class="x-app-layout-menu"><slot name="menu"></slot></div>
            <div class="x-app-layout-content"><slot name="appPage"></slot></div>
          </div>
        </div>
      `,
    }});

    Vue.component('x-app-header', {{
      props: {{
        appInfo: {{ type: Object, default: function() {{ return {{}}; }} }},
      }},
      template: `
        <div class="x-app-header-mock">
          <div class="x-app-header-brand">
            <strong>{{{{ appInfo.appName || '自定义应用布局' }}}}</strong>
            <span>布局预览会尽量模拟平台顶部导航和菜单区</span>
          </div>
          <div class="x-app-header-actions">
            <span class="x-app-header-chip">工作台</span>
            <span class="x-app-header-chip">账号中心</span>
          </div>
        </div>
      `,
    }});

    Vue.component('x-app-menu', {{
      props: {{
        menuConfig: {{ type: Object, default: function() {{ return {{}}; }} }},
        showMenu: {{ type: Boolean, default: true }},
      }},
      computed: {{
        menuItems: function() {{
          var list = (this.menuConfig && this.menuConfig.menuTreeData) || [];
          if (Array.isArray(list) && list.length) return list;
          return [
            {{ id: 'home', name: '首页' }},
            {{ id: 'todo', name: '待办中心' }},
            {{ id: 'analysis', name: '经营分析' }},
          ];
        }},
      }},
      template: `
        <div v-if="showMenu" class="x-app-menu-mock">
          <div v-for="item in menuItems" :key="item.id || item.name" class="x-app-menu-item">
            {{{{ item.name || item.title || item.label }}}}
          </div>
        </div>
      `,
    }});

    Vue.LayoutEngine = {{
      currentLayoutId: '{layout_name}',
      _instances: {{}},
      getInstance: function(id) {{
        if (!this._instances[id]) {{
          var self = this;
          this._instances[id] = {{
            id: id,
            layoutDataControl: {{
              appInfo: {{ appName: 'AI Builder 布局演示' }},
              menuConfig: {{
                menuTreeData: [
                  {{ id: 'dashboard', name: '仪表盘' }},
                  {{ id: 'project', name: '项目管理' }},
                  {{ id: 'member', name: '成员中心' }},
                ],
              }},
            }},
            registerLayoutComponent: function(comp) {{
              this.layoutComponent = comp;
              self._instances[id] = this;
            }},
          }};
        }}
        return this._instances[id];
      }},
    }};
  </script>

  <script src="{dist_base_url}/{output_name}.umd.js"></script>

  <script>
    var engine = Vue.LayoutEngine.getInstance(Vue.LayoutEngine.currentLayoutId);
    try {{
      var lib = window['{output_name}'] || window['{output_name.replace("-", "_")}'];
      if (lib && lib.default && lib.default.install) {{
        lib.default.install(Vue);
      }} else if (lib && lib.install) {{
        lib.install(Vue);
      }}
    }} catch (e) {{
      console.error('[Preview] Layout install error:', e);
    }}

    var layoutComp = engine.layoutComponent;
    if (!layoutComp) {{
      var keys = Object.keys(Vue.options.components || {{}});
      var customKeys = keys.filter(function(key) {{
        return !['x-app-layout', 'x-app-header', 'x-app-menu'].includes(key) && key.indexOf('El') !== 0;
      }});
      if (customKeys.length > 0) {{
        layoutComp = Vue.options.components[customKeys[customKeys.length - 1]];
      }}
    }}

    new Vue({{
      el: '#app',
      data: function() {{
        return {{
          layoutComp: layoutComp,
          error: layoutComp ? null : '未找到布局组件，请检查 src/index.js 中是否调用了 LayoutEngine.registerLayoutComponent。',
        }};
      }},
      render: function(h) {{
        if (this.layoutComp) {{
          return h('div', {{ class: 'layout-runtime' }}, [
            h(this.layoutComp, {{
              props: {{
                layoutEngine: engine,
                pkgVersion: 'Preview 1.0.0',
              }},
            }}),
          ]);
        }}
        return h('div', {{ class: 'preview-error' }}, this.error);
      }},
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
