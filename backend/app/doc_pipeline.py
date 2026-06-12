"""文档解析主管道

完整链路（strict 模式）：
  标准度检测 → 纯代码解析 →（失败即抛 DocNotStandardError）→ 校验/规范化 →
  下拉↔字典确定性调和 → 汇总

不再做 LLM 兜底解析（旧的 AI 全量兜底已删，见 config_postprocess 迁移说明）。

对外只暴露一个函数：parse_document()
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.doc_standard_detector import detect
from app.doc_standard_parser import parse, ParseResult
from app.doc_section_splitter import split_sections
from app.config_validator import validate_full_config
from app.config_postprocess import reconcile_dropdown_dicts, downgrade_unbindable_dropdowns
from app.form_component_sanitizer import sync_form_components_with_model_fields

logger = logging.getLogger(__name__)

# 进度回调：msg=进度消息, batch=可选的批量数据(用于实时推送已解析模块)
ProgressCallback = Optional[Callable[..., Coroutine]]

_LARGE_DOC_CHAR_LIMIT = 40000


class DocNotStandardError(Exception):
    """strict 模式下文档未按模板规范，无法纯代码解析。

    用于"更新比对"这类必须保证 parse 结果确定性的场景：
    两次解析必须一致，因此不允许 LLM 兜底。
    """

    def __init__(
        self,
        failed_modules,
        errors=None,
        score: Optional[int] = None,
        decision: Optional[str] = None,
    ):
        self.failed_modules = sorted(list(failed_modules or []))
        self.errors = list(errors or [])
        self.score = score
        self.decision = decision
        modules_hint = ", ".join(self.failed_modules) or "(未知)"
        super().__init__(f"文档未按模板规范，以下模块无法纯代码解析：{modules_hint}")


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)
_SKIP_SECTION_TITLES = ("使用说明", "用户注意事项")
_STANDARD_SECTION_RE = re.compile(r"^##\s+(?:[一二三四五六七八九十]+[、.]?\s*)?.+")


def _strip_template_scaffolding(text: str) -> str:
    """去掉模板 frontmatter 和指导性章节，避免混入业务解析。"""
    cleaned = _FRONTMATTER_RE.sub("", text or "", count=1).strip()
    if not cleaned:
        return ""

    lines = cleaned.splitlines()
    output: list[str] = []
    skip_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and "模板" in stripped and not output:
            # 模板标题不是业务正文，直接丢弃
            continue

        if stripped.startswith("## "):
            skip_section = any(title in stripped for title in _SKIP_SECTION_TITLES)
            if skip_section:
                continue

        if skip_section:
            if _STANDARD_SECTION_RE.match(stripped) and not any(title in stripped for title in _SKIP_SECTION_TITLES):
                skip_section = False
            else:
                continue

        output.append(line)

    return "\n".join(output).strip()


def _detect_incomplete_modules(text: str, result: ParseResult) -> set[str]:
    """识别“有结果但明显不完整”的模块，交给模块级 LLM 补齐。

    目标不是严格判错，而是避免稀疏解析结果直接进入回显/构建。
    """
    sections = split_sections(text)
    incomplete: set[str] = set()

    def _section_len(key: str) -> int:
        return len(str(sections.get(key) or "").strip())

    roles = result.config.get("roles", []) or []
    dicts = result.config.get("dicts", []) or []
    models = result.config.get("models", []) or []
    forms = result.config.get("forms", []) or []
    permissions = result.config.get("permissions", []) or []

    total_model_fields = sum(len(m.get("fields", []) or []) for m in models)
    main_model_count = sum(1 for m in models if str(m.get("table_type", "")).strip() != "子表")

    if _section_len("roles") > 120 and len(roles) <= 1:
        incomplete.add("roles")

    if _section_len("dicts") > 160 and len(dicts) == 0:
        incomplete.add("dicts")

    # 模型章节很长却只解析出极少模型/字段，通常意味着规则解析只抓到了骨架。
    if _section_len("models") > 400 and (main_model_count == 0 or total_model_fields <= 5):
        incomplete.add("models")
    elif _section_len("models") > 1200 and main_model_count <= 1:
        incomplete.add("models")

    # forms 只检测"整段有内容但一个都没解析出"这种真失败场景。
    # 不再用 len(forms) < main_model_count 判定不完整——该判据基于"每个 model 都有 form"
    # 的业务假设，对"主表+子表/明细"的典型文档会产生误判：parser 其实已经正确解析，
    # 却会被误标为失败模块、最终触发 DocNotStandardError（strict 模式下任何失败模块都阻断）。
    if _section_len("forms") > 200 and len(forms) == 0:
        incomplete.add("forms")

    if _section_len("permissions") > 180 and len(permissions) == 0:
        incomplete.add("permissions")

    return incomplete


_AUTO_FIX_MARKERS = (
    "已自动",
    "已规范化",
    "已改为",
    "已降级",
    "已映射",
    "已移除",
    "自动同步",
)


def _split_parse_messages(messages: List[str]) -> tuple[List[str], List[str]]:
    """把解析消息拆成阻塞问题和自动修复记录。

    解析器会先记录“未知类型已降级”等 warning，随后 config 已经完成修复。
    这些信息对用户有价值，但不应继续作为待确认/阻塞错误暴露给后续助手。
    """
    errors: List[str] = []
    auto_fixes: List[str] = []
    for msg in messages or []:
        text = str(msg or "").strip()
        if not text:
            continue
        if any(marker in text for marker in _AUTO_FIX_MARKERS):
            auto_fixes.append(text)
        else:
            errors.append(text)
    return errors, auto_fixes


async def parse_document(
    text: str,
    llm_cfg: Optional[Dict[str, Any]] = None,
    on_progress: ProgressCallback = None,
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    """解析上传的 markdown 文档，返回 preview config

    Args:
        text: markdown 原文
        llm_cfg: tenant 级 LLM 配置（保留参数以兼容旧调用方，当前不再使用）
        on_progress: 进度回调 async def(msg: str)
        strict: 历史参数，保留接口兼容；A 严格模式下默认行为已等同于 strict=True
            （任何解析失败都抛 DocNotStandardError，不再做 LLM 兜底）。

    Returns:
        {"type": "preview", "data": {...}, "parse_meta": {...}}
    """
    del llm_cfg, strict  # 保留签名兼容；当前实现不再使用

    async def progress(msg: str, *, batch=None):
        if on_progress:
            await on_progress(msg, batch=batch)
        logger.info(f"[doc_pipeline] {msg}")

    text = _strip_template_scaffolding(text)
    is_large_doc = len(text) >= _LARGE_DOC_CHAR_LIMIT
    if is_large_doc:
        await progress(f"[skeleton] 文档较大（{len(text)} 字符），启用大文档解析策略...")

    # ── Step 1: 标准度检测 ────────────────────────────────────
    await progress("[skeleton] 检查文档标准度...")
    detection = detect(text)
    decision = detection["decision"]
    score = detection["score"]
    logger.info(f"文档标准度: score={score}, decision={decision}")

    # ── Step 2: 先尝试保真解析，避免低分文档在整篇标准化时丢信息 ───────
    await progress("[skeleton] 解析文档结构...")
    result = parse(text)
    incomplete_modules = _detect_incomplete_modules(text, result)
    if incomplete_modules:
        result.failed_modules.update(incomplete_modules)
        await progress(f"[skeleton] 检测到模块内容不完整，准备智能补齐：{', '.join(sorted(incomplete_modules))}")

    # 纯代码解析完成后，立即推送已成功的模块（毫秒级）
    _pushed_modules: set = set()

    async def _push_module_if_ready(module_key: str, phase_tag: str, data_list: list):
        """如果某模块有数据且尚未推送，立即推给前端"""
        if data_list and module_key not in _pushed_modules:
            _pushed_modules.add(module_key)
            await progress(f"[{phase_tag}] {module_key} 解析完成：{len(data_list)} 个", batch=data_list)

    await _push_module_if_ready("roles", "roles", result.config.get("roles", []))
    await _push_module_if_ready("dicts", "dicts", result.config.get("dicts", []))
    await _push_module_if_ready("models", "models", result.config.get("models", []))
    await _push_module_if_ready("forms", "forms", result.config.get("forms", []))
    await _push_module_if_ready("permissions", "permissions", result.config.get("permissions", []))

    # 通知前端哪些模块解析失败，需要 LLM 修复
    if result.failed_modules:
        failed_list = ', '.join(result.failed_modules)
        await progress(f"[skeleton] 部分模块需要智能修复：{failed_list}")

    # ── 纯代码解析路径（A 严格模式：上游已校验 score>=90，不再走 LLM 兜底）──
    # 上传入口的 detect() 已经把不标准文档挡在外面；走到这里的文档基本都能纯代码
    # 解析。如果仍有失败模块或校验不通过，直接抛 DocNotStandardError 让上游展示
    # 错误并引导用户回 AI-Chat 修订文档，而不是在 Builder 端做 AI 兜底。
    if result.failed_modules:
        raise DocNotStandardError(
            failed_modules=result.failed_modules,
            errors=result.errors,
            score=score,
            decision=decision,
        )

    # ── 校验 & 规范化 config ───────────────────────────────────
    await progress("[complete] 校验配置结构...")
    try:
        cleaned, warnings = validate_full_config(result.config)
        result.config = cleaned
        if warnings:
            result.errors.extend(warnings)
    except ValueError as e:
        logger.error(f"config 校验失败: {e}")
        raise DocNotStandardError(
            failed_modules=["config_validator"],
            errors=[str(e)],
            score=score,
            decision=decision,
        ) from e

    component_fixes = sync_form_components_with_model_fields(result.config)
    if component_fixes:
        for fix in component_fixes:
            result.errors.append(
                f"表单组件 '{fix['form']}.{fix['field']}' 已按模型字段类型 "
                f"'{fix['field_type']}' 从 '{fix['from']}' 自动同步为 '{fix['to']}'"
            )

    # ── 下拉↔字典 确定性调和 ───────────────────────────────────
    # 治大文档分块解析丢字典引用(详见
    # docs/research-0to1-dropdown-dict-rootcause-2026-06-05.md)。strict 管线要求确定性,
    # 所以这里只做「label==字典名」直连(不传 relink_fn / 不调 LLM), 仍连不上的一律降级
    # 单行输入(消除空的 选项1/2/3)。修复消息带「已映射」/「已降级」前缀, 经
    # _split_parse_messages 分流进 auto_fixes 透前端, 不阻塞。失败不阻断解析。
    await progress("[complete] 调和下拉↔字典绑定...")
    try:
        recon = reconcile_dropdown_dicts(result.config)  # relink_fn=None → 纯确定性
        if recon.get("linked_by_name"):
            result.errors.append(
                f"{recon['linked_by_name']} 个下拉组件按字典名匹配已映射回数据字典"
            )
        downgraded = downgrade_unbindable_dropdowns(result.config)
        for d in downgraded:
            label = d.get("label") or d.get("model_field") or "(未命名)"
            result.errors.append(
                f"下拉组件 '{label}' 无字典可绑，已降级为单行输入"
            )
    except Exception as e:
        logger.warning(f"[dropdown-dict] 确定性调和异常(不阻断): {e}")

    blocking_errors, auto_fixes = _split_parse_messages(result.errors)

    await progress("解析完成")

    return {
        "type": "preview",
        "data": result.config,
        "parse_meta": {
            "standard_score": score,
            "standard_level": detection.get("level"),
            "decision": decision,
            "large_doc": is_large_doc,
            "fixed_modules": [],
            "errors": blocking_errors[:20],
            "auto_fixes": auto_fixes[:50],
        },
    }
