import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    FORM_ID = "69b8bf348057aede4f89aa16"  # 劳工优化计划服务收费
    
    print(f"🔍 查询表单...")
    fc = await client.query_form_config(APP_ID, FORM_ID)
    
    print(f"📝 表单: {fc.get('formName')}")
    print(f"   原 allModelCodes: {fc.get('allModelCodes')}")
    
    # 找出子表模型
    comps = fc.get('detailPage', {}).get('formComponents', [])
    sub_models = []
    for c in comps:
        if c.get('componentType') == 'FORM_WIDGET_SON_TABLE':
            sub_cols = c.get('tableColumn', [])
            if sub_cols:
                first_mf = sub_cols[0].get('modelField', '')
                if '.' in first_mf:
                    sub_model = first_mf.split('.')[0]
                    sub_models.append(sub_model)
                    print(f"   子表模型: {sub_model}")
    
    # 尝试添加子表模型到 allModelCodes
    if sub_models:
        original_codes = fc.get('allModelCodes', [])
        new_codes = list(set(original_codes + sub_models))
        fc['allModelCodes'] = new_codes
        
        print(f"\n💾 尝试保存，新 allModelCodes: {new_codes}")
        try:
            await client.save_form_config(APP_ID, fc)
            print("✅ 保存成功")
            
            # 重新查询验证
            print("\n🔍 重新查询验证...")
            fc2 = await client.query_form_config(APP_ID, FORM_ID)
            print(f"   查询后 allModelCodes: {fc2.get('allModelCodes')}")
            
            if set(fc2.get('allModelCodes', [])) == set(new_codes):
                print("✅ 子表模型保留在 allModelCodes 中")
            else:
                print("⚠️ 平台自动移除了子表模型")
                
        except Exception as e:
            print(f"❌ 保存失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
