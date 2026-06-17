"""MCP tools for AI Builder application lifecycle and design-doc handoff."""
from __future__ import annotations

import json
import logging
import time as _time
import uuid as _uuid

from app.config import settings

logger = logging.getLogger(__name__)


class _StaticToolMarker:
    """No-op decorator used so static registry tests can see tool functions."""

    def tool(self):
        def _decorate(fn):
            return fn

        return _decorate


mcp = _StaticToolMarker()

_resolve_identity = None
_resolve_app_id = None
_build_app_view_url = None
_api_call = None
_api_call_sse_collect = None
_call_apaas_platform_tool = None

# ─────────────────────── 工具实现 ───────────────────────


@mcp.tool()
async def parse_design_doc(
    md_content: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """解析一份标准 markdown 设计文档，返回结构化 preview（不创建应用）。

    用法：用户提交 md 后先用这个工具检查解析结果是否符合预期，再决定是否创建应用。

    md_content 必须是 aPaaS Builder 标准 6 章节格式：
        一、应用信息 / 二、角色列表 / 三、数据字典 / 四、数据模型 / 五、表单定义 / 六、权限矩阵

    返回：{ appName, appCode, roles[], dicts[], models[], forms[], permissions[] }
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    res = await _api_call("POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files)
    data = res.get("data") if isinstance(res, dict) else None
    return {
        "ok": True,
        "preview": data or res,
        "document_text_length": len(md_content),
    }


@mcp.tool()
async def list_platform_envs(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前租户配置的所有低代码平台环境。

    用法（agent 工作流）：只在需要选择或诊断平台环境时调用。
    普通“查看现有应用 / 查询当前租户应用列表”不要调用本工具，直接用 list_my_applications。
    当前租户通常已经绑定默认环境；generate_app_from_doc / export_apaas_app_design_doc
    可以在 env_id=0 或不传 env_id 时走默认环境。

    返回示例：
        {
          "envs": [
            {
              "id": 1,
              "name": "trial 环境",
              "base_url": "https://your-apaas.example.com/backend",
              "is_default": true,
              "status": "connected",   # connected | disconnected | unknown
            },
            ...
          ],
          "default_env_id": 1,
          "connected_count": 1,
        }

    Agent 选择策略：
    - connected_count == 0 → 报错给用户："你还没配置可用的低代码平台环境，
      请先去 BuilderDevOps 添加，或检查现有环境登录状态。"
    - connected_count == 1 且唯一 connected 环境 is_default → 后续工具直接用默认环境，不需要再让用户确认
    - connected_count > 1 → 列给用户让其选择，等用户回复后用对应 env_id
      调 generate_app_from_doc(env_id=X)
    """
    tid, _uid = _resolve_identity(tenant_id, user_id)

    # 直接 db 查（绕开 /api/platform-envs 的 require_tenant_admin —— MCP service
    # token 已经验证 tenant_id，且 list 是只读操作，不需要 admin 权限）
    from app.database import AsyncSessionLocal
    from app.models import PlatformEnv
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PlatformEnv)
            .where(PlatformEnv.tenant_id == tid)
            .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
        )
        envs = result.scalars().all()

    items = [
        {
            "id": e.id,
            "name": e.env_name,
            "base_url": e.base_url,
            "is_default": bool(e.is_default),
            "status": e.status,
        }
        for e in envs
    ]
    default_id = next((e["id"] for e in items if e["is_default"]), None)
    connected_count = sum(1 for e in items if e["status"] == "connected")
    return {
        "ok": True,
        "envs": items,
        "default_env_id": default_id,
        "connected_count": connected_count,
    }


@mcp.tool()
async def generate_app_from_doc(
    artifact_id: int,
    app_name: str | None = None,
    env_id: int = 0,
    create_mode: str = "reuse",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """根据标准 markdown 设计文档创建 Builder 本地应用草稿。

    注意：本工具只完成 parse → auto-create，返回本地 app_id / draft 状态；
    它不会在 aPaaS 平台完整创建模型、表单、菜单或权限。要让应用真正可用，
    后续必须继续调用部署/生成工具（例如 deploy_application / generate-run 链路）。
    md 必须是标准 6 章节格式（参考 parse_design_doc 文档）。

    **2026-05-24 强制 artifact_id 模式** (省 token, 跟 validate/submit 一致 commit 6ba63aa):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 创建.
    - 工作流: write_artifact (返 id) → generate_app_from_doc(artifact_id=id)
    - 漏传 → MISSING_ARTIFACT_ID; id 错 → ARTIFACT_NOT_FOUND

    参数：
    - artifact_id：write_artifact 返的 id, backend 从 ai_chat_artifacts 表读 md content
    - app_name：可选；不填会从 md 「一、应用信息」推断
    - env_id：部署到哪个 PlatformEnv。**强烈建议先调 list_platform_envs
      让用户确认**。0 表示用租户默认环境（fallback：找一个 connected 环境）。
    - create_mode：reuse(默认)=同 app_code 复用；new=同编码已存在时自动加后缀新建。

    返回 { app_id, app_name, app_code, status="draft", app_view_url, env: {id, name} }。
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    md_content = await _load_artifact_content(artifact_id)
    if not md_content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }

    tid, uid = _resolve_identity(tenant_id, user_id)

    # 1) 解析
    files = {"file": ("doc.md", md_content.encode("utf-8"), "text/markdown")}
    parse_res = await _api_call(
        "POST", "/applications/upload-doc", tenant_id=tid, user_id=uid, files=files
    )
    preview = parse_res.get("data") if isinstance(parse_res, dict) else None
    if not isinstance(preview, dict):
        raise RuntimeError(f"文档解析返回结构异常：{parse_res!r:.300s}")

    final_app_name = (app_name or preview.get("appName") or "").strip() or "未命名应用"

    # 2) auto-create
    create_body: dict = {"app_name": final_app_name, "config_preview": {"data": preview}}
    if env_id and env_id > 0:
        create_body["platform_env_id"] = int(env_id)
    if (create_mode or "").strip().lower() in {"new", "create_new", "force_new"}:
        create_body["create_mode"] = "new"
    create_res = await _api_call(
        "POST",
        "/applications/auto-create",
        tenant_id=tid,
        user_id=uid,
        json_body=create_body,
    )
    app_id = create_res.get("app_id")
    return {
        "ok": True,
        "app_id": app_id,
        "app_name": create_res.get("app_name"),
        "app_code": create_res.get("app_code"),
        "is_new": create_res.get("is_new"),
        "status": "draft",
        "next_action": "继续部署/生成到 aPaaS 后，模型、表单、菜单和权限才会真正创建。",
        "platform_env_id": create_res.get("platform_env_id"),
        "platform_env_name": create_res.get("platform_env_name"),
        "app_view_url": _build_app_view_url(app_id),
    }


@mcp.tool()
async def list_my_applications(
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列出当前租户下的应用列表。

    2026-06-02 用户决策：「查应用列表」统一查 aPaaS 平台全量（与 AI Coding 的
    list_apaas_apps 一致，避免 Builder 只显示本地纳管的子集、两边数字对不上）。
    解析租户默认 platform env → 查 apaas；无 env / apaas 失败时降级为 ai-builder 本地纳管应用。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)

    # 1) 优先查 aPaaS 平台全量（解析租户默认 env，与 list_platform_envs 同口径）
    env_id = None
    try:
        from app.database import AsyncSessionLocal
        from app.models import PlatformEnv
        from sqlalchemy import select

        async with AsyncSessionLocal() as _db:
            _r = await _db.execute(
                select(PlatformEnv)
                .where(PlatformEnv.tenant_id == tid)
                .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
            )
            _env = _r.scalars().first()
        env_id = _env.id if _env else None
    except Exception:
        env_id = None

    if env_id:
        apaas_res = await _call_apaas_platform_tool("list_apaas_apps", {}, env_id)
        if isinstance(apaas_res, dict) and apaas_res.get("ok"):
            apaas_apps = apaas_res.get("apps") or apaas_res.get("applications") or []
            apps = [
                {
                    "apaas_app_id": a.get("apaas_app_id") or a.get("app_id") or a.get("id"),
                    "app_name": a.get("app_name"),
                    "app_code": a.get("app_code"),
                    "status": a.get("status"),
                }
                for a in apaas_apps
            ]
            return {"ok": True, "applications": apps, "total": len(apps), "source": "apaas"}

    # 2) 降级：ai-builder 本地纳管应用（无 apaas env 的租户仍可用）
    res = await _api_call(
        "GET",
        "/applications/page",
        tenant_id=tid,
        user_id=uid,
        params={"page": 1, "size": 50},
    )
    items = (res or {}).get("items") or []
    apps = [
        {
            "id": it.get("id"),
            "app_name": it.get("app_name"),
            "app_code": it.get("app_code"),
            "status": it.get("status"),
            "current_doc_version": it.get("current_doc_version"),
            "updated_at": it.get("updated_at"),
        }
        for it in items
    ]
    return {"ok": True, "applications": apps, "total": (res or {}).get("total", len(apps)), "source": "local"}


@mcp.tool()
async def get_application(
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """查看指定应用的完整详情，**包括当前 SPEC 的 markdown 文档**（含所有字段、表单、权限）。

    app_id 可省略（=0）：自动用 ai-builder 中用户当前编辑的应用。

    返回的 spec_markdown 是当前应用的完整结构化设计文档（6 章节标准格式：
    应用信息/角色/数据字典/数据模型/表单/权限）。基于它你可以直接做增量改动
    （加字段/改字段/删字段），不用再问用户'有哪些字段'。

    spec_markdown_source 标识来源：
    - 'doc_version': 用户上传过设计文档，直接用最新版
    - 'config_preview_rendered': 应用没设计文档但有 SPEC 配置，从 config 反向渲染
    - 'empty': 真空白草稿，需要从零写文档
    - 'omitted_during_generation': **应用正在生成中**，整篇文档不完整且会被反复轮询，
      故此期间不返回（待 status='completed' 后再 get_application 读取）

    ⚠️ 应用生成中（status=generating/in_progress）时**不返回** spec_markdown，
    轮询期间只看 status / generation_progress 即可。其它状态照常返回完整文档。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    # 拉应用 meta
    meta = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
    status_val = (meta or {}).get("status")
    # 拉 spec markdown（容错）。
    # 上下文爆炸根因修复：应用生成中（generating/in_progress）时这份文档是
    # 不完整/瞬态的，且 agent 会按 hint 反复轮询 get_application，每次都把整篇 6 章节
    # 文档（截到 2 万字符）堆进上下文，6+ 次几乎一模一样 → 最终 400 context_too_large。
    # 故生成中**不拉取也不返回** spec_markdown，只看 status/generation_progress。
    _is_generating = status_val in ("generating", "in_progress")
    spec_md = ""
    spec_source = "omitted_during_generation" if _is_generating else "unknown"
    spec_version = None
    if not _is_generating:
        try:
            spec = await _api_call("GET", f"/applications/{app_id}/spec-markdown", tenant_id=tid, user_id=uid)
            spec_md = (spec or {}).get("markdown") or ""
            spec_source = (spec or {}).get("source") or "unknown"
            spec_version = (spec or {}).get("version")
        except Exception as exc:
            logger.warning("get_application spec-markdown 拉取失败: %s", exc)
    # 生成进度。若 SPEC 声明了 workflows，即便 status=completed 也拉一次步骤状态，
    # 让 agent 能看到审批流程 2/2，而不是只汇报角色/字典/模型/表单。
    gen_progress = None

    def _has_workflows() -> bool:
        config = (meta or {}).get("config_preview") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except Exception:  # noqa: BLE001
                config = {}
        if not isinstance(config, dict):
            return False
        data = config.get("data", config)
        return bool((data or {}).get("workflows"))

    if status_val in ("generating", "in_progress", "draft") or _has_workflows():
        try:
            st = await _api_call("GET", f"/applications/{app_id}/steps/status", tenant_id=tid, user_id=uid)
            steps = (st or {}).get("steps") or []

            def _cnt(prefix: str) -> str:
                tot = [s for s in steps if str(s.get("key", "")).startswith(prefix)]
                done = [s for s in tot if s.get("status") == "completed"]
                return f"{len(done)}/{len(tot)}"

            done_all = sum(1 for s in steps if s.get("status") == "completed")
            app_status = (st or {}).get("app_status") or status_val
            gen_progress = {
                "app_status": app_status,
                "steps": f"{done_all}/{len(steps)}",
                "roles": _cnt("create_role:"),
                "dicts": _cnt("create_dict:"),
                "models": _cnt("create_model:"),
                "forms": _cnt("create_form:"),
                "workflows": _cnt("create_workflow:"),
                "complete": bool(steps) and done_all == len(steps),
                "hint": (
                    "status 还是 generating/in_progress → 后台还在生成, 别 publish、别说已完成, 继续轮询直到 status='completed'。"
                    "应用生成中完整设计文档(spec_markdown)不返回, 待 status='completed' 后再 get_application 读取; "
                    "轮询期间只看 status / generation_progress 即可。"
                    if app_status in ("generating", "in_progress", "draft")
                    else "status 已完成；steps 为平台真实资源核对结果。"
                ),
            }
        except Exception as exc:
            logger.warning("get_application 取生成进度失败 app_id=%s: %s", app_id, exc)
    return {
        "ok": True,
        "app_id": (meta or {}).get("id"),
        "app_name": (meta or {}).get("app_name"),
        "app_code": (meta or {}).get("app_code"),
        "status": status_val,
        "generation_progress": gen_progress,
        "current_doc_version": (meta or {}).get("current_doc_version"),
        "platform_env_id": (meta or {}).get("platform_env_id"),
        "apaas_app_id": (meta or {}).get("apaas_app_id"),
        "app_view_url": _build_app_view_url(app_id),
        "spec_markdown": spec_md,
        "spec_markdown_source": spec_source,
        "spec_markdown_version": spec_version,
    }


async def _normalize_md_via_llm(target_md: str, current_spec_md: str) -> str:
    """LLM 兜底：外部 agent 给的 md 若不符合严格 6 章节模板，
    用 LLM 基于 current_spec_md（已知规范）+ target_md（agent 改动后）
    生成规范化的新版 md。

    避免每次都 LLM 调用 — 调用方仅在 strict parse 失败时才用此兜底。
    """
    from app.llm_client import LLMClient
    llm = LLMClient()
    prompt = f"""你是 ai-builder 设计文档规范化助手，输出严格符合 6 章节模板的 markdown。

## 输入
- CURRENT：当前应用规范的 markdown（标准 6 章节，作为格式模板）
- TARGET：AI 助手生成的新版 md（含用户改动，但格式可能错乱）

## 任务
**先 diff 出 TARGET 相对 CURRENT 的实质改动（新增/修改/删除字段、表单、权限等）**，
然后基于 CURRENT 的格式：
1. 完整保留 CURRENT 所有内容
2. **应用 diff 出的所有改动**（必须保住 TARGET 中比 CURRENT 多/改/少的字段）
3. 章节顺序、标题、表格列名 = CURRENT 格式
4. 输出完整的新版 markdown

## ⚠️ 关键原则（违反会导致用户改动丢失）
- **不要丢失** TARGET 中比 CURRENT 多出来的字段、表单、权限行
- 用户最常见的改动是"加一个字段"，diff 出来 TARGET 比 CURRENT 多一行 → 必须**新版里保留这行**
- 不能因为 TARGET 格式乱就把改动一起丢掉
- 如果不确定改动是什么，宁可多保留 TARGET 内容，也不要丢

只输出规范化后的 markdown 全文。不要解释。不要 ```markdown``` 包裹。

=== CURRENT ===
{current_spec_md}

=== TARGET ===
{target_md}

=== 规范化新版 markdown ==="""
    res = await llm.chat_completion(
        [{"role": "user", "content": prompt}],
        max_tokens=12000,
        temperature=0.0,
    )
    msg = (res.get("choices") or [{}])[0].get("message") or {}
    out = (msg.get("content") or "").strip()
    # 去掉可能的 code fence
    if out.startswith("```"):
        lines = out.split("\n")
        out = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return out.strip() or target_md  # LLM 没出东西就用原始 md


@mcp.tool()
async def update_app_from_doc(
    md_content: str,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """上传新版 markdown 设计文档作为应用 vN+1 版，自动 diff 出待确认的变更计划。

    app_id 可省略（=0）：自动用 ai-builder 中用户当前编辑的应用。
    md_content 不严格符合模板时（章节/表格列差异），后端会自动 LLM 规范化重试一次。

    重要：本工具只生成待确认 change plan，不执行变更计划。返回后必须把 actions
    逐条列给用户确认；用户明确同意后，才能调用 execute_change_plan。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)

    async def _attempt_upload(md: str) -> dict:
        files = {"file": (f"app-{app_id}-doc.md", md.encode("utf-8"), "text/markdown")}
        return await _api_call_sse_collect(
            "POST",
            f"/applications/{app_id}/upload-doc-version",
            tenant_id=tid, user_id=uid, files=files,
        )

    sse = await _attempt_upload(md_content)
    # strict parse 失败 → 拉 current spec_md 用 LLM 规范化重试一次
    if sse["errors"]:
        first_err = str(sse["errors"][-1])
        if "未按模板规范" in first_err or "DocNotStandardError" in first_err or "解析失败" in first_err:
            logger.info("严格解析失败，启用 LLM 规范化兜底重试")
            try:
                spec = await _api_call("GET", f"/applications/{app_id}/spec-markdown", tenant_id=tid, user_id=uid)
                current_md = (spec or {}).get("markdown") or ""
                if current_md:
                    normalized = await _normalize_md_via_llm(md_content, current_md)
                    if normalized and normalized != md_content:
                        sse = await _attempt_upload(normalized)
            except Exception as exc:
                logger.warning("LLM 规范化兜底失败: %s", exc)

    if sse["errors"]:
        raise RuntimeError(f"上传新版 md 失败：{sse['errors'][-1]}")
    done = sse.get("done") or {}
    change_plan_id = done.get("change_plan_id")
    change_plan = None
    actions_preview = []
    if change_plan_id:
        try:
            change_plan = await _api_call(
                "GET",
                f"/applications/{app_id}/change-plans/{change_plan_id}",
                tenant_id=tid,
                user_id=uid,
            )
            raw_actions = change_plan.get("actions") or []
            if isinstance(raw_actions, list):
                actions_preview = [
                    {
                        "id": action.get("id"),
                        "selected": action.get("selected", True),
                        "op": action.get("op"),
                        "description": action.get("description") or action.get("op") or "",
                    }
                    for action in raw_actions
                    if isinstance(action, dict)
                ]
        except Exception as exc:
            logger.warning("读取 change plan 详情失败: %s", exc)
    return {
        "ok": True,
        "app_id": app_id,
        "version": done.get("version") or done.get("to_version"),
        "change_plan_id": change_plan_id,
        "summary": done.get("summary") or done.get("change_summary"),
        "requires_user_confirmation": True,
        "assistant_next_step": (
            "请把 actions_preview 里的变更逐条列给用户确认。不要说已经完成更新；"
            "不要调用 execute_change_plan，除非用户明确回复确认执行。"
        ),
        "actions_preview": actions_preview,
        "change_plan": change_plan,
        "raw_done": done,
    }


@mcp.tool()
async def get_change_plan(
    plan_id: int,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """查看变更计划详情：包含所有 actions（新增/修改/删除的角色、字典、模型、表单、权限）。

    app_id 可省略（=0）：自动用当前编辑应用。
    用户决策"是否执行"前应该读这个 plan。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    res = await _api_call(
        "GET", f"/applications/{app_id}/change-plans/{plan_id}", tenant_id=tid, user_id=uid
    )
    return {"ok": True, "plan": res}


@mcp.tool()
async def execute_change_plan(
    plan_id: int,
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """执行变更计划：把 plan 里所有 actions 落到底层（创建/修改/删除模型、表单、权限等）。

    app_id 可省略（=0）：自动用当前编辑应用。
    这是真正"动手"的工具，调用前请确认用户已经审过 change plan。
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    sse = await _api_call_sse_collect(
        "POST",
        f"/applications/{app_id}/change-plans/{plan_id}/execute",
        tenant_id=tid,
        user_id=uid,
    )
    if sse["errors"]:
        return {"ok": False, "errors": sse["errors"], "events": sse["events"][-10:]}
    return {
        "ok": True,
        "app_id": app_id,
        "plan_id": plan_id,
        "summary": (sse.get("done") or {}).get("summary"),
        "executed_count": len([e for e in sse["events"] if e["event"] in ("step", "step_done")]),
    }


@mcp.tool()
async def publish_application(
    app_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把应用上线：同步当前配置到底层 aPaaS 平台，让真实用户可访问。

    app_id 可省略（=0）：自动用当前编辑应用。

    ⚠️ 前置：应用必须 status='completed'。deploy 起的后台生成(模型/表单/权限)没跑完时
    (status='generating'/'in_progress')，本工具会被后端硬门拒(error_code=STILL_GENERATING)；
    这时**别**跟用户说"已上线/已完成"，继续用 get_application 轮询 status 到 'completed' 再调本工具。"""
    tid, uid = _resolve_identity(tenant_id, user_id)
    app_id, _ = _resolve_app_id(app_id, uid)
    try:
        res = await _api_call("POST", f"/applications/{app_id}/publish", tenant_id=tid, user_id=uid)
    except RuntimeError as exc:
        msg = str(exc)
        if "(409)" in msg or "还在生成中" in msg:
            return {
                "ok": False,
                "error_code": "STILL_GENERATING",
                "app_id": app_id,
                "message": ("应用还在后台生成中(模型/表单/权限尚未全部就绪)，不能上线。"
                            "用 get_application 轮询 status 到 'completed' 再 publish；这期间别跟用户说已上线。"),
            }
        return {"ok": False, "error_code": "PUBLISH_FAILED", "app_id": app_id, "message": msg[:500]}
    return {"ok": True, "app_id": app_id, "result": res}


async def _load_artifact_content(artifact_id: int) -> str | None:
    """从 ai_chat_artifacts 表读 content. 找不到返 None.

    2026-05-21 新增 — 让 validate_builder_doc / submit_design_doc 支持 artifact_id
    引用模式. LLM write_artifact 拿到 id 后, 后续工具传 id 不重写 5000+ 字 md
    节省 token (每次省 ~5000 token + 30-60s LLM 生成时间).
    """
    if not artifact_id or artifact_id <= 0:
        return None
    try:
        from app.database import AsyncSessionLocal
        from app.models import AIChatArtifact
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(AIChatArtifact.content).where(AIChatArtifact.id == artifact_id)
            )
            row = res.first()
            return row[0] if row else None
    except Exception as exc:
        logger.warning("_load_artifact_content(%s) failed: %s", artifact_id, exc)
        return None


def _do_validate_builder_doc(md_content: str) -> dict:
    """validate_builder_doc 的纯函数实现（无 IO，可单独单测）。"""
    from app.doc_standard_detector import detect
    from app.doc_pipeline import _strip_template_scaffolding

    if not md_content or not md_content.strip():
        return {
            "ok": False,
            "score": 0,
            "level": "freeform",
            "decision": "rewrite_first",
            "passes_strict": False,
            "missing_sections": ["应用信息", "角色列表", "数据模型", "权限定义"],
            "weak_sections": [],
            "signals": {},
            "advice": ["md_content 是空的，先把六章节模板写出来再校验。"],
        }

    cleaned = _strip_template_scaffolding(md_content)
    result = detect(cleaned)
    score = int(result.get("score") or 0)
    missing = result.get("missing_sections") or []
    weak = result.get("weak_sections") or []
    signals = result.get("signals") or {}

    advice: list[str] = []
    if missing:
        advice.append(
            f"缺失必填章节：{', '.join(missing)}。补齐 ## 标题 + 标准表格。"
        )
    for section in weak:
        advice.append(
            f"「{section}」表头不达标：核对该章节表头与 6 章模板（"
            "应用信息=应用编码/应用名称、角色=角色编码/角色名称、字典选项=选项编码/选项名称、"
            "模型/表单=字段编码/字段名称、权限=表单名称/角色编码/可查看/可编辑/可删除/数据范围）。"
        )
    if (signals.get("code_compliance") or 1.0) < 0.9:
        advice.append(
            "编码字段不规范：appCode / 角色编码 / 字段编码 必须英文小写 + 下划线"
            "（首字符字母，其余 [a-zA-Z0-9_-]）。检查所有'编码'列。"
        )
    if (signals.get("ref_integrity") or 1.0) < 0.9:
        advice.append("引用不闭合：字典编码 / 关联模型编码 必须在文档内已声明。检查模型字段引用。")
    if (signals.get("header_format") or 1.0) < 0.9:
        advice.append("章节标题格式：用 ## 一、应用信息 / ## 二、角色列表 ... 的中文数字编号。")
    # 阈值与后端 docs.py:1054 保持一致：>= 90 通过，< 90 后端会 400 拒收
    passes = score >= 90 and not missing
    if passes and score >= 95:
        advice.append("✅ 标准（≥95），可直接调 generate_app_from_doc / update_app_from_doc。")
    elif passes:
        advice.append(
            f"✅ 通过门槛（{score}/100，≥90 后端可解析）；如想更稳，按上面建议小修后重跑可冲到 95+。"
        )
    elif score >= 80:
        advice.append(
            f"未达标（{score}/100，门槛 90）：按上面建议修 1-2 处后重跑 validate_builder_doc。"
        )
    else:
        advice.append(
            f"严重偏离模板（{score}/100，门槛 90）：建议先按 STANDARD_DOC_FORMAT 把六章节骨架补齐再校验。"
        )

    return {
        "ok": True,
        "score": score,
        "level": result.get("level"),
        "decision": result.get("decision"),
        "passes_strict": passes,
        "missing_sections": missing,
        "weak_sections": weak,
        "signals": signals,
        "advice": advice,
    }


@mcp.tool()
async def validate_builder_doc(artifact_id: int) -> dict:
    """校验一份 markdown 设计文档是否符合 aPaaS Builder 标准（不创建应用、不需要身份）。

    **2026-05-23 强制 artifact_id 模式** (省 token, 消除 LLM 重写 5000+ 字 md 浪费):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 校验.
    - 工作流: write_artifact (返 id) → validate_builder_doc(artifact_id=id)
    - 撞 MISSING_ARTIFACT_ID → 说明 agent 漏调 write_artifact, 先写文档拿 id 再校验
    - 撞 ARTIFACT_NOT_FOUND → id 错或 artifact 已被删, 重新 write_artifact 拿新 id

    建议工作流：
      1. 写完 md → write_artifact → 拿 artifact_id
      2. validate_builder_doc(artifact_id=N)
      3. passes_strict=False → 按 missing_sections / weak_sections / signals / advice 自我修补
      4. 重新 write_artifact (同名 filename 自动 version++) 拿新 id → 重 validate
      5. 重复至多 3 轮; 仍不通过把问题原文列给用户决定
      6. passes_strict=True 才把 md 文档输出给用户（或直接 generate_app_from_doc）

    返回：
        {
          "ok": True,
          "score": 0-100,                   # 综合分
          "level": "standard|partial|freeform",
          "decision": "pure_code|hybrid_fallback|rewrite_first",
          "passes_strict": bool,
          "missing_sections": [str],
          "weak_sections": [str],
          "signals": { "section_coverage": ..., "header_format": ..., ... },
          "advice": [str],
        }
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    content = await _load_artifact_content(artifact_id)
    if not content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }
    result = _do_validate_builder_doc(content)

    # 2026-05-28 修"假通过": _do_validate_builder_doc 只跑轻量 detect() (看 6 章标题/表头格式),
    # 一份只有标题没有真表格的**摘要**能骗过它 (score≥90) → passes_strict=True; 但 generate_app_from_doc
    # 用的是 parse_document (真把表格解析成结构), 摘要会炸 "forms/models/permissions 无法解析"。
    # 校验器必须跟消费方(generate)一致: 这里跑一遍真 parser 做一致性校验, 过不了就如实标不通过,
    # 不让假通过文档流到 generate (实测 329K 字大文档被 LLM 摘要后就撞这个坑)。
    try:
        from app.doc_pipeline import parse_document
        preview = await parse_document(content)
        pdata = preview.get("data", preview) if isinstance(preview, dict) else {}
        n_models = len(pdata.get("models") or [])
        n_forms = len(pdata.get("forms") or [])
        n_perms = len(pdata.get("permissions") or [])
        result["parse_check"] = {"ok": True, "models": n_models, "forms": n_forms, "permissions": n_perms}
        if n_models == 0 and n_forms == 0:
            result["passes_strict"] = False
            result["advice"] = [
                "❌ 真解析校验未过：parse_document 解析出 0 模型 / 0 表单 —— 章节标题在、但表格内容缺失或不可解析。"
                "最常见原因：把完整设计文档**摘要/缩写**成了说明文字 (尤其大文档塞不进 artifact 时)。"
                "修法：把**完整的 6 章表格原文**写进文档；大文档别让 LLM 重写, 直接在 Builder 工作台上传 .md。",
                *result.get("advice", []),
            ]
    except Exception as exc:  # noqa: BLE001 — parse_document 抛 DocNotStandardError 等 = generate 也必炸
        result["parse_check"] = {"ok": False, "error": str(exc)[:300]}
        result["passes_strict"] = False
        result["advice"] = [
            f"❌ 真解析校验未过：parse_document 抛错 —— {str(exc)[:200]}。"
            "validate 之前只看标题格式才误判通过; 这里跑了 generate 实际用的解析器, 它过不了 = generate 也会过不了。"
            "请补齐可解析的 6 章表格原文 (或在 Builder 工作台直接上传完整 .md, 别经 LLM 摘要)。",
            *result.get("advice", []),
        ]
    return result


# ─────────────────────── 需求分析助手 → ai-builder 设计文档中转 ───────────────────────
#
# 设计目标：让需求分析助手（外部 agent 81）写完标准 md 后，把文档内容传到 ai-builder
# 后端 cache，前端 RequirementsAssistantPage 的右侧 ArtifactPanel 轮询 cache 拉到展示，
# 并提供「→ Builder」一键跳到 /chat 走应用建立流程。
#
# 用户身份反查：MCP 客户端自定义 Body 字段会注入 user_id（trial 阶段都是 1，但前面的
# _resolve_identity 已经支持从 current_app 反查真实 ai-builder 用户）。我们用反查得到
# 的 (tenant_id, user_id) 作为 cache key，避免多用户互相覆盖。
#
# Cache 是进程内的（单实例 trial 够用，生产换 redis）。

# user_id → {pending_id, file_name, md_content, score, submitted_at, source}
_REQUIREMENTS_DOC_CACHE: dict[int, dict] = {}


def _peek_requirements_doc(user_id: int) -> dict | None:
    """前端 GET /requirements/latest-doc 的内部实现 — 返回某用户最新提交的设计文档（不删除）。"""
    rec = _REQUIREMENTS_DOC_CACHE.get(int(user_id))
    if not rec:
        return None
    return dict(rec)


def _consume_requirements_doc(user_id: int, pending_id: str) -> dict | None:
    """点 → Builder 之后调一次拿走。pending_id 校验避免老缓存被误用（用户多次写文档时）。"""
    rec = _REQUIREMENTS_DOC_CACHE.get(int(user_id))
    if not rec or rec.get("pending_id") != pending_id:
        return None
    return _REQUIREMENTS_DOC_CACHE.pop(int(user_id), None)


@mcp.tool()
async def submit_design_doc(
    artifact_id: int,
    file_name: str = "design-doc.md",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把当前 md 设计文档推送到 ai-builder cache，并返回一条 deeplink — agent 必须把这条
    deeplink 贴到 chat 里让用户点击，**这是把 md 送到 Builder 的唯一推荐路径**。

    **2026-05-23 强制 artifact_id 模式** (省 token, 消除 LLM 重写 5000+ 字 md 浪费):
    - 之前 `md_content` 参数已删除. 必须先 write_artifact 拿 id, 再用 id 提交.
    - 工作流: write_artifact (返 id) → validate_builder_doc(artifact_id=id) →
      submit_design_doc(artifact_id=id)

    用法：
      1. 写完 md → write_artifact 拿 id → validate_builder_doc(artifact_id=id) 自检
         (passes_strict=true)
      2. **调本工具** submit_design_doc(artifact_id=id) — 把内容写入 ai-builder 用户 cache
      3. **把返回值里的 deeplink 用 markdown 链接格式贴在 chat 回复里**，例如：
         「✅ 已生成 sales-design.md（自检 95/100），[点这里在 Builder 中搭建](deeplink)」

    返回：
        {
            "ok": True,
            "pending_id": "...",         # 30 分钟内有效
            "expires_in_seconds": 1800,
            "score": 95,
            "deeplink": "https://ai-builder.../chat?from=requirements",
            "ui_hint": "请把 deeplink 用 markdown 链接格式贴给用户，让他点击进 Builder。"
        }

    pending_id 30 分钟后自动失效；用户修改 md 重新 write_artifact (拿新 id) 调本工具时会
    覆盖之前的 cache. deeplink 不带 pending_id —— ai-builder 端按当前登录用户从 cache
    读最新 md，避免跨用户串号。
    """
    if not artifact_id or artifact_id <= 0:
        return {
            "ok": False,
            "error_code": "MISSING_ARTIFACT_ID",
            "error": "artifact_id 必填. 请先 write_artifact 拿 id 再调本工具 (省 token).",
        }
    md_content = await _load_artifact_content(artifact_id)
    if not md_content:
        return {
            "ok": False,
            "error_code": "ARTIFACT_NOT_FOUND",
            "error": f"找不到 artifact_id={artifact_id} - 请重新 write_artifact 拿新 id.",
        }

    tid, uid = _resolve_identity(tenant_id, user_id)
    pending_id = _uuid.uuid4().hex[:16]
    score = (_do_validate_builder_doc(md_content) or {}).get("score", 0)
    rec = {
        "pending_id": pending_id,
        "file_name": (file_name or "design-doc.md").strip() or "design-doc.md",
        "md_content": md_content,
        "score": score,
        "submitted_at": _time.time(),
        "source": "agent-requirements-agent",
        "tenant_id": tid,
    }
    _REQUIREMENTS_DOC_CACHE[uid] = rec
    logger.info(
        "submit_design_doc: cached for user %s (tenant %s), file=%s, %d chars, score=%d",
        uid, tid, rec["file_name"], len(md_content), score,
    )

    # 生成 deeplink — base 留空时 deeplink 为空字符串，agent 应在 chat 里直接贴 md 文件名
    # 引导用户去 ai-builder 菜单「AI 需求分析」自己拉，但这是退化路径。生产环境务必配置。
    base = (settings.ai_builder_chat_deeplink_base or "").rstrip("/")
    deeplink = f"{base}/chat?from=requirements" if base else ""

    return {
        "ok": True,
        "pending_id": pending_id,
        "expires_in_seconds": 1800,
        "score": score,
        "deeplink": deeplink,
        "ui_hint": (
            "请把 deeplink 用 markdown 链接格式贴给用户："
            f"[点这里在 Builder 中搭建]({deeplink})。用户点了会在新 tab 进 Builder 页，"
            "自动从 cache 拿到这份 md，弹窗让他选「新建应用」或「更新现有应用」。"
        ) if deeplink else (
            "ai-builder 未配置 deeplink base —— 请告诉用户去 ai-builder 菜单「AI 需求分析」"
            "页面，刷新一下 Builder 跳转面板会自动出现这份 md。"
        ),
    }


def register(
    mcp,
    resolve_identity,
    api_call,
    api_call_sse_collect,
    resolve_app_id,
    build_app_view_url,
    call_apaas_platform_tool,
):
    global _resolve_identity, _api_call, _api_call_sse_collect, _resolve_app_id
    global _build_app_view_url, _call_apaas_platform_tool
    _resolve_identity = resolve_identity
    _api_call = api_call
    _api_call_sse_collect = api_call_sse_collect
    _resolve_app_id = resolve_app_id
    _build_app_view_url = build_app_view_url
    _call_apaas_platform_tool = call_apaas_platform_tool
    tools = [
        parse_design_doc,
        list_platform_envs,
        generate_app_from_doc,
        list_my_applications,
        get_application,
        update_app_from_doc,
        get_change_plan,
        execute_change_plan,
        publish_application,
        validate_builder_doc,
        submit_design_doc,
    ]
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
