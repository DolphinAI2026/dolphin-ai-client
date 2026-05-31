# backend/app/routes/agents_config.py
"""V2 Agent Config CRUD — /api/agents.

`GET /api/agents` returns the 3 real agents (builder / coding / vibe) with
their actual system prompts read from the agent modules. DB overrides are
applied if present (admin edited prompt/model via PUT).
`PUT /api/agents/{agent_id}` updates model / system_prompt (persisted in
agent_configs table; row is auto-created on first write).

Router prefix here is `/agents` — `app.include_router(..., prefix="/api")` in
main.py adds the `/api` segment.

NOTE (2026-05-19): Skill/MCP binding endpoints removed. The bound skill list
is conceptually wrong as a DB-editable artifact: each agent's real tools are
hardcoded in `builder_spec/tools.py` / `coding/tools.py` and the MCP tools
are the unified 80-tool registry. The Skills/MCP rows on the page are now
read-only.

NOTE (2026-05-19 fix): Old impl returned empty because seed was disabled.
We now return the 3 real agents straight from module-level prompt constants
(builder_spec.agent / coding.prompts / vibe_coding.prompts), with DB
overrides preferred when present. No more lazy seed indirection.
"""
from __future__ import annotations
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.agent_config import (
    AgentConfig, AgentSkill, AgentMcpBinding, AgentKnowledgeBinding,
)

# Real agent prompts — read-only here, defined in their respective modules.
from app.builder_spec.agent import SPEC_DRAFTING_PROMPT as _BUILDER_PROMPT
from app.coding.prompts import AGENT_SYSTEM_PROMPT as _CODING_PROMPT
from app.vibe_coding.prompts import SYSTEM_PROMPT as _VIBE_PROMPT

router = APIRouter(prefix="/agents", tags=["agents-v2"])


# ---------------------------------------------------------------------------
# Default agent registry — 3 real agents wired to actual module prompts.
# Frontend AgentsPage.vue defaults selectedId='builder' and treats id==='whale'
# specially for one helper string; we use canonical id='coding' per task spec,
# which makes the helper fall through to the generic label (harmless).
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "Claude Haiku 4.5"
_FALLBACK_MODEL_OPTIONS = ["Claude Haiku 4.5", "Qwen-Max", "MiniMax abab6"]

DEFAULT_AGENTS: list[dict] = [
    {
        "agent_id": "builder",
        "name": "睿鲸 AI Builder",
        "role": "业务搭建",
        "desc": "从对话出发，把零碎需求整理成标准 SPEC 设计文档，并驱动 aPaaS 平台生成应用。",
        "tone": "ai",
        "icon": "chat",
        "system_prompt": _BUILDER_PROMPT,
        "skills": [
            {"code": "spec-draft", "name": "SPEC 草案", "desc": "把对话整理为标准设计文档"},
            {"code": "apaas-deploy", "name": "应用部署", "desc": "调用 aPaaS API 生成模型 / 表单 / 流程"},
            {"code": "apaas-update", "name": "应用更新", "desc": "对已部署应用做增量改动"},
            {"code": "requirements-elicit", "name": "需求挖掘", "desc": "多轮追问 + 角色 / 边界澄清"},
        ],
        "mcps": ["apaas-mcp"],  # unified 80-tool MCP server
        "knowledge": {
            "industry_packs": ["pkg-mfg", "pkg-crm"],
            "spec_templates": ["std_design_doc"],
        },
    },
    {
        "agent_id": "coding",
        "name": "睿鲸 AI Coding",
        "role": "低代码组件生成",
        "desc": "把组件需求翻译为符合 aPaaS 规范的 Vue 组件，并发布到组件市场。",
        "tone": "brand",
        "icon": "whale",
        "system_prompt": _CODING_PROMPT,
        "skills": [
            {"code": "form-component", "name": "表单组件生成", "desc": "按 Element UI 2.x 规范生成表单组件"},
            {"code": "form-page", "name": "页面生成", "desc": "生成 form-page 整页组件"},
            {"code": "backend-api", "name": "后端接口生成", "desc": "生成 aPaaS 后端 OpenAPI 接口"},
            {"code": "umd-build", "name": "UMD 打包", "desc": "编译为可挂载到平台的 UMD bundle"},
        ],
        "mcps": ["apaas-mcp"],
        "knowledge": {"industry_packs": [], "spec_templates": []},
    },
    {
        "agent_id": "vibe",
        "name": "Vibe Coding",
        "role": "全代码工作区助手",
        "desc": "code-server 内置 Chat 扩展，对话式全代码 agent (Claude Code / Codex 同类)。",
        "tone": "emerald",
        "icon": "code",
        "system_prompt": _VIBE_PROMPT,
        "skills": [
            {"code": "project-search", "name": "项目检索", "desc": "ripgrep + 语义搜索"},
            {"code": "multi-edit", "name": "多文件编辑", "desc": "并行修改多个文件 + diff 预览"},
            {"code": "terminal-exec", "name": "终端执行", "desc": "运行 npm / git / 测试命令"},
            {"code": "git-aware", "name": "Git 上下文", "desc": "理解 branch / commit / 未提交变更"},
        ],
        "mcps": ["apaas-mcp"],
        "knowledge": {"industry_packs": [], "spec_templates": []},
    },
]


def _default_for(agent_id: str) -> Optional[dict]:
    for entry in DEFAULT_AGENTS:
        if entry["agent_id"] == agent_id:
            return entry
    return None


class SkillItem(BaseModel):
    code: str
    name: str
    desc: str


class AgentKnowledge(BaseModel):
    industry_packs: list[str]
    spec_templates: list[str]


class AgentConfigResp(BaseModel):
    id: str
    name: str
    role: str
    desc: str
    tone: str
    icon: str
    model: str
    model_options: list[str]
    system_prompt: str
    context_window: int
    max_output: int
    active_calls: int
    today_calls: int
    skills: list[SkillItem]
    mcps: list[str]
    knowledge: AgentKnowledge


class AgentListResp(BaseModel):
    agents: list[AgentConfigResp]


class AgentUpdateReq(BaseModel):
    model: Optional[str] = None
    system_prompt: Optional[str] = None


def _resp_from_default(entry: dict, db_row: Optional[AgentConfig] = None) -> AgentConfigResp:
    """Build an AgentConfigResp from the DEFAULT_AGENTS entry, overlaying any
    DB-stored model / system_prompt overrides from db_row when present."""
    model = (db_row.model if db_row and db_row.model else DEFAULT_MODEL)
    system_prompt = (
        db_row.system_prompt
        if db_row and db_row.system_prompt
        else entry["system_prompt"]
    )
    model_options = (
        db_row.model_options
        if db_row and db_row.model_options
        else _FALLBACK_MODEL_OPTIONS
    )
    return AgentConfigResp(
        id=entry["agent_id"],
        name=entry["name"],
        role=entry["role"],
        desc=entry["desc"],
        tone=entry["tone"],
        icon=entry["icon"],
        model=model,
        model_options=list(model_options),
        system_prompt=system_prompt,
        context_window=(db_row.context_window if db_row else 200000),
        max_output=(db_row.max_output if db_row else 8192),
        active_calls=(db_row.active_calls if db_row else 0),
        today_calls=(db_row.today_calls if db_row else 0),
        skills=[SkillItem(**s) for s in entry["skills"]],
        mcps=list(entry["mcps"]),
        knowledge=AgentKnowledge(
            industry_packs=list(entry["knowledge"]["industry_packs"]),
            spec_templates=list(entry["knowledge"]["spec_templates"]),
        ),
    )


@router.get("", response_model=AgentListResp)
async def list_agents(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the 3 real agents (builder / coding / vibe) with their actual
    system prompts. DB rows (created on first PUT) override model + prompt."""
    rows = (await db.execute(
        select(AgentConfig).where(AgentConfig.tenant_id == ctx.tenant_id)
    )).scalars().all()
    by_id = {r.agent_id: r for r in rows}

    out: list[AgentConfigResp] = []
    for entry in DEFAULT_AGENTS:
        out.append(_resp_from_default(entry, by_id.get(entry["agent_id"])))
    return AgentListResp(agents=out)


@router.put("/{agent_id}", response_model=AgentConfigResp)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update model and/or system_prompt for a tenant's agent. Upserts the
    agent_configs row on first write (lazy materialization)."""
    entry = _default_for(agent_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"agent {agent_id} not found (must be one of: "
            + ", ".join(e["agent_id"] for e in DEFAULT_AGENTS) + ")",
        )

    cfg = (await db.execute(
        select(AgentConfig).where(
            AgentConfig.tenant_id == ctx.tenant_id,
            AgentConfig.agent_id == agent_id,
        )
    )).scalar_one_or_none()

    if cfg is None:
        # Lazy upsert: create row with defaults so update has somewhere to land.
        cfg = AgentConfig(
            tenant_id=ctx.tenant_id,
            agent_id=agent_id,
            name=entry["name"],
            role=entry["role"],
            desc=entry["desc"],
            tone=entry["tone"],
            icon=entry["icon"],
            model=DEFAULT_MODEL,
            model_options=list(_FALLBACK_MODEL_OPTIONS),
            system_prompt=entry["system_prompt"],
        )
        db.add(cfg)

    if payload.model is not None:
        cfg.model = payload.model
    if payload.system_prompt is not None:
        cfg.system_prompt = payload.system_prompt
    await db.commit()
    await db.refresh(cfg)

    return _resp_from_default(entry, cfg)
