from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.engineering_sessions.models import SessionType
from app.engineering_sessions.service import EngineeringSessionService


def _json(data: Any) -> None:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    elif isinstance(data, list):
        data = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in data
        ]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic session")
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
        _json(service.list(sync=args.sync))
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
        _json(service.reconcile())
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
