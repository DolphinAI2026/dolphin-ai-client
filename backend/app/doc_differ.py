"""文档驱动增量开发 — 核心对比引擎

纯 Python 实现语义对比，基于 code 匹配模型/字典/角色/字段的增删改，
并生成可选择的 patch actions 列表。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from typing import Dict, List, Optional


def build_structure_index(text: str) -> dict:
    """纯 Python 按 ## / ### 标题拆分，生成章节索引"""
    sections: list[dict] = []
    lines = text.split('\n')
    current: dict | None = None
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,4})\s+(.+)', line)
        if m:
            if current:
                current['end_line'] = i - 1
                current['char_count'] = sum(len(lines[j]) for j in range(current['start_line'], i))
                sections.append(current)
            current = {
                'id': f's{len(sections) + 1}',
                'heading': m.group(2).strip(),
                'level': len(m.group(1)),
                'start_line': i,
                'end_line': len(lines) - 1,
            }
    if current:
        current['end_line'] = len(lines) - 1
        current['char_count'] = sum(len(lines[j]) for j in range(current['start_line'], len(lines)))
        sections.append(current)
    return {"sections": sections, "total_lines": len(lines), "total_chars": len(text)}


def semantic_diff(v1_config: dict, v2_config: dict) -> dict:
    """纯 Python 语义对比，基于 code 匹配"""
    diff: dict = {
        "added": {"models": [], "dicts": [], "roles": [], "fields": []},
        "modified": {"models": [], "dicts": [], "fields": []},
        "removed": {"models": [], "dicts": [], "roles": [], "fields": []},
    }

    # ── Models 对比 ──
    v1_models = {m.get("code", ""): m for m in v1_config.get("models", []) if m.get("code")}
    v2_models = {m.get("code", ""): m for m in v2_config.get("models", []) if m.get("code")}

    for code, v2m in v2_models.items():
        if code not in v1_models:
            diff["added"]["models"].append({
                "name": v2m.get("name", ""), "code": code,
                "field_count": len(v2m.get("fields", [])),
            })
        else:
            v1m = v1_models[code]
            field_changes = _diff_fields(v1m.get("fields", []), v2m.get("fields", []))
            if field_changes["added"] or field_changes["modified"] or field_changes["removed"]:
                changes_desc = []
                if field_changes["added"]:
                    changes_desc.append(f"新增{len(field_changes['added'])}个字段")
                if field_changes["modified"]:
                    changes_desc.append(f"修改{len(field_changes['modified'])}个字段")
                if field_changes["removed"]:
                    changes_desc.append(f"删除{len(field_changes['removed'])}个字段")
                diff["modified"]["models"].append({
                    "name": v2m.get("name", ""), "code": code,
                    "changes": "，".join(changes_desc),
                    "field_changes": field_changes,
                })

    for code, v1m in v1_models.items():
        if code not in v2_models:
            diff["removed"]["models"].append({"name": v1m.get("name", ""), "code": code})

    # ── Dicts 对比 ──
    v1_dicts = {d.get("code", ""): d for d in v1_config.get("dicts", []) if d.get("code")}
    v2_dicts = {d.get("code", ""): d for d in v2_config.get("dicts", []) if d.get("code")}

    for code, v2d in v2_dicts.items():
        if code not in v1_dicts:
            diff["added"]["dicts"].append({"name": v2d.get("name", ""), "code": code})
        else:
            v1d = v1_dicts[code]
            v1_opts = {o.get("code", ""): o for o in v1d.get("options", []) if isinstance(o, dict)}
            v2_opts = {o.get("code", ""): o for o in v2d.get("options", []) if isinstance(o, dict)}
            new_opts = [o for c, o in v2_opts.items() if c not in v1_opts]
            del_opts = [o for c, o in v1_opts.items() if c not in v2_opts]
            if new_opts or del_opts:
                changes = f"新增{len(new_opts)}选项" if new_opts else ""
                if del_opts:
                    changes += ("，" if changes else "") + f"删除{len(del_opts)}选项"
                diff["modified"]["dicts"].append({
                    "name": v2d.get("name", ""), "code": code, "changes": changes,
                })

    for code, v1d in v1_dicts.items():
        if code not in v2_dicts:
            diff["removed"]["dicts"].append({"name": v1d.get("name", ""), "code": code})

    # ── Roles 对比 ──
    v1_roles = {r.get("code", ""): r for r in v1_config.get("roles", []) if r.get("code")}
    v2_roles = {r.get("code", ""): r for r in v2_config.get("roles", []) if r.get("code")}
    for code, r in v2_roles.items():
        if code not in v1_roles:
            diff["added"]["roles"].append({"name": r.get("name", ""), "code": code})
    for code, r in v1_roles.items():
        if code not in v2_roles:
            diff["removed"]["roles"].append({"name": r.get("name", ""), "code": code})

    return diff


def _diff_fields(v1_fields: list, v2_fields: list) -> dict:
    """对比两个字段列表，只比较核心业务属性（type/dict/ref）"""
    v1 = {f.get("code", ""): f for f in v1_fields if f.get("code")}
    v2 = {f.get("code", ""): f for f in v2_fields if f.get("code")}

    modified = []
    for c in v2:
        if c in v1:
            f1, f2 = v1[c], v2[c]
            # 只比较核心属性，忽略 required/icon/comment 等 AI 不稳定输出
            t1 = f1.get("type", "")
            t2 = f2.get("type", "")
            d1 = f1.get("dict", "") or ""
            d2 = f2.get("dict", "") or ""
            r1 = str(f1.get("ref", "") or "")
            r2 = str(f2.get("ref", "") or "")
            if (t1 and t2 and t1 != t2) or d1 != d2 or r1 != r2:
                modified.append({"old": f1, "new": f2})

    return {
        "added": [f for c, f in v2.items() if c not in v1],
        "modified": modified,
        "removed": [f for c, f in v1.items() if c not in v2],
    }


def diff_to_actions(diff: dict, v2_config: dict) -> list:
    """将语义差异转为 patch actions"""
    actions: list[dict] = []

    # 新增模型
    v2_models = {m.get("code", ""): m for m in v2_config.get("models", []) if m.get("code")}
    for item in diff["added"]["models"]:
        model = v2_models.get(item["code"])
        if model:
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "add_model",
                "value": model,
                "description": f"新增模型：{item['name']}（{item.get('field_count', 0)}个字段）",
            })

    # 修改模型的字段
    for item in diff["modified"]["models"]:
        fc = item.get("field_changes", {})
        for f in fc.get("added", []):
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "add_field",
                "model": item["name"], "value": f,
                "description": f"新增字段：{item['name']}.{f.get('name', '')}",
            })
        for f in fc.get("modified", []):
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "update_field",
                "model": item["name"], "target": f["old"].get("name", ""), "value": f["new"],
                "description": f"修改字段：{item['name']}.{f['new'].get('name', '')}",
            })
        for f in fc.get("removed", []):
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "remove_field",
                "model": item["name"], "target": f.get("name", ""),
                "description": f"删除字段：{item['name']}.{f.get('name', '')}",
            })

    # 删除模型
    for item in diff["removed"]["models"]:
        actions.append({
            "id": str(uuid.uuid4())[:8], "selected": True, "op": "remove_model",
            "target": item["name"],
            "description": f"删除模型：{item['name']}",
        })

    # 新增/修改/删除字典
    v2_dicts = {d.get("code", ""): d for d in v2_config.get("dicts", []) if d.get("code")}
    for item in diff["added"]["dicts"]:
        d = v2_dicts.get(item["code"])
        if d:
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "add_dict",
                "value": d,
                "description": f"新增字典：{item['name']}",
            })
    for item in diff["modified"]["dicts"]:
        d = v2_dicts.get(item["code"])
        if d:
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "update_dict",
                "target": item["name"], "value": d,
                "description": f"修改字典：{item['name']}（{item.get('changes', '')}）",
            })
    for item in diff["removed"]["dicts"]:
        actions.append({
            "id": str(uuid.uuid4())[:8], "selected": True, "op": "remove_dict",
            "target": item["name"],
            "description": f"删除字典：{item['name']}",
        })

    # 角色
    v2_roles = {r.get("code", ""): r for r in v2_config.get("roles", []) if r.get("code")}
    for item in diff["added"]["roles"]:
        r = v2_roles.get(item["code"])
        if r:
            actions.append({
                "id": str(uuid.uuid4())[:8], "selected": True, "op": "add_role",
                "value": r,
                "description": f"新增角色：{item['name']}",
            })
    for item in diff["removed"]["roles"]:
        actions.append({
            "id": str(uuid.uuid4())[:8], "selected": True, "op": "remove_role",
            "target": item["name"],
            "description": f"删除角色：{item['name']}",
        })

    return actions


def apply_actions_to_config(config: dict, actions: list) -> dict:
    """后端执行 patch actions，与前端 applyPatch 对等"""
    config = deepcopy(config)
    for action in actions:
        if not action.get("selected", True):
            continue
        op = action["op"]
        if op == "add_model":
            config.setdefault("models", []).append(action["value"])
        elif op == "remove_model":
            config["models"] = [m for m in config.get("models", []) if m.get("name") != action.get("target")]
        elif op == "add_field":
            for m in config.get("models", []):
                if m.get("name") == action.get("model"):
                    m.setdefault("fields", []).append(action["value"])
        elif op == "update_field":
            for m in config.get("models", []):
                if m.get("name") == action.get("model"):
                    for i, f in enumerate(m.get("fields", [])):
                        if f.get("name") == action.get("target"):
                            m["fields"][i] = action["value"]
        elif op == "remove_field":
            for m in config.get("models", []):
                if m.get("name") == action.get("model"):
                    m["fields"] = [f for f in m.get("fields", []) if f.get("name") != action.get("target")]
        elif op == "add_dict":
            config.setdefault("dicts", []).append(action["value"])
        elif op == "update_dict":
            for i, d in enumerate(config.get("dicts", [])):
                if d.get("name") == action.get("target"):
                    config["dicts"][i] = action["value"]
        elif op == "remove_dict":
            config["dicts"] = [d for d in config.get("dicts", []) if d.get("name") != action.get("target")]
        elif op == "add_role":
            config.setdefault("roles", []).append(action["value"])
        elif op == "remove_role":
            config["roles"] = [r for r in config.get("roles", []) if r.get("name") != action.get("target")]
    return config


def compute_hash(text: str) -> str:
    """计算文本的 SHA256 哈希"""
    return hashlib.sha256(text.encode()).hexdigest()
