from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def main() -> None:
    payload = json.load(sys.stdin)
    database_path = Path(str(payload["database_path"])).resolve()
    launch_tokens = [str(value) for value in payload.get("launch_tokens", []) if value]
    if not launch_tokens:
        raise SystemExit("launch token evidence is empty")

    with sqlite3.connect(database_path) as db:
        sessions = db.execute(
            "select browser_session_id, generation, runtime_session_hash "
            "from code_runtime_browser_sessions order by id"
        ).fetchall()
        if len(sessions) < 2:
            raise SystemExit(f"expected at least 2 browser sessions, got {len(sessions)}")
        if len({row[0] for row in sessions}) != len(sessions):
            raise SystemExit("browser_session_id values are not isolated")
        if len({row[2] for row in sessions}) != len(sessions):
            raise SystemExit("runtime session hashes are not isolated")
        if max(int(row[1]) for row in sessions) < 2:
            raise SystemExit(f"browser generations did not advance: {sessions!r}")

        tables = [
            row[0]
            for row in db.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()
        ]
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise SystemExit(f"unsafe table name: {table!r}")
            rows = db.execute(f'SELECT * FROM "{table}"').fetchall()
            serialized = repr(rows)
            for launch_token in launch_tokens:
                if launch_token in serialized:
                    raise SystemExit(f"launch token persisted in table {table}")

    print("L3_DATABASE_ISOLATION=PASS")


if __name__ == "__main__":
    main()
