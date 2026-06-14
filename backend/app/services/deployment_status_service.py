"""部署真相归一服务(Phase 2D)。

契约见 `docs/architecture/deployment-truth.md`。把散落在 6 个模块的"七级部署真相"
归一成单一可查询的状态对象,杜绝 agent 把"build 过"说成"已发布"。

七级(逐级独立,不可跳级宣称):
  1 workspace_changed          本地工作区有改动            AI Builder 本地 FS
  2 build_passed               本地 build 成功(可缓存)    AI Builder 构建观测
  3 package_exists             生成了 zip/包(本地 FS)
  4 uploaded_to_asset_library  上传到资产库(可缓存)
  5 bound_to_app               绑定到某 aPaaS 应用          apaas_app_id 绑定记录
  6 deployed_to_apaas          部署进 aPaaS                 aPaaS 动作结果
  7 republished_visible        republish 后运行态可见       aPaaS live / 短 TTL

三条铁律(本服务的存在理由):
  - "build 过"(级2)≠ "已发布"(级6/7)。
  - "上传资产库"(级4)≠ "已 republish"(级7)。
  - aPaaS 侧真相(级6-7)绝不信缓存 —— 要 live 核实(apaas_truth_is_live)才能断言已发布。

本服务**只读**,不写任何状态、不改现有路由响应结构;它是 UI 和 agent 断言上线态前
应当查询的唯一真相来源。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class DeploymentLevel(IntEnum):
    """七级真相的序号。NONE = 什么都没观测到。"""

    NONE = 0
    WORKSPACE_CHANGED = 1
    BUILD_PASSED = 2
    PACKAGE_EXISTS = 3
    UPLOADED_TO_ASSET_LIBRARY = 4
    BOUND_TO_APP = 5
    DEPLOYED_TO_APAAS = 6
    REPUBLISHED_VISIBLE = 7


class Observation(str, Enum):
    """单级真相的三态:确认 / 否定 / 未观测。

    UNKNOWN 与 DENIED 必须区分:"没去查 aPaaS"(unknown)不等于
    "查了 aPaaS 发现没发布"(denied)。前者不能宣称任何上线态。
    """

    CONFIRMED = "confirmed"
    DENIED = "denied"
    UNKNOWN = "unknown"


# 按 DeploymentLevel 顺序排列的字段名(级1→级7)。
_LEVEL_FIELDS: list[tuple[DeploymentLevel, str]] = [
    (DeploymentLevel.WORKSPACE_CHANGED, "workspace_changed"),
    (DeploymentLevel.BUILD_PASSED, "build_passed"),
    (DeploymentLevel.PACKAGE_EXISTS, "package_exists"),
    (DeploymentLevel.UPLOADED_TO_ASSET_LIBRARY, "uploaded_to_asset_library"),
    (DeploymentLevel.BOUND_TO_APP, "bound_to_app"),
    (DeploymentLevel.DEPLOYED_TO_APAAS, "deployed_to_apaas"),
    (DeploymentLevel.REPUBLISHED_VISIBLE, "republished_visible"),
]

# 属于 aPaaS 侧真相的级别(缓存不可信)。
_APAAS_SIDE_LEVELS = {
    DeploymentLevel.DEPLOYED_TO_APAAS,
    DeploymentLevel.REPUBLISHED_VISIBLE,
}


@dataclass
class DeploymentStatus:
    """归一后的七级真相对象。

    每级是独立的 tri-state 观测,默认 UNKNOWN(未观测)。`apaas_truth_is_live`
    标记级6-7 的观测是否来自 live 拉取(而非缓存的历史记录);它是宣称
    "已发布"的硬前提。
    """

    workspace_changed: Observation = Observation.UNKNOWN
    build_passed: Observation = Observation.UNKNOWN
    package_exists: Observation = Observation.UNKNOWN
    uploaded_to_asset_library: Observation = Observation.UNKNOWN
    bound_to_app: Observation = Observation.UNKNOWN
    deployed_to_apaas: Observation = Observation.UNKNOWN
    republished_visible: Observation = Observation.UNKNOWN
    # 级6-7 是否经 live 核实(非缓存)。绝不信缓存的"已发布"。
    apaas_truth_is_live: bool = False

    def _obs(self, level: DeploymentLevel) -> Observation:
        for lvl, field in _LEVEL_FIELDS:
            if lvl == level:
                return getattr(self, field)
        return Observation.UNKNOWN

    def highest_confirmed_level(self) -> DeploymentLevel:
        """最高的 *已确认* 级别(逐级独立,取 confirmed 里的最大序号)。"""
        highest = DeploymentLevel.NONE
        for lvl, field in _LEVEL_FIELDS:
            if getattr(self, field) == Observation.CONFIRMED:
                highest = lvl
        return highest

    def can_claim_published(self) -> bool:
        """是否可以断言"已发布/已上线"。

        硬前提:级6 或级7 为 CONFIRMED **且** 来自 live 核实。
        缓存的级6/7、UNKNOWN、DENIED 一律不得宣称(三条铁律)。
        """
        if not self.apaas_truth_is_live:
            return False
        return (
            self.deployed_to_apaas == Observation.CONFIRMED
            or self.republished_visible == Observation.CONFIRMED
        )

    def summary_phrase(self) -> str:
        """给 agent 用的人话摘要 —— 只陈述核实到的级别,不夸大。"""
        if self.can_claim_published():
            if self.republished_visible == Observation.CONFIRMED:
                return "已发布,且 republish 运行态 live 可见。"
            return "已发布(aPaaS live 核实)。"

        highest = self.highest_confirmed_level()
        # 级6/7 已确认但仅缓存 → 明确说明"未 live 核实"。
        if highest in _APAAS_SIDE_LEVELS and not self.apaas_truth_is_live:
            return "本地记录显示曾成功部署,但当前发布态未经 live 核实,不能断言已发布。"

        phrases = {
            DeploymentLevel.NONE: "尚无任何部署观测。",
            DeploymentLevel.WORKSPACE_CHANGED: "工作区有本地改动,尚未 build,未发布。",
            DeploymentLevel.BUILD_PASSED: "已 build 通过,但尚未打包/上传,未发布。",
            DeploymentLevel.PACKAGE_EXISTS: "已出包,但尚未上传资产库,未发布。",
            DeploymentLevel.UPLOADED_TO_ASSET_LIBRARY: "已上传资产库,但尚未绑定应用/部署,未发布。",
            DeploymentLevel.BOUND_TO_APP: "已绑定应用,但尚未部署到 aPaaS,未发布。",
        }
        return phrases.get(highest, "尚未发布。")

    def to_payload(self) -> dict:
        """给 UI 和 agent 的同一个状态 payload。"""
        return {
            "levels": {field: getattr(self, field).value for _, field in _LEVEL_FIELDS},
            "highest_confirmed_level": int(self.highest_confirmed_level()),
            "highest_confirmed_level_name": self.highest_confirmed_level().name.lower(),
            "apaas_truth_is_live": self.apaas_truth_is_live,
            "can_claim_published": self.can_claim_published(),
            "summary": self.summary_phrase(),
        }


def _bool_to_obs(value: Optional[bool]) -> Observation:
    """工作区/live 观测的布尔结果转 tri-state(None → UNKNOWN)。"""
    if value is None:
        return Observation.UNKNOWN
    return Observation.CONFIRMED if value else Observation.DENIED


async def gather_deployment_status(
    *,
    app_id: int,
    db: AsyncSession,
    workspace_observer: Optional[Callable[[], dict]] = None,
    apaas_live_fetcher: Optional[Callable[[str], Awaitable[dict]]] = None,
) -> DeploymentStatus:
    """从现有真相源组装七级真相。

    - 级1-4(本地):由 `workspace_observer()` 提供(可选;不提供则保持 UNKNOWN)。
      约定返回 dict,键为 workspace_changed/build_passed/package_exists/
      uploaded_to_asset_library,值为 bool。
    - 级5(绑定):读 `Application.apaas_app_id`(DB 事实)。
    - 级6-7(aPaaS):优先 `apaas_live_fetcher(apaas_app_id)` live 拉取(置
      apaas_truth_is_live=True);否则退化为读 DeployRecord 成功记录作 **缓存** 观测
      (apaas_truth_is_live 保持 False → 不能宣称已发布)。

    依赖注入 observer/fetcher 是刻意的:让本服务可纯单测、且不在内部硬编码
    工作区路径解析与 aPaaS HTTP 调用(那些是各自模块的职责)。
    """
    from app.models import Application
    from app.models.deploy_history import DeployRecord

    status = DeploymentStatus()

    # 级1-4:本地工作区观测(可选)。
    if workspace_observer is not None:
        ws = workspace_observer() or {}
        status.workspace_changed = _bool_to_obs(ws.get("workspace_changed"))
        status.build_passed = _bool_to_obs(ws.get("build_passed"))
        status.package_exists = _bool_to_obs(ws.get("package_exists"))
        status.uploaded_to_asset_library = _bool_to_obs(ws.get("uploaded_to_asset_library"))

    app = (
        await db.execute(select(Application).where(Application.id == app_id))
    ).scalar_one_or_none()
    apaas_app_id = getattr(app, "apaas_app_id", None) if app else None

    # 级5:绑定。
    status.bound_to_app = Observation.CONFIRMED if apaas_app_id else Observation.DENIED

    # 级6-7:aPaaS 侧真相。
    if apaas_app_id and apaas_live_fetcher is not None:
        live = await apaas_live_fetcher(apaas_app_id) or {}
        status.apaas_truth_is_live = True
        status.deployed_to_apaas = _bool_to_obs(live.get("deployed"))
        status.republished_visible = _bool_to_obs(live.get("republished_visible"))
    else:
        # 退化:读本地 DeployRecord 成功记录作缓存观测(不可据此宣称已发布)。
        latest = (
            await db.execute(
                select(DeployRecord)
                .where(DeployRecord.app_id == app_id, DeployRecord.status == "success")
                .order_by(DeployRecord.completed_at.desc(), DeployRecord.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None:
            status.deployed_to_apaas = Observation.CONFIRMED  # 缓存观测
            # apaas_truth_is_live 保持 False → can_claim_published() 仍为 False

    return status
