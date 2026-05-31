"""Workspace 路径解析与安全 — 工具层用，不抛 HTTPException。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# 复用 online_coding 的根目录与元数据读取——workspace 本身仍然由 online_coding 管理。
def _online_coding_helpers():
    """延迟 import，避免循环依赖。"""
    from app.routes import online_coding as oc
    return oc


def find_workspace(workspace_id: str) -> Optional[tuple[Path, dict]]:
    """根据 workspace_id 查找目录与 meta，找不到返回 None（不抛异常）。

    扫描覆盖新路径 {root}/{tenant_id}/<ws> 与老路径 {root}/<ws>。
    """
    oc = _online_coding_helpers()
    oc.ONLINE_CODING_ROOT.mkdir(parents=True, exist_ok=True)
    for ws_dir in oc._iter_workspace_meta_dirs():
        try:
            meta = oc._read_workspace(ws_dir)
        except Exception:
            continue
        if meta.get("id") == workspace_id:
            return ws_dir, meta
    return None


def get_repo_dir(workspace_id: str) -> Optional[Path]:
    """返回该 workspace 的工作根（即 IDE 看到的根，repo 子目录）。"""
    found = find_workspace(workspace_id)
    if not found:
        return None
    ws_dir, _ = found
    oc = _online_coding_helpers()
    repo_dir = oc._repo_path(ws_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    return repo_dir


def resolve_path(repo_dir: Path, rel_path: str) -> tuple[Optional[Path], Optional[str]]:
    """把工具传入的相对路径解析为绝对路径，并校验不越界。
    返回 (Path, None) 成功；(None, error_message) 失败。
    .git 内部文件直接拒绝。
    """
    clean = (rel_path or "").strip().replace("\\", "/")
    if not clean:
        return None, "路径不能为空"
    if clean.startswith("/") or "\x00" in clean:
        return None, "不允许绝对路径或非法字符"
    parts = clean.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        return None, "路径含非法段（'.' / '..' / 空段）"

    root = repo_dir.resolve()
    target = (repo_dir / clean).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None, "路径越界"
    if ".git" in rel.parts:
        return None, "禁止访问 .git 内部"
    return target, None


def member_can_access(workspace_id: str, user_id: int, tenant_id: int) -> tuple[bool, Optional[str]]:
    """判断该用户能否操作该 workspace。
    规则：
      1. workspace meta 的 owner（meta.user_id）直接放行
      2. 是 vibe_coding_workspace_members 表内的成员（同 tenant）也放行
    多人协作 v1 暂时只判 owner，DB 成员表预留——member 校验交给 routes 层做更直观。
    返回 (True, None) 成功；(False, 错误说明) 失败。
    """
    found = find_workspace(workspace_id)
    if not found:
        return False, "workspace 不存在"
    _, meta = found
    if int(meta.get("user_id") or 0) == user_id:
        return True, None
    # TODO Step 2: 多人协作时查 vibe_coding_workspace_members
    return False, "无权访问该 workspace"
