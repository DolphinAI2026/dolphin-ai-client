"""AI Builder business SPEC state machine.

This package is intentionally separate from ``app.spec``. ``app.spec`` remains
the Coding V2 component/page contract used by BrainstormAgent and CodingAgent,
while this package stores the business SPEC edited in AI Builder.
"""

from app.builder_spec.schema import (
    Completeness,
    Decision,
    DictOption,
    DictSpec,
    FieldSpec,
    Goal,
    ObjectSpec,
    PermissionRule,
    PermissionSpec,
    Phase,
    Role,
    Spec,
    derive_completeness,
)

__all__ = [
    "Completeness",
    "Decision",
    "DictOption",
    "DictSpec",
    "FieldSpec",
    "Goal",
    "ObjectSpec",
    "PermissionRule",
    "PermissionSpec",
    "Phase",
    "Role",
    "Spec",
    "derive_completeness",
]
