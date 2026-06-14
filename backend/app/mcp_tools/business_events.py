"""aPaaS business event MCP tools."""

from __future__ import annotations

from typing import Callable


_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


def register(mcp, with_client: Callable) -> dict[str, object]:
    """Register aPaaS business event tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    _with_client = with_client

    # ═══════════════════════════════════════════════════════════════════════════
    # 业务事件 (BPM Engine) — 6 个低层工具
    # 详 docs/research-business-event-api.md (770 行实证 API 笔记).
    #
    # 典型工作流 (建一个"字段值改变 → 自动赋值"事件):
    #   1. list_form_menus_for_event(env_id, apaas_app_id) — 列表单菜单, 选 triggerFormId
    #   2. list_apaas_form_components(env_id, apaas_app_id, form_id) — 拿字段 uuid/boCode
    #   3. create_apaas_business_event(env_id, apaas_app_id, event_name="...", event_type="EVENT_VALUE_CHANGE")
    #      → 返 event_id (24hex MongoDB ObjectId)
    #   4. get_apaas_business_event_detail(env_id, apaas_app_id, event_id)
    #      → 拿到 stub DAG (含平台自动填的 boCodeBORelationProperties 元数据)
    #   5. agent 改 trigger node (设 boCode/componentUuid/triggerType=VALUE_CHANGE)
    #      + 在 eventNodeNdList 加 ASSIGNMENT_NODE
    #   6. save_apaas_business_event(env_id, apaas_app_id, event_data) — 持久化整树
    # ═══════════════════════════════════════════════════════════════════════════


    @mcp.tool()
    async def list_apaas_business_events(
        env_id: int,
        apaas_app_id: str,
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """列指定应用的所有业务事件（字段值改变 / 表单提交触发 / 定时 / 审批节点等）。

        返回每个事件的 eventId / eventName / eventType / status / lastUpdateDate.
        给 agent 看已有事件防重复创建. 跨应用聚合用平台租户中心 UI, 本工具仅限单 app.
        """
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
        ok, raw = await _with_client(env_id, "查业务事件",
            lambda c: c.list_business_events(apaas_app_id.strip(), keyword=keyword,
                                              page=page, page_size=page_size))
        if not ok:
            return raw
        return {"ok": True, "apaas_app_id": apaas_app_id, "data": raw}


    @mcp.tool()
    async def get_apaas_business_event_detail(
        env_id: int,
        apaas_app_id: str,
        event_id: str,
    ) -> dict:
        """查业务事件完整详情 — 含 triggerNodeNd + eventNodeNdList + endNode + 完整 boCodeBORelationProperties.

        平台 stub 创建后调这个拿到完整结构 (含元数据), agent 改完调 save_apaas_business_event 持久化.

        event_id 是 24 字符 MongoDB ObjectId (从 list 或 create 的返回里取).
        """
        if not (apaas_app_id.strip() and event_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_id 都必填"}
        ok, raw = await _with_client(env_id, "查业务事件详情",
            lambda c: c.get_business_event_detail(event_id.strip(), apaas_app_id.strip()))
        if not ok:
            return raw
        return {"ok": True, "event_id": event_id, "data": raw}


    @mcp.tool()
    async def create_apaas_business_event(
        env_id: int,
        apaas_app_id: str,
        event_name: str,
        event_type: str = "EVENT_OPERATION",
    ) -> dict:
        """创建业务事件 stub (仅 metadata, DAG 留空) — 返 event_id (24hex MongoDB ObjectId).

        event_type 真值集 (从 prod 160 事件实证):
          - EVENT_OPERATION    表单操作触发 (提交/保存/修改/删除) — 最高频
          - EVENT_BUTTON       按钮触发 (自定义按钮点击)
          - EVENT_VALUE_CHANGE 字段值改变触发 (用户截图场景)
          - EVENT_PROCESS      审批流程触发 (审批环节自动化)
          - EVENT_TIME         定时触发 (Quartz cron)
          - EVENT_EXT          外部触发 (API 暴露给外部)
          - EVENT_WORKFLOW     标准工作流

        建完调 get_apaas_business_event_detail 拿 stub 完整结构, 改完 save 持久化.
        """
        if not (apaas_app_id.strip() and event_name.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_name 都必填"}
        valid_types = {"EVENT_OPERATION", "EVENT_BUTTON", "EVENT_VALUE_CHANGE",
                       "EVENT_PROCESS", "EVENT_TIME", "EVENT_EXT", "EVENT_WORKFLOW"}
        if event_type not in valid_types:
            return {"ok": False, "error_code": "INVALID_EVENT_TYPE",
                    "message": f"event_type 必须是 {valid_types} 之一, 当前={event_type}"}
        ok, raw = await _with_client(env_id, "建业务事件",
            lambda c: c.create_business_event(apaas_app_id.strip(), event_name.strip(),
                                               event_type=event_type))
        if not ok:
            return raw
        event_id = (raw.get("id") or raw.get("eventId") or "") if isinstance(raw, dict) else ""
        return {
            "ok": True,
            "event_id": event_id,
            "event_name": event_name,
            "event_type": event_type,
            "message": f"事件「{event_name}」stub 已建 (id={event_id}); "
                       f"下一步 get_apaas_business_event_detail 拿 stub 完整 DAG, 改 trigger + 加节点后 save",
        }


    @mcp.tool()
    async def save_apaas_business_event(
        env_id: int,
        apaas_app_id: str,
        event_data: dict,
    ) -> dict:
        """保存业务事件完整 DAG (覆盖式) — agent 改完 get_detail 拿的结构后调这个持久化.

        event_data 是完整顶层结构, 含:
          - id (eventId 24hex), eventName, eventType, appId, version:"v3.0", status:"ENABLE"
          - triggerNodeNd (1 个触发节点)
          - eventNodeNdList (中间节点数组, 含 ASSIGNMENT_NODE / UPDATE_NODE / CUSTOM_CODE_NODE 等)
          - endNode (1 个结束节点)
          - eventCode (32hex), objectVersionNumber (乐观锁)

        ⚠️ 覆盖式: event_data 里的字段会**整体替换**平台上的, 别漏关键字段 (尤其
        boCodeBORelationProperties — 用 get_detail 返回的原值, 不要清空).
        """
        if not (apaas_app_id.strip() and isinstance(event_data, dict)):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_data dict 都必填"}
        ok, raw = await _with_client(env_id, "存业务事件",
            lambda c: c.save_business_event(event_data, apaas_app_id.strip()))
        if not ok:
            return raw
        return {
            "ok": True,
            "event_id": event_data.get("id"),
            "event_name": event_data.get("eventName"),
            "message": f"事件「{event_data.get('eventName')}」DAG 已保存",
        }


    @mcp.tool()
    async def delete_apaas_business_event(
        env_id: int,
        apaas_app_id: str,
        event_id: str,
    ) -> dict:
        """删除业务事件 — ⚠️ 平台 endpoint 是 GET 不是 DELETE, 客户端已封装."""
        if not (apaas_app_id.strip() and event_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_id 都必填"}
        ok, raw = await _with_client(env_id, "删业务事件",
            lambda c: c.delete_business_event(event_id.strip(), apaas_app_id.strip()))
        if not ok:
            return raw
        return {"ok": True, "event_id": event_id, "message": f"事件 {event_id} 已删除"}


    @mcp.tool()
    async def list_apaas_form_menus_for_event(
        env_id: int,
        apaas_app_id: str,
    ) -> dict:
        """列应用所有"可作为事件触发源的表单菜单" — 给 agent 选 triggerFormId / triggerBocCode 用.

        每项含 menu_id / menu_name / form_id / boc_code. 跟 list_apaas_app_menus 区别:
        本接口专为业务事件配置场景, 平台用 ?eventFlag=true 过滤了不能挂事件的菜单.
        """
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
        ok, raw = await _with_client(env_id, "查可挂事件表单菜单",
            lambda c: c.list_form_menus_for_event(apaas_app_id.strip()))
        if not ok:
            return raw
        return {"ok": True, "apaas_app_id": apaas_app_id, "form_menus": raw, "count": len(raw)}


    # ─── 业务事件 补 3 个低层 ─────────────────────────────────────────────────────


    @mcp.tool()
    async def list_apaas_business_events_in_tenant(
        env_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
    ) -> dict:
        """列租户业务事件中心（跨应用聚合，只读运维视图）— POST /xdap-app/event/query/allEventList.

        返回 {table: [{eventId, eventName, appId, appName, intactFlag, eventCode, callbackUrl, creationDate}], total}.
        给 agent 跨应用看事件分布用；单 app 内事件用 list_apaas_business_events.
        """
        ok, raw = await _with_client(env_id, "查租户业务事件",
            lambda c: c.list_business_events_in_tenant(page=page, page_size=page_size, keyword=keyword))
        if not ok:
            return raw
        return {"ok": True, **raw}


    @mcp.tool()
    async def query_apaas_business_event_trees(
        env_id: int,
        apaas_app_id: str,
    ) -> dict:
        """查应用业务事件分类树 — GET /xdap-app/event/queryTrees.

        返左侧分类菜单 tree（外部触发 / 定时触发 / 表单触发 / 标准工作流 分组），
        给 agent 按 eventType 浏览事件用。
        """
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}
        ok, raw = await _with_client(env_id, "查事件分类树",
            lambda c: c.query_business_event_trees(apaas_app_id.strip()))
        if not ok:
            return raw
        return {"ok": True, "apaas_app_id": apaas_app_id, "trees": raw}


    @mcp.tool()
    async def list_apaas_business_event_execution_history(
        env_id: int,
        apaas_app_id: str,
        event_id: str,
        page: int = 1,
        page_size: int = 10,
        status: str = "",
        before_time: str = "",
        end_time: str = "",
    ) -> dict:
        """查业务事件执行历史 — POST /xdap-app/event/query/exeHistory/list.

        返 {table: [{triggerTime, costTime, triggerWay, triggerUser, status, ...}], total}.
        用来 debug 事件是否真在跑 / 跑成功 / 跑失败原因.

        status (可选): ENABLE / DISABLE 过滤；
        before_time/end_time (可选): "YYYY-MM-DD HH:mm:ss" 时间区间。
        """
        if not (apaas_app_id.strip() and event_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_id 都必填"}
        ok, raw = await _with_client(env_id, "查事件执行历史",
            lambda c: c.list_business_event_execution_history(
                event_id.strip(), apaas_app_id.strip(),
                page=page, page_size=page_size,
                status=status, before_time=before_time, end_time=end_time))
        if not ok:
            return raw
        return {"ok": True, "event_id": event_id, **raw}


    # ─── 业务事件 3 个高层封装（按 ai-builder MVP 3 条路线分）─────────────────────


    @mcp.tool()
    async def create_form_event_with_python_code(
        env_id: int,
        apaas_app_id: str,
        event_name: str,
        trigger_form_id: str,
        trigger_boc_code: str,
        python_code: str,
        trigger_type: str = "SUBMIT_DONE",
    ) -> dict:
        """🅰️ 路线 A: 一键创建"表单触发 + Python3 自定义节点"业务事件.

        生成 3 节点 DAG: TRIGGER_NODE → CUSTOM_CODE_NODE(PYTHON3) → END_NODE.
        业务逻辑全在 python_code 里（自定义节点的代码字段）, schema 复杂度最低.

        入参:
          - apaas_app_id: 应用 ID (snowflake)
          - event_name: 事件名
          - trigger_form_id: 触发表单 ID (24hex MongoDB ObjectId, 用 list_apaas_form_menus_for_event 拿)
          - trigger_boc_code: 触发业务对象 code (boc_code_<formId>)
          - python_code: Python3 代码, 必含 `import definesys` + `def invoke(): ...`
          - trigger_type: SUBMIT_DONE (默认成功后) / SUBMIT_BEFORE / SUBMIT_OR_SAVE_BEFORE / SUBMIT_OR_SAVE_DONE

        工作流:
          1. add/event 拿 eventId
          2. get/detail 拿 stub (含平台填的 boCodeBORelationProperties 元数据)
          3. 改 triggerNodeNd + 加 CUSTOM_CODE_NODE + endNode
          4. save/event 持久化
        """
        if not (apaas_app_id.strip() and event_name.strip() and trigger_form_id.strip() and python_code.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_name + trigger_form_id + python_code 都必填"}
        valid_trigger_types = {"SUBMIT_DONE", "SUBMIT_BEFORE", "SUBMIT_OR_SAVE_BEFORE",
                                "SUBMIT_OR_SAVE_DONE", "SAVE_BEFORE", "SAVE_DONE",
                                "SUBMIT", "SAVE", "SUBMIT_OR_SAVE"}
        if trigger_type not in valid_trigger_types:
            return {"ok": False, "error_code": "INVALID_TRIGGER_TYPE",
                    "message": f"trigger_type 必须是 {valid_trigger_types} 之一, 当前={trigger_type}"}
        if "definesys" not in python_code or "invoke" not in python_code:
            return {"ok": False, "error_code": "INVALID_PYTHON_CODE",
                    "message": "python_code 必须含 `import definesys` + `def invoke(): ...` (aPaaS SDK contract)"}

        # 计算 triggerWay (映射表实证: docs v2 第 7 节)
        trigger_way_map = {
            "SUBMIT_BEFORE": "FORM_OPT_BEFORE",
            "SUBMIT_OR_SAVE_BEFORE": "FORM_OPT_BEFORE",
            "SAVE_BEFORE": "FORM_OPT_BEFORE",
            "SUBMIT": "FORM_OPT_AFTER",
            "SAVE": "FORM_OPT_AFTER",
            "SUBMIT_OR_SAVE": "FORM_OPT_AFTER",
            "SUBMIT_DONE": "FORM_OPT_AFTER_DONE",
            "SAVE_DONE": "FORM_OPT_AFTER_DONE",
            "SUBMIT_OR_SAVE_DONE": "FORM_OPT_AFTER_DONE",
        }
        trigger_way = trigger_way_map.get(trigger_type, "FORM_OPT_AFTER_DONE")

        async def _do(c):
            from uuid import uuid4
            # 1. 创建 stub
            create_resp = await c.create_business_event(
                apaas_app_id.strip(), event_name.strip(), event_type="EVENT_OPERATION",
            )
            event_id = create_resp.get("id") or create_resp.get("eventId")
            if not event_id:
                raise Exception(f"创建事件 stub 失败: 没拿到 event_id, raw={create_resp}")

            # 2. 拿 stub detail (含平台填的元数据)
            data = await c.get_business_event_detail(event_id, apaas_app_id.strip())
            if not isinstance(data, dict):
                raise Exception(f"detail 不是 dict: {type(data)}")

            # 3. 构造 3 节点 DAG (节点 ID 用 UUID hex 32 字符)
            trigger_node_id = uuid4().hex
            custom_node_id = uuid4().hex
            end_node_id = uuid4().hex

            data["triggerNodeNd"] = {
                "nodeId": trigger_node_id,
                "nodeName": "表单操作触发",
                "nextNodeId": [custom_node_id],
                "nodeType": "TRIGGER_NODE",
                "triggerType": trigger_type,
                "triggerTypeName": "",
                "triggerWay": trigger_way,
                "triggerWayName": "",
                "triggerEnv": "EVENT_FRONT",
                "triggerFormId": trigger_form_id.strip(),
                "triggerBocCode": trigger_boc_code.strip(),
                "triggerFormName": "",
                "filterConditionGroupList": [],
                "fieldChangeRange": [],
                "beforeAndAfterDataFlag": False,
                "buttonName": "",
                "excelTemplateId": [],
                "triggerBuriedPoint": "DISABLE",
                "useTableData": True,
                "validateStatus": "success",
                "boCodeBORelationProperties": (data.get("triggerNodeNd") or {}).get("boCodeBORelationProperties") or {},
            }

            data["eventNodeNdList"] = [{
                "nodeId": custom_node_id,
                "nodeName": "AI 业务逻辑",
                "nodeType": "CUSTOM_CODE_NODE",
                "nextNodeId": [end_node_id],
                "validateStatus": "success",
                "nodeDesc": "",
                "extResponse": "",
                "customCode": python_code.strip(),
                "customNodeEnv": "PYTHON3",
                "relatedDataNodeId": trigger_node_id,
                "firstRules": [],
                "secondRules": [],
                "targetBocName": "",
                "tableConfigs": [],
                "filterConditionGroup": [],
                "boCodeBORelationProperties": {},
            }]

            data["endNode"] = {
                "nodeId": end_node_id,
                "nodeName": "结束节点",
                "nextNodeId": [],
                "nodeType": "END_NODE",
                "dataStatus": "COMPLETED",
            }

            # 4. 保存
            saved = await c.save_business_event(data, apaas_app_id.strip())
            return {
                "event_id": event_id,
                "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else None,
                "status": saved.get("status") if isinstance(saved, dict) else "ENABLE",
            }

        ok, raw = await _with_client(env_id, "建 Python 自定义事件", _do)
        if not ok:
            return raw
        return {
            "ok": True,
            "route": "A_PYTHON_CUSTOM_CODE",
            "event_id": raw["event_id"],
            "event_name": event_name,
            "trigger_type": trigger_type,
            "intact_flag": raw.get("intact_flag"),
            "message": f"事件「{event_name}」已建 (Python 自定义节点) — id={raw['event_id']} intactFlag={raw.get('intact_flag')}",
        }


    @mcp.tool()
    async def create_time_event_with_python_code(
        env_id: int,
        apaas_app_id: str,
        event_name: str,
        cron_expression: str,
        python_code: str,
        job_trigger_type: str = "REPEAT_EXECUTE",
        start_time: str = "",
        end_time: str = "2159-12-31 00:00:00",
    ) -> dict:
        """🅲️ 定时触发 + Python3 自定义节点 (路线 A 在 EVENT_TIME 上的应用).

        生成 3 节点 DAG: TRIGGER_NODE(EVENT_TIME, eventJobConfig.cronList=[cron_expression])
          → CUSTOM_CODE_NODE(PYTHON3) → END_NODE.

        入参:
          - cron_expression: Quartz cron 标准 7 段 (秒 分 时 日 月 周 年), 例 "0 00 20 ? * FRI"
          - python_code: 同 create_form_event_with_python_code
          - job_trigger_type: ONCE_EXECUTE (一次) / REPEAT_EXECUTE (重复, 默认)
          - start_time: "YYYY-MM-DD HH:mm:ss", 留空用当前时间
          - end_time: 同上, 默认 2159-12-31

        ⚠️ EVENT_TIME 触发节点没 triggerType / triggerWay / triggerEnv / triggerFormId.
        """
        if not (apaas_app_id.strip() and event_name.strip() and cron_expression.strip() and python_code.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + event_name + cron_expression + python_code 都必填"}
        if job_trigger_type not in ("ONCE_EXECUTE", "REPEAT_EXECUTE"):
            return {"ok": False, "error_code": "INVALID_JOB_TYPE",
                    "message": "job_trigger_type 必须 ONCE_EXECUTE 或 REPEAT_EXECUTE"}
        if "definesys" not in python_code or "invoke" not in python_code:
            return {"ok": False, "error_code": "INVALID_PYTHON_CODE",
                    "message": "python_code 必须含 `import definesys` + `def invoke(): ...`"}

        import datetime as _dt
        if not start_time.strip():
            start_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        async def _do(c):
            from uuid import uuid4
            create_resp = await c.create_business_event(
                apaas_app_id.strip(), event_name.strip(), event_type="EVENT_TIME",
            )
            event_id = create_resp.get("id") or create_resp.get("eventId")
            if not event_id:
                raise Exception(f"创建事件 stub 失败: {create_resp}")

            data = await c.get_business_event_detail(event_id, apaas_app_id.strip())
            if not isinstance(data, dict):
                raise Exception(f"detail 不是 dict: {type(data)}")

            trigger_node_id = uuid4().hex
            custom_node_id = uuid4().hex
            end_node_id = uuid4().hex

            data["triggerNodeNd"] = {
                "nodeId": trigger_node_id,
                "nodeName": "定时触发",
                "nextNodeId": [custom_node_id],
                "nodeType": "TRIGGER_NODE",
                "triggerTypeName": "",
                "triggerBocCode": "",
                "triggerFormName": "",
                "buttonName": "",
                "beforeAndAfterDataFlag": False,
                "triggerBuriedPoint": "DISABLE",
                "boCodeBORelationProperties": {},
                "eventJobConfig": {
                    "jobTriggerType": job_trigger_type,
                    "cycleNumber": 1,
                    "cycleType": "",
                    "jobTriggerTime": "",
                    "startTime": start_time,
                    "endTime": end_time,
                    "cronList": [cron_expression.strip()],
                    "apaasTaskIds": [],
                    "syncUpdateTable": False,
                },
            }

            data["eventNodeNdList"] = [{
                "nodeId": custom_node_id,
                "nodeName": "AI 业务逻辑",
                "nodeType": "CUSTOM_CODE_NODE",
                "nextNodeId": [end_node_id],
                "relatedDataNodeId": trigger_node_id,
                "validateStatus": "success",
                "nodeDesc": "",
                "extResponse": "",
                "customCode": python_code.strip(),
                "customNodeEnv": "PYTHON3",
                "firstRules": [],
                "secondRules": [],
                "targetBocName": "",
                "tableConfigs": [],
                "filterConditionGroup": [],
                "boCodeBORelationProperties": {},
            }]

            data["endNode"] = {
                "nodeId": end_node_id,
                "nodeName": "结束节点",
                "nextNodeId": [],
                "nodeType": "END_NODE",
                "dataStatus": "COMPLETED",
            }

            saved = await c.save_business_event(data, apaas_app_id.strip())
            return {
                "event_id": event_id,
                "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else None,
                "cron": cron_expression,
            }

        ok, raw = await _with_client(env_id, "建定时 Python 事件", _do)
        if not ok:
            return raw
        return {
            "ok": True,
            "route": "TIME_PYTHON",
            "event_id": raw["event_id"],
            "event_name": event_name,
            "cron_expression": raw["cron"],
            "job_trigger_type": job_trigger_type,
            "intact_flag": raw.get("intact_flag"),
            "message": f"定时事件「{event_name}」已建 — id={raw['event_id']} cron={raw['cron']}",
        }


    _VALUE_CHANGE_CAPTURE_PATH = (
        "/Users/mars/Vibe Coding/apaas-builder-ai/"
        "docs/captures/business-event-save-captured-1779695560.json"
    )
    _VALUE_CHANGE_CAPTURE_FORM_ID = "6a1272e174cfbc26cbf1e15c"   # 借阅记录 form (capture 来源)
    _VALUE_CHANGE_CACHED_TEMPLATE: dict | None = None


    def _load_value_change_template() -> dict:
        """读 capture template (lazy, 缓存). 2026-05-25 用户手动建事件抓的真 schema."""
        global _VALUE_CHANGE_CACHED_TEMPLATE
        if _VALUE_CHANGE_CACHED_TEMPLATE is None:
            import json as _j
            with open(_VALUE_CHANGE_CAPTURE_PATH, encoding="utf-8") as f:
                _VALUE_CHANGE_CACHED_TEMPLATE = _j.load(f)
        return _VALUE_CHANGE_CACHED_TEMPLATE


    @mcp.tool()
    async def create_apaas_value_change_assignment_event(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        event_name: str,
        trigger_field_label: str,
        trigger_value: str,
        target_field_label: str,
        value_expression: str,
    ) -> dict:
        """🅳 一键建"字段值改变 → 自动赋值"事件 — 用户最高频的"X 改成 Y 时填 Z" 场景.

        例: 借阅状态=已归还 时, 自动填归还日期=当前时间
            create_apaas_value_change_assignment_event(
              env_id=49, apaas_app_id="846...", form_id="6a1...",
              event_name="归还时自动填归还日期",
              trigger_field_label="借阅状态",   trigger_value="已归还",
              target_field_label="归还日期",   value_expression="${dateNow}",
            )

        内部实现 (2026-05-25 v3, capture-as-template):
          1. 加载用户手抓的真实 save body 当 template (含完整 boCodeBORelationProperties 19 字段)
          2. list_apaas_form_components 拿字段 (label → uuid + bocCode + 字典选项)
          3. 解析字典 (借阅状态='已归还' → returned_)
          4. create_business_event stub → 拿 event_id
          5. 深拷 template + 替换: id/eventName/eventCode/3 nodeId + trigger 字段 + assignment 字段 + value
          6. save → 立刻 get_detail 验证持久化, 失败回滚

        value_expression 支持:
          - "${dateNow}"   当前时间 (用 capture 的 formula record verbatim)
          - 字面值如 "已审批"  (filterType=COMMON, filterDisplayValue={})
          - 其他公式 (${userName} 等) 暂不支持 — 需要先创建对应 formula record

        ⚠️ 限制: 当前 template 绑死借阅记录 form_id `6a1272e174cfbc26cbf1e15c`,
           因为 boCodeBORelationProperties 含该 form 全 19 字段元数据 (含 boId 等不可造的字段).
           其他 form 用户先在平台 UI 配一个事件 + 我抓 capture 后再加 template.
        """
        import uuid as _uuid
        import copy as _copy

        if not all([apaas_app_id.strip(), form_id.strip(), event_name.strip(),
                    trigger_field_label.strip(), trigger_value.strip(),
                    target_field_label.strip(), value_expression.strip()]):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "8 个参数都必填"}

        # 限制: 仅借阅记录 form 有 template
        if form_id.strip() != _VALUE_CHANGE_CAPTURE_FORM_ID:
            return {
                "ok": False,
                "error_code": "FORM_TEMPLATE_NOT_FOUND",
                "message": (
                    f"目前仅借阅记录 form_id={_VALUE_CHANGE_CAPTURE_FORM_ID} 有 schema template "
                    f"(2026-05-25 用户手动建事件抓的). 你给的 form_id={form_id} 还没采集 template. "
                    "解决方案: 在平台 UI 给该 form 手动建一个 VALUE_CHANGE 事件后我能抓 capture 加 template."
                ),
            }

        async def _do(c):
            # 1. 拿表单字段 — label → uuid + bocCode + 字典选项
            comps = await c.query_form_components(apaas_app_id.strip(), form_id.strip())
            if not isinstance(comps, list):
                raise Exception(f"表单 {form_id} 没返字段列表")

            def _find(label):
                for cc in comps:
                    if not isinstance(cc, dict):
                        continue
                    if (cc.get("label") or cc.get("componentName") or "") == label:
                        return cc
                return None

            trig = _find(trigger_field_label)
            if not trig:
                raise Exception(
                    f"表单里找不到名为「{trigger_field_label}」的字段; "
                    f"可选: {[c.get('label') for c in comps if isinstance(c, dict)]}"
                )
            tgt = _find(target_field_label)
            if not tgt:
                raise Exception(f"表单里找不到名为「{target_field_label}」的字段")

            trig_uuid = trig.get("uuid") or ""
            trig_boc = trig.get("bocCode") or trig.get("boCode") or ""
            trig_bo_type = trig.get("businessObjectComponentType") or "BOF_TEXT"
            tgt_boc = tgt.get("bocCode") or tgt.get("boCode") or ""
            tgt_bo_type = tgt.get("businessObjectComponentType") or "BOF_DATE"

            # 2. 触发字段是字典/下拉时, 解析 trigger_value 到 dict code (如 "已归还" → "returned_")
            actual_trigger_value = trigger_value.strip()
            dict_opts = (trig.get("dictionaryChooseOptions")
                          or trig.get("dictionary_choose_options")
                          or trig.get("chooseOptions")
                          or [])
            if dict_opts and isinstance(dict_opts, list):
                for opt in dict_opts:
                    if not isinstance(opt, dict):
                        continue
                    lbl = str(opt.get("label") or opt.get("name") or "")
                    # 平台字典选项实证字段优先级: id > value > code (id 是 dict code 真值, 如 returned_)
                    val = str(opt.get("id") or opt.get("value") or opt.get("code") or "")
                    if not val:
                        continue
                    if lbl == trigger_value or val == trigger_value:
                        actual_trigger_value = val
                        break

            # 3. 拷 capture template 当蓝本
            body = _copy.deepcopy(_load_value_change_template())

            # 4. create stub event 拿 event_id
            stub = await c.create_business_event(
                apaas_app_id.strip(), event_name.strip(), event_type="EVENT_VALUE_CHANGE",
            )
            event_id = (stub.get("id") or stub.get("eventId") or "") if isinstance(stub, dict) else ""
            if not event_id:
                raise Exception(f"stub 创建没拿到 event_id: {stub}")

            # 5. 在 template 上做替换
            # 顶层
            body["id"] = event_id
            body["eventName"] = event_name.strip()
            body["eventCode"] = _uuid.uuid4().hex
            body["objectVersionNumber"] = 1
            # 删 audit (服务端重填)
            for k in ("createdBy", "creationDate", "lastUpdatedBy", "lastUpdateDate",
                      "owner", "tenantId", "editLockDto"):
                body.pop(k, None)

            # 3 个新 nodeId 避免冲突
            new_trig_id = _uuid.uuid4().hex
            new_assign_id = _uuid.uuid4().hex
            new_end_id = _uuid.uuid4().hex

            # triggerNodeNd 改 nodeId + 监听字段 + 触发条件
            trig_node = body["triggerNodeNd"]
            trig_node["nodeId"] = new_trig_id
            trig_node["nextNodeId"] = [new_assign_id]
            trig_node["componentUuid"] = trig_uuid
            trig_node["boCode"] = trig_boc
            # filterConditionGroupList 嵌套结构: selectorFilterConditionList[0].filterInputs[0].filterParams[0].filterValue
            try:
                cond = trig_node["filterConditionGroupList"][0]["selectorFilterConditionList"][0]
                cond["uuid"] = trig_uuid
                cond["boCode"] = trig_boc
                cond["businessObjectComponentType"] = trig_bo_type
                cond["filterInputs"][0]["filterParams"][0]["filterValue"] = actual_trigger_value
            except (KeyError, IndexError) as e:
                raise Exception(f"template filterConditionGroupList 结构异常: {e}")

            # eventNodeNdList[0] (ASSIGNMENT_NODE) 改 nodeId + target 字段 + 值
            assign_node = body["eventNodeNdList"][0]
            assign_node["nodeId"] = new_assign_id
            assign_node["nextNodeId"] = [new_end_id]
            assign_node["relatedDataNodeId"] = new_trig_id
            try:
                rule = assign_node["firstRules"][0]
                rule["uuid"] = tgt_boc
                rule["boCode"] = tgt_boc
                rule["businessObjectComponentType"] = tgt_bo_type
                fparam = rule["filterInputs"][0]["filterParams"][0]
                ve = value_expression.strip()
                if ve == "${dateNow}":
                    # 公式: 保留 template 里捕获的 formula record id + filterDisplayValue verbatim
                    # (filterValue 是 formula record 24hex id, filterDisplayValue 是 formula 内容缓存)
                    pass  # 不改, template 里就是这个
                else:
                    # 字面值: filterType=COMMON, filterDisplayValue={}, filterValue=ve
                    fparam["filterType"] = "COMMON"
                    fparam["filterValue"] = ve
                    fparam["filterDisplayValue"] = {}
                    fparam["filterBoComponentType"] = tgt_bo_type
            except (KeyError, IndexError) as e:
                raise Exception(f"template ASSIGNMENT_NODE.firstRules 结构异常: {e}")

            # endNode 只改 nodeId
            body["endNode"]["nodeId"] = new_end_id

            # 6. save + 立刻验证
            try:
                saved = await c.save_business_event(body, apaas_app_id.strip())
            except Exception as save_exc:
                try:
                    await c.delete_business_event(event_id, apaas_app_id.strip())
                except Exception:
                    pass
                raise Exception(f"save 失败已回滚 stub: {save_exc}")

            try:
                verify = await c.get_business_event_detail(event_id, apaas_app_id.strip())
                verify_trig = (verify or {}).get("triggerNodeNd") or {}
                verify_nodes = (verify or {}).get("eventNodeNdList") or []
                verified = (
                    verify_trig.get("nodeType") == "TRIGGER_NODE"
                    and verify_trig.get("triggerType") == "VALUE_CHANGE"
                    and len(verify_nodes) >= 1
                    and verify_nodes[0].get("nodeType") == "ASSIGNMENT_NODE"
                )
            except Exception:
                verified = False
                verify_trig = {}
                verify_nodes = []

            if not verified:
                try:
                    await c.delete_business_event(event_id, apaas_app_id.strip())
                except Exception:
                    pass
                raise Exception(
                    "save 返 ok 但 get_detail 验证不匹配 (stub 已回滚). "
                    "可能 template 结构跟当前 form/字段不兼容."
                )

            return {
                "event_id": event_id,
                "intact_flag": saved.get("intactFlag") if isinstance(saved, dict) else True,
                "actual_trigger_value": actual_trigger_value,
                "verified_trigger_type": verify_trig.get("triggerType"),
                "verified_nodes_count": len(verify_nodes),
            }

        ok, raw = await _with_client(env_id, "建字段改变赋值事件", _do)
        if not ok:
            return raw
        return {
            "ok": True,
            "route": "D_VALUE_CHANGE_ASSIGNMENT",
            "event_id": raw["event_id"],
            "event_name": event_name,
            "trigger_field": trigger_field_label,
            "trigger_value": raw["actual_trigger_value"],
            "target_field": target_field_label,
            "value_expression": value_expression,
            "intact_flag": raw.get("intact_flag"),
            "message": (f"事件「{event_name}」已创建: "
                        f"当「{trigger_field_label}」=「{raw['actual_trigger_value']}」时, "
                        f"自动设「{target_field_label}」=「{value_expression}」"),
        }

    tools = {
        "list_apaas_business_events": list_apaas_business_events,
        "get_apaas_business_event_detail": get_apaas_business_event_detail,
        "create_apaas_business_event": create_apaas_business_event,
        "save_apaas_business_event": save_apaas_business_event,
        "delete_apaas_business_event": delete_apaas_business_event,
        "list_apaas_form_menus_for_event": list_apaas_form_menus_for_event,
        "list_apaas_business_events_in_tenant": list_apaas_business_events_in_tenant,
        "query_apaas_business_event_trees": query_apaas_business_event_trees,
        "list_apaas_business_event_execution_history": list_apaas_business_event_execution_history,
        "create_form_event_with_python_code": create_form_event_with_python_code,
        "create_time_event_with_python_code": create_time_event_with_python_code,
        "create_apaas_value_change_assignment_event": create_apaas_value_change_assignment_event,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
