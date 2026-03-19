import asyncio
import sys
import json
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    FORM_ID = "69b8bf478057aede4f89ab15"
    
    print(f"🔍 查询表单配置...")
    fc = await client.query_form_config(APP_ID, FORM_ID)
    
    print(f"📝 表单: {fc.get('formName')}")
    print(f"🗄️ allModelCodes: {fc.get('allModelCodes')}\n")
    
    # 查询实际的模型
    print("🔍 查询平台模型...")
    models = await client.query_models(APP_ID)
    model_by_code = {m.get('modelCode'): m for m in models}
    
    # 检查 allModelCodes 中的模型是否存在
    all_codes = fc.get('allModelCodes', [])
    for mc in all_codes:
        if mc in model_by_code:
            m = model_by_code[mc]
            print(f"✅ {mc} 存在，字段数: {len(m.get('fields', []))}")
        else:
            print(f"❌ {mc} 不存在！")
    
    # 检查组件的 modelField
    print("\n📋 检查组件 modelField:")
    components = fc.get('detailPage', {}).get('formComponents', [])
    
    field_issues = []
    for i, comp in enumerate(components):
        ct = comp.get('componentType', '')
        label = comp.get('label', '')
        mf = comp.get('modelField', '')
        
        if ct == 'FORM_WIDGET_SON_TABLE':
            sub_cols = comp.get('tableColumn', [])
            print(f"\n  {i+1}. [子表] {label}")
            for j, col in enumerate(sub_cols):
                col_mf = col.get('modelField', '')
                if '.' in col_mf:
                    col_mc, col_fc = col_mf.split('.', 1)
                    # 检查模型是否存在
                    if col_mc not in model_by_code:
                        field_issues.append(f"子表列 '{col.get('label')}': 模型 {col_mc} 不存在")
                    else:
                        # 检查字段是否存在
                        m = model_by_code[col_mc]
                        field_codes = [f.get('fieldCode') for f in m.get('fields', [])]
                        if col_fc not in field_codes:
                            field_issues.append(f"子表列 '{col.get('label')}': 字段 {col_fc} 不在模型 {col_mc} 中")
        else:
            if '.' in mf:
                mc, fc = mf.split('.', 1)
                # 检查模型是否存在
                if mc not in model_by_code:
                    field_issues.append(f"组件 '{label}': 模型 {mc} 不存在")
                else:
                    # 检查字段是否存在
                    m = model_by_code[mc]
                    field_codes = [f.get('fieldCode') for f in m.get('fields', [])]
                    if fc not in field_codes:
                        field_issues.append(f"组件 '{label}': 字段 {fc} 不在模型 {mc} 中")
    
    if field_issues:
        print("\n❌ 发现字段配置问题:")
        for issue in field_issues:
            print(f"  - {issue}")
    else:
        print("\n✅ 所有字段配置正确")

if __name__ == "__main__":
    asyncio.run(main())
