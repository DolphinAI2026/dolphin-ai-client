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
    FORM_COMPONENT = "form-component"           # 表单自开发组件（PC）
    MOBILE_COMPONENT = "mobile-component"       # 移动端自开发组件
    FORM_PAGE = "form-page"                     # 自开发菜单页面（PC）
    MENU_PAGE = "menu-page"                     # 自开发菜单页面（PC，别名）
    MOBILE_PAGE = "mobile-page"                 # 移动端自开发页面
    FORM_LIST = "form-list"                     # 自开发列表视图
    LAYOUT = "layout"                           # 自定义布局
    PLUGIN = "plugin"                           # 自开发插件
    BACKEND_API = "backend-api"                 # 后端自开发接口
    SCRIPT = "script"                           # 脚本扩展
    SCRIPT_JS = "script-js"                     # JavaScript脚本扩展
    SCRIPT_PYTHON = "script-python"             # Python脚本扩展
    SCRIPT_GROOVY = "script-groovy"             # Groovy脚本扩展
    BUSINESS_DIALOG = "business-dialog"         # 业务事件自定义弹窗
    UI_STYLE = "ui-style"                       # UI样式扩展（CSS）
    LIST_CUSTOM_MODULE = "list-custom-module"   # 列表自定义模块
    WEB_LOGIN = "web-login"                     # 自定义登录页


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
        project_id: Optional[int] = None,
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
                ProjectType.MENU_PAGE: "form-page-",
                ProjectType.FORM_LIST: "form-list-",
                ProjectType.BACKEND_API: "backend-api-",
            }
            safe_name = prefix_map.get(project_type, "") + safe_name

        # 写入 workspace 元信息
        meta = {
            "id": ws_id,
            "project_id": project_id,
            "project_type": project_type.value,
            "project_name": safe_name,
            "user_id": user_id,
            "status": WorkspaceStatus.CREATING.value,
        }
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )

        # 生成脚手架
        if project_type == ProjectType.MOBILE_COMPONENT:
            # 移动端组件复用 PC 组件脚手架（结构相同，只是 widgetConfigList 多 client.mobile 节点）
            self._scaffold_form_component(ws_path, safe_name, mobile=True)
        elif project_type == ProjectType.FORM_COMPONENT:
            self._scaffold_form_component(ws_path, safe_name)
        elif project_type == ProjectType.MOBILE_PAGE:
            # 移动端页面复用 PC 页面脚手架（结构相同）
            self._scaffold_form_page(ws_path, safe_name, mobile=True)
        elif project_type in (ProjectType.FORM_PAGE, ProjectType.MENU_PAGE):
            self._scaffold_form_page(ws_path, safe_name)
        elif project_type == ProjectType.FORM_LIST:
            self._scaffold_form_list(ws_path, safe_name)
        elif project_type == ProjectType.BACKEND_API:
            self._scaffold_backend_api(ws_path, safe_name)
        elif project_type == ProjectType.LAYOUT:
            self._scaffold_layout(ws_path, safe_name)
        elif project_type == ProjectType.PLUGIN:
            self._scaffold_plugin(ws_path, safe_name)
        elif project_type == ProjectType.SCRIPT:
            self._scaffold_script_js(ws_path, safe_name)  # generic script defaults to JS
        elif project_type == ProjectType.SCRIPT_JS:
            self._scaffold_script_js(ws_path, safe_name)
        elif project_type == ProjectType.SCRIPT_PYTHON:
            self._scaffold_script_python(ws_path, safe_name)
        elif project_type == ProjectType.SCRIPT_GROOVY:
            self._scaffold_script_groovy(ws_path, safe_name)
        elif project_type == ProjectType.BUSINESS_DIALOG:
            self._scaffold_business_dialog(ws_path, safe_name)
        elif project_type == ProjectType.UI_STYLE:
            self._scaffold_ui_style(ws_path, safe_name)
        elif project_type == ProjectType.LIST_CUSTOM_MODULE:
            self._scaffold_list_custom_module(ws_path, safe_name)
        elif project_type == ProjectType.WEB_LOGIN:
            self._scaffold_web_login(ws_path, safe_name)

        # 生成 VS Code AI Chat 配置（接入 LLM）
        try:
            self._setup_vscode_ai_config(ws_path)
        except Exception as e:
            logger.warning(f"Failed to setup VS Code AI config: {e}")

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
        if meta["project_type"] in (
            ProjectType.BACKEND_API.value,
            ProjectType.SCRIPT_JS.value,
            ProjectType.SCRIPT_PYTHON.value,
            ProjectType.SCRIPT_GROOVY.value,
            ProjectType.BUSINESS_DIALOG.value,
            ProjectType.SCRIPT.value,
            ProjectType.UI_STYLE.value,
            ProjectType.LIST_CUSTOM_MODULE.value,
        ):
            return {"status": "skip", "message": "此类型项目无需 npm install"}

        meta["status"] = WorkspaceStatus.INSTALLING.value
        self._write_meta(ws_path, meta)

        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                "--registry", "https://registry.npmmirror.com",
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

    async def build_if_needed(self, ws_id: str) -> dict:
        """按需构建 - 仅在 src 文件比 dist 更新时重新构建"""
        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        dist_path = ws_path / "dist"
        src_path = ws_path / "src"

        # 如果 dist 不存在，必须构建
        if not dist_path.exists():
            return await self.build_project(ws_id)

        # 比较 src 和 dist 的最新修改时间
        def _latest_mtime(directory: Path) -> float:
            latest = 0
            for f in directory.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    mtime = f.stat().st_mtime
                    if mtime > latest:
                        latest = mtime
            return latest

        src_mtime = _latest_mtime(src_path) if src_path.exists() else 0
        dist_mtime = _latest_mtime(dist_path)

        if src_mtime > dist_mtime:
            logger.info(f"[build_if_needed] src is newer, rebuilding {ws_id}")
            return await self.build_project(ws_id)
        else:
            logger.info(f"[build_if_needed] dist is up-to-date for {ws_id}")
            return {"status": "ok", "message": "已是最新，无需重新构建"}

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

    # ======== Serve & Debug 进程管理 ========
    _serve_processes: dict = {}   # {ws_id: {"process": Process, "port": int}}
    _debug_processes: dict = {}   # {ws_id: {"process": Process}}
    _next_port: int = 8080

    async def start_serve(self, ws_id: str) -> dict:
        """启动 npm run serve 后台进程，返回端口号"""
        if ws_id in self._serve_processes:
            info = self._serve_processes[ws_id]
            if info["process"].returncode is None:  # 还在运行
                return {"status": "ok", "port": info["port"], "message": "serve 已在运行"}

        ws_path = WORKSPACE_ROOT / ws_id
        if not ws_path.exists():
            raise FileNotFoundError(f"Workspace {ws_id} not found")

        # 找到可用端口
        port = self._next_port
        WorkspaceManager._next_port += 1
        import socket
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("localhost", port)) != 0:
                    break
                port += 1
                WorkspaceManager._next_port = port + 1

        env = {**__import__("os").environ, "PORT": str(port)}
        proc = await asyncio.create_subprocess_exec(
            "npx", "vue-cli-service", "serve", "src/index.js", "--port", str(port),
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._serve_processes[ws_id] = {"process": proc, "port": port}

        # 等待 serve 启动（最多 30 秒）
        import time
        start = time.time()
        while time.time() - start < 30:
            await asyncio.sleep(1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("localhost", port)) == 0:
                    return {"status": "ok", "port": port, "message": f"serve 已启动在端口 {port}"}
            if proc.returncode is not None:
                stdout, stderr = await proc.communicate()
                return {"status": "error", "port": port,
                        "message": f"serve 启动失败: {stderr.decode('utf-8', errors='replace')[:300]}"}

        return {"status": "ok", "port": port, "message": f"serve 正在启动（端口 {port}）"}

    async def stop_serve(self, ws_id: str) -> dict:
        """停止 serve 进程"""
        if ws_id not in self._serve_processes:
            return {"status": "ok", "message": "serve 未运行"}
        info = self._serve_processes.pop(ws_id)
        proc = info["process"]
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        return {"status": "ok", "message": "serve 已停止"}

    def is_serve_running(self, ws_id: str) -> dict:
        """查询 serve 状态"""
        if ws_id not in self._serve_processes:
            return {"running": False}
        info = self._serve_processes[ws_id]
        running = info["process"].returncode is None
        if not running:
            self._serve_processes.pop(ws_id, None)
        return {"running": running, "port": info["port"] if running else None}

    async def build_and_package(self, ws_id: str) -> str:
        """构建 + 打包 zip，返回 zip 文件路径"""
        # 先构建
        result = await self.build_project(ws_id)
        if result["status"] == "error":
            raise RuntimeError(f"构建失败: {result['message']}")

        # 打包 zip
        ws_path = WORKSPACE_ROOT / ws_id
        meta = self._read_meta(ws_path)
        project_name = meta.get("project_name", ws_id)
        dist_path = ws_path / "dist"
        if not dist_path.exists():
            raise FileNotFoundError("dist 目录不存在，构建可能失败")

        import zipfile, io
        zip_path = ws_path / f"{project_name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in dist_path.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(dist_path))
            # 加入 apaas.json
            apaas_json = ws_path / "src" / "apaas.json"
            if apaas_json.exists():
                zf.write(apaas_json, "apaas.json")
                try:
                    cfg = json.loads(apaas_json.read_text())
                    for asset in cfg.get("copyAssets", []):
                        static_dir = asset.replace("public/", "static/", 1)
                        zf.writestr(f"{static_dir}/", "")
                except Exception:
                    zf.writestr(f"static/custom/{project_name}/", "")
            else:
                zf.writestr(f"static/custom/{project_name}/", "")

        return str(zip_path)

    async def start_debug(self, ws_id: str, serve_port: int,
                          platform_url: str, tenant_id: str, app_id: str,
                          output_name: str, custom_widget_list: list,
                          debug_mode: str = "platform",
                          app_code: str = "",
                          form_id: str = "",
                          menu_id: str = "",
                          component_name: str = "",
                          apaas_token: str = "",
                          platform_backend_url: str = "") -> dict:
        """启动 Puppeteer debug 模式，注入组件到平台或应用"""
        # 如果已有 debug 进程在运行，先停止
        if ws_id in self._debug_processes:
            old_proc = self._debug_processes[ws_id]["process"]
            if old_proc.returncode is None:
                old_proc.terminate()
                try:
                    await asyncio.wait_for(old_proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    old_proc.kill()

        ws_path = WORKSPACE_ROOT / ws_id

        # 根据 debug_mode 计算目标 URL — 简单模式：打开平台/应用首页，用户自己导航
        _base_url = platform_url.replace("/platform/", "/").rstrip("/") + "/"
        if debug_mode == "app" and app_code:
            # 应用调试 → 打开应用首页
            target_url = f"{_base_url}app/dragonfly/{app_code}/"
        else:
            # 平台调试 → 打开平台首页（用户自己选择表单）
            target_url = f"{platform_url}account/login"

        # 生成 debug 脚本
        debug_script = f"""
const path = require('path')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:{serve_port}/'
const targetEnv = '{debug_mode}'
const tenantId = '{tenant_id}'
const appId = '{app_id}'
const outputName = '{output_name}'
const customWidgetList = {json.dumps(custom_widget_list)}

const INJECT_CODE = `(function(params) {{
  if (window.__APAAS_DEBUG_INJECTED__) return;
  var checkInterval = setInterval(function() {{
    if (window.APaaSSDK && window.df && window.Vue && window.Vue.FormEngine && !window.location.href.includes('/login')) {{
      clearInterval(checkInterval);
      if (window.__APAAS_DEBUG_INJECTED__) return;
      window.__APAAS_DEBUG_INJECTED__ = true;
      console.log('[DEBUG] Injecting component...');
      setTimeout(function() {{
        var s1 = document.createElement('script');
        s1.src = params.localServerRunningAt + 'js/chunk-vendors.js';
        s1.async = false;
        document.head.appendChild(s1);
        var s2 = document.createElement('script');
        s2.src = params.localServerRunningAt + 'js/app.js';
        s2.async = false;
        s2.onload = function() {{
          try {{
            var mod = window[params.outputName];
            if (mod && mod.default) mod.default.install(window.Vue);
          }} catch(e) {{ console.warn('[DEBUG] install error:', e.message); }}
          try {{
            window.Vue.FormEngine.WidgetControl.customComponentEffectMap.set(
              params.customWidgetList[0].code,
              {{ appIdList: [params.appId], tenantId: params.tenantId }}
            );
          }} catch(e) {{}}
          function r() {{ try {{ window.APaaSSDK.context.XEventBus.emit('refreshGroupWidgetList'); }} catch(e) {{}} }}
          r(); setTimeout(r,1000); setTimeout(r,3000); setTimeout(r,5000);
          console.log('[DEBUG] ✅ Component injected!');
        }};
        s2.onerror = function() {{ window.__APAAS_DEBUG_INJECTED__ = false; }};
        document.head.appendChild(s2);
      }}, 2000);
    }}
  }}, 1000);
}})`

;(async () => {{
  const realArch = os.arch()
  let executablePath
  if (realArch === 'x64') {{
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac/Chromium.app/Contents/MacOS/Chromium')
  }} else {{
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac_arm/Chromium.app/Contents/MacOS/Chromium')
  }}
  const browser = await puppeteer.launch({{
    args: ['--start-maximized', '--ignore-certificate-errors', '--no-sandbox'],
    ignoreDefaultArgs: ['--disable-extensions'],
    executablePath, headless: false, defaultViewport: null
  }})
  const pages = await browser.pages()
  const page = pages[0]
  page.setDefaultNavigationTimeout(120000)
  page.setDefaultTimeout(120000)
  const injectParams = {{ localServerRunningAt, outputName, targetEnv, customWidgetList, tenantId, appId }}
  const injectCall = `${{INJECT_CODE}}(${{JSON.stringify(injectParams)}})`
  await page.evaluateOnNewDocument(injectCall)
  try {{
    await page.goto('{target_url}', {{ waitUntil: 'domcontentloaded', timeout: 120000 }})
  }} catch(e) {{ console.log('Nav issue:', e.message.split('\\n')[0]) }}
  await page.evaluate(injectCall)
  console.log('✅ Debug active')
  await new Promise(r => browser.on('disconnected', r))
  process.exit(0)
}})()
"""
        debug_script_path = ws_path / "_debug.js"
        debug_script_path.write_text(debug_script, encoding="utf-8")

        # 启动 debug 进程
        proc = await asyncio.create_subprocess_exec(
            "node", str(debug_script_path),
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._debug_processes[ws_id] = {"process": proc}

        # 等待 Chromium 启动（最多 15 秒）
        import time
        start = time.time()
        while time.time() - start < 15:
            await asyncio.sleep(1)
            # 检查进程是否还活着
            if proc.returncode is not None:
                stdout, stderr = await proc.communicate()
                return {"status": "error", "message": f"Debug 启动失败: {stderr.decode('utf-8', errors='replace')[:300]}"}

        _mode_label = "应用前台" if debug_mode == "app" else "平台设计器"
        return {
            "status": "ok",
            "message": f"Debug 已启动（{_mode_label}），请在打开的 Chromium 中登录后 F5 刷新",
            "serve_port": serve_port,
            "platform_url": platform_url,
            "debug_mode": debug_mode,
        }

    async def _ensure_debug_form(self, ws_id: str, ws_path: Path,
                                  app_id: str, component_name: str,
                                  apaas_token: str, platform_backend_url: str,
                                  tenant_id: str) -> tuple:
        """确保 debug 用的测试表单存在，返回 (form_id, menu_id)。
        优先从 .workspace.json 缓存读取，缓存不存在则调用 aPaaS API 创建。
        """
        # 1. 尝试从工作区元数据读取缓存
        meta = self._read_meta(ws_path)
        cached_form_id = meta.get("debug_form_id")
        cached_menu_id = meta.get("debug_menu_id")
        if cached_form_id and cached_menu_id:
            logger.info(f"[DEBUG] 复用已缓存的测试表单: formId={cached_form_id}, menuId={cached_menu_id}")
            return cached_form_id, cached_menu_id

        # 2. 调用 aPaaS API 创建空白测试表单
        from app.apaas_client import APaaSClient
        client = APaaSClient(base_url=platform_backend_url, tenant_id=tenant_id, token=apaas_token)

        form_name = f"AI测试-{component_name}" if component_name else f"AI测试-{ws_id[:8]}"
        form_code = f"ai_test_{ws_id[:8].replace('-', '_')}"
        form_payload = [{
            "formName": form_name,
            "formCode": form_code,
            "allModelCodes": [],
            "formComponents": [],
        }]

        logger.info(f"[DEBUG] 自动创建测试表单: {form_name}")
        result = await client.create_form_config(app_id, form_payload)

        form_id = ""
        menu_id = ""
        if isinstance(result, list):
            for fr in result:
                if isinstance(fr, dict) and fr.get("id"):
                    form_id = fr["id"]
                    menu_id = fr.get("menuId", "")
                    break

        if not form_id:
            raise Exception(f"自动创建测试表单失败: {result}")

        # 如果 API 没有返回 menuId，手动创建菜单
        if not menu_id:
            logger.info(f"[DEBUG] 表单创建未返回 menuId，手动创建菜单...")
            menu_result = await client.create_menu(app_id, form_name, form_id)
            menu_id = menu_result.get("id", "") if isinstance(menu_result, dict) else ""

        if not menu_id:
            raise Exception(f"自动创建测试菜单失败")

        # 3. 缓存到 .workspace.json
        meta["debug_form_id"] = form_id
        meta["debug_menu_id"] = menu_id
        meta["debug_form_name"] = form_name
        self._write_meta(ws_path, meta)
        logger.info(f"[DEBUG] 测试表单创建成功并已缓存: formId={form_id}, menuId={menu_id}")

        return form_id, menu_id

    async def start_auto_debug(self, ws_id: str, serve_port: int,
                                platform_url: str, tenant_id: str, app_id: str,
                                output_name: str, custom_widget_list: list,
                                debug_mode: str = "platform",
                                app_code: str = "",
                                form_id: str = "",
                                menu_id: str = "",
                                component_name: str = "",
                                apaas_token: str = "",
                                platform_backend_url: str = "") -> dict:
        """启动自动化 Debug：自动登录 + 导航 + 截图 + 组件注入

        新增参数:
          form_id / menu_id — 用户指定的表单/菜单ID，为空则自动创建
          component_name — 组件名称，用于命名自动创建的测试表单
          apaas_token — 平台认证token，自动创建表单时需要
          platform_backend_url — 平台后端URL，自动创建表单时需要
        """
        # 如果已有 debug 进程在运行，先停止
        if ws_id in self._debug_processes:
            old_proc = self._debug_processes[ws_id]["process"]
            if old_proc.returncode is None:
                old_proc.terminate()
                try:
                    await asyncio.wait_for(old_proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    old_proc.kill()

        ws_path = WORKSPACE_ROOT / ws_id
        screenshots_dir = ws_path / "debug" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        result_json_path = ws_path / "debug" / "result.json"
        if result_json_path.exists():
            result_json_path.unlink()

        # platform_url 通常以 /platform/ 结尾，提取 base（如 https://apaas-dev8.dfy.definesys.cn/）
        _base_url = platform_url.replace("/platform/", "/").rstrip("/") + "/"
        login_url = f"{platform_url}account/login"

        if debug_mode == "app" and app_code:
            # 应用调试 → 打开应用首页
            form_url = f"{_base_url}app/dragonfly/{app_code}/"
        else:
            # 平台调试 → 打开平台登录页，用户自己导航到表单设计器
            form_url = login_url

        debug_script = f"""
const path = require('path')
const fs = require('fs')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:{serve_port}/'
const tenantId = '{tenant_id}'
const appId = '{app_id}'
const outputName = '{output_name}'
const customWidgetList = {json.dumps(custom_widget_list)}

const INJECT_CODE = `(function(params) {{
  if (window.__APAAS_DEBUG_INJECTED__) return;
  var checkInterval = setInterval(function() {{
    if (window.APaaSSDK && window.df && window.Vue && window.Vue.FormEngine && !window.location.href.includes('/login')) {{
      clearInterval(checkInterval);
      if (window.__APAAS_DEBUG_INJECTED__) return;
      window.__APAAS_DEBUG_INJECTED__ = true;
      console.log('[DEBUG] Injecting component...');
      setTimeout(function() {{
        var s1 = document.createElement('script');
        s1.src = params.localServerRunningAt + 'js/chunk-vendors.js';
        s1.async = false;
        document.head.appendChild(s1);
        var s2 = document.createElement('script');
        s2.src = params.localServerRunningAt + 'js/app.js';
        s2.async = false;
        s2.onload = function() {{
          try {{
            var mod = window[params.outputName];
            if (mod && mod.default) mod.default.install(window.Vue);
          }} catch(e) {{ console.warn('[DEBUG] install error:', e.message); }}
          try {{
            window.Vue.FormEngine.WidgetControl.customComponentEffectMap.set(
              params.customWidgetList[0].code,
              {{ appIdList: [params.appId], tenantId: params.tenantId }}
            );
          }} catch(e) {{}}
          function r() {{ try {{ window.APaaSSDK.context.XEventBus.emit('refreshGroupWidgetList'); }} catch(e) {{}} }}
          r(); setTimeout(r,1000); setTimeout(r,3000); setTimeout(r,5000);
          console.log('[DEBUG] Component injected!');
        }};
        s2.onerror = function() {{ window.__APAAS_DEBUG_INJECTED__ = false; }};
        document.head.appendChild(s2);
      }}, 2000);
    }}
  }}, 1000);
}})`

const screenshotsDir = '{str(screenshots_dir)}'
const resultPath = '{str(result_json_path)}'

;(async () => {{
  const realArch = os.arch()
  let executablePath
  if (realArch === 'x64') {{
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac/Chromium.app/Contents/MacOS/Chromium')
  }} else {{
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac_arm/Chromium.app/Contents/MacOS/Chromium')
  }}

  const browser = await puppeteer.launch({{
    args: ['--start-maximized', '--ignore-certificate-errors', '--no-sandbox'],
    ignoreDefaultArgs: ['--disable-extensions'],
    executablePath, headless: false, defaultViewport: null
  }})
  const pages = await browser.pages()
  const page = pages[0]
  page.setDefaultNavigationTimeout(120000)
  page.setDefaultTimeout(120000)

  const result = {{ status: 'ok', screenshots: [], message: '' }}

  try {{
    // Step 1: Navigate to login page
    console.log('[AUTO-DEBUG] Navigating to login...')
    await page.goto('{login_url}', {{ waitUntil: 'networkidle2', timeout: 120000 }})
    await page.waitForTimeout(2000)

    // Step 2: Auto-fill credentials and login
    console.log('[AUTO-DEBUG] Filling login form...')
    const inputs = await page.$$('input')
    if (inputs.length >= 2) {{
      await inputs[0].click({{ clickCount: 3 }})
      await inputs[0].type('17621440039')
      const pwdInput = await page.$('input[type="password"]') || inputs[1]
      await pwdInput.click({{ clickCount: 3 }})
      await pwdInput.type('definesys2019')
    }}
    await page.waitForTimeout(500)

    // Click login button
    const loginBtn = await page.evaluateHandle(() => {{
      const buttons = Array.from(document.querySelectorAll('button'))
      return buttons.find(b => b.textContent.includes('登录')) || buttons[0]
    }})
    if (loginBtn) {{
      await loginBtn.click()
    }}

    // Wait for login to complete (URL should change away from /login)
    console.log('[AUTO-DEBUG] Waiting for login...')
    await page.waitForFunction(
      () => !window.location.href.includes('/login'),
      {{ timeout: 120000 }}
    )
    await page.waitForTimeout(2000)
    console.log('[AUTO-DEBUG] Login successful!')

    // Step 3: Set up component injection
    const injectParams = {{ localServerRunningAt, outputName, targetEnv: '{debug_mode}', customWidgetList, tenantId, appId }}
    const injectCall = `${{INJECT_CODE}}(${{JSON.stringify(injectParams)}})`
    await page.evaluateOnNewDocument(injectCall)

    // Step 4: Navigate to target page
    console.log('[AUTO-DEBUG] Navigating to {debug_mode} debug target...')
    await page.goto('{form_url}', {{ waitUntil: 'domcontentloaded', timeout: 60000 }})
    await page.evaluate(injectCall)

    // Step 5: Wait for page load + component injection
    console.log('[AUTO-DEBUG] Waiting for component injection...')
    await page.waitForTimeout(8000)

    // Step 6: Take full-page screenshot
    console.log('[AUTO-DEBUG] Taking screenshot...')
    await page.screenshot({{
      path: path.join(screenshotsDir, 'page.png'),
      fullPage: true
    }})
    result.screenshots.push('page.png')

    // Step 7: Try to screenshot component panel
    try {{
      const panel = await page.$('.widget-list, .custom-component-panel, [class*="widget"]')
      if (panel) {{
        await panel.screenshot({{
          path: path.join(screenshotsDir, 'panel.png')
        }})
        result.screenshots.push('panel.png')
      }}
    }} catch(e) {{
      console.log('[AUTO-DEBUG] Panel screenshot skipped:', e.message)
    }}

    result.message = 'Auto debug completed successfully'
  }} catch(e) {{
    result.status = 'error'
    result.message = e.message
    console.error('[AUTO-DEBUG] Error:', e.message)

    // Take error screenshot
    try {{
      await page.screenshot({{
        path: path.join(screenshotsDir, 'page.png'),
        fullPage: true
      }})
      result.screenshots.push('page.png')
    }} catch(e2) {{}}
  }}

  // Write result JSON
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2))
  console.log('[AUTO-DEBUG] Result written to', resultPath)

  // Keep browser open
  await new Promise(r => browser.on('disconnected', r))
  process.exit(0)
}})()
"""
        debug_script_path = ws_path / "_auto_debug.js"
        debug_script_path.write_text(debug_script, encoding="utf-8")

        # 启动 debug 进程
        proc = await asyncio.create_subprocess_exec(
            "node", str(debug_script_path),
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._debug_processes[ws_id] = {"process": proc}

        # 轮询等待 result.json 出现（最多 60 秒）
        import time
        start = time.time()
        while time.time() - start < 120:
            await asyncio.sleep(2)
            # 检查进程是否崩溃
            if proc.returncode is not None:
                stdout, stderr = await proc.communicate()
                return {"status": "error", "message": f"Auto debug 进程异常退出: {stderr.decode('utf-8', errors='replace')[:300]}"}
            # 检查 result.json 是否生成
            if result_json_path.exists():
                try:
                    result = json.loads(result_json_path.read_text(encoding="utf-8"))
                    return result
                except json.JSONDecodeError:
                    continue

        return {"status": "error", "message": "Auto debug 超时（60秒），未生成结果"}

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

        # HTTPS 自签名证书（debug 模式必需）
        self._generate_https_cert(ws_path)

    # ========== VS Code AI 配置 ==========

    def _setup_vscode_ai_config(self, ws_path: Path):
        """为 workspace 生成 VS Code AI Chat 配置，接入 LLM（如 MiniMax）"""
        from app.config import settings

        api_base = settings.llm_api_base.rstrip("/")
        api_key = settings.llm_api_key
        model = settings.llm_model

        if not api_key:
            return

        # ---- .vscode/settings.json ----
        vscode_dir = ws_path / ".vscode"
        vscode_dir.mkdir(exist_ok=True)

        vscode_settings = {
            # Continue 扩展配置（OpenAI 兼容端点）
            "continue.enableTabAutocomplete": True,
            # GitHub Copilot Chat 自定义模型（VS Code 1.99+）
            "github.copilot.chat.models": [
                {
                    "vendor": "copilot",
                    "family": "openai-compatible",
                    "id": model,
                    "url": f"{api_base}/v1/chat/completions",
                    "headers": {
                        "Authorization": f"Bearer {api_key}"
                    },
                }
            ],
        }

        settings_file = vscode_dir / "settings.json"
        settings_file.write_text(
            json.dumps(vscode_settings, ensure_ascii=False, indent=2)
        )

        # ---- .continue/config.json（Continue 扩展的配置） ----
        continue_dir = ws_path / ".continue"
        continue_dir.mkdir(exist_ok=True)

        continue_config = {
            "models": [
                {
                    "title": f"MiniMax ({model})",
                    "provider": "openai",
                    "model": model,
                    "apiBase": f"{api_base}/v1",
                    "apiKey": api_key,
                }
            ],
            "tabAutocompleteModel": {
                "title": "MiniMax Autocomplete",
                "provider": "openai",
                "model": model,
                "apiBase": f"{api_base}/v1",
                "apiKey": api_key,
            },
            "allowAnonymousTelemetry": False,
        }

        continue_file = continue_dir / "config.json"
        continue_file.write_text(
            json.dumps(continue_config, ensure_ascii=False, indent=2)
        )

    # ========== 脚手架模板 ==========

    def _scaffold_form_component(self, ws_path: Path, name: str, mobile: bool = False):
        """表单自开发组件脚手架 - 完整 FORM_COMPONENT 7场景架构"""
        # 公共文件
        self._write_common_files(ws_path, name, "FORM_COMPONENT")

        # 组件 code（大写下划线格式）
        code = "FORM_CUSTOM_COMPONENT_" + name.replace("form-component-", "").replace("-", "_").upper()
        setting_code = code + "_SETTING"
        # 组件名前缀（PascalCase）
        parts = name.replace("form-component-", "").split("-")
        pascal = "".join(p.capitalize() for p in parts)
        prefix = f"FormComponent{pascal}"
        # 文件名 kebab-case
        kebab = name.replace("form-component-", "")
        full_kebab = f"form-component-{kebab}"

        # ======== 项目根文件 ========

        # package.json（对齐真实 df-apaas-cli 项目）
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "FORM_COMPONENT",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve": "vue-cli-service serve src/index.js",
                "debug": "df-apaas-cli debug",
                "build": f"vue-cli-service build --target lib --name {name} src/index.js"
            },
            "dependencies": {
                "core-js": "3.8.3",
                "vue": "2.7.14"
            },
            "devDependencies": {
                "@babel/core": "7.12.16",
                "@babel/eslint-parser": "7.12.16",
                "@vue/cli-plugin-babel": "5.0.0",
                "@vue/cli-plugin-eslint": "5.0.0",
                "@vue/cli-service": "5.0.8",
                "dart-sass": "1.25.0",
                "eslint": "7.32.0",
                "eslint-plugin-vue": "8.0.3",
                "sass": "1.85.1",
                "sass-loader": "8.0.2",
                "vue-template-compiler": "2.7.14"
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {}
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        }, indent=2, ensure_ascii=False))

        # vue.config.js
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const apaasJson = require('./src/apaas.json')

function loadHttps() {
  const keyPath = './https/server.key'
  const certPath = './https/server.crt'
  if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
    return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
  }
  return false
}

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
    https: loadHttps(),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: {
    output: {
      library: apaasJson.outputName,
      libraryTarget: 'umd'
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
""")

        # babel.config.js
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        # ======== src/apaas.json ========
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "templateType": "FORM_COMPONENT",
            "customWidgetList": [
                {"code": code, "text": kebab, "description": kebab}
            ],
            "copyAssets": [f"public/form-component/{name}"],
            "router": {},
            "outputName": name
        }, indent=2, ensure_ascii=False))

        # ======== src/index.js（FormEngine 注册入口）========
        self._write(ws_path, "src/index.js", f"""import './form-component-local/index.js'
import {{ customFormEditorList, customFormWidgetList }} from './form-component'
import {{ widgetConfigList, editorConfigList }} from './form-component-config'
import {{ AbilityFieldMap, AbilityFieldConvert }} from './form-ability'

const install = function(Vue) {{
  customFormEditorList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  customFormWidgetList.forEach((comp) => {{ Vue.component(comp.name, comp) }})
  editorConfigList.forEach((editorConfig) => {{
    Vue.FormEngine.WidgetControl.registerEditorConfig(editorConfig)
  }})
  widgetConfigList.forEach((widgetConfig) => {{
    Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig({{ widgetConfig }})
  }})
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterComponentTypeConfig(AbilityFieldMap)
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterFieldValueConvert(AbilityFieldConvert)
}}

export default {{ install }}
""")

        # ======== form-component/（7场景组件）========
        self._write(ws_path, "src/form-component/index.js", """import customFormWidgetList from './form-widget'
import customFormEditorList from './form-editor'

export { customFormWidgetList, customFormEditorList }
""")

        # form-widget 聚合
        self._write(ws_path, "src/form-component/form-widget/index.js", """import ideFormComponentList from './ide'
import editFormComponentList from './edit'
import readFormComponentList from './read'
import listFormComponentList from './list'
import printFormComponentList from './print'
import searchFormComponentList from './search'
import searchIdeFormComponentList from './search-ide'

const customFormComponentList = [
  ...ideFormComponentList, ...editFormComponentList, ...readFormComponentList,
  ...listFormComponentList, ...printFormComponentList,
  ...searchFormComponentList, ...searchIdeFormComponentList
]

export default customFormComponentList
""")

        # --- IDE 场景 ---
        self._write(ws_path, "src/form-component/form-widget/ide/index.js",
                     f"import Comp from './{full_kebab}-ide.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/ide/{full_kebab}-ide.vue", f"""<template>
  <div class="form-widget {full_kebab}-ide">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <div style="border:1px dashed #dcdfe6;padding:12px;border-radius:4px;background:#fafafa;">
        <span style="font-size:12px;color:#909399;">自定义组件（设计态预览）</span>
      </div>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{ name: '{prefix}Ide', mixins: [FormWidgetMixin] }}
</script>
""")

        # --- Edit 场景（核心） ---
        self._write(ws_path, "src/form-component/form-widget/edit/index.js",
                     f"import Comp from './{full_kebab}-edit.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/edit/{full_kebab}-edit.vue", f"""<template>
  <div class="form-widget {full_kebab}-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <!-- TODO: AI 将在此实现编辑态交互组件 -->
      <el-input v-model="editValue" placeholder="请输入" />
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{
  name: '{prefix}Edit',
  mixins: [FormWidgetMixin],
  computed: {{
    editValue: {{
      get() {{ return this.formValue || '' }},
      set(val) {{ this.formValue = val }}
    }}
  }}
}}
</script>
<style lang="scss">
.{full_kebab}-edit {{}}
</style>
""")

        # --- Read 场景 ---
        self._write(ws_path, "src/form-component/form-widget/read/index.js",
                     f"import Comp from './{full_kebab}-read.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/read/{full_kebab}-read.vue", f"""<template>
  <div class="form-widget {full_kebab}-read">
    <x-proxy-form-item
      :isInTable="widget.isInTable" :showRequired="showRequired" :label="widget.label"
      :titleDescription="widget.titleDescription" :renderScene="renderScene"
      :processTitle="widget.processTitle" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo" :webFormSettings="webFormSettings"
    >
      <span>{{{{ formValue || '-' }}}}</span>
    </x-proxy-form-item>
  </div>
</template>
<script>
import FormWidgetMixin from '@/mixin/form-widget.mixin'
export default {{ name: '{prefix}Read', mixins: [FormWidgetMixin] }}
</script>
""")

        # --- List 场景 ---
        self._write(ws_path, "src/form-component/form-widget/list/index.js",
                     f"import Comp from './{full_kebab}-list.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/list/{full_kebab}-list.vue", f"""<template>
  <div class="form-widget {full_kebab}-list">
    <span>{{{{ formValue || '-' }}}}</span>
  </div>
</template>
<script>
export default {{
  name: '{prefix}List',
  props: {{
    componentConfig: {{ type: Object, default() {{ return {{}} }} }},
    formValue: {{ type: [String, Object, Array], default: '' }},
    propKey: {{ type: String, default: '' }}
  }}
}}
</script>
""")

        # --- Print 场景 ---
        self._write(ws_path, "src/form-component/form-widget/print/index.js",
                     f"import Comp from './{full_kebab}-print.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/print/{full_kebab}-print.vue", f"""<template>
  <div class="form-widget {full_kebab}-print">
    <span>{{{{ formValue || '-' }}}}</span>
  </div>
</template>
<script>
import PrintWidgetMixin from '@/mixin/print-widget.mixin'
export default {{ name: '{prefix}Print', mixins: [PrintWidgetMixin] }}
</script>
""")

        # --- Search 场景 ---
        self._write(ws_path, "src/form-component/form-widget/search/index.js",
                     f"import Comp from './{full_kebab}-search.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/search/{full_kebab}-search.vue", f"""<template>
  <div class="form-widget {full_kebab}-search">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input v-model="searchValue" clearable size="mini" placeholder="请输入" />
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchWidgetMixin from '@/mixin/search-widget.mixin'
export default {{
  name: '{prefix}Search',
  mixins: [SearchWidgetMixin],
  computed: {{
    searchValue: {{
      get() {{ return this.formValue }},
      set(val) {{ this.formValue = val }}
    }}
  }}
}}
</script>
""")

        # --- Search-IDE 场景 ---
        self._write(ws_path, "src/form-component/form-widget/search-ide/index.js",
                     f"import Comp from './{full_kebab}-search-ide.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-widget/search-ide/{full_kebab}-search-ide.vue", f"""<template>
  <div class="form-widget {full_kebab}-search-ide">
    <x-proxy-form-item :isInTable="widget.isInTable" :showRequired="showRequired"
      :label="widget.label" :validatorRules="validatorRules"
      :validateKey="validateKey" :validateInfo="validateInfo">
      <el-input disabled size="mini" placeholder="搜索（设计态预览）" />
    </x-proxy-form-item>
  </div>
</template>
<script>
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'
export default {{ name: '{prefix}SearchIde', mixins: [SearchIdeWidgetMixin] }}
</script>
""")

        # ======== form-editor（设计器配置面板）========
        self._write(ws_path, "src/form-component/form-editor/index.js",
                     f"import Comp from './{full_kebab}-setting.vue'\nexport default [Comp]\n")
        self._write(ws_path, f"src/form-component/form-editor/{full_kebab}-setting.vue", f"""<template>
  <div class="form-config-item form-config-{kebab}-setting">
    <div class="setting-panel">
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
.form-config-{kebab}-setting {{
  .setting-panel {{
    padding: 12px;
  }}
}}
</style>
""")

        # ======== form-component-config ========
        self._write(ws_path, "src/form-component-config/index.js", """import widgetConfigList from './form-widget'
import editorConfigList from './form-editor'

export { widgetConfigList, editorConfigList }
""")
        self._write(ws_path, "src/form-component-config/form-widget/index.js",
                     f"import config from './{full_kebab}.widget.config'\nexport default [config]\n")
        self._write(ws_path, f"src/form-component-config/form-widget/{full_kebab}.widget.config.js", f"""const config = {{
  version: 2.0,
  code: '{code}',
  desc: {{
    iconType: 'DEFAULT',
    icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#409EFF"/><text x="12" y="16" text-anchor="middle" fill="#fff" font-size="10">C</text></svg>',
    text: '{kebab}',
    description: '{kebab}'
  }},
  instance: {{ uuid: '$itemUuid', inTable: false }},
  component: {{
    ide: '{prefix}Ide',
    edit: '{prefix}Edit',
    read: '{prefix}Read',
    list: '{prefix}List',
    association: '{prefix}List',
    lov: '{prefix}List',
    print: '{prefix}Print',
    search: '{prefix}Search',
    searchIde: '{prefix}SearchIde'
  }},
  widget: {{
    display: {{
      label: '{kebab}', width: 6, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    }},
    allow: {{ useInTableColumn: true }},
    default: {{ customDefaultKey: 'defaultValue', value: '' }},
    validator: {{ uniqueCheck: false }},
    validatorList: [{{ validatorConfig: [], validatorMessage: '' }}],
    special: {{ frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false }},
    customComponentConfig: {{}},
    componentModelField: ['TEXT'],
    editor: {{
      config: [
        'INFO', 'LABEL', 'FIELD_CODE', 'TITLE_DESCRIPTION', 'WIDTH',
        '{setting_code}',
        'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
        'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
      ],
      excludeInTable: ['WIDTH']
    }}
  }},
  client: {{
    mobile: {{
      widget: {{
        editor: {{
          config: [
            'INFO', 'LABEL', 'FIELD_CODE', 'WIDTH', '{setting_code}',
            'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
            'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
          ],
          excludeInTable: ['WIDTH']
        }}
      }},
      component: {{
        ide: 'Mobile{prefix}Ide', edit: 'Mobile{prefix}Edit',
        read: 'Mobile{prefix}Read', list: 'Mobile{prefix}List',
        association: 'Mobile{prefix}Association', lov: 'Mobile{prefix}Lov',
        tableColumn: 'Mobile{prefix}TableColumn'
      }}
    }}
  }},
  methods: {{}},
  formatValueSchema: {{}}
}}

export default config
""")

        self._write(ws_path, "src/form-component-config/form-editor/index.js",
                     f"import config from './{full_kebab}.editor.config'\nexport default [config]\n")
        self._write(ws_path, f"src/form-component-config/form-editor/{full_kebab}.editor.config.js", f"""const config = {{
  code: '{setting_code}',
  editorConfigType: '{setting_code}',
  componentName: '{prefix}Setting',
  configProperty: 'customComponentConfig'
}}

export default config
""")

        # ======== Mixin（完整版，非 mock）========
        self._write(ws_path, "src/mixin/form-widget.mixin.js", self._get_form_widget_mixin())
        self._write(ws_path, "src/mixin/print-widget.mixin.js", """const PrintWidgetMixin = {
  props: {
    widget: { required: true },
    componentType: { type: String },
    formData: { required: true },
    propKey: { type: String, default: '' },
    inTable: { type: Boolean, default: false },
    formRuleConfig: { type: Object, default: () => {} }
  },
  computed: {
    formValue: {
      get() { return this.propKey ? this.formData[this.propKey] : '' },
      set(value) { this.formData[this.propKey] = value; this.$set(this.formData, this.propKey, value) }
    }
  }
}
export default PrintWidgetMixin
""")
        self._write(ws_path, "src/mixin/search-widget.mixin.js", """export default {
  model: { prop: 'value', event: 'change' },
  props: {
    widget: { type: Object, default: () => ({}) },
    compInfo: { type: Object, default: () => ({}) },
    value: { type: Array, default: () => [] },
    placeholder: { type: String },
    searchItemConfig: { type: Object, default: () => ({}) }
  },
  computed: {
    computeValue: {
      get() { return this.value },
      set(value) { this.$emit('change', value) }
    },
    labelStyle() {
      return {
        width: this.searchItemConfig.labelWidth ? this.searchItemConfig.labelWidth / 14 + 'rem' : '',
        textAlign: this.searchItemConfig.labelalign || ''
      }
    }
  }
}
""")
        self._write(ws_path, "src/mixin/search-ide-widget.mixin.js", """export default {
  model: { prop: 'value', event: 'change' },
  props: {
    widget: { type: Object, default: () => ({}) },
    compInfo: { type: Object, default: () => ({}) },
    value: { type: Array, default: () => [] }
  },
  computed: {
    computeValue: {
      get() { return this.value },
      set(value) { this.$emit('change', value) }
    }
  }
}
""")

        # ======== Validator ========
        self._write(ws_path, "src/validator/widget-required-validator.js", """import { WidgetAreaRequiredValidator } from './widget-area-validator'
const WidgetRequiredValidator = (errorMsg, uuid, xid, widget) => {
  return (rule, value, callback) => {
    if (widget && widget.componentType === 'FORM_WIDGET_AREA') {
      return WidgetAreaRequiredValidator(errorMsg, uuid, xid)('', widget, value, callback)
    }
    if (value === undefined || value === null) return callback(new Error(errorMsg), uuid, xid)
    if (Array.isArray(value) && !value.length) return callback(new Error(errorMsg), uuid, xid)
    if (typeof value === 'string' && !value) return callback(new Error(errorMsg), uuid, xid)
    if (typeof value === 'object' && JSON.stringify(value) === '{}') return callback(new Error(errorMsg), uuid, xid)
    return callback()
  }
}
export default WidgetRequiredValidator
""")
        self._write(ws_path, "src/validator/widget-regex-validator.js", """const WidgetRegexValidator = (regex, errorMsg) => {
  let reg
  try { reg = new RegExp(regex) } catch (e) { console.log(e) }
  if (!reg) return
  return (rule, value, callback) => {
    if (value && !reg.test(value)) { callback(new Error(errorMsg)) } else { callback() }
  }
}
export default WidgetRegexValidator
""")
        self._write(ws_path, "src/validator/widget-area-validator.js", """const WidgetAreaRequiredValidator = (errorMsg, uuid, xid) => {
  return (rule, widget, value, callback) => {
    if (!value) return callback(new Error(errorMsg), uuid, xid)
    if (!value.province || !value.province.code) return callback(new Error(errorMsg), uuid, xid)
    return callback()
  }
}
export { WidgetAreaRequiredValidator }
""")

        # ======== form-ability ========
        self._write(ws_path, "src/form-ability/index.js", """import AbilityFieldMap from './ability-field-map.config'
import AbilityFieldConvert from './ability-field-convert.config.js'
export { AbilityFieldMap, AbilityFieldConvert }
""")
        self._write(ws_path, "src/form-ability/ability-field-map.config.js",
                     "// eslint-disable-next-line\nconst AbilityControl = window.df.getVue().constructor.FormEngine.AbilityControl\nexport default {}\n")
        self._write(ws_path, "src/form-ability/ability-field-convert.config.js",
                     "// eslint-disable-next-line\nconst AbilityControl = window.df.getVue().constructor.FormEngine.AbilityControl\nexport default {}\n")

        # ======== i18n ========
        self._write(ws_path, "src/form-component-local/index.js", """import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
""")
        self._write(ws_path, "src/form-component-local/zh-CN/index.js", "export default { formComponent: {} }\n")
        self._write(ws_path, "src/form-component-local/en-US/index.js", "export default { formComponent: {} }\n")

        # ======== API ========
        self._write(ws_path, "src/api/index.js", """const Api = {
  // 在这里定义接口
}
export default Api
""")

    def _get_form_widget_mixin(self):
        """返回完整的 FormWidgetMixin 代码（平台标准实现）"""
        return """import WidgetRequiredValidator from '@/validator/widget-required-validator'
import WidgetRegexValidator from '@/validator/widget-regex-validator'

const debounce = window._.debounce
const XEventBus = window.APaaSSDK.context.XEventBus
const debounceWaitTime = 150
const AbilityControl = window.Vue.FormEngine.AbilityControl

const FormWidgetMixin = {
  data() {
    return {
      tabindex: '0', componentData: null, widgetRules: null, valueChanged: false,
      bsUnwatch: null,
      bsRefreshDebounce: debounce((newValue, oldValue) => {
        if (newValue !== oldValue) {
          let event
          if (this.widget.isInTable) {
            event = { currentRowTableUuid: this.widget.tableUuid, currentRowIndex: this.rowIndex, vm: this }
          }
          if (this.formEngine.engineContext.instance.documentId && this.widget.desensitization &&
              this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid] &&
              !this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed) {
            this.formEngine.formDataControl.dataMaskingValue[this.widget.uuid].changed = true
          }
          if (this.formEngine.formDataControl.dataFilterComponentList.triggerComponents.includes(this.widget.uuid)) {
            const dataSelectors = this.formEngine.formDataControl.dataFilterComponentList.dataSelectors
            Object.keys(dataSelectors).forEach((key) => {
              if (dataSelectors[key].includes(this.widget.uuid)) {
                XEventBus.emit('REFRESH_SELECT_BOX', { uuid: key, currentFormEngineKey: this.formEngine.engineContext.instance.instanceId })
              }
            })
          }
          try { this.formEngine.bsEventControl.triggerEventValueChange(this.widget, event) } catch (error) { console.error(error) }
        }
      }, 500),
      regexValidatorText: '',
      specialComponents: ['FORM_DATA_STATISTICS', 'FORM_SWITCH_SELECT'],
      debounceFormData: debounce(this.watchFormData, debounceWaitTime),
      debounceFormValue: debounce(this.watchFormValue, debounceWaitTime),
      debounceShowRequired: debounce(this.watchShowRequired, debounceWaitTime)
    }
  },
  props: {
    widget: { required: true },
    renderScene: { type: String, required: true, validator: (v) => ['ide', 'edit', 'read'].includes(v) },
    propKey: { type: String, default: '' },
    validateKey: { type: String, default: '' },
    validateInfo: { type: Object },
    formData: { type: Object },
    globalFormData: { type: Object },
    globalData: { type: Object },
    formItemList: { type: Array, default: () => [] },
    valueValidatedStatus: { type: Boolean, default: true },
    rowIndex: { type: Number },
    tableRowChangeFlag: { type: Boolean, default: false }
  },
  inject: ['renderGlobal', 'themeConfig'],
  computed: {
    formValue: {
      get() {
        this.valueChanged = false
        return this.valueValidatedStatus ? (this.propKey ? this.formData[this.propKey] : undefined) : undefined
      },
      set(value) {
        const { uuid } = this.widget
        if (!value && uuid) {
          const cc = this.formEngine.formDataControl.componentMap.get(uuid)
          cc.showDesensitizationMark = false
        }
        if (this.formData[this.propKey] !== value) {
          this.valueChanged = true
          this.$set(this.formData, this.propKey, value)
          if (!this.specialComponents.includes(this.widget.componentType) && this.formEngine) {
            this.formEngine.formDataControl.ctlFormDataChanged = true
          }
        }
      }
    },
    formEngine() { return this.renderGlobal },
    formEngineContext() { return (this.formEngine && this.formEngine.engineContext) || {} },
    validatorRules() {
      let rules = []
      if (this.renderScene === 'edit') {
        if (this.showRequired && !this.widget.hidden && this._validate) {
          rules.push(this._validate('required', this.widget.label + ' ' + this.$t('formWidget.common.requiredField')))
        }
        if (this.widget.validatorStatus && this.widget.validatorList && this.widget.validatorList[0] && this._validate) {
          rules.push(this._validate(WidgetRegexValidator(this.regexValidatorText, this.widget.validatorList[0].validatorMessage || '')))
        }
        if (this.widgetRules) rules = [...rules, ...this.widgetRules]
      }
      return rules
    },
    showRequired() { return this.widget.required && !this.widget.readOnly },
    webFormSettings() { return { widgetStyle: this.widget.widgetStyle || {}, border: this.widget.border || {} } }
  },
  watch: {
    showRequired: { handler(n, o) { this.debounceShowRequired(n, o) } },
    formDataWithoutTableData: { handler(n, o) { if (!this.widget.isInTable && n !== o) this.debounceFormData(this.formData) }, deep: true }
  },
  created() { this.debounceFormData(this.formData) },
  mounted() {
    if (this.renderScene === 'edit' || this.renderScene === 'read') {
      setTimeout(() => { this.addBsUnwatch() }, 0)
    }
  },
  beforeDestroy() { this.debounceShowRequired.cancel(); this.debounceFormData.cancel(); this.debounceFormValue.cancel() },
  destroyed() { if (this.bsUnwatch) this.bsUnwatch() },
  methods: {
    watchShowRequired() {},
    watchFormValue(n, o) { if (n !== o) { this.valueChanged = true; this.$formEventEmit('change', this.formValue) } },
    watchFormData(newValue) {
      if (newValue) {
        let td = ''
        if (this.widget.titleDescription && (!this.widget.titleDescriptionOptions || !this.widget.titleDescriptionOptions.length)) {
          td = this.widget.titleDescription
        } else {
          td = this.titleDesArrToText(newValue, this.widget.titleDescriptionOptions, AbilityControl.TITLE_DESCRIPTION_FORM_FIELD)
        }
        const cc = this.renderGlobal.formDataControl.getFormItemByUuid(this.widget.uuid)
        if (cc) this.$set(cc, 'titleDescription', td)
      }
    },
    addBsUnwatch() {
      if (this.widget.componentType === 'FORM_WIDGET_SON_TABLE' || this.widget.isInTable) return
      this.bsUnwatch = this.$watch(function() {
        let v = this.formValue
        if (v === null || v === undefined || (typeof v === 'string' && !v) || (Array.isArray(v) && !v.length)) return undefined
        try { return JSON.stringify(v) } catch (e) { return v }
      }, (n, o) => {
        if (n !== o) { this.debounceFormValue(n, o); if (!this.widget.isInTable) this.bsRefreshDebounce(n, o) }
      })
    },
    _validate(type, message, trigger = ['blur', 'change']) {
      const v = { trigger }
      if (typeof type === 'string') { v.type = type; if (type === 'required') v.validator = WidgetRequiredValidator(message); v.message = message }
      else if (typeof type === 'function') v.validator = type
      return v
    },
    updatePropValue(key, value) {
      if (Object.prototype.hasOwnProperty.call(this.formData, key) || (this.formEngine && this.formEngine.formDataControl.ctlComponentMap.has(key))) {
        const w = this.formEngine.formDataControl.ctlComponentMap.get(key)
        this.$set(this.formData, key, value); this.formData[key] = value
        this.$nextTick(() => { this.$emit('formEventEmit', { eventName: 'change', event: value, propKey: key, widget: w }) })
      }
    },
    $formEventEmit(eventName, event) {
      this.$emit(eventName, event)
      this.$emit('formEventEmit', { eventName, propKey: this.propKey, event, widget: this.widget })
    },
    titleDesArrToText(formData, arr, abilityCode) {
      let text = ''
      arr && arr.forEach((item) => {
        if (item.type === 'TEXT') text += item.value
        else if (item.type === 'COMP') {
          const allComps = this.formEngine.formDataControl.allTileFormItemList
          const cc = allComps && allComps.find(i => i.uuid === item.value)
          text += (AbilityControl.formatFiledValue({ fieldType: cc && cc.componentType, value: formData[item.value], fieldConfig: cc, fieldId: item.value, abilityCode }) || '')
        }
      })
      return text
    }
  }
}

export default FormWidgetMixin
"""

    # ------------------------------------------------------------------
    # Layout scaffold
    # ------------------------------------------------------------------
    def _scaffold_layout(self, ws_path: Path, name: str):
        """布局脚手架 - WEB_LAYOUT 架构"""
        self._write_common_files(ws_path, name, "LAYOUT")

        pascal = "".join(w.capitalize() for w in name.split("-"))
        output_name = f"apaas-custom-layout-{name}"

        # ======== package.json ========
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "LAYOUT",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js",
                "serve": "vue-cli-service serve src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build"
            },
            "dependencies": {
                "core-js": "3.8.3",
                "element-ui": "^2.15.14",
                "vue": "2.7.14"
            },
            "devDependencies": {
                "@babel/core": "7.12.16",
                "@babel/eslint-parser": "7.12.16",
                "@vue/cli-plugin-babel": "5.0.0",
                "@vue/cli-plugin-eslint": "5.0.0",
                "@vue/cli-service": "5.0.8",
                "dart-sass": "1.25.0",
                "eslint": "7.32.0",
                "eslint-plugin-vue": "8.0.3",
                "sass": "1.85.1",
                "sass-loader": "8.0.2",
                "vue-template-compiler": "2.7.14"
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {}
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        }, indent=2, ensure_ascii=False))

        # ======== vue.config.js ========
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const path = require('path')
const apaasJson = require('./src/apaas.json')

const isPreview = process.env.VUE_APP_PREVIEW === 'true'

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: isPreview ? 8090 : 8080,
    hot: true,
    allowedHosts: 'all',
    ...(isPreview ? {} : {
      https: (() => {
        const keyPath = './https/server.key'
        const certPath = './https/server.crt'
        if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
          return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
        }
        return false
      })()
    }),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: (config) => {
    if (isPreview) {
      delete config.output.library
      delete config.output.libraryTarget
    } else {
      config.output.library = apaasJson.outputName
      config.output.libraryTarget = 'umd'
    }
  },
  chainWebpack: (config) => {
    if (isPreview) {
      config.plugin('html').tap(args => {
        args[0].template = path.resolve(__dirname, 'preview/index.html')
        return args
      })
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
""")

        # ======== babel.config.js ========
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        # ======== src/apaas.json ========
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "layout": [{"name": output_name, "desc": name, "status": "ENABLE"}],
            "outputName": output_name
        }, indent=2, ensure_ascii=False))

        # ======== src/index.js ========
        self._write(ws_path, "src/index.js", f"""import Home from './Home.vue'

const install = function (Vue) {{
  const layoutId = '{output_name}'
  const layoutEngine = Vue.LayoutEngine.getInstance(layoutId)
  Vue.component(layoutId, Home)
  layoutEngine.registerLayoutComponent(Home)
}}

export default {{ install }}
""")

        # ======== src/Home.vue ========
        self._write(ws_path, "src/Home.vue", f"""<template>
  <x-app-layout>
    <template #header>
      <slot name="header">
        <div class="layout-header">Header</div>
      </slot>
    </template>
    <template #menu>
      <slot name="menu">
        <div class="layout-menu">Menu</div>
      </slot>
    </template>
    <template #appPage>
      <slot name="appPage">
        <div class="layout-app-page">Content</div>
      </slot>
    </template>
  </x-app-layout>
</template>

<script>
export default {{
  name: '{pascal}Layout',
}}
</script>

<style scoped>
.layout-header {{
  padding: 10px 20px;
  background: #f5f7fa;
}}
.layout-menu {{
  width: 200px;
  background: #fafafa;
}}
.layout-app-page {{
  flex: 1;
  padding: 20px;
}}
</style>
""")

    # ------------------------------------------------------------------
    # Plugin scaffold
    # ------------------------------------------------------------------
    def _scaffold_plugin(self, ws_path: Path, name: str):
        """插件脚手架 - WEB_PLUGIN 架构"""
        self._write_common_files(ws_path, name, "PLUGIN")

        pascal = "".join(w.capitalize() for w in name.split("-"))
        name_upper = name.replace("-", "_").upper()
        output_name = f"apaas-custom-{name}"

        # ======== package.json ========
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "PLUGIN",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js",
                "serve": "vue-cli-service serve src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build"
            },
            "dependencies": {
                "core-js": "3.8.3",
                "element-ui": "^2.15.14",
                "vue": "2.7.14"
            },
            "devDependencies": {
                "@babel/core": "7.12.16",
                "@babel/eslint-parser": "7.12.16",
                "@vue/cli-plugin-babel": "5.0.0",
                "@vue/cli-plugin-eslint": "5.0.0",
                "@vue/cli-service": "5.0.8",
                "dart-sass": "1.25.0",
                "eslint": "7.32.0",
                "eslint-plugin-vue": "8.0.3",
                "sass": "1.85.1",
                "sass-loader": "8.0.2",
                "vue-template-compiler": "2.7.14"
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {}
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        }, indent=2, ensure_ascii=False))

        # ======== vue.config.js ========
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const path = require('path')
const apaasJson = require('./src/apaas.json')

const isPreview = process.env.VUE_APP_PREVIEW === 'true'

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: isPreview ? 8090 : 8080,
    hot: true,
    allowedHosts: 'all',
    ...(isPreview ? {} : {
      https: (() => {
        const keyPath = './https/server.key'
        const certPath = './https/server.crt'
        if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
          return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
        }
        return false
      })()
    }),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: (config) => {
    if (isPreview) {
      delete config.output.library
      delete config.output.libraryTarget
    } else {
      config.output.library = apaasJson.outputName
      config.output.libraryTarget = 'umd'
    }
  },
  chainWebpack: (config) => {
    if (isPreview) {
      config.plugin('html').tap(args => {
        args[0].template = path.resolve(__dirname, 'preview/index.html')
        return args
      })
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
""")

        # ======== babel.config.js ========
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        # ======== src/apaas.json ========
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "extensionConfigList": [{"code": f"CUSTOM_{name_upper}_EXTENSION", "text": name}],
            "outputName": output_name
        }, indent=2, ensure_ascii=False))

        # ======== src/index.js ========
        self._write(ws_path, "src/index.js", f"""import extensionConfig from './extension'
import CustomPanel from './custom-tab/custom-panel.vue'
import {{ localMessages }} from './local'

const install = function (Vue) {{
  // Register i18n
  const i18n = window.APaaSSDK?.context?.globalVueI18n
  if (i18n) Object.keys(localMessages).forEach(lang => i18n.mergeLocaleMessage(lang, localMessages[lang]))

  // Register component
  Vue.component('CustomPanel{pascal}', CustomPanel)

  // Register extension
  if (Vue._extensionEngine) Vue._extensionEngine.registerExtensionConfig(extensionConfig)
}}

export default {{ install }}
""")

        # ======== src/extension.js ========
        self._write(ws_path, "src/extension.js", f"""export default {{
  code: 'CUSTOM_{name_upper}_EXTENSION',
  blocks: [],
  funs: [],
  versions: ['V1'],
  extensionMethods: {{}}
}}
""")

        # ======== src/custom-tab/custom-panel.vue ========
        self._write(ws_path, "src/custom-tab/custom-panel.vue", f"""<template>
  <div class="custom-panel-{name}">
    <h3>{{{{ title }}}}</h3>
    <div class="panel-content">
      <slot />
    </div>
  </div>
</template>

<script>
export default {{
  name: 'CustomPanel{pascal}',
  data() {{
    return {{
      title: '{name} Plugin Panel',
    }}
  }},
}}
</script>

<style scoped>
.custom-panel-{name} {{
  padding: 16px;
}}
.panel-content {{
  margin-top: 12px;
}}
</style>
""")

        # ======== src/local/index.js ========
        self._write(ws_path, "src/local/index.js", f"""export const localMessages = {{
  'zh-CN': {{
    '{name}': {{
      title: '{name}',
    }},
  }},
  'en-US': {{
    '{name}': {{
      title: '{name}',
    }},
  }},
}}
""")

    def _scaffold_form_page(self, ws_path: Path, name: str, mobile: bool = False):
        """菜单页面脚手架 - 完整 MENU_PAGE 架构（带筛选+表格+分页+多选+getSelectedData）"""
        # 公共文件
        self._write_common_files(ws_path, name, "MENU_PAGE")

        # 组件标签名
        # name 格式: form-page-xxx-yyy
        kebab = name.replace("form-page-", "")
        component_tag = f"apaas-custom-{kebab}"

        # ======== package.json ========
        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "MENU_PAGE",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js",
                "serve": "vue-cli-service serve src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build"
            },
            "dependencies": {
                "core-js": "3.8.3",
                "element-ui": "^2.15.14",
                "vue": "2.7.14"
            },
            "devDependencies": {
                "@babel/core": "7.12.16",
                "@babel/eslint-parser": "7.12.16",
                "@vue/cli-plugin-babel": "5.0.0",
                "@vue/cli-plugin-eslint": "5.0.0",
                "@vue/cli-service": "5.0.8",
                "dart-sass": "1.25.0",
                "eslint": "7.32.0",
                "eslint-plugin-vue": "8.0.3",
                "sass": "1.85.1",
                "sass-loader": "8.0.2",
                "vue-template-compiler": "2.7.14"
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {}
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        }, indent=2, ensure_ascii=False))

        # ======== vue.config.js ========
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const path = require('path')
const apaasJson = require('./src/apaas.json')

const isPreview = process.env.VUE_APP_PREVIEW === 'true'

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: isPreview ? 8090 : 8080,
    hot: true,
    allowedHosts: 'all',
    ...(isPreview ? {} : {
      https: (() => {
        const keyPath = './https/server.key'
        const certPath = './https/server.crt'
        if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
          return { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
        }
        return false
      })()
    }),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false },
    proxy: {
      '/custom': {
        target: 'http://localhost:9092',
        changeOrigin: true
      }
    }
  },
  configureWebpack: (config) => {
    if (isPreview) {
      delete config.output.library
      delete config.output.libraryTarget
    } else {
      config.output.library = apaasJson.outputName
      config.output.libraryTarget = 'umd'
    }
  },
  chainWebpack: (config) => {
    if (isPreview) {
      config.plugin('html').tap(args => {
        args[0].template = path.resolve(__dirname, 'preview/index.html')
        return args
      })
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
""")

        # ======== babel.config.js ========
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        # ======== src/apaas.json ========
        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "templateType": "MENU_PAGE",
            "router": {
                component_tag: {
                    "name": component_tag,
                    "path": component_tag
                }
            },
            "customWidgetList": [],
            "copyAssets": [f"public/form-page/{name}"],
            "outputName": name
        }, indent=2, ensure_ascii=False))

        # ======== src/index.js ========
        self._write(ws_path, "src/index.js", f"""import "./form-page-local/index.js";
import ApaasCustomPage from "./form-page/{component_tag}.vue";

const install = function (Vue) {{
  Vue.component("{component_tag}", ApaasCustomPage);
  window[Symbol.for("{component_tag}")] = ApaasCustomPage;
}};

export default {{ install }};
""")

        # ======== src/api/index.js ========
        self._write(ws_path, "src/api/index.js", """const Api = {
  QUERY_LIST: {
    url: '/custom/demo/list',
    method: 'POST',
    disableSuccessMsg: true,
  },
}

export default Api
""")

        # ======== src/form-page/component.vue ========
        self._write(ws_path, f"src/form-page/{component_tag}.vue", f"""<template>
  <div class="{component_tag}">

    <!-- 筛选区 -->
    <div class="filter-area">
      <el-input
        v-model="filterForm.keyword"
        placeholder="请输入关键词"
        size="small"
        clearable
        style="width: 220px"
      />
    </div>

    <!-- 查询 / 重置 -->
    <div class="filter-actions">
      <el-button type="primary" size="small" @click="handleQuery">查询</el-button>
      <el-button size="small" @click="handleReset">重置</el-button>
    </div>

    <!-- 已选提示条（弹窗选择场景需要） -->
    <div class="selected-bar">
      <span class="selected-bar-title">
        已选数据
        <span v-if="selectedRows.length" class="selected-badge">{{{{ selectedRows.length }}}}</span>
      </span>
      <template v-if="selectedRows.length === 0">
        <span class="selected-bar-empty">暂未选择</span>
      </template>
      <template v-else>
        <div class="selected-bar-tags">
          <span v-for="row in selectedRows" :key="row.id" class="bar-tag">
            <span class="bar-tag-label">{{{{ row.name || row.id }}}}</span>
            <span class="bar-tag-close" @click="removeSelected(row)">&times;</span>
          </span>
        </div>
        <span class="bar-clear" @click="clearAllSelected">清空</span>
      </template>
    </div>

    <!-- 数据表格 -->
    <div class="table-wrapper" style="overflow-y:auto; flex:1; min-height:0;">
      <el-table
        ref="elTable"
        :data="tableConfig.tableData || []"
        border
        style="width:100%;"
        :max-height="tableConfig.maxHeight || undefined"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" fixed />
        <el-table-column type="index" label="序" width="50" fixed :index="indexStart" />
        <el-table-column
          v-for="col in visibleCols"
          :key="col.columnKey"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.minWidth || 120"
          show-overflow-tooltip
        />
      </el-table>
      <el-pagination
        v-if="tableConfig.pagination"
        style="margin-top: 8px; text-align: right; padding: 4px 0"
        :current-page="tableConfig.pagination.currentPage"
        :page-size="tableConfig.pagination.pageSize"
        :total="tableConfig.pagination.total"
        :page-sizes="[10, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="onSizeChange"
        @current-change="onCurrentPageChange"
      />
    </div>

  </div>
</template>

<script>
import Api from "../api";

export default {{
  name: "{component_tag}",

  data() {{
    return {{
      filterForm: {{
        keyword: "",
      }},
      selectedRows: [],

      tableConfig: {{
        maxHeight: "500",
        colConfigs: [
          {{ prop: "name", columnKey: "name", displayFlag: true, label: "名称", minWidth: 150 }},
          {{ prop: "code", columnKey: "code", displayFlag: true, label: "编码", minWidth: 150 }},
          {{ prop: "status", columnKey: "status", displayFlag: true, label: "状态", minWidth: 100 }},
        ],
        tableData: [],
        pagination: {{
          currentPage: 1,
          pageSize: 10,
          total: 0,
        }},
      }},
    }};
  }},

  computed: {{
    visibleCols() {{
      return (this.tableConfig.colConfigs || []).filter((c) => c.displayFlag);
    }},
    indexStart() {{
      const p = this.tableConfig.pagination;
      if (!p) return 1;
      return (p.currentPage - 1) * p.pageSize + 1;
    }},
  }},

  created() {{
    this.loadTableData();
  }},

  methods: {{
    loadTableData() {{
      const {{ currentPage, pageSize }} = this.tableConfig.pagination;
      this.$request({{
        ...Api.QUERY_LIST,
        params: {{
          page: currentPage,
          pageSize,
          keyword: this.filterForm.keyword,
        }},
      }})
        .asyncThen((resp) => {{
          const list = resp && resp.data ? resp.data : [];
          const total = resp && resp.total ? resp.total : 0;
          this.$set(this.tableConfig, "tableData", list);
          this.$set(this.tableConfig.pagination, "total", total);
          const selectedIds = this.selectedRows.map((r) => r.id);
          if (selectedIds.length) {{
            this.reapplySelection(selectedIds);
          }}
        }})
        .asyncErrorCatch((error) => {{
          console.error("加载数据失败:", error);
        }});
    }},

    handleQuery() {{
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    }},

    handleReset() {{
      this.filterForm.keyword = "";
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    }},

    onSizeChange(size) {{
      this.$set(this.tableConfig.pagination, "pageSize", size);
      this.$set(this.tableConfig.pagination, "currentPage", 1);
      this.loadTableData();
    }},

    onCurrentPageChange(page) {{
      this.$set(this.tableConfig.pagination, "currentPage", page);
      this.loadTableData();
    }},

    handleSelectionChange(rows) {{
      const currentPageIds = new Set(
        (this.tableConfig.tableData || []).map((r) => r.id)
      );
      const otherPageRows = this.selectedRows.filter(
        (r) => !currentPageIds.has(r.id)
      );
      this.selectedRows = [
        ...otherPageRows,
        ...(Array.isArray(rows) ? rows : []),
      ];
    }},

    reapplySelection(selectedIds) {{
      this.$nextTick(() => {{
        const table = this.$refs.elTable;
        if (!table) return;
        table.clearSelection();
        (this.tableConfig.tableData || []).forEach((row) => {{
          if (selectedIds.includes(row.id)) {{
            table.toggleRowSelection(row, true);
          }}
        }});
      }});
    }},

    removeSelected(row) {{
      this.selectedRows = this.selectedRows.filter((r) => r.id !== row.id);
      const table = this.$refs.elTable;
      const tableData = this.tableConfig.tableData || [];
      const found = tableData.find((r) => r.id === row.id);
      if (found && table) {{
        table.toggleRowSelection(found, false);
      }}
    }},

    clearAllSelected() {{
      this.selectedRows = [];
      const table = this.$refs.elTable;
      if (table) table.clearSelection();
    }},

    /**
     * 供弹窗"确定"按钮调用，返回当前所有已选行数据
     */
    getSelectedData() {{
      return this.selectedRows;
    }},
  }},
}};
</script>

<style lang="scss">
.{component_tag} {{
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px;
  overflow: hidden;

  .filter-area {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
    flex-wrap: wrap;
  }}

  .filter-actions {{
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-shrink: 0;
  }}

  .selected-bar {{
    display: flex;
    align-items: flex-start;
    gap: 8px;
    flex-shrink: 0;
    padding: 6px 10px;
    background: #f0f7ff;
    border: 1px solid #b3d8ff;
    border-radius: 4px;
    font-size: 13px;
    min-height: 36px;
    max-height: 72px;
    overflow-y: auto;

    .selected-bar-title {{
      font-weight: 600;
      color: #303133;
      white-space: nowrap;
      flex-shrink: 0;

      .selected-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        background: #409eff;
        color: #fff;
        border-radius: 9px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 4px;
      }}
    }}

    .selected-bar-empty {{ color: #c0c4cc; font-style: italic; }}

    .selected-bar-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      flex: 1;

      .bar-tag {{
        display: inline-flex;
        align-items: center;
        gap: 3px;
        height: 22px;
        padding: 0 6px;
        background: #fff;
        border: 1px solid #b3d8ff;
        border-radius: 3px;
        font-size: 12px;
        color: #409eff;

        .bar-tag-label {{ max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .bar-tag-close {{ cursor: pointer; color: #909399; &:hover {{ color: #f56c6c; }} }}
      }}
    }}

    .bar-clear {{
      margin-left: auto;
      color: #909399;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      flex-shrink: 0;
      &:hover {{ color: #f56c6c; }}
    }}
  }}
}}

.x-lov-modal {{
  .{component_tag} {{
    // 弹窗内高度有限，按需压缩各区域
  }}
}}
</style>
""")

        # ======== src/form-page-local/ (国际化) ========
        self._write(ws_path, "src/form-page-local/index.js", """import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df && window.df.getI18n && window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
""")
        self._write(ws_path, "src/form-page-local/zh-CN/index.js", """export default {
  formPage: {},
};
""")
        self._write(ws_path, "src/form-page-local/en-US/index.js", """export default {
  formPage: {},
};
""")

        # ======== preview/ (本地预览环境) ========
        self._write(ws_path, "preview/index.html", """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>本地预览</title>
</head>
<body>
  <div id="app"></div>
</body>
</html>
""")

        self._write(ws_path, "preview/App.vue", f"""<template>
  <div style="min-height: 100vh;">
    <{component_tag} />
  </div>
</template>

<script>
export default {{ name: 'PreviewApp' }}
</script>
""")

        self._write(ws_path, "preview/main.js", f"""import Vue from 'vue'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'

import {{ installMockRequest }} from './mock-api'
import ApaasCustomPage from '../src/form-page/{component_tag}.vue'
import App from './App.vue'

Vue.use(ElementUI)

// 注入 $request mock
installMockRequest(Vue)

// 注册业务组件
Vue.component('{component_tag}', ApaasCustomPage)

new Vue({{
  el: '#app',
  render: h => h(App)
}})
""")

        self._write(ws_path, "preview/mock-api.js", """/**
 * 模拟平台 $request：通过 devServer proxy 转发到后端
 * 支持 .asyncThen().asyncErrorCatch() 链式调用（与平台行为一致）
 */
export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    const ctrl = {}

    const promise = fetch(config.url, {
      method: (config.method || 'GET').toUpperCase(),
      headers: { 'Content-Type': 'application/json' },
      body: config.params != null ? JSON.stringify(config.params) : undefined
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status)
      return res.json()
    })

    ctrl.asyncThen = function (onSuccess, onError) {
      promise.then(onSuccess).catch(onError || function () {})
      return ctrl
    }

    ctrl.asyncErrorCatch = function (onError) {
      promise.catch(onError)
      return ctrl
    }

    return ctrl
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

    # ======== 轻量级脚手架（脚本 & 业务弹窗）========

    def _scaffold_script_js(self, ws_path: Path, name: str):
        """JavaScript 脚本扩展脚手架 - 仅生成 src/script.js"""
        self._write(ws_path, "src/script.js", f"""\
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
""")

    def _scaffold_script_python(self, ws_path: Path, name: str):
        """Python 脚本扩展脚手架 - 仅生成 src/script.py"""
        self._write(ws_path, "src/script.py", f"""\
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
""")

    def _scaffold_script_groovy(self, ws_path: Path, name: str):
        """Groovy 脚本扩展脚手架 - 仅生成 src/script.groovy"""
        self._write(ws_path, "src/script.groovy", f"""\
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
""")

    def _scaffold_business_dialog(self, ws_path: Path, name: str):
        """业务事件自定义弹窗脚手架 - 仅生成 src/setting.js"""
        self._write(ws_path, "src/setting.js", f"""\
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
""")

    def _scaffold_ui_style(self, ws_path: Path, name: str):
        """UI 样式扩展脚手架 — 轻量，仅生成 CSS 文件"""
        self._write(ws_path, "src/style.css", f"""/**
 * UI 样式扩展 - {name}
 * 使用 .form-custom-style 作用域，或 [data-component-id="xxx"] 定位字段
 */

.form-custom-style {{
  .el-form-item__label {{ font-weight: 600; }}
  .el-input__inner {{ border-radius: 6px; }}
}}
""")

    def _scaffold_list_custom_module(self, ws_path: Path, name: str):
        """列表自定义模块脚手架 — 轻量，生成 Vue 模板 + SCSS"""
        pascal = "".join(w.capitalize() for w in name.split("-"))
        self._write(ws_path, "src/module-template.vue", f"""<template>
  <div class="list-custom-module-{name}">
    <div v-for="(item, idx) in listData" :key="idx" class="module-item">
      {{{{ item.name || '-' }}}}
    </div>
    <div v-if="!listData.length" class="module-empty">暂无数据</div>
  </div>
</template>
<script>
export default {{
  name: '{pascal}Module',
  props: {{ lowCodeContext: {{ type: Object, default: () => ({{}}) }} }},
  data() {{ return {{ listData: [], total: 0 }} }},
  mounted() {{
    const cfg = this.lowCodeContext?.pageViewConfig
    if (cfg) {{ this.listData = cfg.data || []; this.total = cfg.total || 0 }}
  }},
}}
</script>
""")
        self._write(ws_path, "src/module-style.scss", f""".list-custom-module-{name} {{
  padding: 16px;
  .module-item {{ padding: 10px 12px; border-bottom: 1px solid #ebeef5; font-size: 14px; }}
  .module-empty {{ text-align: center; color: #c0c4cc; padding: 40px 0; }}
}}
""")

    def _scaffold_web_login(self, ws_path: Path, name: str):
        """自定义登录页脚手架 — 完整 Vue 项目"""
        self._write_common_files(ws_path, name, "WEB_LOGIN")

        full_name = f"apaas-custom-{name}"
        pascal = "".join(w.capitalize() for w in name.split("-"))

        # package.json
        self._write(ws_path, "package.json", json.dumps({{
            "name": full_name,
            "version": "1.0.0",
            "private": True,
            "scripts": {{
                "serve": "vue-cli-service serve src/index.js",
                "build": "vue-cli-service build",
            }},
            "dependencies": {{
                "core-js": "^3.8.3", "vue": "^2.7.14", "element-ui": "^2.15.14",
            }},
            "devDependencies": {{
                "@vue/cli-service": "~5.0.0",
                "@vue/cli-plugin-babel": "~5.0.0",
                "sass": "^1.32.7", "sass-loader": "^12.0.0",
            }},
        }}, indent=2))

        # vue.config.js
        self._write(ws_path, "vue.config.js", f"""const path = require('path')
module.exports = {{
  outputDir: 'dist',
  configureWebpack: {{
    output: {{ library: '{full_name}', libraryTarget: 'umd', jsonpFunction: 'webpackJsonp_{full_name.replace("-","_")}' }},
    resolve: {{ alias: {{ '@': path.resolve(__dirname, 'src') }} }},
  }},
  devServer: {{ port: 8080, https: true, headers: {{ 'Access-Control-Allow-Origin': '*' }} }},
}}
""")

        # babel.config.js
        self._write(ws_path, "babel.config.js", "module.exports = { presets: ['@vue/cli-plugin-babel/preset'] }\n")

        # src/apaas.json
        self._write(ws_path, "src/apaas.json", json.dumps({{
            "entry": "index.js",
            "router": {{full_name: full_name}},
            "outputName": full_name,
        }}, indent=2, ensure_ascii=False))

        # src/index.js
        self._write(ws_path, "src/index.js", f"""import LoginPage from './login.vue'
const install = function(Vue) {{ Vue.component('{full_name}', LoginPage) }}
export default {{ install }}
""")

        # src/login.vue
        self._write(ws_path, "src/login.vue", f"""<template>
  <div class="custom-login-page">
    <div class="login-box">
      <h1>系统登录</h1>
      <el-form ref="form" :model="form" :rules="rules">
        <el-form-item prop="username">
          <el-input v-model="form.username" prefix-icon="el-icon-user" placeholder="账号" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" prefix-icon="el-icon-lock" placeholder="密码"
            type="password" show-password @keyup.enter.native="handleLogin" />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width:100%" @click="handleLogin">登 录</el-button>
      </el-form>
    </div>
  </div>
</template>
<script>
export default {{
  name: '{pascal}Login',
  data() {{
    return {{
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
      this.$refs.form.validate(async (valid) => {{
        if (!valid) return
        this.loading = true
        try {{
          // TODO: 调用登录接口
        }} catch (e) {{
          this.$message.error(e.message || '登录失败')
        }} finally {{ this.loading = false }}
      }})
    }},
  }},
}}
</script>
<style scoped>
.custom-login-page {{ min-height:100vh; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#667eea,#764ba2); }}
.login-box {{ width:400px; padding:40px; background:#fff; border-radius:12px; box-shadow:0 20px 60px rgba(0,0,0,.15); }}
.login-box h1 {{ text-align:center; margin:0 0 30px; font-size:28px; color:#303133; }}
</style>
""")

        # env.tmpl.js
        self._write(ws_path, "env.tmpl.js", """window.GLOBAL_ENV = {
  ENV: '${ENV}',
  SSO_URL: '${SSO_URL}',
  API_BASE: '${API_BASE}',
}
""")

    def _generate_https_cert(self, ws_path: Path):
        """生成 HTTPS 自签名证书（debug 模式需要 HTTPS）"""
        https_dir = ws_path / "https"
        if (https_dir / "server.key").exists():
            return  # 已存在，跳过
        https_dir.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess
            # 生成自签名证书
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(https_dir / "server.key"),
                "-out", str(https_dir / "server.crt"),
                "-days", "365", "-nodes",
                "-subj", "/CN=localhost"
            ], check=True, capture_output=True)
            # 生成 CSR（可选，部分参考项目有）
            subprocess.run([
                "openssl", "req", "-new",
                "-key", str(https_dir / "server.key"),
                "-out", str(https_dir / "server.csr"),
                "-subj", "/CN=localhost"
            ], check=True, capture_output=True)
        except Exception as e:
            print(f"[WARN] 生成 HTTPS 证书失败: {e}，debug 模式可能需要手动添加证书")

    def _write(self, base_path: Path, rel_path: str, content: str):
        """写文件，自动创建目录"""
        target = base_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
