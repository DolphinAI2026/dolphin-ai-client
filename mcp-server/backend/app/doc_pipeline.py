"""文档解析主管道

完整链路：
  标准度检测 → 纯代码解析 → 失败模块 LLM 修复 → 再解析 → 汇总

对外只暴露一个函数：parse_document()
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.doc_standard_detector import detect
from app.doc_standard_parser import parse, ParseResult
from app.doc_section_splitter import split_sections
from app.module_standardizer import standardize_module
from app.config_validator import validate_full_config

logger = logging.getLogger(__name__)

# 进度回调：msg=进度消息, batch=可选的批量数据(用于实时推送已解析模块)
ProgressCallback = Optional[Callable[..., Coroutine]]

# 当模型解析彻底失败时，降级使用旧的 AI 全量解析
_FALLBACK_TO_AI = True
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

    dicts = result.config.get("dicts", []) or []
    models = result.config.get("models", []) or []
    forms = result.config.get("forms", []) or []
    permissions = result.config.get("permissions", []) or []

    total_model_fields = sum(len(m.get("fields", []) or []) for m in models)
    main_model_count = sum(1 for m in models if str(m.get("table_type", "")).strip() != "子表")

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
    # 但会被误拖进 _fallback_ai_parse（3-5 分钟），反而被 AI 搞乱（例如把 5.1 表单清单
    # 也塞进 models）。保留 AI 兜底只用于 parser 真正失败的情况。
    if _section_len("forms") > 200 and len(forms) == 0:
        incomplete.add("forms")

    if _section_len("permissions") > 180 and len(permissions) == 0:
        incomplete.add("permissions")

    return incomplete


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
            "errors": result.errors[:20],
        },
    }


async def _fix_failed_modules(
    original_text: str,
    result: ParseResult,
    llm_cfg: Optional[Dict[str, Any]],
    progress_cb=None,
) -> ParseResult:
    """对失败模块并行调用 LLM 标准化，然后重新解析"""
    import asyncio
    from app.doc_parsers import roles as roles_parser
    from app.doc_parsers import dicts as dicts_parser
    from app.doc_parsers import models as models_parser
    from app.doc_parsers import forms as forms_parser
    from app.doc_parsers import permissions as permissions_parser

    sections = split_sections(original_text)
    # 找不到具体章节时，把整篇文档作为该模块的输入
    modules_to_fix = list(result.failed_modules)

    async def fix_one(module: str, models_context: str = None) -> tuple:
        section_text = sections.get(module) or original_text
        logger.info(f"LLM 修复模块: {module} (section={'found' if sections.get(module) else 'full_doc'})")
        if progress_cb:
            await progress_cb(f"[{module}] 正在智能解析...")
        standardized = await standardize_module(module, section_text, llm_cfg, models_context=models_context)
        if progress_cb:
            await progress_cb(f"[{module}] 智能解析完成")
        return module, standardized

    standardized_map: Dict[str, Any] = {}

    # Step 1: models + 非 forms 模块全部并行跑（roles/dicts/permissions 不依赖 models）
    independent_modules = [m for m in modules_to_fix if m not in ("models", "forms")]
    parallel_tasks = [fix_one(m) for m in independent_modules]
    if "models" in modules_to_fix:
        parallel_tasks.append(fix_one("models"))

    if parallel_tasks:
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        for item in parallel_results:
            if isinstance(item, Exception):
                logger.error(f"LLM 并行修复异常: {item}")
                continue
            module, standardized = item
            standardized_map[module] = standardized

    # models 修复后立即解析，供 forms 使用
    if "models" in standardized_map:
        try:
            parsed_models, errs = models_parser.parse(standardized_map["models"])
            if parsed_models:
                result.config["models"] = parsed_models
                result.failed_modules.discard("models")
                result.errors.extend(errs)
        except Exception as e:
            logger.error(f"LLM 修复后重新解析 models 失败: {e}")

    # Step 2: forms 单独跑（依赖 models 上下文）
    if "forms" in modules_to_fix:
        models_ctx = standardized_map.get("models", "")
        item = await fix_one("forms", models_context=models_ctx)
        _, standardized = item
        standardized_map["forms"] = standardized

    for module in ["roles", "dicts", "forms", "permissions"]:  # models 已在 Step 1 处理
        standardized = standardized_map.get(module)
        if standardized is None:
            continue
        try:
            if module == "roles":
                roles, errs = roles_parser.parse(standardized)
                if roles:
                    result.config["roles"] = roles
                    result.failed_modules.discard(module)
                    result.errors.extend(errs)

            elif module == "dicts":
                dicts, errs = dicts_parser.parse(standardized)
                if dicts:
                    result.config["dicts"] = dicts
                    result.failed_modules.discard(module)
                    result.errors.extend(errs)

            elif module == "forms":
                forms, errs = forms_parser.parse(standardized, result.config.get("models", []))
                if forms:
                    result.config["forms"] = forms
                    result.failed_modules.discard(module)
                    result.errors.extend(errs)

            elif module == "permissions":
                role_codes = {r["code"] for r in result.config.get("roles", [])}
                permissions, errs = permissions_parser.parse(standardized, role_codes)
                if permissions:
                    result.config["permissions"] = permissions
                    result.failed_modules.discard(module)
                    result.errors.extend(errs)

        except Exception as e:
            logger.error(f"LLM 修复后重新解析 {module} 失败: {e}")

    return result


async def _fallback_ai_parse(
    text: str,
    llm_cfg: Optional[Dict[str, Any]],
    on_progress: ProgressCallback,
    parse_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """降级：使用旧的 AI 全量解析器"""
    from app.ai_doc_parser import parse_doc_with_ai
    logger.warning("降级使用 AI 全量解析器")
    result = await parse_doc_with_ai(
        text,
        llm_cfg=llm_cfg,
        on_progress=on_progress,
    )
    if isinstance(result, dict):
        merged_meta = dict(parse_meta or {})
        if isinstance(result.get("parse_meta"), dict):
            merged_meta.update(result["parse_meta"])
        if merged_meta:
            result["parse_meta"] = merged_meta
    return result
