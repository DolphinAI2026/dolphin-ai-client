"""SPEC → Application.config conversion.

One-way transformation. Only confirmed items are emitted to keep the
config a "source of truth for what the user actually approved".
"""

from __future__ import annotations
from app.builder_spec.schema import Spec


def spec_to_config(spec: Spec) -> dict:
    """Render a Spec into the legacy Application.config dict format.

    Output shape (matches what frontend preview store consumes today):
    {
      "appName": str,
      "roles": [{"code", "name"}],
      "dicts": [{"code", "name", "options": [{"code", "name"}]}],
      "models": [{"code", "name", "fields": [{"code", "name", "type", "required", "dict?", "ref?"}]}],
      "permissions": [{"form": object_code, "rules": [{"role", "op", "data"}]}],
    }
    """
    out: dict = {}

    out["appName"] = spec.goal.title if (spec.goal and spec.goal.confirmed) else ""

    out["roles"] = [
        {"code": r.code, "name": r.name}
        for r in spec.roles if r.confirmed
    ]

    out["dicts"] = [
        {
            "code": d.code,
            "name": d.name,
            "options": [{"code": o.code, "name": o.name} for o in d.options],
        }
        for d in spec.dicts if d.confirmed
    ]

    out["models"] = [
        _render_object(o) for o in spec.objects if o.confirmed
    ]

    out["permissions"] = [
        {
            "form": p.object_code,
            "rules": [
                {"role": r.role, "op": r.op, "data": r.data} for r in p.rules
            ],
        }
        for p in spec.permissions if p.confirmed
    ]

    return out


def _render_object(obj) -> dict:
    return {
        "code": obj.code,
        "name": obj.name,
        "fields": [_render_field(f) for f in obj.fields if f.confirmed],
    }


def _render_field(f) -> dict:
    out: dict = {
        "code": f.code,
        "name": f.name,
        "type": f.type,
        "required": f.required,
    }
    if f.dict_code:
        out["dict"] = f.dict_code
    if f.ref_model and f.ref_field:
        out["ref"] = {"model": f.ref_model, "field": f.ref_field}
    return out
