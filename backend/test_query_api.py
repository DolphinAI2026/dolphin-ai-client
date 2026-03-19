import asyncio
import sys
import json
import httpx
sys.path.insert(0, '.')

from app.apaas_client import APaaSClient

async def main():
    client = APaaSClient()
    await client.login("17621440039", "definesys2019")
    
    APP_ID = "821693297817812992"
    
    print("🔍 直接调用查询API...")
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        response = await http.post(
            f"{client.base_url}/xdap-app/dataModel/query/modelWithField",
            headers=client._get_headers(APP_ID),
            json={"appId": APP_ID}
        )
        data = response.json()
        
        if data.get("code") == "ok":
            models = data.get("table", [])
            print(f"✅ 返回 {len(models)} 个模型\n")
            
            # 找测试模型
            test = [m for m in models if m.get('modelCode') == 'test_model_delete_me']
            if test:
                m = test[0]
                print(f"📋 测试模型:")
                print(f"   modelName: {m.get('modelName')}")
                print(f"   modelCode: {m.get('modelCode')}")
                print(f"   fields: {m.get('fields', [])}")
                print(f"   modelFields: {m.get('modelFields', [])}")
                
                # 检查所有可能的字段key
                print(f"\n🔑 所有keys: {list(m.keys())}")
            else:
                print("❌ 未找到测试模型")
                
            # 检查其他模型
            print(f"\n📋 检查其他模型的字段:")
            for m in models[:3]:
                mc = m.get('modelCode', '')
                fields = m.get('fields', [])
                model_fields = m.get('modelFields', [])
                print(f"   {mc}: fields={len(fields)}, modelFields={len(model_fields)}")
        else:
            print(f"❌ 查询失败: {data}")

if __name__ == "__main__":
    asyncio.run(main())
