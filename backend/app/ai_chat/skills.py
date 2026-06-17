"""桌面 Skill 包文件系统层 — 扫描/解析/读取，路线1，不进 DB。

skill = data_dir/skills/{platform,user}/<name>/SKILL.md(+helper/模板/资源)。
SKILL.md frontmatter 需含 name + description（与 Claude Code skill 一致）。
目录不存在 → 空集，云端/无 skill 时整链路 no-op。
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def skills_root() -> Path | None:
    """解析 skill 根目录。优先级：显式 env > 桌面 data_dir > 无。

    data_dir 的真相源是 desktop_sidecar.build_env：Tauri 用 bundle identifier 推出
    的 app_data_dir(macOS = ~/Library/Application Support/com.ruijing.builder)经
    `--data-dir` 传给 sidecar，build_env 据此 **无条件** 写 os.environ
    ['APAAS_WORKSPACE_ROOT'] = <data_dir>/workspaces。所以这里从
    APAAS_WORKSPACE_ROOT 反推 data_dir（取 .parent），与 sidecar 真正使用的目录
    严格一致；绝不能猜 ~/.ruijing-builder —— 那是 main() 里仅当没传 --data-dir 时
    的 CLI 兜底默认，生产桌面包从不命中，会让 scan() 永远扫空目录。
    """
    env = os.environ.get("RUIJING_SKILLS_DIR")
    if env:
        return Path(env)
    # 桌面 sidecar：从 build_env 实际导出的信号反推 data_dir。
    if os.environ.get("DESKTOP_MODE") == "1" or getattr(sys, "frozen", False):
        # 首选 build_env 显式导出的 data_dir。
        data_dir = os.environ.get("SIDECAR_DATA_DIR")
        if not data_dir:
            # 退而从 workspaces 根反推（build_env 无条件设置，是更稳的真相源）。
            ws = os.environ.get("APAAS_WORKSPACE_ROOT")
            if ws:
                return Path(ws).parent / "skills"
            # 都没有时仅作为最后兜底（开发/裸跑），与 main() 的默认对齐。
            data_dir = str(Path.home() / ".ruijing-builder")
        return Path(data_dir) / "skills"
    return None


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


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self._root = root if root is not None else skills_root()

    def scan(self) -> list[Skill]:
        root = self._root
        if root is None or not root.exists():
            return []
        by_name: dict[str, Skill] = {}
        # platform 先扫，user 后扫覆盖同名（本地优先）。
        for source in ("platform", "user"):
            base = root / source
            if not base.is_dir():
                continue
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
        return list(by_name.values())

    def get(self, name: str) -> Skill | None:
        for s in self.scan():
            if s.name == name:
                return s
        return None

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
        "需要某个技能时, 先调 `use_skill(name)` 读它的完整说明再按其执行(脚本会在本机运行):",
    ]
    for s in skills:
        tag = "平台预置" if s.source == "platform" else "本地上传"
        lines.append(f"- {s.name}: {s.description}  [{tag}]")
    return "\n".join(lines)
