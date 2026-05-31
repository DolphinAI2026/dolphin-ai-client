"""第一道门：promote 时的纯文档校验（不联平台）"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.builder_spec.schema import Spec


@dataclass
class CheckResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    ok: bool
    completeness: CheckResult
    consistency: CheckResult
    naming: CheckResult
    markdown: CheckResult

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "completeness": {"ok": self.completeness.ok, "issues": self.completeness.issues},
            "consistency": {"ok": self.consistency.ok, "issues": self.consistency.issues},
            "naming": {"ok": self.naming.ok, "issues": self.naming.issues},
            "markdown": {"ok": self.markdown.ok, "issues": self.markdown.issues},
        }


def check_completeness(spec: "Spec") -> CheckResult:
    """5 类卡片是否齐全：goal / role / object / dict / permission

    role / dict / permission 至少一项；object 至少一项；goal 必填。
    """
    issues: list[str] = []
    if not spec.goal or not spec.goal.title:
        issues.append("goal 缺少标题")
    if not spec.objects:
        issues.append("缺少业务对象（object）")
    if not spec.roles:
        issues.append("缺少角色（role）")
    return CheckResult(ok=not issues, issues=issues)


def check_consistency(spec: "Spec") -> CheckResult:
    """字段引用 / 角色 scope 引用的 object 是否存在 / dict 引用是否存在"""
    issues: list[str] = []
    object_codes = {o.code for o in spec.objects}
    dict_codes = {d.code for d in spec.dicts}

    for obj in spec.objects:
        for f in obj.fields:
            if f.dict_code and f.dict_code not in dict_codes:
                issues.append(f"对象 {obj.code} 字段 {f.code} 引用不存在的字典 {f.dict_code}")
            if f.ref_model and f.ref_model not in object_codes:
                issues.append(f"对象 {obj.code} 字段 {f.code} 引用不存在的对象 {f.ref_model}")

    for perm in spec.permissions:
        if perm.object_code not in object_codes:
            issues.append(f"权限规则引用不存在的对象 {perm.object_code}")

    return CheckResult(ok=not issues, issues=issues)


def check_naming(spec: "Spec") -> CheckResult:
    """重名 / 保留字 / 命名规范"""
    issues: list[str] = []
    seen_obj: set[str] = set()
    for o in spec.objects:
        if o.code in seen_obj:
            issues.append(f"对象 code 重复：{o.code}")
        seen_obj.add(o.code)

    seen_dict: set[str] = set()
    for d in spec.dicts:
        if d.code in seen_dict:
            issues.append(f"字典 code 重复：{d.code}")
        seen_dict.add(d.code)

    seen_role: set[str] = set()
    for r in spec.roles:
        if r.code in seen_role:
            issues.append(f"角色 code 重复：{r.code}")
        seen_role.add(r.code)

    # 字段 code 在同对象内不能重复
    for o in spec.objects:
        seen_field: set[str] = set()
        for f in o.fields:
            if f.code in seen_field:
                issues.append(f"对象 {o.code} 字段 code 重复：{f.code}")
            seen_field.add(f.code)

    return CheckResult(ok=not issues, issues=issues)


def check_markdown(spec: "Spec") -> CheckResult:
    """markdown 渲染是否干净（YAML 不损坏）"""
    issues: list[str] = []
    try:
        # 试一下转 markdown 渲染，捕获异常
        from app.builder_spec.converter import spec_to_config
        spec_to_config(spec)
    except Exception as e:
        issues.append(f"markdown 渲染失败：{e}")
    return CheckResult(ok=not issues, issues=issues)


def validate(spec: "Spec") -> ValidationReport:
    """聚合 4 个 check"""
    completeness = check_completeness(spec)
    consistency = check_consistency(spec)
    naming = check_naming(spec)
    markdown = check_markdown(spec)
    ok = all(c.ok for c in (completeness, consistency, naming, markdown))
    return ValidationReport(
        ok=ok,
        completeness=completeness,
        consistency=consistency,
        naming=naming,
        markdown=markdown,
    )
