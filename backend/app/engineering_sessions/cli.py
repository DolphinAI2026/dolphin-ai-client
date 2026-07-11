from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.engineering_sessions.git_state import GitCommandError
from app.engineering_sessions.models import SessionType
from app.engineering_sessions.registry import SessionRegistryError
from app.engineering_sessions.service import EngineeringSessionService


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_arguments",
                        "message": message,
                    }
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _json(data: Any) -> None:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    elif isinstance(data, list):
        data = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in data
        ]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _json_error(
    code: str,
    message: str,
    *,
    details: list[str] | None = None,
) -> int:
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    print(
        json.dumps(
            {"error": error},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 1


def _json_warnings(messages: list[str]) -> None:
    if not messages:
        return
    print(
        json.dumps({"warnings": messages}, ensure_ascii=False),
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="agentic session")
    parser.add_argument("--repo", default=".", help="Git repo path")
    parser.add_argument(
        "--registry-root",
        default=None,
        help="Override session registry root",
    )
    parser.add_argument(
        "--worktree-parent",
        default=None,
        help="Override worktree parent directory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument(
        "--type",
        required=True,
        choices=[item.value for item in SessionType],
    )
    create.add_argument("--title", required=True)
    create.add_argument("--base-branch", default=None)
    create.add_argument("--no-worktree", action="store_true")

    for name in ("resume", "sync", "archive", "checkpoint"):
        item = sub.add_parser(name)
        item.add_argument("session_id")
    sub.add_parser("list").add_argument("--sync", action="store_true")
    sub.add_parser("reconcile")

    checkpoint = sub.choices["checkpoint"]
    checkpoint.add_argument("--message", default=None)
    archive = sub.choices["archive"]
    archive.add_argument("--no-checkpoint", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (
        args.command == "create"
        and args.no_worktree
        and EngineeringSessionService.requires_worktree(args.type)
    ):
        parser.error(f"session type '{args.type}' requires a worktree")

    try:
        service = EngineeringSessionService(
            Path(args.repo),
            registry_root=args.registry_root,
            worktree_parent=args.worktree_parent,
        )
        if args.command == "create":
            session = service.create(
                args.type,
                args.title,
                base_branch=args.base_branch,
                create_worktree=not args.no_worktree,
            )
            _json(session)
            return 0
        if args.command == "resume":
            _json(service.resume(args.session_id))
            return 0
        if args.command == "sync":
            _json(service.sync(args.session_id))
            return 0
        if args.command == "list":
            sessions = service.list(sync=args.sync)
            _json(sessions)
            _json_warnings(service.registry.last_read_errors)
            return 0
        if args.command == "archive":
            _json(
                service.archive(
                    args.session_id,
                    checkpoint=not args.no_checkpoint,
                )
            )
            return 0
        if args.command == "checkpoint":
            _json(
                {
                    "created": service.checkpoint(
                        args.session_id,
                        message=args.message,
                    )
                }
            )
            return 0
        if args.command == "reconcile":
            sessions = service.reconcile()
            _json(sessions)
            _json_warnings(service.registry.last_read_errors)
            return 0
    except SessionRegistryError as exc:
        code = (
            "session_not_found"
            if str(exc).startswith("session not found:")
            else "session_registry_error"
        )
        return _json_error(
            code,
            str(exc),
            details=getattr(exc, "__notes__", None),
        )
    except GitCommandError as exc:
        return _json_error(
            "git_error",
            str(exc),
            details=getattr(exc, "__notes__", None),
        )
    except ValueError as exc:
        return _json_error(
            "invalid_request",
            str(exc),
            details=getattr(exc, "__notes__", None),
        )
    except Exception as exc:
        return _json_error(
            "internal_error",
            str(exc),
            details=getattr(exc, "__notes__", None),
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
