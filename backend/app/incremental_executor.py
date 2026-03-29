"""
增量执行器模块

根据 ConfigDiff 执行增量更新操作，支持：
- 角色：新增/更新/删除
- 字典：新增/更新/禁用
- 字典选项：新增/更新/禁用
- 模型：新增/更新（删除不支持）
- 模型字段：新增/更新/禁用
- 表单：新增/更新/删除
- 流程：新增/更新/关闭
"""

from __future__ import annotations
import asyncio
import time
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator
from dataclasses import dataclass, field

from app.config_diff import (
    ConfigDiff, ChangeType,
    RoleChange, DictChange, DictOptionChange,
    ModelChange, FieldChange, FormChange, ProcessChange
)
from app.apaas_client import APaaSClient, _extract_query_params, _log_request, _log_response

logger = logging.getLogger(__name__)

# ── 重试配置 ──
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0


# ══════════════════════════════════════════════════════════════
# 执行日志（Journal）— 记录每个 API 操作，用于回滚
# ══════════════════════════════════════════════════════════════

@dataclass
class JournalEntry:
    """单条执行日志"""
    resource_type: str          # "role" | "dict" | "model" | "form" | "process"
    operation: str              # "create" | "update" | "delete" | "disable"
    resource_name: str          # 资源名称
    resource_code: str          # 资源编码
    platform_id: Optional[str] = None   # 平台返回的 ID
    old_value: Optional[Dict] = None    # 修改前的值（用于回滚）
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ExecutionJournal:
    """执行日志集合"""
    entries: List[JournalEntry] = field(default_factory=list)

    def record(self, resource_type: str, operation: str, name: str, code: str,
               platform_id: Optional[str] = None, old_value: Optional[Dict] = None):
        """记录一条操作"""
        entry = JournalEntry(
            resource_type=resource_type,
            operation=operation,
            resource_name=name,
            resource_code=code,
            platform_id=platform_id,
            old_value=old_value,
        )
        self.entries.append(entry)
        return entry

    def to_dict(self) -> List[Dict]:
        return [
            {
                "resource_type": e.resource_type,
                "operation": e.operation,
                "resource_name": e.resource_name,
                "resource_code": e.resource_code,
                "platform_id": e.platform_id,
                "timestamp": e.timestamp,
            }
            for e in self.entries
        ]


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool = True
    results: Dict[str, List[str]] = field(default_factory=lambda: {
        "roles": [],
        "dicts": [],
        "models": [],
        "forms": [],
        "processes": []
    })
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    journal: ExecutionJournal = field(default_factory=ExecutionJournal)

    def add_success(self, category: str, message: str):
        """添加成功记录"""
        self.results[category].append(message)

    def add_error(self, message: str):
        """添加错误记录"""
        self.errors.append(message)
        self.success = False

    def add_warning(self, message: str):
        """添加警告记录"""
        self.warnings.append(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "results": self.results,
            "errors": self.errors,
            "warnings": self.warnings,
            "journal": self.journal.to_dict(),
        }


class IncrementalExecutor:
    """增量执行器"""

    def __init__(self, client: APaaSClient, app_id: str, app_name: str = ""):
        """
        初始化执行器

        Args:
            client: APaaS 客户端
            app_id: 应用 ID
            app_name: 应用名称（用于 useScope）
        """
        self.client = client
        self.app_id = app_id
        self.app_name = app_name
        self.result = ExecutionResult()
        self._remote_models_by_code: Optional[Dict[str, Dict[str, Any]]] = None

    @staticmethod
    def _field_comment_value(field_data: Optional[Dict[str, Any]]) -> str:
        """兼容 preview 的 description 与平台字段的 fieldComment。"""
        if not field_data:
            return ""
        return field_data.get("fieldComment", field_data.get("description", ""))

    async def _load_remote_models_by_code(self) -> Dict[str, Dict[str, Any]]:
        """按 modelCode 建立远端模型索引，供执行阶段补 remote_id。"""
        if self._remote_models_by_code is not None:
            return self._remote_models_by_code

        remote_models = await self.client.query_models(self.app_id)
        self._remote_models_by_code = {}
        for model in remote_models:
            model_code = model.get("modelCode", model.get("code", ""))
            if model_code:
                self._remote_models_by_code[model_code] = model
        return self._remote_models_by_code

    async def _resolve_model_remote_id(self, change: ModelChange) -> Optional[str]:
        """当 diff 未命中 remote_id 时，执行阶段按 modelCode 再查一次。"""
        remote_models = await self._load_remote_models_by_code()
        remote_model = remote_models.get(change.code)
        if not remote_model:
            return None

        remote_id = remote_model.get("id", remote_model.get("modelId"))
        if remote_id:
            change.remote_id = str(remote_id)
            logger.info(
                f"模型「{change.name}」动态补全 remote_id 成功: code={change.code}, remote_id={change.remote_id}"
            )
        return change.remote_id

    async def _resolve_field_remote_id(
        self,
        model_change: ModelChange,
        field_change: FieldChange
    ) -> Optional[str]:
        """当 diff 未命中字段 remote_id 时，执行阶段按 fieldCode 再查一次。"""
        remote_models = await self._load_remote_models_by_code()
        remote_model = remote_models.get(model_change.code)
        if not remote_model:
            return None

        remote_fields = remote_model.get("fields", remote_model.get("dataModelFields", []))
        for remote_field in remote_fields:
            remote_code = remote_field.get("fieldCode", remote_field.get("code", ""))
            if remote_code != field_change.code:
                continue

            remote_id = remote_field.get("id", remote_field.get("fieldId"))
            if remote_id:
                field_change.remote_id = str(remote_id)
                logger.info(
                    f"字段「{field_change.name}」动态补全 remote_id 成功: "
                    f"model_code={model_change.code}, field_code={field_change.code}, remote_id={field_change.remote_id}"
                )
            return field_change.remote_id

        return None

    async def execute_diff(self, diff: ConfigDiff) -> ExecutionResult:
        """
        执行差异更新

        Args:
            diff: 配置差异报告

        Returns:
            ExecutionResult: 执行结果
        """
        if not diff.has_changes:
            logger.info("无变更需要执行")
            return self.result

        # 按顺序执行：角色 -> 字典 -> 模型 -> 表单 -> 流程
        # 这个顺序保证依赖关系：模型依赖字典，表单依赖模型，流程依赖表单

        # 1. 执行角色变更
        await self._execute_role_changes(diff.role_changes)

        # 2. 执行字典变更
        await self._execute_dict_changes(diff.dict_changes)

        # 3. 执行模型变更
        await self._execute_model_changes(diff.model_changes)

        # 4. 执行表单变更
        await self._execute_form_changes(diff.form_changes)

        # 5. 执行流程变更
        await self._execute_process_changes(diff.process_changes)

        return self.result

    async def execute_diff_stream(self, diff: ConfigDiff) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式执行差异更新，逐步 yield 进度事件

        Args:
            diff: 配置差异报告

        Yields:
            进度事件字典，格式：
            - {"stage": "roles", "status": "running", "step": "...", "current": 1, "total": 3}
            - {"stage": "roles", "status": "done", "step": "角色更新完成"}
            - {"type": "complete", "result": {...}}
            - {"type": "error", "message": "..."}
        """
        if not diff.has_changes:
            logger.info("无变更需要执行")
            yield {"type": "complete", "result": self.result.to_dict(), "message": "无变更需要执行"}
            return

        total_stages = sum([
            1 if diff.role_changes else 0,
            1 if diff.dict_changes else 0,
            1 if diff.model_changes else 0,
            1 if diff.form_changes else 0,
            1 if diff.process_changes else 0,
        ])
        current_stage = 0

        try:
            # 1. 执行角色变更
            if diff.role_changes:
                current_stage += 1
                yield {"stage": "roles", "status": "running", "step": f"更新角色 ({len(diff.role_changes)} 个)", "current": current_stage, "total": total_stages}
                for i, change in enumerate(diff.role_changes):
                    yield {"stage": "roles", "status": "running", "step": f"处理角色: {change.name}", "current": current_stage, "total": total_stages, "detail": f"{i+1}/{len(diff.role_changes)}"}
                    await self._execute_single_role_change(change)
                yield {"stage": "roles", "status": "done", "step": f"角色更新完成 ({len(diff.role_changes)} 个)", "current": current_stage, "total": total_stages}

            # 2. 执行字典变更
            if diff.dict_changes:
                current_stage += 1
                yield {"stage": "dicts", "status": "running", "step": f"更新字典 ({len(diff.dict_changes)} 个)", "current": current_stage, "total": total_stages}
                for i, change in enumerate(diff.dict_changes):
                    yield {"stage": "dicts", "status": "running", "step": f"处理字典: {change.name}", "current": current_stage, "total": total_stages, "detail": f"{i+1}/{len(diff.dict_changes)}"}
                    await self._execute_single_dict_change(change)
                yield {"stage": "dicts", "status": "done", "step": f"字典更新完成 ({len(diff.dict_changes)} 个)", "current": current_stage, "total": total_stages}

            # 3. 执行模型变更
            if diff.model_changes:
                current_stage += 1
                yield {"stage": "models", "status": "running", "step": f"更新模型 ({len(diff.model_changes)} 个)", "current": current_stage, "total": total_stages}
                for i, change in enumerate(diff.model_changes):
                    yield {"stage": "models", "status": "running", "step": f"处理模型: {change.name}", "current": current_stage, "total": total_stages, "detail": f"{i+1}/{len(diff.model_changes)}"}
                    await self._execute_single_model_change(change)
                yield {"stage": "models", "status": "done", "step": f"模型更新完成 ({len(diff.model_changes)} 个)", "current": current_stage, "total": total_stages}

            # 4. 执行表单变更
            if diff.form_changes:
                current_stage += 1
                yield {"stage": "forms", "status": "running", "step": f"更新表单 ({len(diff.form_changes)} 个)", "current": current_stage, "total": total_stages}
                for i, change in enumerate(diff.form_changes):
                    yield {"stage": "forms", "status": "running", "step": f"处理表单: {change.name}", "current": current_stage, "total": total_stages, "detail": f"{i+1}/{len(diff.form_changes)}"}
                    await self._execute_single_form_change(change)
                yield {"stage": "forms", "status": "done", "step": f"表单更新完成 ({len(diff.form_changes)} 个)", "current": current_stage, "total": total_stages}

            # 5. 执行流程变更
            if diff.process_changes:
                current_stage += 1
                yield {"stage": "processes", "status": "running", "step": f"更新流程 ({len(diff.process_changes)} 个)", "current": current_stage, "total": total_stages}
                for i, change in enumerate(diff.process_changes):
                    yield {"stage": "processes", "status": "running", "step": f"处理流程: {change.name}", "current": current_stage, "total": total_stages, "detail": f"{i+1}/{len(diff.process_changes)}"}
                    await self._execute_single_process_change(change)
                yield {"stage": "processes", "status": "done", "step": f"流程更新完成 ({len(diff.process_changes)} 个)", "current": current_stage, "total": total_stages}

            # 完成
            yield {"type": "complete", "result": self.result.to_dict()}

        except Exception as e:
            logger.exception("增量更新执行失败")
            self.result.add_error(str(e))
            yield {"type": "error", "message": str(e), "result": self.result.to_dict()}

    # ==================== 重试辅助 ====================

    async def _with_retry(self, func, resource_type: str, resource_name: str):
        """带重试的执行包装。最多重试 MAX_RETRIES 次。"""
        last_error = None
        for attempt in range(1, MAX_RETRIES + 2):  # 1 次正常 + MAX_RETRIES 次重试
            try:
                return await func()
            except Exception as e:
                last_error = e
                if attempt <= MAX_RETRIES:
                    logger.warning(
                        f"{resource_type}「{resource_name}」第 {attempt} 次失败: {e}，"
                        f"{RETRY_DELAY_SECONDS}s 后重试..."
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                else:
                    raise last_error

    # ==================== 单个变更执行方法（带重试 + 日志） ====================

    async def _execute_single_role_change(self, change: RoleChange):
        """执行单个角色变更"""
        try:
            async def _do():
                if change.change_type == ChangeType.ADDED:
                    await self._create_role(change)
                    self.result.journal.record("role", "create", change.name, change.code)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_role(change)
                    self.result.journal.record("role", "update", change.name, change.code,
                                               platform_id=change.remote_id, old_value=change.old_value)
                elif change.change_type == ChangeType.DELETED:
                    await self._delete_role(change)
                    self.result.journal.record("role", "delete", change.name, change.code,
                                               platform_id=change.remote_id)
            await self._with_retry(_do, "角色", change.name)
        except Exception as e:
            self.result.add_error(f"角色「{change.name}」操作失败: {str(e)}")
            logger.exception(f"角色操作失败: {change.name}")

    async def _execute_single_dict_change(self, change: DictChange):
        """执行单个字典变更"""
        try:
            async def _do():
                if change.change_type == ChangeType.ADDED:
                    await self._create_dict(change)
                    self.result.journal.record("dict", "create", change.name, change.code)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_dict(change)
                    self.result.journal.record("dict", "update", change.name, change.code,
                                               platform_id=change.remote_id, old_value=change.old_value)
                elif change.change_type == ChangeType.DELETED:
                    await self._disable_dict(change)
                    self.result.journal.record("dict", "disable", change.name, change.code,
                                               platform_id=change.remote_id)
                # 处理字典选项变更
                await self._execute_dict_option_changes(change)
            await self._with_retry(_do, "字典", change.name)
        except Exception as e:
            self.result.add_error(f"字典「{change.name}」操作失败: {str(e)}")
            logger.exception(f"字典操作失败: {change.name}")

    async def _execute_single_model_change(self, change: ModelChange):
        """执行单个模型变更"""
        try:
            async def _do():
                if change.change_type == ChangeType.ADDED:
                    await self._create_model(change)
                    self.result.journal.record("model", "create", change.name, change.code)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_model(change)
                    self.result.journal.record("model", "update", change.name, change.code,
                                               platform_id=change.remote_id, old_value=change.old_value)
                elif change.change_type == ChangeType.DELETED:
                    self.result.add_warning(f"模型「{change.name}」删除: 平台不支持删除模型，已忽略")
                    return
                # 处理字段变更
                if change.change_type != ChangeType.DELETED:
                    await self._execute_field_changes(change)
            await self._with_retry(_do, "模型", change.name)
        except Exception as e:
            self.result.add_error(f"模型「{change.name}」操作失败: {str(e)}")
            logger.exception(f"模型操作失败: {change.name}")

    async def _execute_single_form_change(self, change: FormChange):
        """执行单个表单变更"""
        try:
            async def _do():
                if change.change_type == ChangeType.ADDED:
                    await self._create_form(change)
                    self.result.journal.record("form", "create", change.name, change.code)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_form(change)
                    self.result.journal.record("form", "update", change.name, change.code,
                                               platform_id=change.remote_id, old_value=change.old_value)
                elif change.change_type == ChangeType.DELETED:
                    await self._delete_form(change)
                    self.result.journal.record("form", "delete", change.name, change.code,
                                               platform_id=change.remote_id)
            await self._with_retry(_do, "表单", change.name)
        except Exception as e:
            self.result.add_error(f"表单「{change.name}」操作失败: {str(e)}")
            logger.exception(f"表单操作失败: {change.name}")

    async def _execute_single_process_change(self, change: ProcessChange):
        """执行单个流程变更"""
        try:
            async def _do():
                if change.change_type == ChangeType.ADDED:
                    await self._create_process(change)
                    self.result.journal.record("process", "create", change.name, change.code)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_process(change)
                    self.result.journal.record("process", "update", change.name, change.code,
                                               platform_id=change.remote_id, old_value=change.old_value)
                elif change.change_type == ChangeType.DELETED:
                    await self._close_process(change)
                    self.result.journal.record("process", "close", change.name, change.code,
                                               platform_id=change.remote_id)
            await self._with_retry(_do, "流程", change.name)
        except Exception as e:
            self.result.add_error(f"流程「{change.name}」操作失败: {str(e)}")
            logger.exception(f"流程操作失败: {change.name}")

    # ==================== 角色变更 ====================

    async def _execute_role_changes(self, changes: List[RoleChange]):
        """执行角色变更"""
        for change in changes:
            try:
                if change.change_type == ChangeType.ADDED:
                    await self._create_role(change)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_role(change)
                elif change.change_type == ChangeType.DELETED:
                    await self._delete_role(change)
            except Exception as e:
                self.result.add_error(f"角色「{change.name}」操作失败: {str(e)}")
                logger.exception(f"角色操作失败: {change.name}")

    async def _create_role(self, change: RoleChange):
        """创建角色"""
        role_data = change.new_value or {}
        payload = [{
            "appId": self.app_id,  # 必须传入 appId，否则角色会变成公开级别
            "roleCode": change.code,
            "roleName": change.name,
            "useScope": self.app_name,
            "internalResource": True,
            "enableGroupParam": role_data.get("enableGroupParam", "DISABLE"),
            "roleParams": role_data.get("roleParams", [])
        }]

        logger.info(f"创建角色请求: app_id={self.app_id}, payload={payload}")
        result = await self.client.create_roles(self.app_id, payload)
        logger.info(f"创建角色响应: {result}")
        self.result.add_success("roles", f"新增角色: {change.name}")
        logger.info(f"创建角色成功: {change.name} ({change.code})")

    async def _update_role(self, change: RoleChange):
        """更新角色"""
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"角色「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_role(change)
            return

        role_data = change.new_value or {}
        payload = {
            "roleId": change.remote_id,
            "appId": self.app_id,
            "roleCode": change.code,
            "roleName": change.name,
            "useScope": self.app_name,
            "internalResource": True,
            "enableGroupParam": role_data.get("enableGroupParam", "DISABLE"),
            "roleNameI18nAssociated": False,
            "roleNameI18nResourceCode": "",
            "roleNameI18n": {},
            "roleParams": role_data.get("roleParams", [])
        }

        await self._post("/xdap-app/roles/edit/role", payload)
        self.result.add_success("roles", f"更新角色: {change.name}")
        logger.info(f"更新角色成功: {change.name} ({change.code})")

    async def _delete_role(self, change: RoleChange):
        """删除角色"""
        if not change.remote_id:
            # 平台上不存在，无需删除
            self.result.add_warning(f"角色「{change.name}」在平台上不存在，跳过删除")
            return

        await self._post("/xdap-app/roles/delete/role", {"roleId": change.remote_id})
        self.result.add_success("roles", f"删除角色: {change.name}")
        logger.info(f"删除角色成功: {change.name} ({change.code})")

    # ==================== 字典变更 ====================

    async def _execute_dict_changes(self, changes: List[DictChange]):
        """执行字典变更"""
        for change in changes:
            try:
                if change.change_type == ChangeType.ADDED:
                    await self._create_dict(change)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_dict(change)
                elif change.change_type == ChangeType.DELETED:
                    await self._disable_dict(change)

                # 处理字典选项变更
                await self._execute_dict_option_changes(change)

            except Exception as e:
                self.result.add_error(f"字典「{change.name}」操作失败: {str(e)}")
                logger.exception(f"字典操作失败: {change.name}")

    async def _create_dict(self, change: DictChange):
        """创建字典"""
        dict_data = change.new_value or {}
        options = dict_data.get("values", dict_data.get("options", []))

        payload = [{
            "appId": self.app_id,  # 必须传入 appId，否则字典会变成公开级别
            "dictionaryCode": change.code,
            "dictionaryName": change.name,
            "dictionaryDescribe": dict_data.get("dictionaryDescribe", ""),
            "internalResource": True,
            "dictionaryMulticolorStatus": dict_data.get("dictionaryMulticolorStatus", "ENABLE"),
            "dictionaryValues": [
                {
                    "valueCode": opt.get("valueCode", opt.get("code", "")),
                    "valueName": opt.get("valueName", opt.get("name", "")),
                    "displayOrder": opt.get("displayOrder", idx),
                    "valueDescribe": opt.get("valueDescribe", ""),
                    "valueStatus": "ENABLE",
                    "valueMulticolor": opt.get("valueMulticolor", "#027AFF")
                }
                for idx, opt in enumerate(options)
            ]
        }]

        try:
            await self.client.create_dicts(self.app_id, payload)
            self.result.add_success("dicts", f"新增字典: {change.name} ({len(options)} 个选项)")
            logger.info(f"创建字典成功: {change.name} ({change.code})")
        except Exception as e:
            err_msg = str(e)
            if "重复" in err_msg or "已存在" in err_msg or "duplicate" in err_msg.lower():
                # 字典已存在，降级为更新 + 逐个添加选项
                logger.info(f"字典「{change.name}」已存在，降级为更新操作")
                await self._update_dict(change)
            else:
                raise

    async def _update_dict(self, change: DictChange):
        """更新字典"""
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"字典「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_dict(change)
            return

        dict_data = change.new_value or {}
        payload = {
            "id": change.remote_id,
            "appId": self.app_id,
            "dictionaryCode": change.code,
            "dictionaryName": change.name,
            "dictionaryDescribe": dict_data.get("dictionaryDescribe", ""),
            "dictionaryStatus": "ENABLE",
            "dictionaryMulticolorStatus": dict_data.get("dictionaryMulticolorStatus", "ENABLE"),
            "internalResource": True,
            "dictionaryNameI18nAssociated": False,
            "dictionaryNameI18nResourceCode": "",
            "dictionaryNameI18n": {}
        }

        await self._post("/xdap-app/dataDictionary/edit/dataDictionary/fromApp", payload)
        self.result.add_success("dicts", f"更新字典: {change.name}")
        logger.info(f"更新字典成功: {change.name} ({change.code})")

    async def _disable_dict(self, change: DictChange):
        """禁用字典（代替删除）"""
        if not change.remote_id:
            # 平台上不存在，无需禁用
            self.result.add_warning(f"字典「{change.name}」在平台上不存在，跳过禁用")
            return

        await self._get(f"/xdap-app/dataDictionary/disable/dataDictionary?id={change.remote_id}")
        self.result.add_success("dicts", f"禁用字典: {change.name}")
        logger.info(f"禁用字典成功: {change.name} ({change.code})")

    async def _execute_dict_option_changes(self, dict_change: DictChange):
        """执行字典选项变更"""
        if not dict_change.remote_id:
            return

        for opt_change in dict_change.option_changes:
            try:
                if opt_change.change_type == ChangeType.ADDED:
                    await self._create_dict_option(dict_change.remote_id, opt_change)
                elif opt_change.change_type == ChangeType.MODIFIED:
                    await self._update_dict_option(dict_change.remote_id, opt_change)
                elif opt_change.change_type == ChangeType.DELETED:
                    await self._disable_dict_option(opt_change)
            except Exception as e:
                self.result.add_error(f"字典「{dict_change.name}」选项「{opt_change.name}」操作失败: {str(e)}")
                logger.exception(f"字典选项操作失败: {opt_change.name}")

    async def _create_dict_option(self, dict_id: str, change: DictOptionChange):
        """创建字典选项（如果已存在则降级为更新）"""
        opt_data = change.new_value or {}
        try:
            await self.client.add_dict_option(
                self.app_id,
                dict_id,
                change.code,
                change.name,
                opt_data.get("displayOrder", 0)
            )
            self.result.add_success("dicts", f"字典选项新增: {change.name}")
            logger.info(f"创建字典选项成功: {change.name} ({change.code})")
        except Exception as e:
            err_msg = str(e)
            if "重复" in err_msg or "已存在" in err_msg or "duplicate" in err_msg.lower():
                logger.info(f"字典选项「{change.name}」已存在，降级为更新操作")
                await self._update_dict_option(dict_id, change)
            else:
                raise

    async def _update_dict_option(self, dict_id: str, change: DictOptionChange):
        """更新字典选项"""
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"字典选项「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_dict_option(dict_id, change)
            return

        opt_data = change.new_value or {}
        payload = {
            "id": change.remote_id,
            "appId": self.app_id,
            "dictionaryId": dict_id,
            "valueCode": change.code,
            "valueName": change.name,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "",
            "valueNameI18n": {},
            "displayOrder": opt_data.get("displayOrder", 0),
            "valueDescribe": opt_data.get("valueDescribe", ""),
            "valueStatus": "ENABLE",
            "valueMulticolor": opt_data.get("valueMulticolor", "#027AFF")
        }

        await self._post("/xdap-app/dataDictionary/edit/dictionaryValue/fromApp", payload)
        self.result.add_success("dicts", f"字典选项更新: {change.name}")
        logger.info(f"更新字典选项成功: {change.name} ({change.code})")

    async def _disable_dict_option(self, change: DictOptionChange):
        """禁用字典选项"""
        if not change.remote_id:
            # 平台上不存在，无需禁用
            self.result.add_warning(f"字典选项「{change.name}」在平台上不存在，跳过禁用")
            return

        await self._get(f"/xdap-app/dataDictionary/disable/dictionaryValue?id={change.remote_id}")
        self.result.add_success("dicts", f"字典选项禁用: {change.name}")
        logger.info(f"禁用字典选项成功: {change.name} ({change.code})")

    # ==================== 模型变更 ====================

    async def _execute_model_changes(self, changes: List[ModelChange]):
        """执行模型变更

        按设计文档逻辑：
        - ADDED: 创建模型及字段
        - MODIFIED: 先判断 modelName 是否变化，变了才调 _update_model；
          然后无论是否更新模型名称，都进入字段级处理
        - DELETED: 不删除模型（避免数据丢失）
        """
        for change in changes:
            try:
                if change.change_type == ChangeType.ADDED:
                    await self._create_model(change)
                elif change.change_type == ChangeType.MODIFIED:
                    # 仅当模型名称变化时才调用模型更新 API
                    old_name = (change.old_value or {}).get("modelName", "")
                    new_name = (change.new_value or {}).get("modelName", change.name)
                    if old_name and new_name and old_name != new_name:
                        await self._update_model(change)
                    else:
                        logger.info(f"模型「{change.name}」名称未变化，跳过模型更新，直接处理字段")
                elif change.change_type == ChangeType.DELETED:
                    self.result.add_warning(f"模型「{change.name}」删除: 平台不支持删除模型，已忽略")
                    continue

                # 处理字段变更（仅对非删除的模型）
                if change.change_type != ChangeType.DELETED:
                    await self._execute_field_changes(change)

            except Exception as e:
                self.result.add_error(f"模型「{change.name}」操作失败: {str(e)}")
                logger.exception(f"模型操作失败: {change.name}")

    async def _create_model(self, change: ModelChange):
        """创建模型"""
        model_data = change.new_value or {}
        fields = model_data.get("fields", model_data.get("dataModelFields", []))

        payload = {
            "appId": self.app_id,  # 外层需要 appId
            "datasourceId": "",
            "dataModels": [{
                "appId": self.app_id,  # 每个模型也需要 appId，否则模型会变成公开级别
                "modelCode": change.code,
                "modelName": change.name,
                "modelType": "DATABASE",
                "useScope": self.app_name,
                "internalResource": True,
                "fields": [
                    {
                        "fieldCode": f.get("fieldCode", f.get("code", "")),
                        "fieldName": f.get("fieldName", f.get("name", "")),
                        "fieldType": f.get("fieldType", "STRING"),
                        "databaseFieldType": f.get("databaseFieldType", "varchar"),
                        "fieldStatus": "ENABLE",
                        "fieldComment": self._field_comment_value(f)
                    }
                    for f in fields
                ]
            }]
        }

        await self.client.create_models(self.app_id, payload)
        self.result.add_success("models", f"新增模型: {change.name} ({len(fields)} 个字段)")
        logger.info(f"创建模型成功: {change.name} ({change.code})")

    async def _update_model(self, change: ModelChange):
        """更新模型"""
        if not change.remote_id:
            await self._resolve_model_remote_id(change)
            if not change.remote_id:
                # 平台上不存在，降级为创建
                logger.info(f"模型「{change.name}」缺少 remote_id，降级为创建操作")
                await self._create_model(change)
                return

        model_data = change.new_value or {}

        # 从远端模型数据中获取 modelDataSource（平台必填字段）
        remote_models = await self._load_remote_models_by_code()
        remote_model = remote_models.get(change.code, {})
        model_data_source = (
            model_data.get("modelDataSource")
            or remote_model.get("modelDataSource")
            or remote_model.get("datasourceId")
            or ""
        )

        payload = {
            "id": change.remote_id,
            "appId": self.app_id,
            "modelCode": change.code,
            "modelName": change.name,
            "modelType": "DATABASE",
            "modelDataSource": model_data_source,
            "useScope": self.app_name,
            "internalResource": True,
            "interfaceType": "CUSTOM",
            "createType": "NEWCREATE",
            "apiVersion": "V2",
            "generateType": "NEWCREATE"
        }

        await self._post("/xdap-app/dataModel/update", payload)
        self.result.add_success("models", f"更新模型: {change.name}")
        logger.info(f"更新模型成功: {change.name} ({change.code})")

    async def _execute_field_changes(self, model_change: ModelChange):
        """执行模型字段变更"""
        if not model_change.remote_id:
            await self._resolve_model_remote_id(model_change)
            if not model_change.remote_id:
                return

        for field_change in model_change.field_changes:
            try:
                if field_change.change_type in (ChangeType.MODIFIED, ChangeType.DELETED) and not field_change.remote_id:
                    await self._resolve_field_remote_id(model_change, field_change)
                if field_change.change_type == ChangeType.ADDED:
                    await self._create_field(model_change.remote_id, field_change)
                elif field_change.change_type == ChangeType.MODIFIED:
                    await self._update_field(model_change.remote_id, field_change)
                elif field_change.change_type == ChangeType.DELETED:
                    await self._disable_field(model_change.remote_id, field_change)
            except Exception as e:
                self.result.add_error(f"模型「{model_change.name}」字段「{field_change.name}」操作失败: {str(e)}")
                logger.exception(f"字段操作失败: {field_change.name}")

    async def _create_field(self, model_id: str, change: FieldChange):
        """创建模型字段"""
        field_data = change.new_value or {}

        # 获取模型编码（平台 API 必填）
        model_code = change.model_code or ""
        if not model_code:
            remote_models = await self._load_remote_models_by_code()
            for code, m in remote_models.items():
                mid = str(m.get("id", m.get("modelId", "")))
                if mid == model_id:
                    model_code = code
                    break

        payload = {
            "dataModelId": model_id,
            "modelId": model_id,
            "modelCode": model_code,
            "appId": self.app_id,
            "fieldCode": change.code,
            "fieldName": change.name,
            "fieldType": field_data.get("fieldType", "STRING"),
            "databaseFieldType": field_data.get("databaseFieldType", "varchar"),
            "fieldStatus": "ENABLE",
            "fieldComment": self._field_comment_value(field_data),
        }

        await self._post("/xdap-app/modelField/add", payload)
        self.result.add_success("models", f"模型字段新增: {change.name}")
        logger.info(f"创建字段成功: {change.name} ({change.code})")

    async def _update_field(self, model_id: str, change: FieldChange):
        """更新模型字段

        特殊处理：当 fieldType 发生变化时，按设计文档要求执行"禁用旧字段 + 创建新字段"，
        而非直接更新类型（类型变更可能导致数据兼容性问题）。
        """
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"字段「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_field(model_id, change)
            return

        old_data = change.old_value or {}
        new_data = change.new_value or {}
        old_type = old_data.get("fieldType", old_data.get("type", ""))
        new_type = new_data.get("fieldType", new_data.get("type", "STRING"))

        # 检测 fieldType 是否变化 → 禁用旧字段 + 创建新字段
        if old_type and new_type and old_type != new_type:
            logger.warning(
                f"字段「{change.name}」类型变更: {old_type} → {new_type}，"
                f"执行禁用旧字段+创建新字段策略"
            )

            # 1. 禁用旧字段（保留原 fieldCode）
            disable_payload = {
                "id": change.remote_id,
                "modelId": model_id,
                "fieldCode": change.code,
                "fieldName": change.name,
                "fieldType": old_type,
                "databaseFieldType": old_data.get("databaseFieldType", "varchar"),
                "fieldStatus": "DISABLE",
                "fieldComment": self._field_comment_value(old_data),
            }
            await self._post("/xdap-app/modelField/update/fromApp", disable_payload)
            self.result.journal.record(
                "model", "disable", change.name, change.code,
                platform_id=change.remote_id, old_value=old_data,
            )
            logger.info(f"禁用旧字段: {change.name} ({change.code})")

            # 2. 生成新 fieldCode 并创建新字段
            new_code = f"{change.code}_v2"
            new_field_change = FieldChange(
                name=change.name,
                code=new_code,
                change_type=ChangeType.ADDED,
                new_value={
                    "fieldType": new_type,
                    "databaseFieldType": new_data.get("databaseFieldType", "varchar"),
                    "fieldComment": self._field_comment_value(new_data),
                },
            )
            await self._create_field(model_id, new_field_change)

            self.result.add_success(
                "models",
                f"模型字段类型变更: {change.name} ({old_type}→{new_type})，"
                f"旧字段 {change.code} 已禁用，新字段 {new_code} 已创建"
            )
            self.result.add_warning(
                f"字段「{change.name}」类型从 {old_type} 变更为 {new_type}，"
                f"旧数据需手动迁移: {change.code} → {new_code}"
            )
            return

        # 普通属性更新（fieldName/maxLength/fieldComment）
        payload = {
            "id": change.remote_id,
            "modelId": model_id,
            "fieldCode": change.code,
            "fieldName": change.name,
            "fieldType": new_type,
            "databaseFieldType": new_data.get("databaseFieldType", "varchar"),
            "fieldStatus": "ENABLE",
            "fieldComment": self._field_comment_value(new_data),
        }

        await self._post("/xdap-app/modelField/update/fromApp", payload)
        self.result.add_success("models", f"模型字段更新: {change.name}")
        logger.info(f"更新字段成功: {change.name} ({change.code})")

    async def _disable_field(self, model_id: str, change: FieldChange):
        """禁用模型字段（通过更新状态实现）"""
        if not change.remote_id:
            # 平台上不存在，无需禁用
            self.result.add_warning(f"字段「{change.name}」在平台上不存在，跳过禁用")
            return

        field_data = change.old_value or {}
        payload = {
            "id": change.remote_id,
            "modelId": model_id,
            "fieldCode": change.code,
            "fieldName": change.name,
            "fieldType": field_data.get("fieldType", "STRING"),
            "databaseFieldType": field_data.get("databaseFieldType", "varchar"),
            "fieldStatus": "DISABLE",  # 设置为禁用
            "fieldComment": self._field_comment_value(field_data)
        }

        await self._post("/xdap-app/modelField/update/fromApp", payload)
        self.result.add_success("models", f"模型字段禁用: {change.name}")
        logger.info(f"禁用字段成功: {change.name} ({change.code})")

    # ==================== 表单变更 ====================

    async def _execute_form_changes(self, changes: List[FormChange]):
        """执行表单变更"""
        for change in changes:
            try:
                if change.change_type == ChangeType.ADDED:
                    await self._create_form(change)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_form(change)
                elif change.change_type == ChangeType.DELETED:
                    await self._delete_form(change)
            except Exception as e:
                self.result.add_error(f"表单「{change.name}」操作失败: {str(e)}")
                logger.exception(f"表单操作失败: {change.name}")

    async def _create_form(self, change: FormChange):
        """创建表单"""
        form_data = change.new_value or {}

        payload = [{
            "formCode": change.code,
            "formName": change.name,
            "modelCode": form_data.get("modelCode", change.model_code or ""),
            "formType": form_data.get("formType", "NORMAL"),
            "components": form_data.get("components", [])
        }]

        await self.client.create_form_config(self.app_id, payload)
        self.result.add_success("forms", f"新增表单: {change.name}")
        logger.info(f"创建表单成功: {change.name} ({change.code})")

    async def _update_form(self, change: FormChange):
        """更新表单"""
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"表单「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_form(change)
            return

        form_data = change.new_value or {}

        # 先获取当前表单配置
        try:
            current_config = await self.client.query_form_config(self.app_id, change.remote_id)
        except Exception:
            self.result.add_warning(f"表单「{change.name}」无法获取当前配置，跳过更新")
            return

        # 合并新配置
        if "components" in form_data:
            current_config["detailPage"]["formComponents"] = form_data["components"]

        await self.client.save_form_config(self.app_id, current_config)
        self.result.add_success("forms", f"更新表单: {change.name}")
        logger.info(f"更新表单成功: {change.name} ({change.code})")

    async def _delete_form(self, change: FormChange):
        """删除表单"""
        if not change.menu_id:
            # 平台上不存在，无需删除
            self.result.add_warning(f"表单「{change.name}」在平台上不存在，跳过删除")
            return

        payload = {
            "id": change.menu_id,
            "appId": self.app_id,
            "menuName": change.name
        }

        await self._post("/xdap-app/menu/delete/menu", payload)
        self.result.add_success("forms", f"删除表单: {change.name}")
        logger.info(f"删除表单成功: {change.name} ({change.code})")

    # ==================== 流程变更 ====================

    async def _execute_process_changes(self, changes: List[ProcessChange]):
        """执行流程变更"""
        for change in changes:
            try:
                if change.change_type == ChangeType.ADDED:
                    await self._create_process(change)
                elif change.change_type == ChangeType.MODIFIED:
                    await self._update_process(change)
                elif change.change_type == ChangeType.DELETED:
                    await self._close_process(change)
            except Exception as e:
                self.result.add_error(f"流程「{change.name}」操作失败: {str(e)}")
                logger.exception(f"流程操作失败: {change.name}")

    async def _create_process(self, change: ProcessChange):
        """创建流程"""
        proc_data = change.new_value or {}

        payload = [{
            "processCode": change.code,
            "processName": change.name,
            "formCode": proc_data.get("formCode", change.form_code or ""),
            "nodes": proc_data.get("nodes", []),
            "edges": proc_data.get("edges", [])
        }]

        await self.client.create_process_config(self.app_id, payload)
        self.result.add_success("processes", f"新增流程: {change.name}")
        logger.info(f"创建流程成功: {change.name} ({change.code})")

    async def _update_process(self, change: ProcessChange):
        """更新流程"""
        if not change.remote_id:
            # 平台上不存在，降级为创建
            logger.info(f"流程「{change.name}」缺少 remote_id，降级为创建操作")
            await self._create_process(change)
            return

        proc_data = change.new_value or {}
        payload = {
            "id": change.remote_id,
            "processCode": change.code,
            "processName": change.name,
            "formCode": proc_data.get("formCode", change.form_code or ""),
            "nodes": proc_data.get("nodes", []),
            "edges": proc_data.get("edges", []),
            "bpmn": proc_data.get("bpmn", "")
        }

        await self.client.save_process_config(self.app_id, payload)
        self.result.add_success("processes", f"更新流程: {change.name}")
        logger.info(f"更新流程成功: {change.name} ({change.code})")

    async def _close_process(self, change: ProcessChange):
        """关闭流程（代替删除）"""
        if not change.remote_id:
            # 平台上不存在，无需关闭
            self.result.add_warning(f"流程「{change.name}」在平台上不存在，跳过关闭")
            return

        timestamp = int(time.time() * 1000)
        await self._post(
            f"/xdap-app/process/close/processConfig?processId={change.remote_id}&timestamp={timestamp}",
            {}
        )
        self.result.add_success("processes", f"关闭流程: {change.name}")
        logger.info(f"关闭流程成功: {change.name} ({change.code})")

    # ==================== 通用方法 ====================

    async def _post(self, path: str, payload: dict) -> dict:
        """发送 POST 请求"""
        import httpx

        url = f"{self.client.base_url}/xdap-app{path}" if not path.startswith("/xdap-app") else f"{self.client.base_url}{path}"
        params = _extract_query_params(url)
        _log_request("POST", url, payload=payload, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.post(
                url,
                headers=self.client._get_headers(app_id=self.app_id),
                json=payload
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "API 调用失败"))

            return data

    async def _get(self, path: str) -> dict:
        """发送 GET 请求"""
        import httpx

        url = f"{self.client.base_url}/xdap-app{path}" if not path.startswith("/xdap-app") else f"{self.client.base_url}{path}"
        params = _extract_query_params(url)
        _log_request("GET", url, params=params)
        start = time.time()

        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.get(
                url,
                headers=self.client._get_headers(app_id=self.app_id)
            )
            elapsed_ms = (time.time() - start) * 1000
            response.raise_for_status()
            data = response.json()
            _log_response(url, response.status_code, data, elapsed_ms)

            if data.get("code") not in ("ok", 200):
                raise Exception(data.get("message", "API 调用失败"))

            return data


async def fetch_remote_data(client: APaaSClient, app_id: str) -> Dict[str, Any]:
    """
    获取平台远程数据，用于差异对比时填充 remote_id

    Args:
        client: APaaS 客户端
        app_id: 应用 ID

    Returns:
        远程数据字典
    """
    result = {
        "roles": [],
        "dicts": [],
        "dict_options": {},
        "models": [],
        "forms": [],
        "processes": []
    }

    logger.info(f"开始获取平台远程数据: app_id={app_id}")

    try:
        # 查询角色
        import httpx
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
            response = await http_client.post(
                f"{client.base_url}/xdap-app/roles/query/rolesList",
                headers=client._get_headers(app_id=app_id),
                json={"keyWord": "", "appId": app_id, "appQueryFlag": True}
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == "ok":
                    result["roles"] = data.get("data", [])
                    logger.info(f"查询角色成功: {len(result['roles'])} 个, codes={[r.get('roleCode') for r in result['roles']]}")
    except Exception as e:
        logger.warning(f"查询角色失败: {e}")

    try:
        # 查询字典
        result["dicts"] = await client.query_dicts(app_id)
        logger.info(f"查询字典成功: {len(result['dicts'])} 个, codes={[d.get('dictionaryCode') for d in result['dicts']]}")

        # 查询每个字典的选项
        for d in result["dicts"]:
            dict_code = d.get("dictionaryCode", "")
            dict_id = d.get("id", "")
            if dict_code and dict_id:
                options = await client.query_dict_options(app_id, dict_id)
                result["dict_options"][dict_code] = options
    except Exception as e:
        logger.warning(f"查询字典失败: {e}")

    try:
        # 查询模型
        result["models"] = await client.query_models(app_id)
        logger.info(f"查询模型成功: {len(result['models'])} 个, codes={[m.get('modelCode') for m in result['models']]}")
    except Exception as e:
        logger.warning(f"查询模型失败: {e}")

    try:
        # 查询表单（菜单）
        result["forms"] = await client.query_menus(app_id)
        logger.info(f"查询表单成功: {len(result['forms'])} 个")
    except Exception as e:
        logger.warning(f"查询表单失败: {e}")

    logger.info(f"获取平台远程数据完成: roles={len(result['roles'])}, dicts={len(result['dicts'])}, models={len(result['models'])}, forms={len(result['forms'])}")
    return result
