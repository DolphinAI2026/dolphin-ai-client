"""
基于劳务管理系统设计文档，直接调用 aPaaS API 创建完整应用。
这是 Step 1: 手动跑通的脚本，后续会工程化为 AI Agent。

运行: cd backend && ./venv/bin/python scripts/build_labor_system.py
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from app.apaas_client import APaaSClient

# ============================================================
# 配置
# ============================================================
BASE_URL = "https://apaas-poc.definesys.cn/backend"
TENANT_ID = "822201427723026433"
USERNAME = "17621440039"
PASSWORD = "definesys2019"
APP_ID = "822254164473020416"  # 刚创建的应用

# ============================================================
# 数据字典定义（从文档提取）
# ============================================================
DICTS = [
    {"name": "批准书类型", "code": "approval_type", "options": ["委托派遣", "直接用工", "合作派遣"]},
    {"name": "区域", "code": "service_area", "options": ["大陆", "香港", "澳门"]},
    {"name": "是否", "code": "yes_no", "options": ["是", "否"]},
    {"name": "签约类型", "code": "sign_type", "options": ["新签", "续约"]},
    {"name": "企业类型", "code": "enterprise_type", "options": ["香港企业", "内地企业", "中外合资", "外资独资", "其他"]},
    {"name": "注册类型", "code": "register_type", "options": ["有限公司", "无限公司", "个体工商户", "非盈利机构", "其他"]},
    {"name": "证照类型", "code": "license_type", "options": ["营业执照", "商业登记证编号"]},
    {"name": "合作状态", "code": "cooperation_status", "options": ["合作中", "暂停合作", "终止合作"]},
    {"name": "合作方类型", "code": "cooperator_type", "options": ["劳务公司", "职业介绍所", "培训机构", "保险公司", "其他服务机构"]},
    {"name": "企业性质", "code": "enterprise_nature", "options": ["国企", "民企", "外企", "合资", "个体", "非盈利机构"]},
    {"name": "企业状态", "code": "enterprise_status", "options": ["有效", "失效", "未启用"]},
    {"name": "业务范围", "code": "cooperation_scope", "options": ["配额申请对接", "人员派遣", "培训服务", "保险代办", "证件办理", "其他"]},
    {"name": "资质类型", "code": "qualification_type", "options": ["劳务派遣经营许可", "职业介绍所牌照", "人力资源服务许可", "对外劳务合作资格", "其他"]},
    {"name": "资质状态", "code": "qualification_status", "options": ["有效", "过期", "注销"]},
    {"name": "协议类型", "code": "agreement_type", "options": ["劳务派遣协议", "人力资源服务协议", "培训服务协议", "保险代理协议", "合作框架协议", "其他协议"]},
    {"name": "协议状态", "code": "agreement_status", "options": ["生效", "失效"]},
    {"name": "适用业务类型", "code": "business_type", "options": ["配额申请对接", "人员派遣", "证照代办", "培训服务", "保险代理服务", "其他"]},
    {"name": "币种", "code": "currency", "options": ["人民币", "美元", "港币", "欧元"]},
    {"name": "提成方式", "code": "commission_type", "options": ["比例提成", "固定金额提成", "阶梯提成"]},
    {"name": "支付方式", "code": "payment_method", "options": ["银行转账", "电子汇款", "其他"]},
    {"name": "规则状态", "code": "rule_status", "options": ["有效", "暂停", "作废"]},
    {"name": "支付频率", "code": "settlement_cycle", "options": ["按次", "按月", "一次性支付", "其他频率"]},
    {"name": "支付比例", "code": "pay_rate_way", "options": ["全额支付", "部分支付"]},
    {"name": "结算周期状态", "code": "pay_status", "options": ["失效", "生效"]},
    {"name": "支付节点", "code": "pay_node", "options": ["劳工入境次月支付", "合同期满前一个月支付"]},
    {"name": "是否特殊支付", "code": "is_special", "options": ["按月", "是"]},
    {"name": "支付次序", "code": "pay_order", "options": ["首次支付", "第二次", "第三次", "第四次", "其他"]},
    {"name": "批准书状态", "code": "approval_status", "options": ["有效", "过期", "作废"]},
    {"name": "雇佣期", "code": "hire_period", "options": ["6个月", "12个月", "24个月"]},
    {"name": "工种职位", "code": "job_type", "options": ["技术员", "工地督导", "高级督导", "护工", "厨师"]},
    {"name": "是否生效", "code": "is_effective", "options": ["生效", "未生效"]},
    {"name": "明细配额分配状态", "code": "detail_allocation_status", "options": ["未分配", "部分分配", "全部分配", "已回收"]},
    {"name": "支付方式_收费", "code": "pay_cycle_way", "options": ["一次性支付", "季度", "月度", "半年", "年度"]},
    {"name": "支付期限", "code": "pay_deadline", "options": ["签订合同后7天", "每月5日前", "服务完成后3天", "一次性付清"]},
    {"name": "香港行业", "code": "hk_industry", "options": ["建筑业", "酒店及旅游业", "零售业", "制造业", "其他"]},
    {"name": "所属行业", "code": "industry_type", "options": ["制造业", "建筑业", "服务业", "贸易业", "其他"]},
]

# ============================================================
# 数据模型定义（从文档提取）
# ============================================================
# 字段组件类型缩写
# S=单行输入, T=多行输入, N=数字, D=日期, $=金额, V=下拉单选, VM=下拉多选
# DS=数据单选, #=单据号, F=附件上传, SW=开关, P=手机号码, @=邮箱, U=人员选择
COMP_MAP = {
    "S": "FORM_TEXT_INPUT",
    "T": "FORM_TEXTAREA_INPUT",
    "N": "FORM_NUMBER_INPUT",
    "D": "FORM_DATEPICK_INPUT",
    "$": "FORM_MONEY_INPUT",
    "V": "FORM_SELECT_INPUT",
    "VM": "FORM_SELECT_INPUT",
    "DS": "FORM_DATA_SELECTOR_SINGLE",
    "#": "FORM_DOCUMENT_NUMBER",
    "F": "FORM_FILE_UPLOAD",
    "SW": "FORM_SWITCH_SELECT",
    "P": "FORM_PHONE_INPUT",
    "@": "FORM_EMAIL_INPUT",
    "U": "FORM_PEOPLE_SELECT",
}

# 字段类型 → 模型字段类型
MODEL_TYPE_MAP = {
    "S": "STRING", "T": "BIG_TEXT", "N": "NUM", "D": "DATE", "$": "NUM",
    "V": "STRING", "VM": "STRING", "DS": "STRING", "#": "STRING",
    "F": "STRING", "SW": "STRING", "P": "STRING", "@": "STRING", "U": "STRING",
}

MODELS = [
    {
        "name": "行业", "code": "industry",
        "fields": [
            {"name": "批准书类型", "code": "f_approval_type", "comp": "V", "dict": "approval_type"},
            {"name": "行业", "code": "f_industry", "comp": "DS"},
            {"name": "签发单位", "code": "f_issuance_of_units", "comp": "S"},
            {"name": "配额批准部门联系邮箱", "code": "f_issuance_of_units_mail", "comp": "@"},
            {"name": "负责人姓名", "code": "f_responsible_person", "comp": "S"},
            {"name": "负责人电话", "code": "f_responsible_phone", "comp": "P"},
            {"name": "适用区域", "code": "f_service_area", "comp": "V", "dict": "service_area"},
            {"name": "可替换次数", "code": "f_able_change", "comp": "N"},
        ]
    },
    {
        "name": "劳工优化计划服务收费标准", "code": "labor_optimization_fee_standard",
        "fields": [
            {"name": "适用区域", "code": "f_fee_service_area", "comp": "V", "dict": "service_area"},
            {"name": "服务收费流水码", "code": "f_fee_standard_code", "comp": "#"},
            {"name": "是否生效", "code": "f_fee_status", "comp": "V", "dict": "yes_no"},
            {"name": "签约类型", "code": "f_fee_sign_type", "comp": "V", "dict": "sign_type"},
        ],
        "sub_tables": [
            {
                "name": "劳工优化计划服务收费标准子表", "code": "labor_optimization_fee_table",
                "fields": [
                    {"name": "服务区域", "code": "f_sub_service_area", "comp": "V", "dict": "service_area"},
                    {"name": "项目", "code": "f_sub_project_name", "comp": "V"},
                    {"name": "服务内容", "code": "f_sub_service_content", "comp": "T"},
                    {"name": "基本收费标准", "code": "f_sub_basic_fee", "comp": "$"},
                    {"name": "支付金额/人", "code": "f_sub_pay_amount", "comp": "$"},
                    {"name": "币种", "code": "f_sub_currency", "comp": "V", "dict": "currency"},
                    {"name": "收款方", "code": "f_sub_payee", "comp": "S"},
                    {"name": "支付方式", "code": "f_sub_pay_way", "comp": "V", "dict": "pay_cycle_way"},
                    {"name": "支付周期", "code": "f_sub_pay_cycle_num", "comp": "N"},
                    {"name": "备注", "code": "f_sub_remark", "comp": "T"},
                ]
            }
        ]
    },
    {
        "name": "雇主基础数据表", "code": "elab_employer_base_info",
        "fields": [
            {"name": "雇主编号", "code": "f_employer_code", "comp": "#"},
            {"name": "客商code编码", "code": "f_employer_mdm_code", "comp": "S"},
            {"name": "雇主全称", "code": "f_employer_full_name", "comp": "S"},
            {"name": "雇主简称", "code": "f_employer_short_name", "comp": "S"},
            {"name": "雇主英文名称", "code": "f_employer_en_name", "comp": "S"},
            {"name": "企业类型", "code": "f_enterprise_type", "comp": "V", "dict": "enterprise_type"},
            {"name": "地区", "code": "f_employer_address", "comp": "V", "dict": "service_area"},
            {"name": "注册类型", "code": "f_register_type", "comp": "V", "dict": "register_type"},
            {"name": "证件类型", "code": "f_biz_reg_type", "comp": "V", "dict": "license_type"},
            {"name": "证照号码", "code": "f_biz_reg_no", "comp": "S"},
            {"name": "注册地址", "code": "f_register_address", "comp": "S"},
            {"name": "法定代表人", "code": "f_legal_representative", "comp": "S"},
            {"name": "法定代表人身份信息", "code": "f_legal_person_id_card", "comp": "S"},
            {"name": "业务联系人", "code": "f_contact_person", "comp": "S"},
            {"name": "联系人电话", "code": "f_contact_phone", "comp": "P"},
            {"name": "联系人传真", "code": "f_contact_fax", "comp": "S"},
            {"name": "联系人邮箱", "code": "f_contact_email", "comp": "@"},
            {"name": "通讯地址", "code": "f_communication_address", "comp": "S"},
            {"name": "所属行业", "code": "f_industry_type", "comp": "V", "dict": "industry_type"},
            {"name": "合作状态", "code": "f_cooperation_status", "comp": "V", "dict": "cooperation_status"},
            {"name": "备注", "code": "f_employer_remark", "comp": "T"},
        ]
    },
    {
        "name": "合作方信息表", "code": "elab_cooperator_info",
        "fields": [
            {"name": "合作方编号", "code": "f_cooperator_code", "comp": "#"},
            {"name": "合作方全称", "code": "f_cooperator_full_name", "comp": "S"},
            {"name": "合作方简称", "code": "f_cooperator_short_name", "comp": "S"},
            {"name": "合作方名称英文", "code": "f_cooperator_en_name", "comp": "S"},
            {"name": "电话", "code": "f_cooperator_phone", "comp": "P"},
            {"name": "传真", "code": "f_cooperator_fax", "comp": "S"},
            {"name": "合作方类型", "code": "f_cooperator_type", "comp": "V", "dict": "cooperator_type"},
            {"name": "合作方客商code", "code": "f_cooperator_mdm_code", "comp": "S"},
            {"name": "所属地区", "code": "f_region_type", "comp": "V", "dict": "service_area"},
            {"name": "企业性质", "code": "f_enterprise_nature", "comp": "V", "dict": "enterprise_nature"},
            {"name": "企业状态", "code": "f_enterprise_status", "comp": "V", "dict": "enterprise_status"},
            {"name": "证照类型", "code": "f_biz_license_no", "comp": "V", "dict": "license_type"},
            {"name": "证照编号", "code": "f_hk_biz_reg_no", "comp": "S"},
            {"name": "法定代表人", "code": "f_coop_legal_rep", "comp": "S"},
            {"name": "业务联系人", "code": "f_coop_contact_person", "comp": "S"},
            {"name": "联系人电话", "code": "f_coop_contact_phone", "comp": "P"},
            {"name": "联系人邮箱", "code": "f_coop_contact_email", "comp": "@"},
            {"name": "注册地址", "code": "f_coop_registered_address", "comp": "S"},
            {"name": "经营地址", "code": "f_coop_business_address", "comp": "S"},
            {"name": "合作范围", "code": "f_cooperation_scope", "comp": "VM", "dict": "cooperation_scope"},
            {"name": "合作状态", "code": "f_coop_status", "comp": "V", "dict": "cooperation_status"},
            {"name": "备注", "code": "f_coop_remark", "comp": "T"},
        ],
        "sub_tables": [
            {
                "name": "合作方专项资质子表", "code": "elab_cooperator_qualification",
                "fields": [
                    {"name": "资质类型", "code": "f_qual_type", "comp": "V", "dict": "qualification_type"},
                    {"name": "资质编号", "code": "f_qual_no", "comp": "S"},
                    {"name": "资质有效期开始", "code": "f_qual_valid_start", "comp": "D"},
                    {"name": "资质有效期结束", "code": "f_qual_valid_end", "comp": "D"},
                    {"name": "资质许可范围", "code": "f_qual_scope", "comp": "T"},
                    {"name": "资质附件", "code": "f_qual_attachment_url", "comp": "F"},
                    {"name": "资质状态", "code": "f_qual_status", "comp": "V", "dict": "qualification_status"},
                ]
            }
        ]
    },
    {
        "name": "合作商协议信息表", "code": "elab_cooperator_agreement",
        "fields": [
            {"name": "协议编号", "code": "f_agreement_no", "comp": "S"},
            {"name": "协议名称", "code": "f_agreement_name", "comp": "S"},
            {"name": "协议类型", "code": "f_agreement_type", "comp": "V", "dict": "agreement_type"},
            {"name": "合作方财务计算", "code": "f_cooperate_fa_method", "comp": "V"},
            {"name": "区域", "code": "f_agreement_area", "comp": "V", "dict": "service_area"},
            {"name": "合作方ID", "code": "f_agr_cooperator_id", "comp": "DS"},
            {"name": "合作方名称", "code": "f_agr_cooperator_name", "comp": "S"},
            {"name": "签约公司ID", "code": "f_our_company_id", "comp": "DS"},
            {"name": "签约公司名称", "code": "f_our_company_name", "comp": "S"},
            {"name": "签订日期", "code": "f_sign_date", "comp": "D"},
            {"name": "协议有效期开始", "code": "f_valid_start_date", "comp": "D"},
            {"name": "协议有效期结束", "code": "f_valid_end_date", "comp": "D"},
            {"name": "合作范围", "code": "f_agr_cooperation_scope", "comp": "T"},
            {"name": "支付条款", "code": "f_payment_terms", "comp": "T"},
            {"name": "协议状态", "code": "f_agreement_status", "comp": "V", "dict": "agreement_status"},
            {"name": "协议附件", "code": "f_agreement_attachment", "comp": "F"},
        ]
    },
    {
        "name": "合作商提成计提规则表", "code": "elab_cooperator_commission",
        "fields": [
            {"name": "关联合作方协议ID", "code": "f_comm_agreement_id", "comp": "DS"},
            {"name": "合作方ID", "code": "f_comm_cooperator_id", "comp": "S"},
            {"name": "适用范围", "code": "f_comm_range_area", "comp": "DS"},
            {"name": "区域", "code": "f_comm_area", "comp": "V", "dict": "service_area"},
            {"name": "合作方财务计算", "code": "f_comm_fa_method", "comp": "V"},
            {"name": "适用业务类型", "code": "f_comm_business_type", "comp": "V", "dict": "business_type"},
            {"name": "支付币种", "code": "f_comm_currency", "comp": "V", "dict": "currency"},
            {"name": "提成方式", "code": "f_comm_commission_type", "comp": "V", "dict": "commission_type"},
            {"name": "提成比例", "code": "f_comm_rate", "comp": "N"},
            {"name": "固定提成金额", "code": "f_comm_fixed_amount", "comp": "$"},
            {"name": "关联结算规则", "code": "f_comm_link_settlement", "comp": "DS"},
            {"name": "支付频率", "code": "f_comm_settlement_cycle", "comp": "V", "dict": "settlement_cycle"},
            {"name": "支付方式", "code": "f_comm_payment_method", "comp": "V", "dict": "payment_method"},
            {"name": "规则状态", "code": "f_comm_rule_status", "comp": "V", "dict": "rule_status"},
            {"name": "规则生效日期", "code": "f_comm_valid_start", "comp": "D"},
            {"name": "规则失效日期", "code": "f_comm_valid_end", "comp": "D"},
            {"name": "备注", "code": "f_comm_remark", "comp": "T"},
        ],
        "sub_tables": [
            {
                "name": "阶梯提成子表", "code": "ladder_commission",
                "fields": [
                    {"name": "阶梯起始值", "code": "f_ladder_start", "comp": "N"},
                    {"name": "阶梯结束值", "code": "f_ladder_end", "comp": "N"},
                    {"name": "阶梯提成比例", "code": "f_ladder_rate", "comp": "N"},
                ]
            }
        ]
    },
    {
        "name": "合作方结算周期", "code": "cooperator_settlement",
        "fields": [
            {"name": "结算周期流水", "code": "f_settle_agreement_id", "comp": "#"},
            {"name": "合作方ID", "code": "f_settle_cooperator_id", "comp": "S"},
            {"name": "合作方名称", "code": "f_settle_cooperator_name", "comp": "S"},
            {"name": "区域", "code": "f_settle_area", "comp": "V", "dict": "service_area"},
            {"name": "支付频率", "code": "f_settle_cycle", "comp": "V", "dict": "settlement_cycle"},
            {"name": "结算日期", "code": "f_settle_date", "comp": "S"},
            {"name": "支付方式", "code": "f_settle_payment_method", "comp": "V", "dict": "payment_method"},
            {"name": "支付比例", "code": "f_settle_pay_rate_way", "comp": "V", "dict": "pay_rate_way"},
            {"name": "结算周期状态", "code": "f_settle_pay_status", "comp": "V", "dict": "pay_status"},
        ],
        "sub_tables": [
            {
                "name": "按次支付子表", "code": "times_rate",
                "fields": [
                    {"name": "支付比例", "code": "f_times_pay_rate", "comp": "N"},
                    {"name": "支付节点", "code": "f_times_pay_node", "comp": "V", "dict": "pay_node"},
                ]
            },
            {
                "name": "其他频率支付子表", "code": "others_rate",
                "fields": [
                    {"name": "是否特殊支付", "code": "f_others_is_special", "comp": "V", "dict": "is_special"},
                    {"name": "支付次序", "code": "f_others_pay_order", "comp": "V", "dict": "pay_order"},
                    {"name": "支付月数", "code": "f_others_pay_month", "comp": "N"},
                ]
            }
        ]
    },
    {
        "name": "配额申请", "code": "elab_quotation_approval",
        "fields": [
            {"name": "批文编号", "code": "f_approval_no", "comp": "S"},
            {"name": "配额申请ID", "code": "f_quotation_approval_id", "comp": "#"},
            {"name": "批准书类型", "code": "f_qa_approval_type", "comp": "V", "dict": "approval_type"},
            {"name": "行业", "code": "f_qa_company_type", "comp": "DS"},
            {"name": "签发单位", "code": "f_qa_issuance_units", "comp": "S"},
            {"name": "配额批准部门联系邮箱", "code": "f_qa_issuance_mail", "comp": "@"},
            {"name": "雇主", "code": "f_qa_partner_company", "comp": "DS"},
            {"name": "雇主编码", "code": "f_qa_employer_id", "comp": "S"},
            {"name": "签约组织", "code": "f_qa_org_structure", "comp": "DS"},
            {"name": "签约组织ID", "code": "f_qa_org_structure_id", "comp": "S"},
            {"name": "合作方", "code": "f_qa_cooperator_code", "comp": "DS"},
            {"name": "批准配额总数量", "code": "f_qa_quotation_num", "comp": "N"},
            {"name": "劳务合同生成数量", "code": "f_qa_contract_num", "comp": "N"},
            {"name": "已使用配额数量", "code": "f_qa_used_num", "comp": "N"},
            {"name": "有效期开始日期", "code": "f_qa_valid_start", "comp": "D"},
            {"name": "有效期结束日期", "code": "f_qa_valid_end", "comp": "D"},
            {"name": "负责人姓名", "code": "f_qa_responsible_person", "comp": "S"},
            {"name": "负责人电话", "code": "f_qa_responsible_phone", "comp": "P"},
            {"name": "批准书状态", "code": "f_qa_approval_status", "comp": "V", "dict": "approval_status"},
            {"name": "配额批准书上传", "code": "f_qa_attachment_url", "comp": "F"},
        ],
        "sub_tables": [
            {
                "name": "配额批准书明细", "code": "table_elab_quotation",
                "fields": [
                    {"name": "配额申请ID", "code": "f_sub_qa_id", "comp": "S"},
                    {"name": "配额申请明细ID", "code": "f_sub_detail_id", "comp": "#"},
                    {"name": "合作方", "code": "f_sub_co_name", "comp": "DS"},
                    {"name": "配额明细编号", "code": "f_sub_detail_no", "comp": "S"},
                    {"name": "配额数目", "code": "f_sub_detail_num", "comp": "N"},
                    {"name": "雇佣期", "code": "f_sub_hire_period", "comp": "V", "dict": "hire_period"},
                    {"name": "工种/职位", "code": "f_sub_job_type", "comp": "V", "dict": "job_type"},
                    {"name": "工作地点", "code": "f_sub_work_place", "comp": "S"},
                    {"name": "每日工作时数", "code": "f_sub_daily_hours", "comp": "N"},
                    {"name": "每月工作日数", "code": "f_sub_monthly_days", "comp": "N"},
                    {"name": "每月工资(雇主货币)", "code": "f_sub_monthly_salary", "comp": "$"},
                    {"name": "币种", "code": "f_sub_salary_currency", "comp": "V", "dict": "currency"},
                    {"name": "备注", "code": "f_sub_qa_remark", "comp": "S"},
                ]
            }
        ]
    },
    {
        "name": "配额明细表", "code": "elab_quotation_detail",
        "fields": [
            {"name": "配额明细ID", "code": "f_detail_id", "comp": "#"},
            {"name": "配额序号", "code": "f_elab_num", "comp": "S"},
            {"name": "配额批准书ID", "code": "f_qd_approval_id", "comp": "S"},
            {"name": "批文编号", "code": "f_qd_approval_no", "comp": "S"},
            {"name": "雇主ID", "code": "f_qd_employer_id", "comp": "DS"},
            {"name": "雇主名称", "code": "f_qd_employer_name", "comp": "S"},
            {"name": "签约公司ID", "code": "f_qd_sign_company_id", "comp": "DS"},
            {"name": "签约公司名称", "code": "f_qd_sign_company_name", "comp": "S"},
            {"name": "可用数量", "code": "f_qd_available_num", "comp": "N"},
            {"name": "已用数量", "code": "f_qd_used_num", "comp": "N"},
            {"name": "分配人员ID", "code": "f_qd_assigned_person_id", "comp": "S"},
            {"name": "分配人员姓名", "code": "f_qd_assigned_person_name", "comp": "S"},
            {"name": "是否生效", "code": "f_qd_is_effective", "comp": "V", "dict": "is_effective"},
            {"name": "绑定时间", "code": "f_qd_start_time_link", "comp": "D"},
            {"name": "有效时间开始", "code": "f_qd_effective_start", "comp": "D"},
            {"name": "有效时间结束", "code": "f_qd_effective_end", "comp": "D"},
            {"name": "明细配额分配状态", "code": "f_qd_allocation_status", "comp": "V", "dict": "detail_allocation_status"},
            {"name": "可替换次数", "code": "f_qd_available_change_num", "comp": "N"},
            {"name": "已替换次数", "code": "f_qd_have_change_num", "comp": "N"},
        ]
    },
    {
        "name": "配额明细记录", "code": "elab_quotation_detail_record",
        "fields": [
            {"name": "配额明细ID", "code": "f_rec_detail_id", "comp": "S"},
            {"name": "配额批准书ID", "code": "f_rec_approval_id", "comp": "S"},
            {"name": "配额序号", "code": "f_rec_elab_num", "comp": "S"},
            {"name": "批文编号", "code": "f_rec_approval_no", "comp": "S"},
            {"name": "雇主ID", "code": "f_rec_employer_id", "comp": "S"},
            {"name": "雇主名称", "code": "f_rec_employer_name", "comp": "S"},
            {"name": "签约公司ID", "code": "f_rec_sign_company_id", "comp": "S"},
            {"name": "签约公司名称", "code": "f_rec_sign_company_name", "comp": "S"},
            {"name": "分配人员ID", "code": "f_rec_assigned_id", "comp": "S"},
            {"name": "分配人员姓名", "code": "f_rec_assigned_name", "comp": "S"},
            {"name": "分配时间", "code": "f_rec_create_time", "comp": "D"},
        ]
    },
    {
        "name": "雇主合作委托申请", "code": "elab_employer_cooperation_apply",
        "fields": [
            {"name": "雇主合作委托流水码", "code": "f_apply_approval_code", "comp": "#"},
            {"name": "配额申请ID", "code": "f_apply_quota_id", "comp": "DS"},
            {"name": "行业", "code": "f_apply_company_type", "comp": "DS"},
            {"name": "签发单位", "code": "f_apply_issuance_units", "comp": "S"},
            {"name": "雇主", "code": "f_apply_partner_company", "comp": "DS"},
            {"name": "雇主编码", "code": "f_apply_employer_id", "comp": "S"},
            {"name": "签约组织", "code": "f_apply_org_structure", "comp": "DS"},
            {"name": "签约组织ID", "code": "f_apply_org_id", "comp": "S"},
            {"name": "说明", "code": "f_apply_remark", "comp": "T"},
            {"name": "附件上传", "code": "f_apply_file_upload", "comp": "F"},
            {"name": "流程标题", "code": "f_apply_process_title", "comp": "S"},
        ]
    },
]


# ============================================================
# 辅助函数
# ============================================================

async def add_dict_option(http: httpx.AsyncClient, headers: dict, app_id: str, dict_id: str, opt_name: str, opt_code: str, order: int):
    """添加单个字典选项"""
    await http.post(
        f"{BASE_URL}/xdap-app/dataDictionary/add/dictionaryValue",
        headers=headers,
        json={
            "appId": app_id,
            "dictionaryId": dict_id,
            "valueCode": opt_code,
            "valueName": opt_name,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "",
            "valueNameI18n": {},
            "displayOrder": order,
            "valueDescribe": "",
            "valueStatus": "ENABLE",
            "valueMulticolor": "#027AFF",
        },
    )


# ============================================================
# 主流程
# ============================================================

async def main():
    client = APaaSClient(base_url=BASE_URL, tenant_id=TENANT_ID)
    await client.login(USERNAME, PASSWORD)
    print(f"✅ 登录成功")

    app_id = APP_ID
    headers = client._get_headers(app_id)

    # ── Phase 1: 创建字典 ──
    print(f"\n{'='*60}")
    print(f"Phase 1: 创建 {len(DICTS)} 个数据字典")
    print(f"{'='*60}")

    existing_dicts = await client.query_dicts(app_id)
    existing_dict_names = {d.get("dictionaryName") for d in existing_dicts}
    dict_id_map = {}  # code -> id

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        for i, d in enumerate(DICTS):
            if d["name"] in existing_dict_names:
                print(f"  [{i+1}/{len(DICTS)}] ⏭ {d['name']} (已存在)")
                # 找到已存在的 dict ID
                for ed in existing_dicts:
                    if ed.get("dictionaryName") == d["name"]:
                        dict_id_map[d["code"]] = ed["id"]
                continue

            try:
                await client.create_dicts(app_id, [{
                    "appId": app_id,
                    "dictionaryCode": d["code"],
                    "dictionaryName": d["name"],
                    "dictionaryOptions": [],
                }])
                print(f"  [{i+1}/{len(DICTS)}] ✅ {d['name']} ({d['code']})")
            except Exception as e:
                if "重复" in str(e):
                    print(f"  [{i+1}/{len(DICTS)}] ⏭ {d['name']} (编码重复)")
                else:
                    print(f"  [{i+1}/{len(DICTS)}] ❌ {d['name']}: {e}")
                    continue

        # 刷新获取所有字典ID
        all_dicts = await client.query_dicts(app_id)
        dict_by_code = {d.get("dictionaryCode"): d for d in all_dicts}

        # 添加选项
        print(f"\n  添加字典选项...")
        for d in DICTS:
            dc = d["code"]
            obj = dict_by_code.get(dc)
            if not obj:
                continue
            dict_id = obj["id"]
            dict_id_map[dc] = dict_id

            # 检查是否已有选项
            existing_opts = await client.query_dict_options(app_id, dict_id)
            if existing_opts:
                print(f"    ⏭ {d['name']}: 已有 {len(existing_opts)} 个选项")
                continue

            for idx, opt in enumerate(d["options"]):
                opt_code = f"{dc}_opt{idx}"
                try:
                    await add_dict_option(http, headers, app_id, dict_id, opt, opt_code, idx)
                except Exception as e:
                    print(f"    ❌ {d['name']}.{opt}: {e}")
            print(f"    ✅ {d['name']}: {len(d['options'])} 个选项")

    print(f"\n  字典创建完成: {len(dict_id_map)} 个")

    # ── Phase 2: 创建数据模型 ──
    print(f"\n{'='*60}")
    print(f"Phase 2: 创建 {len(MODELS)} 个数据模型")
    print(f"{'='*60}")

    existing_models = await client.query_models(app_id)
    existing_model_names = {m.get("modelName") for m in existing_models}
    model_code_map = {}  # model_name -> modelCode

    for i, m in enumerate(MODELS):
        if m["name"] in existing_model_names:
            print(f"  [{i+1}/{len(MODELS)}] ⏭ {m['name']} (已存在)")
            for em in existing_models:
                if em.get("modelName") == m["name"]:
                    model_code_map[m["name"]] = em["modelCode"]
            continue

        data_models = []

        # 子表模型先创建
        if m.get("sub_tables"):
            for st in m["sub_tables"]:
                sub_fields = [
                    {"fieldName": f["name"], "fieldCode": f["code"], "fieldType": MODEL_TYPE_MAP.get(f.get("comp", "S"), "STRING"), "fieldDescription": ""}
                    for f in st["fields"]
                ]
                data_models.append({
                    "appId": app_id, "modelName": st["name"],
                    "modelCode": st["code"], "modelDescription": st["name"],
                    "fields": sub_fields,
                })

        # 主模型
        main_fields = [
            {"fieldName": f["name"], "fieldCode": f["code"], "fieldType": MODEL_TYPE_MAP.get(f.get("comp", "S"), "STRING"), "fieldDescription": ""}
            for f in m["fields"]
        ]
        data_models.append({
            "appId": app_id, "modelName": m["name"],
            "modelCode": m["code"], "modelDescription": m["name"],
            "fields": main_fields,
        })

        try:
            payload = {"appId": app_id, "datasourceId": "", "dataModels": data_models}
            await client.create_models(app_id, payload)
            model_code_map[m["name"]] = m["code"]
            sub_count = len(m.get("sub_tables", []))
            print(f"  [{i+1}/{len(MODELS)}] ✅ {m['name']} ({len(main_fields)} 字段" + (f", {sub_count} 个子表)" if sub_count else ")"))
        except Exception as e:
            if "重复" in str(e) or "已存在" in str(e):
                model_code_map[m["name"]] = m["code"]
                print(f"  [{i+1}/{len(MODELS)}] ⏭ {m['name']} (编码重复，复用)")
            else:
                print(f"  [{i+1}/{len(MODELS)}] ❌ {m['name']}: {e}")

    print(f"\n  模型创建完成: {len(model_code_map)} 个")

    # ── Phase 3: 创建表单 ──
    print(f"\n{'='*60}")
    print(f"Phase 3: 创建表单")
    print(f"{'='*60}")

    # 刷新模型信息
    refreshed_models = await client.query_models(app_id)
    ref_by_code = {rm.get("modelCode"): rm for rm in refreshed_models}

    form_results = []
    for i, m in enumerate(MODELS):
        mc = model_code_map.get(m["name"], m["code"])
        rm = ref_by_code.get(mc)
        if not rm:
            print(f"  [{i+1}/{len(MODELS)}] ⏭ {m['name']} (模型不存在)")
            continue

        # 提取字段映射
        field_map = {f.get("fieldName"): f.get("fieldCode") for f in rm.get("fields", [])}

        # 构建组件
        components = []
        all_model_codes = [mc]

        for f in m["fields"]:
            fc = field_map.get(f["name"], f["code"])
            comp_key = f.get("comp", "S")
            comp_type = COMP_MAP.get(comp_key, "FORM_TEXT_INPUT")

            comp = {
                "componentType": comp_type,
                "label": f["name"],
                "modelField": f"{mc}.{fc}",
            }

            # 下拉选择绑定字典
            if comp_key in ("V", "VM") and f.get("dict"):
                dc = f["dict"]
                did = dict_id_map.get(dc)
                if did:
                    comp["dictionarySelectConfig"] = {
                        "dictionaryCode": dc,
                        "dictionarySelectOptions": [],
                    }
                    if comp_key == "VM":
                        comp["chooseType"] = "MULTIPLE"

            components.append(comp)

        # 子表
        if m.get("sub_tables"):
            for st in m["sub_tables"]:
                st_rm = ref_by_code.get(st["code"])
                if not st_rm:
                    continue
                all_model_codes.append(st["code"])
                st_field_map = {f.get("fieldName"): f.get("fieldCode") for f in st_rm.get("fields", [])}
                sub_cols = []
                for sf in st["fields"]:
                    sfc = st_field_map.get(sf["name"], sf["code"])
                    sf_comp_key = sf.get("comp", "S")
                    sf_comp_type = COMP_MAP.get(sf_comp_key, "FORM_TEXT_INPUT")
                    sub_comp = {"componentType": sf_comp_type, "label": sf["name"], "modelField": f"{st['code']}.{sfc}"}
                    # 子表字段也绑字典
                    if sf_comp_key in ("V", "VM") and sf.get("dict"):
                        dc = sf["dict"]
                        did = dict_id_map.get(dc)
                        if did:
                            sub_comp["dictionarySelectConfig"] = {"dictionaryCode": dc, "dictionarySelectOptions": []}
                    sub_cols.append(sub_comp)
                if sub_cols:
                    components.append({
                        "componentType": "FORM_WIDGET_SON_TABLE",
                        "label": st["name"],
                        "tableColumn": sub_cols,
                    })

        if not components:
            continue

        # 列表查询字段（前4个STRING字段）
        query_conditions = []
        query_list = []
        for f in m["fields"][:8]:
            fc = field_map.get(f["name"], f["code"])
            mf = f"{mc}.{fc}"
            if len(query_conditions) < 4:
                query_conditions.append(mf)
            query_list.append(mf)

        form_payload = [{
            "formName": m["name"],
            "formCode": f"form_{m['code'][:20]}",
            "allModelCodes": all_model_codes,
            "formComponents": components,
            "listPageView": {
                "queryConditions": query_conditions,
                "queryList": query_list,
            },
        }]

        try:
            result = await client.create_form_config(app_id, form_payload)
            form_id = ""
            if isinstance(result, list):
                for fr in result:
                    if isinstance(fr, dict) and "id" in fr:
                        form_id = fr["id"]
                        form_results.append({"formId": form_id, "formName": m["name"], "formCode": fr.get("formCode", "")})
            sub_count = len(m.get("sub_tables", []))
            print(f"  [{i+1}/{len(MODELS)}] ✅ {m['name']} ({len(components)} 组件" + (f", {sub_count} 子表)" if sub_count else ")"))
        except Exception as e:
            print(f"  [{i+1}/{len(MODELS)}] ❌ {m['name']}: {e}")

    print(f"\n  表单创建完成: {len(form_results)} 个")

    # ── Phase 4: 权限配置 ──
    print(f"\n{'='*60}")
    print(f"Phase 4: 配置权限")
    print(f"{'='*60}")

    perm_payloads = []
    for fr in form_results:
        perm_payloads.append({
            "formCode": fr.get("formCode", ""),
            "appId": app_id,
            "tenantId": "",
            "formId": fr["formId"],
            "operationPermissionGroups": [{
                "permissionName": "默认操作权限",
                "permissionDescribe": "全部人员可操作",
                "PermissionObjects": [{
                    "permissionObjectDisplayName": "全部人员",
                    "permissionObjectType": "ALL_USER",
                    "permissionObjectValue": "",
                    "permissionRange": {"rangeType": "ALL"},
                }],
                "permissionOperationType": {
                    "addPermission": True, "batchDeletePermission": False,
                    "batchAgreePermission": False, "batchRejectPermission": False,
                    "copyAddPermission": False, "importPermission": False,
                    "shareFormPermission": False, "temporaryStoragePermission": False,
                },
            }],
            "dataPermissionGroups": [{
                "permissionName": "默认数据权限",
                "permissionDescribe": "全部人员可查看全部数据",
                "permissionObjects": [{
                    "permissionObjectDisplayName": "全部人员",
                    "permissionObjectType": "ALL_USER",
                    "permissionObjectValue": "",
                    "permissionRange": {"rangeType": "ALL"},
                }],
                "permissionOperationType": {
                    "queryPermission": True, "deletePermission": False, "updatePermission": False,
                },
            }],
        })

    if perm_payloads:
        try:
            await client.create_form_permissions(app_id, perm_payloads)
            print(f"  ✅ {len(perm_payloads)} 个表单权限配置完成")
        except Exception as e:
            print(f"  ❌ 权限配置失败: {e}")

    # ── 完成 ──
    print(f"\n{'='*60}")
    print(f"🎉 劳务管理系统创建完成！")
    print(f"  应用ID: {app_id}")
    print(f"  字典: {len(dict_id_map)} 个")
    print(f"  模型: {len(model_code_map)} 个")
    print(f"  表单: {len(form_results)} 个")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
