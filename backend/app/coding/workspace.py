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
                          output_name: str, custom_widget_list: list) -> dict:
        """启动 Puppeteer debug 模式，注入组件到平台"""
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

        # 生成 debug 脚本
        debug_script = f"""
const path = require('path')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:{serve_port}/'
const targetServerRunningAt = '{platform_url}'
const targetEnv = 'platform'
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
  const injectParams = {{ localServerRunningAt, outputName, targetEnv, customWidgetList, tenantId, appId }}
  const injectCall = `${{INJECT_CODE}}(${{JSON.stringify(injectParams)}})`
  await page.evaluateOnNewDocument(injectCall)
  try {{
    await page.goto(targetServerRunningAt, {{ waitUntil: 'domcontentloaded', timeout: 120000 }})
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

        return {
            "status": "ok",
            "message": f"Debug 已启动，请在打开的 Chromium 中登录平台后 F5 刷新",
            "serve_port": serve_port,
            "platform_url": platform_url,
        }

    async def start_auto_debug(self, ws_id: str, serve_port: int,
                                platform_url: str, tenant_id: str, app_id: str,
                                output_name: str, custom_widget_list: list) -> dict:
        """启动自动化 Debug：自动登录 + 导航 + 截图 + 组件注入"""
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

        form_url = f"{platform_url}{tenant_id}/default/data-model-fn-config?appId={app_id}&menuId=819626319129083904&formId=69b138fe49b6ac36772fa040"
        login_url = f"{platform_url}account/login"

        debug_script = f"""
const path = require('path')
const fs = require('fs')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:{serve_port}/'
const targetServerRunningAt = '{platform_url}'
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
    const injectParams = {{ localServerRunningAt, outputName, targetEnv: 'platform', customWidgetList, tenantId, appId }}
    const injectCall = `${{INJECT_CODE}}(${{JSON.stringify(injectParams)}})`
    await page.evaluateOnNewDocument(injectCall)

    // Step 4: Navigate to form designer
    console.log('[AUTO-DEBUG] Navigating to form designer...')
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

    # ========== 脚手架模板 ==========

    def _scaffold_form_component(self, ws_path: Path, name: str):
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
