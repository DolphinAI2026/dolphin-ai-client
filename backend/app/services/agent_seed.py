# backend/app/services/agent_seed.py
"""Seed the 3 default agents (Builder / Coding / Vibe) for a tenant.

Called lazily from `/api/agents` GET endpoint when no row exists for the
current tenant. Idempotent: only inserts if no row exists for
(tenant_id, agent_id).
"""
from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_config import (
    AgentConfig, AgentSkill, AgentMcpBinding, AgentKnowledgeBinding,
)

logger = logging.getLogger(__name__)


# Seed data taken verbatim from frontend/src/views/v2/AgentsPage.vue inline seeds
SEED = [
    {
        "agent_id": "builder",
        "name": "睿鲸 AI Builder",
        "role": "业务搭建",
        "desc": "从对话出发，把零碎需求整理成标准 SPEC 设计文档，并驱动 aPaaS 平台生成应用。",
        "tone": "ai",
        "icon": "chat",
        "model": "Claude Haiku 4.5",
        "model_options": ["Claude Haiku 4.5", "Qwen-Max", "MiniMax abab6"],
        "system_prompt": "你是得帆云 aPaaS Builder 的业务搭建助手，目标是把用户的业务需求转化为标准设计文档（SPEC），同时驱动 aPaaS API 生成对应的模型、表单、流程、权限。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("apaas-app-builder", "应用搭建", "把 SPEC 翻译为 aPaaS YAML 配置 + 调用执行引擎"),
            ("apaas-app-updater", "应用增量更新", "对已部署应用做增量改动 + diff"),
            ("apaas-api-reference", "API 参考", "查询 aPaaS API 文档"),
            ("std-design-doc", "标准设计文档", "按章节模板生成 / 校验设计文档"),
            ("requirements-elicit", "需求挖掘", "多轮追问 + 角色 / 边界澄清"),
        ],
        "mcps": ["mcp-1", "mcp-3", "mcp-8"],
        "knowledge": [
            ("industry_pack", "pkg-mfg"),
            ("industry_pack", "pkg-crm"),
            ("spec_template", "std_design_doc"),
            ("spec_template", "mfg_design_doc"),
            ("spec_template", "crm_design_doc"),
        ],
    },
    {
        "agent_id": "whale",
        "name": "睿鲸 AI Coding",
        "role": "低代码组件生成",
        "desc": "把组件需求翻译为符合 aPaaS 规范的 Vue 组件，并发布到组件市场。",
        "tone": "brand",
        "icon": "whale",
        "model": "Claude Haiku 4.5",
        "model_options": ["Claude Haiku 4.5", "Qwen-Coder", "DeepSeek Coder"],
        "system_prompt": "你是得帆云 aPaaS 的组件生成助手，目标是生成符合平台规范的 Vue 自开发组件（表单组件 / 页面 / 列表视图 / 后端接口），并打包为 UMD。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("form-component", "表单组件生成", "按 Element UI 2.x 规范生成表单组件"),
            ("form-page", "页面生成", "生成 form-page 整页组件"),
            ("backend-api", "后端接口生成", "生成 aPaaS 后端 OpenAPI 接口"),
            ("umd-build", "UMD 打包", "编译为可挂载到平台的 UMD bundle"),
        ],
        "mcps": ["mcp-1", "mcp-2"],
        "knowledge": [],
    },
    {
        "agent_id": "vibe",
        "name": "Vibe Coding",
        "role": "全代码工作区助手",
        "desc": "code-server 内置 Chat 扩展，帮你直接编辑 / 重构本项目代码。Cursor 风格。",
        "tone": "emerald",
        "icon": "code",
        "model": "MiniMax abab6",
        "model_options": ["Claude Haiku 4.5", "Qwen-Coder", "MiniMax abab6"],
        "system_prompt": "你是嵌入 code-server 工作区里的代码助手，可以读写工程文件、执行命令、查看 git 状态。优先用项目内已有模式。",
        "context_window": 200000,
        "max_output": 8192,
        "skills": [
            ("project-search", "项目检索", "ripgrep + 语义搜索"),
            ("multi-edit", "多文件编辑", "并行修改多个文件 + diff 预览"),
            ("terminal-exec", "终端执行", "运行 npm / git / 测试命令"),
            ("git-aware", "Git 上下文", "理解 branch / commit / 未提交变更"),
        ],
        "mcps": ["mcp-2", "mcp-6"],
        "knowledge": [],
    },
]


async def seed_agents_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    """DISABLED 2026-05-19 — user requested clean slate to build real Skills/MCP接入.

    To re-enable, remove the early return below. SEED dict below is kept as a
    reference for the original 3-agent structure (Builder / Coding / Vibe).
    """
    return  # no-op; lazy seed disabled
    existing = (await db.execute(  # type: ignore[unreachable]
        select(AgentConfig).where(AgentConfig.tenant_id == tenant_id)
    )).scalars().all()
    existing_ids = {a.agent_id for a in existing}

    for entry in SEED:
        if entry["agent_id"] in existing_ids:
            continue
        cfg = AgentConfig(
            tenant_id=tenant_id,
            agent_id=entry["agent_id"],
            name=entry["name"],
            role=entry["role"],
            desc=entry["desc"],
            tone=entry["tone"],
            icon=entry["icon"],
            model=entry["model"],
            model_options=entry["model_options"],
            system_prompt=entry["system_prompt"],
            context_window=entry["context_window"],
            max_output=entry["max_output"],
        )
        db.add(cfg)
        await db.flush()  # need cfg.id

        for i, (code, name, desc) in enumerate(entry["skills"]):
            db.add(AgentSkill(agent_config_id=cfg.id, code=code, name=name, desc=desc, order_idx=i))
        for i, mcp_id in enumerate(entry["mcps"]):
            db.add(AgentMcpBinding(agent_config_id=cfg.id, mcp_id=mcp_id, order_idx=i))
        for i, (kind, ref_id) in enumerate(entry["knowledge"]):
            db.add(AgentKnowledgeBinding(agent_config_id=cfg.id, kind=kind, ref_id=ref_id, order_idx=i))

    await db.commit()
    logger.info(f"seeded agents for tenant {tenant_id}")
