"""
Workspace Manager - 管理aPaaS自开发项目的工作区
负责项目创建、模板脚手架、文件读写、依赖安装、构建
"""

import os
import json
import shutil
import asyncio
import inspect
import logging
import subprocess
import tempfile
import re
import uuid
import hashlib
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union
from enum import Enum

from app.coding.form_component_editor import normalize_form_component_editor_artifacts
from app.coding.runtime_env import ensure_node_tool_env, resolve_executable

logger = logging.getLogger(__name__)

# 工作区根目录
REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE_ROOT = REPO_ROOT / "workspaces"


def _resolve_workspace_root() -> Path:
    explicit_root = (os.environ.get("APAAS_WORKSPACE_ROOT") or "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser()

    # df-apaas-cli build 会把 entry 直接拼进 shell 命令里，路径里如果包含空格，
    # vue-cli-service 会把 entry 拆坏，最终在 code-server 内触发 EISDIR。
    if " " in str(LEGACY_WORKSPACE_ROOT):
        return Path.home() / ".apaas-builder-ai" / "workspaces"

    return LEGACY_WORKSPACE_ROOT


WORKSPACE_ROOT = _resolve_workspace_root()

# vibe-serve.js — 包装 vue-cli-service serve，完成后打印公网 proxy 地址
_VIBE_SERVE_JS = """\
'use strict'
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

let proxyBase = ''
try {
  const cfg = fs.readFileSync(path.join(__dirname, 'vibe-serve-config'), 'utf8')
  const m = cfg.match(/^PROXY_BASE=(.+)$/m)
  if (m) proxyBase = m[1].trim()
} catch (_) {}

const args = ['vue-cli-service', 'serve', ...process.argv.slice(2)]
const proc = spawn('npx', args, { cwd: __dirname, stdio: ['inherit', 'pipe', 'pipe'], env: process.env })

let announced = false
function handleLine(line) {
  process.stdout.write(line + '\\n')
  if (!announced) {
    const m = line.match(/Local:\\s+https?:\\/\\/localhost:(\\d+)/)
    if (m) {
      if (proxyBase) process.stdout.write('  - Public:  ' + proxyBase + '/proxy/' + m[1] + '/\\n')
      announced = true
    }
  }
}
function pipeStream(s) {
  let buf = ''
  s.setEncoding('utf8')
  s.on('data', c => { buf += c; const lines = buf.split('\\n'); buf = lines.pop(); lines.forEach(handleLine) })
  s.on('end', () => { if (buf) handleLine(buf) })
}
pipeStream(proc.stdout)
pipeStream(proc.stderr)
proc.on('exit', code => process.exit(code ?? 0))
"""

WORKSPACE_SEARCH_ROOTS = tuple(
    root for idx, root in enumerate((WORKSPACE_ROOT, LEGACY_WORKSPACE_ROOT))
    if root not in (WORKSPACE_ROOT, LEGACY_WORKSPACE_ROOT)[:idx]
)
DEPENDENCY_CACHE_ROOT = WORKSPACE_ROOT / ".dependency-cache"
NPM_CACHE_ROOT = WORKSPACE_ROOT / ".npm-cache"
DEFAULT_RULES_ROOT = Path(__file__).parent / "default_rules"
FALLBACK_NPM_REGISTRY = "https://registry.npmmirror.com"

# 得帆私有 npm 源（group 仓库：既供私有 @x-apaas/* scoped 包，也代理公共包）。
# df-apaas-cli 脚手架（@x-apaas/df-apaas-cli）只发布在这里——公共源（npmmirror/npmjs）
# 必然 404；且必须用 scoped 包名，裸名 df-apaas-cli 在任何源（含私有源）都 404。
APAAS_SCOPE = "@x-apaas"
APAAS_PRIVATE_NPM_REGISTRY_FALLBACK = "https://registry.dfy.definesys.cn/repository/apaas-npm-group/"


def _safe_read_json(path: Path, default=None):
    """安全读取 JSON 文件。文件不存在、读取失败或解析失败时返回 default。

    替代散落各处的 `try: json.loads(path.read_text(...)) except Exception: fallback` 模式，
    集中处理错误语义（静默失败，不打日志 — 调用方有需要可自行 warn）。
    """
    if default is None:
        default = {}
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


@lru_cache(maxsize=1)
def _resolve_default_npm_registry() -> str:
    explicit_registry = (
        os.environ.get("APAAS_NPM_REGISTRY")
        or os.environ.get("npm_config_registry")
        or os.environ.get("NPM_CONFIG_REGISTRY")
        or ""
    ).strip()
    if explicit_registry:
        return explicit_registry

    try:
        env = ensure_node_tool_env()
        npm_exec = resolve_executable("npm", env)
        if not npm_exec:
            return FALLBACK_NPM_REGISTRY
        result = subprocess.run(
            [npm_exec, "config", "get", "registry"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        resolved_registry = (result.stdout or "").strip()
        if result.returncode == 0 and resolved_registry and resolved_registry != "undefined":
            return resolved_registry
    except Exception:
        pass

    return FALLBACK_NPM_REGISTRY


DEFAULT_NPM_REGISTRY = _resolve_default_npm_registry()


def _resolve_apaas_private_npm_registry() -> str:
    """@x-apaas/* scoped 包（含 df-apaas-cli 脚手架）的私有源。

    允许用 APAAS_PRIVATE_NPM_REGISTRY 环境变量覆盖（如换 Nexus 地址），
    默认走得帆 apaas-npm-group。注意：这是给 scoped 包用的，公共依赖仍走
    DEFAULT_NPM_REGISTRY（npmmirror）以保证速度。
    """
    explicit = (os.environ.get("APAAS_PRIVATE_NPM_REGISTRY") or "").strip()
    return explicit or APAAS_PRIVATE_NPM_REGISTRY_FALLBACK


APAAS_PRIVATE_NPM_REGISTRY = _resolve_apaas_private_npm_registry()

DISPLAY_NAME_HINTS = {
    "gantt-chart": "甘特图组件",
    "approval-flow": "审批流程组件",
    "approval": "审批组件",
    "progress-bar": "进度条组件",
    "star-rating": "评分组件",
    "color-picker": "颜色选择器",
    "tag-input": "标签输入组件",
    "chart-analysis": "图表分析组件",
    "chart": "图表组件",
    "date-picker": "日期选择器",
    "date-range": "日期范围选择器",
    "file-upload": "文件上传组件",
    "upload": "上传组件",
    "avatar": "头像组件",
    "signature": "签名组件",
    "qrcode": "二维码组件",
    "map-view": "地图页面",
    "rich-text": "富文本组件",
    "tree-select": "树形选择器",
    "cascader": "级联选择器",
    "data-table": "数据表格组件",
    "kanban": "看板页面",
    "data-query": "数据查询页面",
    "popup-select": "弹窗选择器",
    "person-select": "人员选择器",
    "image-recognition": "图片识别组件",
    "screenshot": "截图组件",
    "ai-analysis": "AI分析组件",
    "camera": "拍照组件",
    "watermark": "水印组件",
    "countdown": "倒计时组件",
    "steps": "步骤条组件",
    "timeline": "时间轴组件",
    "carousel": "轮播组件",
    "drawer": "抽屉组件",
    "material-select": "物料选择器",
    "map-picker": "地图选点组件",
    "supplier-mgmt": "供应商管理页面",
    "supplier": "供应商页面",
    "purchase-mgmt": "采购管理页面",
    "purchase": "采购页面",
    "customer-mgmt": "客户管理页面",
    "customer": "客户页面",
    "work-order-mgmt": "工单管理页面",
    "work-order": "工单页面",
    "dispatch-mgmt": "派工管理页面",
    "dispatch": "派工页面",
    "smart-dispatch": "智能派工页面",
    "order-mgmt": "订单管理页面",
    "order": "订单页面",
    "inventory-mgmt": "库存管理页面",
    "inventory": "库存页面",
    "attendance-mgmt": "考勤管理页面",
    "attendance": "考勤页面",
    "report": "报表页面",
    "dashboard": "仪表盘页面",
    "data-analysis": "数据分析页面",
    "device-mgmt": "设备管理页面",
    "device": "设备页面",
    "project-mgmt": "项目管理页面",
    "task-mgmt": "任务管理页面",
    "contract-mgmt": "合同管理页面",
    "contract": "合同页面",
    "expense-mgmt": "费用管理页面",
    "expense": "费用页面",
    "budget-mgmt": "预算管理页面",
    "budget": "预算页面",
}

PROJECT_TYPE_PREFIXES = {
    "form-component-dual": "form-component-",
    "form-page": "form-page-",
    "menu-page": "form-page-",
    "mobile-page": "form-page-",
    "form-list": "form-view-",
    "backend-api": "backend-api-",
    "layout": "form-layout-",
    "plugin": "frontend-plugin-",
}

PROJECT_TYPE_SUFFIXES = {
    "form-component-dual": "组件",
    "form-page": "页面",
    "menu-page": "页面",
    "mobile-page": "页面",
    "form-list": "列表",
    "backend-api": "接口",
    "backend-feign": "外部调用",
    "backend-scheduled": "定时任务",
    "layout": "布局",
    "plugin": "插件",
    "web-login": "登录页",
}

FRONTEND_RULE_WORKSPACE_TYPES = {
    "form-component-dual",
    "form-page",
    "menu-page",
    "mobile-page",
    "form-list",
    "layout",
    "plugin",
    "web-login",
}

PAGE_RULE_WORKSPACE_TYPES = {
    "form-page",
    "menu-page",
    "mobile-page",
}


class ProjectType(str, Enum):
    """项目类型"""
    FORM_COMPONENT_DUAL = "form-component-dual" # 表单自开发组件（双端：PC + 移动端，所有组件统一走此模板）
    FORM_PAGE = "form-page"                     # 自开发菜单页面（PC）
    MENU_PAGE = "menu-page"                     # 自开发菜单页面（PC，别名）
    MOBILE_PAGE = "mobile-page"                 # 移动端自开发页面
    FORM_LIST = "form-list"                     # 自开发列表视图
    LAYOUT = "layout"                           # 自定义布局
    PLUGIN = "plugin"                           # 自开发插件
    BACKEND_API = "backend-api"                 # 后端自开发接口
    BACKEND_FEIGN = "backend-feign"             # 后端外部调用（FeignClient）
    BACKEND_SCHEDULED = "backend-scheduled"     # 后端定时任务
    WEB_LOGIN = "web-login"                     # 自定义登录页


class WorkspaceStatus(str, Enum):
    CREATING = "creating"
    INSTALLING = "installing"
    READY = "ready"
    BUILDING = "building"
    ERROR = "error"


# ── CLI 模板相关常量 ──────────────────────────────────────────
CLI_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "cli-generated"

CLI_TEMPLATE_MAP: dict[str, str] = {
    ProjectType.FORM_COMPONENT_DUAL: "form-component-dual",
    ProjectType.MENU_PAGE:           "form-page-web",
    ProjectType.FORM_PAGE:      "form-page-web",
    ProjectType.FORM_LIST:      "form-view-web",
    ProjectType.LAYOUT:         "form-layout-web",
    ProjectType.PLUGIN:         "frontend-plugin-web",
}

# 预生成模板中使用的占位名称
_CLI_TPL_PLACEHOLDER = "demo"


class WorkspaceManager:
    """工作区管理器"""
    _install_locks: dict[str, asyncio.Lock] = {}
    _workspace_path_cache: dict[str, Path] = {}

    def __init__(self):
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        DEPENDENCY_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        NPM_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    def _build_workspace_folder_name(self, ws_id: str, project_name: str) -> str:
        readable_name = self._slugify_project_token(project_name) or "custom-dev"
        return f"{readable_name}__{ws_id}"

    def _fallback_project_name_from_path(self, ws_path: Path) -> str:
        folder_name = ws_path.name
        if "__" in folder_name:
            return folder_name.split("__", 1)[0].strip() or folder_name
        return folder_name

    def _iter_workspace_dirs(self):
        seen: set[Path] = set()
        for root in WORKSPACE_SEARCH_ROOTS:
            if not root.exists():
                continue
            for candidate in root.iterdir():
                if not candidate.is_dir():
                    continue
                if candidate.name.startswith("."):
                    continue
                if not (candidate / ".workspace.json").exists():
                    continue
                resolved_candidate = candidate.resolve()
                if resolved_candidate in seen:
                    continue
                seen.add(resolved_candidate)
                yield candidate

    def _workspace_root_priority(self, ws_path: Path) -> int:
        return 0 if ws_path.parent == WORKSPACE_ROOT else 1

    def _workspace_activity_ts(self, ws_path: Path) -> float:
        candidates = [
            ws_path,
            ws_path / ".workspace.json",
            ws_path / ".vscode" / "chat-history.json",
            ws_path / ".vscode" / "chat-replay.json",
            ws_path / ".vscode" / "ruijing-ai.json",
        ]
        latest = 0.0
        for candidate in candidates:
            try:
                if candidate.exists():
                    latest = max(latest, candidate.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _migrate_workspace_if_needed(self, ws_path: Path) -> Path:
        if ws_path.parent == WORKSPACE_ROOT or WORKSPACE_ROOT == LEGACY_WORKSPACE_ROOT:
            self._ensure_copy_asset_placeholders(ws_path)
            return ws_path

        target_path = WORKSPACE_ROOT / ws_path.name
        if target_path.exists():
            self._ensure_copy_asset_placeholders(target_path)
            return target_path

        try:
            shutil.copytree(ws_path, target_path, symlinks=True)
            self._ensure_copy_asset_placeholders(target_path)
            logger.info("Migrated legacy workspace to primary root: %s -> %s", ws_path, target_path)
            return target_path
        except Exception as exc:
            logger.warning("Failed to migrate legacy workspace %s: %s", ws_path, exc)
            return ws_path

    def get_workspace_path(self, ws_id: str) -> Path:
        cached = self._workspace_path_cache.get(ws_id)
        if cached and cached.exists():
            return cached

        for root in WORKSPACE_SEARCH_ROOTS:
            direct = root / ws_id
            if direct.exists():
                resolved_path = self._migrate_workspace_if_needed(direct)
                self._workspace_path_cache[ws_id] = resolved_path
                return resolved_path

        for candidate in self._iter_workspace_dirs():
            try:
                meta = self._read_meta(candidate)
            except Exception:
                continue
            if meta.get("id") == ws_id:
                resolved_path = self._migrate_workspace_if_needed(candidate)
                self._workspace_path_cache[ws_id] = resolved_path
                return resolved_path

        raise FileNotFoundError(f"Workspace {ws_id} not found")

    def _decorate_workspace_meta(self, ws_path: Path, meta: dict) -> dict:
        hydrated = self._ensure_display_name(ws_path, meta)
        hydrated["folder_name"] = ws_path.name
        hydrated["disk_path"] = str(ws_path.resolve())
        activity_ts = self._workspace_activity_ts(ws_path)
        hydrated["activity_ts"] = activity_ts
        if activity_ts:
            hydrated["updated_at"] = datetime.fromtimestamp(activity_ts).isoformat()
        return hydrated

    def _read_apaas_config(self, ws_path: Path) -> dict:
        # 双端工程（form-component-dual）的 apaas.json 在 web/src/ 下
        meta = self._read_meta(ws_path) if (ws_path / ".workspace.json").exists() else {}
        if meta.get("project_type") == "form-component-dual":
            apaas_json_path = ws_path / "web" / "src" / "apaas.json"
        else:
            apaas_json_path = ws_path / "src" / "apaas.json"
        return _safe_read_json(apaas_json_path)

    def _get_frontend_plugin_output_dir(self, ws_path: Path, apaas_config: dict) -> Path:
        plugin_code = (apaas_config.get("code") or "").strip()
        if not plugin_code:
            ext_list = apaas_config.get("extensionConfigList") or []
            if ext_list and isinstance(ext_list[0], dict):
                plugin_code = (ext_list[0].get("code") or "").strip()
        if not plugin_code:
            return ws_path / "dist"
        md5_code = hashlib.md5(plugin_code.encode("utf-8")).hexdigest()
        return ws_path / "crypto" / md5_code

    def _slugify_project_token(self, raw_name: str) -> str:
        candidate = (raw_name or "").strip().lower()
        if not candidate:
            return ""

        candidate = candidate.replace("&", " and ")
        candidate = re.sub(r"[^a-z0-9\\s-]", "-", candidate)
        candidate = candidate.replace("_", "-")
        candidate = re.sub(r"\s+", "-", candidate)
        candidate = re.sub(r"-+", "-", candidate).strip("-")
        candidate = re.sub(r"^[^a-z]+", "", candidate)
        return candidate[:64].strip("-")

    def _normalize_project_name(self, project_type: ProjectType, project_name: str) -> str:
        safe_name = self._slugify_project_token(project_name) or "custom-dev"
        if safe_name.startswith("apaas-custom-"):
            return safe_name

        prefix = PROJECT_TYPE_PREFIXES.get(project_type.value, "")
        if prefix and safe_name.startswith(prefix):
            return safe_name
        return f"{prefix}{safe_name}" if prefix else safe_name

    def _get_default_rule_files(self, project_type: Union[ProjectType, str]) -> list[Path]:
        project_type_value = project_type.value if isinstance(project_type, ProjectType) else str(project_type)
        files: list[Path] = []

        if project_type_value in FRONTEND_RULE_WORKSPACE_TYPES:
            files.append(DEFAULT_RULES_ROOT / "前端SDK-v2介绍.mdc")
        if project_type_value in PAGE_RULE_WORKSPACE_TYPES:
            files.append(DEFAULT_RULES_ROOT / "自开发菜单页面开发指南.mdc")

        return [file for file in files if file.exists()]

    def _seed_default_workspace_rules(self, ws_path: Path, project_type: Union[ProjectType, str]):
        rule_files = self._get_default_rule_files(project_type)
        if not rule_files:
            return

        rules_dir = ws_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        for source in rule_files:
            target = rules_dir / source.name
            if target.exists():
                continue
            shutil.copy2(source, target)

    def _ensure_copy_asset_placeholders(self, ws_path: Path):
        """为 copyAssets 目录补可见占位文件，避免 df-apaas-cli 的 cp path/* 在空目录时报错。"""
        apaas_config = self._read_apaas_config(ws_path)
        copy_assets = apaas_config.get("copyAssets") or []
        placeholder_content = (
            "Placeholder asset file for df-apaas-cli copyAssets.\n"
            "Delete this file after you add real assets.\n"
        )

        for copy_asset in copy_assets:
            if not isinstance(copy_asset, str):
                continue
            normalized_asset = copy_asset.strip().strip("/")
            if not normalized_asset:
                continue

            asset_dir = ws_path / normalized_asset
            asset_dir.mkdir(parents=True, exist_ok=True)

            has_visible_entries = any(
                child.name != ".DS_Store" and not child.name.startswith(".")
                for child in asset_dir.iterdir()
            )
            if has_visible_entries:
                continue

            placeholder_path = asset_dir / "asset-placeholder.txt"
            if not placeholder_path.exists():
                placeholder_path.write_text(placeholder_content, encoding="utf-8")

    def _strip_project_prefix(self, project_type: str, project_name: str) -> str:
        base_name = (project_name or "").strip()
        if base_name.startswith("apaas-custom-"):
            base_name = base_name[len("apaas-custom-"):]
        prefix = PROJECT_TYPE_PREFIXES.get(project_type, "")
        if prefix and base_name.startswith(prefix):
            base_name = base_name[len(prefix):]
        return base_name.strip("-_ ")

    def _humanize_project_name(self, project_type: str, project_name: str) -> str:
        base_name = self._strip_project_prefix(project_type, project_name).lower()
        if not base_name:
            return "未命名工作区"
        if base_name in DISPLAY_NAME_HINTS:
            return DISPLAY_NAME_HINTS[base_name]

        pretty = re.sub(r"[-_]+", " ", base_name).strip()
        if not pretty:
            return "未命名工作区"

        if re.search(r"[\u4e00-\u9fff]", pretty):
            return pretty

        formatted = " ".join(
            part.upper() if len(part) <= 3 else part.capitalize()
            for part in pretty.split()
        )
        suffix = PROJECT_TYPE_SUFFIXES.get(project_type, "")
        if suffix:
            return f"{formatted} {suffix}".strip()
        return formatted

    def _normalize_display_name(self, display_name: Optional[str], project_type: str, project_name: str) -> str:
        candidate = re.sub(r"\s+", " ", (display_name or "").strip())
        if not candidate:
            return self._humanize_project_name(project_type, project_name)

        normalized_candidate = candidate.lower().replace(" ", "-")
        if candidate == project_name or normalized_candidate == project_name.lower():
            return self._humanize_project_name(project_type, project_name)
        return candidate[:48]

    def _ensure_display_name(self, ws_path: Path, meta: dict) -> dict:
        if meta.get("display_name"):
            return meta
        hydrated_meta = dict(meta)
        hydrated_meta["display_name"] = self._normalize_display_name(
            hydrated_meta.get("project_name", ""),
            hydrated_meta.get("project_type", ""),
            hydrated_meta.get("project_name", ""),
        )
        self._write_meta(ws_path, hydrated_meta)
        return hydrated_meta

    @staticmethod
    def _resolve_output_name(apaas_config: Optional[dict], fallback: str) -> str:
        config = apaas_config or {}

        output_name = config.get("outputName")
        if isinstance(output_name, str) and output_name.strip():
            return output_name.strip()

        output_path = config.get("outputPath")
        if isinstance(output_path, str) and output_path.strip():
            normalized_path = output_path.replace("\\", "/").rstrip("/")
            candidate = normalized_path.split("/")[-1].strip()
            if candidate:
                return candidate

        return fallback

    def _get_build_output_dir(self, ws_path: Path, apaas_config: Optional[dict] = None) -> Path:
        meta = self._read_meta(ws_path) if (ws_path / ".workspace.json").exists() else {}
        # 双端模板：从 web/src/apaas.json 读取 PC 端输出目录
        if meta.get("project_type") == ProjectType.FORM_COMPONENT_DUAL.value:
            web_apaas = ws_path / "web" / "src" / "apaas.json"
            web_config = _safe_read_json(web_apaas)
            output_name = self._resolve_output_name(
                web_config,
                meta.get("project_name") or self._fallback_project_name_from_path(ws_path),
            )
            return ws_path / "web" / output_name
        apaas_config = apaas_config or self._read_apaas_config(ws_path)
        template_type = (apaas_config.get("templateType") or "").upper()
        if meta.get("project_type") == ProjectType.BACKEND_API.value:
            return ws_path / "target"
        output_name = self._resolve_output_name(
            apaas_config,
            meta.get("project_name") or self._fallback_project_name_from_path(ws_path),
        )
        if template_type == "FORM_COMPONENT":
            return ws_path / output_name
        if template_type in {"MENU_PAGE", "FORM_PAGE", "PAGE_CUSTOM_DEV", "PAGE_LAYOUT", "LIST_VIEW"}:
            return ws_path / output_name
        if template_type in {"FRONTEND_PLUGIN", "PLUGIN"}:
            return self._get_frontend_plugin_output_dir(ws_path, apaas_config)
        return ws_path / "dist"

    def get_build_output_dir(self, ws_id: str) -> Path:
        ws_path = self.get_workspace_path(ws_id)
        return self._get_build_output_dir(ws_path)

    def _has_build_artifacts(self, output_dir: Path) -> bool:
        if not output_dir.exists() or not output_dir.is_dir():
            return False
        for suffix in (".js", ".css", ".html", ".jar", ".war"):
            if any(output_dir.rglob(f"*{suffix}")):
                return True
        return False

    def _uses_df_apaas_cli_build(self, ws_path: Path) -> bool:
        package_json_path = ws_path / "package.json"
        # 双端模板没有根目录 package.json，用 web/ 子目录判断
        if not package_json_path.exists():
            package_json_path = ws_path / "web" / "package.json"
        if not package_json_path.exists():
            return False
        try:
            package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        build_script = ((package_json.get("scripts") or {}).get("build") or "").strip()
        return "df-apaas-cli build" in build_script

    def _project_requires_npm_install(self, project_type: str) -> bool:
        return project_type not in (
            ProjectType.BACKEND_API.value,
            ProjectType.BACKEND_FEIGN.value,
            ProjectType.BACKEND_SCHEDULED.value,
        )

    def _clean_build_output(self, text: str) -> str:
        if not text:
            return ""

        cleaned_lines: list[str] = []
        skip_next_blank = False
        for line in text.splitlines():
            if "DEPRECATION WARNING [legacy-js-api]" in line:
                skip_next_blank = True
                continue
            if "More info: https://sass-lang.com/d/legacy-js-api" in line:
                skip_next_blank = True
                continue
            if skip_next_blank and not line.strip():
                continue
            skip_next_blank = False
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def _summarize_build_failure(self, stdout: bytes, stderr: bytes, limit: int = 1800) -> str:
        stdout_text = self._clean_build_output(stdout.decode("utf-8", errors="replace"))
        stderr_text = self._clean_build_output(stderr.decode("utf-8", errors="replace"))

        markers = (
            # 前端 build markers
            "Failed to compile",
            "[eslint]",
            "ERROR  Failed to compile",
            "Error: Build failed with errors.",
            "error  ",
            # Maven build markers（2026-05-14 加，治后端打包失败诊断）
            "[ERROR] BUILD FAILURE",
            "[ERROR] Failed to execute goal",
            "Could not resolve dependencies",
            "Could not find artifact",
            "401 Unauthorized",
            "Authentication failed",
            "COMPILATION ERROR",
            "package does not exist",
            "cannot find symbol",
            "source release",  # JDK 版本不匹配："source release 1.8 requires ..."
            "The requested profile",
        )

        def _focus(text: str) -> str:
            if not text:
                return ""
            last_index = -1
            for marker in markers:
                idx = text.rfind(marker)
                if idx > last_index:
                    last_index = idx
            if last_index >= 0:
                return text[last_index:].strip()
            return text.strip()

        for candidate in (_focus(stdout_text), _focus(stderr_text), stdout_text, stderr_text):
            if candidate:
                return candidate[:limit]
        return "构建失败"

    def diagnose_build_failure(self, stdout: bytes, stderr: bytes) -> dict:
        """结构化诊断 build 失败：error_code + hint + summary + raw tail。

        给 MCP 工具用，方便 agent 拿到精准 error_code 决定下一步动作（重试 /
        改 settings.xml / 改 JDK / 改 pom），不必每次让 LLM 看大块日志自己猜。

        error_code 取值：
          - MVN_NOT_FOUND          mvn 命令不在 PATH（_run_backend_build_process 早已处理）
          - MVN_AUTH_FAIL          Nexus 401 / Authentication failed → 配 ~/.m2/settings.xml
          - MVN_DEPS_RESOLVE_FAIL  依赖拿不到 → settings.xml / pom <repositories> / 网络
          - MVN_PROFILE_NOT_FOUND  -P lib profile 在 pom 里找不到
          - MVN_JDK_MISMATCH       source release X requires target release X
          - MVN_COMPILE_FAIL       编译错（缺类 / lombok / 注解处理器）
          - MVN_BUILD_FAILURE      BUILD FAILURE 但没匹配到上面任何一种
          - FE_COMPILE_FAIL        前端编译失败（eslint / Failed to compile）
          - UNKNOWN                没匹配到 marker
        """
        stdout_text = self._clean_build_output(stdout.decode("utf-8", errors="replace"))
        stderr_text = self._clean_build_output(stderr.decode("utf-8", errors="replace"))
        combined = stdout_text + "\n" + stderr_text

        # 优先级从具体到通用（顺序敏感）
        if "401 Unauthorized" in combined or "Authentication failed for" in combined:
            code = "MVN_AUTH_FAIL"
            hint = (
                "Maven Nexus 仓库认证失败。配置 ~/.m2/settings.xml，加上 dcloud-public "
                "server 认证（username/password 都是 dcloud-public）和 mirror 把所有请求"
                "劫持到 maven-public。详见 docs/skills/apaas-backend-dev.md。"
            )
        elif "Could not resolve dependencies" in combined or "Could not find artifact" in combined:
            code = "MVN_DEPS_RESOLVE_FAIL"
            hint = (
                "依赖拉不到。三件事：(1) 看 pom.xml 是否含 <repositories> 指向 "
                "https://registry.dfy.definesys.cn/repository/maven-public/ ; (2) "
                "~/.m2/settings.xml 是否配 dcloud-public 认证；(3) 看是不是网络/代理"
                "拦了，先 mvn -X 看完整 URL。"
            )
        elif "The requested profile" in combined and "could not be activated" in combined:
            code = "MVN_PROFILE_NOT_FOUND"
            hint = (
                "-P lib profile 在 pom.xml 里不存在。检查 pom <profiles> 节点是否含 "
                "<profile><id>lib</id>... 直接用 init_apaas_backend_workspace 重写一份"
                "标准 pom 最稳。"
            )
        elif "source release" in combined and "requires target release" in combined:
            code = "MVN_JDK_MISMATCH"
            hint = (
                "JDK 版本和 pom <maven.compiler.source/target> 不匹配。aPaaS 模版包"
                "要求 Java 8（<source>8</source>）。检查 `java -version`，必要时 "
                "JAVA_HOME 切到 JDK 8。"
            )
        elif "COMPILATION ERROR" in combined or "cannot find symbol" in combined \
                or "package does not exist" in combined:
            code = "MVN_COMPILE_FAIL"
            hint = (
                "Java 编译错。常见：(1) lombok 注解处理器没启用（IDE / mvn 都得有 "
                "lombok 依赖 + processor）；(2) import 写错；(3) 漏依赖 — 看具体 "
                "'cannot find symbol' 是哪个类。"
            )
        elif "[ERROR] BUILD FAILURE" in combined or "[ERROR] Failed to execute goal" in combined:
            code = "MVN_BUILD_FAILURE"
            hint = "Maven BUILD FAILURE。看 stderr 末尾详细错（看 raw_tail 字段）。"
        elif any(m in combined for m in ("Failed to compile", "[eslint]",
                                          "Error: Build failed with errors.")):
            code = "FE_COMPILE_FAIL"
            hint = "前端编译失败 — 看 eslint / TS 错。"
        else:
            code = "UNKNOWN"
            hint = "没匹配到已知失败模式，看 raw_tail 原始日志。"

        # raw_tail：最后 30 行（给 LLM 进一步看）
        tail_lines = (combined.strip().split("\n"))[-30:]
        raw_tail = "\n".join(tail_lines)

        return {
            "error_code": code,
            "hint": hint,
            "summary": self._summarize_build_failure(stdout, stderr, limit=600),
            "raw_tail": raw_tail[:2000],
        }

    async def _run_backend_build_process(self, cwd: Path) -> tuple[int, bytes, bytes]:
        mvnw = cwd / "mvnw"
        if mvnw.exists():
            # scaffold 出的文件可能没有执行权限，统一补上
            mvnw.chmod(mvnw.stat().st_mode | 0o111)
            cmd = [str(mvnw), "-q", "-DskipTests", "package", "-P", "lib"]
        else:
            mvn_exec = shutil.which("mvn")
            if not mvn_exec:
                return 127, b"", "未检测到 Maven，请先安装 Maven/JDK 再构建后端项目".encode("utf-8")
            cmd = [mvn_exec, "-q", "-DskipTests", "package", "-P", "lib"]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout, stderr

    async def _run_build_process(self, cwd: Path) -> tuple[int, bytes, bytes]:
        meta_path = cwd / ".workspace.json"
        if meta_path.exists():
            meta = _safe_read_json(meta_path)
            if meta.get("project_type") == ProjectType.BACKEND_API.value:
                return await self._run_backend_build_process(cwd)

        env = self._build_npm_env()
        npm_exec = resolve_executable("npm", env)
        if not npm_exec:
            return 127, b"", "未检测到 npm，请检查 Node.js 安装或后端服务 PATH 配置".encode("utf-8")

        proc = await asyncio.create_subprocess_exec(
            npm_exec, "run", "build",
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout, stderr

    async def _build_with_staging(self, ws_path: Path) -> dict:
        apaas_config = self._read_apaas_config(ws_path)
        output_dir = self._get_build_output_dir(ws_path, apaas_config)
        output_name = self._resolve_output_name(apaas_config, output_dir.name)

        with tempfile.TemporaryDirectory(prefix="apaas-build-stage.") as temp_dir:
            stage_path = Path(temp_dir) / "workspace"
            shutil.copytree(
                ws_path,
                stage_path,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__", ".DS_Store"),
            )

            source_node_modules = ws_path / "node_modules"
            if source_node_modules.exists():
                os.symlink(source_node_modules, stage_path / "node_modules", target_is_directory=True)

            returncode, stdout, stderr = await self._run_build_process(stage_path)
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            stage_output_dir = self._get_build_output_dir(stage_path, apaas_config)
            if returncode != 0 or not self._has_build_artifacts(stage_output_dir):
                message = self._summarize_build_failure(stdout, stderr)
                return {"status": "error", "message": message}

            if output_dir.exists():
                shutil.rmtree(output_dir)
            shutil.copytree(stage_output_dir, output_dir)

            if (apaas_config.get("templateType") or "").upper() == "FRONTEND_PLUGIN":
                stage_zip = stage_output_dir.parent / f"{stage_output_dir.name}.zip"
            else:
                stage_zip = stage_path / f"{output_name}.zip"
            if stage_zip.exists():
                shutil.copy2(stage_zip, ws_path / stage_zip.name)

            return {"status": "ok", "message": "构建成功"}

    def create_workspace(
        self,
        project_type: ProjectType,
        project_name: str,
        user_id: int,
        project_id: Optional[int] = None,
        display_name: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> dict:
        """创建新工作区并生成脚手架"""
        # 规范化项目名
        safe_name = self._normalize_project_name(project_type, project_name)
        resolved_display_name = self._normalize_display_name(display_name, project_type.value, safe_name)
        ws_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        folder_name = self._build_workspace_folder_name(ws_id, safe_name)
        ws_path = WORKSPACE_ROOT / folder_name

        if ws_path.exists():
            shutil.rmtree(ws_path)

        ws_path.mkdir(parents=True)

        # 写入 workspace 元信息（2026-05-17 加 tenant_id — 没写的话 list_accessible_workspaces
        # 严格过滤会把整个 ws 隐藏掉，用户在 /coding 看不到 ai-chat 新建的 ws。
        meta = {
            "id": ws_id,
            "folder_name": folder_name,
            "project_id": project_id,
            "project_type": project_type.value,
            "project_name": safe_name,
            "display_name": resolved_display_name,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "status": WorkspaceStatus.CREATING.value,
        }
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        self._workspace_path_cache[ws_id] = ws_path

        # 生成脚手架 —— 优先使用 df-apaas-cli 预生成的标准模板
        if project_type.value in CLI_TEMPLATE_MAP:
            self._scaffold_via_cli_template(ws_path, safe_name, project_type, display_name=resolved_display_name)
        elif project_type == ProjectType.BACKEND_API:
            self._scaffold_backend_api(ws_path, safe_name)
        elif project_type == ProjectType.BACKEND_FEIGN:
            self._scaffold_backend_feign(ws_path, safe_name)
        elif project_type == ProjectType.BACKEND_SCHEDULED:
            self._scaffold_backend_scheduled(ws_path, safe_name)
        # ── 以下类型已从 UI 隐藏，保留 fallback 以兼容旧数据 ──
        elif project_type == ProjectType.MOBILE_PAGE:
            self._scaffold_form_page(ws_path, safe_name, mobile=True)
        elif project_type == ProjectType.WEB_LOGIN:
            self._scaffold_web_login(ws_path, safe_name)
        else:
            logger.warning(f"Unsupported project type for scaffolding: {project_type}")

        self._seed_default_workspace_rules(ws_path, project_type)
        self._ensure_copy_asset_placeholders(ws_path)

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

    @staticmethod
    def _install_state_path(ws_path: Path) -> Path:
        return ws_path / ".install-state.json"

    @staticmethod
    def _remove_path(path: Path):
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    async def _emit_install_progress(
        progress_callback: Optional[Callable[[str], Optional[Awaitable[None]]]],
        chunk: str,
    ):
        if not progress_callback or not chunk:
            return
        maybe_awaitable = progress_callback(chunk)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _build_npm_env(self) -> dict[str, str]:
        env = ensure_node_tool_env()
        env.setdefault("npm_config_registry", DEFAULT_NPM_REGISTRY)
        env.setdefault("NPM_CONFIG_REGISTRY", DEFAULT_NPM_REGISTRY)
        env.setdefault("npm_config_cache", str(NPM_CACHE_ROOT))
        env.setdefault("npm_config_prefer_offline", "true")
        env.setdefault("npm_config_audit", "false")
        env.setdefault("npm_config_fund", "false")
        env.setdefault("FORCE_COLOR", "0")
        return env

    @staticmethod
    def _npmrc_content() -> str:
        """npm install 用的 .npmrc 内容：默认源（公共依赖，快）+ @x-apaas scope 钉私有源。

        公共依赖（vue / @vue/cli-service / sass …）走 DEFAULT_NPM_REGISTRY；
        @x-apaas/* scoped 包（含运行时 SDK）走私有源，否则在公共源必然 404。
        """
        return (
            f"registry={DEFAULT_NPM_REGISTRY}\n"
            f"{APAAS_SCOPE}:registry={APAAS_PRIVATE_NPM_REGISTRY}\n"
        )

    def _ensure_workspace_npmrc(self, ws_path: Path) -> None:
        """确保 workspace 根目录有 .npmrc：默认源 + @x-apaas scope → 私有源。"""
        npmrc_path = ws_path / ".npmrc"
        scoped_line = f"{APAAS_SCOPE}:registry={APAAS_PRIVATE_NPM_REGISTRY}"
        default_line = f"registry={DEFAULT_NPM_REGISTRY}"
        # 已含两行（默认源 + scoped 私有源）才跳过；老的单行 .npmrc 要被升级补 scoped 行
        if npmrc_path.exists():
            try:
                existing = npmrc_path.read_text(encoding="utf-8")
                if scoped_line in existing and default_line in existing:
                    return
            except Exception:
                pass
        npmrc_path.write_text(self._npmrc_content(), encoding="utf-8")
        logger.info(
            f"[workspace] wrote .npmrc (registry={DEFAULT_NPM_REGISTRY}, "
            f"{APAAS_SCOPE}→{APAAS_PRIVATE_NPM_REGISTRY}) to {ws_path}"
        )

    async def _ensure_df_apaas_cli(self) -> None:
        """确保 df-apaas-cli 脚手架全局可用；不存在则从私有源安装，失败大声报错。

        @x-apaas/df-apaas-cli 是 scoped 私有包，只发布在得帆 apaas-npm-group。
        公共源（npmmirror/npmjs）必然 404；裸名 df-apaas-cli 在任何源都 404。
        装不上时直接 raise（不再静默 warn）——否则后续 `df-apaas-cli build`
        会以「命令找不到 / 404」的模糊错误失败，让人误判成模板/源码问题。
        """
        env = self._build_npm_env()
        if resolve_executable("df-apaas-cli", env):
            return

        npm_exec = resolve_executable("npm", env)
        if not npm_exec:
            raise RuntimeError("未检测到 npm，无法安装 df-apaas-cli，请检查 Node.js 安装或后端服务 PATH 配置")

        registry = APAAS_PRIVATE_NPM_REGISTRY
        logger.info("[workspace] df-apaas-cli not found globally, installing @x-apaas/df-apaas-cli from %s …", registry)
        proc = await asyncio.create_subprocess_exec(
            npm_exec, "install", "-g",
            "@x-apaas/df-apaas-cli",
            "--registry", registry,
            "--no-audit", "--no-fund",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()

        # returncode==0 但仍解析不到（如装到了不在 PATH 的 node 前缀）也算失败
        if proc.returncode != 0 or not resolve_executable("df-apaas-cli", env):
            raise RuntimeError(
                "无法安装 df-apaas-cli 脚手架（@x-apaas/df-apaas-cli）。"
                f"已尝试私有源 {registry}。请确认：① 该私有源可达；② 用 scoped 包名 "
                "@x-apaas/df-apaas-cli（裸名 df-apaas-cli 在任何源都 404）；"
                "③ 必要时设环境变量 APAAS_PRIVATE_NPM_REGISTRY 覆盖私有源地址。\n"
                f"npm 输出（尾部）:\n{output[-800:]}"
            )
        logger.info("[workspace] df-apaas-cli installed globally from %s", registry)

    def _build_dependency_signature(self, ws_path: Path, install_dir: Optional[Path] = None) -> str:
        package_json_path = (install_dir or ws_path) / "package.json"
        package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
        signature_payload = {
            "templateType": package_json.get("templateType"),
            "engines": package_json.get("engines") or {},
            "dependencies": package_json.get("dependencies") or {},
            "devDependencies": package_json.get("devDependencies") or {},
            "optionalDependencies": package_json.get("optionalDependencies") or {},
            "peerDependencies": package_json.get("peerDependencies") or {},
            "registry": DEFAULT_NPM_REGISTRY,
        }
        serialized = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def _dependency_cache_dir(self, signature: str) -> Path:
        return DEPENDENCY_CACHE_ROOT / signature

    def _write_install_state(self, ws_path: Path, signature: str, source: str):
        self._install_state_path(ws_path).write_text(
            json.dumps({"signature": signature, "source": source}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _workspace_install_ready(self, ws_path: Path, signature: str, install_dir: Optional[Path] = None) -> bool:
        node_modules_path = (install_dir or ws_path) / "node_modules"
        if not node_modules_path.exists():
            return False

        state = _safe_read_json(self._install_state_path(ws_path))
        if state.get("signature") == signature:
            return True

        package_lock_path = ws_path / "package-lock.json"
        if package_lock_path.exists() or any(node_modules_path.iterdir()):
            self._write_install_state(ws_path, signature, "workspace")
            return True
        return False

    def _cache_ready(self, cache_dir: Path) -> bool:
        node_modules_path = cache_dir / "node_modules"
        return node_modules_path.exists() and any(node_modules_path.iterdir())

    # ======== 源码 Hash（构建缓存判断） ========

    def _compute_src_hash(self, ws_path: Path) -> str:
        """对工作区源码文件内容计算 SHA-256，用于判断是否需要重新构建。
        双端模板：覆盖 web/src、mobile/src、shared 三个目录。
        单端模板：覆盖 src/ 目录。
        """
        meta = self._read_meta(ws_path) if (ws_path / ".workspace.json").exists() else {}
        if meta.get("project_type") == ProjectType.FORM_COMPONENT_DUAL.value:
            src_dirs = [ws_path / "web" / "src", ws_path / "mobile" / "src", ws_path / "shared"]
        else:
            src_dirs = [ws_path / "src"]

        hasher = hashlib.sha256()
        for src_dir in src_dirs:
            if not src_dir.exists():
                continue
            for f in sorted(src_dir.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    hasher.update(str(f.relative_to(ws_path)).encode("utf-8"))
                    try:
                        hasher.update(f.read_bytes())
                    except Exception:
                        pass
        return hasher.hexdigest()[:16]

    # ======== 模板依赖预热 ========

    async def prewarm_template_deps(self) -> None:
        """服务启动时在后台预热所有模板的 npm 依赖缓存。
        后续新建工作区时可直接命中缓存，跳过 npm install。
        """
        templates_root = REPO_ROOT / "templates" / "cli-generated"
        if not templates_root.exists():
            return

        pkg_dirs: list[Path] = []
        for template_dir in sorted(templates_root.iterdir()):
            if not template_dir.is_dir():
                continue
            # 单端模板：根目录有 package.json
            if (template_dir / "package.json").exists():
                pkg_dirs.append(template_dir)
            # 双端模板：web/ 和 mobile/ 各有 package.json
            for subdir in ("web", "mobile"):
                sub_pkg = template_dir / subdir / "package.json"
                if sub_pkg.exists():
                    pkg_dirs.append(template_dir / subdir)

        for pkg_dir in pkg_dirs:
            try:
                await self._prewarm_pkg_dir(pkg_dir)
            except Exception as e:
                logger.warning(f"[prewarm] {pkg_dir} 预热失败: {e}")

    async def _prewarm_pkg_dir(self, pkg_dir: Path) -> None:
        """预热单个 package.json 目录的依赖缓存。"""
        pkg_json_path = pkg_dir / "package.json"
        if not pkg_json_path.exists():
            return

        # 用 package.json 内容计算 signature（与工作区一致）
        try:
            pkg_json = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        except Exception:
            return
        signature_payload = {
            "templateType": pkg_json.get("templateType"),
            "engines": pkg_json.get("engines") or {},
            "dependencies": pkg_json.get("dependencies") or {},
            "devDependencies": pkg_json.get("devDependencies") or {},
            "optionalDependencies": pkg_json.get("optionalDependencies") or {},
            "peerDependencies": pkg_json.get("peerDependencies") or {},
            "registry": DEFAULT_NPM_REGISTRY,
        }
        serialized = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
        signature = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        cache_dir = self._dependency_cache_dir(signature)

        if self._cache_ready(cache_dir):
            logger.debug(f"[prewarm] {pkg_dir.name} 依赖缓存已就绪，跳过")
            return

        logger.info(f"[prewarm] 开始预热模板依赖: {pkg_dir.name} (sig={signature})")
        env = self._build_npm_env()
        npm_exec = resolve_executable("npm", env)
        if not npm_exec:
            logger.warning("[prewarm] 未检测到 npm，跳过预热")
            return

        temp_dir = Path(tempfile.mkdtemp(prefix="apaas-prewarm.", dir=str(DEPENDENCY_CACHE_ROOT)))
        try:
            shutil.copy2(pkg_json_path, temp_dir / "package.json")
            # 写入 .npmrc（默认源 + @x-apaas scope 钉私有源，与工作区一致）
            (temp_dir / ".npmrc").write_text(self._npmrc_content(), encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                npm_exec, "install",
                "--registry", DEFAULT_NPM_REGISTRY,
                "--prefer-offline", "--no-audit", "--no-fund",
                cwd=str(temp_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"[prewarm] {pkg_dir.name} npm install 失败 (code={proc.returncode})")
                return

            self._remove_path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_dir / "node_modules"), str(cache_dir / "node_modules"))
            lock_src = temp_dir / "package-lock.json"
            if lock_src.exists():
                shutil.move(str(lock_src), str(cache_dir / "package-lock.json"))
            logger.info(f"[prewarm] {pkg_dir.name} 依赖预热完成")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _link_cached_install(self, ws_path: Path, cache_dir: Path, signature: str):
        cache_node_modules = cache_dir / "node_modules"
        if not cache_node_modules.exists():
            raise FileNotFoundError(f"cache missing node_modules: {cache_dir}")

        workspace_node_modules = ws_path / "node_modules"
        if workspace_node_modules.is_symlink():
            current_target = workspace_node_modules.resolve()
            if current_target == cache_node_modules.resolve():
                self._write_install_state(ws_path, signature, "shared-cache")
                return

        self._remove_path(workspace_node_modules)
        try:
            os.symlink(cache_node_modules, workspace_node_modules, target_is_directory=True)
        except OSError:
            shutil.copytree(cache_node_modules, workspace_node_modules)

        cache_package_lock = cache_dir / "package-lock.json"
        if cache_package_lock.exists():
            shutil.copy2(cache_package_lock, ws_path / "package-lock.json")

        self._write_install_state(ws_path, signature, "shared-cache")

    async def _install_cache_miss(
        self,
        ws_path: Path,
        cache_dir: Path,
        progress_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    ) -> tuple[bool, str]:
        await self._emit_install_progress(
            progress_callback,
            "[cache] 未命中共享依赖缓存，正在首次安装依赖...\n",
        )

        temp_dir = Path(tempfile.mkdtemp(prefix="apaas-npm-install.", dir=str(DEPENDENCY_CACHE_ROOT)))
        try:
            shutil.copy2(ws_path / "package.json", temp_dir / "package.json")
            # 拷贝 .npmrc（包含私有 registry 配置），确保 @x-apaas scope 可以正确解析
            npmrc_src = ws_path / ".npmrc"
            if npmrc_src.exists():
                shutil.copy2(npmrc_src, temp_dir / ".npmrc")

            env = self._build_npm_env()
            npm_exec = resolve_executable("npm", env)
            if not npm_exec:
                return False, "未检测到 npm，请检查 Node.js 安装或后端服务 PATH 配置"

            proc = await asyncio.create_subprocess_exec(
                npm_exec,
                "install",
                "--registry",
                DEFAULT_NPM_REGISTRY,
                "--prefer-offline",
                "--no-audit",
                "--no-fund",
                cwd=str(temp_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            output_chunks: list[str] = []
            while True:
                chunk = await proc.stdout.read(1024) if proc.stdout else b""
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                output_chunks.append(text)
                await self._emit_install_progress(progress_callback, text)

            await proc.wait()
            output = "".join(output_chunks)
            if proc.returncode != 0:
                return False, output[:1200] or "npm install 失败"

            self._remove_path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_dir / "node_modules"), str(cache_dir / "node_modules"))
            package_lock_path = temp_dir / "package-lock.json"
            if package_lock_path.exists():
                shutil.move(str(package_lock_path), str(cache_dir / "package-lock.json"))

            await self._emit_install_progress(
                progress_callback,
                "[cache] 首次安装完成，后续同依赖工作区将直接复用缓存。\n",
            )
            return True, "依赖安装完成（已写入共享缓存）"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _install_at(
        self,
        install_dir: Path,
        ws_path: Path,
        progress_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    ) -> dict:
        """在指定子目录安装 npm 依赖（双端模板的 web/ 或 mobile/ 子目录）。
        install_dir: 含 package.json 的目录；ws_path: 工作区根目录（用于 .npmrc 和 install-state）。
        """
        # 确保 .npmrc 存在（从工作区根目录复制/生成）
        self._ensure_workspace_npmrc(ws_path)
        npmrc_src = ws_path / ".npmrc"
        npmrc_dst = install_dir / ".npmrc"
        if npmrc_src.exists() and not npmrc_dst.exists():
            try:
                shutil.copy2(npmrc_src, npmrc_dst)
            except Exception:
                pass

        try:
            signature = self._build_dependency_signature(ws_path, install_dir)
            cache_dir = self._dependency_cache_dir(signature)
            state_path = install_dir / ".install-state.json"

            # 已安装且签名匹配
            node_modules = install_dir / "node_modules"
            if node_modules.exists():
                state = _safe_read_json(state_path)
                if state.get("signature") == signature:
                    return {"status": "ok", "message": "依赖已就绪"}

            install_lock = self._install_locks.setdefault(f"subdir:{signature}", asyncio.Lock())
            async with install_lock:
                # 双重检查
                if node_modules.exists():
                    state = _safe_read_json(state_path)
                    if state.get("signature") == signature:
                        return {"status": "ok", "message": "依赖已就绪"}

                def _write_state(src: str):
                    state_path.write_text(
                        json.dumps({"signature": signature, "source": src}, ensure_ascii=False),
                        encoding="utf-8",
                    )

                def _link_cache():
                    cache_nm = cache_dir / "node_modules"
                    self._remove_path(node_modules)
                    try:
                        os.symlink(cache_nm, node_modules, target_is_directory=True)
                    except OSError:
                        shutil.copytree(cache_nm, node_modules)
                    lock = cache_dir / "package-lock.json"
                    if lock.exists():
                        shutil.copy2(lock, install_dir / "package-lock.json")

                if self._cache_ready(cache_dir):
                    _link_cache()
                    _write_state("shared-cache")
                    await self._emit_install_progress(
                        progress_callback,
                        f"[cache] {install_dir.name}/ 已复用共享依赖缓存。\n",
                    )
                    return {"status": "ok", "message": "依赖已从共享缓存复用"}

                # 临时目录安装，复用 _install_cache_miss 的核心逻辑
                temp_dir = Path(tempfile.mkdtemp(prefix="apaas-npm-install.", dir=str(DEPENDENCY_CACHE_ROOT)))
                try:
                    shutil.copy2(install_dir / "package.json", temp_dir / "package.json")
                    if npmrc_dst.exists():
                        shutil.copy2(npmrc_dst, temp_dir / ".npmrc")

                    env = self._build_npm_env()
                    npm_exec = resolve_executable("npm", env)
                    if not npm_exec:
                        return {"status": "error", "message": "未检测到 npm，请检查 Node.js 安装"}

                    await self._emit_install_progress(
                        progress_callback,
                        f"[install] 开始安装 {install_dir.name}/ 依赖...\n",
                    )
                    proc = await asyncio.create_subprocess_exec(
                        npm_exec, "install",
                        "--registry", DEFAULT_NPM_REGISTRY,
                        "--prefer-offline", "--no-audit", "--no-fund",
                        cwd=str(temp_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env=env,
                    )
                    output_chunks: list[str] = []
                    while True:
                        chunk = await proc.stdout.read(1024) if proc.stdout else b""
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        output_chunks.append(text)
                        await self._emit_install_progress(progress_callback, text)
                    await proc.wait()
                    output = "".join(output_chunks)
                    if proc.returncode != 0:
                        return {"status": "error", "message": output[:1200] or "npm install 失败"}

                    self._remove_path(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(temp_dir / "node_modules"), str(cache_dir / "node_modules"))
                    lock_src = temp_dir / "package-lock.json"
                    if lock_src.exists():
                        shutil.move(str(lock_src), str(cache_dir / "package-lock.json"))

                    _link_cache()
                    _write_state("shared-cache")
                    return {"status": "ok", "message": f"{install_dir.name}/ 依赖安装完成"}
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def install_deps(
        self,
        ws_id: str,
        progress_callback: Optional[Callable[[str], Optional[Awaitable[None]]]] = None,
    ) -> dict:
        """安装 npm 依赖"""
        ws_path = self.get_workspace_path(ws_id)

        meta = self._read_meta(ws_path)
        if not self._project_requires_npm_install(meta["project_type"]):
            return {"status": "skip", "message": "此类型项目无需 npm install"}

        meta["status"] = WorkspaceStatus.INSTALLING.value
        self._write_meta(ws_path, meta)

        # 双端模板：分别在 web/ 和 mobile/ 安装依赖
        if meta.get("project_type") == ProjectType.FORM_COMPONENT_DUAL.value:
            try:
                for subdir in ("web", "mobile"):
                    sub_path = ws_path / subdir
                    if not (sub_path / "package.json").exists():
                        continue
                    result = await self._install_at(sub_path, ws_path, progress_callback)
                    if result["status"] == "error":
                        meta["status"] = WorkspaceStatus.ERROR.value
                        self._write_meta(ws_path, meta)
                        return result
                meta["status"] = WorkspaceStatus.READY.value
                self._write_meta(ws_path, meta)
                return {"status": "ok", "message": "双端依赖安装完成"}
            except Exception as e:
                meta["status"] = WorkspaceStatus.ERROR.value
                self._write_meta(ws_path, meta)
                return {"status": "error", "message": str(e)}

        # 确保 .npmrc 存在（install 期间 npm 和 df-apaas-cli 内部 npm 都需要）
        self._ensure_workspace_npmrc(ws_path)

        try:
            signature = self._build_dependency_signature(ws_path)
            cache_dir = self._dependency_cache_dir(signature)

            if self._workspace_install_ready(ws_path, signature):
                meta["status"] = WorkspaceStatus.READY.value
                self._write_meta(ws_path, meta)
                return {"status": "ok", "message": "依赖已就绪"}

            install_lock = self._install_locks.setdefault(signature, asyncio.Lock())
            async with install_lock:
                if self._workspace_install_ready(ws_path, signature):
                    meta["status"] = WorkspaceStatus.READY.value
                    self._write_meta(ws_path, meta)
                    return {"status": "ok", "message": "依赖已就绪"}

                if self._cache_ready(cache_dir):
                    self._link_cached_install(ws_path, cache_dir, signature)
                    meta["status"] = WorkspaceStatus.READY.value
                    self._write_meta(ws_path, meta)
                    await self._emit_install_progress(
                        progress_callback,
                        "[cache] 已复用共享依赖缓存，跳过重复 npm install。\n",
                    )
                    return {"status": "ok", "message": "依赖已从共享缓存复用"}

                ok, message = await self._install_cache_miss(
                    ws_path,
                    cache_dir,
                    progress_callback=progress_callback,
                )
                if ok:
                    self._link_cached_install(ws_path, cache_dir, signature)
                    meta["status"] = WorkspaceStatus.READY.value
                    self._write_meta(ws_path, meta)
                    return {"status": "ok", "message": message}

                meta["status"] = WorkspaceStatus.ERROR.value
                self._write_meta(ws_path, meta)
                return {"status": "error", "message": message[:1200]}
        except Exception as e:
            meta["status"] = WorkspaceStatus.ERROR.value
            self._write_meta(ws_path, meta)
            return {"status": "error", "message": str(e)}

    async def build_if_needed(self, ws_id: str) -> dict:
        """按需构建 - 仅在源码比构建产物更新时重新构建"""
        ws_path = self.get_workspace_path(ws_id)
        meta = self._read_meta(ws_path)

        output_dir = self._get_build_output_dir(ws_path)

        # 双端模板：src 路径取 web/src 和 mobile/src 两者最新时间
        if meta.get("project_type") == ProjectType.FORM_COMPONENT_DUAL.value:
            mobile_output_dir = None
            mobile_cfg = _safe_read_json(ws_path / "mobile" / "src" / "apaas.json")
            if mobile_cfg:
                mobile_output_name = self._resolve_output_name(
                    mobile_cfg,
                    meta.get("project_name") or self._fallback_project_name_from_path(ws_path),
                )
                mobile_output_dir = ws_path / "mobile" / mobile_output_name
            # 任意一端产物不存在都需重新构建
            if not self._has_build_artifacts(output_dir) or (
                mobile_output_dir and not self._has_build_artifacts(mobile_output_dir)
            ):
                return await self.build_project(ws_id)
            src_paths = [ws_path / "web" / "src", ws_path / "mobile" / "src", ws_path / "shared"]
        else:
            src_paths = [ws_path / "src"]
            # 如果构建产物不存在，必须构建
            if not self._has_build_artifacts(output_dir):
                return await self.build_project(ws_id)

        # 比较 src 和 dist 的最新修改时间
        def _latest_mtime(directory: Path) -> float:
            latest = 0
            if not directory.exists():
                return latest
            for f in directory.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    mtime = f.stat().st_mtime
                    if mtime > latest:
                        latest = mtime
            return latest

        src_mtime = max((_latest_mtime(p) for p in src_paths), default=0)
        output_mtime = _latest_mtime(output_dir)

        if src_mtime > output_mtime:
            logger.info(f"[build_if_needed] src is newer, rebuilding {ws_id}")
            return await self.build_project(ws_id)
        else:
            logger.info(f"[build_if_needed] build output is up-to-date for {ws_id}")
            return {"status": "ok", "message": "已是最新，无需重新构建"}

    async def build_project(self, ws_id: str) -> dict:
        """构建项目"""
        ws_path = self.get_workspace_path(ws_id)

        self._run_workspace_compat_handlers(ws_path)

        meta = self._read_meta(ws_path)
        if self._project_requires_npm_install(meta.get("project_type", "")):
            install_result = await self.install_deps(ws_id)
            if install_result["status"] == "error":
                return install_result
            meta = self._read_meta(ws_path)

        meta["status"] = WorkspaceStatus.BUILDING.value
        self._write_meta(ws_path, meta)

        # 按项目类型分派
        try:
            # 若本次构建需要 df-apaas-cli，确保其全局可用（从私有源），并写入 .npmrc。
            # 放进 try：装不上时 _ensure_df_apaas_cli 会 raise，统一收成 build error
            # 返回给上层（而非裸异常逃逸 build_project）。
            if self._uses_df_apaas_cli_build(ws_path):
                await self._ensure_df_apaas_cli()
                self._ensure_workspace_npmrc(ws_path)

            if meta.get("project_type") == ProjectType.FORM_COMPONENT_DUAL.value:
                result = await self._build_dual_project(ws_path, meta)
            else:
                result = await self._build_single_project(ws_path)
        except Exception as e:
            result = {"status": "error", "message": str(e)}

        return self._finalize_build(ws_path, meta, result)

    def _finalize_build(self, ws_path: Path, meta: dict, result: dict) -> dict:
        """统一写入 meta.status（READY / ERROR），返回 result。"""
        meta["status"] = (
            WorkspaceStatus.READY.value if result.get("status") == "ok"
            else WorkspaceStatus.ERROR.value
        )
        self._write_meta(ws_path, meta)
        return result

    async def _build_dual_project(self, ws_path: Path, meta: dict) -> dict:
        """双端项目：分别构建 web/ 和 mobile/，各自验证产物。"""
        all_stdout, all_stderr = b"", b""
        for subdir in ("web", "mobile"):
            sub_path = ws_path / subdir
            if not sub_path.is_dir():
                continue
            returncode, stdout, stderr = await self._run_build_process(sub_path)
            all_stdout += stdout
            all_stderr += stderr
            if returncode != 0:
                return {
                    "status": "error",
                    "message": f"{subdir}/ 构建失败: " + self._summarize_build_failure(stdout, stderr),
                }

        # 验证 web/ 产物
        if not self._has_build_artifacts(self._get_build_output_dir(ws_path)):
            detail = self._summarize_build_failure(all_stdout, all_stderr)
            return {
                "status": "error",
                "message": f"双端构建完成但未找到 web/ 产物，请检查 web/src 代码\n构建日志:\n{detail}",
            }

        # 验证 mobile/ 产物（若存在 mobile/src/apaas.json）
        mobile_cfg = _safe_read_json(ws_path / "mobile" / "src" / "apaas.json")
        if mobile_cfg:
            try:
                mobile_output_name = self._resolve_output_name(
                    mobile_cfg,
                    meta.get("project_name") or self._fallback_project_name_from_path(ws_path),
                )
                mobile_output_dir = ws_path / "mobile" / mobile_output_name
                if not self._has_build_artifacts(mobile_output_dir):
                    detail = self._summarize_build_failure(all_stdout, all_stderr)
                    return {
                        "status": "error",
                        "message": f"双端构建完成但未找到 mobile/ 产物（{mobile_output_dir.name}/），请检查 mobile/src 代码\n构建日志:\n{detail}",
                    }
            except Exception as e:
                logger.warning(f"[build_project] 校验 mobile 产物时出错: {e}")

        # 构建产物校验通过 → 清掉 web/{outputName}/ 和 mobile/{outputName}/ 目录。
        # 目的：
        # 1. 打包后的 UMD 文件是混淆过的代码，LLM（coding agent / verification agent）
        #    grep / read 它们完全无益，只会浪费 turn 且污染推理上下文
        #    （比如 verify 阶段看到 form-component-custom-intl-phone.umd.js 会反复 read 它）
        # 2. LLM 有时会 glob 全工作区，看到 UMD 目录后臆想"产物该在 dist 目录"
        #    之类无关结论，影响思考过程质量
        # 保留 .zip：下载 / 上传到平台 / 发布市场用的是 .zip 制品，放在 ws_path 根下不动。
        # 副作用：如果用户点"下载 dist"按钮（routes/coding.py `type=dist`），
        # 会拿到 400「请先构建项目」，需再跑一次构建。可接受。
        self._cleanup_dual_build_artifacts(ws_path, meta)

        return {"status": "ok", "message": "双端构建成功"}

    def _cleanup_dual_build_artifacts(self, ws_path: Path, meta: dict) -> None:
        """删掉双端构建产物目录（web/{outputName}/ 和 mobile/{outputName}/）。

        只在 form-component-dual 类型调用，只删 UMD/assets 目录本身，不触 .zip / src / node_modules。
        所有异常静默吞 —— 清理是锦上添花，失败不应阻断主流程。
        """
        for side in ("web", "mobile"):
            try:
                apaas = _safe_read_json(ws_path / side / "src" / "apaas.json")
                if not apaas:
                    continue
                output_name = self._resolve_output_name(
                    apaas,
                    meta.get("project_name") or self._fallback_project_name_from_path(ws_path),
                )
                artifact_dir = ws_path / side / output_name
                if artifact_dir.exists() and artifact_dir.is_dir():
                    shutil.rmtree(artifact_dir, ignore_errors=True)
                    logger.info(
                        f"[build] cleanup: removed build artifact dir {side}/{output_name}/"
                    )
            except Exception as e:
                logger.warning(f"[build] cleanup 跳过 {side}（非致命）: {e}")

    async def _build_single_project(self, ws_path: Path) -> dict:
        """单端项目：直接在 ws_path 跑 npm/mvn build，验证产物。"""
        # 路径含空格 + 使用 df-apaas-cli → 用 staging 目录避空格陷阱
        if " " in str(ws_path) and self._uses_df_apaas_cli_build(ws_path):
            return await self._build_with_staging(ws_path)

        returncode, stdout, stderr = await self._run_build_process(ws_path)
        if returncode == 0 and self._has_build_artifacts(self._get_build_output_dir(ws_path)):
            return {"status": "ok", "message": "构建成功"}
        return {
            "status": "error",
            "message": self._summarize_build_failure(stdout, stderr),
        }

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

        ws_path = self.get_workspace_path(ws_id)

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

        meta = self._read_meta(ws_path)
        if self._project_requires_npm_install(meta.get("project_type", "")):
            install_result = await self.install_deps(ws_id)
            if install_result["status"] == "error":
                return install_result

        env = self._build_npm_env()
        env["PORT"] = str(port)
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
        """停止 serve 进程（单端 or 双端均支持）"""
        if ws_id not in self._serve_processes:
            return {"status": "ok", "message": "serve 未运行"}
        info = self._serve_processes.pop(ws_id)

        async def _terminate(proc):
            if proc is None or proc.returncode is not None:
                return
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()

        # 双端格式：{"web": {"process": ..., "port": ...}, "mobile": {"process": ..., "port": ...}}
        if "web" in info or "mobile" in info:
            for side in ("web", "mobile"):
                side_info = info.get(side)
                if side_info:
                    await _terminate(side_info.get("process"))
        else:
            # 单端格式：{"process": proc, "port": int}
            await _terminate(info.get("process"))

        return {"status": "ok", "message": "serve 已停止"}

    def is_serve_running(self, ws_id: str) -> dict:
        """查询 serve 状态。

        单端格式：{"process": proc, "port": int}
        双端格式：{"web": {"process": proc, "port": int}, "mobile": {"process": proc, "port": int}}
        """
        if ws_id not in self._serve_processes:
            return {"running": False}
        info = self._serve_processes[ws_id]

        # 双端格式
        if "web" in info or "mobile" in info:
            web_info = info.get("web")
            mobile_info = info.get("mobile")
            web_running = bool(web_info and web_info["process"].returncode is None)
            mobile_running = bool(mobile_info and mobile_info["process"].returncode is None)
            if not web_running and not mobile_running:
                self._serve_processes.pop(ws_id, None)
                return {"running": False}
            return {
                "running": True,
                "dual": True,
                "web": {"port": web_info["port"]} if web_running else None,
                "mobile": {"port": mobile_info["port"]} if mobile_running else None,
            }

        # 单端格式（原逻辑不变）
        running = info["process"].returncode is None
        if not running:
            self._serve_processes.pop(ws_id, None)
        return {"running": running, "port": info["port"] if running else None}

    async def build_and_package(self, ws_id: str) -> str:
        """构建 + 打包 zip，返回 zip 文件路径。
        上传前先比对源码 hash：未变化且 zip 已存在则跳过构建直接返回。
        """
        ws_path = self.get_workspace_path(ws_id)
        meta = self._read_meta(ws_path)
        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)
        project_type = meta.get("project_type", "")

        _backend_types = (ProjectType.BACKEND_API.value, ProjectType.BACKEND_FEIGN.value, ProjectType.BACKEND_SCHEDULED.value)
        is_backend = project_type in _backend_types

        if not is_backend:
            output_dir = self._get_build_output_dir(ws_path)
            cli_zip = output_dir.parent / f"{output_dir.name}.zip"
            current_hash = self._compute_src_hash(ws_path)
            if (meta.get("src_hash") == current_hash
                    and cli_zip.exists()
                    and self._has_build_artifacts(output_dir)):
                logger.info(f"[build_and_package] 源码未变化，跳过构建: {ws_id}")
                return str(cli_zip)

        # 需要重新构建
        result = await self.build_project(ws_id)
        if result["status"] == "error":
            raise RuntimeError(f"构建失败: {result['message']}")

        # 构建成功后记录 hash
        if not is_backend:
            meta = self._read_meta(ws_path)
            meta["src_hash"] = self._compute_src_hash(ws_path)
            self._write_meta(ws_path, meta)

        meta = self._read_meta(ws_path)
        project_type = meta.get("project_type", "")
        output_dir = self._get_build_output_dir(ws_path)
        if not self._has_build_artifacts(output_dir):
            raise FileNotFoundError("构建产物目录不存在，构建可能失败")

        # 后端项目：手动打包 target/ 下的 JAR
        if project_type in (ProjectType.BACKEND_API.value, ProjectType.BACKEND_FEIGN.value, ProjectType.BACKEND_SCHEDULED.value):
            import zipfile
            zip_path = ws_path / f"{project_name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                jar_files = list(output_dir.glob("*.jar"))
                final_jars = [j for j in jar_files if not j.name.endswith(".original")]
                for jar in (final_jars or jar_files):
                    zf.write(jar, jar.name)
            return str(zip_path)

        # 前端项目：优先使用 df-apaas-cli build 生成的 zip 包
        # df-apaas-cli 将 zip 输出到与产物目录同级，命名为 {outputName}.zip
        # _build_with_staging 在暂存构建后也会将该 zip 拷回工作区根目录
        cli_zip = output_dir.parent / f"{output_dir.name}.zip"
        if cli_zip.exists():
            logger.info(f"[build_and_package] 使用 df-apaas-cli 生成的 zip: {cli_zip}")
            return str(cli_zip)

        # 兜底：df-apaas-cli zip 不存在时手动压缩（极端情况）
        logger.warning(f"[build_and_package] 未找到 df-apaas-cli zip（{cli_zip}），降级为手动压缩")
        import zipfile
        zip_path = ws_path / f"{output_dir.name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(output_dir))
            apaas_json = ws_path / "src" / "apaas.json"
            if apaas_json.exists() and not (output_dir / "apaas.json").exists():
                zf.write(apaas_json, "apaas.json")
                try:
                    cfg = json.loads(apaas_json.read_text())
                    for asset in cfg.get("copyAssets", []):
                        static_dir = asset.replace("public/", "static/", 1)
                        zf.writestr(f"{static_dir}/", "")
                except Exception:
                    zf.writestr(f"static/custom/{output_dir.name}/", "")
            else:
                zf.writestr(f"static/custom/{output_dir.name}/", "")
        return str(zip_path)

    def _collect_dual_zips(self, ws_path: Path, project_name: str) -> list[tuple[str, str]]:
        """收集双端已有 zip 路径，两端都存在且有产物才返回，否则返回空列表。"""
        outputs: list[tuple[str, str]] = []
        for subdir, file_type in (("web", "FRONTCOMPONENT"), ("mobile", "MFRONTCOMPONENT")):
            sub_path = ws_path / subdir
            if not sub_path.is_dir():
                continue
            apaas_cfg = _safe_read_json(sub_path / "src" / "apaas.json")
            output_name = self._resolve_output_name(apaas_cfg, project_name)
            output_dir = sub_path / output_name
            cli_zip = sub_path / f"{output_name}.zip"
            if not (cli_zip.exists() and self._has_build_artifacts(output_dir)):
                return []
            outputs.append((str(cli_zip), file_type))
        return outputs

    async def build_and_package_dual(self, ws_id: str) -> list[tuple[str, str]]:
        """双端模板专用：构建 web/ 和 mobile/，分别打包，返回 [(zip_path, file_type), ...]。
        PC 端 → FRONTCOMPONENT，移动端 → MFRONTCOMPONENT。
        上传前先比对源码 hash：未变化且 zip 已存在则跳过构建直接返回。
        优先使用 df-apaas-cli build 在各子目录生成的 zip 包。
        """
        ws_path = self.get_workspace_path(ws_id)
        meta = self._read_meta(ws_path)
        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)

        # hash 检查：源码未变化且两端 zip 都存在则跳过构建
        current_hash = self._compute_src_hash(ws_path)
        if meta.get("src_hash") == current_hash:
            cached = self._collect_dual_zips(ws_path, project_name)
            if cached:
                logger.info(f"[build_and_package_dual] 源码未变化，跳过构建: {ws_id}")
                return cached

        # 需要重新构建
        result = await self.build_project(ws_id)
        if result["status"] == "error":
            raise RuntimeError(f"构建失败: {result['message']}")

        # 构建成功后记录 hash
        meta = self._read_meta(ws_path)
        meta["src_hash"] = self._compute_src_hash(ws_path)
        self._write_meta(ws_path, meta)

        outputs: list[tuple[str, str]] = []

        for subdir, file_type in (("web", "FRONTCOMPONENT"), ("mobile", "MFRONTCOMPONENT")):
            sub_path = ws_path / subdir
            if not sub_path.is_dir():
                continue

            # 读 sub/src/apaas.json 获取 outputName
            apaas_cfg = _safe_read_json(sub_path / "src" / "apaas.json")
            output_name = self._resolve_output_name(apaas_cfg, project_name)
            output_dir = sub_path / output_name

            # 验证产物（必须含 umd.js 等文件，不能只有 apaas.json）
            if not self._has_build_artifacts(output_dir):
                raise FileNotFoundError(f"{subdir}/ 构建产物不存在或不完整（{output_dir.name}/），请检查 {subdir}/src 代码")

            # 优先使用 df-apaas-cli 在子目录生成的 zip，直接用原路径上传
            # df-apaas-cli 将 zip 输出到与产物目录同级：sub_path/{outputName}.zip
            cli_zip = sub_path / f"{output_name}.zip"
            if cli_zip.exists():
                logger.info(f"[build_and_package_dual] {subdir}/ 使用 df-apaas-cli zip: {cli_zip}")
                outputs.append((str(cli_zip), file_type))
                continue

            # 兜底：df-apaas-cli zip 不存在时手动压缩（极端情况）
            logger.warning(f"[build_and_package_dual] {subdir}/ 未找到 df-apaas-cli zip（{cli_zip}），降级为手动压缩")
            import zipfile as _zipfile
            dest_zip = ws_path / f"{output_name}.zip"
            with _zipfile.ZipFile(dest_zip, 'w', _zipfile.ZIP_DEFLATED) as zf:
                for f in output_dir.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(output_dir))
                if apaas_json_path.exists() and not (output_dir / "apaas.json").exists():
                    zf.write(apaas_json_path, "apaas.json")
                    try:
                        for asset in apaas_cfg.get("copyAssets", []):
                            static_dir = asset.replace("public/", "static/", 1)
                            zf.writestr(f"{static_dir}/", "")
                    except Exception:
                        zf.writestr(f"static/custom/{output_name}/", "")
                else:
                    zf.writestr(f"static/custom/{output_name}/", "")
            outputs.append((str(dest_zip), file_type))

        return outputs

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

        ws_path = self.get_workspace_path(ws_id)

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

        ws_path = self.get_workspace_path(ws_id)
        screenshots_dir = ws_path / "debug" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        result_json_path = ws_path / "debug" / "result.json"
        if result_json_path.exists():
            result_json_path.unlink()

        # platform_url 通常以 /platform/ 结尾，这里提取平台 base。
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

    # 各项目类型允许写入的文件扩展名白名单
    _BACKEND_EXTENSIONS = {".java", ".xml", ".properties", ".yml", ".yaml", ".md", ".txt", ".json"}
    _FRONTEND_EXTENSIONS = {".vue", ".js", ".ts", ".jsx", ".tsx", ".css", ".scss", ".less",
                             ".html", ".json", ".md", ".txt"}
    _BACKEND_PROJECT_TYPES = {"backend-api", "backend-feign", "backend-scheduled"}

    def write_file(self, ws_id: str, file_path: str, content: str):
        """写入文件到工作区"""
        ws_path = self.get_workspace_path(ws_id)

        # 安全检查：不允许写入工作区外
        target = (ws_path / file_path).resolve()
        if not str(target).startswith(str(ws_path.resolve())):
            raise ValueError("File path escapes workspace")

        # 项目类型与文件扩展名一致性检查：后端项目拒绝写入 Vue/JS 等前端文件
        meta = self._read_meta(ws_path)
        project_type = meta.get("project_type", "")
        if project_type in self._BACKEND_PROJECT_TYPES:
            suffix = Path(file_path).suffix.lower()
            if suffix and suffix not in self._BACKEND_EXTENSIONS:
                logger.warning(
                    "write_file blocked: backend project '%s' cannot write '%s' (%s)",
                    project_type, file_path, suffix
                )
                return  # 静默丢弃，不报错，避免中断整体生成流程

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, ws_id: str, file_path: str) -> str:
        """读取工作区文件"""
        ws_path = self.get_workspace_path(ws_id)
        target = (ws_path / file_path).resolve()
        if not str(target).startswith(str(ws_path.resolve())):
            raise ValueError("File path escapes workspace")
        if not target.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return target.read_text(encoding="utf-8")

    def list_files(self, ws_id: str) -> list:
        """列出工作区的文件树"""
        ws_path = self.get_workspace_path(ws_id)

        files = []
        for p in sorted(ws_path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(ws_path)
                rel_str = str(rel)
                # 跳过隐藏文件和 node_modules，但保留 .cursor/rules 里的规范文档
                if "node_modules" in rel_str:
                    continue
                if rel_str.startswith(".") and not rel_str.startswith(".cursor/rules/"):
                    continue
                files.append(rel_str)
        return files

    def get_workspace_info(self, ws_id: str) -> dict:
        """获取工作区信息"""
        ws_path = self.get_workspace_path(ws_id)
        meta = self._decorate_workspace_meta(ws_path, self._read_meta(ws_path))
        meta["files"] = self.list_files(ws_id)
        return meta

    def list_user_workspaces(self, user_id: int) -> list:
        """列出用户的所有工作区"""
        results_by_id: dict[str, dict] = {}
        if not any(root.exists() for root in WORKSPACE_SEARCH_ROOTS):
            return []
        for d in self._iter_workspace_dirs():
            try:
                meta = self._decorate_workspace_meta(d, self._read_meta(d))
                if meta.get("user_id") != user_id:
                    continue
                ws_id = str(meta.get("id") or d.name)
                existing = results_by_id.get(ws_id)
                if not existing:
                    results_by_id[ws_id] = meta
                    continue

                existing_path = Path(existing.get("disk_path") or d)
                if self._workspace_root_priority(d) < self._workspace_root_priority(existing_path):
                    results_by_id[ws_id] = meta
            except Exception:
                pass
        return sorted(
            results_by_id.values(),
            key=lambda meta: (
                -(float(meta.get("activity_ts") or 0)),
                self._workspace_root_priority(Path(meta.get("disk_path") or WORKSPACE_ROOT)),
                str(meta.get("display_name") or meta.get("project_name") or meta.get("id") or ""),
            ),
        )

    def list_project_workspaces(self, project_id: int) -> list:
        """列出项目下的所有工作区。"""
        results_by_id: dict[str, dict] = {}
        if not any(root.exists() for root in WORKSPACE_SEARCH_ROOTS):
            return []
        for d in self._iter_workspace_dirs():
            try:
                meta = self._decorate_workspace_meta(d, self._read_meta(d))
                if meta.get("project_id") != project_id:
                    continue
                ws_id = str(meta.get("id") or d.name)
                existing = results_by_id.get(ws_id)
                if not existing:
                    results_by_id[ws_id] = meta
                    continue

                existing_path = Path(existing.get("disk_path") or d)
                if self._workspace_root_priority(d) < self._workspace_root_priority(existing_path):
                    results_by_id[ws_id] = meta
            except Exception:
                pass
        return sorted(
            results_by_id.values(),
            key=lambda meta: (
                -(float(meta.get("activity_ts") or 0)),
                self._workspace_root_priority(Path(meta.get("disk_path") or WORKSPACE_ROOT)),
                str(meta.get("display_name") or meta.get("project_name") or meta.get("id") or ""),
            ),
        )

    def list_accessible_workspaces(
        self,
        user_id: int,
        project_ids: list[int] | None = None,
        tenant_id: int | None = None,
    ) -> list:
        """列出用户可访问的工作区：个人工作区 + 有权限的项目工作区。

        tenant_id 不为 None 时强制过滤：只返回 meta.tenant_id 匹配的 workspace。
        老 workspace 没 tenant_id 字段时按 user_id 兜底放行（避免吞掉历史数据）。
        """
        allowed_projects = set(project_ids or [])
        results_by_id: dict[str, dict] = {}
        if not any(root.exists() for root in WORKSPACE_SEARCH_ROOTS):
            return []
        for d in self._iter_workspace_dirs():
            try:
                meta = self._decorate_workspace_meta(d, self._read_meta(d))
                project_id = meta.get("project_id")
                if project_id:
                    if project_id not in allowed_projects:
                        continue
                elif meta.get("user_id") != user_id:
                    continue
                # 租户隔离：meta.tenant_id 匹配时通过；缺失时按 user_id 兜底放行
                # (2026-05-17 修：原代码 strict continue 跟 docstring "按 user_id 兜底放行" 不一致，
                # 导致 ai-chat 通过 MCP 创建的 ws 因 meta 缺 tenant_id 字段全部不可见)
                if tenant_id is not None:
                    meta_tenant = meta.get("tenant_id")
                    if meta_tenant is not None and int(meta_tenant) != int(tenant_id):
                        continue
                    # meta_tenant is None → 已通过 user_id 校验（上面 line 2540），放行

                ws_id = str(meta.get("id") or d.name)
                existing = results_by_id.get(ws_id)
                if not existing:
                    results_by_id[ws_id] = meta
                    continue

                existing_path = Path(existing.get("disk_path") or d)
                if self._workspace_root_priority(d) < self._workspace_root_priority(existing_path):
                    results_by_id[ws_id] = meta
            except Exception:
                pass
        return sorted(
            results_by_id.values(),
            key=lambda meta: (
                -(float(meta.get("activity_ts") or 0)),
                self._workspace_root_priority(Path(meta.get("disk_path") or WORKSPACE_ROOT)),
                str(meta.get("display_name") or meta.get("project_name") or meta.get("id") or ""),
            ),
        )

    async def delete_workspace(self, ws_id: str):
        """删除工作区：先停掉所有 serve 进程，再递归删除文件夹。"""
        # 1. 停 serve 进程（单端 / 双端都会清理）
        try:
            await self.stop_serve(ws_id)
        except Exception as e:
            logger.warning(f"[delete_workspace] 停止 serve 进程失败（忽略继续删除）: {e}")

        # 2. 收集所有匹配的工作区目录
        matched_paths: list[Path] = []
        try:
            matched_paths.append(self.get_workspace_path(ws_id))
        except FileNotFoundError:
            pass

        for candidate in self._iter_workspace_dirs():
            try:
                if self._read_meta(candidate).get("id") == ws_id:
                    matched_paths.append(candidate)
            except Exception:
                continue

        # 3. 递归删除
        for ws_path in {path.resolve(): path for path in matched_paths}.values():
            if ws_path.exists():
                shutil.rmtree(ws_path)
        self._workspace_path_cache.pop(ws_id, None)

    # 注：原 try_rename_workspace_to_output_name 已移除。
    # 工作区 folder name 一旦创建即永久不变，不再随 outputName 改名——
    # 改名会让 .vibe-ide.code-workspace 里的绝对路径、IDE URL、agent 持有的
    # ws_path、build cwd FD 等多个缓存同时失效，引发"workspace does not exist"
    # 之类的连锁问题。包名走 apaas.json 的 outputName，与 folder name 解耦。

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
        if template_type == "FORM_COMPONENT":
            public_root = "form-component"
        elif template_type == "PAGE_LAYOUT":
            public_root = "form-layout"
        elif template_type == "LIST_VIEW":
            public_root = "form-view"
        elif template_type == "FRONTEND_PLUGIN":
            public_root = "frontend-plugin"
        else:
            public_root = "form-page"
        pub_dir = f"public/{public_root}/{name}"
        self._write(ws_path, f"{pub_dir}/.gitkeep", "")

        # HTTPS 自签名证书（debug 模式必需）
        self._generate_https_cert(ws_path)

        # .vscode/tasks.json（IDE 便捷命令）
        self._write(ws_path, ".vscode/tasks.json", json.dumps({
            "version": "2.0.0",
            "tasks": [
                {
                    "label": "npm install",
                    "type": "shell",
                    "command": "npm install",
                    "problemMatcher": []
                },
                {
                    "label": "npm run serve",
                    "type": "shell",
                    "command": "npm run serve",
                    "isBackground": True,
                    "problemMatcher": []
                },
                {
                    "label": "npm run build",
                    "type": "shell",
                    "command": "npm run build",
                    "problemMatcher": []
                }
            ]
        }, indent=2, ensure_ascii=False))

    def _run_workspace_compat_handlers(self, ws_path: Path) -> None:
        """按 project_type 分派到对应的兼容修复函数。

        比依次调用所有 6 个 `_ensure_*_workspace_compat` 更高效：
        - 只读一次 meta（不需要每个 handler 都读一次）
        - 集中注册表，加新项目类型只改这里
        - 每个 handler 内部仍保留 project_type guard 作为防御（被外部直接调用时依然安全）
        """
        if not (ws_path / ".workspace.json").exists():
            return
        meta = self._read_meta(ws_path)
        project_type = meta.get("project_type", "")

        handlers = {
            ProjectType.MENU_PAGE.value: self._ensure_menu_page_workspace_compat,
            ProjectType.LAYOUT.value: self._ensure_layout_workspace_compat,
            ProjectType.FORM_LIST.value: self._ensure_form_list_workspace_compat,
            ProjectType.PLUGIN.value: self._ensure_plugin_workspace_compat,
            ProjectType.BACKEND_API.value: self._ensure_backend_workspace_compat,
        }
        handler = handlers.get(project_type)
        if handler:
            handler(ws_path)

    def _ensure_layout_workspace_compat(self, ws_path: Path):
        """修复旧版布局工作区，使其对齐 PAGE_LAYOUT 脚手架协议。"""
        meta = self._read_meta(ws_path)
        if meta.get("project_type") != ProjectType.LAYOUT.value:
            return

        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)
        package_json_path = ws_path / "package.json"
        apaas_json_path = ws_path / "src" / "apaas.json"

        if not package_json_path.exists() or not apaas_json_path.exists():
            return

        try:
            package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
        except Exception:
            package_json = {}
        try:
            apaas_config = json.loads(apaas_json_path.read_text(encoding="utf-8"))
        except Exception:
            apaas_config = {}

        layout_items = apaas_config.get("layout")
        layout_name = None
        if isinstance(layout_items, list):
            for item in layout_items:
                if isinstance(item, dict) and item.get("name"):
                    layout_name = item["name"]
                    break
        if not layout_name:
            layout_name = f"apaas-custom-{project_name}"

        output_name = apaas_config.get("outputName") or f"form-layout-{project_name}"

        package_changed = False
        if package_json.get("templateType") != "PAGE_LAYOUT":
            package_json["templateType"] = "PAGE_LAYOUT"
            package_changed = True
        if package_changed:
            package_json_path.write_text(
                json.dumps(package_json, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _ensure_form_list_workspace_compat(self, ws_path: Path):
        """修复旧版列表视图工作区，使其对齐 LIST_VIEW 协议。"""
        meta = self._read_meta(ws_path)
        if meta.get("project_type") != ProjectType.FORM_LIST.value:
            return

        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)
        package_json_path = ws_path / "package.json"
        apaas_json_path = ws_path / "src" / "apaas.json"
        public_dir = ws_path / "public" / "form-view" / project_name
        public_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = public_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

        if package_json_path.exists():
            try:
                package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
            except Exception:
                package_json = {}
        else:
            package_json = {}

        package_json.update({
            "name": package_json.get("name") or project_name,
            "version": package_json.get("version") or "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "LIST_VIEW",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve": "node vibe-serve.js src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build",
            },
        })
        package_json["dependencies"] = {
            **(package_json.get("dependencies") or {}),
            "core-js": "3.8.3",
            "vue": "2.7.14",
        }
        package_json["devDependencies"] = {
            **(package_json.get("devDependencies") or {}),
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
            "vue-template-compiler": "2.7.14",
        }
        package_json["eslintConfig"] = {
            "root": True,
            "env": {"node": True},
            "extends": ["plugin:vue/essential", "eslint:recommended"],
            "parserOptions": {"parser": "@babel/eslint-parser"},
            "rules": {},
        }
        package_json["browserslist"] = ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        package_json_path.write_text(json.dumps(package_json, ensure_ascii=False, indent=2), encoding="utf-8")
        (ws_path / "vibe-serve.js").write_text(_VIBE_SERVE_JS, encoding="utf-8")
        from app.config import settings
        (ws_path / "vibe-serve-config").write_text(f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n", encoding="utf-8")

        if apaas_json_path.exists():
            try:
                apaas_json = json.loads(apaas_json_path.read_text(encoding="utf-8"))
            except Exception:
                apaas_json = {}
        else:
            apaas_json = {}

        list_key = next(iter((apaas_json.get("list") or {}).keys()), f"apaas-custom-{self._strip_project_prefix(meta.get('project_type', ''), project_name)}")
        repaired_apaas = dict(apaas_json)
        repaired_apaas["entry"] = repaired_apaas.get("entry") or "index.js"
        repaired_apaas["templateType"] = "LIST_VIEW"
        repaired_apaas["router"] = repaired_apaas.get("router") or {}
        repaired_apaas["customWidgetList"] = repaired_apaas.get("customWidgetList") or []
        repaired_apaas["list"] = repaired_apaas.get("list") or {
            list_key: {
                "renderLogic": "FORM_LIST_VIEW",
                "desc": project_name,
                "status": "ENABLE",
            }
        }
        repaired_apaas["copyAssets"] = [f"public/form-view/{project_name}"]
        repaired_apaas["outputName"] = repaired_apaas.get("outputName") or project_name
        apaas_json_path.write_text(json.dumps(repaired_apaas, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_menu_page_workspace_compat(self, ws_path: Path):
        """修复旧版菜单/表单/移动页面工作区，使其对齐 MENU_PAGE 协议。"""
        meta = self._read_meta(ws_path)
        if meta.get("project_type") not in (
            ProjectType.FORM_PAGE.value,
            ProjectType.MENU_PAGE.value,
            ProjectType.MOBILE_PAGE.value,
        ):
            return

        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)
        asset_name = project_name
        if meta.get("project_type") == ProjectType.MOBILE_PAGE.value and not asset_name.startswith("form-page-"):
            asset_name = f"form-page-{asset_name}"
        package_json_path = ws_path / "package.json"
        apaas_json_path = ws_path / "src" / "apaas.json"
        public_dir = ws_path / "public" / "form-page" / asset_name
        public_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = public_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

        if package_json_path.exists():
            try:
                package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
            except Exception:
                package_json = {}
        else:
            package_json = {}

        existing_deps = package_json.get("dependencies") or {}
        existing_dev_deps = package_json.get("devDependencies") or {}
        current_package_name = (package_json.get("name") or "").strip()
        if meta.get("project_type") == ProjectType.MOBILE_PAGE.value:
            normalized_package_name = asset_name
        else:
            normalized_package_name = current_package_name or asset_name

        package_json.update({
            "name": normalized_package_name,
            "version": package_json.get("version") or "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "MENU_PAGE",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js",
                "serve": "node vibe-serve.js src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build",
            },
        })
        package_json["dependencies"] = {
            **existing_deps,
            "core-js": "3.8.3",
            "element-ui": existing_deps.get("element-ui") or "^2.15.14",
            "vue": "2.7.14",
        }
        package_json["devDependencies"] = {
            **existing_dev_deps,
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
            "vue-template-compiler": "2.7.14",
        }
        package_json["eslintConfig"] = {
            "root": True,
            "env": {"node": True},
            "extends": ["plugin:vue/essential", "eslint:recommended"],
            "parserOptions": {"parser": "@babel/eslint-parser"},
            "rules": {},
        }
        package_json["browserslist"] = ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        package_json_path.write_text(json.dumps(package_json, ensure_ascii=False, indent=2), encoding="utf-8")
        (ws_path / "vibe-serve.js").write_text(_VIBE_SERVE_JS, encoding="utf-8")
        from app.config import settings
        (ws_path / "vibe-serve-config").write_text(f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n", encoding="utf-8")

        if apaas_json_path.exists():
            try:
                apaas_json = json.loads(apaas_json_path.read_text(encoding="utf-8"))
            except Exception:
                apaas_json = {}
        else:
            apaas_json = {}

        router = apaas_json.get("router")
        if not isinstance(router, dict):
            router = {}
        if not router:
            router_name = f"apaas-custom-{self._strip_project_prefix(meta.get('project_type', ''), project_name)}"
            router = {
                router_name: {
                    "name": router_name,
                    "path": router_name,
                }
            }

        repaired_apaas = dict(apaas_json)
        repaired_apaas["entry"] = repaired_apaas.get("entry") or "index.js"
        repaired_apaas["templateType"] = "MENU_PAGE"
        repaired_apaas["router"] = router
        repaired_apaas["customWidgetList"] = repaired_apaas.get("customWidgetList") or []
        current_copy_assets = repaired_apaas.get("copyAssets")
        if meta.get("project_type") == ProjectType.MOBILE_PAGE.value:
            normalized_copy_assets = [f"public/form-page/{asset_name}"]
        else:
            normalized_copy_assets = current_copy_assets or [f"public/form-page/{asset_name}"]

        current_output_name = self._resolve_output_name(repaired_apaas, asset_name)
        if meta.get("project_type") == ProjectType.MOBILE_PAGE.value:
            normalized_output_name = asset_name
        else:
            normalized_output_name = current_output_name

        repaired_apaas["copyAssets"] = normalized_copy_assets
        repaired_apaas["outputName"] = normalized_output_name
        apaas_json_path.write_text(json.dumps(repaired_apaas, ensure_ascii=False, indent=2), encoding="utf-8")

        component_tag = next(iter(router.keys()), "")
        index_path = ws_path / "src" / "index.js"
        if component_tag and index_path.exists():
            try:
                index_content = index_path.read_text(encoding="utf-8")
            except Exception:
                index_content = ""

            needs_install_wrapper = "Vue.component(" in index_content and "const install = function" not in index_content
            if needs_install_wrapper:
                self._write(
                    ws_path,
                    "src/index.js",
                    f"""import "./form-page-local/index.js";
import ApaasCustomPage from "./form-page/{component_tag}.vue";

const install = function (Vue) {{
  Vue.component("{component_tag}", ApaasCustomPage);
  window[Symbol.for("{component_tag}")] = ApaasCustomPage;
}};

export default {{ install }};
""",
                )

    def _ensure_plugin_workspace_compat(self, ws_path: Path):
        """修复旧版插件工作区，使其对齐 FRONTEND_PLUGIN 协议。"""
        meta = self._read_meta(ws_path)
        if meta.get("project_type") != ProjectType.PLUGIN.value:
            return

        project_name = meta.get("project_name") or self._fallback_project_name_from_path(ws_path)
        package_json_path = ws_path / "package.json"
        apaas_json_path = ws_path / "src" / "apaas.json"
        public_dir = ws_path / "public" / "frontend-plugin" / project_name
        public_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = public_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

        if package_json_path.exists():
            try:
                package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
            except Exception:
                package_json = {}
        else:
            package_json = {}

        package_json.update({
            "name": package_json.get("name") or project_name,
            "version": package_json.get("version") or "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "FRONTEND_PLUGIN",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve-admin": "node vibe-serve.js src/admin.js",
                "serve-app": "node vibe-serve.js src/app.js",
                "serve-mobile": "node vibe-serve.js src/mobile.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build",
            },
        })
        package_json["dependencies"] = {
            **(package_json.get("dependencies") or {}),
            "core-js": "3.8.3",
            "vue": "2.7.14",
            "md5": "2.3.0",
        }
        package_json["devDependencies"] = {
            **(package_json.get("devDependencies") or {}),
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
            "vue-template-compiler": "2.7.14",
        }
        package_json["eslintConfig"] = {
            "root": True,
            "env": {"node": True},
            "extends": ["plugin:vue/essential", "eslint:recommended"],
            "parserOptions": {"parser": "@babel/eslint-parser"},
            "rules": {},
        }
        package_json["browserslist"] = ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
        package_json_path.write_text(json.dumps(package_json, ensure_ascii=False, indent=2), encoding="utf-8")
        (ws_path / "vibe-serve.js").write_text(_VIBE_SERVE_JS, encoding="utf-8")
        from app.config import settings
        (ws_path / "vibe-serve-config").write_text(f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n", encoding="utf-8")

        if apaas_json_path.exists():
            try:
                apaas_json = json.loads(apaas_json_path.read_text(encoding="utf-8"))
            except Exception:
                apaas_json = {}
        else:
            apaas_json = {}

        plugin_suffix = self._strip_project_prefix(meta.get("project_type", ""), project_name).replace("-", "_").upper() or "CUSTOM_PLUGIN"
        plugin_code = apaas_json.get("code")
        if not plugin_code:
            ext_list = apaas_json.get("extensionConfigList") or []
            if ext_list and isinstance(ext_list[0], dict):
                plugin_code = (ext_list[0].get("code") or "").strip()
        plugin_code = plugin_code or f"PLUGIN_{plugin_suffix}"

        repaired_apaas = dict(apaas_json)
        repaired_apaas["templateType"] = "FRONTEND_PLUGIN"
        repaired_apaas["copyAssets"] = [f"public/frontend-plugin/{project_name}"]
        repaired_apaas["code"] = plugin_code
        repaired_apaas["name"] = repaired_apaas.get("name", "")
        repaired_apaas["description"] = repaired_apaas.get("description", "")
        repaired_apaas["outputName"] = repaired_apaas.get("outputName") or project_name
        repaired_apaas["admin"] = "admin.js"
        repaired_apaas["app"] = "app.js"
        repaired_apaas["mobile"] = "mobile.js"
        repaired_apaas["extraConfig"] = repaired_apaas.get("extraConfig") or {}
        apaas_json_path.write_text(json.dumps(repaired_apaas, ensure_ascii=False, indent=2), encoding="utf-8")

        plugin_local = ws_path / "src" / "plugin-local"
        plugin_local.mkdir(parents=True, exist_ok=True)
        (plugin_local / "zh-CN").mkdir(parents=True, exist_ok=True)
        (plugin_local / "en-US").mkdir(parents=True, exist_ok=True)
        self._write(ws_path, "src/plugin-local/zh-CN/index.js", f"export default {{ frontendPlugin: {{ title: '{project_name}', panel: '自定义面板' }} }}\n")
        self._write(ws_path, "src/plugin-local/en-US/index.js", f"export default {{ frontendPlugin: {{ title: '{project_name}', panel: 'Custom Panel' }} }}\n")
        self._write(ws_path, "src/plugin-local/index.js", """import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

const mergeLocaleMessage =
  window.df?.getI18n?.().mergeLocaleMessage?.bind(window.df.getI18n()) ||
  window.APaaSSDK?.context?.globalVueI18n?.mergeLocaleMessage?.bind(window.APaaSSDK.context.globalVueI18n)

if (mergeLocaleMessage) {
  mergeLocaleMessage('zh-CN', zhLocaleModule)
  mergeLocaleMessage('en-US', enLocaleModule)
}
""")

        self._write(ws_path, "src/tab-config.js", """export function getCustomTabConfig() {
  return [
    {
      code: 'customPanel',
      title: '自定义面板',
      componentName: 'apaas-plugin-panel',
      resourceCode: 'APP_INFORMATION'
    }
  ]
}
""")
        self._write(ws_path, "src/extension.js", f"""import {{ getCustomTabConfig }} from './tab-config.js'

const extensionConfig = {{
  code: '{plugin_code}',
  name: '{project_name}',
  blocks: [],
  versions: ['TRIAL_EDITION', 'TEAM_EDITION', 'STANDARD_EDITION', 'PREMIUM_EDITION'],
  enable: true,
  extensionMethods: {{
    'custom-tab': {{
      getCustomTabConfig
    }}
  }}
}}

export default extensionConfig
""")
        self._write(ws_path, "src/custom-tab/custom-panel.vue", f"""<template>
  <div class="plugin-panel">
    <h3>{{{{ $t ? $t('frontendPlugin.title') : '{project_name}' }}}}</h3>
    <p>{{{{ $t ? $t('frontendPlugin.panel') : '自定义面板' }}}}</p>
  </div>
</template>

<script>
export default {{
  name: 'apaas-plugin-panel'
}}
</script>

<style scoped>
.plugin-panel {{
  padding: 16px;
}}
</style>
""")
        plugin_entry = """import './plugin-local/index.js'
import extensionConfig from './extension.js'
import CustomPanel from './custom-tab/custom-panel.vue'

const activateExtension = () => {
  const engine = window?.Vue?._extensionEngine
  if (engine && typeof engine.registerExtensionConfig === 'function') {
    engine.registerExtensionConfig(extensionConfig)
  }
}

// eslint-disable-next-line no-unused-vars
const install = function (context, hookManager, definition) {
  activateExtension()
}

// eslint-disable-next-line no-unused-vars
const activate = function (context, hookManager, definition) {
  activateExtension()
}

const staticComponents = [CustomPanel]

export default { install, activate, staticComponents }
"""
        self._write(ws_path, "src/admin.js", plugin_entry)
        self._write(ws_path, "src/app.js", plugin_entry)
        self._write(ws_path, "src/mobile.js", plugin_entry)

    def _ensure_backend_workspace_compat(self, ws_path: Path):
        """修复后端工作区 POM，使其至少具备可编译的依赖声明。"""
        meta = self._read_meta(ws_path)
        if meta.get("project_type") != ProjectType.BACKEND_API.value:
            return

        pom_path = ws_path / "pom.xml"
        if not pom_path.exists():
            return

        pom_text = pom_path.read_text(encoding="utf-8")
        # com.definesys.mpaas.* 已通过 com.xdap:app 传递依赖引入，无需单独声明
        # 清理历史遗留的 query-mongodb 显式依赖（旧版错误 groupId 或冗余声明）
        import re as _re
        pom_text = _re.sub(
            r'\s*<dependency>\s*<groupId>com\.definesys(?:\.mpaas)?</groupId>\s*'
            r'<artifactId>query-mongodb</artifactId>.*?</dependency>',
            '',
            pom_text,
            flags=_re.DOTALL,
        )
        if "<build>" not in pom_text:
            pom_text = pom_text.replace(
                "</profiles>",
                """</profiles>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
                <configuration>
                    <source>${java.version}</source>
                    <target>${java.version}</target>
                    <encoding>UTF-8</encoding>
                </configuration>
            </plugin>
        </plugins>
    </build>""",
            )
        pom_path.write_text(pom_text, encoding="utf-8")

    # ========== VS Code AI 配置 ==========

    def _setup_vscode_ai_config(self, ws_path: Path):
        """为 workspace 生成安全的 IDE 配置，不在工作区落盘任何 LLM 密钥。"""
        from app.config import settings

        model = settings.llm_model

        # ---- .vscode/settings.json ----
        vscode_dir = ws_path / ".vscode"
        vscode_dir.mkdir(exist_ok=True)

        vscode_settings = {
            "continue.enableTabAutocomplete": True,
            "minimax.model": model,
        }

        settings_file = vscode_dir / "settings.json"
        settings_file.write_text(
            json.dumps(vscode_settings, ensure_ascii=False, indent=2)
        )

        # Continue / 内置 Chat 统一改走后端代理，避免在工作区明文写入 API key。

    # ========== 脚手架模板 ==========

    # ── CLI 预生成模板脚手架 ─────────────────────────────────────

    def _scaffold_via_cli_template(self, ws_path: Path, name: str, project_type: ProjectType, display_name: str | None = None):
        """从 df-apaas-cli 预生成的标准模板复制并做变量替换。

        模板目录位于 backend/templates/cli-generated/{template_key}/，
        使用占位名 "demo" 生成，此方法将 "demo" 替换为用户实际的项目名。
        """
        template_key = CLI_TEMPLATE_MAP[project_type.value]
        template_dir = CLI_TEMPLATE_DIR / template_key
        if not template_dir.exists():
            logger.error(f"CLI template not found: {template_dir}")
            raise FileNotFoundError(f"CLI template directory missing: {template_dir}")

        # 1. 递归复制模板到 ws_path
        shutil.copytree(template_dir, ws_path, dirs_exist_ok=True)

        # 2. 变量替换
        self._replace_cli_template_vars(ws_path, name, project_type, display_name=display_name)

        # 3. 清理不需要的文件
        for fn in ("README.md",):
            p = ws_path / fn
            if p.exists():
                p.unlink()

        # 4. 写入 vibe-serve.js 和 vibe-serve-config
        from app.config import settings
        _proxy_base = (settings.code_server_base_url or "").rstrip("/")
        if project_type == ProjectType.FORM_COMPONENT_DUAL:
            # 双端工程：web/ 和 mobile/ 各是独立的 Vue CLI 项目，
            # vibe-serve.js 需分别写入各子目录（根目录无 package.json，无法执行）
            for _sub in ("web", "mobile"):
                (ws_path / _sub / "vibe-serve.js").write_text(_VIBE_SERVE_JS, encoding="utf-8")
                (ws_path / _sub / "vibe-serve-config").write_text(
                    f"PROXY_BASE={_proxy_base}\n", encoding="utf-8"
                )
        else:
            (ws_path / "vibe-serve.js").write_text(_VIBE_SERVE_JS, encoding="utf-8")
            (ws_path / "vibe-serve-config").write_text(
                f"PROXY_BASE={_proxy_base}\n", encoding="utf-8"
            )

        logger.info(f"Scaffolded {project_type.value} via CLI template: {ws_path.name}")

    def _replace_cli_template_vars(self, ws_path: Path, name: str, project_type: ProjectType, display_name: str | None = None):
        """将 CLI 模板中的 'demo' 占位替换为用户实际的项目名。

        替换分两步：1) 文件内容中的字符串替换 2) 文件名中的字符串替换。
        display_name 用于替换模板中的中文占位文字（"Demo组件" / "Demo组件描述"）。
        """
        placeholder = _CLI_TPL_PLACEHOLDER  # "demo"

        # 计算不含前缀的 kebab 短名（如 "rating-star"）
        prefix_map = {
            ProjectType.FORM_COMPONENT_DUAL: "form-component-",
            ProjectType.MENU_PAGE:           "form-page-",
            ProjectType.FORM_PAGE:           "form-page-",
            ProjectType.FORM_LIST:           "form-view-",
            ProjectType.LAYOUT:              "form-layout-",
            ProjectType.PLUGIN:              "frontend-plugin-",
        }
        full_prefix = prefix_map.get(project_type, "")
        # name 可能已经包含前缀，也可能不包含
        if name.startswith(full_prefix):
            short_name = name[len(full_prefix):]
        else:
            short_name = name
        if not short_name:
            short_name = "custom"

        # ── 构建替换对 ──────────────────────────
        replacements: list[tuple[str, str]] = []

        if project_type == ProjectType.FORM_COMPONENT_DUAL:
            # 双端模板：web/ 和 mobile/ 各有独立包
            old_kebab = f"form-component-{placeholder}"           # form-component-demo
            new_kebab = f"form-component-{short_name}"

            old_kebab_m = f"form-component-{placeholder}-m"      # form-component-demo-m（移动端 outputName）
            new_kebab_m = f"form-component-{short_name}-m"

            old_upper = f"FORM_CUSTOM_{placeholder.upper()}"      # FORM_CUSTOM_DEMO
            new_upper = "FORM_CUSTOM_" + short_name.replace("-", "_").upper()

            old_no_custom_upper = f"FORM_COMPONENT_{placeholder.upper()}"  # FORM_COMPONENT_DEMO
            new_no_custom_upper = "FORM_COMPONENT_" + short_name.replace("-", "_").upper()

            old_no_custom_kebab = old_no_custom_upper.replace("_", "-").lower()
            new_no_custom_kebab = new_no_custom_upper.replace("_", "-").lower()

            parts = short_name.split("-")
            pascal_suffix = "".join(p.capitalize() for p in parts)
            old_mobile_pascal = "MobileFormComponentDemo"          # 移动端组件名前缀（先替换，避免子串冲突）
            new_mobile_pascal = f"MobileFormComponent{pascal_suffix}"
            old_pascal = "FormComponentDemo"
            new_pascal = f"FormComponent{pascal_suffix}"

            replacements = [
                # 长串先替换，避免子串冲突
                (old_upper, new_upper),
                (old_no_custom_upper, new_no_custom_upper),
                (old_no_custom_kebab, new_no_custom_kebab),
                (old_mobile_pascal, new_mobile_pascal),            # Mobile 前缀先替换
                (old_pascal, new_pascal),
                (old_kebab_m, new_kebab_m),                       # -m 后缀先替换
                (old_kebab, new_kebab),
            ]
        elif project_type in (ProjectType.MENU_PAGE, ProjectType.FORM_PAGE):
            old_proj = f"form-page-{placeholder}"
            new_proj = f"form-page-{short_name}"
            old_route = f"apaas-custom-{placeholder}"
            new_route = f"apaas-custom-{short_name}"
            replacements = [
                (old_proj, new_proj),
                (old_route, new_route),
            ]
        elif project_type == ProjectType.FORM_LIST:
            old_proj = f"form-view-{placeholder}"
            new_proj = f"form-view-{short_name}"
            old_route = f"apaas-custom-{placeholder}"
            new_route = f"apaas-custom-{short_name}"
            replacements = [
                (old_proj, new_proj),
                (old_route, new_route),
            ]
        elif project_type == ProjectType.LAYOUT:
            old_proj = f"form-layout-{placeholder}"
            new_proj = f"form-layout-{short_name}"
            old_route = f"apaas-custom-{placeholder}"
            new_route = f"apaas-custom-{short_name}"
            replacements = [
                (old_proj, new_proj),
                (old_route, new_route),
                # layout apaas.json 中 desc 字段
                (f'"{placeholder} page layout"', f'"{short_name} page layout"'),
            ]
        elif project_type == ProjectType.PLUGIN:
            old_proj = f"frontend-plugin-{placeholder}"
            new_proj = f"frontend-plugin-{short_name}"
            # plugin apaas.json 中有 "code": "PLUGIN_DEMO", "name": "demo", "description": "demo plugin"
            old_plugin_code = f"PLUGIN_{placeholder.upper()}"
            new_plugin_code = "PLUGIN_" + short_name.replace("-", "_").upper()
            replacements = [
                (old_proj, new_proj),
                (old_plugin_code, new_plugin_code),
                # 裸 demo 出现在 "name"/"description" 字段中，用短名替换
                (f'"{placeholder} plugin"', f'"{short_name} plugin"'),
                (f'"name": "{placeholder}"', f'"name": "{short_name}"'),
            ]

        if not replacements:
            return

        # 如果提供了 display_name，追加中文占位文字的替换（desc.text / desc.description / widget.display.label 等）
        if display_name:
            replacements = list(replacements) + [
                ("Demo组件描述", display_name),  # 先替换较长的，避免子串冲突
                ("Demo组件", display_name),
            ]

        # 在 .cursor/rules 的 mdc 文件中也做替换
        text_suffixes = {".js", ".json", ".vue", ".mdc", ".md", ".css", ".html", ".ts"}

        # ── 步骤 1：替换文件内容 ──
        for fpath in ws_path.rglob("*"):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in text_suffixes:
                continue
            try:
                content = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue
            new_content = content
            for old, new in replacements:
                new_content = new_content.replace(old, new)
            if new_content != content:
                fpath.write_text(new_content, encoding="utf-8")

        # ── 步骤 2：重命名包含占位的文件和目录（从深到浅） ──
        # 收集所有需要重命名的路径
        for old, new in replacements:
            # 每次替换后重新遍历，因为路径可能已经变了
            paths_to_rename = sorted(
                (p for p in ws_path.rglob("*") if old in p.name),
                key=lambda p: len(p.parts),
                reverse=True,  # 从最深层开始
            )
            for p in paths_to_rename:
                new_name = p.name.replace(old, new)
                if new_name != p.name:
                    target = p.parent / new_name
                    if not target.exists():
                        p.rename(target)

    # ------------------------------------------------------------------
    # Layout scaffold
    # ------------------------------------------------------------------
    def _scaffold_layout(self, ws_path: Path, name: str):
        """布局脚手架 - WEB_LAYOUT 架构"""
        self._write_common_files(ws_path, name, "PAGE_LAYOUT")

        pascal = "".join(w.capitalize() for w in name.split("-"))
        layout_name = f"apaas-custom-{name}"
        output_name = f"form-layout-{name}"

        # ======== package.json ========
        self._write(ws_path, "package.json", json.dumps({
            "name": output_name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "PAGE_LAYOUT",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve": "node vibe-serve.js src/index.js",
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
        self._write(ws_path, "vibe-serve.js", _VIBE_SERVE_JS)
        from app.config import settings
        self._write(ws_path, "vibe-serve-config", f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n")

        # ======== vue.config.js ========
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
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
            "templateType": "PAGE_LAYOUT",
            "router": {},
            "customWidgetList": [],
            "layout": [{"name": layout_name, "desc": name, "status": "ENABLE"}],
            "copyAssets": [f"public/form-layout/{name}"],
            "outputName": output_name
        }, indent=2, ensure_ascii=False))

        # ======== src/form-layout-local/index.js ========
        self._write(ws_path, "src/form-layout-local/index.js", """// 预留给国际化和布局本地扩展
export default {}
""")

        # ======== src/index.js ========
        self._write(ws_path, "src/index.js", f"""import './form-layout-local/index.js'
import LayoutComponent from './form-layout/{layout_name}.vue'

const install = function (Vue) {{
  if (!Vue || !Vue.LayoutEngine) return
  const activeLayoutId = Vue.LayoutEngine.currentLayoutId || '{layout_name}'
  const layoutEngine = Vue.LayoutEngine.getInstance(activeLayoutId)
  Vue.component('{layout_name}', LayoutComponent)
  layoutEngine.registerLayoutComponent(LayoutComponent)
}}

export default {{ install }}
""")

        # ======== src/form-layout/*.vue ========
        self._write(ws_path, f"src/form-layout/{layout_name}.vue", f"""<template>
  <x-app-layout :layoutEngine="layoutEngine" :isCollapse="isCollapse">
    <template #header>
      <slot name="header">
        <x-app-header :layoutEngine="layoutEngine" :appInfo="appInfo" />
      </slot>
    </template>
    <template #menu>
      <slot name="menu">
        <x-app-menu
          :layoutEngine="layoutEngine"
          :menuConfig="menuConfig"
          :showMenu="showMenu"
          :isCollapse="isCollapse"
          @change-collapse="changeCollapse"
        />
      </slot>
    </template>
    <template #appPage>
      <slot name="appPage">
        <div class="layout-app-page">
          <div class="layout-card">
            <div class="layout-badge">AI 生成布局</div>
            <h2>{pascal} Layout</h2>
            <p>这是一个页面布局骨架，后续可以继续扩展 header、menu 和 appPage 区域。</p>
          </div>
        </div>
      </slot>
    </template>
  </x-app-layout>
</template>

<script>
export default {{
  name: '{pascal}Layout',
  props: {{
    layoutEngine: {{
      type: Object,
      default: function () {{
        return {{}}
      }},
    }},
    pkgVersion: {{
      type: String,
      default: '',
    }},
  }},
  data() {{
    return {{
      isCollapse: false,
      showMenu: true,
    }}
  }},
  computed: {{
    appInfo() {{
      return (
        (this.layoutEngine &&
          this.layoutEngine.layoutDataControl &&
          this.layoutEngine.layoutDataControl.appInfo) ||
        {{ appName: '{pascal} Layout' }}
      )
    }},
    menuConfig() {{
      return (
        (this.layoutEngine &&
          this.layoutEngine.layoutDataControl &&
          this.layoutEngine.layoutDataControl.menuConfig) || {{
          menuTreeData: [],
        }}
      )
    }},
  }},
  methods: {{
    changeCollapse() {{
      this.isCollapse = !this.isCollapse
    }},
  }},
}}
</script>

<style scoped>
.layout-app-page {{
  min-height: 100%;
  padding: 24px;
  background: linear-gradient(180deg, #f7f8fc 0%, #eef2f8 100%);
  box-sizing: border-box;
}}
.layout-card {{
  max-width: 680px;
  padding: 28px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 18px 36px rgba(31, 35, 71, 0.12);
}}
.layout-badge {{
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(64, 158, 255, 0.12);
  color: #2f6ef2;
  font-size: 12px;
  font-weight: 600;
}}
.layout-card h2 {{
  margin: 16px 0 10px;
  color: #1f2347;
  font-size: 28px;
}}
.layout-card p {{
  margin: 0;
  color: #5b6287;
  line-height: 1.7;
}}
</style>
""")

    # ------------------------------------------------------------------
    # Plugin scaffold
    # ------------------------------------------------------------------
    def _scaffold_plugin(self, ws_path: Path, name: str):
        """插件脚手架 - FRONTEND_PLUGIN 架构"""
        self._write_common_files(ws_path, name, "FRONTEND_PLUGIN")

        base_name = self._strip_project_prefix(ProjectType.PLUGIN.value, name) or name
        plugin_code = f"PLUGIN_{base_name.replace('-', '_').upper()}"

        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "FRONTEND_PLUGIN",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve-admin": "node vibe-serve.js src/admin.js",
                "serve-app": "node vibe-serve.js src/app.js",
                "serve-mobile": "node vibe-serve.js src/mobile.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build",
            },
            "dependencies": {
                "core-js": "3.8.3",
                "vue": "2.7.14",
                "md5": "2.3.0",
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
                "vue-template-compiler": "2.7.14",
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {},
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"],
        }, indent=2, ensure_ascii=False))
        self._write(ws_path, "vibe-serve.js", _VIBE_SERVE_JS)
        from app.config import settings
        self._write(ws_path, "vibe-serve-config", f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n")

        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const md5 = require('md5')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: {
    output: {
      library: md5(apaasJson.code),
      libraryTarget: 'umd'
    }
  },
  css: {
    loaderOptions: {
      sass: {
        implementation: require('sass')
      }
    }
  }
})
""")
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        self._write(ws_path, "src/apaas.json", json.dumps({
            "copyAssets": [f"public/frontend-plugin/{name}"],
            "templateType": "FRONTEND_PLUGIN",
            "code": plugin_code,
            "name": "",
            "description": "",
            "outputName": name,
            "admin": "admin.js",
            "app": "app.js",
            "mobile": "mobile.js",
            "extraConfig": {},
        }, indent=2, ensure_ascii=False))

        plugin_entry = """import './plugin-local/index.js'
import extensionConfig from './extension.js'
import CustomPanel from './custom-tab/custom-panel.vue'

const activateExtension = () => {
  const engine = window?.Vue?._extensionEngine
  if (engine && typeof engine.registerExtensionConfig === 'function') {
    engine.registerExtensionConfig(extensionConfig)
  }
}

// eslint-disable-next-line no-unused-vars
const install = function (context, hookManager, definition) {
  activateExtension()
}

// eslint-disable-next-line no-unused-vars
const activate = function (context, hookManager, definition) {
  activateExtension()
}

const staticComponents = [CustomPanel]

export default { install, activate, staticComponents }
"""
        self._write(ws_path, "src/admin.js", plugin_entry)
        self._write(ws_path, "src/app.js", plugin_entry)
        self._write(ws_path, "src/mobile.js", plugin_entry)
        self._write(ws_path, "src/api/index.js", "export default {}\n")

        self._write(ws_path, "src/plugin-local/index.js", """import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

const mergeLocaleMessage =
  window.df?.getI18n?.().mergeLocaleMessage?.bind(window.df.getI18n()) ||
  window.APaaSSDK?.context?.globalVueI18n?.mergeLocaleMessage?.bind(window.APaaSSDK.context.globalVueI18n)

if (mergeLocaleMessage) {
  mergeLocaleMessage('zh-CN', zhLocaleModule)
  mergeLocaleMessage('en-US', enLocaleModule)
}
""")
        self._write(ws_path, "src/plugin-local/zh-CN/index.js", f"export default {{ frontendPlugin: {{ title: '{name}', panel: '自定义面板' }} }}\n")
        self._write(ws_path, "src/plugin-local/en-US/index.js", f"export default {{ frontendPlugin: {{ title: '{name}', panel: 'Custom Panel' }} }}\n")

        self._write(ws_path, "src/tab-config.js", """export function getCustomTabConfig() {
  return [
    {
      code: 'customPanel',
      title: '自定义面板',
      componentName: 'apaas-plugin-panel',
      resourceCode: 'APP_INFORMATION'
    }
  ]
}
""")
        self._write(ws_path, "src/extension.js", f"""import {{ getCustomTabConfig }} from './tab-config.js'

const extensionConfig = {{
  code: '{plugin_code}',
  name: '{name}',
  blocks: [],
  versions: ['TRIAL_EDITION', 'TEAM_EDITION', 'STANDARD_EDITION', 'PREMIUM_EDITION'],
  enable: true,
  extensionMethods: {{
    'custom-tab': {{
      getCustomTabConfig
    }}
  }}
}}

export default extensionConfig
""")

        self._write(ws_path, "src/custom-tab/custom-panel.vue", f"""<template>
  <div class="plugin-panel">
    <h3>{{{{ $t ? $t('frontendPlugin.title') : '{name}' }}}}</h3>
    <p>{{{{ $t ? $t('frontendPlugin.panel') : '自定义面板' }}}}</p>
  </div>
</template>

<script>
export default {{
  name: 'apaas-plugin-panel'
}}
</script>

<style scoped>
.plugin-panel {{
  padding: 16px;
}}
</style>
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
                "serve": "node vibe-serve.js src/index.js",
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
        self._write(ws_path, "vibe-serve.js", _VIBE_SERVE_JS)
        from app.config import settings
        self._write(ws_path, "vibe-serve-config", f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n")

        # ======== vue.config.js ========
        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
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

const platformI18n =
  window.df?.getI18n?.() ||
  window.APaaSSDK?.context?.globalVueI18n

if (platformI18n?.mergeLocaleMessage) {
  platformI18n.mergeLocaleMessage('zh-CN', zhLocaleModule)
  platformI18n.mergeLocaleMessage('en-US', enLocaleModule)
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

        if mobile:
            self._write(ws_path, f"src/form-page/{component_tag}.vue", f"""<template>
  <div class="{component_tag}">
    <header class="page-header">
      <div class="page-header-main">
        <div class="page-eyebrow">移动端页面</div>
        <h2 class="page-title">{kebab}</h2>
        <p class="page-subtitle">适合扫码、审批、采集等移动业务场景的默认骨架。</p>
      </div>
      <button class="ghost-btn" @click="refreshList">刷新</button>
    </header>

    <section class="search-card">
      <label class="field-label">关键字</label>
      <div class="field-row">
        <input
          v-model.trim="keyword"
          class="field-input"
          placeholder="请输入名称或编码"
          @keyup.enter="loadList"
        />
        <button class="search-btn" @click="loadList">搜索</button>
      </div>
    </section>

    <section class="summary-card">
      <div class="summary-label">数据状态</div>
      <div class="summary-value">{{{{ loading ? '加载中...' : items.length + ' 条记录' }}}}</div>
      <div class="summary-meta">当前页面为移动端骨架，默认使用原生布局和触屏尺寸。</div>
    </section>

    <section class="list-section">
      <div v-if="items.length" class="mobile-list">
        <article v-for="item in items" :key="item.id" class="mobile-card" @click="selectItem(item)">
          <div class="mobile-card-top">
            <strong>{{{{ item.name || item.id }}}}</strong>
            <span class="status-chip">{{{{ item.status || '待处理' }}}}</span>
          </div>
          <div class="mobile-card-code">编码：{{{{ item.code || '--' }}}}</div>
        </article>
      </div>
      <div v-else class="empty-state">
        <div class="empty-title">{{{{ loading ? '正在加载数据' : '暂无数据' }}}}</div>
        <div class="empty-desc">后续可以在这里接入扫码、定位、审批按钮或更复杂的移动流程。</div>
      </div>
    </section>

    <footer class="page-footer">
      <button class="primary-btn" @click="handlePrimaryAction">提交操作</button>
    </footer>
  </div>
</template>

<script>
import Api from "../api";

export default {{
  name: "{component_tag}",
  data() {{
    return {{
      keyword: "",
      loading: false,
      items: [],
      selectedItem: null,
    }};
  }},
  created() {{
    this.loadList();
  }},
  methods: {{
    loadList() {{
      this.loading = true;
      this.$request({{
        ...Api.QUERY_LIST,
        params: {{
          keyword: this.keyword,
        }},
      }})
        .asyncThen((resp) => {{
          const list = resp && resp.data ? resp.data : [];
          this.items = Array.isArray(list) ? list : [];
          this.loading = false;
        }})
        .asyncErrorCatch((error) => {{
          console.error("加载数据失败:", error);
          this.loading = false;
        }});
    }},
    refreshList() {{
      this.loadList();
    }},
    selectItem(item) {{
      this.selectedItem = item;
    }},
    handlePrimaryAction() {{
      console.log("mobile primary action", this.selectedItem || null);
    }},
  }},
}};
</script>

<style lang="scss">
.{component_tag} {{
  min-height: 100vh;
  background: linear-gradient(180deg, #f7f9fc 0%, #eef3f9 100%);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  color: #1f2937;
  box-sizing: border-box;

  .page-header,
  .search-card,
  .summary-card,
  .mobile-card,
  .page-footer {{
    background: #fff;
    border-radius: 18px;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
  }}

  .page-header {{
    padding: 18px 16px;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }}

  .page-header-main {{
    flex: 1;
  }}

  .page-eyebrow {{
    font-size: 12px;
    letter-spacing: 0.08em;
    color: #64748b;
    margin-bottom: 6px;
  }}

  .page-title {{
    font-size: 22px;
    line-height: 1.2;
    margin-bottom: 6px;
  }}

  .page-subtitle {{
    font-size: 13px;
    line-height: 1.5;
    color: #6b7280;
  }}

  .ghost-btn,
  .search-btn,
  .primary-btn {{
    min-height: 44px;
    border: none;
    border-radius: 14px;
    font-size: 14px;
    cursor: pointer;
  }}

  .ghost-btn {{
    min-width: 72px;
    padding: 0 14px;
    background: #eef4ff;
    color: #2563eb;
  }}

  .search-card {{
    padding: 14px;
  }}

  .field-label {{
    display: block;
    font-size: 13px;
    color: #64748b;
    margin-bottom: 8px;
  }}

  .field-row {{
    display: flex;
    gap: 10px;
  }}

  .field-input {{
    flex: 1;
    min-height: 44px;
    border: 1px solid #dbe3ef;
    border-radius: 14px;
    padding: 0 14px;
    font-size: 15px;
    background: #f8fafc;
  }}

  .search-btn {{
    min-width: 84px;
    padding: 0 14px;
    background: #2563eb;
    color: #fff;
  }}

  .summary-card {{
    padding: 16px;
  }}

  .summary-label {{
    font-size: 13px;
    color: #64748b;
    margin-bottom: 6px;
  }}

  .summary-value {{
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 8px;
  }}

  .summary-meta {{
    font-size: 13px;
    color: #6b7280;
    line-height: 1.5;
  }}

  .list-section {{
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }}

  .mobile-list {{
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}

  .mobile-card {{
    padding: 16px;
    cursor: pointer;
  }}

  .mobile-card-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
  }}

  .mobile-card-code {{
    font-size: 13px;
    color: #6b7280;
  }}

  .status-chip {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 28px;
    padding: 0 10px;
    border-radius: 999px;
    background: #e0ecff;
    color: #2563eb;
    font-size: 12px;
    font-weight: 600;
  }}

  .empty-state {{
    padding: 28px 18px;
    text-align: center;
    color: #6b7280;
  }}

  .empty-title {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 8px;
    color: #374151;
  }}

  .empty-desc {{
    font-size: 13px;
    line-height: 1.6;
  }}

  .page-footer {{
    padding: 14px;
    position: sticky;
    bottom: 0;
  }}

  .primary-btn {{
    width: 100%;
    background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
    color: #fff;
    font-weight: 600;
  }}
}}
</style>
""")

            self._write(ws_path, "preview/App.vue", f"""<template>
  <div class="mobile-preview-shell">
    <div class="mobile-preview-frame">
      <div class="mobile-preview-notch"></div>
      <{component_tag} />
    </div>
  </div>
</template>

<script>
export default {{ name: 'PreviewApp' }}
</script>

<style scoped>
.mobile-preview-shell {{
  min-height: 100vh;
  padding: 16px;
  background: linear-gradient(180deg, #eef2f7 0%, #e6ebf2 100%);
}}

.mobile-preview-frame {{
  width: min(100%, 390px);
  min-height: calc(100vh - 32px);
  margin: 0 auto;
  background: #fff;
  border-radius: 28px;
  overflow: hidden;
  box-shadow: 0 20px 48px rgba(15, 23, 42, 0.16);
}}

.mobile-preview-notch {{
  width: 120px;
  height: 6px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.12);
  margin: 12px auto 4px;
}}
</style>
""")

            self._write(ws_path, "preview/main.js", f"""import Vue from 'vue'
import {{ installMockRequest }} from './mock-api'
import ApaasCustomPage from '../src/form-page/{component_tag}.vue'
import App from './App.vue'

installMockRequest(Vue)

Vue.component('{component_tag}', ApaasCustomPage)

new Vue({{
  el: '#app',
  render: h => h(App)
}})
""")

    def _scaffold_form_list(self, ws_path: Path, name: str):
        """列表视图脚手架"""
        self._write_common_files(ws_path, name, "LIST_VIEW")

        base_name = self._strip_project_prefix(ProjectType.FORM_LIST.value, name) or name
        component_tag = f"apaas-custom-{base_name}"

        self._write(ws_path, "package.json", json.dumps({
            "name": name,
            "version": "1.0.0",
            "engines": {"node": "16.x"},
            "templateType": "LIST_VIEW",
            "private": True,
            "scripts": {
                "lint": "vue-cli-service lint",
                "serve": "node vibe-serve.js src/index.js",
                "debug": "df-apaas-cli debug",
                "build": "df-apaas-cli build",
            },
            "dependencies": {
                "core-js": "3.8.3",
                "vue": "2.7.14",
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
                "vue-template-compiler": "2.7.14",
            },
            "eslintConfig": {
                "root": True,
                "env": {"node": True},
                "extends": ["plugin:vue/essential", "eslint:recommended"],
                "parserOptions": {"parser": "@babel/eslint-parser"},
                "rules": {},
            },
            "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"],
        }, indent=2, ensure_ascii=False))
        self._write(ws_path, "vibe-serve.js", _VIBE_SERVE_JS)
        from app.config import settings
        self._write(ws_path, "vibe-serve-config", f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n")

        self._write(ws_path, "vue.config.js", """const { defineConfig } = require('@vue/cli-service')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
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
      sass: {
        implementation: require('sass')
      }
    }
  }
})
""")
        self._write(ws_path, "babel.config.js", "module.exports = {\n  presets: ['@vue/cli-plugin-babel/preset']\n}\n")

        self._write(ws_path, "src/apaas.json", json.dumps({
            "entry": "index.js",
            "templateType": "LIST_VIEW",
            "router": {},
            "customWidgetList": [],
            "list": {
                component_tag: {
                    "renderLogic": "FORM_LIST_VIEW",
                    "desc": name,
                    "status": "ENABLE",
                }
            },
            "copyAssets": [f"public/form-view/{name}"],
            "outputName": name,
        }, indent=2, ensure_ascii=False))

        self._write(ws_path, "src/index.js", f"""import './form-view-local/index.js'
import CustomListView from './form-view/{component_tag}.vue'

const install = function(Vue) {{
  Vue.component('{component_tag}', CustomListView)
}}

export default {{ install }}
""")
        self._write(ws_path, "src/api/index.js", "export default {}\n")
        self._write(ws_path, "src/form-view-local/index.js", """import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

const mergeLocaleMessage =
  window.df?.getI18n?.().mergeLocaleMessage?.bind(window.df.getI18n()) ||
  window.APaaSSDK?.context?.globalVueI18n?.mergeLocaleMessage?.bind(window.APaaSSDK.context.globalVueI18n)

if (mergeLocaleMessage) {
  mergeLocaleMessage('zh-CN', zhLocaleModule)
  mergeLocaleMessage('en-US', enLocaleModule)
}
""")
        self._write(ws_path, "src/form-view-local/zh-CN/index.js", f"export default {{ formView: {{ title: '{name}' }} }}\n")
        self._write(ws_path, "src/form-view-local/en-US/index.js", f"export default {{ formView: {{ title: '{name}' }} }}\n")

        self._write(ws_path, f"src/form-view/{component_tag}.vue", f"""<template>
  <div class="{component_tag}">
    <x-list-view :listEngine="listEngine">
      <template #listTable>
        <x-list-table
          ref="xListTableView"
          :treeViewListEngine="listEngine"
          :treeViewInAssoc="true"
          :pageViewComponents="listEngine.listDataControl.tablePanelComponents"
        ></x-list-table>
      </template>
    </x-list-view>
  </div>
</template>

<script>
export default {{
  name: 'CustomListView',
  props: {{
    listEngine: {{
      type: Object,
      default: () => ({{}})
    }}
  }},
  mounted() {{
    if (this.$refs.xListTableView) {{
      this.$refs.xListTableView.handlerRowClick = function () {{
        return undefined
      }}
    }}
  }}
}}
</script>

<style lang="scss">
.{component_tag} {{
  height: 100%;
}}
</style>
""")

    def _scaffold_backend_api(self, ws_path: Path, name: str):
        """后端接口脚手架 — 从 backend/templates/backend-api 模板目录生成"""
        module_name = name.replace("backend-api-", "")
        pkg_path = module_name.replace("-", "")
        class_prefix = "".join(p.capitalize() for p in module_name.split("-"))
        replacements = {
            "{basePackage}": pkg_path,
            "{class_prefix}": class_prefix,
            "{module_name}": module_name,
        }
        self._scaffold_from_template(ws_path, "backend-api", replacements)

    def _scaffold_backend_feign(self, ws_path: Path, name: str):
        """FeignClient 外部调用脚手架 — 复用 backend-api 模板 + 追加 Feign 特有文件"""
        module_name = name.replace("backend-feign-", "")
        pkg_path = module_name.replace("-", "")
        class_prefix = "".join(p.capitalize() for p in module_name.split("-"))
        base_pkg = f"src/main/java/com/xdap/{pkg_path}"
        field_name = module_name.replace("-", "")

        # 复用基础模板（.claude/rules, .claude/skills, examples, pom.xml, 基础类）
        replacements = {
            "{basePackage}": pkg_path,
            "{class_prefix}": class_prefix,
            "{module_name}": module_name,
        }
        self._scaffold_from_template(ws_path, "backend-api", replacements)

        # 覆写 Application.java — 加 @EnableFeignClients
        self._write(ws_path, f"{base_pkg}/Application.java", f"""\
package com.xdap.{pkg_path};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@EnableFeignClients
@ComponentScan({{"com.definesys.mpaas", "com.xdap.*"}})
public class Application {{

    public static void main(String[] args) {{
        SpringApplication.run(Application.class, args);
    }}
}}
""")

        # FeignClient 配置
        self._write(ws_path, f"{base_pkg}/config/{class_prefix}FeignConfig.java", f"""\
package com.xdap.{pkg_path}.config;

import feign.RequestInterceptor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Feign 全局配置 — 为所有外部调用注入认证 Header
 */
@Configuration
public class {class_prefix}FeignConfig {{

    @Value("${{external.api.token:}}")
    private String apiToken;

    @Bean
    public RequestInterceptor authRequestInterceptor() {{
        return requestTemplate -> {{
            if (apiToken != null && !apiToken.isEmpty()) {{
                requestTemplate.header("Authorization", "Bearer " + apiToken);
            }}
        }};
    }}
}}
""")

        # FeignClient 接口
        self._write(ws_path, f"{base_pkg}/client/{class_prefix}FeignClient.java", f"""\
package com.xdap.{pkg_path}.client;

import com.xdap.{pkg_path}.dto.{class_prefix}RequestDTO;
import com.xdap.{pkg_path}.dto.{class_prefix}ResponseDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/**
 * {class_prefix} 外部调用客户端
 * url 配置在 application.yml 中：external.api.base-url
 */
@FeignClient(name = "{module_name}-client", url = "${{external.api.base-url}}")
public interface {class_prefix}FeignClient {{

    @PostMapping("/api/v1/query")
    {class_prefix}ResponseDTO query(@RequestBody {class_prefix}RequestDTO request);
}}
""")

        # Request/Response DTO
        self._write(ws_path, f"{base_pkg}/dto/{class_prefix}RequestDTO.java", f"""\
package com.xdap.{pkg_path}.dto;

import lombok.Data;

@Data
public class {class_prefix}RequestDTO {{
    private String id;
    private String keyword;
}}
""")

        self._write(ws_path, f"{base_pkg}/dto/{class_prefix}ResponseDTO.java", f"""\
package com.xdap.{pkg_path}.dto;

import lombok.Data;

@Data
public class {class_prefix}ResponseDTO {{
    private Integer code;
    private String message;
    private Object data;
}}
""")

        # Service
        self._write(ws_path, f"{base_pkg}/service/{class_prefix}Service.java", f"""\
package com.xdap.{pkg_path}.service;

import com.xdap.{pkg_path}.dto.{class_prefix}RequestDTO;
import com.xdap.{pkg_path}.dto.{class_prefix}ResponseDTO;

public interface {class_prefix}Service {{
    {class_prefix}ResponseDTO query({class_prefix}RequestDTO request);
}}
""")

        self._write(ws_path, f"{base_pkg}/service/impl/{class_prefix}ServiceImpl.java", f"""\
package com.xdap.{pkg_path}.service.impl;

import com.xdap.{pkg_path}.client.{class_prefix}FeignClient;
import com.xdap.{pkg_path}.dto.{class_prefix}RequestDTO;
import com.xdap.{pkg_path}.dto.{class_prefix}ResponseDTO;
import com.xdap.{pkg_path}.service.{class_prefix}Service;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class {class_prefix}ServiceImpl implements {class_prefix}Service {{

    private final {class_prefix}FeignClient {field_name}FeignClient;

    @Override
    public {class_prefix}ResponseDTO query({class_prefix}RequestDTO request) {{
        return {field_name}FeignClient.query(request);
    }}
}}
""")

        # Controller
        self._write(ws_path, f"{base_pkg}/controller/{class_prefix}Controller.java", f"""\
package com.xdap.{pkg_path}.controller;

import com.xdap.{pkg_path}.dto.{class_prefix}RequestDTO;
import com.xdap.{pkg_path}.dto.{class_prefix}ResponseDTO;
import com.xdap.{pkg_path}.service.{class_prefix}Service;
import com.definesys.mpaas.common.http.Response;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/custom/{module_name}")
@RequiredArgsConstructor
public class {class_prefix}Controller {{

    private final {class_prefix}Service {field_name}Service;

    @PostMapping("/query")
    public Response query(@RequestBody {class_prefix}RequestDTO request) {{
        {class_prefix}ResponseDTO result = {field_name}Service.query(request);
        return Response.ok().data(result);
    }}
}}
""")

        # application.yml（覆写 properties）
        self._write(ws_path, "src/main/resources/application.yml", f"""\
external:
  api:
    base-url: https://your-external-api.com
    token: your-token-here

server:
  port: 8080
""")

    def _scaffold_backend_scheduled(self, ws_path: Path, name: str):
        """定时任务脚手架 — 复用 backend-api 模板 + 追加定时任务特有文件"""
        module_name = name.replace("backend-scheduled-", "")
        pkg_path = module_name.replace("-", "")
        class_prefix = "".join(p.capitalize() for p in module_name.split("-"))
        base_pkg = f"src/main/java/com/xdap/{pkg_path}"
        field_name = module_name.replace("-", "")

        # 复用基础模板
        replacements = {
            "{basePackage}": pkg_path,
            "{class_prefix}": class_prefix,
            "{module_name}": module_name,
        }
        self._scaffold_from_template(ws_path, "backend-api", replacements)

        # 覆写 Application.java — 加 @EnableScheduling
        self._write(ws_path, f"{base_pkg}/Application.java", f"""\
package com.xdap.{pkg_path};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@EnableScheduling
@ComponentScan({{"com.definesys.mpaas", "com.xdap.*"}})
public class Application {{

    public static void main(String[] args) {{
        SpringApplication.run(Application.class, args);
    }}
}}
""")

        # Dao
        self._write(ws_path, f"{base_pkg}/dao/{class_prefix}Dao.java", f"""\
package com.xdap.{pkg_path}.dao;

import com.xdap.{pkg_path}.config.DatasourceUtil;
import com.definesys.mpaas.query.MpaasQuery;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import java.util.List;
import java.util.Map;

@Component
@RequiredArgsConstructor
public class {class_prefix}Dao {{

    private final DatasourceUtil datasourceUtil;

    public List<Map<String, Object>> getPendingByStatus(String status) {{
        if (status == null) return java.util.Collections.emptyList();
        MpaasQuery query = datasourceUtil.buildDefaultMpaasQuery();
        return query.from("your_table_name")
                .eq("status", status)
                .doQuery()
                .getList();
    }}

    public int updateStatusById(String id, String newStatus) {{
        if (id == null || newStatus == null) return 0;
        MpaasQuery query = datasourceUtil.buildDefaultMpaasQuery();
        return query.from("your_table_name")
                .set("status", newStatus)
                .eq("id", id)
                .doUpdate();
    }}
}}
""")

        # Service
        self._write(ws_path, f"{base_pkg}/service/{class_prefix}Service.java", f"""\
package com.xdap.{pkg_path}.service;

public interface {class_prefix}Service {{
    void execute();
}}
""")

        self._write(ws_path, f"{base_pkg}/service/impl/{class_prefix}ServiceImpl.java", f"""\
package com.xdap.{pkg_path}.service.impl;

import com.xdap.{pkg_path}.dao.{class_prefix}Dao;
import com.xdap.{pkg_path}.service.{class_prefix}Service;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class {class_prefix}ServiceImpl implements {class_prefix}Service {{

    private final {class_prefix}Dao {field_name}Dao;

    @Override
    public void execute() {{
        log.info("[{class_prefix}Task] 开始执行");
        List<Map<String, Object>> pendingList = {field_name}Dao.getPendingByStatus("PENDING");
        log.info("[{class_prefix}Task] 待处理记录数: {{}}", pendingList.size());
        for (Map<String, Object> record : pendingList) {{
            try {{
                String id = (String) record.get("id");
                // TODO: 添加业务处理逻辑
                {field_name}Dao.updateStatusById(id, "PROCESSED");
                log.info("[{class_prefix}Task] 处理成功, id={{}}", id);
            }} catch (Exception e) {{
                log.error("[{class_prefix}Task] 处理失败, record={{}}", record, e);
            }}
        }}
        log.info("[{class_prefix}Task] 执行完成");
    }}
}}
""")

        # 定时任务入口
        self._write(ws_path, f"{base_pkg}/task/{class_prefix}ScheduledTask.java", f"""\
package com.xdap.{pkg_path}.task;

import com.xdap.{pkg_path}.service.{class_prefix}Service;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class {class_prefix}ScheduledTask {{

    private final {class_prefix}Service {field_name}Service;

    @Scheduled(cron = "0 0 2 * * ?")
    public void run() {{
        log.info("[{class_prefix}ScheduledTask] 触发执行");
        {field_name}Service.execute();
    }}
}}
""")

        # application.yml
        self._write(ws_path, "src/main/resources/application.yml", f"""\
server:
  port: 8080

scheduled:
  {module_name}:
    enabled: true
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
                "serve": "node vibe-serve.js src/index.js",
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
        self._write(ws_path, "vibe-serve.js", _VIBE_SERVE_JS)
        from app.config import settings
        self._write(ws_path, "vibe-serve-config", f"PROXY_BASE={(settings.code_server_base_url or '').rstrip('/')}\n")

        # vue.config.js
        self._write(ws_path, "vue.config.js", f"""const path = require('path')
module.exports = {{
  outputDir: 'dist',
  configureWebpack: {{
    output: {{ library: '{full_name}', libraryTarget: 'umd', jsonpFunction: 'webpackJsonp_{full_name.replace("-","_")}' }},
    resolve: {{ alias: {{ '@': path.resolve(__dirname, 'src') }} }},
  }},
  devServer: {{ port: 8080, headers: {{ 'Access-Control-Allow-Origin': '*' }} }},
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

    def _scaffold_from_template(self, ws_path: Path, template_dir: str, replacements: dict):
        """从模板目录复制文件到 workspace，对文件路径和内容执行变量替换"""
        tpl_root = Path(__file__).parent.parent.parent / "templates" / template_dir
        if not tpl_root.exists():
            logger.warning(f"Template directory not found: {tpl_root}")
            return
        for src_file in sorted(tpl_root.rglob("*")):
            if src_file.is_dir():
                continue
            if src_file.name == ".DS_Store":
                continue
            # 过滤 macOS AppleDouble 元数据文件（._xxx）
            if src_file.name.startswith("._"):
                continue
            rel = str(src_file.relative_to(tpl_root))
            for k, v in replacements.items():
                rel = rel.replace(k, v)
            try:
                content = src_file.read_text(encoding="utf-8")
                for k, v in replacements.items():
                    content = content.replace(k, v)
                self._write(ws_path, rel, content)
            except UnicodeDecodeError:
                # 二进制文件直接复制
                target = ws_path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, target)
