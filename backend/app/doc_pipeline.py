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


async def parse_document(
    text: str,
    llm_cfg: Optional[Dict[str, Any]] = None,
    on_progress: ProgressCallback = None,
) -> Dict[str, Any]:
    """解析上传的 markdown 文档，返回 preview config

    Args:
        text: markdown 原文
        llm_cfg: tenant 级 LLM 配置
        on_progress: 进度回调 async def(msg: str)

    Returns:
        {"type": "preview", "data": {...}, "parse_meta": {...}}
    """

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

    # 大文档优先保持单一 canonical config 源头。
    # 若规则解析后仍有失败模块，则直接切到分块 AI 兜底，避免把整篇超长文档再次塞进模块修复 prompt。
    if is_large_doc and result.failed_modules and _FALLBACK_TO_AI:
        await progress("[skeleton] 大文档存在未解析模块，切换到分块智能解析...")
        return await _fallback_ai_parse(
            text,
            llm_cfg,
            on_progress,
            parse_meta={
                "standard_score": score,
                "standard_level": detection.get("level"),
                "decision": decision,
                "fallback_used": True,
                "large_doc": True,
                "large_doc_strategy": "chunked_ai_fallback",
            },
        )

    # ── Step 3: 统一走模块级 LLM 修复（不再走 AI 全量兜底）────
    # 即使纯代码解析全部失败，也按模块并行调 LLM，比全量快
    if result.failed_modules:
        failed_list = ', '.join(result.failed_modules)
        if decision == "rewrite_first":
            await progress(f"[skeleton] 文档标准度较低（{score}分），按模块智能解析：{failed_list}")
        else:
            await progress(f"[skeleton] 修复非标准模块：{failed_list}")
        result = await _fix_failed_modules(text, result, llm_cfg, progress_cb=progress)
        # 修复完成后推送新修复的模块
        await _push_module_if_ready("roles", "roles", result.config.get("roles", []))
        await _push_module_if_ready("dicts", "dicts", result.config.get("dicts", []))
        await _push_module_if_ready("models", "models", result.config.get("models", []))
        await _push_module_if_ready("forms", "forms", result.config.get("forms", []))
        await _push_module_if_ready("permissions", "permissions", result.config.get("permissions", []))

    # ── Step 4: 关键模块仍然失败，最后才降级到全量 AI 解析 ────
    if result.has_critical_failure and _FALLBACK_TO_AI:
        await progress("[skeleton] 模块修复未成功，启用全量智能解析兜底...")
        return await _fallback_ai_parse(
            text,
            llm_cfg,
            on_progress,
            parse_meta={
                "standard_score": score,
                "standard_level": detection.get("level"),
                "decision": decision,
                "fallback_used": True,
                "large_doc": is_large_doc,
            },
        )

    # ── Step 6: 校验 & 修复 config ───────────────────────────
    await progress("[complete] 校验配置结构...")
    try:
        cleaned, warnings = validate_full_config(result.config)
        result.config = cleaned
        if warnings:
            result.errors.extend(warnings)
    except ValueError as e:
        logger.error(f"config 校验失败: {e}")
        if _FALLBACK_TO_AI:
            await progress("配置校验失败，启用智能解析兜底...")
            return await _fallback_ai_parse(
                text,
                llm_cfg,
                on_progress,
                parse_meta={
                    "standard_score": score,
                    "standard_level": detection.get("level"),
                    "decision": decision,
                    "fallback_used": True,
                    "large_doc": is_large_doc,
                },
            )

    await progress("解析完成")

    return {
        "type": "preview",
        "data": result.config,
        "parse_meta": {
            "standard_score": score,
            "standard_level": detection.get("level"),
            "decision": decision,
            "large_doc": is_large_doc,
            "large_doc_strategy": "rules_then_module_fix",
            "fixed_modules": sorted(result.failed_modules),
            "errors": result.errors[:20],  # 最多返回20条
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


async def _rewrite_full_doc(text: str, llm_cfg: Optional[Dict[str, Any]]) -> str:
    """整篇文档 LLM 标准化（score < 50 时使用）"""
    from app.module_standardizer import _llm_completion

    prompt = f"""{_REWRITE_PROMPT}

## 待标准化文档
{text}

## 输出（只输出标准 Markdown 文档，不要加任何解释）
"""
    try:
        return (await _llm_completion(
            messages=[{"role": "user", "content": prompt}],
            llm_cfg=llm_cfg,
            temperature=0.1,
            max_tokens=8192,
            timeout=180.0,
        )).strip()
    except Exception as e:
        logger.error(f"整篇文档标准化失败: {e}")
        return text


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


# ── 整篇标准化 prompt ─────────────────────────────────────────
_REWRITE_PROMPT = """\
你是一个 aPaaS 应用设计文档格式化助手。
请将下面这份设计文档整理成标准格式。

## 标准格式要求

文档必须包含以下章节（按顺序）：
1. ## 一、应用信息 — 表格：应用编码 | 应用名称
2. ## 二、角色列表 — 表格：角色编码 | 角色名称
3. ## 三、数据字典 — 每个字典一个 ### 子章节，表格：选项编码 | 选项名称
4. ## 四、数据模型 — 每个模型一个 ### 子章节（标注【主表】/【子表】），
   表格：字段编码 | 字段名称 | 存储类型 | 长度 | 字典编码 | 关联模型编码 | 关联显示字段编码 | 说明
5. ## 五、表单配置 — 每个表单一个 ### 子章节，
   主表字段表格：字段编码 | 字段名称 | 是否隐藏 | 是否只读 | 是否必填 | 是否列表展示 | 是否查询条件
   如存在子表，还需补充：
   - 子表区域表格：子表模型编码 | 子表模型名称 | 子表显示名称
   - 每个子表的字段表格：子表字段编码 | 子表字段名称 | 组件类型 | 是否必填 | 说明
6. ## 六、权限配置 — 若原文未定义，则明确写“当前文档未定义权限明细，本节不生成权限表。”
   若原文已定义，则表格：表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围

## 约束
- 编码字段：英文小写字母+下划线，字母开头（如 supplier_type）
- 不要丢失原文中的“长度/精度”“所属主表模型编码”“子表区域”“说明”
- 如果同一个模型被多个表单复用，允许生成多个表单子章节，但数据模型仍只保留一份
- 字段类型只能用：单据号/单行输入/多行输入/富文本/手机号码/电子邮箱/身份证号/超链接/
  数字/金额/日期时间/开关/附件上传/地理位置/地区地址/人员选择/部门选择/
  下拉单选/下拉多选/单选框/复选框/数据单选/数据选择/关联表单/子表
- 下拉单选/下拉多选/单选框/复选框 必须有对应字典（字典编码列填写）
- 数据单选/数据选择/关联表单/子表 必须有关联模型编码
- 数据范围只能：全公司/本部门/本部门及下属部门/仅本人
- 不要脑补，原文没有的内容不要新增
- 缺失信息留空
"""
