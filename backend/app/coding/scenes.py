"""
开发场景定义 - 定义所有支持的aPaaS自开发场景
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel


class SceneType(str, Enum):
    """自开发场景类型"""
    WEB_COMPONENT = "web_component"           # Web端自开发组件
    WEB_PAGE = "web_page"                     # Web端自开发页面
    WEB_LIST_VIEW = "web_list_view"           # Web端自开发列表视图
    WEB_LAYOUT = "web_layout"                 # Web端自定义布局
    WEB_LOGIN = "web_login"                   # Web端自定义登录页
    WEB_PLUGIN = "web_plugin"                 # Web端自开发插件
    MOBILE_COMPONENT = "mobile_component"     # 移动端自开发组件
    MOBILE_PAGE = "mobile_page"               # 移动端自开发页面
    BACKEND_API = "backend_api"               # 后端自开发接口
    SCRIPT_JS = "script_js"                   # JavaScript脚本扩展
    SCRIPT_PYTHON = "script_python"           # Python脚本扩展
    SCRIPT_GROOVY = "script_groovy"           # Groovy脚本扩展
    BUSINESS_DIALOG = "business_dialog"       # 业务事件自定义弹窗
    UI_STYLE = "ui_style"                     # 界面样式扩展(CSS)
    LIST_CUSTOM_MODULE = "list_custom_module" # 列表自定义模块


class SceneInfo(BaseModel):
    """场景信息"""
    type: SceneType
    name: str
    description: str
    category: str  # frontend / backend / script
    platform: str  # web / mobile / both / server
    file_patterns: List[str]  # 需要生成的文件类型模式
    required_conventions: List[str]  # 必须遵守的规范


# 所有场景注册表
SCENE_REGISTRY: Dict[SceneType, SceneInfo] = {
    SceneType.WEB_COMPONENT: SceneInfo(
        type=SceneType.WEB_COMPONENT,
        name="Web端自开发组件",
        description="在表单中使用的自定义Vue组件，包含编辑态和只读态",
        category="frontend",
        platform="web",
        file_patterns=["*.config.js", "edit/*.vue", "read/*.vue", "index.js", "apaas.json"],
        required_conventions=[
            "必须使用FormWidgetConfigMixin",
            "组件名必须以apaas-custom-开头",
            "config中需声明version/code/component",
            "建议使用x-proxy-form-item包裹",
        ],
    ),
    SceneType.WEB_PAGE: SceneInfo(
        type=SceneType.WEB_PAGE,
        name="Web端自开发页面",
        description="完整的自定义页面，可在应用菜单中访问",
        category="frontend",
        platform="web",
        file_patterns=["page.vue", "index.js", "apaas.json"],
        required_conventions=[
            "路由必须以apaas-custom-开头",
            "模块必须在custom目录下",
            "入口为标准Vue插件格式",
            "可使用this.$request进行网络请求",
        ],
    ),
    SceneType.WEB_LIST_VIEW: SceneInfo(
        type=SceneType.WEB_LIST_VIEW,
        name="Web端自开发列表视图",
        description="自定义列表展示方式，基于ListEngine",
        category="frontend",
        platform="web",
        file_patterns=["custom-list-view.vue", "index.js", "apaas.json"],
        required_conventions=[
            "必须接收listEngine参数",
            "组件名必须以apaas-custom-开头",
            "apaas.json中配置list字段和renderLogic",
        ],
    ),
    SceneType.WEB_LAYOUT: SceneInfo(
        type=SceneType.WEB_LAYOUT,
        name="Web端自定义布局",
        description="自定义应用布局结构，基于LayoutEngine",
        category="frontend",
        platform="web",
        file_patterns=["layout.vue", "index.js", "apaas.json"],
        required_conventions=[
            "基于LayoutEngine开发",
            "组件名必须以apaas-custom-开头",
        ],
    ),
    SceneType.WEB_LOGIN: SceneInfo(
        type=SceneType.WEB_LOGIN,
        name="Web端自定义登录页",
        description="自定义登录页面，支持验证码、短信、邮箱验证",
        category="frontend",
        platform="web",
        file_patterns=["login.vue", "index.js", "apaas.json"],
        required_conventions=[
            "需配置SSO重定向URL",
            "通过env.tmpl.js获取window.GLOBAL_ENV",
            "登录后跳转/app/callback/apaas/index.html",
        ],
    ),
    SceneType.WEB_PLUGIN: SceneInfo(
        type=SceneType.WEB_PLUGIN,
        name="Web端自开发插件",
        description="自定义平台扩展插件，遵循 FRONTEND_PLUGIN 协议并基于 ExtensionEngine/HookManager 扩展能力",
        category="frontend",
        platform="web",
        file_patterns=["admin.js", "app.js", "mobile.js", "extension.js", "tab-config.js", "*.vue", "apaas.json", "plugin-local/index.js"],
        required_conventions=[
            "apaas.json 中 templateType 必须是 FRONTEND_PLUGIN",
            "admin.js/app.js/mobile.js 需默认导出 install/activate/staticComponents",
            "使用 Vue._extensionEngine.registerExtensionConfig() 或宿主注入的 HookManager 扩展能力",
            "支持i18n国际化注册",
            "静态组件必须包含稳定 name",
        ],
    ),
    SceneType.MOBILE_COMPONENT: SceneInfo(
        type=SceneType.MOBILE_COMPONENT,
        name="移动端自开发组件",
        description="移动端表单中使用的自定义Vue组件",
        category="frontend",
        platform="mobile",
        file_patterns=["*.config.js", "edit/*.vue", "read/*.vue", "index.js", "apaas.json"],
        required_conventions=[
            "必须使用FormWidgetConfigMixin",
            "基础组件库使用cube-ui",
            "需同时有Web端自开发组件包",
        ],
    ),
    SceneType.MOBILE_PAGE: SceneInfo(
        type=SceneType.MOBILE_PAGE,
        name="移动端自开发页面",
        description="移动端完整的自定义页面",
        category="frontend",
        platform="mobile",
        file_patterns=["page.vue", "index.js", "apaas.json"],
        required_conventions=[
            "路由必须以apaas-custom-开头",
            "基础组件库使用cube-ui",
        ],
    ),
    SceneType.BACKEND_API: SceneInfo(
        type=SceneType.BACKEND_API,
        name="后端自开发接口",
        description="SpringBoot后端自定义接口服务",
        category="backend",
        platform="server",
        file_patterns=["*Controller.java", "*Service.java", "*AllowUrlConfig.java", "pom.xml"],
        required_conventions=[
            "包名前缀必须是com.xdap",
            "接口路径必须以/custom开头",
            "需实现AllowUrlManage接口注册白名单",
            "打包使用-P lib参数",
        ],
    ),
    SceneType.SCRIPT_JS: SceneInfo(
        type=SceneType.SCRIPT_JS,
        name="JavaScript脚本扩展",
        description="业务事件中的前端JavaScript脚本",
        category="script",
        platform="web",
        file_patterns=["script.js"],
        required_conventions=[
            "通过lowCodeContext.businessEventEngine获取数据",
            "必须返回对象{}或对象数组[{},{}]",
        ],
    ),
    SceneType.SCRIPT_PYTHON: SceneInfo(
        type=SceneType.SCRIPT_PYTHON,
        name="Python脚本扩展",
        description="业务事件中的后端Python脚本",
        category="script",
        platform="server",
        file_patterns=["script.py"],
        required_conventions=[
            "使用definesys模块",
            "输入用definesys.input()",
            "返回字典类型",
        ],
    ),
    SceneType.SCRIPT_GROOVY: SceneInfo(
        type=SceneType.SCRIPT_GROOVY,
        name="Groovy脚本扩展",
        description="业务事件中的后端Groovy脚本",
        category="script",
        platform="server",
        file_patterns=["script.groovy"],
        required_conventions=[
            "通过xdapEventSystemFunctions获取数据",
            "字段key前缀为bof_code_",
        ],
    ),
    SceneType.BUSINESS_DIALOG: SceneInfo(
        type=SceneType.BUSINESS_DIALOG,
        name="业务事件自定义弹窗",
        description="表单提交时的二次确认或信息采集弹窗",
        category="frontend",
        platform="web",
        file_patterns=["dialog-template.vue"],
        required_conventions=[
            "language固定为Vue",
            "通过lowCodeContext.businessEventEngine.confirmEventEmit确认",
            "通过lowCodeContext.businessEventEngine.cancelEventEmit取消",
            "支持modalOptions配置弹窗样式",
        ],
    ),
    SceneType.UI_STYLE: SceneInfo(
        type=SceneType.UI_STYLE,
        name="界面样式扩展",
        description="通过CSS调整表单/列表的界面样式",
        category="frontend",
        platform="web",
        file_patterns=["style.css"],
        required_conventions=[
            "CSS在.form-custom-style作用域内",
            "可用data-component-id定位特定组件",
        ],
    ),
    SceneType.LIST_CUSTOM_MODULE: SceneInfo(
        type=SceneType.LIST_CUSTOM_MODULE,
        name="列表自定义模块",
        description="在列表页面中嵌入自定义展示模块",
        category="frontend",
        platform="web",
        file_patterns=["module-template.vue", "module-style.scss"],
        required_conventions=[
            "通过lowCodeContext.pageViewConfig获取页面数据",
            "脚本代码使用Vue/HTML语法",
            "样式代码使用SCSS",
        ],
    ),
}


def get_scene(scene_type: SceneType) -> SceneInfo:
    return SCENE_REGISTRY[scene_type]


def get_scenes_by_category(category: str) -> List[SceneInfo]:
    return [s for s in SCENE_REGISTRY.values() if s.category == category]


def get_all_scenes() -> List[SceneInfo]:
    return list(SCENE_REGISTRY.values())
