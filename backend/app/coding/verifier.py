"""
ComponentVerifier - AI 驱动的组件截图验证
通过 LLM Vision 分析 debug 截图，判断组件是否正确渲染
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from app.llm_client import LLMClient
from app.coding.workspace import WorkspaceManager, WORKSPACE_ROOT

logger = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    passed: bool
    issues: str = ""
    fix_suggestion: str = ""
    screenshot_path: Optional[str] = None


class ComponentVerifier:
    def __init__(self):
        self.llm = LLMClient()
        self.ws_mgr = WorkspaceManager()

    async def analyze_screenshot(self, ws_id: str, requirement: str) -> VerifyResult:
        """Analyze debug screenshot with AI vision"""
        screenshot_path = WORKSPACE_ROOT / ws_id / "debug" / "screenshots" / "page.png"
        if not screenshot_path.exists():
            return VerifyResult(passed=False, issues="截图不存在，debug 可能失败")

        # Encode image
        image_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()

        # Build vision prompt
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"""你是一个 aPaaS 低代码平台的组件质量检查专家。

用户需求：{requirement}

请分析这张表单设计器的截图，检查自开发组件是否正确：
1. 组件是否出现在左侧"自开发组件"面板中？
2. 组件拖入表单后是否正常渲染（不是空白或报错）？
3. 组件的外观是否符合用户需求描述？

请用以下 JSON 格式回复：
{{"passed": true/false, "issues": "问题描述（如果有）", "fix_suggestion": "修复建议（如果有）"}}
只返回 JSON，不要其他内容。"""},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
            ]
        }]

        try:
            response = await self.llm.chat_completion_vision(messages)
            logger.info(f"[Verifier] AI response: {response[:200]}")

            # Try to extract JSON from response (may be wrapped in markdown code block)
            json_str = response.strip()
            if json_str.startswith("```"):
                # Remove markdown code fences
                lines = json_str.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.strip().startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block or not line.strip().startswith("```"):
                        json_lines.append(line)
                json_str = "\n".join(json_lines).strip()

            result = json.loads(json_str)
            return VerifyResult(
                passed=result.get("passed", False),
                issues=result.get("issues", ""),
                fix_suggestion=result.get("fix_suggestion", ""),
                screenshot_path=str(screenshot_path)
            )
        except json.JSONDecodeError:
            return VerifyResult(
                passed=False,
                issues=f"AI 分析结果解析失败: {response[:200]}",
                screenshot_path=str(screenshot_path)
            )
        except Exception as e:
            logger.error(f"[Verifier] Error: {e}")
            return VerifyResult(
                passed=False,
                issues=f"AI 验证异常: {str(e)}",
                screenshot_path=str(screenshot_path) if screenshot_path.exists() else None
            )

    async def auto_fix(self, ws_id: str, verify_result: VerifyResult, requirement: str) -> dict:
        """Based on verification issues, attempt to auto-fix the component code"""
        ws_path = WORKSPACE_ROOT / ws_id

        # Read current component source files
        src_dir = ws_path / "src"
        component_files = {}
        if src_dir.exists():
            for f in src_dir.rglob("*"):
                if f.is_file() and f.suffix in (".vue", ".js", ".ts", ".json", ".css", ".scss"):
                    rel = str(f.relative_to(ws_path))
                    try:
                        component_files[rel] = f.read_text(encoding="utf-8")
                    except Exception:
                        pass

        if not component_files:
            return {"fixed": False, "message": "没有找到组件源文件"}

        # Build fix prompt
        files_context = "\n".join(
            f"--- {path} ---\n{content}\n"
            for path, content in component_files.items()
        )

        fix_prompt = f"""你是 aPaaS 低代码平台的自开发组件专家。

当前组件存在以下问题：
{verify_result.issues}

修复建议：
{verify_result.fix_suggestion}

用户原始需求：
{requirement}

当前组件代码：
{files_context}

请修复代码中的问题，只返回需要修改的文件。格式：
```file:文件路径
修复后的完整文件内容
```"""

        try:
            result = await self.llm.chat_completion(
                [{"role": "user", "content": fix_prompt}],
                max_tokens=8192,
                temperature=0.3,
            )
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Parse fixed files
            import re
            changed = []
            for match in re.finditer(r'```file:([^\n]+)\n([\s\S]*?)```', content):
                file_path = match.group(1).strip()
                file_content = match.group(2).strip()
                if file_path and file_content:
                    self.ws_mgr.write_file(ws_id, file_path, file_content)
                    changed.append(file_path)

            return {"fixed": len(changed) > 0, "changed_files": changed, "message": f"已修复 {len(changed)} 个文件"}
        except Exception as e:
            logger.error(f"[Verifier] Auto-fix error: {e}")
            return {"fixed": False, "message": f"自动修复失败: {str(e)}"}
