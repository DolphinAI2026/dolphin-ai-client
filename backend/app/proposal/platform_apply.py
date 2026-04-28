"""Phase E：把 SPEC diff 翻译成 IncrementalExecutor 能消费的 ConfigDiff，并执行真平台部署。

设计要点：
- 复用既有 compute_config_diff (config_diff.py) 与 IncrementalExecutor (V1→V2 增量已验证)，
  避免重写平台部署逻辑。
- spec_diff_to_config_diff：canonical Spec + draft Spec → spec_to_config → compute_config_diff。
- execute_platform_apply：dry_run=True 仅算 diff 不调 platform API，dry_run=False 真踩平台。
"""

from __future__ import annotations

import logging
from typing import Optional

from app.apaas_client import APaaSClient
from app.config_diff import ConfigDiff, compute_config_diff
from app.incremental_executor import ExecutionResult, IncrementalExecutor
from app.models import Application
from app.builder_spec.converter import spec_to_config
from app.builder_spec.schema import Spec

logger = logging.getLogger(__name__)


def spec_diff_to_config_diff(canonical: Optional[Spec], draft: Spec) -> ConfigDiff:
    """把 SPEC 的 canonical → draft 转成 IncrementalExecutor 能消费的 ConfigDiff。

    canonical=None（全新应用）时 old_config 用空骨架，diff 全部是 add ops。
    """
    if canonical is None:
        old_config = {
            "appName": "",
            "roles": [],
            "dicts": [],
            "models": [],
            "permissions": [],
        }
    else:
        old_config = spec_to_config(canonical)
    new_config = spec_to_config(draft)
    return compute_config_diff(old_config, new_config)


async def execute_platform_apply(
    *,
    application: Application,
    canonical: Optional[Spec],
    draft: Spec,
    dry_run: bool = False,
) -> ExecutionResult:
    """真接平台 apply：调 IncrementalExecutor.execute_diff。

    dry_run=True 时仅算 diff、不构造 client / executor、也不调平台 API
    （用于 Phase B 第二道门预检 hook，目前仅返回 diff 摘要）。

    dry_run=False 时要求 application 已绑定 platform_url + platform_token + apaas_app_id，
    否则 raise RuntimeError（execute_apply 的 except 分支会标 apply_failed）。
    """
    diff = spec_diff_to_config_diff(canonical, draft)

    if dry_run:
        result = ExecutionResult()
        for category, attr in (
            ("roles", "role_changes"),
            ("dicts", "dict_changes"),
            ("models", "model_changes"),
            ("forms", "form_changes"),
            ("processes", "process_changes"),
        ):
            for change in getattr(diff, attr, []) or []:
                result.add_success(
                    category,
                    f"[dry-run] {change.change_type.value} {category}:{change.code}",
                )
        return result

    if not application.platform_url or not application.platform_token:
        raise RuntimeError(
            f"application {application.id} 未连接 aPaaS 平台（platform_url/token 缺失）"
        )
    if not application.apaas_app_id:
        raise RuntimeError(
            f"application {application.id} 还没在 aPaaS 平台创建（apaas_app_id 缺失）"
        )

    client = APaaSClient(
        base_url=application.platform_url,
        tenant_id=application.platform_tenant_id,
        token=application.platform_token,
    )
    new_config = spec_to_config(draft)
    executor = IncrementalExecutor(
        client=client,
        app_id=application.apaas_app_id,
        app_name=application.app_name or "",
        target_config=new_config,
    )
    return await executor.execute_diff(diff)
