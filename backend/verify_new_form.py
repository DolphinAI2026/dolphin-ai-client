import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    NEW_FORM_ID = "69b8c73b8057aede4f89abb4"
    
    print("🔍 验证新表单...")
    fc = await client.query_form_config(APP_ID, NEW_FORM_ID)
    
    print(f"📝 表单: {fc.get('formName')}")
    print(f"🗄️ allModelCodes: {fc.get('allModelCodes')}")
    
    components = fc.get('detailPage', {}).get('formComponents', [])
    print(f"✅ 组件数: {len(components)}")
    
    # 检查字段配置
    models = await client.query_models(APP_ID)
    model_by_code = {m.get('modelCode'): m for m in models}
    
    field_issues = []
    for comp in components:
        ct = comp.get('componentType', '')
        label = comp.get('label', '')
        
        if ct == 'FORM_WIDGET_SON_TABLE':
            sub_cols = comp.get('tableColumn', [])
            for col in sub_cols:
                col_mf = col.get('modelField', '')
                if '.' in col_mf:
                    mc, fc = col_mf.split('.', 1)
                    if mc not in model_by_code:
                        field_issues.append(f"子表列 '{col.get('label')}': 模型 {mc} 不存在")
                    else:
                        m = model_by_code[mc]
                        field_codes = [f.get('fieldCode') for f in m.get('fields', [])]
                        if fc not in field_codes:
                            field_issues.append(f"子表列 '{col.get('label')}': 字段 {fc} 不在模型中")
        else:
            mf = comp.get('modelField', '')
            if '.' in mf:
                mc, fc = mf.split('.', 1)
                if mc not in model_by_code:
                    field_issues.append(f"组件 '{label}': 模型 {mc} 不存在")
                else:
                    m = model_by_code[mc]
                    field_codes = [f.get('fieldCode') for f in m.get('fields', [])]
                    if fc not in field_codes:
                        field_issues.append(f"组件 '{label}': 字段 {fc} 不在模型中")
    
    if field_issues:
        print("\n❌ 发现问题:")
        for issue in field_issues[:5]:
            print(f"   - {issue}")
    else:
        print("\n✅ 所有字段配置正确")
    
    # 测试保存
    print("\n💾 测试保存...")
    try:
        await client.save_form_config(APP_ID, fc)
        print("✅ 保存成功")
    except Exception as e:
        print(f"❌ 保存失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
