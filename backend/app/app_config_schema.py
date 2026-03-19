"""
aPaaS 应用配置 Schema

标准化的应用配置格式，AI 只需生成符合此 schema 的配置文件
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class DictOption(BaseModel):
    """字典选项"""
    name: str = Field(..., description="选项名称")
    code: str = Field(..., description="选项编码")


class DictConfig(BaseModel):
    """数据字典配置"""
    name: str = Field(..., description="字典名称")
    code: str = Field(..., description="字典编码")
    options: List[DictOption] = Field(default_factory=list, description="字典选项")


class FieldConfig(BaseModel):
    """模型字段配置"""
    name: str = Field(..., description="字段名称")
    code: str = Field(..., description="字段编码")
    type: Literal[
        "单行输入", "多行输入", "数字输入", "金额", "手机号码", "电子邮箱",
        "日期时间", "单据号", "下拉单选", "下拉多选", "数据选择器",
        "人员选择", "附件上传", "开关", "地理位置"
    ] = Field(..., description="字段类型")
    dict: Optional[str] = Field(None, description="关联字典编码（下拉选择类型必填）")
    ref_model: Optional[str] = Field(None, description="关联模型编码（数据选择器必填）")
    required: bool = Field(False, description="是否必填")
    description: Optional[str] = Field(None, description="字段描述")


class ModelConfig(BaseModel):
    """数据模型配置"""
    name: str = Field(..., description="模型名称")
    code: str = Field(..., description="模型编码")
    description: Optional[str] = Field(None, description="模型描述")
    fields: List[FieldConfig] = Field(..., description="字段列表")


class ComponentConfig(BaseModel):
    """表单组件配置"""
    field: str = Field(..., description="字段编码（对应 ModelConfig.fields[].code）")
    required: Optional[bool] = Field(None, description="是否必填（覆盖字段默认值）")
    placeholder: Optional[str] = Field(None, description="占位符文本")
    hidden: Optional[bool] = Field(None, description="是否隐藏")
    readonly: Optional[bool] = Field(None, description="是否只读")


class FormConfig(BaseModel):
    """表单配置"""
    name: str = Field(..., description="表单名称")
    model: str = Field(..., description="关联模型编码")
    components: List[ComponentConfig] = Field(..., description="表单组件列表")
    list_query_fields: Optional[List[str]] = Field(None, description="列表页查询字段")
    list_display_fields: Optional[List[str]] = Field(None, description="列表页显示字段")


class AppConfig(BaseModel):
    """应用配置（顶层）"""
    name: str = Field(..., description="应用名称")
    code: Optional[str] = Field(None, description="应用编码（可选，自动生成）")
    description: Optional[str] = Field(None, description="应用描述")
    dicts: List[DictConfig] = Field(default_factory=list, description="数据字典列表")
    models: List[ModelConfig] = Field(..., description="数据模型列表")
    forms: List[FormConfig] = Field(..., description="表单列表")


# YAML 示例
EXAMPLE_YAML = """
name: 资产管理系统
description: 企业资产管理应用

dicts:
  - name: 资产类别
    code: asset_category
    options:
      - name: 电子设备
        code: electronic
      - name: 办公家具
        code: furniture
      - name: 车辆
        code: vehicle

  - name: 使用状态
    code: usage_status
    options:
      - name: 在用
        code: in_use
      - name: 闲置
        code: idle

models:
  - name: 资产
    code: asset
    description: 资产主数据
    fields:
      - name: 资产名称
        code: asset_name
        type: 单行输入
        required: true
      - name: 资产编号
        code: asset_no
        type: 单行输入
        required: true
      - name: 资产类别
        code: category
        type: 下拉单选
        dict: asset_category
        required: true
      - name: 购买日期
        code: purchase_date
        type: 日期时间
      - name: 购买金额
        code: purchase_amount
        type: 金额
      - name: 使用状态
        code: usage_status
        type: 下拉单选
        dict: usage_status
      - name: 使用部门
        code: department
        type: 单行输入
      - name: 责任人
        code: owner
        type: 人员选择

forms:
  - name: 资产
    model: asset
    components:
      - field: asset_name
        required: true
        placeholder: 请输入资产名称
      - field: asset_no
        required: true
      - field: category
        required: true
      - field: purchase_date
      - field: purchase_amount
      - field: usage_status
      - field: department
      - field: owner
    list_query_fields:
      - asset_name
      - asset_no
      - category
    list_display_fields:
      - asset_name
      - asset_no
      - category
      - purchase_date
      - usage_status
"""


# JSON Schema（用于 AI 生成配置时的参考）
JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["name", "models", "forms"],
    "properties": {
        "name": {"type": "string", "description": "应用名称"},
        "code": {"type": "string", "description": "应用编码（可选）"},
        "description": {"type": "string", "description": "应用描述"},
        "dicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "code"],
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "code"],
                            "properties": {
                                "name": {"type": "string"},
                                "code": {"type": "string"}
                            }
                        }
                    }
                }
            }
        },
        "models": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "code", "fields"],
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "code", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "code": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "单行输入", "多行输入", "数字输入", "金额",
                                        "手机号码", "电子邮箱", "日期时间", "单据号",
                                        "下拉单选", "下拉多选", "数据选择器",
                                        "人员选择", "附件上传", "开关", "地理位置"
                                    ]
                                },
                                "dict": {"type": "string"},
                                "ref_model": {"type": "string"},
                                "required": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        },
        "forms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "model", "components"],
                "properties": {
                    "name": {"type": "string"},
                    "model": {"type": "string"},
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["field"],
                            "properties": {
                                "field": {"type": "string"},
                                "required": {"type": "boolean"},
                                "placeholder": {"type": "string"},
                                "hidden": {"type": "boolean"},
                                "readonly": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        }
    }
}
