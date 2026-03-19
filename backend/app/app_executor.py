"""
aPaaS 应用执行引擎

负责解析标准配置并调用 aPaaS API 创建应用
AI 不需要写这部分代码，只需生成符合 schema 的配置
"""

import asyncio
import random
import string
import re
import httpx
from typing import Dict, List, Optional
from app.apaas_client import APaaSClient
from app.app_config_schema import AppConfig, DictConfig, ModelConfig, FormConfig

import logging

logger = logging.getLogger(__name__)


class AppExecutor:
    """应用执行引擎"""

    # 字段类型映射
    FIELD_TYPE_MAP = {
        "单行输入": "STRING",
        "多行输入": "BIG_TEXT",
        "数字输入": "NUM",
        "金额": "NUM",
        "手机号码": "STRING",
        "电子邮箱": "STRING",
        "日期时间": "DATE",
        "单据号": "STRING",
        "下拉单选": "STRING",
        "下拉多选": "STRING",
        "数据选择器": "STRING",
        "人员选择": "STRING",
        "附件上传": "STRING",
        "开关": "STRING",
        "地理位置": "STRING"
    }

    # 组件类型映射
    COMPONENT_TYPE_MAP = {
        "单行输入": "FORM_TEXT_INPUT",
        "多行输入": "FORM_TEXTAREA_INPUT",
        "数字输入": "FORM_NUMBER_INPUT",
        "金额": "FORM_MONEY_INPUT",
        "手机号码": "FORM_PHONE_INPUT",
        "电子邮箱": "FORM_EMAIL_INPUT",
        "日期时间": "FORM_DATEPICK_INPUT",
        "单据号": "FORM_DOCUMENT_NUMBER",
        "下拉单选": "FORM_SELECT_INPUT_SINGLE",
        "下拉多选": "FORM_SELECT_INPUT",
        "数据选择器": "FORM_DATA_SELECTOR_SINGLE",
        "人员选择": "FORM_PEOPLE_SELECT",
        "附件上传": "FORM_FILE_UPLOAD",
        "开关": "FORM_SWITCH_SELECT",
        "地理位置": "FORM_WIDGET_LOCATION"
    }

    # Reserved Words（数据库保留字）
    RESERVED_WORDS = {
        'name', 'status', 'type', 'order', 'group', 'key', 'value', 'index',
        'table', 'column', 'select', 'insert', 'update', 'delete', 'create',
        'drop', 'alter', 'from', 'where', 'join', 'on', 'in', 'is', 'not',
        'null', 'and', 'or', 'like', 'between', 'having', 'limit', 'offset',
        'desc', 'asc', 'set', 'into', 'values', 'as', 'by', 'all', 'any',
        'exists', 'case', 'when', 'then', 'else', 'end', 'if', 'for', 'each',
        'action', 'result', 'level', 'role', 'user', 'date', 'time', 'timestamp',
        'comment', 'location', 'email', 'phone', 'address', 'account', 'model',
        'unit', 'category', 'manager', 'priority', 'amount', 'currency',
        'operator', 'spec', 'id', 'owner', 'department', 'data', 'file',
        'text', 'number', 'code', 'description', 'title', 'content',
    }

    def __init__(self, client: APaaSClient):
        self.client = client
        self.progress = {}

    @staticmethod
    def _safe_code(code: str) -> str:
        """清理编码：只保留字母数字下划线，处理保留字"""
        c = re.sub(r'[^a-zA-Z0-9_]', '_', code)
        if c.lower() in AppExecutor.RESERVED_WORDS:
            c = f"f_{c}"
        return c

    async def execute(self, config: AppConfig) -> Dict:
        """执行完整的应用创建流程"""
        logger.info(f"开始创建应用: {config.name}")

        # Phase 1: 创建应用
        await self._phase1_create_app(config)

        # Phase 2: 创建数据字典
        if config.dicts:
            await self._phase2_create_dicts(config.dicts)

        # Phase 3: 创建数据模型
        await self._phase3_create_models(config.models)

        # Phase 4: 创建表单
        await self._phase4_create_forms(config.forms, config.models)

        logger.info(f"✓ 应用创建完成: {config.name}")
        return self.progress

    async def _phase1_create_app(self, config: AppConfig):
        """Phase 1: 创建应用"""
        logger.info("=== Phase 1: 创建应用 ===")

        # 生成唯一后缀
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

        # 生成 app_code
        if config.code:
            app_code = f"{config.code}-{suffix}"
        else:
            # 中文转拼音或使用通用名称
            import re
            # 移除所有非ASCII字符
            base_code = re.sub(r'[^\x00-\x7F]+', '', config.name.lower())
            if not base_code:
                # 如果全是中文，使用通用名称
                base_code = "app"
            base_code = base_code.replace(' ', '-').strip('-')
            app_code = f"{base_code}-{suffix}" if base_code else f"app-{suffix}"

        # 创建应用
        result = await self.client.create_app(
            app_name=config.name,
            app_code=app_code,
            description=config.description or f"{config.name}应用"
        )

        app_id = str(result.get("id", result))

        self.progress = {
            "app_id": app_id,
            "app_code": app_code,
            "suffix": suffix,
            "dict_codes": {},
            "dict_ids": {},
            "model_codes": {},
            "model_ids": {},
            "form_ids": {}
        }

        logger.info(f"✓ 应用创建成功 - App ID: {app_id}, Code: {app_code}")

    async def _phase2_create_dicts(self, dicts: List[DictConfig]):
        """Phase 2: 创建数据字典"""
        logger.info("=== Phase 2: 创建数据字典 ===")

        app_id = self.progress['app_id']
        suffix = self.progress['suffix']

        # Step 1: 创建字典（不含选项）
        dict_payload = []
        for d in dicts:
            dict_code = f"{self._safe_code(d.code)}_{suffix}"
            dict_payload.append({
                "appId": app_id,
                "dictionaryCode": dict_code,
                "dictionaryName": d.name,
                "dictionaryOptions": []
            })
            self.progress['dict_codes'][d.code] = dict_code

        await self.client.create_dicts(app_id, dict_payload)
        logger.info(f"✓ 创建了 {len(dict_payload)} 个字典")

        # Step 2: 查询字典 ID 并添加选项
        headers = self.client._get_headers(app_id)
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
            response = await http_client.post(
                f"{self.client.base_url}/xdap-app/dataDictionary/query/dataDictionaryList",
                headers=headers,
                json={"keyword": "", "appId": app_id}
            )
            result = response.json()
            dict_list = result.get("data", {}).get("list", [])

            # 如果 list 为空，尝试从 table 获取
            if not dict_list:
                dict_list = result.get("table", [])

            logger.info(f"查询到 {len(dict_list)} 个字典")

            for d in dicts:
                dict_code = self.progress['dict_codes'][d.code]
                dict_obj = next((x for x in dict_list if x.get("dictionaryCode") == dict_code), None)

                if dict_obj:
                    dict_id = dict_obj.get("id")
                    self.progress['dict_ids'][d.code] = dict_id
                    logger.info(f"  字典 {d.name} ID: {dict_id}")

                    if d.options:
                        options_payload = []
                        for opt in d.options:
                            opt_code = f"{self._safe_code(opt.code)}_{suffix}"
                            options_payload.append({
                                "valueCode": opt_code,
                                "valueName": opt.name
                            })

                        await http_client.post(
                            f"{self.client.base_url}/xdap-app/dataDictionary/edit/dataDictionary",
                            headers=headers,
                            json={
                                "id": dict_id,
                                "dictionaryCode": dict_code,
                                "dictionaryName": d.name,
                                "dictionaryOptions": options_payload
                            }
                        )
                        logger.info(f"  ✓ {d.name}: 添加了 {len(options_payload)} 个选项")

    async def _phase3_create_models(self, models: List[ModelConfig]):
        """Phase 3: 创建数据模型"""
        logger.info("=== Phase 3: 创建数据模型 ===")

        app_id = self.progress['app_id']
        suffix = self.progress['suffix']

        data_models = []
        for model in models:
            model_code = f"{self._safe_code(model.code)}_{suffix}"
            self.progress['model_codes'][model.code] = model_code

            fields = []
            for field in model.fields:
                field_code = self._safe_code(field.code)
                field_type = self.FIELD_TYPE_MAP.get(field.type, 'STRING')

                logger.info(f"  字段: {field.name} ({field.code} → {field_code})")

                field_obj = {
                    "fieldName": field.name,
                    "fieldCode": field_code,
                    "fieldType": field_type,
                    "fieldDescription": field.type
                }
                fields.append(field_obj)

            data_models.append({
                "appId": app_id,
                "modelName": model.name,
                "modelCode": model_code,
                "modelDescription": model.description or "",
                "fields": fields
            })

        payload = {
            "appId": app_id,
            "datasourceId": "",
            "dataModels": data_models
        }

        await self.client.create_models(app_id, payload)
        logger.info(f"✓ 创建了 {len(data_models)} 个数据模型")

        # 查询模型 ID
        await self._query_model_ids(app_id)

    async def _query_model_ids(self, app_id: str):
        """查询模型 ID"""
        headers = self.client._get_headers(app_id)
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
            response = await http_client.post(
                f"{self.client.base_url}/xdap-app/dataModel/query/list",
                headers=headers,
                json={"appId": app_id}
            )
            result = response.json()
            model_list = result.get("data", {}).get("list", [])

            for orig_code, full_code in self.progress['model_codes'].items():
                model_obj = next((m for m in model_list if m.get("modelCode") == full_code), None)
                if model_obj:
                    self.progress['model_ids'][orig_code] = model_obj.get("id")

    async def _phase4_create_forms(self, forms: List[FormConfig], models: List[ModelConfig]):
        """Phase 4: 创建表单"""
        logger.info("=== Phase 4: 创建表单 ===")

        app_id = self.progress['app_id']
        suffix = self.progress['suffix']

        # 构建模型字段映射
        model_fields_map = {}
        for model in models:
            model_fields_map[model.code] = {f.code: f for f in model.fields}

        form_configs = []
        for form in forms:
            form_code = f"form_{self._safe_code(form.model)}_{suffix}"
            model_code = self.progress['model_codes'][form.model]

            # 构建表单组件
            form_components = []
            list_query_fields = []
            list_display_fields = []

            for comp in form.components:
                field_def = model_fields_map[form.model][comp.field]
                field_code = self._safe_code(comp.field)

                component = {
                    "componentType": self.COMPONENT_TYPE_MAP[field_def.type],
                    "label": field_def.name,
                    "modelField": f"{model_code}.{field_code}"
                }

                # 应用组件配置
                if comp.required is not None:
                    component["required"] = comp.required
                elif field_def.required:
                    component["required"] = True

                if comp.placeholder:
                    component["placeholder"] = comp.placeholder
                if comp.hidden:
                    component["hidden"] = comp.hidden
                if comp.readonly:
                    component["readOnly"] = comp.readonly

                # 处理下拉选择
                if field_def.type in ["下拉单选", "下拉多选"] and field_def.dict:
                    dict_id = self.progress['dict_ids'].get(field_def.dict)
                    dict_code = self.progress['dict_codes'].get(field_def.dict)

                    if dict_id and dict_code:
                        # 查询字典选项
                        dict_options = await self._get_dict_options(app_id, dict_code)

                        component["source"] = {
                            "type": "DICTIONARY_TYPE",
                            "id": dict_id
                        }
                        component["chooseOptions"] = dict_options
                        component["dictionaryChooseOptions"] = dict_options
                        component["chooseType"] = "SINGLE" if field_def.type == "下拉单选" else "MULTIPLE"
                        component["multicolor"] = False

                form_components.append(component)

                # 列表页字段
                if form.list_query_fields and comp.field in form.list_query_fields:
                    list_query_fields.append(f"{model_code}.{field_code}")
                if form.list_display_fields and comp.field in form.list_display_fields:
                    list_display_fields.append(f"{model_code}.{field_code}")

            # 如果未指定列表页字段，使用前几个字段
            if not list_query_fields:
                list_query_fields = [c["modelField"] for c in form_components[:3]]
            if not list_display_fields:
                list_display_fields = [c["modelField"] for c in form_components[:5]]

            form_config = {
                "formName": form.name,
                "formCode": form_code,
                "allModelCodes": [model_code],
                "formComponents": form_components,
                "listPageView": {
                    "queryConditions": list_query_fields,
                    "queryList": list_display_fields
                }
            }

            form_configs.append(form_config)

        await self.client.create_form_config(app_id, form_configs)
        logger.info(f"✓ 创建了 {len(form_configs)} 个表单")

    async def _get_dict_options(self, app_id: str, dict_code: str) -> list:
        """查询字典选项"""
        headers = self.client._get_headers(app_id)
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
            response = await http_client.post(
                f"{self.client.base_url}/xdap-app/dataDictionary/query/dataDictionaryList",
                headers=headers,
                json={"keyword": "", "appId": app_id}
            )
            result = response.json()
            dict_list = result.get("data", {}).get("list", [])
            if not dict_list:
                dict_list = result.get("table", [])

            # 找到对应的字典
            dict_obj = next((d for d in dict_list if d.get("dictionaryCode") == dict_code), None)
            if dict_obj and dict_obj.get("dictionaryOptions"):
                # 转换选项格式
                options = []
                for opt in dict_obj["dictionaryOptions"]:
                    options.append({
                        "id": opt.get("valueCode"),
                        "name": opt.get("valueName")
                    })
                return options
            return []
