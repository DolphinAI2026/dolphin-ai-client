"""
项目模板 - 为各种开发场景提供初始项目骨架
"""

import json
from typing import Dict, List
from app.coding.scenes import SceneType


def _inject_copy_asset_placeholders(files: Dict[str, str]) -> Dict[str, str]:
    apaas_content = files.get("src/apaas.json")
    if not apaas_content:
        return files

    try:
        apaas_config = json.loads(apaas_content)
    except json.JSONDecodeError:
        return files

    patched_files = dict(files)
    placeholder_content = (
        "Placeholder asset file for df-apaas-cli copyAssets.\n"
        "Delete this file after you add real assets.\n"
    )

    for copy_asset in apaas_config.get("copyAssets") or []:
        if not isinstance(copy_asset, str):
            continue

        asset_root = copy_asset.strip().strip("/")
        if not asset_root:
            continue

        has_visible_children = False
        asset_prefix = f"{asset_root}/"
        for path in patched_files:
            if not path.startswith(asset_prefix):
                continue
            relative_path = path[len(asset_prefix):]
            if not relative_path:
                continue
            first_segment = relative_path.split("/", 1)[0]
            if first_segment and not first_segment.startswith("."):
                has_visible_children = True
                break

        if has_visible_children:
            continue

        patched_files[f"{asset_root}/asset-placeholder.txt"] = placeholder_content

    return patched_files


def get_project_template(scene_type: SceneType, module_name: str) -> Dict[str, str]:
    """获取项目模板，返回 {文件路径: 文件内容} 字典"""
    generators = {
        SceneType.WEB_COMPONENT: _web_component_template,
        SceneType.WEB_PAGE: _web_page_template,
        SceneType.WEB_LIST_VIEW: _web_list_view_template,
        SceneType.MOBILE_PAGE: _mobile_page_template,
        SceneType.MOBILE_COMPONENT: _mobile_component_template,
        SceneType.WEB_LAYOUT: _web_layout_template,
        SceneType.WEB_PLUGIN: _web_plugin_template,
        SceneType.BACKEND_API: _backend_api_template,
        SceneType.SCRIPT_JS: _script_js_template,
        SceneType.SCRIPT_PYTHON: _script_python_template,
        SceneType.SCRIPT_GROOVY: _script_groovy_template,
        SceneType.BUSINESS_DIALOG: _business_dialog_template,
        SceneType.UI_STYLE: _ui_style_template,
        SceneType.LIST_CUSTOM_MODULE: _list_custom_module_template,
        SceneType.WEB_LOGIN: _web_login_template,
    }
    generator = generators.get(scene_type)
    if generator:
        return _inject_copy_asset_placeholders(generator(module_name))
    return {}


def _web_component_template(name: str) -> Dict[str, str]:
    """Web端自开发组件模板 - 完整 FORM_COMPONENT 架构（7场景）"""
    code = "FORM_CUSTOM_COMPONENT_" + name.upper().replace("-", "_")
    parts = name.split("-")
    pascal = "".join(w.capitalize() for w in parts)
    prefix = f"FormComponent{pascal}"
    full_kebab = f"form-component-{name}"

    return {
        f"src/apaas.json": json.dumps({
            "entry": "index.js",
            "templateType": "FORM_COMPONENT",
            "customWidgetList": [{"code": code, "text": name, "description": name}],
            "copyAssets": [f"public/form-component/{full_kebab}"],
            "router": {},
            "outputName": full_kebab
        }, indent=2, ensure_ascii=False),

        f"src/index.js": f"""\
import './form-component-local/index.js'
import {{ customFormEditorList, customFormWidgetList }} from './form-component'
import {{ widgetConfigList, editorConfigList }} from './form-component-config'
import {{ AbilityFieldMap, AbilityFieldConvert }} from './form-ability'

const install = function(Vue) {{
  customFormEditorList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  customFormWidgetList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  editorConfigList.forEach((ec) => {{ Vue.FormEngine.WidgetControl.registerEditorConfig(ec) }})
  widgetConfigList.forEach((wc) => {{ Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig({{ widgetConfig: wc }}) }})
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterComponentTypeConfig(AbilityFieldMap)
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterFieldValueConvert(AbilityFieldConvert)
}}
export default {{ install }}
""",

        f"src/form-component-config/form-widget/{full_kebab}.widget.config.js": f"""\
const config = {{
  version: 2.0,
  code: '{code}',
  desc: {{ iconType: 'DEFAULT', icon: '', text: '{name}', description: '{name}' }},
  instance: {{ uuid: '$itemUuid', inTable: false }},
  component: {{
    ide: '{prefix}Ide', edit: '{prefix}Edit', read: '{prefix}Read',
    list: '{prefix}List', association: '{prefix}List', lov: '{prefix}List',
    print: '{prefix}Print', search: '{prefix}Search', searchIde: '{prefix}SearchIde'
  }},
  widget: {{
    display: {{ label: '{name}', width: 6, mobileWidth: 12, height: 1, hidden: false, readOnly: false, required: false }},
    allow: {{ useInTableColumn: true }},
    default: {{ customDefaultKey: 'defaultValue', value: '' }},
    validator: {{ uniqueCheck: false }},
    validatorList: [{{ validatorConfig: [], validatorMessage: '' }}],
    special: {{ frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false }},
    customComponentConfig: {{}},
    editor: {{ config: ['INFO','LABEL','FIELD_CODE','TITLE_DESCRIPTION','WIDTH','{code}_SETTING','FORMULA_RULE','HIDDEN','READONLY','REQUIRED','EDITONNEW','UNIQUE','HIDDEN_SAVE','HIDDEN_TRIGGER','TRIGGER_BUSINESS_EVENTS'], excludeInTable: ['WIDTH'] }}
  }},
  componentModelField: ['STRING'],
  methods: {{}}, formatValueSchema: {{}}
}}
export default config
""",

        f"src/form-component/form-widget/edit/{full_kebab}-edit.vue": f"""\
<template>
  <div class="form-widget {full_kebab}-edit">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :validatorRules="validatorRules" :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings">
      <el-input v-model="editValue" placeholder="请输入" />
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{
  name: '{prefix}Edit', mixins: [FormWidgetMixin],
  computed: {{ editValue: {{ get() {{ return this.formValue || '' }}, set(v) {{ this.formValue = v }} }} }}
}}
</script>
""",

        f"src/form-component/form-editor/{full_kebab}-setting.vue": f"""\
<template>
  <div class="form-config-item {full_kebab}-setting">
    <div class="setting-panel">
      <el-divider>组件配置</el-divider>
      <!-- 直接放置 el-form-item，平台外层已提供 el-form -->
      <!-- 在此添加配置项，统一使用 v-model="customComponentConfig.xxx" -->
    </div>
  </div>
</template>
<script>
export default {{
  name: '{prefix}Setting',
  props: {{
    componentConfig: {{ default: null }},
    formEngine: {{ default: null }},
    widget: {{ default: null }},
    editConfig: {{ default: null }},
    configProperty: {{ default: null }},
    formItemList: {{ default: null }},
    formRule: {{ default: null }},
    globalData: {{ default: null }},
    widgetConfig: {{ default: null }},
    disabled: {{ default: false }}
  }},
  inject: {{
    renderGlobal: {{ default: null }},
    getPreviewLanguage: {{ default: null }},
    getI18nShowStatus: {{ default: null }},
    filterTableFromNodeFields: {{ default: null }}
  }},
  computed: {{
    customComponentConfig() {{
      const target = this.componentConfig || this.widget || null
      return (target && target.customComponentConfig) || {{}}
    }},
    engine() {{
      if (this.formEngine) return this.formEngine
      if (this.renderGlobal) return this.renderGlobal
      return null
    }},
    subTableList() {{
      if (!this.engine || !this.engine.formDataControl) return []
      return (this.engine.formDataControl.allTileFormItemList || [])
        .filter(item => item.componentType === 'FORM_WIDGET_SON_TABLE')
    }}
  }},
  created() {{
    const target = this.componentConfig || this.widget || null
    if (target && !target.customComponentConfig) {{
      this.$set(target, 'customComponentConfig', {{}})
    }}
  }}
}}
</script>
<style lang="scss">
.{full_kebab}-setting {{
  .setting-panel {{
    .el-divider {{ margin: 0 0 16px 0; }}
  }}
}}
</style>
""",

        f"src/form-component/form-widget/read/{full_kebab}-read.vue": f"""\
<template>
  <div class="form-widget {full_kebab}-read">
    <x-proxy-form-item :isInTable="widget.isInTable" :label="widget.label" :webFormSettings="webFormSettings">
      <span>{{{{ formValue || '-' }}}}</span>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{ name: '{prefix}Read', mixins: [FormWidgetMixin] }}
</script>
""",
    }


def _web_page_template(name: str) -> Dict[str, str]:
    """Web端自开发页面模板"""
    module = f"apaas-custom-{name}"
    camel = "".join(w.capitalize() for w in name.split("-"))

    return {
        f"src/custom/{module}/apaas.json": f"""\
{{
  "entry": "index.js",
  "copyAssets": ["public/custom/{module}"],
  "router": {{
    "{module}": {{
      "name": "{module}",
      "path": "{module}",
      "meta": {{ "title": "自开发-{name}" }}
    }}
  }},
  "outputName": "{module}"
}}""",

        f"src/custom/{module}/index.js": f"""\
import ApaasCustom{camel} from './page.vue'

const install = function(Vue, opts) {{
  Vue.component('{module}', ApaasCustom{camel})
}}

export default {{ install }}
""",

        f"src/custom/{module}/page.vue": f"""\
<template>
  <div class="{module}">
    <h2>自开发页面 - {name}</h2>
    <!-- 在此添加页面内容 -->
  </div>
</template>

<script>
export default {{
  name: 'ApaasCustom{camel}',
  data() {{
    return {{}}
  }},
  created() {{
    // 初始化逻辑
  }},
  methods: {{
    // 网络请求示例
    async fetchData() {{
      this.$request({{
        url: '/custom/api/data',
        method: 'get',
        disableSuccessMsg: true
      }}).asyncThen((resp) => {{
        console.log(resp)
      }})
    }}
  }}
}}
</script>

<style lang="scss" scoped>
.{module} {{
  padding: 20px;
}}
</style>
""",
    }


def _web_list_view_template(name: str) -> Dict[str, str]:
    """Web端自开发列表视图模板"""
    module = f"apaas-custom-{name}"

    return {
        "src/apaas.json": f"""\
{{
  "entry": "index.js",
  "templateType": "LIST_VIEW",
  "router": {{}},
  "customWidgetList": [],
  "list": {{
    "{module}": {{
      "renderLogic": "FORM_LIST_VIEW",
      "desc": "自定义列表-{name}",
      "status": "ENABLE"
    }}
  }},
  "copyAssets": ["public/form-view/form-view-{name}"],
  "outputName": "form-view-{name}"
}}""",

        "src/index.js": f"""\
import './form-view-local/index.js'
import CustomListView from './form-view/{module}.vue'

const install = function(Vue) {{
  Vue.component('{module}', CustomListView)
}}

export default {{ install }}
""",

        f"src/form-view/{module}.vue": f"""\
<template>
  <div class="custom-list-view">
    <x-list-view :listEngine="listEngine">
      <template #listTable>
        <x-list-table
          ref="xListTableView"
          :treeViewListEngine="listEngine"
          :treeViewInAssoc="true"
          :pageViewComponents="listEngine.listDataControl.tablePanelComponents"
        ></x-list-table>
      </template>
    </x-list-view>
  </div>
</template>

<script>
export default {{
  name: 'CustomListView',
  props: {{
    listEngine: {{
      type: Object
    }}
  }},
  mounted() {{
    if (this.$refs.xListTableView) {{
      this.$refs.xListTableView.handlerRowClick = function () {{
        return undefined
      }}
    }}
  }},
}}
</script>

<style lang="scss">
.custom-list-view {{
  height: 100%;
}}
</style>
""",

        "src/form-view-local/index.js": """\
import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
""",

        "src/form-view-local/zh-CN/index.js": """\
export default {
  formView: {
    title: '自定义列表视图'
  }
}
""",

        "src/form-view-local/en-US/index.js": """\
export default {
  formView: {
    title: 'Custom List View'
  }
}
""",
    }


def _mobile_page_template(name: str) -> Dict[str, str]:
    """移动端自开发页面模板"""
    module = f"apaas-custom-{name}"
    camel = "".join(w.capitalize() for w in name.split("-"))

    return {
        f"src/custom/{module}/apaas.json": f"""\
{{
  "entry": "index.js",
  "copyAssets": ["public/custom/{module}"],
  "router": {{
    "{module}": {{
      "name": "{module}",
      "path": "{module}",
      "meta": {{ "title": "移动端-{name}" }}
    }}
  }},
  "outputName": "{module}"
}}""",

        f"src/custom/{module}/index.js": f"""\
import ApaasCustom{camel} from './page.vue'

const install = function(Vue, opts) {{
  Vue.component('{module}', ApaasCustom{camel})
}}

export default {{ install }}
""",

        f"src/custom/{module}/page.vue": f"""\
<template>
  <div class="{module}">
    <h2>{name}</h2>
  </div>
</template>

<script>
export default {{
  name: 'ApaasCustom{camel}',
  data() {{
    return {{}}
  }}
}}
</script>

<style lang="scss" scoped>
.{module} {{
  padding: 16px;
}}
</style>
""",
    }


def _mobile_component_template(name: str) -> Dict[str, str]:
    """移动端自开发组件模板 - 简化版（仅 ide/edit/read 三态）"""
    code = "FORM_CUSTOM_COMPONENT_" + name.upper().replace("-", "_")
    parts = name.split("-")
    pascal = "".join(w.capitalize() for w in parts)
    prefix = f"FormComponent{pascal}"
    full_kebab = f"form-component-{name}-mobile"

    return {
        f"src/apaas.json": json.dumps({
            "entry": "index.js",
            "templateType": "FORM_COMPONENT",
            "customWidgetList": [{"code": code, "text": name, "description": f"{name} (移动端)"}],
            "copyAssets": [f"public/form-component/{full_kebab}"],
            "router": {},
            "outputName": full_kebab
        }, indent=2, ensure_ascii=False),

        f"src/index.js": f"""\
import {{ customFormEditorList, customFormWidgetList }} from './component'
import {{ widgetConfigList, editorConfigList }} from './config'

const install = function(Vue) {{
  customFormWidgetList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  customFormEditorList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  widgetConfigList.forEach((wc) => {{
    Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig({{ widgetConfig: wc }})
  }})
  editorConfigList.forEach((ec) => {{
    Vue.FormEngine && Vue.FormEngine.registerCustomEditorConfig(ec)
  }})
}}
export default {{ install }}
""",

        f"src/config/widgetConfigList.js": f"""\
const widgetConfigList = [{{
  version: 2.0,
  code: '{code}',
  desc: {{ iconType: 'DEFAULT', icon: '', text: '{name}', description: '{name} (移动端)' }},
  instance: {{ uuid: '$itemUuid', inTable: false }},
  component: {{
    ide: '{prefix}Edit',
    edit: '{prefix}Edit',
    read: '{prefix}Read'
  }},
  widget: {{
    display: {{ label: '{name}', width: 12, mobileWidth: 12, height: 1, hidden: false, readOnly: false, required: false }},
    allow: {{ useInTableColumn: true }},
    default: {{ customDefaultKey: 'defaultValue', value: '' }},
    validator: {{ uniqueCheck: false }},
    special: {{ frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false }},
    customComponentConfig: {{}},
    editor: {{
      config: ['INFO', 'LABEL', 'WIDTH', '{code}_SETTING', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW']
    }}
  }},
  componentModelField: ['STRING'],
  client: {{
    mobile: {{
      widget: {{
        editor: {{
          config: ['INFO', 'LABEL', 'HIDDEN', 'READONLY', 'REQUIRED']
        }}
      }},
      component: {{
        ide: '{prefix}Edit',
        edit: '{prefix}Edit',
        read: '{prefix}Read'
      }}
    }}
  }},
  methods: {{}},
  formatValueSchema: {{}}
}}]
export default widgetConfigList
""",

        f"src/config/editorConfigList.js": f"""\
const editorConfigList = [{{
  code: '{code}_SETTING',
  editorConfigType: '{code}_SETTING',
  componentName: '{prefix}Setting',
  configProperty: 'customComponentConfig'
}}]
export default editorConfigList
""",

        f"src/config/index.js": f"""\
import widgetConfigList from './widgetConfigList'
import editorConfigList from './editorConfigList'
export {{ widgetConfigList, editorConfigList }}
""",

        f"src/component/form-widget/{full_kebab}-edit.vue": f"""\
<template>
  <div class="form-widget {full_kebab}-edit">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :validatorRules="validatorRules" :validateKey="validateKey" :validateInfo="validateInfo">
      <input v-model="editValue" class="mobile-input" placeholder="请输入" />
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{
  name: '{prefix}Edit', mixins: [FormWidgetMixin],
  computed: {{ editValue: {{ get() {{ return this.formValue || '' }}, set(v) {{ this.formValue = v }} }} }}
}}
</script>
<style scoped>
.mobile-input {{ width: 100%; padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; }}
</style>
""",

        f"src/component/form-widget/{full_kebab}-read.vue": f"""\
<template>
  <div class="form-widget {full_kebab}-read">
    <x-proxy-form-item :isInTable="widget.isInTable" :label="widget.label">
      <span>{{{{ formValue || '-' }}}}</span>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{ name: '{prefix}Read', mixins: [FormWidgetMixin] }}
</script>
""",

        f"src/component/form-config/BasicSetting.vue": f"""\
<template>
  <div class="form-config-item {full_kebab}-setting">
    <div class="setting-panel">
      <el-form size="mini" label-width="80px">
        <!-- 在此添加移动端组件配置项 -->
      </el-form>
    </div>
  </div>
</template>
<script>
export default {{
  name: '{prefix}Setting',
  props: {{
    componentConfig: {{ default: null }},
    formEngine: {{ default: null }},
    widget: {{ default: null }},
    editConfig: {{ default: null }},
    configProperty: {{ default: null }}
  }},
  computed: {{
    customComponentConfig() {{
      const target = this.componentConfig || this.widget || null
      return (target && target.customComponentConfig) || {{}}
    }}
  }},
  created() {{
    const target = this.componentConfig || this.widget || null
    if (target && !target.customComponentConfig) {{
      this.$set(target, 'customComponentConfig', {{}})
    }}
  }}
}}
</script>
""",

        f"src/component/index.js": f"""\
import {prefix}Edit from './form-widget/{full_kebab}-edit.vue'
import {prefix}Read from './form-widget/{full_kebab}-read.vue'
import {prefix}Setting from './form-config/BasicSetting.vue'

export const customFormWidgetList = [{prefix}Edit, {prefix}Read]
export const customFormEditorList = [{prefix}Setting]
""",
    }


def _web_layout_template(name: str) -> Dict[str, str]:
    """Web端自定义布局模板 - 基于LayoutEngine"""
    module = f"apaas-custom-{name}"
    output_name = f"form-layout-{name}"
    camel = "".join(w.capitalize() for w in name.split("-"))

    return {
        f"src/apaas.json": json.dumps({
            "entry": "index.js",
            "templateType": "PAGE_LAYOUT",
            "router": {},
            "customWidgetList": [],
            "layout": [{
                "name": module,
                "desc": f"自定义布局-{name}",
                "status": "ENABLE"
            }],
            "copyAssets": [f"public/form-layout/{name}"],
            "outputName": output_name
        }, indent=2, ensure_ascii=False),

        f"src/index.js": f"""\
import './form-layout-local/index.js'
import Home from './form-layout/{module}.vue'

const install = function(Vue, opts) {{
  if (Vue.LayoutEngine) {{
    const layoutEngine = Vue.LayoutEngine.getInstance(
      Vue.LayoutEngine.currentLayoutId
    )
    Vue.component('{module}', Home)
    layoutEngine.registerLayoutComponent(Home)
  }}
}}

export default {{ install }}
""",

        f"src/form-layout-local/index.js": "export default {{}}\\n",

        f"src/form-layout/{module}.vue": f"""\
<template>
  <div class="{module}">
    <x-app-layout :layout-engine="layoutEngine" :is-collapse="isCollapse">
      <template v-slot:header>
        <x-app-header
          v-if="appInfo"
          :layout-engine="layoutEngine"
          :app-info="appInfo"
        />
      </template>
      <template v-slot:menu>
        <x-app-menu
          :menu-config="menuConfig"
          :show-menu="showMenu && !!appInfo"
          :is-collapse="isCollapse"
          :layout-engine="layoutEngine"
          @menu-add-click="menuAddClick"
        />
      </template>
      <template v-slot:appPage>
        <!-- 平台会在此注入页面内容 -->
        <slot name="appPage"></slot>
      </template>
    </x-app-layout>
  </div>
</template>

<script>
export default {{
  name: 'ApaasCustomLayout{camel}',
  props: {{
    layoutEngine: {{
      type: Object,
      default: () => ({{}})
    }},
    pkgVersion: {{
      type: String,
      default: ''
    }}
  }},
  data() {{
    return {{
      isCollapse: false,
      showMenu: true
    }}
  }},
  computed: {{
    appInfo() {{
      return this.layoutEngine?.layoutDataControl?.appInfo ?? {{}}
    }},
    menuConfig() {{
      return this.layoutEngine?.layoutDataControl?.menuConfig ?? {{
        menu: [],
        defaultActive: null,
        menuTreeData: []
      }}
    }}
  }},
  methods: {{
    menuAddClick(e) {{
      this.$emit('menu-add-click', e)
    }}
  }}
}}
</script>

<style lang="scss" scoped>
.{module} {{
  height: 100%;
  width: 100%;
}}
</style>
""",
    }


def _web_plugin_template(name: str) -> Dict[str, str]:
    """Web端自开发插件模板 - 对齐 FRONTEND_PLUGIN 协议"""
    module = f"frontend-plugin-{name}"
    ext_code = f"PLUGIN_{name.upper().replace('-', '_')}"

    return {
        "src/apaas.json": json.dumps({
            "copyAssets": [f"public/frontend-plugin/{module}"],
            "templateType": "FRONTEND_PLUGIN",
            "code": ext_code,
            "name": "",
            "description": "",
            "outputName": module,
            "admin": "admin.js",
            "app": "app.js",
            "mobile": "mobile.js",
            "extraConfig": {}
        }, indent=2, ensure_ascii=False),

        "src/admin.js": """\
import './plugin-local/index.js'
import extensionConfig from './extension.js'
import CustomPanel from './custom-tab/custom-panel.vue'

const activateExtension = () => {
  const engine = window?.Vue?._extensionEngine
  if (engine && typeof engine.registerExtensionConfig === 'function') {
    engine.registerExtensionConfig(extensionConfig)
  }
}

// eslint-disable-next-line no-unused-vars
const install = function (context, hookManager, definition) {
  activateExtension()
}

// eslint-disable-next-line no-unused-vars
const activate = function (context, hookManager, definition) {
  activateExtension()
}

const staticComponents = [CustomPanel]

export default { install, activate, staticComponents }
""",

        "src/app.js": """\
import extension from './admin.js'
export default extension
""",

        "src/mobile.js": """\
import extension from './admin.js'
export default extension
""",

        "src/extension.js": f"""\
import {{ getCustomTabConfig }} from './tab-config.js'

const extensionConfig = {{
  code: '{ext_code}',
  name: '自开发插件-{name}',
  blocks: [],
  versions: ['TRIAL_EDITION', 'TEAM_EDITION', 'STANDARD_EDITION', 'PREMIUM_EDITION'],
  enable: true,
  extensionMethods: {{
    'custom-tab': {{
      getCustomTabConfig
    }}
  }}
}}

export default extensionConfig
""",

        "src/tab-config.js": """\
export function getCustomTabConfig() {
  return [
    {
      code: 'customPanel',
      title: '自定义面板',
      componentName: 'apaas-plugin-panel',
      resourceCode: 'APP_INFORMATION'
    }
  ]
}
""",

        "src/plugin-local/index.js": """\
import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

const mergeLocaleMessage =
  window.df?.getI18n?.().mergeLocaleMessage?.bind(window.df.getI18n()) ||
  window.APaaSSDK?.context?.globalVueI18n?.mergeLocaleMessage?.bind(window.APaaSSDK.context.globalVueI18n)

if (mergeLocaleMessage) {
  mergeLocaleMessage('zh-CN', zhLocaleModule)
  mergeLocaleMessage('en-US', enLocaleModule)
}
""",

        "src/plugin-local/zh-CN/index.js": """\
export default {
  frontendPlugin: {
    title: '插件标题',
    panel: '自定义面板'
  }
}
""",

        "src/plugin-local/en-US/index.js": """\
export default {
  frontendPlugin: {
    title: 'Plugin Title',
    panel: 'Custom Panel'
  }
}
""",

        "src/custom-tab/custom-panel.vue": """\
<template>
  <div class="plugin-panel">
    <h3>{{ $t ? $t('frontendPlugin.title') : '插件标题' }}</h3>
    <p>{{ $t ? $t('frontendPlugin.panel') : '自定义面板' }}</p>
  </div>
</template>

<script>
export default {
  name: 'apaas-plugin-panel'
}
</script>

<style lang="scss" scoped>
.plugin-panel {
  padding: 20px;
}
</style>
""",
    }


def _backend_api_template(name: str) -> Dict[str, str]:
    """后端自开发接口模板"""
    camel = "".join(w.capitalize() for w in name.split("-"))
    pkg_name = name.replace("-", "")

    return {
        f"src/main/java/com/xdap/custom/{pkg_name}/controller/{camel}Controller.java": f"""\
package com.xdap.custom.{pkg_name}.controller;

import com.xdap.custom.{pkg_name}.service.{camel}Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/custom/{name}")
public class {camel}Controller {{

    @Autowired
    private {camel}Service {pkg_name}Service;

    @GetMapping("/list")
    public Map<String, Object> list() {{
        Map<String, Object> result = new HashMap<>();
        result.put("code", "ok");
        result.put("data", {pkg_name}Service.getList());
        return result;
    }}
}}
""",

        f"src/main/java/com/xdap/custom/{pkg_name}/service/{camel}Service.java": f"""\
package com.xdap.custom.{pkg_name}.service;

import java.util.List;

public interface {camel}Service {{
    List<?> getList();
}}
""",

        f"src/main/java/com/xdap/custom/{pkg_name}/service/impl/{camel}ServiceImpl.java": f"""\
package com.xdap.custom.{pkg_name}.service.impl;

import com.xdap.custom.{pkg_name}.service.{camel}Service;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class {camel}ServiceImpl implements {camel}Service {{

    @Override
    public List<?> getList() {{
        return new ArrayList<>();
    }}
}}
""",

        f"src/main/java/com/xdap/custom/{pkg_name}/config/{camel}AllowUrlConfig.java": f"""\
package com.xdap.custom.{pkg_name}.config;

import com.definesys.mpaas.common.http.AllowUrlManage;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.Set;

@Component
public class {camel}AllowUrlConfig implements AllowUrlManage {{

    @Override
    public Set<String> getCustomAllowUrls() {{
        Set<String> urlSet = new HashSet<>();
        urlSet.add("/custom/{name}/*");
        return urlSet;
    }}
}}
""",
    }


def _script_js_template(name: str) -> Dict[str, str]:
    """JavaScript 脚本扩展模板"""
    return {
        "src/script.js": f"""\
/**
 * JavaScript 脚本扩展 - {name}
 * 在业务事件中嵌入前端 JavaScript 脚本
 *
 * API:
 *   lowCodeContext.businessEventEngine.customNodeData  - 当前节点数据
 *   lowCodeContext.businessEventEngine.inputDatas       - 触发数据
 *   lowCodeContext.businessEventEngine.confirmEventEmit(result) - 确认执行
 *   lowCodeContext.businessEventEngine.cancelEventEmit()  - 取消执行
 */

// 获取触发数据
const inputDatas = lowCodeContext.businessEventEngine.inputDatas
const formData = inputDatas[0] || {{}}

// TODO: 实现业务逻辑

// 返回结果
return {{}}
""",
    }


def _script_python_template(name: str) -> Dict[str, str]:
    """Python 脚本扩展模板"""
    return {
        "src/script.py": f"""\
\"\"\"
Python 脚本扩展 - {name}
在后端业务事件中执行 Python 脚本

API:
  definesys.input()    - 获取输入参数（dict）
  definesys.output()   - 设置输出结果
  definesys.log()      - 日志输出
  definesys.http_get/http_post - HTTP 请求
\"\"\"

# 获取输入数据
params = definesys.input()

# TODO: 实现业务逻辑

# 返回结果
definesys.output({{"status": "ok"}})
""",
    }


def _script_groovy_template(name: str) -> Dict[str, str]:
    """Groovy 脚本扩展模板"""
    return {
        "src/script.groovy": f"""\
/**
 * Groovy 脚本扩展 - {name}
 * 在后端业务事件中执行 Groovy 脚本
 *
 * API:
 *   xdapEventSystemFunctions.getFullData() - 获取完整表单数据
 *   xdapEventSystemFunctions.setResult()   - 设置返回结果
 */

def fullData = xdapEventSystemFunctions.getFullData()

// TODO: 实现业务逻辑

xdapEventSystemFunctions.setResult(["status": "ok"])
""",
    }


def _business_dialog_template(name: str) -> Dict[str, str]:
    """业务事件自定义弹窗模板"""
    return {
        "src/setting.js": f"""\
/**
 * 业务事件自定义弹窗 - {name}
 * 在业务事件触发时弹出自定义对话框，采集用户输入
 */
const componentOptions = {{
  language: 'Vue',
  template: `
    <div class="custom-dialog-{name}">
      <el-form ref="ruleForm" :model="formData" :rules="rules" label-width="80px">
        <el-form-item label="备注" prop="remark">
          <el-input v-model="formData.remark" type="textarea" :rows="3" placeholder="请输入"></el-input>
        </el-form-item>
      </el-form>
    </div>
  `,
  footerTemplate: `
    <el-button @click="onCancel">取消</el-button>
    <el-button type="primary" @click="onSubmit" :loading="submitting">确定</el-button>
  `,
  data() {{
    return {{
      modalOptions: {{
        modalVisible: true,
        title: '{name}',
        width: '480',
        loading: false,
        closeConfig: {{
          onClose: () => {{ lowCodeContext.businessEventEngine.cancelEventEmit() }},
        }},
      }},
      formData: {{ remark: '' }},
      rules: {{ remark: [{{ required: true, message: '请输入备注', trigger: 'blur' }}] }},
      submitting: false,
    }}
  }},
  methods: {{
    onSubmit() {{
      this.$refs.ruleForm.validate((valid) => {{
        if (valid) {{
          this.submitting = true
          lowCodeContext.businessEventEngine.confirmEventEmit(this.formData)
          this.modalOptions.modalVisible = false
        }}
      }})
    }},
    onCancel() {{
      lowCodeContext.businessEventEngine.cancelEventEmit()
      this.modalOptions.modalVisible = false
    }},
  }},
}}
""",
    }


def _ui_style_template(name: str) -> Dict[str, str]:
    """UI 样式扩展模板 — 纯 CSS"""
    return {
        "src/style.css": f"""/**
 * UI 样式扩展 - {name}
 *
 * 使用 .form-custom-style 作用域限制影响范围
 * 使用 [data-component-id="xxx"] 定位具体字段
 *
 * 常用 Element UI 类名:
 *   .el-input__inner          输入框
 *   .el-form-item__label      标签
 *   .el-select .el-input      下拉框
 *   .el-table th              表头
 *   .el-button--primary       主按钮
 *   .x-form-build-render      表单渲染区
 */

/* ====== 全局样式 ====== */
.form-custom-style {{
  /* 表单标签加粗 */
  .el-form-item__label {{
    font-weight: 600;
  }}

  /* 输入框统一圆角 */
  .el-input__inner {{
    border-radius: 6px;
  }}
}}

/* ====== 按字段定位（替换为实际 data-component-id）====== */
/*
[data-component-id="your-field-uuid"] {{
  .el-input__inner {{
    background-color: #f5f7fa;
  }}
}}
*/

/* ====== 响应式 ====== */
@media (max-width: 768px) {{
  .form-custom-style {{
    .el-form-item__label {{
      font-size: 13px;
    }}
  }}
}}
""",
    }


def _list_custom_module_template(name: str) -> Dict[str, str]:
    """列表自定义模块模板 — Vue/HTML + SCSS"""
    pascal = "".join(w.capitalize() for w in name.split("-"))
    return {
        "src/module-template.vue": f"""<template>
  <div class="list-custom-module-{name}">
    <div class="module-header">
      <h3>{{{{ title }}}}</h3>
      <span class="module-count">共 {{{{ total }}}} 条</span>
    </div>
    <div class="module-content">
      <!-- TODO: 自定义列表内容 -->
      <div v-for="(item, index) in listData" :key="index" class="module-item">
        <span>{{{{ item.name || '-' }}}}</span>
      </div>
      <div v-if="!listData.length" class="module-empty">暂无数据</div>
    </div>
  </div>
</template>

<script>
export default {{
  name: '{pascal}Module',
  props: {{
    lowCodeContext: {{ type: Object, default: () => ({{}}), }},
  }},
  data() {{
    return {{
      title: '{name}',
      listData: [],
      total: 0,
    }}
  }},
  mounted() {{
    this.loadData()
  }},
  methods: {{
    loadData() {{
      // 通过 lowCodeContext.pageViewConfig 获取列表数据
      const pageViewConfig = this.lowCodeContext?.pageViewConfig
      if (pageViewConfig) {{
        this.listData = pageViewConfig.data || []
        this.total = pageViewConfig.total || 0
      }}
    }},
  }},
}}
</script>
""",
        "src/module-style.scss": f"""/* 列表自定义模块样式 - {name} */
.list-custom-module-{name} {{
  padding: 16px;

  .module-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    h3 {{
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }}

    .module-count {{
      color: #909399;
      font-size: 13px;
    }}
  }}

  .module-item {{
    padding: 10px 12px;
    border-bottom: 1px solid #ebeef5;
    font-size: 14px;

    &:last-child {{
      border-bottom: none;
    }}
  }}

  .module-empty {{
    text-align: center;
    color: #c0c4cc;
    padding: 40px 0;
    font-size: 14px;
  }}
}}
""",
    }


def _web_login_template(name: str) -> Dict[str, str]:
    """自定义登录页模板 — 完整 Vue 项目"""
    pascal = "".join(w.capitalize() for w in name.split("-"))
    full_name = f"apaas-custom-{name}"
    apaas_config = {
        "entry": "index.js",
        "router": {full_name: full_name},
        "outputName": full_name,
    }
    return {
        "src/apaas.json": json.dumps(apaas_config, indent=2, ensure_ascii=False),
        "src/index.js": f"""import LoginPage from './login.vue'

const install = function(Vue) {{
  Vue.component('apaas-custom-{name}', LoginPage)
}}

export default {{ install }}
""",
        "src/login.vue": f"""<template>
  <div class="custom-login-page">
    <div class="login-container">
      <div class="login-header">
        <h1>{{{{ title }}}}</h1>
        <p>欢迎使用</p>
      </div>
      <el-form ref="loginForm" :model="form" :rules="rules" class="login-form">
        <el-form-item prop="username">
          <el-input v-model="form.username" prefix-icon="el-icon-user" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" prefix-icon="el-icon-lock" placeholder="请输入密码"
            type="password" show-password @keyup.enter.native="handleLogin" />
        </el-form-item>
        <el-button type="primary" :loading="loading" class="login-btn" @click="handleLogin">
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script>
export default {{
  name: '{pascal}Login',
  data() {{
    return {{
      title: '系统登录',
      loading: false,
      form: {{ username: '', password: '' }},
      rules: {{
        username: [{{ required: true, message: '请输入账号', trigger: 'blur' }}],
        password: [{{ required: true, message: '请输入密码', trigger: 'blur' }}],
      }},
    }}
  }},
  methods: {{
    handleLogin() {{
      this.$refs.loginForm.validate(async (valid) => {{
        if (!valid) return
        this.loading = true
        try {{
          // TODO: 调用登录接口
          // const res = await this.$request(...)
          // 登录成功后跳转
          // window.location.href = '/app/callback/apaas/index.html'
        }} catch (e) {{
          this.$message.error(e.message || '登录失败')
        }} finally {{
          this.loading = false
        }}
      }})
    }},
  }},
}}
</script>

<style scoped>
.custom-login-page {{
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}}
.login-container {{
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}}
.login-header {{
  text-align: center;
  margin-bottom: 30px;
}}
.login-header h1 {{
  margin: 0 0 8px;
  font-size: 28px;
  color: #303133;
}}
.login-header p {{
  margin: 0;
  color: #909399;
}}
.login-btn {{
  width: 100%;
  height: 44px;
  font-size: 16px;
  margin-top: 10px;
}}
</style>
""",
        "env.tmpl.js": """// 环境变量模板 - 部署时替换
window.GLOBAL_ENV = {
  ENV: '${ENV}',           // GRAY / OL
  SSO_URL: '${SSO_URL}',  // SSO 登录地址
  API_BASE: '${API_BASE}', // 后端 API 地址
  CALLBACK_URL: '${CALLBACK_URL}', // 登录回调地址
}
""",
    }
