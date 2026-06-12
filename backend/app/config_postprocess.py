"""配置后处理：code 规范化 / 图标补全 / 字典去重 + 下拉↔字典调和。

本模块的函数原样迁自 `app/ai_doc_parser.py`（该模块为 AI 兜底解析死岛，已删除）。
迁移背景：db2882ae(2026-06-05) 的「下拉↔字典调和」修复落在了 ai_doc_parser 这条
死路上；这族函数本身有真实价值（详见
docs/research-0to1-dropdown-dict-rootcause-2026-06-05.md），故抽出独立模块，既给活管线
(doc_pipeline.parse_document 接确定性调和) 复用，也保留给 repair 脚本 / 配置组装后处理用。

迁入函数（保持原函数名/签名/docstring）：
  - _sanitize_codes / _fill_icons / _dedup_dicts        ← config_assembler 后处理引用
  - find_unlinked_dropdown_components / reconcile_dropdown_dicts
  - _relink_dropdowns_via_llm / downgrade_unbindable_dropdowns
  - 私有 helper: _is_dropdown_component / _component_dict_ref / _dict_code_set /
    _reconcile_norm / _set_component_dict / _extract_json
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

from app.llm_client import LLMClient
from app.field_types import get_icon_map

logger = logging.getLogger(__name__)


# ================================================================
# 下拉↔字典 调和兜底 (治大文档分块解析丢下拉字典引用)
# ================================================================

_SELECT_COMPONENT_TYPES = ("FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT")
_SELECT_FIELD_TYPES = ("下拉单选", "下拉多选")


def _is_dropdown_component(c: dict) -> bool:
    ct = str(c.get("componentType") or c.get("type") or "")
    return ct in _SELECT_COMPONENT_TYPES or ct in _SELECT_FIELD_TYPES


def _component_dict_ref(c: dict) -> str:
    return str(c.get("dict") or c.get("dictCode") or "").strip()


def _dict_code_set(data: dict) -> set:
    return {str(d.get("code")).strip() for d in (data.get("dicts") or []) if d.get("code")}


def _reconcile_norm(s) -> str:
    return str(s or "").strip().lower().replace(" ", "")


def find_unlinked_dropdown_components(data: dict) -> List[dict]:
    """找出 dict 缺失 / 不解析到已定义字典的下拉组件。

    每项: {key, form_code, form_name, label, model_field, comp(原对象引用)}。
    注意: app5 实测 下拉性挂在【表单组件】componentType=FORM_SELECT_* 上, 模型字段反而是
    单行输入, 所以这里以组件为准, 不只看 model field。
    """
    if not isinstance(data, dict):
        return []
    codes = _dict_code_set(data)
    out: List[dict] = []
    for fo in (data.get("forms") or []):
        if not isinstance(fo, dict):
            continue
        for c in (fo.get("components") or fo.get("fields") or []):
            if not isinstance(c, dict) or not _is_dropdown_component(c):
                continue
            ref = _component_dict_ref(c)
            if ref and ref in codes:
                continue  # 已绑且能解析 — 不动
            mf = str(c.get("modelField") or "")
            label = c.get("label") or c.get("name") or (mf.split(".")[-1] if mf else "") or c.get("code") or ""
            out.append({
                "key": mf or f"{fo.get('code')}::{label}",
                "form_code": fo.get("code"),
                "form_name": fo.get("name"),
                "label": label,
                "model_field": mf,
                "comp": c,
            })
    return out


def _set_component_dict(comp: dict, code: str, data: dict, model_field: str) -> None:
    """给下拉组件绑 dict, 并同步回模型字段(field.dict + 类型修正为下拉), 保持一致。"""
    comp["dict"] = code
    comp["dictCode"] = code
    if model_field and "." in model_field:
        mcode, fcode = model_field.split(".", 1)
        for m in (data.get("models") or []):
            if str(m.get("code")) == mcode:
                for f in (m.get("fields") or []):
                    if str(f.get("code")) == fcode:
                        f["dict"] = code
                        if str(f.get("type") or "") not in _SELECT_FIELD_TYPES:
                            f["type"] = "下拉单选"
                        break
                break


def reconcile_dropdown_dicts(data: dict, *, relink_fn=None) -> dict:
    """解析后兜底: 把无字典引用的下拉组件连回已定义字典。

    ① 确定性: 组件 label 精确(或规范化后)== 某字典名 → 直连。
    ② 残余: 若给了 relink_fn(语义匹配, 通常是 LLM), 调它拿 {key: dict_code} 映射, 只接受
       解析到已定义字典的映射(防乱绑)。
    ③ 仍连不上的列进 unlinked, 交上层标记(不在这里阻断生成)。

    返回 {linked_by_name, linked_by_relink, unlinked:[{label,model_field,form_code}]}。
    """
    result = {"linked_by_name": 0, "linked_by_relink": 0, "unlinked": []}
    if not isinstance(data, dict):
        return result
    dicts = data.get("dicts") or []
    unlinked = find_unlinked_dropdown_components(data)
    if not unlinked:
        return result

    name_to_code: Dict[str, str] = {}
    for d in dicts:
        code = str(d.get("code") or "").strip()
        name = str(d.get("name") or "").strip()
        if code and name:
            name_to_code.setdefault(name, code)
            name_to_code.setdefault(_reconcile_norm(name), code)

    still: List[dict] = []
    for u in unlinked:
        code = name_to_code.get(u["label"]) or name_to_code.get(_reconcile_norm(u["label"]))
        if code:
            _set_component_dict(u["comp"], code, data, u["model_field"])
            result["linked_by_name"] += 1
        else:
            still.append(u)

    if still and relink_fn is not None and dicts:
        valid = _dict_code_set(data)
        try:
            mapping = relink_fn(still, dicts) or {}
        except Exception as e:  # relink 失败不阻断, 残余照常列 unlinked
            logger.warning(f"下拉字典 relink_fn 失败, 跳过: {e}")
            mapping = {}
        remaining: List[dict] = []
        for u in still:
            code = mapping.get(u["key"])
            if code and str(code).strip() in valid:
                _set_component_dict(u["comp"], str(code).strip(), data, u["model_field"])
                result["linked_by_relink"] += 1
            else:
                remaining.append(u)
        still = remaining

    result["unlinked"] = [
        {"label": u["label"], "model_field": u["model_field"], "form_code": u["form_code"]}
        for u in still
    ]
    return result


def downgrade_unbindable_dropdowns(data: dict) -> List[dict]:
    """把仍连不上字典的下拉组件降级成【单行输入】(用户决策 A: 消除空的 选项1/2/3 下拉)。

    根因: 大文档生成时, 文档里本是「单行输入」、无选项的字段, 被 LLM 按"状态/类型→下拉"规则
    误升级成下拉, 既无字典也无选项可补 → 渲染成 选项1/2/3 垃圾。无字典可绑就回归单行输入,
    合文档原意。同步把模型字段类型也改回单行输入 + 清 dict。返回被降级列表。
    """
    downgraded: List[dict] = []
    for u in find_unlinked_dropdown_components(data):
        c = u["comp"]
        c["componentType"] = "FORM_TEXT_INPUT"
        for k in ("dict", "dictCode", "chooseOptions", "dictionaryChooseOptions", "source", "chooseType", "multicolor"):
            c.pop(k, None)
        mf = u["model_field"]
        if mf and "." in mf:
            mcode, fcode = mf.split(".", 1)
            for m in (data.get("models") or []):
                if str(m.get("code")) == mcode:
                    for f in (m.get("fields") or []):
                        if str(f.get("code")) == fcode:
                            if str(f.get("type") or "") in _SELECT_FIELD_TYPES:
                                f["type"] = "单行输入"
                            f.pop("dict", None)
                            break
                    break
        downgraded.append({"label": u["label"], "model_field": mf, "form_code": u["form_code"]})
    return downgraded


async def _relink_dropdowns_via_llm(unlinked: List[dict], dicts: List[dict], llm_cfg: Optional[Dict] = None) -> Dict[str, str]:
    """语义重连线: 给 LLM 一批无字典下拉 + 一批已定义字典, 返回 {下拉key: 字典code}。

    确定性名字匹配兜不住的(如「标准分类」↔「标准类型」)交给它。保守: 没把握就别放进结果。
    """
    if not unlinked or not dicts:
        return {}
    client = LLMClient(api_key=llm_cfg.get("api_key"), base_url=llm_cfg.get("base_url"), model=llm_cfg.get("model")) if llm_cfg else LLMClient()
    fields_desc = [{"key": u["key"], "field": u["label"], "form": u.get("form_name")} for u in unlinked]
    dicts_desc = []
    for d in dicts:
        opts = [str(o.get("label") or o.get("valueName") or o.get("name") or o.get("value") or "")
                for o in (d.get("options") or d.get("items") or [])]
        dicts_desc.append({"code": d.get("code"), "name": d.get("name"), "options": [o for o in opts if o][:8]})
    sys = ("你是低代码配置专家。给定一批下拉字段和一批已定义的数据字典, 把每个下拉字段匹配到"
           "语义最贴切的那个字典。**只在有把握时匹配**, 没有语义贴切的就不要放进结果(宁缺毋滥, "
           "错绑比不绑更糟)。dict code 必须从给定字典列表里选, 不要编。只返回一个 JSON 对象 "
           "{下拉字段key: 字典code}, 不要任何解释/markdown 包裹。")
    user = (f"下拉字段(key 是稳定标识, 原样回填):\n{json.dumps(fields_desc, ensure_ascii=False)}\n\n"
            f"已定义字典:\n{json.dumps(dicts_desc, ensure_ascii=False)}\n\n返回 JSON:")
    try:
        r = await client.chat_completion(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            max_tokens=2048, timeout=60.0, temperature=0.0,
        )
        content = r["choices"][0]["message"]["content"]
        parsed = _extract_json(content) or {}
        if not isinstance(parsed, dict):
            return {}
        return {str(k): str(v) for k, v in parsed.items() if k and v}
    except Exception as e:
        logger.warning(f"[dropdown-dict] LLM relink 调用失败, 跳过: {e}")
        return {}


# ================================================================
# JSON 提取 & 后处理
# ================================================================

def _extract_json(content: str) -> Optional[Dict]:
    """从 AI 回复中提取 JSON 对象"""
    # 先尝试 ```json 代码块
    m = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试直接解析整段
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # 尝试找到第一个 { 到最后一个 }
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _sanitize_codes(data: Dict):
    """确保所有 code 字段为纯 ASCII 英文小写+下划线"""
    import hashlib

    def _fix(code: Optional[str], fallback: str = "") -> str:
        if not code:
            if fallback:
                return _fix(fallback)
            return ""
        if re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            return code.lower()
        ascii_part = re.sub(r'[^a-zA-Z0-9_]', '', code).lower()
        if len(ascii_part) >= 2:
            return ascii_part
        return 'c' + hashlib.md5(code.encode()).hexdigest()[:7]

    for r in (data.get("roles") or []):
        r["code"] = _fix(r.get("code"), r.get("name", ""))

    for d in (data.get("dicts") or []):
        d["code"] = _fix(d.get("code"), d.get("name", ""))
        for opt in (d.get("options") or []):
            opt["code"] = _fix(opt.get("code"), opt.get("name", ""))

    for m in (data.get("models") or []):
        m["code"] = _fix(m.get("code"), m.get("name", ""))
        for f in (m.get("fields") or []):
            f["code"] = _fix(f.get("code"), f.get("name", ""))
            if f.get("dict"):
                f["dict"] = _fix(f["dict"])
            if f.get("ref") and isinstance(f["ref"], dict):
                f["ref"]["model"] = _fix(f["ref"].get("model", ""))
                f["ref"]["field"] = _fix(f["ref"].get("field", ""))
            if f.get("sub_code"):
                f["sub_code"] = _fix(f["sub_code"])
            for sf in (f.get("sub_fields") or []):
                sf["code"] = _fix(sf.get("code"), sf.get("name", ""))
                if sf.get("dict"):
                    sf["dict"] = _fix(sf["dict"])
                if sf.get("ref") and isinstance(sf["ref"], dict):
                    sf["ref"]["model"] = _fix(sf["ref"].get("model", ""))
                    sf["ref"]["field"] = _fix(sf["ref"].get("field", ""))


_ICON_MAP = get_icon_map()


def _fill_icons(data: Dict):
    """始终用 _ICON_MAP 覆盖 icon 字段（LLM 可能返回中文类型名导致竖排）"""
    for m in (data.get("models") or []):
        for f in (m.get("fields") or []):
            f["icon"] = _ICON_MAP.get(f.get("type", ""), "T")
            for sf in (f.get("sub_fields") or []):
                sf["icon"] = _ICON_MAP.get(sf.get("type", ""), "T")


def _dedup_dicts(data: Dict):
    """去重字典（分段解析可能产生重复）"""
    seen = {}
    deduped = []
    for d in (data.get("dicts") or []):
        code = d.get("code", "")
        if code not in seen:
            seen[code] = d
            deduped.append(d)
        else:
            # 合并选项（保留更多选项的那个）
            existing = seen[code]
            if len(d.get("options", [])) > len(existing.get("options", [])):
                existing["options"] = d["options"]
    data["dicts"] = deduped
