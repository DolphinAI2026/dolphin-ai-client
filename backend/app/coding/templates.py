"""
项目模板 - 为各种开发场景提供初始项目骨架
"""

import json
from typing import Dict, List
from app.coding.scenes import SceneType


def get_project_template(scene_type: SceneType, module_name: str) -> Dict[str, str]:
    """获取项目模板，返回 {文件路径: 文件内容} 字典"""
    generators = {
        SceneType.WEB_COMPONENT: _web_component_template,
        SceneType.WEB_PAGE: _web_page_template,
        SceneType.WEB_LIST_VIEW: _web_list_view_template,
        SceneType.MOBILE_PAGE: _mobile_page_template,
        SceneType.MOBILE_COMPONENT: _mobile_component_template,
        SceneType.BACKEND_API: _backend_api_template,
    }
    generator = generators.get(scene_type)
    if generator:
        return generator(module_name)
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
    componentModelField: ['TEXT'],
    editor: {{ config: ['INFO','LABEL','FIELD_CODE','TITLE_DESCRIPTION','WIDTH','{code}_SETTING','FORMULA_RULE','HIDDEN','READONLY','REQUIRED','EDITONNEW','UNIQUE','HIDDEN_SAVE','HIDDEN_TRIGGER','TRIGGER_BUSINESS_EVENTS'], excludeInTable: ['WIDTH'] }}
  }},
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
      <el-form size="mini" label-width="100px">
        <!-- 在此添加配置项，使用 v-model + @change="saveConfig" -->
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
  data() {{
    return {{
      localConfig: {{}}
    }}
  }},
  computed: {{
    widgetObj() {{
      return this.componentConfig || this.widget || {{}}
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
    const saved = this.widgetObj.customComponentConfig || {{}}
    Object.keys(this.localConfig).forEach(key => {{
      if (saved[key] !== undefined) this.localConfig[key] = saved[key]
    }})
  }},
  methods: {{
    saveConfig() {{
      this.$set(this.widgetObj, 'customComponentConfig', {{ ...this.localConfig }})
    }}
  }}
}}
</script>
<style lang="scss">
.{full_kebab}-setting {{
  .setting-panel {{
    padding: 12px;
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
    module = f"apaas-custom-list-{name}"

    return {
        f"src/custom/{module}/apaas.json": f"""\
{{
  "entry": "index.js",
  "copyAssets": ["public/custom/{module}"],
  "list": {{
    "{module}": {{
      "renderLogic": "FORM_LIST_VIEW",
      "desc": "自定义列表-{name}",
      "status": "ENABLE"
    }}
  }},
  "outputName": "{module}"
}}""",

        f"src/custom/{module}/index.js": f"""\
import CustomListView from './custom-list/custom-list-view.vue'

const install = function(Vue, opts) {{
  Vue.component('{module}', CustomListView)
}}

export default {{ install }}
""",

        f"src/custom/{module}/custom-list/custom-list-view.vue": f"""\
<template>
  <div class="custom-list-view">
    <x-list-view :listEngine="listEngine"></x-list-view>
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
  data() {{
    return {{}}
  }},
  methods: {{}}
}}
</script>

<style lang="scss">
.custom-list-view {{
  height: 100%;
}}
</style>
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
    """移动端自开发组件模板 - 与Web端组件结构相同"""
    return _web_component_template(name)


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
