from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, Callable

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass(frozen=True)
class CleanupStats:
    rows_scanned: int = 0
    rows_cleaned: int = 0
    rows_recontaminated: int = 0
    last_checkpoint: int = 0


async def cleanup_builder_urls(
    *,
    session_factory: Callable[[], Any] | None = None,
    batch_size: int = 100,
    apply: bool = False,
) -> CleanupStats:
    from app.code_runtime.sandbox_auth import remove_builder_entry_tokens
    from app.database import AsyncSessionLocal
    from app.models.ai_chat import CodeRuntimeBinding

    session_factory = session_factory or AsyncSessionLocal
    batch_size = max(1, int(batch_size))
    rows_scanned = 0
    rows_cleaned = 0
    checkpoint = 0

    async with session_factory() as db:
        while True:
            rows = (
                await db.execute(
                    select(CodeRuntimeBinding)
                    .where(CodeRuntimeBinding.id > checkpoint)
                    .order_by(CodeRuntimeBinding.id)
                    .limit(batch_size)
                )
            ).scalars().all()
            if not rows:
                break
            for row in rows:
                checkpoint = int(row.id)
                rows_scanned += 1
                clean_url, removed = remove_builder_entry_tokens(row.builder_url)
                if not removed:
                    continue
                rows_cleaned += 1
                print(f"builder_url_cleanup row_id={row.id}")
                if apply:
                    row.builder_url = clean_url
            if apply:
                await db.commit()
            else:
                await db.rollback()

    rows_recontaminated = 0
    if apply:
        async with session_factory() as db:
            checkpoint_verify = 0
            while True:
                rows = (
                    await db.execute(
                        select(CodeRuntimeBinding)
                        .where(CodeRuntimeBinding.id > checkpoint_verify)
                        .order_by(CodeRuntimeBinding.id)
                        .limit(batch_size)
                    )
                ).scalars().all()
                if not rows:
                    break
                for row in rows:
                    checkpoint_verify = int(row.id)
                    _clean_url, removed = remove_builder_entry_tokens(
                        row.builder_url
                    )
                    if removed:
                        rows_recontaminated += 1
                        print(f"builder_url_recontaminated row_id={row.id}")

    return CleanupStats(
        rows_scanned=rows_scanned,
        rows_cleaned=rows_cleaned,
        rows_recontaminated=rows_recontaminated,
        last_checkpoint=checkpoint,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove legacy Runtime entry tokens from Code binding URLs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes. The default is dry-run.",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    return parser


async def _run(args: argparse.Namespace) -> int:
    stats = await cleanup_builder_urls(
        batch_size=args.batch_size,
        apply=args.apply,
    )
    print(json.dumps(asdict(stats), separators=(",", ":"), sort_keys=True))
    if not args.apply:
        print("dry_run=true")
    return 1 if stats.rows_recontaminated else 0


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
