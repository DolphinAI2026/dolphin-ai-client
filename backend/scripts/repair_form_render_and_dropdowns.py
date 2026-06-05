"""可复用就地修复(不重新生成): 给定 app, 修它所有表单 ——
  ① 删 detailPage.webFormSettings / mobileFormSettings (设计器画布渲染崩的根因)
  ② 下拉绑字典: 按"字典名 == 组件 label"绑 source=DICTIONARY_TYPE + 选项(下拉空的根因)
用法: python _repair_forms.py <apaas_app_id> <env_id>
"""
import asyncio, sys, httpx, logging
logging.disable(logging.CRITICAL)

APP = sys.argv[1] if len(sys.argv) > 1 else "850744994011545600"
ENV = int(sys.argv[2]) if len(sys.argv) > 2 else 59


async def main():
    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.database import AsyncSessionLocal
    from app.generator_v2 import _bind_dict_on_component

    async def C(fn):
        async with AsyncSessionLocal() as db:
            return await call_apaas_with_relogin(ENV, db, fn)

    async def ctx_status(fid):
        async def fn(c):
            url = f"{c.base_url}/xdap-app/v2/form/query/formContext?formId={fid}"
            async with httpx.AsyncClient(verify=False, timeout=60) as cli:
                return (await cli.get(url, headers=c._get_headers(APP))).status_code
        return await C(fn)

    # 平台字典 → 名/码/id/选项
    dicts = await C(lambda c: c.query_dicts(APP))
    dict_id_map = {d.get("dictionaryCode"): d.get("id") for d in dicts if d.get("dictionaryCode") and d.get("id")}
    label_dict = {str(d.get("dictionaryName") or "").strip(): d.get("dictionaryCode")
                  for d in dicts if d.get("dictionaryName") and d.get("dictionaryCode")}
    dict_options_map = {}
    for code, did in dict_id_map.items():
        dict_options_map[code] = await C(lambda c, did=did: c.query_dict_options(APP, did))

    # 表单
    ms = await C(lambda c: c.query_menus(APP))
    flat = []
    def walk(x):
        for it in x or []:
            flat.append(it); walk(it.get("children") or it.get("subMenus") or [])
    walk(ms if isinstance(ms, list) else ms.get("data") or [])
    forms = [(m.get("menuName") or m.get("name"), m.get("formId")) for m in flat if m.get("formId")]
    print(f"app={APP} 表单数={len(forms)}\n")

    for name, fid in forms:
        before = await ctx_status(fid)
        try:
            cfg = await C(lambda c, fid=fid: c.query_form_config(APP, fid))
        except Exception as e:
            print(f"  {str(name)[:14]:<16} 读取失败(建议重新生成此表单): {str(e)[:50]}")
            continue
        dp = cfg.get("detailPage") or {}
        removed = [k for k in ("webFormSettings", "mobileFormSettings") if k in dp]
        for k in removed:
            dp.pop(k, None)
        bound = 0
        for comp in dp.get("formComponents", []) or []:
            if _bind_dict_on_component(comp, label_dict, dict_id_map, dict_options_map):
                bound += 1
            if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                for col in comp.get("tableColumn", []) or []:
                    if _bind_dict_on_component(col, label_dict, dict_id_map, dict_options_map):
                        bound += 1
        if not removed and bound == 0:
            print(f"  {str(name)[:14]:<16} 无需修复(formContext={before})")
            continue
        try:
            await C(lambda c, cfg=cfg: c.save_form_config(APP, cfg))
        except Exception as e:
            print(f"  {str(name)[:14]:<16} 存盘失败: {str(e)[:60]}")
            continue
        after = await ctx_status(fid)
        print(f"  {str(name)[:14]:<16} 删webForm={removed} 绑下拉={bound}个 | formContext {before}->{after}")


if __name__ == "__main__":
    asyncio.run(main())
