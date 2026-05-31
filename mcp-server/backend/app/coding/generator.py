"""
代码生成器 — 场景检测 + 辅助功能。
旧的 generate / generate_stream（基于 scene prompt 的一次性代码生成）已清理，
代码生成统一走 VibeCodingAgent。
"""

import logging
from typing import Optional

from app.coding.scenes import SceneType
from app.llm_client import LLMClient

logger = logging.getLogger(__name__)


class CodingGenerator:
    """aPaaS 自开发 — 场景检测 & LLM 客户端入口"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    async def detect_scene(self, user_input: str) -> SceneType:
        """根据用户输入自动识别开发场景"""
        system_prompt = """你是aPaaS低代码平台的场景分类助手。根据用户的开发需求，从以下场景中选择最匹配的一个，**只输出场景代码，不要任何解释**。

## 场景定义

### 前端 Web 类
- **web_page**：在应用菜单中独立访问的完整业务页面。
  典型形态：数据查询页面、图表分析页面、报表页面、管理列表页、看板、大屏、仪表盘、自开发菜单页面。
  技术特征：有独立路由、完整页面结构（Vue 页面组件 + index.js + apaas.json），可使用 this.$request 调接口。

- **web_component_dual**：嵌入在低代码表单字段中的可复用 UI 控件（双端：PC + 移动端），所有组件类需求统一走此场景。
  典型形态：自定义选择器、日期范围组件、文件上传控件、富文本编辑器、自定义输入框、数据关联选择控件。
  技术特征：三层目录结构 shared/ + web/ + mobile/，shared 层共享 widget.config 与业务逻辑，web 使用 element-ui，mobile 使用 cube-ui。

- **web_list_view**：自定义列表视图，嵌入在列表页中替换默认展示方式（基于 ListEngine），不是独立页面。

- **web_layout**：自定义应用整体布局结构（基于 LayoutEngine），如自定义顶导、侧边栏。

- **web_login**：自定义登录页，替换平台默认登录界面。

- **web_plugin**：平台扩展插件，通过 ExtensionEngine/HookManager 扩展平台能力。

### 移动端类
- **mobile_page**：移动端独立页面（使用 cube-ui 组件库）。

### 后端 Java 类
- **backend_api**：开发 SpringBoot/Java 后端 REST 接口（Controller + Service），接口路径以 /custom 开头，包名以 com.xdap 开头。注意：前端页面"调用接口"不属于此类。
- **backend_feign**：用 FeignClient 调用外部 HTTP 服务，含接口定义、DTO、FeignConfig。
- **backend_scheduled**：Spring @Scheduled 定时任务，含 ScheduledTask.java + Dao + Service。

## 关键区分原则

**web_page vs web_component_dual**（最常见混淆）：
- "页面/菜单页面/自开发页面/查询页面/分析页面/报表/看板/大屏" → **web_page**
- "组件/控件/选择器/输入框/自开发组件/表单组件" → **web_component_dual**
- 图表、表格出现在"页面"语境中 → **web_page**（图表页面是完整页面，不是组件）

**backend_api vs web_page**：
- 用户要"开发接口/写后端/SpringBoot/Java Controller" → **backend_api**
- 用户要"做一个页面，页面里调用接口" → **web_page**（接口调用是前端行为）

## 示例

用户需求 → 场景代码
"创建一个项目分析图表自开发页面" → web_page
"做一个数据看板页面" → web_page
"开发一个员工查询菜单页面" → web_page
"做一个自定义日期范围选择器" → web_component_dual
"开发一个关联数据选择组件" → web_component_dual
"写一个员工信息展示的富文本输入框" → web_component_dual
"开发一个 SpringBoot 接口查询订单数据" → backend_api
"用 FeignClient 调用外部天气 API" → backend_feign
"每天凌晨同步一次数据，定时任务" → backend_scheduled"""

        response = await self.llm_client.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户需求：{user_input}"},
            ],
            max_tokens=20,
            temperature=0,
        )
        scene_code = response["choices"][0]["message"]["content"].strip().lower()
        # 清理可能的多余文本
        scene_code = scene_code.split("\n")[0].strip().strip("`").strip('"').strip("'")

        try:
            return SceneType(scene_code)
        except ValueError:
            # 默认返回Web组件
            logger.warning(f"无法识别场景 '{scene_code}'，默认使用 web_component_dual")
            return SceneType.WEB_COMPONENT_DUAL
