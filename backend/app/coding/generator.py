"""
代码生成器 - 基于LLM生成符合aPaaS规范的自开发代码
"""

import re
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional, Any

from app.coding.scenes import SceneType, get_scene
from app.coding.prompts import get_scene_prompt, CODE_GENERATION_INSTRUCTION
from app.coding.validator import validate_generated_code
from app.llm_client import LLMClient

logger = logging.getLogger(__name__)


class GeneratedFile:
    """生成的代码文件"""
    def __init__(self, path: str, content: str, language: str = ""):
        self.path = path
        self.content = content
        self.language = language or self._detect_language(path)

    def _detect_language(self, path: str) -> str:
        ext_map = {
            ".vue": "vue", ".js": "javascript", ".ts": "typescript",
            ".json": "json", ".css": "css", ".scss": "scss",
            ".java": "java", ".py": "python", ".groovy": "groovy",
            ".xml": "xml", ".html": "html",
        }
        for ext, lang in ext_map.items():
            if path.endswith(ext):
                return lang
        return "text"


class CodeGenerationResult:
    """代码生成结果"""
    def __init__(self):
        self.files: List[GeneratedFile] = []
        self.explanation: str = ""
        self.scene_type: Optional[SceneType] = None
        self.validation_errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": [
                {"path": f.path, "content": f.content, "language": f.language}
                for f in self.files
            ],
            "explanation": self.explanation,
            "scene_type": self.scene_type.value if self.scene_type else None,
            "validation_errors": self.validation_errors,
        }


def parse_files_from_response(response_text: str) -> List[GeneratedFile]:
    """从LLM响应中解析文件内容

    支持格式:
    ```file:path/to/file.ext
    content
    ```
    或:
    ```language:path/to/file.ext
    content
    ```
    """
    files = []
    # 匹配 ```file:路径 或 ```language:路径 格式的代码块
    pattern = r'```(?:file|[\w]+):([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, response_text, re.DOTALL)

    for path, content in matches:
        path = path.strip()
        content = content.strip()
        if path and content:
            files.append(GeneratedFile(path=path, content=content))

    # 如果上面没匹配到，尝试更宽松的匹配
    if not files:
        # 匹配带文件名注释的代码块
        pattern2 = r'(?://|#|<!--)\s*(?:文件|File)[:：]\s*([^\n]+?)\s*(?:-->)?\n```\w*\n(.*?)```'
        matches2 = re.findall(pattern2, response_text, re.DOTALL)
        for path, content in matches2:
            path = path.strip()
            content = content.strip()
            if path and content:
                files.append(GeneratedFile(path=path, content=content))

    return files


class CodingGenerator:
    """aPaaS自开发代码生成器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def _build_messages(
        self,
        scene_type: SceneType,
        user_requirement: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        app_context: Optional[Dict[str, Any]] = None,
        workspace_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """构建LLM消息列表"""
        system_prompt = get_scene_prompt(scene_type)
        system_prompt += CODE_GENERATION_INSTRUCTION

        # 如果有应用上下文（来自builder-ai），添加到prompt
        if app_context:
            context_str = "\n\n## 当前应用上下文\n"
            if app_context.get("app_name"):
                context_str += f"- 应用名称: {app_context['app_name']}\n"
            if app_context.get("app_id"):
                context_str += f"- 应用ID: {app_context['app_id']}\n"
            if app_context.get("models"):
                context_str += f"- 数据模型: {json.dumps(app_context['models'], ensure_ascii=False)}\n"
            if app_context.get("forms"):
                context_str += f"- 表单列表: {json.dumps(app_context['forms'], ensure_ascii=False)}\n"
            if app_context.get("dicts"):
                context_str += f"- 数据字典: {json.dumps(app_context['dicts'], ensure_ascii=False)}\n"
            system_prompt += context_str

        # 如果有工作区上下文，告诉 AI 现有的文件结构和关键文件内容
        if workspace_context:
            ws_str = "\n\n## 当前工作区\n"
            ws_str += f"项目名: {workspace_context.get('project_name', '')}\n"
            ws_str += f"项目类型: {workspace_context.get('project_type', '')}\n\n"
            ws_str += "### 现有文件结构\n```\n"
            for fp in workspace_context.get("files", []):
                ws_str += f"{fp}\n"
            ws_str += "```\n\n"

            # 附带关键文件内容
            key_files = workspace_context.get("key_files", {})
            if key_files:
                ws_str += "### 关键文件内容\n"
                for fp, content in key_files.items():
                    ws_str += f"\n**{fp}**:\n```\n{content}\n```\n"

            ws_str += "\n### 重要规则（必须严格遵守）\n"
            ws_str += "- **禁止**尝试读取文件、调用工具、或说'让我先查看文件'。你已经拥有所有需要的信息(上面已提供关键文件内容)\n"
            ws_str += "- **直接输出代码**，使用 ```file:path 格式，path 必须是上面文件列表中已有的路径\n"
            ws_str += "- **必须修改现有脚手架文件**，不要创建新的目录结构\n"
            project_type = (workspace_context.get("project_type", "") or "").lower()
            if project_type in {"form-component", "mobile-component"}:
                ws_str += "- **必须输出所有7个场景的 .vue 组件文件**（edit、read、ide、list、print、search、search-ide）和 setting.vue\n"
                ws_str += "- **必须同时输出 widget.config.js**，根据组件用途设置正确的 componentModelField 和 frontBusinessObjectComponentType（日期类用 DATE，数字类用 NUMBER，文本类用 TEXT）\n"
                ws_str += "- edit/read/ide.vue 与 setting.vue 的 customComponentConfig 读写路径必须一致\n"
            elif project_type == "layout":
                ws_str += "- **布局项目通常只需要 Home.vue、index.js、apaas.json 以及必要的子组件**，不要套用表单组件的 7 场景规则\n"
                ws_str += "- **不要擅自新增 widget.config.js / editor.config.js / setting.vue**，除非用户明确要求且平台确有这套接入方式\n"
                ws_str += "- `templateType` 必须是 `PAGE_LAYOUT`，布局组件名必须以 `apaas-custom-` 开头\n"
                ws_str += "- `appPage` 区域必须通过 `<slot name=\"appPage\">` 转发平台页面内容\n"
            elif project_type in {"menu-page", "form-page", "mobile-page"}:
                ws_str += "- 页面项目只输出页面入口、页面组件和必要的 API/样式文件，不要套用组件的 7 场景规则\n"
            elif project_type == "form-list":
                ws_str += "- 列表视图项目应遵循 `LIST_VIEW` 协议，重点修改 apaas.json、index.js 和 form-view/*.vue\n"
                ws_str += "- 不要套用组件 7 场景规则，也不要生成 setting.vue / widget.config.js\n"
            elif project_type == "plugin":
                ws_str += "- 插件项目应遵循 `FRONTEND_PLUGIN` 协议，重点修改 admin.js/app.js/mobile.js、extension.js、tab-config.js\n"
                ws_str += "- 默认导出对象必须包含 install、activate、staticComponents\n"
            elif project_type in {"backend-api", "backend-feign", "backend-scheduled"}:
                ws_str += "- 后端项目输出 Java 文件（Controller/Service/Dao/DTO/Task 等）；不要输出 Vue 组件文件\n"
            ws_str += "- .vue / .java / .py 文件中不要留 TODO 占位符，要实现完整的功能逻辑\n"
            ws_str += "- **禁止修改 package.json 添加私有包**（如 babel-preset-definesys、df-apaas-cli 等）。如需第三方库（如 echarts），只能添加 npm 公共 registry 上的包\n"
            ws_str += "- 先用简短的一段话说明实现方案，然后立即开始输出代码文件\n"
            system_prompt += ws_str

        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话（智能截断，避免上下文爆炸）
        if conversation_history:
            messages.extend(
                self._truncate_history(conversation_history, has_workspace=workspace_context is not None)
            )

        messages.append({"role": "user", "content": user_requirement})
        return messages

    def _truncate_history(
        self,
        history: List[Dict[str, str]],
        has_workspace: bool = False,
        max_rounds: int = 6,
        max_assistant_chars: int = 500,
    ) -> List[Dict[str, str]]:
        """
        智能截断历史对话，防止上下文爆炸。

        策略：
        - 有工作区时：AI 的代码回复不需要保留（最新代码在 workspace_context 里），
          只保留用户消息 + AI 回复的摘要（去掉代码块）
        - 无工作区时：保留最近 max_rounds 轮完整对话
        - 每条 AI 回复最多 max_assistant_chars 字符
        """
        if not history:
            return []

        truncated = []

        if has_workspace:
            # 有工作区：只保留最近 max_rounds 轮，AI 回复去掉代码只留摘要
            import re
            # 按轮次配对 (user, assistant)
            rounds = []
            current_round = []
            for msg in history:
                current_round.append(msg)
                if msg["role"] == "assistant":
                    rounds.append(current_round)
                    current_round = []
            if current_round:
                rounds.append(current_round)

            # 只取最近 max_rounds 轮
            recent_rounds = rounds[-max_rounds:]

            for round_msgs in recent_rounds:
                for msg in round_msgs:
                    if msg["role"] == "user":
                        truncated.append(msg)
                    elif msg["role"] == "assistant":
                        content = msg["content"]
                        # 去掉代码块（```file:... ``` 和 ```lang ... ```）
                        summary = re.sub(r'```[\s\S]*?```', '[代码已省略，见工作区文件]', content)
                        # 截断过长的摘要
                        if len(summary) > max_assistant_chars:
                            summary = summary[:max_assistant_chars] + "...[截断]"
                        truncated.append({"role": "assistant", "content": summary})
                    else:
                        truncated.append(msg)
        else:
            # 无工作区：保留最近 max_rounds * 2 条消息
            truncated = history[-(max_rounds * 2):]

        return truncated

    async def generate(
        self,
        scene_type: SceneType,
        user_requirement: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        app_context: Optional[Dict[str, Any]] = None,
        workspace_context: Optional[Dict[str, Any]] = None,
    ) -> CodeGenerationResult:
        """非流式代码生成"""
        messages = self._build_messages(
            scene_type, user_requirement, conversation_history, app_context, workspace_context
        )

        response = await self.llm_client.chat_completion(
            messages, max_tokens=16384, temperature=0.2
        )

        content = response["choices"][0]["message"]["content"]
        result = CodeGenerationResult()
        result.scene_type = scene_type
        result.files = parse_files_from_response(content)
        result.explanation = self._extract_explanation(content)

        # 校验生成的代码
        scene_info = get_scene(scene_type)
        result.validation_errors = validate_generated_code(result.files, scene_info)

        return result

    async def generate_stream(
        self,
        scene_type: SceneType,
        user_requirement: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        app_context: Optional[Dict[str, Any]] = None,
        workspace_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """流式代码生成，返回SSE格式的数据块"""
        messages = self._build_messages(
            scene_type, user_requirement, conversation_history, app_context, workspace_context
        )

        full_response = ""
        async for chunk_data in self.llm_client.chat_completion_stream(messages):
            try:
                chunk = json.loads(chunk_data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_response += content
                    yield content
            except json.JSONDecodeError:
                continue

        # 流式结束后，解析并校验文件
        files = parse_files_from_response(full_response)
        scene_info = get_scene(scene_type)
        # 工作区模式下跳过校验（脚手架已包含 apaas.json 等必要文件）
        if workspace_context:
            errors = []
        else:
            errors = validate_generated_code(files, scene_info)

        # 发送解析结果
        result_meta = {
            "type": "generation_complete",
            "files": [{"path": f.path, "language": f.language} for f in files],
            "validation_errors": errors,
        }
        yield f"\n\n<!--GENERATION_META:{json.dumps(result_meta, ensure_ascii=False)}-->"

    async def detect_scene(self, user_input: str) -> SceneType:
        """根据用户输入自动识别开发场景"""
        detect_prompt = """根据用户的需求描述，判断属于以下哪种aPaaS自开发场景，只返回场景代码，不要其他内容：

- web_component: Web端自开发组件（表单组件、输入控件等）
- web_page: Web端自开发页面（菜单页面、弹窗页面、数据查询页面、完整页面、图表页面等，用户说"做一个XX页面"属于此类）
- web_list_view: Web端自开发列表视图（自定义列表展示）
- web_layout: Web端自定义布局
- web_login: Web端自定义登录页
- mobile_component: 移动端自开发组件
- mobile_page: 移动端自开发页面
- backend_api: 后端自开发接口（SpringBoot接口）
- backend_feign: 后端外部调用（FeignClient 调用外部 HTTP 接口）
- backend_scheduled: 后端定时任务（Spring @Scheduled 定时任务）
- script_js: JavaScript脚本扩展（业务事件JS脚本）
- script_python: Python脚本扩展（业务事件Python脚本）
- script_groovy: Groovy脚本扩展（业务事件Groovy脚本）
- business_dialog: 业务事件自定义弹窗
- ui_style: 界面样式扩展（CSS调整）
- list_custom_module: 列表自定义模块

用户需求: """ + user_input

        response = await self.llm_client.chat_completion(
            [{"role": "user", "content": detect_prompt}],
            max_tokens=50,
            temperature=0.1,
        )
        scene_code = response["choices"][0]["message"]["content"].strip().lower()
        # 清理可能的多余文本
        scene_code = scene_code.split("\n")[0].strip().strip("`").strip('"').strip("'")

        try:
            return SceneType(scene_code)
        except ValueError:
            # 默认返回Web组件
            logger.warning(f"无法识别场景 '{scene_code}'，默认使用 web_component")
            return SceneType.WEB_COMPONENT

    def _extract_explanation(self, content: str) -> str:
        """提取LLM回复中的说明文字（非代码部分）"""
        lines = content.split("\n")
        explanation_lines = []
        in_code_block = False
        for line in lines:
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if not in_code_block:
                explanation_lines.append(line)
        return "\n".join(explanation_lines).strip()
