import glob
import os
import shutil
from functools import lru_cache
from pathlib import Path


_STATIC_NODE_BIN_DIRS = (
    "/usr/local/bin",
    "/opt/homebrew/bin",
    str(Path.home() / ".npm-global" / "bin"),
    str(Path.home() / ".volta" / "bin"),
    str(Path.home() / ".asdf" / "shims"),
    str(Path.home() / ".local" / "share" / "pnpm"),
)

_DYNAMIC_NODE_BIN_PATTERNS = (
    str(Path.home() / ".nvm" / "versions" / "node" / "*" / "bin"),
    str(Path.home() / ".fnm" / "node-versions" / "*" / "installation" / "bin"),
)


@lru_cache(maxsize=1)
def discover_node_bin_dirs() -> tuple[str, ...]:
    dirs: list[str] = []
    seen: set[str] = set()

    def add(path_str: str) -> None:
        expanded = str(Path(path_str).expanduser())
        if not expanded or expanded in seen:
            return
        if not Path(expanded).exists():
            return
        seen.add(expanded)
        dirs.append(expanded)

    for path_str in _STATIC_NODE_BIN_DIRS:
        add(path_str)

    for pattern in _DYNAMIC_NODE_BIN_PATTERNS:
        for match in sorted(glob.glob(pattern), reverse=True):
            add(match)

    return tuple(dirs)


def ensure_node_tool_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    current_path = env.get("PATH", "")
    current_parts = [part for part in current_path.split(":") if part]
    extras = [part for part in discover_node_bin_dirs() if part not in current_parts]
    if extras:
        env["PATH"] = ":".join(extras + current_parts)
    return env


def resolve_executable(name: str, env: dict[str, str] | None = None) -> str | None:
    lookup_path = (env or os.environ).get("PATH", "")
    return shutil.which(name, path=lookup_path) or shutil.which(name)
