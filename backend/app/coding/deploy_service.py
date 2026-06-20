"""Coding self-development upload and deploy orchestration."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.apaas_client import APaaSClient
from app.coding.apaas_tools import call_apaas_with_relogin, _relogin_apaas_env
from app.coding.workspace import ProjectType, WorkspaceManager
from app.error_messages import is_apaas_token_error
from app.config import settings
from app.routes.applications.extension import (
    _ensure_env_token,
    _load_app_and_env,
    publish_extension_update,
)

logger = logging.getLogger(__name__)


# project_type -> 平台 fileType 映射
_PROJECT_TYPE_TO_FILE_TYPE = {
    "form-component-dual": "FRONTCOMPONENT",
    "menu-page": "FRONTENGINE",
    "form-page": "FRONTENGINE",
    "form-list": "FRONTLISTVIEW",
    "layout": "FRONTLAYOUT",
    "mobile-page": "MFRONTENGINE",
    "plugin": "FRONTTENANTCOMPONENT",
    "backend-api": "BACKENDENGINE",
    "backend-feign": "BACKENDENGINE",
    "backend-scheduled": "BACKENDENGINE",
}


async def _query_existing_development_kits(
    base_url: str,
    tenant_id: str,
    token: str,
    key_word: str,
) -> list[dict]:
    """查询平台已有的自开发组件列表（模糊匹配 keyWord）。"""
    import time as _time

    query_url = f"{base_url.rstrip('/')}/xdap-app/selfdevelopment/query/allDevelopmentKit"
    logger.info("[upload-to-platform] 查询已有组件 keyWord=%r", key_word)
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        try:
            resp = await http.post(
                query_url,
                headers={
                    "xdaptenantid": tenant_id,
                    "xdaptoken": token,
                    "xdaptimestamp": str(int(_time.time() * 1000)),
                    "Content-Type": "application/json",
                },
                json={"keyWord": key_word, "page": 1, "pageSize": 50},
            )
        except httpx.RequestError as e:
            logger.warning("[upload-to-platform] 查询已有组件失败: %s", e)
            return []
    try:
        data = resp.json()
    except Exception:
        logger.warning("[upload-to-platform] 查询响应非 JSON: status=%s", resp.status_code)
        return []
    if data.get("code") != "ok":
        logger.warning("[upload-to-platform] 查询失败 code=%s msg=%s", data.get("code"), data.get("message"))
        return []
    table = data.get("table") or []
    kits = [item for item in table if isinstance(item, dict)]
    logger.info("[upload-to-platform] 查询到 %s 条: %s", len(kits), [k.get("fileName") for k in kits])
    return kits


def _find_kit_by_filename(kits: list[dict], file_name: str) -> Optional[dict]:
    """在查询返回的 table 中按 fileName 精准匹配。"""
    for item in kits:
        if item.get("fileName") == file_name:
            return item
    return None


def _normalize_backend_jdk(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"8", "1.8", "jdk8", "java8"}:
        return "8"
    if text in {"17", "jdk17", "java17"}:
        return "17"
    if text == "auto":
        return "auto"
    return "17"


def _resolve_backend_runtime_version(ws_path: Path) -> str:
    """Resolve the runtime jar version that must accompany backend self-dev jars."""
    override = (os.environ.get("APAAS_BACKEND_RUNTIME_VERSION") or "").strip()
    if override:
        return override

    jdk = _normalize_backend_jdk(settings.apaas_backend_jdk_version)
    if jdk == "17":
        return "5.0.0"
    if jdk == "8":
        return "4.1.1-rc"

    pom = ws_path / "pom.xml"
    if pom.exists():
        text = pom.read_text(encoding="utf-8", errors="ignore")
        java_match = re.search(r"<java\.version>\s*([^<]+?)\s*</java\.version>", text)
        source_match = re.search(r"<maven\.compiler\.source>\s*([^<]+?)\s*</maven\.compiler\.source>", text)
        java_version = (java_match or source_match).group(1).strip() if (java_match or source_match) else ""
        if java_version.startswith("17"):
            return "5.0.0"
        papaas_match = re.search(r"<papaas\.version>\s*([^<]+?)\s*</papaas\.version>", text)
        if papaas_match:
            return papaas_match.group(1).strip()

    return "5.0.0"


def _resolve_backend_runtime_jar(ws_path: Path) -> Path:
    override = (os.environ.get("APAAS_BACKEND_RUNTIME_JAR") or "").strip()
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return path
        raise FileNotFoundError(f"APAAS_BACKEND_RUNTIME_JAR 指向的文件不存在: {path}")

    version = _resolve_backend_runtime_version(ws_path)
    repo = Path(os.environ.get("MAVEN_REPO_LOCAL") or Path.home() / ".m2" / "repository").expanduser()
    jar = repo / "com" / "xdap" / "runtime" / version / f"runtime-{version}.jar"
    if jar.exists():
        return jar
    raise FileNotFoundError(
        f"后端自开发需要 runtime-{version}.jar,但本机 Maven 缓存未找到: {jar}"
    )


def _build_upload_form_data(
    *,
    file_type: str,
    description: str,
    version_code: str,
    upload_id: str,
    existing_kit: Optional[dict] = None,
) -> dict:
    """构造上传的表单字段。"""
    effective_description = description
    if existing_kit:
        from datetime import datetime as _dt

        ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        effective_description = f"{description}（更新于 {ts}）"

    form: dict = {
        "fileType": file_type,
        "description": effective_description,
        "uploadId": upload_id,
        "versionCode": version_code,
        "useScope": "全部应用",
        "internalResource": "false",
        "effectiveScope": "SINGLE_APPLICATION",
    }
    if existing_kit:
        for key in ("id", "ossObjectName", "fileName", "yeahMonthDate"):
            val = existing_kit.get(key)
            if val is not None:
                form[key] = str(val)
        if existing_kit.get("useScope"):
            form["useScope"] = existing_kit["useScope"]
        if existing_kit.get("effectiveScope"):
            form["effectiveScope"] = existing_kit["effectiveScope"]
        if "internalResource" in existing_kit:
            form["internalResource"] = str(existing_kit["internalResource"]).lower()
    return form


def _resolve_page_register_name(apaas_config: dict | None, fallback: str) -> str:
    """Resolve the Vue component tag used by PAGE/MENU custom menus."""
    config = apaas_config or {}
    router = config.get("router")
    if isinstance(router, dict):
        for key in router.keys():
            candidate = str(key or "").strip()
            if candidate.startswith("apaas-custom-"):
                return candidate
        for key in router.keys():
            candidate = str(key or "").strip()
            if candidate:
                return candidate

    return str(fallback or "").strip()


def _upload_resp_is_token_error(r: httpx.Response) -> bool:
    """上传响应是否为 apaas token 失效(HTTP 401 / 响应体 message 含 token 错标记)。

    上传是裸 httpx(不抛异常、靠查 body code), 平台 token 过期可能回 HTTP 401, 也可能 HTTP 200
    但 body `{code != ok, message: "...Unauthorized..."}`。两种都要认出来走重登重试。
    """
    if r.status_code == 401:
        return True
    try:
        body = r.json()
    except Exception:
        return False
    if body.get("code") in ("ok", 200):
        return False
    msg = str(body.get("message") or body.get("msg") or "")
    return is_apaas_token_error(msg)


async def _post_kit_upload(target: str, env, fp: Path, ct: str, form_data: dict) -> httpx.Response:
    """裸上传单个 kit 文件 POST(每次重读 env.token, 便于重登后重试用新 token)。"""
    import time as _t

    async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
        return await http.post(
            target,
            headers={
                "xdaptenantid": env.platform_tenant_id,
                "xdaptoken": env.token,
                "xdaptimestamp": str(int(_t.time() * 1000)),
            },
            files={"file": (fp.name, fp.read_bytes(), ct)},
            data=form_data,
        )


async def _upload_one_kit(target: str, env, fp: Path, ct: str, form_data: dict, db) -> dict:
    """上传单个 kit; 撞 token 失效(401) → `_relogin_apaas_env` 刷新 + 重试一次, 返回解析后的响应 json。

    修复: 上传是 deploy 第一个平台调用, 用的 env.token 可能已过期(`_ensure_env_token` 只在 token
    为空时重登、不验证过期), 且这处裸 httpx 漏了 `call_apaas_with_relogin` 自愈 → 旧 token 直接撞
    Unauthorized。这里镜像 `call_apaas_with_relogin`: 撞 token 错就重登(原地刷新 env.token)再重试一次。
    """
    r = await _post_kit_upload(target, env, fp, ct, form_data)
    if _upload_resp_is_token_error(r) and await _relogin_apaas_env(getattr(env, "id", None), db):
        logger.info("[deploy-to-app] 上传撞 token 失效, 已重登, 重试上传: %s", fp.name)
        r = await _post_kit_upload(target, env, fp, ct, form_data)  # env.token 已被重登原地刷新
    try:
        rj = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"平台上传响应非 JSON (status={r.status_code})")
    if rj.get("code") not in ("ok", 200):
        raise HTTPException(status_code=500, detail=rj.get("message") or rj.get("msg") or "上传失败")
    return rj


async def _build_and_upload_kits(*, ws_mgr, ws_id: str, env, db) -> dict:
    """构建 workspace -> 上传 developmentKit(组件库) -> 用 fileName 反查 kit_id。"""
    import time as _t
    import uuid as _u

    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)

    backend_project_types = {"backend-api", "backend-feign", "backend-scheduled"}

    if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
        packages = [
            {
                "path": path,
                "file_type": ft,
                "description": f"{display_name} - 由 apaas-builder 装回",
                "upload_policy": "update_if_exists",
            }
            for path, ft in await ws_mgr.build_and_package_dual(ws_id)
        ]
    else:
        ft = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
        if not ft:
            raise HTTPException(status_code=400, detail=f"不支持上传的项目类型: {project_type}")
        if project_type in backend_project_types:
            await ws_mgr.build_and_package(ws_id)
            out_dir = ws_mgr._get_build_output_dir(ws_path)
            jars = [j for j in out_dir.glob("*.jar") if not j.name.endswith(".original")]
            if not jars:
                raise HTTPException(status_code=500, detail="未找到编译产物 JAR,请先在 IDE 构建项目")
            runtime_jar = _resolve_backend_runtime_jar(ws_path)
            packages = [
                {
                    "path": str(jars[0]),
                    "file_type": ft,
                    "description": f"{display_name} - 由 apaas-builder 装回",
                    "upload_policy": "update_if_exists",
                },
                {
                    "path": str(runtime_jar),
                    "file_type": ft,
                    "description": f"{runtime_jar.stem} - aPaaS 后端运行时依赖",
                    "upload_policy": "missing_only",
                },
            ]
        else:
            packages = [{
                "path": await ws_mgr.build_and_package(ws_id),
                "file_type": ft,
                "description": f"{display_name} - 由 apaas-builder 装回",
                "upload_policy": "update_if_exists",
            }]

    add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
    update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"
    file_names = [Path(pkg["path"]).name for pkg in packages]
    skipped_existing: list[str] = []

    for pkg in packages:
        fp = Path(pkg["path"])
        ft = str(pkg["file_type"])
        existing = await _query_existing_development_kits(
            env.base_url, env.platform_tenant_id, env.token, fp.name,
        )
        kit = _find_kit_by_filename(existing, fp.name)
        if kit and pkg.get("upload_policy") == "missing_only":
            skipped_existing.append(fp.name)
            logger.info("[deploy-to-app] 运行时依赖已存在,跳过上传: %s", fp.name)
            continue
        form_data = _build_upload_form_data(
            file_type=ft,
            description=str(pkg["description"]),
            version_code=_u.uuid4().hex,
            upload_id=str(int(_t.time() * 1000)),
            existing_kit=kit,
        )
        target = update_url if kit else add_url
        ct = "application/java-archive" if fp.suffix == ".jar" else "application/zip"
        # 撞 token 失效 → 重登刷新 + 重试一次(裸上传此前漏了自愈, 见 _upload_one_kit)
        await _upload_one_kit(target, env, fp, ct, form_data, db)

    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
    kit_ids: list[str] = []
    for fn in file_names:
        kits = await client.query_app_dev_kits("", file_name=fn)
        for kit in kits:
            kit_id = kit.get("id")
            if kit.get("fileName") == fn and kit_id and str(kit_id) not in kit_ids:
                kit_ids.append(str(kit_id))

    try:
        _cfg = ws_mgr._read_apaas_config(ws_path)
        register_name = _resolve_page_register_name(_cfg if isinstance(_cfg, dict) else None, display_name)
    except Exception:
        register_name = display_name

    return {
        "kit_ids": kit_ids,
        "file_type": packages[0]["file_type"],
        "project_type": project_type,
        "display_name": display_name,
        "file_names": file_names,
        "register_name": register_name,
        "skipped_existing_files": skipped_existing,
    }


_PAGE_TYPES = {"menu-page", "form-page", "mobile-page"}


def _find_self_dev_menu(nodes: list[dict] | None, *, menu_name: str, link_url: str) -> dict | None:
    """Find an existing custom page menu by display name first, then linkUrl."""
    target_name = str(menu_name or "").strip()
    target_link = str(link_url or "").strip()

    name_match = None
    link_match = None

    def _walk(items):
        nonlocal name_match, link_match
        for item in items or []:
            if not isinstance(item, dict):
                continue
            current_name = str(item.get("menuName") or item.get("menu_name") or item.get("name") or "").strip()
            current_link = str(item.get("linkUrl") or item.get("link_url") or "").strip()
            current_type = str(item.get("menuType") or item.get("menu_type") or "").strip().upper()
            is_custom = current_type in {"", "CUSTOM"} or bool(current_link.startswith("apaas-custom-"))
            if is_custom and target_name and current_name == target_name and name_match is None:
                name_match = item
            if is_custom and target_link and current_link == target_link and link_match is None:
                link_match = item
            _walk(item.get("submenus") or item.get("children") or [])

    _walk(nodes)
    return name_match or link_match


def _is_duplicate_attach_error(exc: Exception) -> bool:
    message = str(exc)
    return any(marker in message for marker in ("重复", "已存在", "duplicate", "exist"))


async def _attach_dev_kits_tolerant(env_id, db, apaas_app_id: str, kit_ids: list[str]) -> dict:
    try:
        await call_apaas_with_relogin(
            env_id,
            db,
            lambda c: c.attach_apaas_source_relation(apaas_app_id, object_ids=kit_ids),
        )
        return {"attached": [str(i) for i in kit_ids], "skipped_duplicates": []}
    except Exception as exc:
        if not _is_duplicate_attach_error(exc):
            raise

    attached: list[str] = []
    skipped: list[str] = []
    for kit_id in kit_ids:
        try:
            await call_apaas_with_relogin(
                env_id,
                db,
                lambda c, kid=kit_id: c.attach_apaas_source_relation(apaas_app_id, object_ids=[kid]),
            )
            attached.append(str(kit_id))
        except Exception as exc:
            if _is_duplicate_attach_error(exc):
                skipped.append(str(kit_id))
                continue
            raise
    return {"attached": attached, "skipped_duplicates": skipped}


async def _deploy_to_app_impl(ws_id: str, local_app_id, ctx, db) -> dict:
    """装回应用编排:upload -> (bound) enable->attach->页面建菜单->republish."""
    from app.models import PlatformEnv

    ws_mgr = WorkspaceManager()

    if not local_app_id:
        env = (await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )).scalars().first()
        if not env:
            raise HTTPException(status_code=400, detail="租户未配置平台环境")
        env.token = await _ensure_env_token(env, db)
        up = await _build_and_upload_kits(ws_mgr=ws_mgr, ws_id=ws_id, env=env, db=db)
        return {
            "status": "uploaded_only",
            "kits": up["file_names"],
            "hint": "已传到自开发资产库,可在表单设计器引用 / 去 Builder 关联到应用",
        }

    app, env = await _load_app_and_env(local_app_id, ctx, db)
    if not getattr(app, "apaas_app_id", None):
        raise HTTPException(status_code=400, detail="应用尚未部署到平台(无 apaas_app_id),无法装回")
    if env is None:
        raise HTTPException(status_code=400, detail="租户未配置平台环境")
    env.token = await _ensure_env_token(env, db)
    apaas_app_id = str(app.apaas_app_id)

    up = await _build_and_upload_kits(ws_mgr=ws_mgr, ws_id=ws_id, env=env, db=db)
    if not up["kit_ids"]:
        raise HTTPException(status_code=502, detail="上传成功但反查不到 kit id,无法关联到应用")

    env_id = env.id
    await call_apaas_with_relogin(env_id, db, lambda c: c.enable_self_dev_config(apaas_app_id, "ENABLE"))
    attach_result = await _attach_dev_kits_tolerant(env_id, db, apaas_app_id, up["kit_ids"])

    menu = None
    if up["project_type"] in _PAGE_TYPES:
        register = up.get("register_name") or up["display_name"]
        menu_name = up["display_name"]
        menus = await call_apaas_with_relogin(env_id, db, lambda c: c.query_menus(apaas_app_id))
        existing_menu = _find_self_dev_menu(menus, menu_name=menu_name, link_url=register)
        if existing_menu:
            menu_id = str(existing_menu.get("id") or existing_menu.get("menuId") or existing_menu.get("menu_id") or "")
            current_link = str(existing_menu.get("linkUrl") or existing_menu.get("link_url") or "").strip()
            if menu_id and current_link != register:
                await call_apaas_with_relogin(
                    env_id,
                    db,
                    lambda c: c.update_self_dev_menu_link_url(
                        apaas_app_id,
                        menu_id,
                        register,
                        menu_type="CUSTOM",
                        confirmed=True,
                    ),
                )
                menu = {"name": menu_name, "action": "updated", "menu_id": menu_id, "link_url": register}
            else:
                menu = {"name": menu_name, "action": "reused", "menu_id": menu_id, "link_url": register}
        else:
            await call_apaas_with_relogin(
                env_id,
                db,
                lambda c: c.create_self_dev_menu(apaas_app_id, menu_name=menu_name, link_url=register),
            )
            menu = {"name": menu_name, "action": "created", "link_url": register}

    detail = await call_apaas_with_relogin(env_id, db, lambda c: c.query_app_detail(apaas_app_id))
    version = str(detail.get("currentVersion") or detail.get("version") or "1.0.0")
    try:
        await call_apaas_with_relogin(
            env_id,
            db,
            lambda c: c.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发"),
        )
    except Exception as e:
        if "版本" in str(e) or "version" in str(e).lower():
            parts = version.split(".")
            try:
                parts[-1] = str(int(parts[-1]) + 1)
            except (ValueError, IndexError):
                raise
            version = ".".join(parts)
            await call_apaas_with_relogin(
                env_id,
                db,
                lambda c: c.deploy_app(apaas_app_id, version, abstract="自开发装回自动重发"),
            )
        else:
            raise

    await publish_extension_update(app.id, "republish_done", {"kits": up["file_names"]})
    return {
        "status": "installed",
        "app": {"local_app_id": app.id, "name": getattr(app, "name", "")},
        "menu": menu,
        "version": version,
        "kits": up["file_names"],
        "attached_kit_ids": attach_result["attached"],
        "skipped_duplicate_kit_ids": attach_result["skipped_duplicates"],
    }
