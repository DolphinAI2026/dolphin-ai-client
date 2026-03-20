"""
项目模板 - 为各种开发场景提供初始项目骨架
"""

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
    """Web端自开发组件模板"""
    code = name.upper().replace("-", "_")
    camel = "".join(w.capitalize() for w in name.split("-"))

    return {
        f"src/custom/apaas-custom-widget/apaas.json": f"""\
{{
  "entry": "index.js",
  "copyAssets": ["public/custom/apaas-custom-widget"],
  "router": {{
    "apaas-custom-widget": {{
      "name": "apaas-custom-widget",
      "path": "apaas-custom-widget",
      "meta": {{ "title": "自开发Widget" }}
    }}
  }},
  "customWidgetList": [
    {{ "code": "FORM_CUSTOM_{code}", "text": "{name}" }}
  ],
  "outputName": "apaas-custom-widget"
}}""",

        f"src/custom/apaas-custom-widget/index.js": f"""\
import ApaasCustomWidget from './custom-page/page.vue'
import {{ customFormComponentList }} from './custom-component/form-component'
import {{ widgetConfigList }} from './custom-component/form-config'

const install = function(Vue, opts) {{
  Vue.component('apaas-custom-widget', ApaasCustomWidget)
  if (customFormComponentList && Array.isArray(customFormComponentList)) {{
    customFormComponentList.forEach((comp) => {{
      Vue.component(comp.name, comp)
    }})
  }}
  if (widgetConfigList && Array.isArray(widgetConfigList)) {{
    widgetConfigList.forEach((widgetConfig) => {{
      Vue.FormEngine && Vue.FormEngine.registerCustomComponentConfig({{ widgetConfig }})
    }})
  }}
}}

export default {{ install }}
""",

        f"src/custom/apaas-custom-widget/custom-component/form-config/form-widget/{name}.config.js": f"""\
const FormCustom{camel}Config = {{
  version: 2.0,
  code: 'FORM_CUSTOM_{code}',
  component: {{
    edit: 'FormCustom{camel}',
    read: 'FormCustomRead{camel}'
  }}
}}
export default FormCustom{camel}Config
""",

        f"src/custom/apaas-custom-widget/custom-component/form-config/form-widget/index.js": f"""\
import FormCustom{camel}Config from './{name}.config'

const widgetConfigList = [
  FormCustom{camel}Config
]
export default widgetConfigList
""",

        f"src/custom/apaas-custom-widget/custom-component/form-component/form-widget/edit/{name}.vue": f"""\
<template>
  <x-proxy-form-item
    :isInTable="widget.isInTable"
    :showRequired="showRequired"
    :label="widget.label"
    :validatorRules="validatorRules"
    :validateKey="validateKey"
    :validateInfo="validateInfo"
  >
    <!-- 在此添加自定义内容 -->
    <el-input v-model="formValue" placeholder="请输入"></el-input>
  </x-proxy-form-item>
</template>

<script>
import FormWidgetConfigMixin from '@/mixin/form-widget.mixin'

export default {{
  name: 'FormCustom{camel}',
  mixins: [FormWidgetConfigMixin],
  data() {{
    return {{}}
  }},
  methods: {{}}
}}
</script>
""",

        f"src/custom/apaas-custom-widget/custom-component/form-component/form-widget/edit/index.js": f"""\
import FormCustom{camel} from './{name}.vue'

const editFormComponentList = [
  FormCustom{camel}
]
export default editFormComponentList
""",

        f"src/custom/apaas-custom-widget/custom-component/form-component/form-widget/read/{name}-read.vue": f"""\
<template>
  <x-proxy-form-item
    :isInTable="widget.isInTable"
    :label="widget.label"
  >
    <span>{{{{ formValue }}}}</span>
  </x-proxy-form-item>
</template>

<script>
import FormWidgetConfigMixin from '@/mixin/form-widget.mixin'

export default {{
  name: 'FormCustomRead{camel}',
  mixins: [FormWidgetConfigMixin]
}}
</script>
""",

        f"src/custom/apaas-custom-widget/custom-component/form-component/form-widget/read/index.js": f"""\
import FormCustomRead{camel} from './{name}-read.vue'

const readFormComponentList = [
  FormCustomRead{camel}
]
export default readFormComponentList
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
