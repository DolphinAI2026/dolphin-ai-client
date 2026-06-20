"""多端请求分解为 N 个 aPaaS 单扩展产物的计划解析 + LLM 调用。

源自招聘系统 dogfood:多端/多页请求不该塞单页或拒绝,而是分解成多个独立产物。
parse_decomposition 纯函数(可单测);decompose 加一次 LLM 调用 + 失败回落 None(永不更糟)。
"""
from __future__ import annotations

import json
import logging
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class Artifact(TypedDict):
    name: str
    side: str          # "admin" | "user"
    scene: str         # 单产物 scene 值
    sub_request: str   # 聚焦自然语言, 喂给一次首轮 run_coding_pipeline


def parse_decomposition(
    raw_json: str, available_scenes: set[str], max_artifacts: int = 4
) -> Optional[list[Artifact]]:
    """解析/校验 LLM 分解输出。非法/不值得分解(<2 有效项)→ None。"""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    raw_arts = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(raw_arts, list):
        return None
    out: list[Artifact] = []
    for a in raw_arts:
        if not isinstance(a, dict):
            continue
        scene = str(a.get("scene") or "").strip()
        sub = str(a.get("sub_request") or "").strip()
        if scene not in available_scenes or not sub:
            continue
        out.append(Artifact(
            name=str(a.get("name") or sub[:20]).strip(),
            side=str(a.get("side") or "admin").strip(),
            scene=scene, sub_request=sub,
        ))
        if len(out) >= max_artifacts:
            break
    return out if len(out) >= 2 else None


_DECOMPOSE_PROMPT = """你是 aPaaS 低代码平台的需求分解助手。把用户需求分解成多个**独立的单页面/单组件 aPaaS 扩展产物**。

可用 scene(每个产物必须选一个): form-list(列表+CRUD 管理页) / menu-page(菜单聚合页) / mobile-page(移动端页面) / form-page(单表单页)。

规则:
- 只有当需求明显是「多端(管理端+用户端)/多个独立页面/完整业务系统」时才分解成 2-4 个产物;否则返回 {"artifacts":[]}(交给单产物流程)。
- 管理端(HR/后台)用 form-list(每个核心实体一个列表管理页, 或合并相关实体)。用户端(求职者/前台/移动)用 mobile-page。
- 每个产物给一个**聚焦、能独立开发**的 sub_request(自然语言, 只描述这一个产物)。

示例输入: "做招聘系统, 管理端 HR 管职位/候选人/投递/面试, 用户端求职者浏览职位+投递"
示例输出: {"artifacts":[
  {"name":"招聘管理后台","side":"admin","scene":"form-list","sub_request":"做一个招聘管理列表页, 管理职位、候选人、投递、面试四类数据的增删改查"},
  {"name":"求职者端","side":"user","scene":"mobile-page","sub_request":"做一个求职者移动端页面, 浏览职位列表、投递简历、查看我的投递状态"}
]}
反例输入: "做一个登录页" → 输出: {"artifacts":[]}

只输出 JSON, 不要解释。用户需求:
"""


def _call_decompose_llm(prompt: str, llm_cfg: dict) -> str:
    """同步发一次 chat completion 返回正文。失败抛异常(由 decompose 捕获回落)。"""
    import httpx

    base = llm_cfg["base_url"].rstrip("/")
    resp = httpx.post(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"},
        json={"model": llm_cfg["model"], "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 1200, "temperature": 0},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def decompose(
    requirement: str, llm_cfg: dict, available_scenes: set[str]
) -> Optional[list[Artifact]]:
    """多端请求 → 产物计划;任何失败/不适用 → None(回落单产物)。"""
    try:
        raw = _call_decompose_llm(_DECOMPOSE_PROMPT + (requirement or ""), llm_cfg)
    except Exception as exc:  # noqa: BLE001 — LLM 失败一律回落, 不中断
        logger.warning("decompose LLM 失败, 回落单产物: %r", exc)
        return None
    raw = (raw or "").strip()
    if raw.startswith("```"):
        # 剥 ```json ... ``` 围栏
        inner = raw[3:]
        if "```" in inner:
            inner = inner.split("```", 1)[0]
        raw = inner[4:].strip() if inner.lstrip().lower().startswith("json") else inner.strip()
    return parse_decomposition(raw, available_scenes)

