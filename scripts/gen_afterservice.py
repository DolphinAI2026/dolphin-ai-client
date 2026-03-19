#!/usr/bin/env python3
"""Generate dataModels + formConfigs JSON for 全球售后系统-功能设计.md"""
import json

# All dictionaries referenced in the design doc
DICTS = {
    "region": [{"id":"cn","label":"中国区"},{"id":"eu","label":"欧洲区"},{"id":"na","label":"北美区"},{"id":"apac","label":"亚太区"}],
    "customer_level": [{"id":"vip","label":"VIP"},{"id":"normal","label":"普通"},{"id":"strategic","label":"战略客户"}],
    "timezone": [{"id":"UTC","label":"UTC"},{"id":"UTC8","label":"UTC+8"},{"id":"UTC1","label":"UTC+1"},{"id":"UTC_5","label":"UTC-5"}],
    "device_status": [{"id":"running","label":"运行中"},{"id":"stopped","label":"停机"},{"id":"scrapped","label":"报废"},{"id":"maintenance","label":"维修中"}],
    "skill_tag": [{"id":"mechanical","label":"机械"},{"id":"electrical","label":"电气"},{"id":"software","label":"软件"},{"id":"hydraulic","label":"液压"}],
    "engineer_status": [{"id":"active","label":"在职"},{"id":"leave","label":"休假"},{"id":"resigned","label":"离职"}],
    "part_category": [{"id":"consumable","label":"易耗件"},{"id":"spare","label":"备件"},{"id":"tool","label":"工具"}],
    "part_status": [{"id":"enabled","label":"启用"},{"id":"disabled","label":"停用"}],
    "fault_type": [{"id":"hardware","label":"硬件故障"},{"id":"software","label":"软件故障"},{"id":"network","label":"网络故障"},{"id":"other","label":"其他"}],
    "order_source": [{"id":"phone","label":"电话"},{"id":"email","label":"邮件"},{"id":"portal","label":"自助门户"},{"id":"wechat","label":"微信"}],
    "priority": [{"id":"urgent","label":"紧急"},{"id":"high","label":"高"},{"id":"medium","label":"中"},{"id":"low","label":"低"}],
    "order_status": [{"id":"new","label":"新建"},{"id":"accepted","label":"已受理"},{"id":"processing","label":"处理中"},{"id":"pending_parts","label":"待配件"},{"id":"completed","label":"已完成"},{"id":"closed","label":"已关闭"}],
    "dispatch_type": [{"id":"first","label":"首次派单"},{"id":"reassign","label":"改派"},{"id":"escalate","label":"升级"}],
    "dispatch_status": [{"id":"dispatched","label":"已派"},{"id":"accepted","label":"已接单"},{"id":"rejected","label":"拒绝"},{"id":"done","label":"已完成"}],
    "repair_result": [{"id":"fixed","label":"已修复"},{"id":"pending_parts","label":"待配件"},{"id":"cannot_fix","label":"无法修复"}],
    "qc_result": [{"id":"pass","label":"合格"},{"id":"fail","label":"不合格"}],
    "part_flow_type": [{"id":"request","label":"备件申请"},{"id":"outbound","label":"配件出库"},{"id":"inbound","label":"配件入库"},{"id":"adjust","label":"库存调整"}],
    "approval_status": [{"id":"pending","label":"待审批"},{"id":"approved","label":"已通过"},{"id":"rejected","label":"已拒绝"}],
    "sla_result": [{"id":"ok","label":"达标"},{"id":"overtime","label":"超时"}],
    "fee_type": [{"id":"labor","label":"人工费"},{"id":"parts","label":"配件费"},{"id":"travel","label":"差旅费"},{"id":"other","label":"其他"}],
    "currency": [{"id":"CNY","label":"人民币"},{"id":"USD","label":"美元"},{"id":"EUR","label":"欧元"}],
    "audit_status": [{"id":"pending","label":"待审核"},{"id":"approved","label":"已审核"},{"id":"settled","label":"已结算"}],
    "audit_action": [{"id":"create","label":"新增"},{"id":"update","label":"修改"},{"id":"delete","label":"删除"},{"id":"approve","label":"审批"}],
    "biz_object_type": [{"id":"service_order","label":"工单"},{"id":"dispatch","label":"派单"},{"id":"part_flow","label":"备件流转"},{"id":"settlement","label":"结算"}],
    "user_status": [{"id":"enabled","label":"启用"},{"id":"disabled","label":"停用"}],
    "role_status": [{"id":"enabled","label":"启用"},{"id":"disabled","label":"停用"}],
}

def f(name, code, ft, ct, l=None, q=None, d=None, rm=None, rf=None):
    """Compact field builder"""
    return {"name":name,"code":code,"ft":ft,"ct":ct,"l":l,"q":q,"d":d,"rm":rm,"rf":rf}

FORMS = [
  {"model":"customer","name":"客户主数据","fields":[
    f("客户ID","customer_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("客户名称","customer_name","STRING","FORM_TEXT_INPUT",2,2),
    f("国家/区域","country_region","STRING","FORM_SELECT_INPUT_SINGLE",3,3,d="region"),
    f("联系人","contact_name","STRING","FORM_TEXT_INPUT",4,4),
    f("联系电话","contact_phone","STRING","FORM_PHONE_INPUT",5,5),
    f("客户等级","customer_level","STRING","FORM_SELECT_INPUT_SINGLE",6,6,d="customer_level"),
    f("备注","remark_info","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"site","name":"站点主数据","fields":[
    f("站点ID","site_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("所属客户","customer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="customer",rf="customer_name"),
    f("站点名称","site_name","STRING","FORM_TEXT_INPUT",3,3),
    f("地理位置","location_info","STRING","FORM_WIDGET_LOCATION",4),
    f("时区","timezone_val","STRING","FORM_SELECT_INPUT_SINGLE",5,4,d="timezone"),
    f("备注","remark_info","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"device","name":"设备主数据","fields":[
    f("设备ID","device_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("设备名称","device_name","STRING","FORM_TEXT_INPUT",2,2),
    f("SN序列号","serial_no","STRING","FORM_TEXT_INPUT",3,3),
    f("型号","model_no","STRING","FORM_TEXT_INPUT",4,4),
    f("安装日期","install_date","DATE","FORM_DATEPICK_INPUT",5),
    f("保修截止日期","warranty_end","DATE","FORM_DATEPICK_INPUT",6,5),
    f("设备状态","device_status","STRING","FORM_SELECT_INPUT_SINGLE",7,6,d="device_status"),
    f("所属客户","customer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",8,7,rm="customer",rf="customer_name"),
    f("所属站点","site_ref","STRING","FORM_DATA_SELECTOR_SINGLE",9,None,rm="site",rf="site_name"),
  ]},
  {"model":"engineer","name":"工程师主数据","fields":[
    f("工程师ID","engineer_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("姓名","eng_name","STRING","FORM_TEXT_INPUT",2,2),
    f("区域","region_val","STRING","FORM_SELECT_INPUT_SINGLE",3,3,d="region"),
    f("技能标签","skill_tag","STRING","FORM_SELECT_INPUT",4,4,d="skill_tag"),
    f("手机号","phone_no","STRING","FORM_PHONE_INPUT",5,5),
    f("邮箱","email_addr","STRING","FORM_EMAIL_INPUT"),
    f("在职状态","eng_status","STRING","FORM_SELECT_INPUT_SINGLE",6,6,d="engineer_status"),
  ]},
  {"model":"part_info","name":"配件主数据","fields":[
    f("配件编码","part_code","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("配件名称","part_name","STRING","FORM_TEXT_INPUT",2,2),
    f("规格型号","spec_info","STRING","FORM_TEXT_INPUT",3,3),
    f("单位","unit_val","STRING","FORM_TEXT_INPUT",4,4),
    f("分类","category_val","STRING","FORM_SELECT_INPUT_SINGLE",5,5,d="part_category"),
    f("成本价","cost_price","NUM","FORM_NUMBER_INPUT",6),
    f("售价","retail_price","NUM","FORM_NUMBER_INPUT",7),
    f("状态","part_status","STRING","FORM_SELECT_INPUT_SINGLE",8,6,d="part_status"),
  ]},
  {"model":"warehouse","name":"仓库主数据","fields":[
    f("仓库ID","warehouse_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("仓库名称","warehouse_name","STRING","FORM_TEXT_INPUT",2,2),
    f("区域","region_val","STRING","FORM_SELECT_INPUT_SINGLE",3,3,d="region"),
    f("地址","address_info","BIG_TEXT","FORM_TEXTAREA_INPUT",4),
    f("仓库负责人","manager_user","STRING","FORM_PEOPLE_SELECT",5,4),
  ]},
  {"model":"service_order","name":"工单","fields":[
    f("工单编号","order_code","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单标题","order_title","STRING","FORM_TEXT_INPUT",2,2),
    f("客户","customer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",3,3,rm="customer",rf="customer_name"),
    f("站点","site_ref","STRING","FORM_DATA_SELECTOR_SINGLE",4,4,rm="site",rf="site_name"),
    f("设备","device_ref","STRING","FORM_DATA_SELECTOR_SINGLE",5,5,rm="device",rf="serial_no"),
    f("联系人","contact_name","STRING","FORM_TEXT_INPUT",6),
    f("联系电话","contact_phone","STRING","FORM_PHONE_INPUT",7),
    f("故障类型","fault_type","STRING","FORM_SELECT_INPUT_SINGLE",8,6,d="fault_type"),
    f("故障描述","fault_desc","BIG_TEXT","FORM_TEXTAREA_INPUT"),
    f("报修来源","order_source","STRING","FORM_SELECT_INPUT_SINGLE",9,7,d="order_source"),
    f("优先级","priority_val","STRING","FORM_SELECT_INPUT_SINGLE",10,8,d="priority"),
    f("当前状态","order_status","STRING","FORM_SELECT_INPUT_SINGLE",11,9,d="order_status"),
    f("是否需要配件","need_parts","STRING","FORM_SWITCH_SELECT",12),
    f("受理时间","created_at","DATE","FORM_DATEPICK_INPUT",13),
    f("预计完成时间","expected_finish","DATE","FORM_DATEPICK_INPUT",14),
    f("附件","attachments","STRING","FORM_FILE_UPLOAD"),
    f("备注","remark_info","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"dispatch_log","name":"派单日志","fields":[
    f("派单编号","dispatch_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单编号","order_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="service_order",rf="order_code"),
    f("派单类型","dispatch_type","STRING","FORM_SELECT_INPUT_SINGLE",3,3,d="dispatch_type"),
    f("派单人","dispatch_user","STRING","FORM_PEOPLE_SELECT",4,4),
    f("被指派工程师","engineer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",5,5,rm="engineer",rf="eng_name"),
    f("派单时间","dispatch_time","DATE","FORM_DATEPICK_INPUT",6),
    f("接单时间","accepted_time","DATE","FORM_DATEPICK_INPUT",7),
    f("状态","dispatch_status","STRING","FORM_SELECT_INPUT_SINGLE",8,6,d="dispatch_status"),
    f("派单备注","dispatch_remark","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"service_record","name":"服务执行与质检","sub_models":["service_record_parts"],
   "fields":[
    f("记录编号","record_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单编号","order_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="service_order",rf="order_code"),
    f("工程师","engineer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",3,3,rm="engineer",rf="eng_name"),
    f("到场时间","arrival_time","DATE","FORM_DATEPICK_INPUT",4),
    f("开始时间","start_time","DATE","FORM_DATEPICK_INPUT",5),
    f("结束时间","end_time","DATE","FORM_DATEPICK_INPUT",6),
    f("工时","duration_val","NUM","FORM_NUMBER_INPUT",7),
    f("维修结果","result_type","STRING","FORM_SELECT_INPUT_SINGLE",8,4,d="repair_result"),
    f("执行内容","work_desc","BIG_TEXT","FORM_TEXTAREA_INPUT"),
    f("现场图片","photos","STRING","FORM_FILE_UPLOAD"),
    f("客户确认","customer_signed","STRING","FORM_SWITCH_SELECT",9,5),
    f("质检结果","qc_result","STRING","FORM_SELECT_INPUT_SINGLE",10,6,d="qc_result"),
    f("质检说明","qc_comment","BIG_TEXT","FORM_TEXTAREA_INPUT"),
    f("提交时间","created_at","DATE","FORM_DATEPICK_INPUT",11,7),
  ],"sub_table":{"label":"使用配件明细","model":"service_record_parts","fields":[
    f("配件编码","part_ref","STRING","FORM_DATA_SELECTOR_SINGLE",rm="part_info",rf="part_code"),
    f("使用数量","qty_val","NUM","FORM_NUMBER_INPUT"),
  ]}},
  {"model":"part_flow_ledger","name":"备件申请与库存台账","fields":[
    f("流转单号","flow_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单编号","order_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="service_order",rf="order_code"),
    f("业务类型","flow_type","STRING","FORM_SELECT_INPUT_SINGLE",3,3,d="part_flow_type"),
    f("仓库","warehouse_ref","STRING","FORM_DATA_SELECTOR_SINGLE",4,4,rm="warehouse",rf="warehouse_name"),
    f("配件编码","part_ref","STRING","FORM_DATA_SELECTOR_SINGLE",5,5,rm="part_info",rf="part_code"),
    f("申请数量","qty_request","NUM","FORM_NUMBER_INPUT",6),
    f("出库数量","qty_out","NUM","FORM_NUMBER_INPUT",7),
    f("入库数量","qty_in","NUM","FORM_NUMBER_INPUT",8),
    f("当前库存","qty_current","NUM","FORM_NUMBER_INPUT",9,6),
    f("锁定库存","qty_locked","NUM","FORM_NUMBER_INPUT",10),
    f("可用库存","qty_available","NUM","FORM_NUMBER_INPUT",11,7),
    f("审批状态","approval_status","STRING","FORM_SELECT_INPUT_SINGLE",12,8,d="approval_status"),
    f("审批人","approval_user","STRING","FORM_PEOPLE_SELECT",13),
    f("发生时间","flow_time","DATE","FORM_DATEPICK_INPUT",14,9),
    f("备注","remark_info","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"sla_record","name":"SLA记录","fields":[
    f("SLA编号","sla_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单编号","order_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="service_order",rf="order_code"),
    f("报修时间","created_at","DATE","FORM_DATEPICK_INPUT",3,3),
    f("接单时间","accepted_time","DATE","FORM_DATEPICK_INPUT",4),
    f("响应时长(小时)","response_hours","NUM","FORM_NUMBER_INPUT",5),
    f("修复时长(小时)","repair_hours","NUM","FORM_NUMBER_INPUT",6),
    f("SLA结果","sla_result","STRING","FORM_SELECT_INPUT_SINGLE",7,4,d="sla_result"),
  ]},
  {"model":"settlement","name":"结算单","fields":[
    f("结算单号","settle_code","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("工单编号","order_ref","STRING","FORM_DATA_SELECTOR_SINGLE",2,2,rm="service_order",rf="order_code"),
    f("客户","customer_ref","STRING","FORM_DATA_SELECTOR_SINGLE",3,3,rm="customer",rf="customer_name"),
    f("费用项","fee_type","STRING","FORM_SELECT_INPUT_SINGLE",4,4,d="fee_type"),
    f("金额","amount_val","NUM","FORM_MONEY_INPUT",5),
    f("币种","currency_val","STRING","FORM_SELECT_INPUT_SINGLE",6,5,d="currency"),
    f("审核状态","audit_status","STRING","FORM_SELECT_INPUT_SINGLE",7,6,d="audit_status"),
  ]},
  {"model":"audit_log","name":"审计日志","fields":[
    f("日志编号","log_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("业务对象类型","biz_type","STRING","FORM_SELECT_INPUT_SINGLE",2,2,d="biz_object_type"),
    f("业务对象ID","biz_id","STRING","FORM_TEXT_INPUT",3,3),
    f("操作类型","action_type","STRING","FORM_SELECT_INPUT_SINGLE",4,4,d="audit_action"),
    f("操作人","operator_user","STRING","FORM_PEOPLE_SELECT",5,5),
    f("操作时间","operate_time","DATE","FORM_DATEPICK_INPUT",6,6),
    f("操作前快照","before_snapshot","BIG_TEXT","FORM_TEXTAREA_INPUT"),
    f("操作后快照","after_snapshot","BIG_TEXT","FORM_TEXTAREA_INPUT"),
  ]},
  {"model":"sys_user_info","name":"系统用户","fields":[
    f("用户ID","user_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("登录账号","account_name","STRING","FORM_TEXT_INPUT",2,2),
    f("用户姓名","username_val","STRING","FORM_TEXT_INPUT",3,3),
    f("手机号","phone_no","STRING","FORM_PHONE_INPUT",4,4),
    f("邮箱","email_addr","STRING","FORM_EMAIL_INPUT"),
    f("所属区域","region_val","STRING","FORM_SELECT_INPUT_SINGLE",5,5,d="region"),
    f("状态","user_status","STRING","FORM_SELECT_INPUT_SINGLE",6,6,d="user_status"),
  ]},
  {"model":"sys_role_info","name":"系统角色","fields":[
    f("角色ID","role_id","STRING","FORM_DOCUMENT_NUMBER",1,1),
    f("角色编码","role_code","STRING","FORM_TEXT_INPUT",2,2),
    f("角色名称","role_name","STRING","FORM_TEXT_INPUT",3,3),
    f("角色描述","role_desc","BIG_TEXT","FORM_TEXTAREA_INPUT"),
    f("启用状态","role_status","STRING","FORM_SELECT_INPUT_SINGLE",4,4,d="role_status"),
  ]},
]


def build_component(fld, model_code):
    comp = {"componentType": fld["ct"], "label": fld["name"],
            "modelField": f"{model_code}.{fld['code']}"}
    if fld.get("d"):
        comp["dictionarySelectConfig"] = {
            "dictionaryCode": fld["d"],
            "dictionarySelectOptions": DICTS.get(fld["d"], [])
        }
    if fld.get("rm"):
        comp["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": fld["rm"],
            "otherFieldCode": fld["rf"]
        }
    return comp


def generate():
    data_models = []
    form_configs = []

    for form in FORMS:
        mc = form["model"]
        # --- dataModel ---
        model = {"modelName": form["name"], "modelCode": mc,
                 "description": form["name"], "fields": []}
        for fld in form["fields"]:
            model["fields"].append({"fieldName": fld["name"], "fieldCode": fld["code"],
                                    "fieldType": fld["ft"], "fieldDescription": fld["name"]})
        # sub-table model
        sub = form.get("sub_table")
        sub_model = None
        if sub:
            sub_model = {"modelName": sub["label"], "modelCode": sub["model"],
                         "description": sub["label"], "fields": []}
            for sf in sub["fields"]:
                sub_model["fields"].append({"fieldName": sf["name"], "fieldCode": sf["code"],
                                            "fieldType": sf["ft"], "fieldDescription": sf["name"]})
            data_models.append(sub_model)
        data_models.append(model)

        # --- formConfig ---
        all_codes = [mc]
        if sub:
            all_codes.append(sub["model"])
        fc = {"formName": form["name"], "formCode": f"{mc}_form",
              "allModelCodes": all_codes, "formComponents": [],
              "listPageView": {"queryConditions": [], "queryList": []}}
        for fld in form["fields"]:
            fc["formComponents"].append(build_component(fld, mc))
            mf = f"{mc}.{fld['code']}"
            if fld.get("l"):
                fc["listPageView"]["queryList"].append(mf)
            if fld.get("q"):
                fc["listPageView"]["queryConditions"].append(mf)
        # sub-table component
        if sub:
            cols = [build_component(sf, sub["model"]) for sf in sub["fields"]]
            fc["formComponents"].append({
                "componentType": "FORM_WIDGET_SON_TABLE",
                "label": sub["label"],
                "tableColumn": cols
            })
        form_configs.append(fc)

    return {"dataModels": data_models, "formConfigs": form_configs}


if __name__ == "__main__":
    import sys, os
    result = generate()
    out = os.path.join(os.path.dirname(__file__), "afterservice_config.json")
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    print(f"Generated {len(result['dataModels'])} models, {len(result['formConfigs'])} forms → {out}")
    # Also print summary
    for m in result["dataModels"]:
        print(f"  Model: {m['modelCode']} ({m['modelName']}) - {len(m['fields'])} fields")
    for fc in result["formConfigs"]:
        print(f"  Form:  {fc['formCode']} ({fc['formName']}) - {len(fc['formComponents'])} components")
