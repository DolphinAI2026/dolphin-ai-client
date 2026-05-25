"""aPaaS 平台内省工具集 — 给 AI Coding (layer 2，二次开发) 用。

这一层做的是「对一个已经在 aPaaS 平台上的应用做自开发」，所以 agent 需要：
- 列应用 / 拿菜单 / 拿表单视图 (tabId) / 拿组件 (uuid 映射)
- 拿模型字段、字典选项
- 部署前查 modelCode / appCode 是否撞名

跟另外两条线的区别：
- 这不是 vibe-coding（layer 3，纯自开发，跟 aPaaS 无关）
- 这不是 ai-chat（layer 1，产文档喂给 ai-builder，不直接打平台 API）

13 个工具：
  list_apaas_apps              列环境下所有应用
  list_apaas_app_menus         应用菜单树（含 form_id / form_code）
  list_apaas_form_views        表单视图（拿 tab_id）
  list_apaas_form_components   表单组件（uuid → label 映射 + 下拉选项）
  list_apaas_app_models        应用下模型 + 字段定义
  list_apaas_app_dicts         应用下字典 + 选项
  get_apaas_app_overview       精简版应用全貌
  list_apaas_models_in_env     环境内所有模型（modelCode 冲突预检）
  check_app_code_conflict      app_code 是否被占用
  get_doc_template_spec        Builder 设计文档官方标准
  validate_builder_doc         校验 md 是否符合 Builder 标准
  read_attachment              读 workspace .attachments/ 下用户上传的文件
  write_artifact               写版本化 markdown 产物到 .artifacts/

执行签名：
    async def execute_xxx(args: dict, platform_env_id: int, db: AsyncSession) -> str
    返回字符串。失败以 "Error:" 前缀（跟 coding/tools.py 的约定一致）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ─────────────────────────── helpers ───────────────────────────

def _ok(payload: dict) -> str:
    """工具成功结果统一序列化（中文不转义、紧凑 JSON）。"""
    return json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2)


def _err(message: str) -> str:
    """错误以 'Error:' 开头 — coding agent 的 ToolResult 包装层靠这个判断 success。"""
    return f"Error: {message}"


async def _get_apaas_client(platform_env_id: int, db: AsyncSession):
    """按 platform_env_id 拿登录态的 APaaSClient。

    依赖 platform_envs 表已配齐 base_url + platform_tenant_id + token。
    """
    from app.models import PlatformEnv
    from app.apaas_client import APaaSClient
    from sqlalchemy import select

    row = await db.execute(select(PlatformEnv).where(PlatformEnv.id == platform_env_id))
    env = row.scalar_one_or_none()
    if env is None:
        raise ValueError(f"platform_env_id={platform_env_id} 不存在")
    if not env.token:
        raise ValueError(
            f"platform_env_id={platform_env_id} 未登录 aPaaS（token 为空），"
            f"先在「平台环境」配置"
        )
    return APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id or "default",
        token=env.token,
    )


# ═══════════════════════════════════════════════════════════════════════════
# A. aPaaS 平台内省 — 11 个只读查询工具
# ═══════════════════════════════════════════════════════════════════════════


async def _list_apaas_apps(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列环境下所有应用（含 app_code / apaas_app_id / app_name）。"""
    try:
        client = await _get_apaas_client(platform_env_id, db)
        apps = await client.query_app_list(page=1, page_size=200)
    except Exception as exc:
        return _err(f"查询 aPaaS 应用列表失败: {exc}")
    result = [
        {
            "apaas_app_id": str(a.get("id") or ""),
            "app_code": str(a.get("appCode") or a.get("code") or ""),
            "app_name": str(a.get("appName") or a.get("name") or ""),
            "status": str(a.get("status") or ""),
        }
        for a in apps if isinstance(a, dict)
    ]
    return _ok({"platform_env_id": platform_env_id, "apps": result, "total": len(result)})


async def _list_apaas_app_menus(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列应用菜单树（含 form_id / form_code，自开发场景从这里拿表单入口）。

    2026-05-25 改: 从 allAppMenu 换 manageAppMenu, 因为前者过滤 GROUP 菜单
    导致 agent 看不到分组 menu_id 没法挂菜单. manageAppMenu 含全菜单 (GROUP +
    用户菜单 + 系统流程菜单), 我们过滤掉系统流程类 (TODO/TO_CHECK/PROC_* 等)
    保留 GROUP + 用户表单菜单.
    """
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    if not apaas_app_id:
        return _err("apaas_app_id 必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        # 用 manageAppMenu — 返完整树 (含 GROUP). 老 allAppMenu 过滤 GROUP, 无法挂菜单.
        menus = await client.query_menus(apaas_app_id)
    except Exception as exc:
        return _err(f"查询菜单失败: {exc}")

    def flatten(nodes, parent_path="", parent_id="", depth=0, out=None):
        """递归扁平化 apaas 平台菜单树。

        2026-05-14 修：apaas 平台 GET /menu/query/allAppMenu 实际返回的嵌套字段
        是 `submenus`（看真实 response：GROUP 节点下的子菜单挂在 submenus 数组
        里，深度最多 3 层 — GROUP → GROUP → MENU/MODEL/REPORT）。
        老版本只看 `children` 永远拿不到子菜单，导致 agent 看到顶层全是 GROUP
        且 form_id 全空，误判「菜单权限不可见」。
        """
        if out is None:
            out = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            name = str(n.get("menuName") or n.get("name") or "")
            path = f"{parent_path}/{name}" if parent_path else name
            # apaas 真实嵌套字段是 submenus；其他几个作 fallback 兼容
            children = (n.get("submenus") or n.get("children")
                        or n.get("subMenus") or n.get("menuList") or [])
            menu_id = str(n.get("id") or n.get("menuId") or "")
            out.append({
                "menu_id": menu_id,
                "menu_name": name,
                "path": path,
                "depth": depth,
                "parent_id": parent_id,
                "menu_type": str(n.get("menuType") or ""),
                "menu_model_type": str(n.get("menuModelType") or ""),
                "form_id": str(n.get("formId") or ""),
                "form_code": str(n.get("formCode") or ""),
                "datasource_id": str(n.get("datasourceId") or ""),
                "has_children": bool(children),
                "menu_order": n.get("menuOrder", 0),
                "is_effective": bool(n.get("isEffective", True)),
            })
            if children:
                flatten(children, path, menu_id, depth + 1, out)
        return out

    flat = flatten(menus)
    # 过滤掉平台自动注入的系统流程菜单 (TODO/TO_CHECK/MY_SUBMIT/MY_PARTICIPATE/
    # TODO_MANAGE/PROC_AUTH/PROC_FORWARD) — 用户配置事件 / 挂菜单时不需要这些.
    # 保留 GROUP 类型 — agent 挂菜单到分组下需要 group menu_id.
    _SYSTEM_AUTO_TYPES = {
        "TODO", "TO_CHECK", "MY_SUBMIT", "MY_PARTICIPATE",
        "TODO_MANAGE", "PROC_AUTH", "PROC_FORWARD",
    }
    flat = [m for m in flat if (m.get("menu_type") or "").upper() not in _SYSTEM_AUTO_TYPES]
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "menus": flat,
        "total": len(flat),
    })


async def _list_apaas_form_views(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列表单的所有视图（拿 tab_id，listPageBusinessData 的前置必调）。"""
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    form_id = (args.get("form_id") or "").strip()
    if not apaas_app_id or not form_id:
        return _err("apaas_app_id + form_id 都必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        raw = await client.query_form_views(apaas_app_id, form_id)
    except Exception as exc:
        return _err(f"查询视图失败: {exc}")
    views = [
        {
            "tab_id": str(v.get("tabId") or v.get("id") or ""),
            "tab_name": str(v.get("tabName") or v.get("name") or v.get("viewName") or v.get("title") or ""),
        }
        for v in (raw or []) if isinstance(v, dict)
    ]
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "form_id": form_id,
        "views": views,
        "default_tab_id": views[0]["tab_id"] if views else None,
        "total": len(views),
    })


async def _list_apaas_form_components(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列表单组件（uuid → label 映射 + 下拉选项）。

    listPageBusinessData 返回行数据 key 是 component uuid（不是字段名）
    所以前端 vue 写表头 / 渲染下拉时必须用本接口的映射。
    """
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    form_id = (args.get("form_id") or "").strip()
    if not apaas_app_id or not form_id:
        return _err("apaas_app_id + form_id 都必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        raw = await client.query_form_components(apaas_app_id, form_id)
    except Exception as exc:
        return _err(f"查询组件失败: {exc}")
    comps = []
    for c in (raw or []):
        if not isinstance(c, dict):
            continue
        choose = c.get("chooseOptions") or []
        dict_opts = c.get("dictionaryChooseOptions") or []
        comps.append({
            "uuid": str(c.get("uuid") or ""),
            "label": str(c.get("label") or c.get("name") or ""),
            "component_type": str(c.get("componentType") or ""),
            "bo_code": str(c.get("boCode") or ""),
            "required": bool(c.get("required", False)),
            "choose_options": [
                {"id": str(o.get("id") or ""), "label": str(o.get("label") or "")}
                for o in choose if isinstance(o, dict)
            ],
            "dictionary_choose_options": [
                {"code": str(o.get("valueCode") or o.get("code") or ""),
                 "name": str(o.get("valueName") or o.get("name") or o.get("label") or "")}
                for o in dict_opts if isinstance(o, dict)
            ],
        })
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "form_id": form_id,
        "components": comps,
        "total": len(comps),
    })


async def _list_apaas_app_models(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列应用下所有数据模型 + 每个模型的字段（modelCode / dataType / boCode）。"""
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    with_fields = bool(args.get("with_fields", True))
    if not apaas_app_id:
        return _err("apaas_app_id 必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        models = await client.query_models(apaas_app_id)
        out = []
        for m in (models or []):
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            entry = {
                "model_id": mid,
                "model_code": str(m.get("modelCode") or m.get("code") or ""),
                "model_name": str(m.get("modelName") or m.get("name") or ""),
            }
            if with_fields and mid:
                try:
                    fields = await client.query_model_fields(apaas_app_id, mid)
                    entry["fields"] = [
                        {
                            "field_code": str(f.get("fieldCode") or f.get("boCode") or ""),
                            "field_name": str(f.get("fieldName") or f.get("name") or ""),
                            "data_type": str(f.get("dataType") or ""),
                            "required": bool(f.get("required", False)),
                        }
                        for f in (fields or []) if isinstance(f, dict)
                    ]
                except Exception:
                    entry["fields"] = []
            out.append(entry)
    except Exception as exc:
        return _err(f"查询模型失败: {exc}")
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "models": out,
        "total": len(out),
    })


async def _list_apaas_app_dicts(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列应用下所有数据字典（下拉选项的来源）。"""
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    with_options = bool(args.get("with_options", True))
    if not apaas_app_id:
        return _err("apaas_app_id 必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        dicts = await client.query_dicts(apaas_app_id)
        out = []
        for d in (dicts or []):
            if not isinstance(d, dict):
                continue
            did = str(d.get("id") or "")
            entry = {
                "dict_id": did,
                "dict_code": str(d.get("dictCode") or d.get("code") or ""),
                "dict_name": str(d.get("dictName") or d.get("name") or ""),
            }
            if with_options and did:
                try:
                    opts = await client.query_dict_options(apaas_app_id, did)
                    entry["options"] = [
                        {"code": str(o.get("valueCode") or o.get("code") or ""),
                         "name": str(o.get("valueName") or o.get("name") or "")}
                        for o in (opts or []) if isinstance(o, dict)
                    ]
                except Exception:
                    entry["options"] = []
            out.append(entry)
    except Exception as exc:
        return _err(f"查询字典失败: {exc}")
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "dicts": out,
        "total": len(out),
    })


async def _get_apaas_app_overview(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """精简版应用全貌（模型清单 + 字典清单，不带字段/选项）。"""
    apaas_app_id = (args.get("apaas_app_id") or "").strip()
    if not apaas_app_id:
        return _err("apaas_app_id 必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        models = await client.query_models(apaas_app_id)
        dicts = await client.query_dicts(apaas_app_id)
    except Exception as exc:
        return _err(f"查询失败: {exc}")
    return _ok({
        "platform_env_id": platform_env_id,
        "apaas_app_id": apaas_app_id,
        "models": [
            {"model_code": str(m.get("modelCode") or ""),
             "model_name": str(m.get("modelName") or m.get("name") or "")}
            for m in (models or []) if isinstance(m, dict)
        ],
        "dicts": [
            {"dict_code": str(d.get("dictCode") or ""),
             "dict_name": str(d.get("dictName") or d.get("name") or "")}
            for d in (dicts or []) if isinstance(d, dict)
        ],
        "models_total": len(models or []),
        "dicts_total": len(dicts or []),
    })


async def _list_apaas_models_in_env(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """列环境内所有模型（含 modelCode）——给"创建新模型不撞名"用。"""
    try:
        client = await _get_apaas_client(platform_env_id, db)
        rows = await client.query_all_model_codes()
    except Exception as exc:
        return _err(f"查询失败: {exc}")
    return _ok({
        "platform_env_id": platform_env_id,
        "models": [
            {"model_code": str(r.get("modelCode") or r.get("code") or ""),
             "app_code": str(r.get("appCode") or "")}
            for r in (rows or []) if isinstance(r, dict)
        ],
        "total": len(rows or []),
    })


async def _check_app_code_conflict(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """查 app_code 是否被占用（部署前预检）。"""
    app_code = (args.get("app_code") or "").strip()
    if not app_code:
        return _err("app_code 必填")
    try:
        client = await _get_apaas_client(platform_env_id, db)
        apps = await client.query_app_list(page=1, page_size=200)
    except Exception as exc:
        return _err(f"查询失败: {exc}")
    hits = [
        {"apaas_app_id": str(a.get("id") or ""),
         "app_name": str(a.get("appName") or a.get("name") or "")}
        for a in (apps or [])
        if isinstance(a, dict) and (a.get("appCode") or a.get("code")) == app_code
    ]
    return _ok({
        "platform_env_id": platform_env_id,
        "app_code": app_code,
        "conflict": bool(hits),
        "occupants": hits,
    })


_DOC_TEMPLATE_SPEC = {
    "version": "v0.2",
    "required_sections": [
        "应用元数据", "角色定义", "数据字典", "数据模型",
        "表单与流程", "权限矩阵", "页面与导航",
    ],
    "naming_rules": {
        "model_code": "lower_snake_case, 8~40 chars, [a-z][a-z0-9_]*",
        "field_code": "lower_snake_case, 不可用 application_id / approver_id 等保留字",
        "app_code": "lower_kebab-case 或 lower_snake_case",
    },
    "model_table_headers": [
        "字段名称", "字段编码", "类型", "必填", "字典编码", "默认值",
        "约束", "校验规则", "说明",
    ],
    "tips": [
        "模型字段编码不允许平台保留字段（application_id / approver_id / approval_* 等）",
        "字典编码必须显式声明在「数据字典」章节，引用处仅写编码",
        "权限矩阵用列：角色 × 模型/表单 × 操作（CRUD + 自定义 action）",
    ],
}


async def _get_doc_template_spec(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """拿 Builder 设计文档官方标准（章节 / 表头 / 命名规则）。"""
    return _ok(_DOC_TEMPLATE_SPEC)


async def _validate_builder_doc(args: dict, platform_env_id: int, db: AsyncSession) -> str:
    """轻量校验 markdown 是否符合 Builder 标准（不创建应用、不打远端）。"""
    md = args.get("md_content") or ""
    if not md.strip():
        return _err("md_content 不能为空")
    missing = []
    for section in _DOC_TEMPLATE_SPEC["required_sections"]:
        if section not in md:
            missing.append(section)
    reserved_hits = []
    for token in re.findall(r"\b(application_id|approver_id|approval_[a-z_]+)\b", md):
        reserved_hits.append(token)
    return _ok({
        "valid": (not missing and not reserved_hits),
        "missing_sections": missing,
        "reserved_field_hits": list(set(reserved_hits)),
        "spec_version": _DOC_TEMPLATE_SPEC["version"],
    })


# ═══════════════════════════════════════════════════════════════════════════
# B. workspace 产物 / 附件 — 2 个工具
#
# 注意：AI Coding 也跑在 workspace 里（routes/coding.py 那条线），workspace_path
# 由 _resolve_workspace_path(ctx) 给出，跟 vibe-coding 的 workspace 不同源。
# 这两个工具拿到 workspace_path 后只用 .artifacts/ 和 .attachments/ 子目录。
# ═══════════════════════════════════════════════════════════════════════════


async def _read_attachment(args: dict, workspace_path) -> str:
    """读 workspace 下 .attachments/ 里的用户上传文件（PDF/Excel/Word/markdown 等）。"""
    from pathlib import Path
    filename = (args.get("filename") or "").strip()
    if not filename or "/" in filename or "\\" in filename:
        return _err("filename 必填且不允许包含 / \\")
    ws = Path(workspace_path) if not isinstance(workspace_path, Path) else workspace_path
    attach = ws / ".attachments"
    attach.mkdir(parents=True, exist_ok=True)
    target = attach / filename
    if not target.exists():
        existing = sorted(p.name for p in attach.iterdir() if p.is_file())
        return _err(
            f"附件 '{filename}' 不存在。已有附件: {existing}"
        )
    suffix = target.suffix.lower()
    text_exts = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".log"}
    if suffix in text_exts:
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_text(encoding="gbk", errors="ignore")
        truncated = len(content) > 50000
        return _ok({
            "filename": filename,
            "size_bytes": target.stat().st_size,
            "content": content[:50000],
            "truncated": truncated,
        })
    return _ok({
        "filename": filename,
        "size_bytes": target.stat().st_size,
        "suffix": suffix,
        "is_text": False,
        "hint": f"二进制文件，请用 run_command 'python xxx_parser.py .attachments/{filename}' 解析",
    })


async def _write_artifact(args: dict, workspace_path) -> str:
    """写一份版本化 markdown 产物到 workspace/.artifacts/。

    版本号自动从已有的 spec_v{N}.md 推算。
    """
    from pathlib import Path
    base = (args.get("filename_base") or "spec").strip()
    content = args.get("content") or ""
    replace_latest = bool(args.get("replace_latest", False))
    if not re.match(r"^[a-zA-Z0-9_\-]+$", base):
        return _err("filename_base 只能含 字母/数字/_/-")
    if not content.strip():
        return _err("content 不能为空")

    ws = Path(workspace_path) if not isinstance(workspace_path, Path) else workspace_path
    arts = ws / ".artifacts"
    arts.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(rf"^{re.escape(base)}_v(\d+)\.md$")
    existing = []
    for p in arts.iterdir():
        if p.is_file():
            m = pattern.match(p.name)
            if m:
                existing.append((int(m.group(1)), p))
    existing.sort()

    if replace_latest and existing:
        target = existing[-1][1]
        version = existing[-1][0]
    else:
        version = (existing[-1][0] if existing else 0) + 1
        target = arts / f"{base}_v{version}.md"

    target.write_text(content, encoding="utf-8")
    return _ok({
        "filename": target.name,
        "version": version,
        "bytes_written": len(content.encode("utf-8")),
        "preview_path": f".artifacts/{target.name}",
    })


# ═══════════════════════════════════════════════════════════════════════════
# 导出：APAAS_TOOL_DEFINITIONS + APAAS_TOOL_EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════


APAAS_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_apaas_apps",
            "description": (
                "列 aPaaS 环境下所有应用（含 app_code / apaas_app_id / app_name）。"
                "做应用二次开发的入口工具 — 先调它定位你要二开的应用。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_app_menus",
            "description": (
                "列应用的菜单树（含每个菜单的 form_id / form_code）。从这里拿到表单入口 ID，"
                "下一步用 list_apaas_form_views 拿 tab_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "apaas_app_id": {"type": "string", "description": "应用 ID（从 list_apaas_apps 拿）"},
                },
                "required": ["apaas_app_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_form_views",
            "description": (
                "列表单的视图（拿 tab_id）。listPageBusinessData 接口必须传 tab_id，"
                "一个表单常有多个视图（全部/我的/待办）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "apaas_app_id": {"type": "string"},
                    "form_id": {"type": "string", "description": "表单 ID（从 list_apaas_app_menus 拿）"},
                },
                "required": ["apaas_app_id", "form_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_form_components",
            "description": (
                "列表单组件（uuid → label 映射 + 下拉选项）。listPageBusinessData 返回行数据的 key 是 uuid，"
                "写 vue 表头/下拉时必须用本接口的映射。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "apaas_app_id": {"type": "string"},
                    "form_id": {"type": "string"},
                },
                "required": ["apaas_app_id", "form_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_app_models",
            "description": (
                "列应用下所有数据模型 + 每个模型的字段定义（modelCode / dataType / boCode）。"
                "with_fields=false 时只列模型骨架不展开字段，省 token。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "apaas_app_id": {"type": "string"},
                    "with_fields": {"type": "boolean", "default": True},
                },
                "required": ["apaas_app_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_app_dicts",
            "description": "列应用下所有数据字典（下拉/单选选项的来源）。with_options=false 时只列字典骨架。",
            "parameters": {
                "type": "object",
                "properties": {
                    "apaas_app_id": {"type": "string"},
                    "with_options": {"type": "boolean", "default": True},
                },
                "required": ["apaas_app_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_apaas_app_overview",
            "description": "精简版应用全貌（模型 + 字典清单不带字段/选项）— 快速知道应用「有什么」，再决定深挖。",
            "parameters": {
                "type": "object",
                "properties": {"apaas_app_id": {"type": "string"}},
                "required": ["apaas_app_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apaas_models_in_env",
            "description": "列环境内所有模型（含 modelCode 跨应用）— 创建新模型前查重避免撞名。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_app_code_conflict",
            "description": "查 app_code 是否被占用（部署前预检）。",
            "parameters": {
                "type": "object",
                "properties": {"app_code": {"type": "string"}},
                "required": ["app_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_doc_template_spec",
            "description": "拿 Builder 设计文档官方标准（章节 / 表头 / 命名规则 / 字段类型）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_builder_doc",
            "description": "校验 markdown 是否符合 Builder 标准。返回 missing_sections + reserved_field_hits。",
            "parameters": {
                "type": "object",
                "properties": {"md_content": {"type": "string"}},
                "required": ["md_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_attachment",
            "description": "读 workspace .attachments/ 下用户上传的文件（PDF/Excel/Word/markdown 等）。",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_artifact",
            "description": (
                "写版本化 markdown 产物到 workspace/.artifacts/{base}_v{N}.md。"
                "版本号自动递增（replace_latest=true 时覆盖最新版不升号）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename_base": {"type": "string", "default": "spec"},
                    "content": {"type": "string"},
                    "replace_latest": {"type": "boolean", "default": False},
                },
                "required": ["content"],
            },
        },
    },
]


# 工具分两类：
#   - aPaaS 平台查询类（11 个）：(args, platform_env_id, db) -> str
#   - workspace 产物 / 附件类（2 个）：(args, workspace_path) -> str
APAAS_TOOL_EXECUTORS_PLATFORM: dict[str, Any] = {
    "list_apaas_apps": _list_apaas_apps,
    "list_apaas_app_menus": _list_apaas_app_menus,
    "list_apaas_form_views": _list_apaas_form_views,
    "list_apaas_form_components": _list_apaas_form_components,
    "list_apaas_app_models": _list_apaas_app_models,
    "list_apaas_app_dicts": _list_apaas_app_dicts,
    "get_apaas_app_overview": _get_apaas_app_overview,
    "list_apaas_models_in_env": _list_apaas_models_in_env,
    "check_app_code_conflict": _check_app_code_conflict,
    "get_doc_template_spec": _get_doc_template_spec,
    "validate_builder_doc": _validate_builder_doc,
}

APAAS_TOOL_EXECUTORS_WORKSPACE: dict[str, Any] = {
    "read_attachment": _read_attachment,
    "write_artifact": _write_artifact,
}

# 所有 apaas 工具名 — 给 build_coding_tools 分流用
APAAS_TOOL_NAMES = set(APAAS_TOOL_EXECUTORS_PLATFORM) | set(APAAS_TOOL_EXECUTORS_WORKSPACE)
