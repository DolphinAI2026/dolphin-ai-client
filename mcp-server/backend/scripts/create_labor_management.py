"""
劳务管理系统 - 完整创建脚本
严格按 Skills 模式：字典 → 模型 → 表单 → 绑定字典 → 角色

用法: python -m scripts.create_labor_management
"""
import asyncio
import random
import string
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.apaas_client import APaaSClient
import httpx

# ============================================================
# 配置
# ============================================================
APP_ID = "821693297817812992"  # 填入你的应用 ID
SUFFIX = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

print(f"🔑 后缀: {SUFFIX}")


# ============================================================
# Step 1: 数据字典定义
# ============================================================
DICTS = [
    {
        "name": "批准书类型", "code": f"approval_type_{SUFFIX}",
        "options": [
            {"name": "委托派遣", "code": f"approval_type_1_{SUFFIX}"},
            {"name": "直接用工", "code": f"approval_type_2_{SUFFIX}"},
            {"name": "合作派遣", "code": f"approval_type_3_{SUFFIX}"},
        ]
    },
    {
        "name": "区域", "code": f"region_{SUFFIX}",
        "options": [
            {"name": "大陆", "code": f"region_mainland_{SUFFIX}"},
            {"name": "香港", "code": f"region_hk_{SUFFIX}"},
            {"name": "澳门", "code": f"region_mo_{SUFFIX}"},
        ]
    },
    {
        "name": "是否", "code": f"yes_no_{SUFFIX}",
        "options": [
            {"name": "是", "code": f"yes_{SUFFIX}"},
            {"name": "否", "code": f"no_{SUFFIX}"},
        ]
    },
    {
        "name": "签约类型", "code": f"sign_type_{SUFFIX}",
        "options": [
            {"name": "新签", "code": f"sign_new_{SUFFIX}"},
            {"name": "续约", "code": f"sign_renew_{SUFFIX}"},
        ]
    },
    {
        "name": "企业类型", "code": f"enterprise_type_{SUFFIX}",
        "options": [
            {"name": "香港企业", "code": f"ent_hk_{SUFFIX}"},
            {"name": "内地企业", "code": f"ent_mainland_{SUFFIX}"},
            {"name": "中外合资", "code": f"ent_jv_{SUFFIX}"},
            {"name": "外资独资", "code": f"ent_foreign_{SUFFIX}"},
            {"name": "其他", "code": f"ent_other_{SUFFIX}"},
        ]
    },
    {
        "name": "注册类型", "code": f"register_type_{SUFFIX}",
        "options": [
            {"name": "有限公司", "code": f"reg_limited_{SUFFIX}"},
            {"name": "无限公司", "code": f"reg_unlimited_{SUFFIX}"},
            {"name": "个体工商户", "code": f"reg_individual_{SUFFIX}"},
            {"name": "非盈利机构", "code": f"reg_nonprofit_{SUFFIX}"},
            {"name": "其他", "code": f"reg_other_{SUFFIX}"},
        ]
    },
    {
        "name": "证照类型", "code": f"biz_reg_type_{SUFFIX}",
        "options": [
            {"name": "营业执照", "code": f"biz_license_{SUFFIX}"},
            {"name": "商业登记证编号", "code": f"biz_hkreg_{SUFFIX}"},
        ]
    },
    {
        "name": "合作状态", "code": f"cooperation_status_{SUFFIX}",
        "options": [
            {"name": "合作中", "code": f"coop_active_{SUFFIX}"},
            {"name": "暂停合作", "code": f"coop_pause_{SUFFIX}"},
            {"name": "终止合作", "code": f"coop_end_{SUFFIX}"},
        ]
    },
    {
        "name": "合作方类型", "code": f"cooperator_type_{SUFFIX}",
        "options": [
            {"name": "劳务公司", "code": f"ctype_labor_{SUFFIX}"},
            {"name": "职业介绍所", "code": f"ctype_agency_{SUFFIX}"},
            {"name": "培训机构", "code": f"ctype_training_{SUFFIX}"},
            {"name": "保险公司", "code": f"ctype_insurance_{SUFFIX}"},
            {"name": "其他服务机构", "code": f"ctype_other_{SUFFIX}"},
        ]
    },
    {
        "name": "企业性质", "code": f"enterprise_nature_{SUFFIX}",
        "options": [
            {"name": "国企", "code": f"nat_state_{SUFFIX}"},
            {"name": "民企", "code": f"nat_private_{SUFFIX}"},
            {"name": "外企", "code": f"nat_foreign_{SUFFIX}"},
            {"name": "合资", "code": f"nat_jv_{SUFFIX}"},
            {"name": "个体", "code": f"nat_individual_{SUFFIX}"},
            {"name": "非盈利机构", "code": f"nat_nonprofit_{SUFFIX}"},
        ]
    },
    {
        "name": "企业状态", "code": f"enterprise_status_{SUFFIX}",
        "options": [
            {"name": "有效", "code": f"status_active_{SUFFIX}"},
            {"name": "失效", "code": f"status_inactive_{SUFFIX}"},
            {"name": "未启用", "code": f"status_disabled_{SUFFIX}"},
        ]
    },
    {
        "name": "资质类型", "code": f"qual_type_{SUFFIX}",
        "options": [
            {"name": "劳务派遣经营许可", "code": f"qual_dispatch_{SUFFIX}"},
            {"name": "职业介绍所牌照", "code": f"qual_agency_{SUFFIX}"},
            {"name": "人力资源服务许可", "code": f"qual_hr_{SUFFIX}"},
            {"name": "对外劳务合作资格", "code": f"qual_overseas_{SUFFIX}"},
            {"name": "其他", "code": f"qual_other_{SUFFIX}"},
        ]
    },
    {
        "name": "资质状态", "code": f"qual_status_{SUFFIX}",
        "options": [
            {"name": "有效", "code": f"qstat_active_{SUFFIX}"},
            {"name": "过期", "code": f"qstat_expired_{SUFFIX}"},
            {"name": "注销", "code": f"qstat_revoked_{SUFFIX}"},
        ]
    },
    {
        "name": "协议类型", "code": f"agreement_type_{SUFFIX}",
        "options": [
            {"name": "劳务派遣协议", "code": f"agr_dispatch_{SUFFIX}"},
            {"name": "合作服务协议", "code": f"agr_service_{SUFFIX}"},
            {"name": "其他", "code": f"agr_other_{SUFFIX}"},
        ]
    },
    {
        "name": "协议状态", "code": f"agreement_status_{SUFFIX}",
        "options": [
            {"name": "生效", "code": f"agr_active_{SUFFIX}"},
            {"name": "失效", "code": f"agr_inactive_{SUFFIX}"},
            {"name": "待审批", "code": f"agr_pending_{SUFFIX}"},
        ]
    },
    {
        "name": "适用业务类型", "code": f"business_type_{SUFFIX}",
        "options": [
            {"name": "配额申请对接", "code": f"biz_quota_{SUFFIX}"},
            {"name": "人员派遣", "code": f"biz_dispatch_{SUFFIX}"},
            {"name": "证照代办", "code": f"biz_cert_{SUFFIX}"},
            {"name": "培训服务", "code": f"biz_training_{SUFFIX}"},
            {"name": "其他", "code": f"biz_other_{SUFFIX}"},
        ]
    },
    {
        "name": "币种", "code": f"f_currency_{SUFFIX}",
        "options": [
            {"name": "人民币", "code": f"cny_{SUFFIX}"},
            {"name": "港币", "code": f"hkd_{SUFFIX}"},
        ]
    },
    {
        "name": "提成方式", "code": f"commission_type_{SUFFIX}",
        "options": [
            {"name": "比例提成", "code": f"comm_rate_{SUFFIX}"},
            {"name": "固定金额提成", "code": f"comm_fixed_{SUFFIX}"},
            {"name": "阶梯提成", "code": f"comm_ladder_{SUFFIX}"},
        ]
    },
    {
        "name": "支付频率", "code": f"settlement_cycle_{SUFFIX}",
        "options": [
            {"name": "按次", "code": f"cycle_per_{SUFFIX}"},
            {"name": "按月", "code": f"cycle_month_{SUFFIX}"},
            {"name": "一次性支付", "code": f"cycle_once_{SUFFIX}"},
            {"name": "其他频率", "code": f"cycle_other_{SUFFIX}"},
        ]
    },
    {
        "name": "支付方式", "code": f"payment_method_{SUFFIX}",
        "options": [
            {"name": "银行转账", "code": f"pay_bank_{SUFFIX}"},
            {"name": "电子汇款", "code": f"pay_wire_{SUFFIX}"},
            {"name": "其他", "code": f"pay_other_{SUFFIX}"},
        ]
    },
    {
        "name": "支付比例", "code": f"pay_rate_way_{SUFFIX}",
        "options": [
            {"name": "全额支付", "code": f"payrate_full_{SUFFIX}"},
            {"name": "部分支付", "code": f"payrate_partial_{SUFFIX}"},
        ]
    },
    {
        "name": "结算周期状态", "code": f"pay_status_{SUFFIX}",
        "options": [
            {"name": "生效", "code": f"pstat_active_{SUFFIX}"},
            {"name": "失效", "code": f"pstat_inactive_{SUFFIX}"},
        ]
    },
    {
        "name": "批准书状态", "code": f"approval_status_{SUFFIX}",
        "options": [
            {"name": "有效", "code": f"apstat_active_{SUFFIX}"},
            {"name": "过期", "code": f"apstat_expired_{SUFFIX}"},
            {"name": "作废", "code": f"apstat_void_{SUFFIX}"},
        ]
    },
    {
        "name": "雇佣期", "code": f"hire_period_{SUFFIX}",
        "options": [
            {"name": "6个月", "code": f"hire_6m_{SUFFIX}"},
            {"name": "12个月", "code": f"hire_12m_{SUFFIX}"},
            {"name": "24个月", "code": f"hire_24m_{SUFFIX}"},
        ]
    },
    {
        "name": "工种", "code": f"job_type_{SUFFIX}",
        "options": [
            {"name": "技术员", "code": f"job_tech_{SUFFIX}"},
            {"name": "工地督导", "code": f"job_supervisor_{SUFFIX}"},
            {"name": "高级督导", "code": f"job_senior_{SUFFIX}"},
            {"name": "护工", "code": f"job_nurse_{SUFFIX}"},
            {"name": "厨师", "code": f"job_chef_{SUFFIX}"},
        ]
    },
    {
        "name": "配额分配状态", "code": f"detail_alloc_status_{SUFFIX}",
        "options": [
            {"name": "未分配", "code": f"alloc_none_{SUFFIX}"},
            {"name": "部分分配", "code": f"alloc_partial_{SUFFIX}"},
            {"name": "全部分配", "code": f"alloc_full_{SUFFIX}"},
            {"name": "已回收", "code": f"alloc_recycled_{SUFFIX}"},
        ]
    },
    {
        "name": "合作方财务计算", "code": f"fa_calculation_{SUFFIX}",
        "options": [
            {"name": "净额", "code": f"fa_net_{SUFFIX}"},
            {"name": "全额", "code": f"fa_gross_{SUFFIX}"},
        ]
    },
    {
        "name": "规则状态", "code": f"rule_status_{SUFFIX}",
        "options": [
            {"name": "有效", "code": f"rule_active_{SUFFIX}"},
            {"name": "暂停", "code": f"rule_pause_{SUFFIX}"},
            {"name": "作废", "code": f"rule_void_{SUFFIX}"},
        ]
    },
    {
        "name": "支付周期方式", "code": f"pay_cycle_way_{SUFFIX}",
        "options": [
            {"name": "一次性支付", "code": f"pcw_once_{SUFFIX}"},
            {"name": "季度", "code": f"pcw_quarter_{SUFFIX}"},
            {"name": "月度", "code": f"pcw_month_{SUFFIX}"},
            {"name": "半年", "code": f"pcw_halfyear_{SUFFIX}"},
            {"name": "年度", "code": f"pcw_year_{SUFFIX}"},
        ]
    },
    {
        "name": "行业类型", "code": f"industry_type_{SUFFIX}",
        "options": [
            {"name": "建造业", "code": f"ind_construction_{SUFFIX}"},
            {"name": "运输业", "code": f"ind_transport_{SUFFIX}"},
            {"name": "制造业", "code": f"ind_manufacture_{SUFFIX}"},
            {"name": "食品及饮品工业", "code": f"ind_food_{SUFFIX}"},
            {"name": "其他", "code": f"ind_other_{SUFFIX}"},
        ]
    },
    {
        "name": "合作范围", "code": f"cooperation_scope_{SUFFIX}",
        "options": [
            {"name": "配额申请对接", "code": f"scope_quota_{SUFFIX}"},
            {"name": "人员派遣", "code": f"scope_dispatch_{SUFFIX}"},
            {"name": "培训服务", "code": f"scope_training_{SUFFIX}"},
            {"name": "保险代办", "code": f"scope_insurance_{SUFFIX}"},
            {"name": "证件办理", "code": f"scope_cert_{SUFFIX}"},
            {"name": "其他", "code": f"scope_other_{SUFFIX}"},
        ]
    },
]


# ============================================================
# Step 2: 数据模型定义（按创建顺序！被引用的先创建）
# ============================================================
MODELS = [
    # --- 基础数据 ---
    {
        "modelName": "行业",
        "modelCode": f"industry_{SUFFIX}",
        "fields": [
            {"fieldName": "批准书类型", "fieldCode": "approval_type", "fieldType": "STRING"},
            {"fieldName": "行业", "fieldCode": "f_industry", "fieldType": "STRING"},
            {"fieldName": "签发单位", "fieldCode": "issuance_of_units", "fieldType": "STRING"},
            {"fieldName": "配额批准部门联系邮箱", "fieldCode": "issuance_of_units_mail", "fieldType": "STRING"},
            {"fieldName": "负责人姓名", "fieldCode": "responsible_person", "fieldType": "STRING"},
            {"fieldName": "负责人电话", "fieldCode": "responsible_phone", "fieldType": "STRING"},
            {"fieldName": "适用区域", "fieldCode": "service_area", "fieldType": "STRING"},
            {"fieldName": "可替换次数", "fieldCode": "able_change", "fieldType": "NUM"},
        ]
    },
    # 收费标准子表
    {
        "modelName": "劳工优化计划服务收费标准子表",
        "modelCode": f"labor_optimization_fee_table_{SUFFIX}",
        "fields": [
            {"fieldName": "服务区域", "fieldCode": "service_area", "fieldType": "STRING"},
            {"fieldName": "项目", "fieldCode": "project_name", "fieldType": "STRING"},
            {"fieldName": "服务内容", "fieldCode": "service_content", "fieldType": "BIG_TEXT"},
            {"fieldName": "基本收费标准", "fieldCode": "basic_fee_standard", "fieldType": "NUM"},
            {"fieldName": "支付金额/人", "fieldCode": "pay_amount", "fieldType": "NUM"},
            {"fieldName": "币种", "fieldCode": "f_currency", "fieldType": "STRING"},
            {"fieldName": "收款方", "fieldCode": "payee", "fieldType": "STRING"},
            {"fieldName": "支付方式", "fieldCode": "pay_cycle_way", "fieldType": "STRING"},
            {"fieldName": "支付周期", "fieldCode": "pay_cycle_num", "fieldType": "STRING"},
            {"fieldName": "备注", "fieldCode": "f_remark", "fieldType": "BIG_TEXT"},
        ]
    },
    # 收费标准主表
    {
        "modelName": "劳工优化计划服务收费",
        "modelCode": f"labor_optimization_fee_standard_{SUFFIX}",
        "fields": [
            {"fieldName": "适用区域", "fieldCode": "service_area", "fieldType": "STRING"},
            {"fieldName": "服务收费流水码", "fieldCode": "fee_standard_code", "fieldType": "STRING"},
            {"fieldName": "是否生效", "fieldCode": "fee_status", "fieldType": "STRING"},
            {"fieldName": "签约类型", "fieldCode": "sign_type", "fieldType": "STRING"},
        ]
    },
    # --- 雇主信息 ---
    {
        "modelName": "雇主基础数据表",
        "modelCode": f"elab_employer_base_info_{SUFFIX}",
        "fields": [
            {"fieldName": "雇主编号", "fieldCode": "employer_code", "fieldType": "STRING"},
            {"fieldName": "客商code编码", "fieldCode": "employer_mdm_code", "fieldType": "STRING"},
            {"fieldName": "雇主全称", "fieldCode": "employer_full_name", "fieldType": "STRING"},
            {"fieldName": "雇主简称", "fieldCode": "employer_short_name", "fieldType": "STRING"},
            {"fieldName": "雇主英文名称", "fieldCode": "employer_en_name", "fieldType": "STRING"},
            {"fieldName": "企业类型", "fieldCode": "enterprise_type", "fieldType": "STRING"},
            {"fieldName": "地区", "fieldCode": "employer_address", "fieldType": "STRING"},
            {"fieldName": "注册类型", "fieldCode": "register_type", "fieldType": "STRING"},
            {"fieldName": "证件类型", "fieldCode": "biz_reg_type", "fieldType": "STRING"},
            {"fieldName": "证照号码", "fieldCode": "biz_reg_no", "fieldType": "STRING"},
            {"fieldName": "注册地址", "fieldCode": "register_address", "fieldType": "STRING"},
            {"fieldName": "法定代表人/负责人", "fieldCode": "legal_representative", "fieldType": "STRING"},
            {"fieldName": "法定代表人身份信息", "fieldCode": "legal_person_id_card", "fieldType": "STRING"},
            {"fieldName": "业务联系人", "fieldCode": "contact_person", "fieldType": "STRING"},
            {"fieldName": "联系人电话", "fieldCode": "contact_phone", "fieldType": "STRING"},
            {"fieldName": "联系人传真", "fieldCode": "contact_fax", "fieldType": "STRING"},
            {"fieldName": "联系人邮箱", "fieldCode": "contact_email", "fieldType": "STRING"},
            {"fieldName": "通讯地址", "fieldCode": "communication_address", "fieldType": "STRING"},
            {"fieldName": "所属行业", "fieldCode": "f_industry_type", "fieldType": "STRING"},
            {"fieldName": "合作状态", "fieldCode": "cooperation_status", "fieldType": "STRING"},
            {"fieldName": "备注", "fieldCode": "f_remark", "fieldType": "BIG_TEXT"},
            {"fieldName": "香港行业", "fieldCode": "hk_industry_code", "fieldType": "STRING"},
            {"fieldName": "注册时间", "fieldCode": "register_date", "fieldType": "DATE"},
        ]
    },
    # --- 合作方信息 ---
    # 合作方专项资质子表
    {
        "modelName": "合作方专项资质子表",
        "modelCode": f"elab_cooperator_qualification_{SUFFIX}",
        "fields": [
            {"fieldName": "资质类型", "fieldCode": "qual_type", "fieldType": "STRING"},
            {"fieldName": "资质编号", "fieldCode": "qual_no", "fieldType": "STRING"},
            {"fieldName": "资质有效期开始", "fieldCode": "qual_valid_start", "fieldType": "DATE"},
            {"fieldName": "资质有效期结束", "fieldCode": "qual_valid_end", "fieldType": "DATE"},
            {"fieldName": "资质许可范围备注", "fieldCode": "qual_scope", "fieldType": "BIG_TEXT"},
            {"fieldName": "资质附件", "fieldCode": "qual_attachment_url", "fieldType": "STRING"},
            {"fieldName": "资质状态", "fieldCode": "qual_status", "fieldType": "STRING"},
            {"fieldName": "国内签约公司名称", "fieldCode": "domestic_company_name", "fieldType": "STRING"},
            {"fieldName": "国内公司负责人", "fieldCode": "domestic_company_principal", "fieldType": "STRING"},
            {"fieldName": "国内公司地址", "fieldCode": "domestic_company_address", "fieldType": "STRING"},
        ]
    },
    # 合作方信息主表
    {
        "modelName": "合作方信息表",
        "modelCode": f"elab_cooperator_info_{SUFFIX}",
        "fields": [
            {"fieldName": "合作方编号", "fieldCode": "cooperator_code", "fieldType": "STRING"},
            {"fieldName": "合作方全称", "fieldCode": "cooperator_full_name", "fieldType": "STRING"},
            {"fieldName": "合作方简称", "fieldCode": "cooperator_short_name", "fieldType": "STRING"},
            {"fieldName": "合作方名称英文", "fieldCode": "cooperator_en_name", "fieldType": "STRING"},
            {"fieldName": "合作方类型", "fieldCode": "cooperator_type", "fieldType": "STRING"},
            {"fieldName": "合作方客商code编码", "fieldCode": "cooperator_mdm_code", "fieldType": "STRING"},
            {"fieldName": "合作方财务计算", "fieldCode": "cooperate_fa_calculation_method", "fieldType": "STRING"},
            {"fieldName": "所属地区", "fieldCode": "region_type", "fieldType": "STRING"},
            {"fieldName": "企业性质", "fieldCode": "enterprise_nature", "fieldType": "STRING"},
            {"fieldName": "企业状态", "fieldCode": "enterprise_status", "fieldType": "STRING"},
            {"fieldName": "证照类型", "fieldCode": "biz_license_no", "fieldType": "STRING"},
            {"fieldName": "证照编号", "fieldCode": "hk_biz_reg_no", "fieldType": "STRING"},
            {"fieldName": "法定代表人/负责人", "fieldCode": "legal_representative", "fieldType": "STRING"},
            {"fieldName": "业务联系人", "fieldCode": "contact_person", "fieldType": "STRING"},
            {"fieldName": "联系人电话", "fieldCode": "contact_phone", "fieldType": "STRING"},
            {"fieldName": "联系人邮箱", "fieldCode": "contact_email", "fieldType": "STRING"},
            {"fieldName": "注册地址", "fieldCode": "registered_address", "fieldType": "STRING"},
            {"fieldName": "经营地址", "fieldCode": "business_address", "fieldType": "STRING"},
            {"fieldName": "合作范围", "fieldCode": "cooperation_scope", "fieldType": "STRING"},
            {"fieldName": "合作状态", "fieldCode": "cooperation_status", "fieldType": "STRING"},
            {"fieldName": "合作有效期开始", "fieldCode": "coop_valid_start", "fieldType": "DATE"},
            {"fieldName": "合作有效期结束", "fieldCode": "coop_valid_end", "fieldType": "DATE"},
            {"fieldName": "备注", "fieldCode": "f_remark", "fieldType": "BIG_TEXT"},
        ]
    },
    # 合作商协议信息表
    {
        "modelName": "合作商协议信息表",
        "modelCode": f"elab_cooperator_agreement_{SUFFIX}",
        "fields": [
            {"fieldName": "协议编号", "fieldCode": "agreement_no", "fieldType": "STRING"},
            {"fieldName": "协议名称", "fieldCode": "agreement_name", "fieldType": "STRING"},
            {"fieldName": "协议类型", "fieldCode": "agreement_type", "fieldType": "STRING"},
            {"fieldName": "合作方财务计算", "fieldCode": "cooperate_fa_calculation_method", "fieldType": "STRING"},
            {"fieldName": "区域", "fieldCode": "f_area", "fieldType": "STRING"},
            {"fieldName": "合作方ID", "fieldCode": "cooperator_id", "fieldType": "STRING"},
            {"fieldName": "合作方名称", "fieldCode": "cooperator_name", "fieldType": "STRING"},
            {"fieldName": "签约公司ID", "fieldCode": "our_company_id", "fieldType": "STRING"},
            {"fieldName": "签约公司名称", "fieldCode": "our_company_name", "fieldType": "STRING"},
            {"fieldName": "签订日期", "fieldCode": "sign_date", "fieldType": "DATE"},
            {"fieldName": "协议有效期开始", "fieldCode": "valid_start_date", "fieldType": "DATE"},
            {"fieldName": "协议有效期结束", "fieldCode": "valid_end_date", "fieldType": "DATE"},
            {"fieldName": "合作范围", "fieldCode": "cooperation_scope", "fieldType": "BIG_TEXT"},
            {"fieldName": "支付条款", "fieldCode": "payment_terms", "fieldType": "BIG_TEXT"},
            {"fieldName": "协议状态", "fieldCode": "agreement_status", "fieldType": "STRING"},
            {"fieldName": "协议附件", "fieldCode": "agreement_attachment", "fieldType": "STRING"},
        ]
    },
    # 合作商提成计提规则 - 阶梯子表
    {
        "modelName": "阶梯提成子表",
        "modelCode": f"elab_commission_ladder_{SUFFIX}",
        "fields": [
            {"fieldName": "阶梯起始值", "fieldCode": "ladder_start", "fieldType": "NUM"},
            {"fieldName": "阶梯结束值", "fieldCode": "ladder_end", "fieldType": "NUM"},
            {"fieldName": "阶梯提成比例", "fieldCode": "ladder_commission_rate", "fieldType": "NUM"},
        ]
    },
    # 合作商提成计提规则表
    {
        "modelName": "合作商提成计提规则表",
        "modelCode": f"elab_cooperator_commission_{SUFFIX}",
        "fields": [
            {"fieldName": "关联合作方协议", "fieldCode": "agreement_id", "fieldType": "STRING"},
            {"fieldName": "合作方ID", "fieldCode": "cooperator_id", "fieldType": "STRING"},
            {"fieldName": "适用范围", "fieldCode": "range_area", "fieldType": "STRING"},
            {"fieldName": "区域", "fieldCode": "f_area", "fieldType": "STRING"},
            {"fieldName": "合作方财务计算", "fieldCode": "cooperate_fa_calculation_method", "fieldType": "STRING"},
            {"fieldName": "适用业务类型", "fieldCode": "business_type", "fieldType": "STRING"},
            {"fieldName": "支付币种", "fieldCode": "f_currency", "fieldType": "STRING"},
            {"fieldName": "提成方式", "fieldCode": "commission_type", "fieldType": "STRING"},
            {"fieldName": "提成比例", "fieldCode": "commission_rate", "fieldType": "NUM"},
            {"fieldName": "固定提成金额", "fieldCode": "fixed_commission", "fieldType": "NUM"},
            {"fieldName": "关联结算规则", "fieldCode": "link_settlement", "fieldType": "STRING"},
            {"fieldName": "支付频率", "fieldCode": "settlement_cycle", "fieldType": "STRING"},
            {"fieldName": "支付方式", "fieldCode": "payment_method", "fieldType": "STRING"},
            {"fieldName": "规则状态", "fieldCode": "rule_status", "fieldType": "STRING"},
            {"fieldName": "规则生效日期", "fieldCode": "valid_start_date", "fieldType": "DATE"},
            {"fieldName": "规则失效日期", "fieldCode": "valid_end_date", "fieldType": "DATE"},
            {"fieldName": "规则备注", "fieldCode": "f_remark", "fieldType": "BIG_TEXT"},
        ]
    },
    # 合作方结算周期
    {
        "modelName": "合作方结算周期",
        "modelCode": f"cooperator_settlement_{SUFFIX}",
        "fields": [
            {"fieldName": "结算周期流水", "fieldCode": "agreement_id", "fieldType": "STRING"},
            {"fieldName": "合作方ID", "fieldCode": "cooperator_id", "fieldType": "STRING"},
            {"fieldName": "合作方名称", "fieldCode": "cooperator_name", "fieldType": "STRING"},
            {"fieldName": "区域", "fieldCode": "f_area", "fieldType": "STRING"},
            {"fieldName": "支付频率", "fieldCode": "settlement_cycle", "fieldType": "STRING"},
            {"fieldName": "结算日期", "fieldCode": "settlement_date", "fieldType": "STRING"},
            {"fieldName": "支付方式", "fieldCode": "payment_method", "fieldType": "STRING"},
            {"fieldName": "支付比例", "fieldCode": "pay_rate_way", "fieldType": "STRING"},
            {"fieldName": "结算周期状态", "fieldCode": "pay_status", "fieldType": "STRING"},
        ]
    },
    # --- 配额申请 ---
    # 配额批准书明细（配额申请的子表）
    {
        "modelName": "配额批准书明细",
        "modelCode": f"table_elab_quotation_{SUFFIX}",
        "fields": [
            {"fieldName": "配额申请ID", "fieldCode": "quotation_approval_id", "fieldType": "STRING"},
            {"fieldName": "配额申请明细ID", "fieldCode": "detail_id", "fieldType": "STRING"},
            {"fieldName": "合作方相关信息", "fieldCode": "co_name", "fieldType": "STRING"},
            {"fieldName": "配额明细编号", "fieldCode": "detail_no", "fieldType": "STRING"},
            {"fieldName": "配额数目", "fieldCode": "detail_num", "fieldType": "NUM"},
            {"fieldName": "劳务合同生成数量", "fieldCode": "contract_num", "fieldType": "NUM"},
            {"fieldName": "雇佣期", "fieldCode": "hire_period", "fieldType": "STRING"},
            {"fieldName": "可入职月份", "fieldCode": "hire_period_num", "fieldType": "NUM"},
            {"fieldName": "工种", "fieldCode": "job_type", "fieldType": "STRING"},
            {"fieldName": "工作地点", "fieldCode": "work_place", "fieldType": "STRING"},
            {"fieldName": "住宿地点", "fieldCode": "accommodation_place", "fieldType": "STRING"},
            {"fieldName": "每日工作时数", "fieldCode": "daily_work_hours", "fieldType": "NUM"},
            {"fieldName": "每月工作日数", "fieldCode": "monthly_work_days", "fieldType": "NUM"},
            {"fieldName": "每月工资(雇主货币)", "fieldCode": "monthly_salary_change", "fieldType": "NUM"},
            {"fieldName": "币种", "fieldCode": "monthly_salary_currency", "fieldType": "STRING"},
            {"fieldName": "备注", "fieldCode": "f_remark", "fieldType": "STRING"},
        ]
    },
    # 配额申请主表
    {
        "modelName": "配额申请",
        "modelCode": f"elab_quotation_approval_{SUFFIX}",
        "fields": [
            {"fieldName": "批文编号", "fieldCode": "approval_no", "fieldType": "STRING"},
            {"fieldName": "配额申请ID", "fieldCode": "quotation_approval_id", "fieldType": "STRING"},
            {"fieldName": "批准书类型", "fieldCode": "approval_type", "fieldType": "STRING"},
            {"fieldName": "行业", "fieldCode": "company_type", "fieldType": "STRING"},
            {"fieldName": "签发单位", "fieldCode": "issuance_of_units", "fieldType": "STRING"},
            {"fieldName": "配额批准部门联系邮箱", "fieldCode": "issuance_of_units_mail", "fieldType": "STRING"},
            {"fieldName": "雇主", "fieldCode": "partner_company_id", "fieldType": "STRING"},
            {"fieldName": "雇主编码", "fieldCode": "employer_id", "fieldType": "STRING"},
            {"fieldName": "签约组织", "fieldCode": "org_structure", "fieldType": "STRING"},
            {"fieldName": "签约组织ID", "fieldCode": "org_structure_id", "fieldType": "STRING"},
            {"fieldName": "合作方", "fieldCode": "cooperator_code", "fieldType": "STRING"},
            {"fieldName": "批准配额总数量", "fieldCode": "quotation_num", "fieldType": "NUM"},
            {"fieldName": "劳务合同生成数量", "fieldCode": "contract_num", "fieldType": "NUM"},
            {"fieldName": "有效期开始日期", "fieldCode": "valid_start_date", "fieldType": "DATE"},
            {"fieldName": "有效期结束日期", "fieldCode": "valid_end_date", "fieldType": "DATE"},
            {"fieldName": "负责人姓名", "fieldCode": "responsible_person", "fieldType": "STRING"},
            {"fieldName": "负责人电话", "fieldCode": "responsible_phone", "fieldType": "STRING"},
            {"fieldName": "批准书状态", "fieldCode": "approval_status", "fieldType": "STRING"},
            {"fieldName": "配额批准书上传", "fieldCode": "attachment_url", "fieldType": "STRING"},
            {"fieldName": "共同合作申明书上传", "fieldCode": "attachment_url2", "fieldType": "STRING"},
            {"fieldName": "劳务合同上传", "fieldCode": "attachment_url3", "fieldType": "STRING"},
            {"fieldName": "授权委托书上传", "fieldCode": "attachment_url4", "fieldType": "STRING"},
        ]
    },
    # 配额明细表
    {
        "modelName": "配额明细表",
        "modelCode": f"elab_quotation_detail_{SUFFIX}",
        "fields": [
            {"fieldName": "配额明细ID", "fieldCode": "detail_id", "fieldType": "STRING"},
            {"fieldName": "配额序号", "fieldCode": "elab_num", "fieldType": "STRING"},
            {"fieldName": "配额批准书ID", "fieldCode": "quotation_approval_id", "fieldType": "STRING"},
            {"fieldName": "批文编号", "fieldCode": "approval_no", "fieldType": "STRING"},
            {"fieldName": "雇主ID", "fieldCode": "employer_id", "fieldType": "STRING"},
            {"fieldName": "雇主名称", "fieldCode": "employer_name", "fieldType": "STRING"},
            {"fieldName": "签约公司ID", "fieldCode": "sign_company_id", "fieldType": "STRING"},
            {"fieldName": "签约公司名称", "fieldCode": "sign_company_name", "fieldType": "STRING"},
            {"fieldName": "可用数量", "fieldCode": "available_num", "fieldType": "NUM"},
            {"fieldName": "已用数量", "fieldCode": "used_num", "fieldType": "NUM"},
            {"fieldName": "分配人员ID", "fieldCode": "assigned_person_id", "fieldType": "STRING"},
            {"fieldName": "分配人员姓名", "fieldCode": "assigned_person_name", "fieldType": "STRING"},
            {"fieldName": "是否生效", "fieldCode": "is_effective", "fieldType": "STRING"},
            {"fieldName": "有效时间开始", "fieldCode": "effective_start_date", "fieldType": "STRING"},
            {"fieldName": "有效时间结束", "fieldCode": "effective_end_date", "fieldType": "STRING"},
            {"fieldName": "明细配额分配状态", "fieldCode": "detail_allocation_status", "fieldType": "STRING"},
            {"fieldName": "可替换次数", "fieldCode": "available_change_num", "fieldType": "NUM"},
            {"fieldName": "已替换次数", "fieldCode": "have_change_num", "fieldType": "NUM"},
        ]
    },
    # 配额明细记录
    {
        "modelName": "配额明细记录",
        "modelCode": f"elab_quotation_detail_record_{SUFFIX}",
        "fields": [
            {"fieldName": "配额明细ID", "fieldCode": "detail_id", "fieldType": "STRING"},
            {"fieldName": "配额批准书ID", "fieldCode": "quotation_approval_id", "fieldType": "STRING"},
            {"fieldName": "配额序号", "fieldCode": "elab_num", "fieldType": "STRING"},
            {"fieldName": "批文编号", "fieldCode": "approval_no", "fieldType": "STRING"},
            {"fieldName": "雇主ID", "fieldCode": "employer_id", "fieldType": "STRING"},
            {"fieldName": "雇主名称", "fieldCode": "employer_name", "fieldType": "STRING"},
            {"fieldName": "签约公司ID", "fieldCode": "sign_company_id", "fieldType": "STRING"},
            {"fieldName": "签约公司名称", "fieldCode": "sign_company_name", "fieldType": "STRING"},
            {"fieldName": "分配人员ID", "fieldCode": "assigned_person_id", "fieldType": "STRING"},
            {"fieldName": "分配人员姓名", "fieldCode": "assigned_person_name", "fieldType": "STRING"},
            {"fieldName": "分配时间", "fieldCode": "creat_time", "fieldType": "DATE"},
        ]
    },
    # 雇主合作委托申请
    {
        "modelName": "雇主合作委托申请",
        "modelCode": f"employer_coop_delegation_{SUFFIX}",
        "fields": [
            {"fieldName": "雇主合作委托流水码", "fieldCode": "quota_apply_approval_code", "fieldType": "STRING"},
            {"fieldName": "配额申请ID", "fieldCode": "quota_apply_id", "fieldType": "STRING"},
            {"fieldName": "行业", "fieldCode": "company_type", "fieldType": "STRING"},
            {"fieldName": "签发单位", "fieldCode": "issuance_of_units", "fieldType": "STRING"},
            {"fieldName": "雇主", "fieldCode": "partner_company_id", "fieldType": "STRING"},
            {"fieldName": "雇主编码", "fieldCode": "employer_id", "fieldType": "STRING"},
            {"fieldName": "签约组织", "fieldCode": "org_structure", "fieldType": "STRING"},
            {"fieldName": "签约组织ID", "fieldCode": "org_structure_id", "fieldType": "STRING"},
            {"fieldName": "说明", "fieldCode": "f_remark", "fieldType": "BIG_TEXT"},
            {"fieldName": "附件上传", "fieldCode": "file_upload", "fieldType": "STRING"},
            {"fieldName": "流程标题", "fieldCode": "process_tittle", "fieldType": "STRING"},
        ]
    },
]


# ============================================================
# Step 3: 表单定义（按依赖顺序！被数据选择器引用的先创建）
# 每个表单绑定一个主模型，可能有子表
# ============================================================
FORMS = [
    # 1. 行业（被配额申请引用）
    {
        "formName": "行业",
        "modelCode": f"industry_{SUFFIX}",
        "allModelCodes": [f"industry_{SUFFIX}"],
    },
    # 2. 收费标准（被委托申请引用）
    {
        "formName": "劳工优化计划服务收费",
        "modelCode": f"labor_optimization_fee_standard_{SUFFIX}",
        "allModelCodes": [f"labor_optimization_fee_standard_{SUFFIX}", f"labor_optimization_fee_table_{SUFFIX}"],
        "subTable": {
            "label": "收费标准明细",
            "modelCode": f"labor_optimization_fee_table_{SUFFIX}",
        }
    },
    # 3. 雇主信息（被配额申请引用）
    {
        "formName": "雇主基础数据表",
        "modelCode": f"elab_employer_base_info_{SUFFIX}",
        "allModelCodes": [f"elab_employer_base_info_{SUFFIX}"],
    },
    # 4. 合作方信息
    {
        "formName": "合作方信息表",
        "modelCode": f"elab_cooperator_info_{SUFFIX}",
        "allModelCodes": [f"elab_cooperator_info_{SUFFIX}", f"elab_cooperator_qualification_{SUFFIX}"],
        "subTable": {
            "label": "合作方专项资质",
            "modelCode": f"elab_cooperator_qualification_{SUFFIX}",
        }
    },
    # 5. 合作商协议
    {
        "formName": "合作商协议信息表",
        "modelCode": f"elab_cooperator_agreement_{SUFFIX}",
        "allModelCodes": [f"elab_cooperator_agreement_{SUFFIX}"],
    },
    # 6. 合作方结算周期
    {
        "formName": "合作方结算周期",
        "modelCode": f"cooperator_settlement_{SUFFIX}",
        "allModelCodes": [f"cooperator_settlement_{SUFFIX}"],
    },
    # 7. 合作商提成计提规则
    {
        "formName": "合作商提成计提规则表",
        "modelCode": f"elab_cooperator_commission_{SUFFIX}",
        "allModelCodes": [f"elab_cooperator_commission_{SUFFIX}", f"elab_commission_ladder_{SUFFIX}"],
        "subTable": {
            "label": "阶梯提成",
            "modelCode": f"elab_commission_ladder_{SUFFIX}",
        }
    },
    # 8. 配额申请
    {
        "formName": "配额申请",
        "modelCode": f"elab_quotation_approval_{SUFFIX}",
        "allModelCodes": [f"elab_quotation_approval_{SUFFIX}", f"table_elab_quotation_{SUFFIX}"],
        "subTable": {
            "label": "配额批准书明细",
            "modelCode": f"table_elab_quotation_{SUFFIX}",
        }
    },
    # 9. 配额明细表
    {
        "formName": "配额明细表",
        "modelCode": f"elab_quotation_detail_{SUFFIX}",
        "allModelCodes": [f"elab_quotation_detail_{SUFFIX}"],
    },
    # 10. 配额明细记录
    {
        "formName": "配额明细记录",
        "modelCode": f"elab_quotation_detail_record_{SUFFIX}",
        "allModelCodes": [f"elab_quotation_detail_record_{SUFFIX}"],
    },
    # 11. 雇主合作委托申请
    {
        "formName": "雇主合作委托申请",
        "modelCode": f"employer_coop_delegation_{SUFFIX}",
        "allModelCodes": [f"employer_coop_delegation_{SUFFIX}"],
    },
]


# ============================================================
# 执行逻辑
# ============================================================

# 建立 modelCode → fields 索引
MODEL_FIELDS = {}
for m in MODELS:
    MODEL_FIELDS[m["modelCode"]] = {f["fieldName"]: f["fieldCode"] for f in m["fields"]}


def build_form_payload(form_def: dict) -> dict:
    """构建单个表单的 API payload"""
    mc = form_def["modelCode"]
    fields = MODEL_FIELDS.get(mc, {})

    components = []
    query_conditions = []
    query_list = []
    listable = 0

    # 主模型字段
    for field_name, field_code in fields.items():
        comp = {
            "componentType": "FORM_TEXT_INPUT",
            "label": field_name,
            "modelField": f"{mc}.{field_code}",
        }
        components.append(comp)

        if listable < 6:
            mf = f"{mc}.{field_code}"
            if listable < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1

    # 子表
    if "subTable" in form_def:
        sub = form_def["subTable"]
        sub_mc = sub["modelCode"]
        sub_fields = MODEL_FIELDS.get(sub_mc, {})
        sub_cols = []
        for sf_name, sf_code in sub_fields.items():
            sub_cols.append({
                "componentType": "FORM_TEXT_INPUT",
                "label": sf_name,
                "modelField": f"{sub_mc}.{sf_code}",
            })
        if sub_cols:
            components.append({
                "componentType": "FORM_WIDGET_SON_TABLE",
                "label": sub["label"],
                "tableColumn": sub_cols,
            })

    return {
        "formName": form_def["formName"],
        "formCode": f"form_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}",
        "allModelCodes": form_def["allModelCodes"],
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        }
    }


async def main():
    if not APP_ID:
        print("❌ 请先设置 APP_ID")
        return

    client = APaaSClient()
    await client.login("17621440039", "definesys2019")

    # =====================
    # Phase 1: 创建字典
    # =====================
    print("\n📚 Phase 1: 创建数据字典...")

    # 查询已有
    existing = await client.query_dicts(APP_ID)
    existing_by_name = {d.get('dictionaryName'): d for d in existing}

    new_dicts = []
    for d in DICTS:
        if d['name'] in existing_by_name:
            print(f"  ♻️ 复用: {d['name']}")
        else:
            new_dicts.append(d)

    if new_dicts:
        payload = [{
            "appId": APP_ID,
            "dictionaryCode": d['code'],
            "dictionaryName": d['name'],
            "dictionaryOptions": []
        } for d in new_dicts]
        await client.create_dicts(APP_ID, payload)
        print(f"  ✅ 新建 {len(new_dicts)} 个字典")

        # 添加选项
        all_dicts = await client.query_dicts(APP_ID)
        dict_by_code = {d.get('dictionaryCode'): d for d in all_dicts}
        headers = client._get_headers(APP_ID)
        total = 0
        async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
            for d in new_dicts:
                obj = dict_by_code.get(d['code'])
                if not obj:
                    continue
                for idx, opt in enumerate(d.get('options', [])):
                    await http.post(
                        f"{client.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                        headers=headers,
                        json={
                            "appId": APP_ID, "dictionaryId": obj['id'],
                            "valueCode": opt['code'], "valueName": opt['name'],
                            "valueNameI18nAssociated": False, "valueNameI18nResourceCode": "",
                            "valueNameI18n": {}, "displayOrder": idx,
                            "valueDescribe": "", "valueStatus": "ENABLE",
                            "valueMulticolor": "#027AFF"
                        })
                    total += 1
        print(f"  ✅ 添加 {total} 个选项")
    else:
        print("  ⏭️ 所有字典已存在")

    print("  ✅ 字典完成")

    # =====================
    # Phase 2: 创建模型
    # =====================
    print("\n🗄️ Phase 2: 创建数据模型...")

    existing_models = await client.query_models(APP_ID)
    existing_by_name = {m.get('modelName'): m for m in existing_models}

    new_models = [m for m in MODELS if m['modelName'] not in existing_by_name]
    reused = [m for m in MODELS if m['modelName'] in existing_by_name]

    for m in reused:
        print(f"  ♻️ 复用: {m['modelName']}")

    if new_models:
        data_models = [{
            "appId": APP_ID,
            "modelName": m['modelName'],
            "modelCode": m['modelCode'],
            "modelDescription": m['modelName'],
            "fields": m['fields']
        } for m in new_models]

        payload = {"appId": APP_ID, "datasourceId": "", "dataModels": data_models}
        await client.create_models(APP_ID, payload)
        print(f"  ✅ 新建 {len(new_models)} 个模型")
    else:
        print("  ⏭️ 所有模型已存在")

    print("  ✅ 模型完成")

    # =====================
    # Phase 3: 创建表单
    # =====================
    print("\n📝 Phase 3: 创建表单...")

    # 查询已有表单
    existing_forms = set()
    try:
        menus = await client.query_menus(APP_ID)
        def collect(items):
            for item in items:
                if item.get('menuType') == 'MODEL' and item.get('formId'):
                    existing_forms.add(item.get('menuName', ''))
                collect(item.get('submenus', []) or item.get('children', []) or [])
        collect(menus)
    except:
        pass

    form_ids = []
    for form_def in FORMS:
        if form_def['formName'] in existing_forms:
            print(f"  ♻️ 复用: {form_def['formName']}")
            continue

        payload = build_form_payload(form_def)
        try:
            result = await client.create_form_config(APP_ID, [payload])
            if isinstance(result, list):
                for fr in result:
                    if isinstance(fr, dict) and 'id' in fr:
                        form_ids.append(fr['id'])
            print(f"  ✅ {form_def['formName']}")
        except Exception as e:
            print(f"  ❌ {form_def['formName']}: {e}")

    print(f"  ✅ 表单完成（{len(form_ids)} 个）")

    # =====================
    # Phase 4: 角色
    # =====================
    print("\n👥 Phase 4: 添加角色...")
    roles = [
        {"roleName": "系统管理员", "roleCode": f"R_admin_{SUFFIX}"},
        {"roleName": "配额管理员", "roleCode": f"R_quota_admin_{SUFFIX}"},
        {"roleName": "业务操作员", "roleCode": f"R_operator_{SUFFIX}"},
    ]
    try:
        payload = [{"appId": APP_ID, **r} for r in roles]
        await client.create_roles(APP_ID, payload)
        print(f"  ✅ 添加 {len(roles)} 个角色")
    except Exception as e:
        if "已存在" in str(e) or "重复" in str(e):
            print("  ♻️ 角色已存在")
        else:
            print(f"  ❌ {e}")

    print(f"\n🎉 完成！后缀: {SUFFIX}")


if __name__ == "__main__":
    asyncio.run(main())
