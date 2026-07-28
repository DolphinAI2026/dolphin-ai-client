from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def string_values(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise SystemExit(f"{key} must be a list")
    return [str(item) for item in value if item]


def main() -> None:
    payload = json.load(sys.stdin)
    launch_tokens = string_values(payload, "launch_tokens")
    runtime_cookies = string_values(payload, "runtime_cookies")
    other_secrets = string_values(payload, "other_secrets")
    literal_canaries = string_values(payload, "literal_canaries")
    log_paths = [Path(value).resolve() for value in string_values(payload, "log_paths")]

    if not launch_tokens:
        raise SystemExit("launch token evidence is empty")
    if not runtime_cookies:
        raise SystemExit("runtime cookie evidence is empty")
    if not log_paths:
        raise SystemExit("service log paths are empty")

    secret_canaries = [*launch_tokens, *runtime_cookies, *other_secrets]
    url_canary = re.compile(r"\?\s*token\s*=\s*(?:[A-Za-z0-9_-]\s*){20,}")
    for log_path in log_paths:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        compact_text = re.sub(r"\s+", "", text)
        if (
            any(value in text for value in literal_canaries)
            or any(value in text or value in compact_text for value in secret_canaries)
            or url_canary.search(text)
        ):
            raise SystemExit(f"credential canary found in service log: {log_path}")


if __name__ == "__main__":
    main()
