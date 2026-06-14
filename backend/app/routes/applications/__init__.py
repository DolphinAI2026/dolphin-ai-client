from __future__ import annotations
import logging
from typing import List

from fastapi import APIRouter
from app.schemas import ApplicationResponse, MergedAppResponse

# 共享 helper 从子模块 re-export（保持 `from app.routes.applications import _xxx` 的向下兼容）
from ._helpers import *  # noqa: F401,F403
from . import _helpers  # noqa: F401

router = APIRouter(prefix="/applications", tags=["应用"])
logger = logging.getLogger(__name__)

# ── 新增子模块挂载 ──────────────────────────────────────────────────────────────
# Phase 4B (2026-06-14): 将 __init__.py 内联路由拆分为三个子模块：
#   crud.py          — 应用 CRUD / 列表 / 详情 / 新建 / 导入 / 更新 / 删除 / 图标
#   lifecycle.py     — 上线 / 环境 / API日志 / 默认模式 / git / chat-session / 部署
#   apaas_menus.py  — apaas 菜单读写 / 应用基本信息编辑
from . import crud as _crud  # noqa: E402

# FastAPI 不允许 include_router 时 prefix="" 且 route.path="" 同时为空，
# 因此将空路径路由（list/create）从 _crud.router 提出，直接在父 router 上注册。
from .crud import list_applications, create_application  # noqa: F401
router.get("", response_model=List[MergedAppResponse])(list_applications)
router.post("", response_model=ApplicationResponse)(create_application)

router.include_router(_crud.router)
from . import lifecycle as _lifecycle  # noqa: E402
router.include_router(_lifecycle.router)
from . import apaas_menus as _apaas_menus  # noqa: E402
router.include_router(_apaas_menus.router)

# ── 既有子模块挂载（保持原顺序不变）─────────────────────────────────────────────
from . import change_plans as _change_plans  # noqa: E402
router.include_router(_change_plans.router)
from . import generate as _generate  # noqa: E402
router.include_router(_generate.router)
from . import docs as _docs  # noqa: E402
router.include_router(_docs.router)
from . import preflight as _preflight  # noqa: E402
router.include_router(_preflight.router)
# 2026-05-24 部署历史 + 回滚 (Agent C cherry-pick)
from . import deploy_history as _deploy_history  # noqa: E402
router.include_router(_deploy_history.router)
# 2026-05-26 PR6 (SPEC v2 §2 Section E0) — 扩展 section 子路由
# 4 endpoint: /dev-kits 轮询 + /extension-update-events SSE +
# /extension-update-notify 内部 hook + /republish 触发 aPaaS 重发
from . import extension as _extension  # noqa: E402
router.include_router(_extension.router)

# PR2b-followup (2026-05-26): SectionNav sub-tab 资源列表 — 7 个 GET endpoint
# 包 list_apaas_app_models / dicts / forms / lists / processes / business-events / roles
from . import section_content as _section_content  # noqa: E402
router.include_router(_section_content.router)

# K4 (2026-05-27): 应用日志 — 4 kind aggregator (deploy / operation / ai / error)
from . import logs_endpoint as _logs_endpoint  # noqa: E402
router.include_router(_logs_endpoint.router)

# U8 (2026-05-27): 设计 tab 内嵌 SPEC chat — 改 spec_sections 草稿 (跟 config-chat
# 区分: 草稿层, 不立即生效, 等用户"确认并生成"). MVP 用 rule-based mock LLM.
from . import spec_chat as _spec_chat  # noqa: E402
router.include_router(_spec_chat.router)
# V3 (2026-05-27): "确认并生成" modal — apply spec_sections 草稿到 apaas.
# /spec/apply-plan + /spec/apply (MVP dry-run, P5 接通 MCP 真调).
from . import spec_apply as _spec_apply  # noqa: E402
router.include_router(_spec_apply.router)

# Y (2026-05-27): SPEC 版本管理 + markdown 缓存.
# /spec/versions + /versions/{id} + /spec/markdown + /spec/export.md
from . import spec_versions as _spec_versions  # noqa: E402
router.include_router(_spec_versions.router)

# Y (2026-05-27): 业务事件 endpoint — SPEC 设计 tab 章九用.
# /business-events 包 list_apaas_business_events MCP.
from . import business_events as _business_events  # noqa: E402
router.include_router(_business_events.router)

# ── 向后兼容 re-export（外部 import 直接从 app.routes.applications 引用）───────
# tests 和 generation_steps.py 直接 `from app.routes.applications import <symbol>`
# 这些符号现在住在子模块里，在此 re-export 保持兼容。

# 来自 crud.py
from .crud import (  # noqa: F401
    _resolve_current_apaas_tenant_id,
    list_applications,
    list_applications_page,
    match_applications_by_name,
    _get_application_permissions,
    _extract_apaas_app_version,
    _bump_patch_version,
    _deploy_apaas_app_with_version_retry,
    _require_application_permission,
    _resolve_apaas_call_context,
    _extract_preview_data,
    _merge_preview_data,
    GenerateAppIconResponse,
    MatchByNameItem,
    AutoCreateRequest,
    AutoCreateResponse,
)

# 来自 lifecycle.py
from .lifecycle import (  # noqa: F401
    PlatformConfigUpdate,
    UpdateAppDefaultModeRequest,
    get_application_default_mode,
    patch_application_default_mode,
    publish_application,
    ensure_application_git_project,
    DeployFromArtifactReq,
    DeployTaskResp,
    DeployStatusResp,
)

# 来自 apaas_menus.py
from .apaas_menus import (  # noqa: F401
    update_apaas_app_info_route,
    _UpdateApaasAppInfoReq,
    _CreateMenuGroupReq,
    _SetMenuParentReq,
    _DeleteMenuReq,
)
