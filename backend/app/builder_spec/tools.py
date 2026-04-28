"""SPEC tool definitions and dispatch.

21 tools split across 4 groups:
- universal (4): ask_clarifying_question, set_goal, transition_phase, resolve_decision
- write (7): add_role, update_role, add_object, add_field, update_field, add_dict, add_permission
- confirm (5): confirm_role, confirm_object, confirm_field, confirm_dict, confirm_permission
- dismiss (5): dismiss_role, dismiss_object, dismiss_field, dismiss_dict, dismiss_permission
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
from app.builder_spec.schema import (
    Spec, Phase, Goal, Role, FieldSpec, ObjectSpec,
    DictSpec, DictOption, PermissionSpec, PermissionRule, Decision,
    derive_completeness,
)


class ToolError(Exception):
    """Raised when a tool call is invalid. Message is fed back to the LLM."""


# ── Tool definitions in OpenAI tool-calling format ──

def _tool(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def _str_param(desc: str) -> dict:
    return {"type": "string", "description": desc}


TOOL_DEFINITIONS: list[dict] = [
    # ── Universal ──
    _tool("ask_clarifying_question",
          "Append a pending decision (clarifying question) for the user to answer.",
          {
              "type": "object",
              "properties": {
                  "topic": _str_param("Short question, e.g. '季度起算月'"),
                  "why_blocking": _str_param("Why this blocks SPEC progression (optional)"),
                  "options": {"type": "array", "items": {"type": "string"},
                              "description": "Candidate answers (optional)"},
                  "blocking": {"type": "boolean", "default": True,
                               "description": "Whether this blocks phase transition"},
              },
              "required": ["topic"],
          }),
    _tool("set_goal", "Set or replace the application goal (default unconfirmed).",
          {
              "type": "object",
              "properties": {
                  "title": _str_param("Application name"),
                  "summary": _str_param("One-paragraph summary"),
                  "business_problem": _str_param("Business problem this solves"),
              },
              "required": ["title", "summary", "business_problem"],
          }),
    _tool("transition_phase", "Move SPEC to a new phase. Blocked if any blocking decision is pending.",
          {
              "type": "object",
              "properties": {
                  "target": {"type": "string", "enum": ["gathering", "drafting", "generating", "ready"]},
                  "reason": _str_param("Why transitioning"),
              },
              "required": ["target", "reason"],
          }),
    _tool("resolve_decision", "Resolve a pending decision with the user's answer.",
          {
              "type": "object",
              "properties": {
                  "decision_id": _str_param("ID of the pending decision (e.g. 'd_xxx')"),
                  "resolution": _str_param("The user's resolved answer"),
              },
              "required": ["decision_id", "resolution"],
          }),
    # ── Write (7) ──
    _tool("add_role", "Add a new role (default unconfirmed).",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("English snake_case code, e.g. 'finance_lead'"),
                  "name": _str_param("Display name, e.g. '财务负责人'"),
                  "scope": {"type": "string", "enum": ["SELF", "DEPT", "DEPT_LOW", "ALL"]},
                  "description": _str_param("Optional description"),
              },
              "required": ["code", "name", "scope"],
          }),
    _tool("update_role", "Update an existing role's fields. Confirmed flag preserved.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Existing role code"),
                  "name": _str_param("New display name (optional)"),
                  "scope": {"type": "string", "enum": ["SELF", "DEPT", "DEPT_LOW", "ALL"]},
                  "description": _str_param("New description (optional)"),
              },
              "required": ["code"],
          }),
    _tool("add_object", "Add a new business object (data model) with optional fields.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Snake_case code prefixed with 't_', e.g. 't_quarter_forecast'"),
                  "name": _str_param("Display name"),
                  "description": _str_param("Optional"),
                  "fields": {
                      "type": "array",
                      "items": {"type": "object", "properties": {
                          "code": {"type": "string"}, "name": {"type": "string"},
                          "type": {"type": "string"},
                          "required": {"type": "boolean", "default": False},
                          "dict_code": {"type": "string"},
                          "ref_model": {"type": "string"},
                          "ref_field": {"type": "string"},
                          "description": {"type": "string"},
                      }, "required": ["code", "name", "type"]},
                  },
              },
              "required": ["code", "name"],
          }),
    _tool("add_field", "Add a field to an existing object.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Existing object code"),
                  "field": {"type": "object", "properties": {
                      "code": {"type": "string"}, "name": {"type": "string"},
                      "type": {"type": "string"},
                      "required": {"type": "boolean", "default": False},
                      "dict_code": {"type": "string"},
                      "ref_model": {"type": "string"},
                      "ref_field": {"type": "string"},
                      "description": {"type": "string"},
                  }, "required": ["code", "name", "type"]},
              },
              "required": ["object_code", "field"],
          }),
    _tool("update_field", "Update an existing field. Confirmed flag preserved.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Object code"),
                  "field_code": _str_param("Field code to update"),
                  "name": _str_param("New name (optional)"),
                  "type": _str_param("New type (optional)"),
                  "required": {"type": "boolean"},
                  "dict_code": _str_param("New dict_code (optional)"),
                  "ref_model": _str_param("New ref_model (optional)"),
                  "ref_field": _str_param("New ref_field (optional)"),
                  "description": _str_param("New description (optional)"),
              },
              "required": ["object_code", "field_code"],
          }),
    _tool("add_dict", "Add a data dictionary with options.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Snake_case code, e.g. 'forecast_status'"),
                  "name": _str_param("Display name"),
                  "options": {"type": "array", "items": {"type": "object", "properties": {
                      "code": {"type": "string"}, "name": {"type": "string"},
                  }, "required": ["code", "name"]}},
              },
              "required": ["code", "name", "options"],
          }),
    _tool("add_permission", "Set permission rules for a business object.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Object code"),
                  "rules": {"type": "array", "items": {"type": "object", "properties": {
                      "role": {"type": "string"},
                      "op": {"type": "string", "enum": ["all", "add", "edit", "delete", "view"]},
                      "data": {"type": "string", "enum": ["ALL", "SELF", "DEPT", "DEPT_LOW"]},
                  }, "required": ["role", "op", "data"]}},
              },
              "required": ["object_code", "rules"],
          }),
    # ── Confirm (6) ──
    _tool("confirm_goal", "Mark the application goal as user-confirmed.", {
        "type": "object", "properties": {}, "required": [],
    }),
    _tool("confirm_role", "Mark a role as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Role code")}, "required": ["code"],
    }),
    _tool("confirm_object", "Mark an object as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Object code")}, "required": ["code"],
    }),
    _tool("confirm_field", "Mark a field as user-confirmed.", {
        "type": "object", "properties": {
            "object_code": _str_param("Object code"),
            "field_code": _str_param("Field code"),
        }, "required": ["object_code", "field_code"],
    }),
    _tool("confirm_dict", "Mark a dict as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Dict code")}, "required": ["code"],
    }),
    _tool("confirm_permission", "Mark permissions of an object as user-confirmed.", {
        "type": "object", "properties": {"object_code": _str_param("Object code")},
        "required": ["object_code"],
    }),
    # ── Dismiss (5): physical delete ──
    _tool("dismiss_role", "Delete a role (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Role code")}, "required": ["code"],
    }),
    _tool("dismiss_object", "Delete an object (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Object code")}, "required": ["code"],
    }),
    _tool("dismiss_field", "Delete a field (user rejected).", {
        "type": "object", "properties": {
            "object_code": _str_param("Object code"),
            "field_code": _str_param("Field code"),
        }, "required": ["object_code", "field_code"],
    }),
    _tool("dismiss_dict", "Delete a dict (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Dict code")}, "required": ["code"],
    }),
    _tool("dismiss_permission", "Delete permission rules of an object.", {
        "type": "object", "properties": {"object_code": _str_param("Object code")},
        "required": ["object_code"],
    }),
]


# ── Tool execution functions ──

def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _refresh(spec: Spec) -> Spec:
    """Recompute completeness + bump updated_at."""
    spec.completeness = derive_completeness(spec)
    spec.updated_at = _now()
    return spec


def _ask_clarifying_question(spec: Spec, args: dict) -> Spec:
    decision = Decision(
        id=_short_id("d"),
        topic=args["topic"],
        why_blocking=args.get("why_blocking"),
        options=args.get("options", []),
        blocking=args.get("blocking", True),
        raised_in_phase=spec.phase,
        created_at=_now(),
    )
    spec.decisions_pending.append(decision)
    return _refresh(spec)


def _set_goal(spec: Spec, args: dict) -> Spec:
    spec.goal = Goal(
        title=args["title"], summary=args["summary"],
        business_problem=args["business_problem"], confirmed=False,
    )
    return _refresh(spec)


def _transition_phase(spec: Spec, args: dict) -> Spec:
    target = Phase(args["target"])
    blocking = [d for d in spec.decisions_pending if d.blocking and not d.resolved]
    if blocking:
        topics = ", ".join(d.topic for d in blocking)
        raise ToolError(f"Cannot transition: {len(blocking)} blocking decision(s) pending: {topics}")
    spec.phase = target
    return _refresh(spec)


def _resolve_decision(spec: Spec, args: dict) -> Spec:
    did = args["decision_id"]
    target = next((d for d in spec.decisions_pending if d.id == did), None)
    if target is None:
        raise ToolError(f"Decision id={did} not found in pending list")
    target.resolved = True
    target.resolution = args["resolution"]
    target.resolved_at = _now()
    spec.decisions_pending.remove(target)
    spec.decisions_resolved.append(target)
    return _refresh(spec)


def _add_role(spec: Spec, args: dict) -> Spec:
    if any(r.code == args["code"] for r in spec.roles):
        raise ToolError(f"Role code={args['code']} already exists; use update_role instead")
    spec.roles.append(Role(
        code=args["code"], name=args["name"], scope=args["scope"],
        description=args.get("description"), confirmed=False,
    ))
    return _refresh(spec)


def _update_role(spec: Spec, args: dict) -> Spec:
    role = next((r for r in spec.roles if r.code == args["code"]), None)
    if role is None:
        raise ToolError(f"Role code={args['code']} not found")
    if "name" in args: role.name = args["name"]
    if "scope" in args: role.scope = args["scope"]
    if "description" in args: role.description = args["description"]
    return _refresh(spec)


def _add_object(spec: Spec, args: dict) -> Spec:
    if any(o.code == args["code"] for o in spec.objects):
        raise ToolError(f"Object code={args['code']} already exists")
    fields = [FieldSpec(**f, confirmed=False) for f in args.get("fields", [])]
    spec.objects.append(ObjectSpec(
        code=args["code"], name=args["name"],
        description=args.get("description"), fields=fields, confirmed=False,
    ))
    return _refresh(spec)


def _add_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field_data = args["field"]
    if any(f.code == field_data["code"] for f in obj.fields):
        raise ToolError(f"Field code={field_data['code']} already exists in {obj.code}")
    obj.fields.append(FieldSpec(**field_data, confirmed=False))
    return _refresh(spec)


def _update_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field = next((f for f in obj.fields if f.code == args["field_code"]), None)
    if field is None:
        raise ToolError(f"Field code={args['field_code']} not found in {obj.code}")
    for key in ("name", "type", "required", "dict_code", "ref_model", "ref_field", "description"):
        if key in args:
            setattr(field, key, args[key])
    return _refresh(spec)


def _add_dict(spec: Spec, args: dict) -> Spec:
    if any(d.code == args["code"] for d in spec.dicts):
        raise ToolError(f"Dict code={args['code']} already exists")
    options = [DictOption(**o) for o in args.get("options", [])]
    spec.dicts.append(DictSpec(code=args["code"], name=args["name"], options=options, confirmed=False))
    return _refresh(spec)


def _add_permission(spec: Spec, args: dict) -> Spec:
    obj_code = args["object_code"]
    rules = [PermissionRule(**r) for r in args["rules"]]
    existing = next((p for p in spec.permissions if p.object_code == obj_code), None)
    if existing:
        existing.rules = rules
        existing.confirmed = False
    else:
        spec.permissions.append(PermissionSpec(object_code=obj_code, rules=rules, confirmed=False))
    return _refresh(spec)


def _flip_confirmed(item, value: bool):
    item.confirmed = value


def _confirm_goal(spec: Spec, args: dict) -> Spec:
    if spec.goal is None:
        raise ToolError("Goal not set; cannot confirm")
    _flip_confirmed(spec.goal, True)
    return _refresh(spec)


def _confirm_role(spec: Spec, args: dict) -> Spec:
    role = next((r for r in spec.roles if r.code == args["code"]), None)
    if role is None:
        raise ToolError(f"Role code={args['code']} not found")
    _flip_confirmed(role, True)
    return _refresh(spec)


def _confirm_object(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['code']} not found")
    _flip_confirmed(obj, True)
    return _refresh(spec)


def _confirm_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field = next((f for f in obj.fields if f.code == args["field_code"]), None)
    if field is None:
        raise ToolError(f"Field code={args['field_code']} not found in {obj.code}")
    _flip_confirmed(field, True)
    return _refresh(spec)


def _confirm_dict(spec: Spec, args: dict) -> Spec:
    d = next((x for x in spec.dicts if x.code == args["code"]), None)
    if d is None:
        raise ToolError(f"Dict code={args['code']} not found")
    _flip_confirmed(d, True)
    return _refresh(spec)


def _confirm_permission(spec: Spec, args: dict) -> Spec:
    p = next((x for x in spec.permissions if x.object_code == args["object_code"]), None)
    if p is None:
        raise ToolError(f"Permission for object_code={args['object_code']} not found")
    _flip_confirmed(p, True)
    return _refresh(spec)


def _dismiss_role(spec: Spec, args: dict) -> Spec:
    spec.roles = [r for r in spec.roles if r.code != args["code"]]
    return _refresh(spec)


def _dismiss_object(spec: Spec, args: dict) -> Spec:
    spec.objects = [o for o in spec.objects if o.code != args["code"]]
    return _refresh(spec)


def _dismiss_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    obj.fields = [f for f in obj.fields if f.code != args["field_code"]]
    return _refresh(spec)


def _dismiss_dict(spec: Spec, args: dict) -> Spec:
    spec.dicts = [d for d in spec.dicts if d.code != args["code"]]
    return _refresh(spec)


def _dismiss_permission(spec: Spec, args: dict) -> Spec:
    spec.permissions = [p for p in spec.permissions if p.object_code != args["object_code"]]
    return _refresh(spec)


_TOOL_DISPATCH = {
    "ask_clarifying_question": _ask_clarifying_question,
    "set_goal": _set_goal,
    "transition_phase": _transition_phase,
    "resolve_decision": _resolve_decision,
    "add_role": _add_role,
    "update_role": _update_role,
    "add_object": _add_object,
    "add_field": _add_field,
    "update_field": _update_field,
    "add_dict": _add_dict,
    "add_permission": _add_permission,
    "confirm_goal": _confirm_goal,
    "confirm_role": _confirm_role,
    "confirm_object": _confirm_object,
    "confirm_field": _confirm_field,
    "confirm_dict": _confirm_dict,
    "confirm_permission": _confirm_permission,
    "dismiss_role": _dismiss_role,
    "dismiss_object": _dismiss_object,
    "dismiss_field": _dismiss_field,
    "dismiss_dict": _dismiss_dict,
    "dismiss_permission": _dismiss_permission,
}


# ── Mutation-creating tools that should not run as the very first action of a fresh
# ── gathering phase. The first turn must establish at least 3 clarifying questions
# ── (per spec section 5 strong constraint #1).
_FIRST_TURN_BLOCKED = {
    "set_goal", "add_role", "update_role", "add_object", "add_field",
    "update_field", "add_dict", "add_permission",
}


def dispatch_tool(spec: Spec, name: str, args: dict, *, enforce_first_turn: bool = False) -> Spec:
    """Execute a tool against a Spec object. Returns the mutated spec.

    Raises ToolError on validation failure; the SpecAgent feeds the error
    back to the LLM as a tool result, so the LLM can self-correct.
    """
    if name not in _TOOL_DISPATCH:
        raise ToolError(f"Unknown tool: {name}")

    if (
        enforce_first_turn
        and spec.phase == Phase.GATHERING
        and spec.completeness.confirmed == 0
        and len(spec.decisions_pending) < 3
        and name in _FIRST_TURN_BLOCKED
    ):
        raise ToolError(
            f"In gathering phase first turn (completeness=0, decisions<3), "
            f"you must call ask_clarifying_question at least 3 times before "
            f"calling {name}. Re-plan this turn to start with clarifying questions."
        )

    return _TOOL_DISPATCH[name](spec, args)
