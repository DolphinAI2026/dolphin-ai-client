"""
开发场景定义 - 定义所有支持的aPaaS自开发场景
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel


class SceneType(str, Enum):
    """自开发场景类型"""
    WEB_COMPONENT_DUAL = "web_component_dual" # 双端自开发组件（PC + 移动端，所有组件统一走双端）
    WEB_PAGE = "web_page"                     # Web端自开发页面
    WEB_LIST_VIEW = "web_list_view"           # Web端自开发列表视图
    WEB_LAYOUT = "web_layout"                 # Web端自定义布局
    WEB_LOGIN = "web_login"                   # Web端自定义登录页
    WEB_PLUGIN = "web_plugin"                 # Web端自开发插件
    MOBILE_PAGE = "mobile_page"               # 移动端自开发页面
    BACKEND_API = "backend_api"               # 后端自开发接口
    BACKEND_FEIGN = "backend_feign"           # 后端外部调用（FeignClient）
    BACKEND_SCHEDULED = "backend_scheduled"   # 后端定时任务


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
    SceneType.WEB_COMPONENT_DUAL: SceneInfo(
        type=SceneType.WEB_COMPONENT_DUAL,
        name="双端自开发组件（PC + 移动端）",
        description="同时支持PC端和移动端的自定义表单组件，PC使用element-ui，移动端使用cube-ui，共享widget.config和业务逻辑",
        category="frontend",
        platform="both",
        file_patterns=[
            "shared/widget.config.json",
            "shared/mixin/*.js",
            "web/src/form-component/**/*.vue",
            "mobile/src/form-component/**/*.vue",
        ],
        required_conventions=[
            "shared/widget.config.json 为双端唯一配置来源",
            "PC端组件名 FormComponentXxxEdit，移动端 MobileFormComponentXxxEdit",
            "web/ 使用 element-ui（el-*），mobile/ 使用 cube-ui",
            "shared/ 内部引用使用相对路径，不使用 @/",
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
    SceneType.BACKEND_FEIGN: SceneInfo(
        type=SceneType.BACKEND_FEIGN,
        name="后端外部调用（FeignClient）",
        description="通过 FeignClient 调用外部 HTTP 接口，含接口定义、请求/响应 DTO、配置类",
        category="backend",
        platform="server",
        file_patterns=["*FeignClient.java", "*DTO.java", "*FeignConfig.java", "pom.xml"],
        required_conventions=[
            "包名前缀必须是com.xdap",
            "使用 @FeignClient 注解，url 从 application.yml 读取",
            "DTO 字段与外部 API 保持一致",
            "需配置 FeignConfig 处理认证头",
        ],
    ),
    SceneType.BACKEND_SCHEDULED: SceneInfo(
        type=SceneType.BACKEND_SCHEDULED,
        name="后端定时任务",
        description="基于 Spring @Scheduled 的定时任务，含 MpaaS 数据库操作",
        category="backend",
        platform="server",
        file_patterns=["*ScheduledTask.java", "*Service.java", "*Dao.java", "pom.xml"],
        required_conventions=[
            "包名前缀必须是com.xdap",
            "使用 @Scheduled(cron=...) 配置执行周期",
            "MpaaS 数据库操作遵循 DatasourceUtil + MpaasQuery 规范",
            "@EnableScheduling 标注在 Application 启动类",
        ],
    ),
}


def get_scene(scene_type: SceneType) -> SceneInfo:
    return SCENE_REGISTRY[scene_type]


def get_scenes_by_category(category: str) -> List[SceneInfo]:
    return [s for s in SCENE_REGISTRY.values() if s.category == category]


def get_all_scenes() -> List[SceneInfo]:
    return list(SCENE_REGISTRY.values())
