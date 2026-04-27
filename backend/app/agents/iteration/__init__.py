"""迭代分级 + SpecPatch（架构文档 § 6.6）。"""
from app.agents.iteration.classifier import (
    IterationClassification,
    classify_heuristic,
    classify_iteration,
)
from app.agents.iteration.spec_patch import (
    IterationLevel,
    PatchApplyError,
    PatchOp,
    SpecPatch,
    apply_patch,
    validate_path,
)

__all__ = [
    # SpecPatch
    "IterationLevel",
    "PatchOp",
    "SpecPatch",
    "PatchApplyError",
    "apply_patch",
    "validate_path",
    # Classifier
    "IterationClassification",
    "classify_iteration",
    "classify_heuristic",
]
