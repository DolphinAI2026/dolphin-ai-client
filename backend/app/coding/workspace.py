"""
Workspace Manager - 管理aPaaS自开发项目的工作区
负责项目创建、模板脚手架、文件读写、依赖安装、构建
"""

import os
import json
import shutil
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)

# 工作区根目录
WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent / "workspaces"


class ProjectType(str, Enum):
    """项目类型"""
    FORM_COMPONENT = "form-component"   # 表单自开发组件
    FORM_PAGE = "form-page"             # 自开发菜单页面
    FORM_LIST = "form-list"             # 自开发列表视图
    BACKEND_API = "backend-api"         # 后端自开发接口


class WorkspaceStatus(str, Enum):
    CREATING = "creating"
    INSTALLING = "installing"
    READY = "ready"
    BUILDING = "building"
    ERROR = "error"


class WorkspaceManager:
    """工作区管理器"""

    def __init__(self):
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    def create_workspace(
        self,
        project_type: ProjectType,
        project_name: str,
        user_id: int,
    ) -> dict:
        """创建新工作区并生成脚手架"""
        # 生成 workspace ID
        ws_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        ws_path = WORKSPACE_ROOT / ws_id

        if ws_path.exists():
            shutil.rmtree(ws_path)

        ws_path.mkdir(parents=True)

        # 规范化项目名
        safe_name = project_name.replace(" ", "-").lower()
        if not safe_name.startswith("apaas-custom-"):
            # 根据类型加前缀
            prefix_map = {
                ProjectType.FORM_COMPONENT: "form-component-",
                ProjectType.FORM_PAGE: "form-page-",
                ProjectType.FORM_LIST: "form-list-",
                ProjectType.BACKEND_API: "backend-api-",
            }
            safe_name = prefix_map.get(project_type, "") + safe_name

        # 写入 workspace 元信息
        meta = {
            "id": ws_id,
            "project_type": project_type.value,
            "project_name": safe_name,
            "user_id": user_id,
            "status": WorkspaceStatus.CREATING.value,
        }
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

        # 生成脚手架
        if project_type == ProjectType.FORM_COMPONENT:
            self._scaffold_form_component(ws_path, safe_name)
        elif project_type == ProjectType.FORM_PAGE:
            self._scaffold_form_page(ws_path, safe_name)
        elif project_type == ProjectType.FORM_LIST:
            self._scaffold_form_list(ws_path, safe_name)
        elif project_type == ProjectType.BACKEND_API:
            self._scaffold_backend_api(ws_path, safe_name)

        # 更新状态
        meta["status"] = WorkspaceStatus.READY.value
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

        return meta

    async def install_deps(self, ws_id: str) -> dict:
        """安装 npm 依赖"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        meta = self._read_meta(ws_path)
        if meta["project_type"] == ProjectType.BACKEND_API.value:
            return {"status": "skip", "message": "后端项目无需 npm install"}

        meta["status"] = WorkspaceStatus.INSTALLING.value
        self._write_meta(ws_path, meta)

        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                "--registry", "https://registry.dfy.definesys.cn/repository/apaas-npm-group/",
                cwd=str(ws_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                meta["status"] = WorkspaceStatus.READY.value
                self._write_meta(ws_path, meta)
                return {"status": "ok", "message": "依赖安装完成"}
            else:
                meta["status"] = WorkspaceStatus.ERROR.value
                self._write_meta(ws_path, meta)
                return {
                    "status": "error",
                    "message": stderr.decode("utf-8", errors="replace")[:500],
                }
        except Exception as e:
            meta["status"] = WorkspaceStatus.ERROR.value
            self._write_meta(ws_path, meta)
            return {"status": "error", "message": str(e)}

    async def build_project(self, ws_id: str) -> dict:
        """构建项目"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        meta = self._read_meta(ws_path)
        meta["status"] = WorkspaceStatus.BUILDING.value
        self._write_meta(ws_path, meta)

        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "run", "build",
                cwd=str(ws_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                meta["status"] = WorkspaceStatus.READY.value
                self._write_meta(ws_path, meta)
                return {"status": "ok", "message": "构建成功"}
            else:
                meta["status"] = WorkspaceStatus.ERROR.value
                self._write_meta(ws_path, meta)
                return {
                    "status": "error",
                    "message": stderr.decode("utf-8", errors="replace")[:500],
                }
        except Exception as e:
            meta["status"] = WorkspaceStatus.ERROR.value
            self._write_meta(ws_path, meta)
            return {"status": "error", "message": str(e)}

    def write_file(self, ws_id: str, file_path: str, content: str):
        """写入文件到工作区"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        # 安全检查：不允许写入工作区外
        target = (ws_path / file_path).resolve()
        if not str(target).startswith(str(ws_path.resolve())):
            raise ValueError("File path escapes workspace")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, ws_id: str, file_path: str) -> str:
        """读取工作区文件"""
        ws_path = WORKSPACE_ROOT / ws_id
        target = (ws_path / file_path).resolve()
        if not str(target).startswith(str(ws_path.resolve())):
            raise ValueError("File path escapes workspace")
        if not target.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return target.read_text(encoding="utf-8")

    def list_files(self, ws_id: str) -> list:
        """列出工作区的文件树"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        files = []
        for p in sorted(ws_path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(ws_path)
                rel_str = str(rel)
                # 跳过隐藏文件和 node_modules
                if rel_str.startswith(".") or "node_modules" in rel_str:
                    continue
                files.append(rel_str)
        return files

    def get_workspace_info(self, ws_id: str) -> dict:
        """获取工作区信息"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")
        meta = self._read_meta(ws_path)
        meta["files"] = self.list_files(ws_id)
        return meta

    def list_user_workspaces(self, user_id: int) -> list:
        """列出用户的所有工作区"""
        results = []
        if not WORKSPACE_ROOT.exists():
            return results
        for d in WORKSPACE_ROOT.iterdir():
            if d.is_dir() and d.name.startswith(f"{user_id}_"):
                try:
                    meta = self._read_meta(d)
                    results.append(meta)
                except Exception:
                    pass
        return results

    def delete_workspace(self, ws_id: str):
        """删除工作区"""
        ws_path = WORKSPACE_ROOT / ws_id
        if ws_path.exists():
            shutil.rmtree(ws_path)

    # ========== 内部方法 ==========

    def _read_meta(self, ws_path: Path) -> dict:
        meta_file = ws_path / ".workspace.json"
        return json.loads(meta_file.read_text())

    def _write_meta(self, ws_path: Path, meta: dict):
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

    # ========== 公共文件 ==========

    def _write_common_files(self, ws_path: Path, name: str, template_type: str):
        """写入所有项目类型共用的基础文件"""
        # jsconfig.json
        self._write(ws_path, "jsconfig.json", json.dumps({
            "compilerOptions": {
                "target": "es5",
                "module": "esnext",
                "baseUrl": "./",
                "moduleResolution": "node",
                "paths": {"@/*": ["src/*"]},
                "lib": ["esnext", "dom", "dom.iterable", "scripthost"]
            }
        }, indent=2))

        # .gitignore
        self._write(ws_path, ".gitignore", """node_modules/
dist/
*.local
.DS_Store
*.log
""")

        # .env.example
        self._write(ws_path, ".env.example", """# 环境变量示例
# VUE_APP_API_BASE=https://your-apaas-domain.com
""")

        # public 目录占位
        pub_dir = f"public/{'form-component' if template_type == 'FORM_COMPONENT' else 'form-page'}/{name}"
        self._write(ws_path, f"{pub_dir}/.gitkeep", "")

    # ========== 脚手架模板 ==========

    def _scaffold_form_component(self, ws_path: Path, name: str):
        """表单自开发组件脚手架"""
        # 公共文件
        self._write_common_files(ws_path, name, "FORM_COMPONENT")

        # 组件 code（大写下划线格式）
        code = "FORM_CUSTOM_" + name.replace("form-component-", "").replace("-", "_").upper()
        # 组件名（PascalCase）
        parts = name.replace("form-component-", "").split("-")
        pascal = "".join(p.capitalize() for p in parts)
        component_name = f"FormCustom{pascal}"
        read_name = f"FormCustomRead{pascal}"
        # 文件名 kebab-case
        kebab = name.replace("form-component-", "")

        # package.json
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "private": True,
            "templateType": "FORM_COMPONENT",
            "scripts": {
                "serve": "vue-cli-service serve",
                "build": f"vue-cli-service build --target lib --name {name} src/index.js"
            },
            "dependencies": {},
            "devDependencies": {
                "@vue/cli-service": "~5.0.0",
                "vue-template-compiler": "^2.7.16",
                "vue": "^2.7.16"
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead"]
        }, indent=2, ensure_ascii=False))

        # vue.config.js - 读取 apaas.json
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  css: { extract: false },
  configureWebpack: {
    output: {
      library: apaasJson.outputName,
      libraryTarget: 'umd',
      libraryExport: 'default'
    },
    externals: {
      vue: 'Vue'
    }
  }
})
""")

        # babel.config.js
        self._write(ws_path, "babel.config.js", """module.exports = {
  presets: ['@vue/cli-plugin-babel/preset']
}
""")

        # apaas.json
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "templateType": "FORM_COMPONENT",
            "customWidgetList": [
                {"code": code, "text": kebab, "description": kebab}
            ],
            "copyAssets": [f"public/form-component/{name}"],
            "outputName": name
        }, indent=2, ensure_ascii=False))

        # src/index.js - 入口
        self._write(ws_path, "src/index.js", f"""import {{ customFormComponentList }} from './form-component'
import {{ widgetConfigList }} from './form-component-config'

const install = function(Vue, opts) {{
  // 注册自定义表单组件
  customFormComponentList.forEach(comp => Vue.component(comp.name, comp))
  // 注册组件配置到 FormEngine
  widgetConfigList.forEach(widgetConfig => {{
    Vue.FormEngine && Vue.FormEngine.registerCustomComponentConfig({{ widgetConfig }})
  }})
}}

export default {{ install }}
""")

        # form-component/index.js
        self._write(ws_path, "src/form-component/index.js", f"""import EditComponent from './form-widget/edit/{kebab}-edit.vue'
import ReadComponent from './form-widget/read/{kebab}-read.vue'

export const customFormComponentList = [EditComponent, ReadComponent]

const install = function(Vue, opts) {{
  customFormComponentList.forEach(comp => Vue.component(comp.name, comp))
}}

export default {{ install }}
""")

        # form-component/form-widget/index.js
        self._write(ws_path, "src/form-component/form-widget/index.js", f"""export {{ default as Edit }} from './edit/{kebab}-edit.vue'
export {{ default as Read }} from './read/{kebab}-read.vue'
""")

        # edit 组件
        self._write(ws_path, f"src/form-component/form-widget/edit/index.js", f"""import Component from './{kebab}-edit.vue'
export default Component
""")
        self._write(ws_path, f"src/form-component/form-widget/edit/{kebab}-edit.vue", f"""<template>
  <x-proxy-form-item
    :isInTable="widget.isInTable"
    :showRequired="showRequired"
    :label="widget.label"
    :validatorRules="validatorRules"
    :validateKey="validateKey"
    :validateInfo="validateInfo"
  >
    <!-- TODO: 在这里实现编辑态组件 -->
    <el-input
      v-model="formValue"
      :placeholder="widget.label || '请输入'"
      :disabled="formDisabled || formReadonly"
    />
  </x-proxy-form-item>
</template>

<script>
import FormWidgetConfigMixin from '@/mixin/form-widget.mixin'

export default {{
  name: '{component_name}',
  mixins: [FormWidgetConfigMixin],
  data() {{
    return {{}}
  }},
  methods: {{}}
}}
</script>

<style lang="scss" scoped>
</style>
""")

        # read 组件
        self._write(ws_path, f"src/form-component/form-widget/read/index.js", f"""import Component from './{kebab}-read.vue'
export default Component
""")
        self._write(ws_path, f"src/form-component/form-widget/read/{kebab}-read.vue", f"""<template>
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
  name: '{read_name}',
  mixins: [FormWidgetConfigMixin]
}}
</script>

<style lang="scss" scoped>
</style>
""")

        # form-component-config
        self._write(ws_path, "src/form-component-config/index.js", f"""import widgetConfig from './form-widget/{kebab}.widget.config'

export const widgetConfigList = [widgetConfig]

export default {{ widgetConfigList }}
""")

        self._write(ws_path, f"src/form-component-config/form-widget/{kebab}.widget.config.js", f"""const config = {{
  version: 2.0,
  code: '{code}',
  desc: {{
    text: '{kebab}',
    description: '{kebab}'
  }},
  component: {{
    edit: '{component_name}',
    read: '{read_name}'
  }},
  widget: {{
    display: {{
      label: '{kebab}',
      width: 1,
      hidden: false,
      readOnly: false,
      required: false
    }},
    componentModelField: ['TEXT']
  }}
}}

export default config
""")

        # mixin（平台提供，本地开发用 mock）
        self._write(ws_path, "src/mixin/form-widget.mixin.js", """/**
 * FormWidgetConfigMixin - 表单组件核心 mixin
 * 在 aPaaS 平台中由系统注入，本地开发时使用此 mock
 */
export default {
  props: {
    widget: {
      type: Object,
      default: () => ({
        code: 'demo_field',
        label: '示例字段',
        isInTable: false
      })
    },
    formReadonly: { type: Boolean, default: false },
    formDisabled: { type: Boolean, default: false },
    showRequired: { type: Boolean, default: false },
    validatorRules: { type: Array, default: () => [] },
    validateKey: { type: String, default: '' },
    validateInfo: { type: Object, default: () => ({}) }
  },
  data() {
    return {
      formValue: ''
    }
  },
  methods: {
    handleValueChange(val) {
      this.formValue = val
      this.$emit('value-change', { code: this.widget.code, value: val })
    }
  }
}
""")

        # API
        self._write(ws_path, "src/api/index.js", """const Api = {
  // 在这里定义接口
  // EXAMPLE_API: {
  //   url: 'xdap-app/custom/example/list',
  //   method: 'get'
  // }
}

export default Api
""")

        # i18n
        self._write(ws_path, "src/form-component-local/index.js", """import zhCN from './zh-CN'
import enUS from './en-US'

export default { 'zh-CN': zhCN, 'en-US': enUS }
""")
        self._write(ws_path, "src/form-component-local/zh-CN/index.js", """export default {
  // 中文语言包
}
""")
        self._write(ws_path, "src/form-component-local/en-US/index.js", """export default {
  // English language pack
}
""")

    def _scaffold_form_page(self, ws_path: Path, name: str):
        """菜单页面脚手架"""
        # 公共文件
        self._write_common_files(ws_path, name, "MENU_PAGE")

        # package.json
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "private": True,
            "templateType": "MENU_PAGE",
            "scripts": {
                "serve": "vue-cli-service serve",
                "build": f"vue-cli-service build --target lib --name {name} src/index.js"
            },
            "dependencies": {},
            "devDependencies": {
                "@vue/cli-service": "~5.0.0",
                "vue-template-compiler": "^2.7.16",
                "vue": "^2.7.16"
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead"]
        }, indent=2, ensure_ascii=False))

        # vue.config.js - 读取 apaas.json
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  css: { extract: false },
  configureWebpack: {
    output: {
      library: apaasJson.outputName,
      libraryTarget: 'umd',
      libraryExport: 'default'
    },
    externals: {
      vue: 'Vue'
    }
  }
})
""")

        # babel.config.js
        self._write(ws_path, "babel.config.js", """module.exports = {
  presets: ['@vue/cli-plugin-babel/preset']
}
""")

        # apaas.json
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "templateType": "MENU_PAGE",
            "router": {
                f"apaas-custom-{name}": {
                    "name": f"apaas-custom-{name}",
                    "path": f"apaas-custom-{name}",
                    "meta": {"title": name}
                }
            },
            "customWidgetList": [],
            "copyAssets": [f"public/form-page/{name}"],
            "outputName": name
        }, indent=2, ensure_ascii=False))

        # index.js
        component_tag = f"apaas-custom-{name}"
        self._write(ws_path, "src/index.js", f"""import ApaasCustomPage from './form-page/{component_tag}.vue'

const install = function(Vue, opts) {{
  Vue.component('{component_tag}', ApaasCustomPage)
}}

export default {{ install }}
""")

        # 主页面组件
        self._write(ws_path, f"src/form-page/{component_tag}.vue", f"""<template>
  <div class="{component_tag}">
    <div class="page-header">
      <h2>{{{{ pageTitle }}}}</h2>
    </div>

    <x-ag-grid
      rowKey="id"
      :tableData="tableData"
      :colConfigs="colConfigs"
      :pagination="pagination"
      @size-change="onSizeChange"
      @current-page-change="onCurrentPageChange"
    ></x-ag-grid>
  </div>
</template>

<script>
import Api from "../api";

export default {{
  name: "{component_tag}",
  data() {{
    return {{
      pageTitle: "{name}",
      tableData: [],
      colConfigs: [
        {{ headerName: "名称", field: "name" }},
        {{ headerName: "状态", field: "status" }},
      ],
      pagination: {{
        currentPage: 1,
        pageSize: 10,
        total: 0,
      }},
    }};
  }},
  created() {{
    // this.getTableData();
  }},
  methods: {{
    onSizeChange(size) {{
      this.pagination.pageSize = size;
      this.getTableData();
    }},
    onCurrentPageChange(page) {{
      this.pagination.currentPage = page;
      this.getTableData();
    }},
    getTableData() {{
      const {{ currentPage, pageSize }} = this.pagination;
      this.$request({{
        ...Api.QUERY_LIST,
        url: Api.QUERY_LIST.url + `?page=${{currentPage}}&pageSize=${{pageSize}}`,
      }})
        .asyncThen(
          (resp) => {{
            if (resp.code === "ok") {{
              this.tableData = resp.table || [];
              this.pagination.total = resp.total || 0;
            }} else {{
              this.$message.error(resp.message || "获取列表失败");
            }}
          }},
          (error) => {{
            console.error("获取列表失败", error);
            this.$message.error("获取列表失败");
          }}
        )
        .asyncErrorCatch((error) => {{
          console.error("请求异常", error);
          this.$message.error("请求异常");
        }});
    }},
  }},
}};
</script>

<style lang="scss">
.{component_tag} {{
  box-sizing: border-box;
  padding: 20px;

  .page-header {{
    margin-bottom: 16px;
    h2 {{
      font-size: 18px;
      font-weight: 600;
      color: #303133;
      margin: 0;
    }}
  }}
}}
</style>
""")

        # API
        self._write(ws_path, "src/api/index.js", """const Api = {
  QUERY_LIST: {
    url: 'xdap-app/custom/demo/list',
    method: 'get'
  },
  CREATE_ITEM: {
    url: 'xdap-app/custom/demo/create',
    method: 'post'
  },
  UPDATE_ITEM: {
    url: 'xdap-app/custom/demo/update',
    method: 'post'
  },
  DELETE_ITEM: {
    url: 'xdap-app/custom/demo/delete',
    method: 'post'
  }
}

export default Api
""")

        # mixin
        self._write(ws_path, "src/mixin/custom-permissions.mixin.js", """/**
 * 自定义权限 Mixin
 * 提供 customPagePermissions 对象，用于按钮权限控制
 */
export default {
  data() {
    return {
      customPagePermissions: {}
    }
  },
  created() {
    // 在 aPaaS 平台中，权限由系统自动注入
    // 本地开发时默认全部开放
    this.customPagePermissions = {
      canCreate: true,
      canEdit: true,
      canDelete: true,
      canExport: true
    }
  }
}
""")

        # i18n
        self._write(ws_path, "src/form-page-local/index.js", """import zhCN from './zh-CN'
import enUS from './en-US'

export default { 'zh-CN': zhCN, 'en-US': enUS }
""")
        self._write(ws_path, "src/form-page-local/zh-CN/index.js", """export default {
  customPage: {
    title: '页面标题'
  }
}
""")
        self._write(ws_path, "src/form-page-local/en-US/index.js", """export default {
  customPage: {
    title: 'Page Title'
  }
}
""")

    def _scaffold_form_list(self, ws_path: Path, name: str):
        """列表视图脚手架"""
        self._write_common_files(ws_path, name, "FORM_LIST")

        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "private": True,
            "templateType": "FORM_LIST",
            "scripts": {
                "serve": "vue-cli-service serve",
                "build": f"vue-cli-service build --target lib --name {name} src/index.js"
            },
            "devDependencies": {
                "@vue/cli-service": "~5.0.0",
                "vue-template-compiler": "^2.7.16",
                "vue": "^2.7.16"
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead"]
        }, indent=2, ensure_ascii=False))

        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  css: { extract: false },
  configureWebpack: {
    output: { library: apaasJson.outputName, libraryTarget: 'umd', libraryExport: 'default' },
    externals: { vue: 'Vue' }
  }
})
""")
        self._write(ws_path, "babel.config.js", "module.exports = { presets: ['@vue/cli-plugin-babel/preset'] }\n")

        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "list": {
                f"apaas-custom-{name}": {
                    "renderLogic": "FORM_LIST_VIEW",
                    "desc": name,
                    "status": "ENABLE"
                }
            },
            "outputName": name
        }, indent=2, ensure_ascii=False))

        self._write(ws_path, "src/index.js", f"""import CustomListView from './custom-list/custom-list-view.vue'

const install = function(Vue, opts) {{
  Vue.component('apaas-custom-{name}', CustomListView)
}}

export default {{ install }}
""")

        self._write(ws_path, "src/custom-list/custom-list-view.vue", """<template>
  <div class="custom-list-view">
    <x-list-view :listEngine="listEngine"></x-list-view>
  </div>
</template>

<script>
export default {
  name: 'CustomListView',
  props: {
    listEngine: { type: Object }
  }
}
</script>

<style lang="scss" scoped>
.custom-list-view {
  width: 100%;
  height: 100%;
}
</style>
""")

    def _scaffold_backend_api(self, ws_path: Path, name: str):
        """后端接口脚手架（Java/SpringBoot）"""
        # 包路径
        pkg_path = name.replace("-", "")
        class_prefix = "".join(p.capitalize() for p in name.replace("backend-api-", "").split("-"))

        self._write(ws_path, "pom.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.xdap.custom</groupId>
    <artifactId>{name}</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>

    <properties>
        <java.version>1.8</java.version>
        <spring-boot.version>2.3.4.RELEASE</spring-boot.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
            <version>${{spring-boot.version}}</version>
            <scope>provided</scope>
        </dependency>
    </dependencies>

    <repositories>
        <repository>
            <id>definesys-maven</id>
            <url>https://registry.dfy.definesys.cn/repository/maven-public/</url>
        </repository>
    </repositories>

    <profiles>
        <profile>
            <id>lib</id>
            <!-- 打包时排除第三方依赖 -->
        </profile>
    </profiles>
</project>
""")

        base_pkg = f"src/main/java/com/xdap/custom/{pkg_path}"

        self._write(ws_path, f"{base_pkg}/controller/{class_prefix}Controller.java", f"""package com.xdap.custom.{pkg_path}.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import com.xdap.custom.{pkg_path}.service.{class_prefix}Service;
import java.util.*;

@RestController
@RequestMapping("/custom/{name.replace('backend-api-', '')}")
public class {class_prefix}Controller {{

    @Autowired
    private {class_prefix}Service service;

    @GetMapping("/list")
    public Map<String, Object> list() {{
        Map<String, Object> result = new HashMap<>();
        result.put("code", "ok");
        result.put("data", service.getList());
        return result;
    }}
}}
""")

        self._write(ws_path, f"{base_pkg}/service/{class_prefix}Service.java", f"""package com.xdap.custom.{pkg_path}.service;

import java.util.List;
import java.util.Map;

public interface {class_prefix}Service {{
    List<Map<String, Object>> getList();
}}
""")

        self._write(ws_path, f"{base_pkg}/service/impl/{class_prefix}ServiceImpl.java", f"""package com.xdap.custom.{pkg_path}.service.impl;

import org.springframework.stereotype.Service;
import com.xdap.custom.{pkg_path}.service.{class_prefix}Service;
import java.util.*;

@Service
public class {class_prefix}ServiceImpl implements {class_prefix}Service {{

    @Override
    public List<Map<String, Object>> getList() {{
        // TODO: 实现业务逻辑
        return new ArrayList<>();
    }}
}}
""")

        self._write(ws_path, f"{base_pkg}/config/AllowUrlConfig.java", f"""package com.xdap.custom.{pkg_path}.config;

import org.springframework.stereotype.Component;
import java.util.*;

/**
 * 接口白名单配置 - 必须实现
 */
@Component
public class AllowUrlConfig implements com.definesys.mpaas.common.http.AllowUrlManage {{

    @Override
    public Set<String> getCustomAllowUrls() {{
        Set<String> urlSet = new HashSet<>();
        urlSet.add("/custom/{name.replace('backend-api-', '')}/*");
        return urlSet;
    }}
}}
""")

    def _write(self, base_path: Path, rel_path: str, content: str):
        """写文件，自动创建目录"""
        target = base_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
