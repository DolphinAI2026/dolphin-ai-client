"""RBAC permission checking module.

Dual-layer permission model:
1. Org role (role.permissions) — capability gate: CAN the user do this type of action?
2. Resource layer (ownership + team role) — scope: WHERE can the user do it?

Both layers must pass (intersection).
"""
from __future__ import annotations
from enum import Enum
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.tenant import TeamMember


class Action(str, Enum):
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    CLONE = "clone"


# All permission codes defined in the system
PERMISSION_CODES = [
    "conversation:view", "conversation:create", "conversation:delete",
    "team:view", "team:create", "team:manage",
    "member:view", "member:invite", "member:manage",
    "role:view", "role:create", "role:edit", "role:delete",
]

# Team role → allowed resource actions
TEAM_ROLE_ACTIONS: dict[str, set[str]] = {
    "admin": {Action.VIEW, Action.CREATE, Action.EDIT, Action.DELETE, Action.CLONE},
    "member": {Action.VIEW, Action.CREATE, Action.EDIT, Action.DELETE, Action.CLONE},
    "viewer": {Action.VIEW, Action.CLONE},
}

# Actions that are "owner-only" for team members (not admins)
_OWNER_ONLY_ACTIONS = {Action.EDIT, Action.DELETE}


def has_org_permission(permissions: dict | None, resource_type: str, action: str | Action) -> bool:
    """Check if the org role's permission JSON allows the given action on a resource type."""
    if not permissions:
        return False
    if permissions.get("*") is True:
        return True
    if isinstance(action, Action):
        action = action.value
    key = f"{resource_type}:{action}"
    return bool(permissions.get(key, False))


async def _get_team_role(db: AsyncSession, user_id: int, team_id: int) -> str | None:
    """Get a user's role in a specific team, or None if not a member."""
    result = await db.execute(
        select(TeamMember.team_role).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_user_team_roles(db: AsyncSession, user_id: int) -> dict[int, str]:
    """Return {team_id: team_role} for all teams the user belongs to."""
    result = await db.execute(
        select(TeamMember.team_id, TeamMember.team_role).where(
            TeamMember.user_id == user_id
        )
    )
    return {row.team_id: row.team_role for row in result.all()}


async def check_resource_permission(
    ctx,  # AuthContext
    db: AsyncSession,
    resource,  # ORM model with created_by, optional team_id
    resource_type: str,
    action: str,
) -> None:
    """Full dual-layer permission check. Raises 403 if denied.

    Layer 1: Org role permission (from role.permissions via ctx.org_permissions)
    Layer 2: Resource scope (ownership + team role)
    """
    # 应用权限尚未设计，当前只由各接口自身的租户条件隔离。
    if resource_type == "application":
        return

    # Super admin / tenant admin bypass all checks
    if ctx.tenant_role in ("platform_admin", "tenant_admin"):
        return

    # 文案用权限码 (view)，不要 py3.13 str-enum 的 repr (Action.VIEW)
    action_name = action.value if isinstance(action, Action) else action

    # Layer 1: Org role permission
    if not has_org_permission(ctx.org_permissions, resource_type, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"你的角色没有 {resource_type}:{action_name} 权限",
        )

    # Layer 2: Resource scope
    is_owner = getattr(resource, "created_by", None) == ctx.user.id
    team_id = getattr(resource, "team_id", None)

    if team_id is not None:
        # Team resource — check team role
        team_role = await _get_team_role(db, ctx.user.id, team_id)
        if team_role is None:
            # Not a team member — can only view published resources
            if action != Action.VIEW:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="你不是该团队成员",
                )
            resource_status = getattr(resource, "status", None)
            if resource_status != "completed":  # aPaaS Builder uses string status
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="该资源未完成，你无权查看",
                )
            return

        allowed = TEAM_ROLE_ACTIONS.get(team_role, set())
        if action not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"你在团队中的角色 ({team_role}) 没有 {action_name} 权限",
            )

        # For team member (not admin): EDIT/DELETE only allowed on own resources
        if team_role == "member" and action in _OWNER_ONLY_ACTIONS and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只能操作自己创建的资源",
            )
    else:
        # Personal resource — ownership check
        if action in (Action.EDIT, Action.DELETE) and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只有创建者可以操作该资源",
            )


async def batch_get_permissions(
    ctx,  # AuthContext
    db: AsyncSession,
    resources: list,
    resource_type: str,
) -> list[dict[str, bool]]:
    """Batch compute permissions for a list of resources (avoids N+1 team queries)."""
    if resource_type == "application":
        full = {Action.EDIT: True, Action.DELETE: True, Action.CLONE: True}
        return [full for _ in resources]

    # Super admin / tenant admin: all permissions
    if ctx.tenant_role in ("platform_admin", "tenant_admin"):
        full = {Action.EDIT: True, Action.DELETE: True, Action.CLONE: True}
        return [full for _ in resources]

    # Pre-fetch all user's team roles
    user_team_roles = await _get_user_team_roles(db, ctx.user.id)

    results = []
    for resource in resources:
        perms = {}
        is_owner = getattr(resource, "created_by", None) == ctx.user.id
        team_id = getattr(resource, "team_id", None)

        for action in (Action.EDIT, Action.DELETE, Action.CLONE):
            # Layer 1: Org permission
            if not has_org_permission(ctx.org_permissions, resource_type, action):
                perms[action] = False
                continue

            # Layer 2: Resource scope
            if team_id is not None:
                team_role = user_team_roles.get(team_id)
                if team_role is None:
                    perms[action] = False
                    continue
                allowed = TEAM_ROLE_ACTIONS.get(team_role, set())
                if action not in allowed:
                    perms[action] = False
                    continue
                if team_role == "member" and action in _OWNER_ONLY_ACTIONS and not is_owner:
                    perms[action] = False
                    continue
                perms[action] = True
            else:
                # Personal resource
                if action in (Action.EDIT, Action.DELETE) and not is_owner:
                    perms[action] = False
                else:
                    perms[action] = True

        results.append(perms)

    return results
