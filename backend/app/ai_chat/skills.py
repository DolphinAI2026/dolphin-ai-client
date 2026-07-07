"""Skill 包文件系统层 — 扫描/解析/读取，路线1，不进 DB。

skill = skills_root/<name>/SKILL.md 或 skills_root/{platform,user}/<name>/SKILL.md(+helper/模板/资源)。
SKILL.md frontmatter 需含 name + description（与 Claude Code skill 一致）。
目录不存在 → 空集；显式禁用时整链路 no-op。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app import runtime

log = logging.getLogger(__name__)


def skills_root() -> Path | None:
    """解析 skill 根目录。

    优先级：显式禁用 > 显式 skills 目录 > 桌面 data_dir > Web 服务端 data 目录 > 仓库兜底。

    桌面判定与 data_dir 反推统一走 app.runtime 门面（is_desktop / desktop_data_dir /
    server_data_dir），不再在此自行判断桌面态/冻结态/data 目录 env。
    桌面 data_dir 真相源仍是 desktop_sidecar.build_env 经 --data-dir 注入，见 runtime.py。
    """
    if os.environ.get("RUIJING_SKILLS_DISABLED") == "1":
        return None
    env = os.environ.get("RUIJING_SKILLS_DIR")
    if env:
        return Path(env)
    if runtime.is_desktop():
        return runtime.desktop_data_dir() / "skills"
    server = runtime.server_data_dir()
    if server:
        return server / "skills"
    return Path(__file__).resolve().parents[2] / "data" / "skills"


@dataclass
class Skill:
    name: str
    description: str
    dir: Path
    source: str  # "platform" | "user"
    files: list[str] = field(default_factory=list)


def _parse_frontmatter(md_text: str) -> tuple[dict, str]:
    """切出 YAML frontmatter（仅取 name/description 等简单 key: value）+ 正文。

    不引入 yaml 依赖：frontmatter 只用扁平 key: value，手解析足够且更稳。
    """
    if not md_text.startswith("---"):
        return {}, md_text
    lines = md_text.splitlines()
    # 找第二个 '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, md_text
    meta: dict = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


_ASCII_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_skill_name(name: str, *, require_ascii: bool = False) -> None:
    """校验 skill 名合法性，非法抛 ValueError（路由/工具层映射成 4xx / error_code）。

    默认沿用历史行为（仅拦空串 + 路径分隔 + ./..）；require_ascii=True 额外要求
    纯 ASCII 字母/数字/连字符/下划线/点 —— AI 生成路径用，防 LLM 造非 ASCII 名引发并发覆盖/路径问题。
    """
    n = (name or "").strip()
    if not n:
        raise ValueError("技能名不能为空")
    if "/" in n or "\\" in n or n in (".", ".."):
        raise ValueError(f"非法技能名: {name}")
    if require_ascii and not _ASCII_SKILL_NAME_RE.match(n):
        raise ValueError(f"技能名必须为 ASCII（字母/数字/连字符/下划线）: {name}")


def validate_skill_frontmatter(meta: dict) -> tuple[str, str]:
    """校验 SKILL.md frontmatter 必含 name + description，返回 (name, description)（已 strip）。"""
    name = (meta.get("name") or "").strip()
    desc = (meta.get("description") or "").strip()
    if not name or not desc:
        raise ValueError("SKILL.md frontmatter 必须含 name 和 description")
    return name, desc


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self._root = root if root is not None else skills_root()

    def _scan_skill_dirs(self, base: Path, source: str, by_name: dict[str, Skill]) -> None:
        if not base.is_dir():
            return
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            md = d / "SKILL.md"
            if not md.is_file():
                continue
            try:
                meta, _ = _parse_frontmatter(md.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("skill 读取失败 %s: %r", d, exc)
                continue
            name = (meta.get("name") or "").strip()
            desc = (meta.get("description") or "").strip()
            if not name or not desc:
                log.warning("skill 缺 name/description, 跳过: %s", d)
                continue
            # 顶层摘要（文件名 + 子目录名带 /），供列表展示用——避免带 JRE/大量
            # 嵌套文件的 skill 把整棵树平铺成上千项撑爆 UI。完整树由 use_skill 递归拷。
            files = [
                (p.name + "/" if p.is_dir() else p.name)
                for p in sorted(d.iterdir())
                if p.name != "SKILL.md"
            ]
            by_name[name] = Skill(name=name, description=desc, dir=d, source=source, files=files)

    def scan(self) -> list[Skill]:
        root = self._root
        if root is None or not root.exists():
            return []
        by_name: dict[str, Skill] = {}
        # 先兼容 d-ai-skills 这类扁平技能根；再扫 platform/user，user 后扫覆盖同名。
        self._scan_skill_dirs(root, "platform", by_name)
        for source in ("platform", "user"):
            self._scan_skill_dirs(root / source, source, by_name)
        return list(by_name.values())

    def get(self, name: str) -> Skill | None:
        for s in self.scan():
            if s.name == name:
                return s
        return None

    def _resolve_file(self, name: str, rel: str, *, require_user: bool = False) -> "Path":
        """解析 skill 内文件的绝对路径，强制落在 skill 目录内（防越界）。"""
        s = self.get(name)
        if s is None:
            raise FileNotFoundError(f"技能不存在: {name}")
        if require_user and s.source != "user":
            raise PermissionError("平台预置技能只读，不能修改")
        base = s.dir.resolve()
        target = (base / rel).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"路径越界: {rel}")
        return target

    def list_skill_files(self, name: str) -> list[str]:
        """skill 目录内全部文件的相对 posix 路径（含 SKILL.md 与嵌套）。"""
        s = self.get(name)
        if s is None:
            raise FileNotFoundError(f"技能不存在: {name}")
        base = s.dir
        return sorted(
            p.relative_to(base).as_posix()
            for p in base.rglob("*")
            if p.is_file()
        )

    def read_skill_file(self, name: str, rel: str) -> str:
        target = self._resolve_file(name, rel)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在: {rel}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_skill_file(self, name: str, rel: str, content: str) -> None:
        target = self._resolve_file(name, rel, require_user=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def delete_skill_file(self, name: str, rel: str) -> None:
        target = self._resolve_file(name, rel, require_user=True)
        if rel.strip("/") == "SKILL.md":
            raise ValueError("不能删除 SKILL.md")
        if target.is_file():
            target.unlink()

    def update_skill_metadata(self, name: str, *, description: str | None = None,
                              tags: list[str] | None = None, display_name: str | None = None) -> None:
        """改写 SKILL.md frontmatter（保留正文）。name(标识) 不在此改，避免目录改名。"""
        s = self.get(name)
        if s is None:
            raise FileNotFoundError(f"技能不存在: {name}")
        if s.source != "user":
            raise PermissionError("平台预置技能只读")
        md_path = s.dir / "SKILL.md"
        meta, body = _parse_frontmatter(md_path.read_text(encoding="utf-8"))
        if description is not None:
            meta["description"] = description
        if display_name is not None:
            meta["display_name"] = display_name
        if tags is not None:
            meta["tags"] = ", ".join(tags)
        meta.setdefault("name", name)
        fm = "\n".join(f"{k}: {v}" for k, v in meta.items())
        md_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

    def create_user_skill(self, name: str) -> str:
        """新建空白 user skill（骨架 SKILL.md）。"""
        validate_skill_name(name)
        if self.get(name) is not None:
            raise ValueError(f"技能已存在: {name}")
        root = self._root if self._root is not None else skills_root()
        if root is None:
            raise ValueError("当前环境未启用技能库")
        d = (root / "user" / name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: 在这里写技能的一句话说明\n---\n"
            f"## 怎么做\n1. 描述这个技能的步骤。\n2. 需要脚本就新建 helper.py，用 run_python 执行。\n",
            encoding="utf-8",
        )
        return name

    def clone_skill(self, src_name: str, new_name: str) -> str:
        """复制任意 skill（含 platform 预置）为一个 user skill。"""
        src = self.get(src_name)
        if src is None:
            raise FileNotFoundError(f"技能不存在: {src_name}")
        validate_skill_name(new_name)
        if self.get(new_name) is not None:
            raise ValueError(f"技能已存在: {new_name}")
        root = self._root if self._root is not None else skills_root()
        if root is None:
            raise ValueError("当前环境未启用技能库")
        dest = (root / "user" / new_name)
        shutil.copytree(src.dir, dest)
        # 改 frontmatter name 对齐新目录名
        md_path = dest / "SKILL.md"
        if md_path.is_file():
            meta, body = _parse_frontmatter(md_path.read_text(encoding="utf-8"))
            meta["name"] = new_name
            fm = "\n".join(f"{k}: {v}" for k, v in meta.items())
            md_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
        return new_name

    def read_skill_md(self, name: str) -> str:
        s = self.get(name)
        if s is None:
            return ""
        _, body = _parse_frontmatter((s.dir / "SKILL.md").read_text(encoding="utf-8"))
        return body


def build_skill_manifest(skills: list[Skill]) -> str:
    """渲染 skill 清单注入 system prompt（渐进披露）。空集返回空串。"""
    if not skills:
        return ""
    lines = [
        "\n\n## 可用技能(Skill)",
        "需要某个技能时, 先调 `use_skill(name)` 读它的完整说明再按其执行(脚本会在当前运行环境执行):",
    ]
    for s in skills:
        tag = "平台预置" if s.source == "platform" else "用户上传"
        lines.append(f"- {s.name}: {s.description}  [{tag}]")
    return "\n".join(lines)
