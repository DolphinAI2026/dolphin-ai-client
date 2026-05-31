import argparse
import asyncio
import json
import sys

sys.path.insert(0, ".")

from app.apaas_client import APaaSClient


async def main():
    parser = argparse.ArgumentParser(description="补齐应用菜单的数据源绑定字段")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--app-id", required=True)
    args = parser.parse_args()

    client = APaaSClient(base_url=args.base_url, tenant_id=args.tenant_id)
    await client.login(args.username, args.password)

    all_menus = await client.query_all_app_menus(args.app_id)
    fixed = []
    skipped = []

    for menu in all_menus:
        if menu.get("menuType") != "MODEL" or not menu.get("formId"):
            continue

        menu_id = str(menu.get("id") or "").strip()
        menu_name = str(menu.get("menuName") or "").strip()
        if not menu_id or not menu_name:
            continue

        current_type = str(menu.get("menuModelType") or "").strip()
        current_ds = str(menu.get("datasourceId") or "").strip()
        if current_type and current_ds:
            skipped.append({"menuId": menu_id, "menuName": menu_name, "reason": "already_bound"})
            continue

        datasource_id, datasource_code = await client.resolve_default_menu_datasource(
            args.app_id,
            form_id=str(menu.get("formId") or "").strip(),
        )
        if not datasource_id:
            skipped.append({"menuId": menu_id, "menuName": menu_name, "reason": "datasource_not_found"})
            continue

        payload = {
            "id": menu_id,
            "appId": args.app_id,
            "menuName": menu_name,
            "menuType": "MODEL",
            "menuOrder": menu.get("menuOrder", 0),
            "formId": menu.get("formId"),
            "menuDisplay": menu.get("menuDisplay", "ALL"),
            "menuIcon": menu.get("menuIcon") or "userInfo",
            "menuModelType": "DATABASE",
            "datasourceId": datasource_id,
            "datasourceCode": datasource_code,
            "cusIconStatus": menu.get("cusIconStatus") or "DISABLE",
            "newWindowStatus": menu.get("newWindowStatus") or "DISABLE",
            "cusModelPageStatus": menu.get("cusModelPageStatus") or "DISABLE",
            "menuNameI18nAssociated": bool(menu.get("menuNameI18nAssociated", False)),
            "iconColor": menu.get("iconColor") or "#027AFF",
        }

        await client._post_resource("/menu/save/menu", payload, app_id=args.app_id)
        fixed.append({"menuId": menu_id, "menuName": menu_name})

    refreshed = await client.query_all_app_menus(args.app_id)
    summary = {
        "appId": args.app_id,
        "fixed": fixed,
        "skipped": skipped,
        "refreshed": [
            {
                "menuId": str(menu.get("id") or ""),
                "menuName": str(menu.get("menuName") or ""),
                "menuModelType": menu.get("menuModelType"),
                "datasourceId": menu.get("datasourceId"),
                "datasourceCode": menu.get("datasourceCode"),
            }
            for menu in refreshed
            if menu.get("menuType") == "MODEL" and menu.get("formId")
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
