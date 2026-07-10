"""Engineering session registry and Git worktree orchestration."""

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
)

__all__ = [
    "EngineeringSession",
    "SessionStatus",
    "SessionType",
]


def __getattr__(name: str) -> object:
    if name == "EngineeringSessionService":
        try:
            from app.engineering_sessions.service import EngineeringSessionService
        except ModuleNotFoundError as exc:
            if exc.name == "app.engineering_sessions.service":
                raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
            raise

        return EngineeringSessionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
