import asyncio
import sys
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    # 创建一个简单的测试模型
    test_model = {
        "appId": APP_ID,
        "modelName": "测试模型_删除",
        "modelCode": "test_model_delete_me",
        "modelDescription": "测试",
        "fields": [
            {"fieldName": "字段1", "fieldCode": "field1", "fieldType": "STRING", "fieldDescription": "测试字段1"},
            {"fieldName": "字段2", "fieldCode": "field2", "fieldType": "NUM", "fieldDescription": "测试字段2"},
        ]
    }
    
    payload = {"appId": APP_ID, "datasourceId": "", "dataModels": [test_model]}
    
    print("📝 创建测试模型...")
    print(f"Payload: {payload}\n")
    
    try:
        result = await client.create_models(APP_ID, payload)
        print(f"✅ 创建成功")
        print(f"返回: {result}\n")
        
        # 查询验证
        print("🔍 查询验证...")
        models = await client.query_models(APP_ID)
        test = [m for m in models if m.get('modelCode') == 'test_model_delete_me']
        
        if test:
            m = test[0]
            print(f"✅ 找到模型: {m.get('modelName')}")
            print(f"   字段数: {len(m.get('fields', []))}")
            for f in m.get('fields', []):
                print(f"   - {f.get('fieldName')} ({f.get('fieldCode')}): {f.get('fieldType')}")
        else:
            print("❌ 模型未找到")
            
    except Exception as e:
        print(f"❌ 创建失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
