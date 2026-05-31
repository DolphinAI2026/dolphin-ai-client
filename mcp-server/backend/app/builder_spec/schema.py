"""SPEC structured data model.

The SPEC object is the single source of truth for an application's
business design (goal / roles / data objects / dicts / permissions),
managed through the SPEC state machine. See
docs/superpowers/specs/2026-04-25-spec-state-machine-design.md.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Phase(str, Enum):
    GATHERING = "gathering"
    DRAFTING = "drafting"
    GENERATING = "generating"
    READY = "ready"


class Decision(BaseModel):
    id: str
    topic: str
    why_blocking: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    blocking: bool = True
    raised_in_phase: Phase
    resolved: bool = False
    resolution: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


class Goal(BaseModel):
    title: str
    summary: str
    business_problem: str
    confirmed: bool = False


class Role(BaseModel):
    code: str
    name: str
    scope: Literal["SELF", "DEPT", "DEPT_LOW", "ALL"]
    description: Optional[str] = None
    confirmed: bool = False


class FieldSpec(BaseModel):
    code: str
    name: str
    type: str
    required: bool = False
    dict_code: Optional[str] = None
    ref_model: Optional[str] = None
    ref_field: Optional[str] = None
    description: Optional[str] = None
    confirmed: bool = False


class ObjectSpec(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    fields: list[FieldSpec] = Field(default_factory=list)
    sub_objects: dict[str, list[FieldSpec]] = Field(default_factory=dict)
    confirmed: bool = False


class DictOption(BaseModel):
    code: str
    name: str


class DictSpec(BaseModel):
    code: str
    name: str
    options: list[DictOption] = Field(default_factory=list)
    confirmed: bool = False


class PermissionRule(BaseModel):
    role: str
    op: Literal["all", "add", "edit", "delete", "view"]
    data: Literal["ALL", "SELF", "DEPT", "DEPT_LOW"]


class PermissionSpec(BaseModel):
    object_code: str
    rules: list[PermissionRule] = Field(default_factory=list)
    confirmed: bool = False


class Completeness(BaseModel):
    confirmed: int = 0
    total: int = 0
    by_section: dict[str, tuple[int, int]] = Field(default_factory=dict)
    pending_decisions: int = 0
    blocking_decisions: int = 0


class Spec(BaseModel):
    id: str
    application_id: Optional[int] = None
    version: int = 1
    parent_spec_id: Optional[str] = None
    phase: Phase = Phase.GATHERING
    goal: Optional[Goal] = None
    roles: list[Role] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    dicts: list[DictSpec] = Field(default_factory=list)
    permissions: list[PermissionSpec] = Field(default_factory=list)
    decisions_pending: list[Decision] = Field(default_factory=list)
    decisions_resolved: list[Decision] = Field(default_factory=list)
    completeness: Completeness
    created_at: datetime
    updated_at: datetime
    created_by: int


def derive_completeness(spec: Spec) -> Completeness:
    """Compute completeness from a Spec snapshot.

    Counts: goal (0/1), each role, each object, each field across all objects,
    each dict, each permission.
    """
    by_section: dict[str, tuple[int, int]] = {}

    goal_total = 1 if spec.goal is not None else 0
    goal_confirmed = 1 if spec.goal and spec.goal.confirmed else 0
    if goal_total:
        by_section["goal"] = (goal_confirmed, goal_total)

    role_total = len(spec.roles)
    role_confirmed = sum(1 for r in spec.roles if r.confirmed)
    if role_total:
        by_section["roles"] = (role_confirmed, role_total)

    object_total = len(spec.objects)
    object_confirmed = sum(1 for o in spec.objects if o.confirmed)
    if object_total:
        by_section["objects"] = (object_confirmed, object_total)

    all_fields = [f for o in spec.objects for f in o.fields]
    field_total = len(all_fields)
    field_confirmed = sum(1 for f in all_fields if f.confirmed)
    if field_total:
        by_section["fields"] = (field_confirmed, field_total)

    dict_total = len(spec.dicts)
    dict_confirmed = sum(1 for d in spec.dicts if d.confirmed)
    if dict_total:
        by_section["dicts"] = (dict_confirmed, dict_total)

    perm_total = len(spec.permissions)
    perm_confirmed = sum(1 for p in spec.permissions if p.confirmed)
    if perm_total:
        by_section["permissions"] = (perm_confirmed, perm_total)

    confirmed = goal_confirmed + role_confirmed + object_confirmed + field_confirmed + dict_confirmed + perm_confirmed
    total = goal_total + role_total + object_total + field_total + dict_total + perm_total

    pending = sum(1 for d in spec.decisions_pending if not d.resolved)
    blocking = sum(1 for d in spec.decisions_pending if not d.resolved and d.blocking)

    return Completeness(
        confirmed=confirmed,
        total=total,
        by_section=by_section,
        pending_decisions=pending,
        blocking_decisions=blocking,
    )
