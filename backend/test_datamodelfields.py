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
    
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        response = await http.post(
            f"{client.base_url}/xdap-app/dataModel/query/modelWithField",
            headers=client._get_headers(APP_ID),
            json={"appId": APP_ID}
        )
        data = response.json()
        
        if data.get("code") == "ok":
            models = data.get("table", [])
            
            # 找测试模型
            test = [m for m in models if m.get('modelCode') == 'test_model_delete_me']
            if test:
                m = test[0]
                dmf = m.get('dataModelFields', [])
                print(f"📋 测试模型:")
                print(f"   dataModelFields: {len(dmf)} 个字段")
                for f in dmf:
                    print(f"   - {f.get('fieldName')} ({f.get('fieldCode')}): {f.get('fieldType')}")

if __name__ == "__main__":
    asyncio.run(main())
