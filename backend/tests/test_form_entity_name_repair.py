"""TDD for app.operations.form_name_repair.repair_form_entity_names

复发生产 bug(2026-06-18 浏览器实证纠正根因):apaas「表单管理」列表「表单名称」列
显示的是**表单实体名**(allFormConfigList.formName),不是菜单名 menuName。
建表那一刻由 formConfigDetail 保存从 formContext.formName 同步实体名;老版本生成时该
保存偶发失败 → 实体名停在平台默认占位「我的待办」(菜单名/设计器标题不受影响,仍是真实名)。

repair_form_entity_names 对每个「实体名为占位」的模型页面表单重跑「查 formContext →
固化真实名 → 存 formConfigDetail」(等价于在设计器点保存),把实体名同步成真实名。

实证:在得帆云设计器对两个表单点保存,「表单管理」列表对应行的「表单名称」从「我的待办」
变成真实名,其它行不变 —— 证明 formConfigDetail 保存确实同步实体名(此前 menuName 改名
那套是误诊,菜单名本来就对)。
"""
import asyncio
import copy

from app.operations.form_name_repair import repair_form_entity_names


class FakeClient:
    """假 apaas client:
      - query_all_form_configs → allFormConfigList(实体名,坏的那一列)
      - query_menus → 菜单树(menuName=真实名, formId, formCode, menuType)
      - query_form_context_config → 可保存配置(_finalize 会查它)
      - save_form_config → 记录保存的 config(实体名靠这步同步), 可被设成抛异常
    """

    def __init__(self, entity_forms, menus, *, ctx_by_id=None, fail_form_ids=None):
        self._entity_forms = entity_forms
        self._menus = menus
        self._ctx_by_id = ctx_by_id or {}
        self._fail = set(fail_form_ids or [])
        self.saved = []  # list[config]

    async def query_all_form_configs(self, app_id):
        return self._entity_forms

    async def query_menus(self, app_id):
        return self._menus

    async def query_form_context_config(self, app_id, form_id):
        return copy.deepcopy(
            self._ctx_by_id.get(
                form_id,
                {"formName": "我的待办", "simpleFormConfig": {"formName": "我的待办"}},
            )
        )

    async def save_form_config(self, app_id, config):
        if str(config.get("id") or "") in self._fail:
            raise Exception("模拟平台保存表单配置失败")
        self.saved.append(copy.deepcopy(config))
        return {"ok": True}


def _entity_forms():
    # f1 实体名是占位(坏), f2 实体名正确(已对)
    return [
        {"id": "f1", "formName": "我的待办", "formCode": "finished_product"},
        {"id": "f2", "formName": "客户信息", "formCode": "customer_info"},
    ]


def _menus():
    return [
        {"id": "m1", "menuName": "成品跟产申请表", "menuType": "MODEL",
         "formId": "f1", "formCode": "finished_product"},
        {"id": "m2", "menuName": "客户信息", "menuType": "MODEL",
         "formId": "f2", "formCode": "customer_info"},
    ]


def test_only_placeholder_entity_forms_repaired():
    client = FakeClient(_entity_forms(), _menus())
    res = asyncio.run(repair_form_entity_names(client, "app1"))

    # 只有 f1(实体名=占位)被重存一次, f2(已正确)跳过
    assert len(client.saved) == 1
    saved = client.saved[0]
    assert saved["id"] == "f1"
    # 实体名靠 formConfigDetail 保存同步 → 保存的 config.formName 必须是真实名(菜单名)
    assert saved["formName"] == "成品跟产申请表"

    assert [f["code"] for f in res["fixed"]] == ["finished_product"]
    assert res["failed"] == []
    assert any(s.get("reason") == "already_correct" for s in res["skipped"])


def test_correct_name_propagated_to_simple_and_detail():
    client = FakeClient(_entity_forms(), _menus())
    asyncio.run(repair_form_entity_names(client, "app1"))
    saved = client.saved[0]
    # 真实名固化到顶层 + simpleFormConfig + detailPage(三处都同步, 跟创建后固化一致)
    assert saved["formName"] == "成品跟产申请表"
    assert saved.get("simpleFormConfig", {}).get("formName") == "成品跟产申请表"
    assert saved.get("detailPage", {}).get("formName") == "成品跟产申请表"


def test_empty_entity_name_treated_as_broken():
    forms = [{"id": "f1", "formName": "", "formCode": "finished_product"}]
    client = FakeClient(forms, _menus())
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    assert [f["code"] for f in res["fixed"]] == ["finished_product"]
    assert client.saved[0]["formName"] == "成品跟产申请表"


def test_save_exception_collected_not_raised():
    client = FakeClient(_entity_forms(), _menus(), fail_form_ids={"f1"})
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    assert res["fixed"] == []
    assert len(res["failed"]) == 1
    assert res["failed"][0]["code"] == "finished_product"
    assert "error" in res["failed"][0]


def test_dry_run_does_not_save():
    client = FakeClient(_entity_forms(), _menus())
    res = asyncio.run(repair_form_entity_names(client, "app1", dry_run=True))
    assert client.saved == []
    planned = [f for f in res["fixed"] if f.get("dry_run")]
    assert [p["code"] for p in planned] == ["finished_product"]
    assert planned[0]["to"] == "成品跟产申请表"


def test_spec_name_overrides_menu_name():
    # 提供 name_by_code(来自 spec)时优先用它, 而非菜单名
    client = FakeClient(_entity_forms(), _menus())
    res = asyncio.run(
        repair_form_entity_names(
            client, "app1", name_by_code={"finished_product": "成品跟产申请表V2"}
        )
    )
    assert client.saved[0]["formName"] == "成品跟产申请表V2"
    assert res["fixed"][0]["to"] == "成品跟产申请表V2"


def test_broken_but_no_real_name_skipped():
    # 实体名坏, 但菜单名也是占位且无 spec → 拿不到真实名 → 跳过(不乱写)
    forms = [{"id": "f1", "formName": "我的待办", "formCode": "x"}]
    menus = [{"id": "m1", "menuName": "我的待办", "menuType": "MODEL",
              "formId": "f1", "formCode": "x"}]
    client = FakeClient(forms, menus)
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    assert client.saved == []
    assert any(s.get("reason") == "no_real_name" for s in res["skipped"])


def test_non_model_menus_ignored():
    forms = [{"id": "f1", "formName": "我的待办", "formCode": "finished_product"}]
    menus = [
        {"id": "p1", "menuName": "审批流程", "menuType": "PROCESS",
         "formId": "f1", "formCode": "finished_product"},
    ]
    client = FakeClient(forms, menus)
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    # 非 MODEL 菜单不处理
    assert client.saved == []
    assert res["fixed"] == []


def test_nested_children_walked():
    forms = [{"id": "f1", "formName": "我的待办", "formCode": "finished_product"}]
    menus = [{
        "id": "g1", "menuName": "分组", "menuType": "GROUP",
        "children": [
            {"id": "m1", "menuName": "成品跟产申请表", "menuType": "MODEL",
             "formId": "f1", "formCode": "finished_product"}
        ],
    }]
    client = FakeClient(forms, menus)
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    assert [f["code"] for f in res["fixed"]] == ["finished_product"]
    assert client.saved[0]["formName"] == "成品跟产申请表"


def test_empty_entity_list_falls_back_to_repair_all():
    # query_all_form_configs 返空(响应结构没命中)→ 降级重存所有 MODEL 表单,而非全跳过
    class EmptyEntityClient(FakeClient):
        async def query_all_form_configs(self, app_id):
            return []

    client = EmptyEntityClient(_entity_forms(), _menus())
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    assert {s["id"] for s in client.saved} == {"f1", "f2"}
    assert {f["code"] for f in res["fixed"]} == {"finished_product", "customer_info"}


def test_entity_list_unavailable_falls_back_to_repair_all():
    # query_all_form_configs 抛/返空时降级:无法判定坏不坏 → 对所有 MODEL 表单重存(幂等)
    class NoEntityClient(FakeClient):
        async def query_all_form_configs(self, app_id):
            raise Exception("接口不可用")

    client = NoEntityClient(_entity_forms(), _menus())
    res = asyncio.run(repair_form_entity_names(client, "app1"))
    # 两个 MODEL 表单都重存(降级)
    assert {s["id"] for s in client.saved} == {"f1", "f2"}
    assert {f["code"] for f in res["fixed"]} == {"finished_product", "customer_info"}
