"""文档解析主管道

完整链路：
  标准度检测 → 纯代码解析 → 失败模块 LLM 修复 → 再解析 → 汇总

对外只暴露一个函数：parse_document()
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.doc_standard_detector import detect
from app.doc_standard_parser import parse, ParseResult
from app.doc_section_splitter import split_sections
from app.module_standardizer import standardize_module
from app.config_validator import validate_full_config

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str], Coroutine]]

# 当模型解析彻底失败时，降级使用旧的 AI 全量解析
_FALLBACK_TO_AI = True


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

    async def progress(msg: str):
        if on_progress:
            await on_progress(msg)
        logger.info(f"[doc_pipeline] {msg}")

    # ── Step 1: 标准度检测 ────────────────────────────────────
    await progress("[skeleton] 检查文档标准度...")
    detection = detect(text)
    decision = detection["decision"]
    score = detection["score"]
    logger.info(f"文档标准度: score={score}, decision={decision}")

    # ── Step 2: 先尝试保真解析，避免低分文档在整篇标准化时丢信息 ───────
    await progress("[skeleton] 解析文档结构...")
    result = parse(text)
    await progress("[dicts] 解析数据字典...")
    await progress("[models] 解析数据模型及表单...")
    await progress("[permissions] 解析权限配置...")

    # ── Step 3: 确实解析不出来时，再整篇重写 ─────────────────────
    if decision == "rewrite_first" and (
        result.has_critical_failure
        or not result.config.get("models")
        or not result.config.get("forms")
    ):
        await progress(f"[skeleton] 文档标准度较低（{score}分），正在智能标准化...")
        text = await _rewrite_full_doc(text, llm_cfg)
        detection = detect(text)
        logger.info(f"标准化后重新检测: score={detection['score']}")
        await progress("[skeleton] 重新解析标准化文档...")
        result = parse(text)
        await progress("[dicts] 解析数据字典...")
        await progress("[models] 解析数据模型及表单...")
        await progress("[permissions] 解析权限配置...")

    # ── Step 4: 失败模块 LLM 修复（hybrid_fallback 或有失败模块时）──
    if result.failed_modules:
        await progress(f"[models] 修复非标准模块：{', '.join(result.failed_modules)}...")
        result = await _fix_failed_modules(text, result, llm_cfg)

    # ── Step 5: 关键模块仍然失败，降级到全量 AI 解析 ──────────
    if result.has_critical_failure and _FALLBACK_TO_AI:
        await progress("[skeleton] 结构解析失败，启用智能解析兜底...")
        return await _fallback_ai_parse(text, llm_cfg, on_progress)

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
            return await _fallback_ai_parse(text, llm_cfg, on_progress)

    await progress("解析完成")

    return {
        "type": "preview",
        "data": result.config,
        "parse_meta": {
            "standard_score": score,
            "decision": decision,
            "fixed_modules": result.failed_modules,
            "errors": result.errors[:20],  # 最多返回20条
        },
    }


async def _fix_failed_modules(
    original_text: str,
    result: ParseResult,
    llm_cfg: Optional[Dict[str, Any]],
) -> ParseResult:
    """对失败模块并行调用 LLM 标准化，然后重新解析"""
    import asyncio
    from app.doc_parsers import roles as roles_parser
    from app.doc_parsers import dicts as dicts_parser
    from app.doc_parsers import models as models_parser
    from app.doc_parsers import forms as forms_parser
    from app.doc_parsers import permissions as permissions_parser

    sections = split_sections(original_text)
    modules_to_fix = [m for m in result.failed_modules if sections.get(m)]

    async def fix_one(module: str, models_context: str = None) -> tuple:
        section_text = sections[module]
        logger.info(f"LLM 修复模块: {module}")
        standardized = await standardize_module(module, section_text, llm_cfg, models_context=models_context)
        return module, standardized

    standardized_map: Dict[str, Any] = {}

    # Step 1: models 优先单独跑（forms 依赖它的编码）
    if "models" in modules_to_fix:
        item = await fix_one("models")
        _, std = item
        standardized_map["models"] = std
        # 立即解析 models，供后续 forms LLM 使用
        try:
            parsed_models, errs = models_parser.parse(std)
            if parsed_models:
                result.config["models"] = parsed_models
                result.failed_modules.discard("models")
                result.errors.extend(errs)
        except Exception as e:
            logger.error(f"LLM 修复后重新解析 models 失败: {e}")
        remaining = [m for m in modules_to_fix if m != "models"]
    else:
        remaining = list(modules_to_fix)

    # Step 2: 其余模块并行，forms 带 models 上下文
    models_ctx = standardized_map.get("models", "")

    async def fix_remaining(module: str) -> tuple:
        ctx = models_ctx if module == "forms" else None
        return await fix_one(module, models_context=ctx)

    if remaining:
        parallel_results = await asyncio.gather(*[fix_remaining(m) for m in remaining], return_exceptions=True)
        for item in parallel_results:
            if isinstance(item, Exception):
                logger.error(f"LLM 并行修复异常: {item}")
                continue
            module, standardized = item
            standardized_map[module] = standardized

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
) -> Dict[str, Any]:
    """降级：使用旧的 AI 全量解析器"""
    from app.ai_doc_parser import parse_doc_with_ai
    logger.warning("降级使用 AI 全量解析器")
    return await parse_doc_with_ai(
        text,
        llm_cfg=llm_cfg,
        on_progress=on_progress,
    )


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
