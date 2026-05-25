"""dev_scene_spec — 自开发场景 SPEC 单一来源（给 外部 agent / dev-coding skill 消费）。

设计原则
========
1. **不重复 vibe_agent prompt**：vibe_agent 写代码用的完整 workflow / critical rules
   仍在 `coding/vibe_agent.py::_build_prompt()` 里，那是给执行层用的。本文件输出的
   是"场景 brief"——给协调层（外部 agent）做需求理解、用户确认、参数收集用。
2. **不动现有代码**：scenes.py SCENE_REGISTRY / vibe_agent prompt / workspace 脚手架都
   保持原样。本文件只**读** scenes.py，整合一份给 MCP 工具用。
3. **跟 ProjectType 对齐**：scene_type 字段直接复用 `coding.workspace.ProjectType`
   的字符串值（form-component-dual / form-page / backend-api ...），create_workspace
   能直接用。

调用方
======
- `mcp_server.list_dev_scenes()` → list_scene_briefs() 返回精简列表
- `mcp_server.get_dev_scene_spec(scene_type)` → get_scene_brief(scene_type) 返回详情
- skill prompt 自己拼"场景识别提示"时可直接 import keyword_match()
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


SPEC_VERSION = "2026-05-07"


@dataclass
class SceneBrief:
    """给 外部 agent 用的场景简介（非 vibe_agent 系统提示）。"""

    # ── 标识 ──
    scene_type: str            # 与 ProjectType 枚举值一致
    name: str                  # 中文显示名（用户看到的）
    one_liner: str             # 一句话描述
    category: str              # frontend / backend
    platform: str              # web / mobile / both / server

    # ── 场景识别 ──
    keywords: list[str]        # 关键词命中规则（用于 agent 简单分类）
    when_to_use: list[str]     # 适用场景描述（自然语言）
    when_NOT_to_use: list[str] = field(default_factory=list)

    # ── 用户协作 ──
    user_inputs_needed: list[str] = field(default_factory=list)   # 必须问用户拿的输入
    user_inputs_optional: list[str] = field(default_factory=list) # 可选

    # ── 预期产出 ──
    file_outline: list[str] = field(default_factory=list)         # 大致会写哪些文件
    typical_duration_min: tuple[int, int] = (3, 8)                # 预估完成时间（分钟）

    # ── 关键提醒（给用户的友好提示，不是内部规则）──
    critical_warnings: list[str] = field(default_factory=list)

    # ── 部署能力 ──
    publishable: bool = True
    publish_target: str = "aPaaS 平台"
    build_command_hint: str = "npm run build"  # 让 外部 agent 知道大概要等多久

    def to_dict(self) -> dict:
        d = asdict(self)
        d["typical_duration_min"] = list(self.typical_duration_min)
        return d


# ─────────────────────── 场景注册表 ───────────────────────


_SCENE_BRIEFS: dict[str, SceneBrief] = {
    "form-component-dual": SceneBrief(
        scene_type="form-component-dual",
        name="自开发表单组件（双端 PC+移动）",
        one_liner="同时支持 PC 和移动端的自定义表单字段组件，会生成 14 个 scene vue + setting + widget config",
        category="frontend",
        platform="both",
        keywords=[
            "表单组件", "自开发组件", "自定义组件", "字段组件",
            "评分", "进度条", "百分比", "签名", "图片选择", "上传",
            "form-component", "widget", "form widget",
        ],
        when_to_use=[
            "用户要在表单里加一个平台没提供的输入字段类型",
            "需要双端（PC + 移动）都支持的字段控件",
            "现有 BOF 类型不够用，需要自定义渲染 + 自定义 setting 面板",
        ],
        when_NOT_to_use=[
            "只是页面展示（用 form-page）",
            "纯 PC，不需要移动端（仍走 form-component-dual，移动端 vue 写空壳即可）",
            "改现有平台组件的样式（用 layout 或 plugin）",
        ],
        user_inputs_needed=[
            "组件中文名（如：评分、进度条）",
            "字段值类型（数字 / 字符串 / 数组）",
            "PC 端展示形式（输入框 / 下拉 / 自绘）",
            "是否需要 setting 面板让用户配参数",
        ],
        user_inputs_optional=[
            "移动端展示是否同 PC（默认同款）",
            "Print 模式（打印态）样式",
        ],
        file_outline=[
            "shared/widget.config.json（双端唯一配置源）",
            "web/src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/*.vue（7 个）",
            "mobile/src/form-component/form-widget/{...}/*.vue（7 个）",
            "web/src/form-component/form-editor/setting.vue + editor.config.json",
            "web/src/form-component/form-editor/index.js + form-component-config/form-editor/index.js",
        ],
        typical_duration_min=(5, 12),
        critical_warnings=[
            "Scene vue 读配置必须用 this.widget.customComponentConfig（不是 this.customComponentConfig）；setting.vue 用 this.componentConfig.customComponentConfig。混用会静默失效。",
            "Print 模式禁止使用 <el-xxx>（Element UI 在打印态不渲染），用纯 HTML/CSS。",
            "Search 模式 emit 必须 wrap 数组：this.$emit('change', [value])。",
            "禁止在 form widget 里用 <el-dialog>——会破坏 FormEngine。改用 <el-popover :append-to-body=\"true\">。",
        ],
    ),
    "form-page": SceneBrief(
        scene_type="form-page",
        name="自开发菜单页面（PC）",
        one_liner="完整的 Web 自定义页面，作为应用菜单项被访问，可调平台 API 渲染任意业务",
        category="frontend",
        platform="web",
        keywords=[
            "页面", "菜单页", "看板", "首页", "数据看板", "dashboard",
            "form-page", "menu-page", "应用页面", "自开发页面",
        ],
        when_to_use=[
            "需要一个独立菜单进入的完整页面（看板 / 数据查询 / 业务工作台）",
            "页面要调平台多个表单/字典做组合查询、图表展示",
            '用户口语"做一个 XXX 页面"时——默认走这条',
        ],
        when_NOT_to_use=[
            "只是表单内的字段控件（用 form-component-dual）",
            "列表的特殊渲染（用 form-list）",
            "整个应用的布局框架（用 layout）",
        ],
        user_inputs_needed=[
            "页面中文名（如：首页看板、订单分析）",
            "页面要调哪些应用 / 表单的数据（appId、formId）",
            "核心功能（筛选条件、展示组件、是否带分页等）",
        ],
        user_inputs_optional=[
            "是否支持弹窗 getSelectedData",
            "需不需要图表（柱状/饼图/折线）",
        ],
        file_outline=[
            "src/page.vue（主页面）",
            "src/index.js（注册组件名 apaas-custom-xxx）",
            "src/api/index.js（接口封装）",
            "apaas.json（templateType=PAGE_CUSTOM_DEV）",
        ],
        typical_duration_min=(3, 8),
        critical_warnings=[
            "组件名/路由必须以 apaas-custom- 开头（平台扫描规则）。",
            "网络请求用 this.$request({...}).asyncThen().asyncErrorCatch()，**不是** Promise.then/.catch。",
            "console.log 在生产构建会被剥离，调试用 console.info。",
        ],
    ),
    "form-list": SceneBrief(
        scene_type="form-list",
        name="自开发列表视图",
        one_liner="自定义列表展示方式（卡片 / 时间轴 / 看板），基于 ListEngine",
        category="frontend",
        platform="web",
        keywords=["列表", "卡片视图", "看板视图", "时间轴", "list-view", "form-list"],
        when_to_use=[
            "默认表格列表不够用，要换成卡片 / 看板 / 时间轴",
            "列表里要 inline 渲染特殊字段（图片墙、进度条等）",
        ],
        when_NOT_to_use=[
            "只是改表格里的某一列（直接用 form-component-dual）",
            "完整页面布局（用 layout）",
        ],
        user_inputs_needed=[
            "列表展示形式（卡片/看板/时间轴/瀑布流）",
            "每个 item 显示哪些字段",
            "点击行为（弹窗 / 跳转）",
        ],
        file_outline=[
            "src/custom-list-view.vue",
            "src/index.js（templateType=LIST_VIEW）",
            "apaas.json（含 list 字段和 renderLogic）",
        ],
        typical_duration_min=(3, 6),
        critical_warnings=[
            "必须接收 listEngine 参数（mixin 提供数据 / 分页 / 选中态）。",
        ],
    ),
    "layout": SceneBrief(
        scene_type="layout",
        name="自定义应用布局",
        one_liner="覆盖整个应用的外框布局（header / 菜单 / 内容区 slot）",
        category="frontend",
        platform="web",
        keywords=["布局", "应用布局", "外框", "layout", "PAGE_LAYOUT"],
        when_to_use=[
            "要改整个应用的 header / 侧边菜单 / footer",
            "需要在所有页面外部加统一的水印 / 提示条",
        ],
        when_NOT_to_use=[
            "只改某个页面（用 form-page）",
            "要嵌平台外的 iframe（用 plugin）",
        ],
        user_inputs_needed=[
            "顶部要保留哪些（用户头像、通知、应用切换）",
            "侧边菜单样式（折叠 / 多级 / 图标）",
            "内容区是否有 padding / 背景色",
        ],
        file_outline=[
            "src/layout.vue（主布局）",
            "src/index.js（templateType=PAGE_LAYOUT）",
            "apaas.json",
        ],
        typical_duration_min=(3, 6),
        critical_warnings=[
            "appPage 必须用 <slot name=\"appPage\"> 转发平台内容，不能写死。",
            "templateType 必须保持 PAGE_LAYOUT。",
        ],
    ),
    "plugin": SceneBrief(
        scene_type="plugin",
        name="自开发前端插件",
        one_liner="平台扩展插件，遵循 FRONTEND_PLUGIN 协议，注入 admin/app/mobile 能力",
        category="frontend",
        platform="web",
        keywords=["插件", "扩展", "plugin", "frontend-plugin", "extension"],
        when_to_use=[
            "需要在平台 admin 后台 / 应用前台 / 移动端注入额外能力",
            "需要复用平台 ExtensionEngine / HookManager 钩子",
        ],
        when_NOT_to_use=[
            "只是一个独立菜单页面（用 form-page）",
        ],
        user_inputs_needed=[
            "插件作用范围（admin / app / mobile）",
            "要扩展的能力点（菜单 / 工具栏 / 表单事件 hook）",
        ],
        file_outline=[
            "src/admin.js / src/app.js / src/mobile.js（按需）",
            "src/extension.js（HookManager 注册）",
            "apaas.json（templateType=FRONTEND_PLUGIN）",
        ],
        typical_duration_min=(4, 10),
        critical_warnings=[
            "templateType 必须是 FRONTEND_PLUGIN。",
            "每个 entry 文件必须 default-export { install, activate, staticComponents }。",
            "静态组件必须包含稳定 name。",
        ],
    ),
    "mobile-page": SceneBrief(
        scene_type="mobile-page",
        name="移动端自开发页面",
        one_liner="移动端独立页面（cube-ui 基础组件库）",
        category="frontend",
        platform="mobile",
        keywords=["移动端页面", "h5", "mobile", "cube-ui"],
        when_to_use=[
            "纯移动端独立页面，PC 端不需要",
        ],
        user_inputs_needed=[
            "页面中文名",
            "目标功能",
        ],
        file_outline=["src/page.vue", "src/index.js", "apaas.json"],
        typical_duration_min=(3, 6),
        critical_warnings=[
            "基础组件库用 cube-ui（不是 element-ui）。",
            "路由以 apaas-custom- 开头。",
        ],
    ),
    "web-login": SceneBrief(
        scene_type="web-login",
        name="自定义登录页",
        one_liner="替换平台默认登录页（账密 / 验证码 / 短信 / 邮箱 / SSO）",
        category="frontend",
        platform="web",
        keywords=["登录页", "login", "登录", "认证页面"],
        when_to_use=[
            "客户要换成自家品牌的登录页",
            "需要接 SSO / 企业微信 / 钉钉登录",
        ],
        user_inputs_needed=[
            "登录方式（账密 / 验证码 / 短信 / 邮箱 / SSO）",
            "品牌色 / logo / 背景图",
            "登录成功跳转到哪",
        ],
        file_outline=["src/login.vue", "src/index.js", "apaas.json"],
        typical_duration_min=(3, 6),
        critical_warnings=[
            "需配 SSO 重定向 URL（env.tmpl.js 取 window.GLOBAL_ENV）。",
            "登录后跳转 /app/callback/apaas/index.html。",
        ],
    ),
    "backend-api": SceneBrief(
        scene_type="backend-api",
        name="后端自开发接口",
        one_liner="SpringBoot Controller + Service，部署到平台后端 lib 目录",
        category="backend",
        platform="server",
        keywords=["后端接口", "API", "Controller", "Service", "Java", "SpringBoot", "backend-api"],
        when_to_use=[
            "前端调一个平台没有的业务接口",
            "需要做平台 BOF 之外的复杂业务逻辑（事务 / 第三方对接 / 大数据量计算）",
        ],
        when_NOT_to_use=[
            "调外部 HTTP API（用 backend-feign）",
            "定时跑任务（用 backend-scheduled）",
        ],
        user_inputs_needed=[
            "接口路径（必须 /custom/ 开头）",
            "入参 / 出参 DTO 字段",
            "业务逻辑描述",
            "是否走数据库（哪些表）",
        ],
        file_outline=[
            "src/main/java/com/xdap/.../XxxController.java",
            "src/main/java/com/xdap/.../XxxService.java",
            "src/main/java/com/xdap/.../config/XxxAllowUrlConfig.java（白名单）",
            "pom.xml",
        ],
        typical_duration_min=(5, 15),
        build_command_hint="mvn -P lib -DskipTests package",
        critical_warnings=[
            "包名必须 com.xdap 开头。",
            "接口路径必须 /custom/ 开头。",
            "需实现 AllowUrlManage 注册白名单。",
            "打包必须带 -P lib 参数。",
        ],
    ),
    "backend-feign": SceneBrief(
        scene_type="backend-feign",
        name="后端 FeignClient 外部调用",
        one_liner="通过 FeignClient 接外部 HTTP API，含 DTO + 配置类",
        category="backend",
        platform="server",
        keywords=["Feign", "FeignClient", "外部API", "外部调用", "HTTP 调用"],
        when_to_use=[
            "后端要调第三方 API（钉钉 / 企微 / 银行 / ERP）",
            "需要统一管理外部接口认证 / 重试 / 超时",
        ],
        user_inputs_needed=[
            "外部 API base URL（写到 application.yml）",
            "认证方式（API Key / OAuth / 签名）",
            "要调的接口路径 + 入参出参",
        ],
        file_outline=[
            "src/main/java/com/xdap/.../XxxFeignClient.java",
            "src/main/java/com/xdap/.../dto/*.java",
            "src/main/java/com/xdap/.../config/XxxFeignConfig.java",
            "pom.xml",
        ],
        typical_duration_min=(5, 12),
        build_command_hint="mvn -P lib -DskipTests package",
        critical_warnings=[
            "包名必须 com.xdap 开头。",
            "@FeignClient 的 url 从 application.yml 读，不写死。",
            "DTO 字段名跟外部 API 保持一致。",
            "FeignConfig 处理认证头（拦截器）。",
        ],
    ),
    "backend-scheduled": SceneBrief(
        scene_type="backend-scheduled",
        name="后端定时任务",
        one_liner="@Scheduled 注解的定时任务，结合 MpaaS 数据源",
        category="backend",
        platform="server",
        keywords=["定时任务", "scheduled", "cron", "调度", "定时"],
        when_to_use=[
            "需要定时跑业务逻辑（每天清账 / 每小时同步 / 节点保活）",
            "需要异步批量处理数据",
        ],
        user_inputs_needed=[
            "执行频率（cron 表达式或人话）",
            "任务做什么",
            "是否要操作数据库（哪些表）",
        ],
        file_outline=[
            "src/main/java/com/xdap/.../XxxScheduledTask.java",
            "src/main/java/com/xdap/.../XxxService.java",
            "src/main/java/com/xdap/.../dao/XxxDao.java",
            "pom.xml",
        ],
        typical_duration_min=(5, 12),
        build_command_hint="mvn -P lib -DskipTests package",
        critical_warnings=[
            "包名必须 com.xdap 开头。",
            "@EnableScheduling 标注在 Application 启动类。",
            "MpaaS 数据库操作走 DatasourceUtil + MpaasQuery 规范。",
            "cron 表达式注意时区（默认服务器时区）。",
        ],
    ),
}


# 给 外部 agent 用的关键词索引（场景识别 fallback 提示，不强制）
def keyword_match(text: str) -> list[str]:
    """简单关键词命中：返回可能匹配的 scene_type 列表（按命中度降序）。

    外部 agent 拿到用户输入后，可以先调本函数拿候选场景，再问用户确认；
    若一个都不匹配，回退到 LLM 分类（让外部 agent 自己判断）。
    """
    if not text:
        return []
    t = text.lower()
    scored: list[tuple[int, str]] = []
    for scene_type, brief in _SCENE_BRIEFS.items():
        hits = sum(1 for kw in brief.keywords if kw.lower() in t)
        if hits:
            scored.append((hits, scene_type))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored]


# ─────────────────────── 公共 API ───────────────────────


def list_scene_briefs() -> list[dict]:
    """返回所有场景的精简列表（给 list_dev_scenes MCP 工具用）。

    精简版只含选场景必要字段，详情走 get_scene_brief。
    """
    return [
        {
            "scene_type": b.scene_type,
            "name": b.name,
            "one_liner": b.one_liner,
            "category": b.category,
            "platform": b.platform,
            "keywords": b.keywords,
            "typical_duration_min": list(b.typical_duration_min),
        }
        for b in _SCENE_BRIEFS.values()
    ]


def get_scene_brief(scene_type: str) -> Optional[dict]:
    """返回单个场景的完整 brief（给 get_dev_scene_spec MCP 工具用）。"""
    brief = _SCENE_BRIEFS.get(scene_type)
    if brief is None:
        return None
    return brief.to_dict()


def all_scene_types() -> list[str]:
    """供 MCP 工具校验入参用。"""
    return list(_SCENE_BRIEFS.keys())


def build_external_skill_section() -> str:
    """生成 skill markdown 里"场景索引"那一段（人话，给 LLM 看的）。

    skill 静态 prompt 不用复制全部场景细节——告诉 agent "调 list_dev_scenes 拿索引、
    调 get_dev_scene_spec 拿详情" 就够了。这个函数只在需要时手动生成一段速查表。
    """
    lines = ["| 场景类型 | 中文名 | 一句话 | 关键词 |", "|---|---|---|---|"]
    for b in _SCENE_BRIEFS.values():
        kw_short = "、".join(b.keywords[:5])
        lines.append(f"| `{b.scene_type}` | {b.name} | {b.one_liner} | {kw_short} |")
    return "\n".join(lines)


__all__ = [
    "SPEC_VERSION",
    "SceneBrief",
    "list_scene_briefs",
    "get_scene_brief",
    "all_scene_types",
    "keyword_match",
    "build_external_skill_section",
]
