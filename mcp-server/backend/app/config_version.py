"""配置版本管理

提供配置快照保存、版本历史查询和回滚能力。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ConfigSnapshot

logger = logging.getLogger(__name__)


async def save_config_snapshot(
    db: AsyncSession,
    app_id: int,
    config: Dict[str, Any],
    source: str = "chat",
    summary: str = "",
) -> ConfigSnapshot:
    """保存一份配置快照。

    每次 config_preview 发生变化时都应调用此函数。
    自动递增 version 号。
    """
    # 获取当前最大版本号
    result = await db.execute(
        select(func.max(ConfigSnapshot.version)).where(
            ConfigSnapshot.application_id == app_id
        )
    )
    max_version = result.scalar() or 0

    snapshot = ConfigSnapshot(
        application_id=app_id,
        version=max_version + 1,
        config_json=json.dumps(config, ensure_ascii=False),
        source=source,
        summary=summary or f"来源: {source}",
    )
    db.add(snapshot)
    # 不 commit —— 让调用方统一 commit
    logger.info(f"应用 {app_id} 保存配置快照 v{snapshot.version} (source={source})")
    return snapshot


async def get_version_history(
    db: AsyncSession,
    app_id: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """获取配置版本历史（最新在前）"""
    result = await db.execute(
        select(ConfigSnapshot)
        .where(ConfigSnapshot.application_id == app_id)
        .order_by(ConfigSnapshot.version.desc())
        .limit(limit)
    )
    snapshots = result.scalars().all()
    return [
        {
            "id": s.id,
            "version": s.version,
            "source": s.source,
            "summary": s.summary,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


async def get_snapshot_config(
    db: AsyncSession,
    app_id: int,
    version: int,
) -> Optional[Dict[str, Any]]:
    """获取指定版本的配置内容"""
    result = await db.execute(
        select(ConfigSnapshot).where(
            ConfigSnapshot.application_id == app_id,
            ConfigSnapshot.version == version,
        )
    )
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        return None
    try:
        return json.loads(snapshot.config_json)
    except json.JSONDecodeError:
        return None


def three_way_diff(
    base: Optional[Dict],
    current: Optional[Dict],
    incoming: Optional[Dict],
) -> Dict[str, Any]:
    """三方合并冲突检测。

    - base: 公共基础版本（如上次文档解析结果）
    - current: 当前本地配置（可能包含 chat patch）
    - incoming: 新的变更来源（如新文档解析结果）

    返回:
    {
        "has_conflicts": bool,
        "conflicts": [
            {
                "resource_type": "model" | "dict" | "role" | "field",
                "code": str,
                "name": str,
                "base_value": ...,
                "current_value": ...,
                "incoming_value": ...,
                "description": str,
            }
        ],
        "safe_incoming": [...],   # incoming 中没有冲突的变更
        "safe_current": [...],    # current 中没有冲突的变更
    }
    """
    base = base or {}
    current = current or {}
    incoming = incoming or {}

    # 解包 data wrapper
    if "data" in base and isinstance(base.get("data"), dict):
        base = base["data"]
    if "data" in current and isinstance(current.get("data"), dict):
        current = current["data"]
    if "data" in incoming and isinstance(incoming.get("data"), dict):
        incoming = incoming["data"]

    conflicts = []
    safe_incoming = []
    safe_current = []

    # 对比模型
    _diff_resource_list(
        base.get("models", []),
        current.get("models", []),
        incoming.get("models", []),
        "model",
        conflicts, safe_incoming, safe_current,
    )

    # 对比字典
    _diff_resource_list(
        base.get("dicts", []),
        current.get("dicts", []),
        incoming.get("dicts", []),
        "dict",
        conflicts, safe_incoming, safe_current,
    )

    # 对比角色
    _diff_resource_list(
        base.get("roles", []),
        current.get("roles", []),
        incoming.get("roles", []),
        "role",
        conflicts, safe_incoming, safe_current,
    )

    return {
        "has_conflicts": len(conflicts) > 0,
        "conflicts": conflicts,
        "safe_incoming": safe_incoming,
        "safe_current": safe_current,
    }


def _diff_resource_list(
    base_list: List[Dict],
    current_list: List[Dict],
    incoming_list: List[Dict],
    resource_type: str,
    conflicts: List[Dict],
    safe_incoming: List[Dict],
    safe_current: List[Dict],
):
    """对比三方的资源列表，检测冲突"""
    base_by_code = {r.get("code", r.get("name", "")): r for r in base_list}
    current_by_code = {r.get("code", r.get("name", "")): r for r in current_list}
    incoming_by_code = {r.get("code", r.get("name", "")): r for r in incoming_list}

    all_codes = set(base_by_code) | set(current_by_code) | set(incoming_by_code)

    for code in all_codes:
        base_val = base_by_code.get(code)
        curr_val = current_by_code.get(code)
        inc_val = incoming_by_code.get(code)

        # 计算谁相对 base 有变化
        curr_changed = _has_changed(base_val, curr_val)
        inc_changed = _has_changed(base_val, inc_val)

        if curr_changed and inc_changed:
            # 双方都改了 —— 冲突
            conflicts.append({
                "resource_type": resource_type,
                "code": code,
                "name": (curr_val or inc_val or base_val or {}).get("name", code),
                "base_value": base_val,
                "current_value": curr_val,
                "incoming_value": inc_val,
                "description": f"{resource_type} '{code}' 在本地和新来源中都有修改",
            })
        elif inc_changed and not curr_changed:
            safe_incoming.append({
                "resource_type": resource_type,
                "code": code,
                "value": inc_val,
            })
        elif curr_changed and not inc_changed:
            safe_current.append({
                "resource_type": resource_type,
                "code": code,
                "value": curr_val,
            })


def _has_changed(base: Optional[Dict], target: Optional[Dict]) -> bool:
    """比较两个资源是否有变化"""
    if base is None and target is None:
        return False
    if base is None or target is None:
        return True  # 一方存在一方不存在 = 有变化

    # 比较关键字段（忽略 icon 等纯展示字段）
    compare_keys = {"name", "code", "type", "required", "dict", "ref", "options", "fields", "sub_code", "sub_fields"}
    for key in compare_keys:
        b_val = base.get(key)
        t_val = target.get(key)
        if b_val != t_val:
            return True
    return False
