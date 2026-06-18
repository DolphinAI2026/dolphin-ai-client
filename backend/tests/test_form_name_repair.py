"""TDD for app.operations.form_name_repair.repair_form_menu_names

复发生产 bug:0-1 生成的应用在 apaas「表单管理」里所有表单「表单名称」都变成
默认占位「我的待办」(=菜单名 menuName 的平台默认值),但表单编码各不相同且正确。

根因:step_executor 建表后用真实 form_name 调 create_menu 改名覆盖占位,失败被
try/except 静默吞掉、不重试、不回读 → 一旦覆盖没生效整批留「我的待办」。

repair_form_menu_names 是共享 sweep:按 formCode 把 spec 真实名回写到菜单名。
"""
import asyncio

import pytest

from app.operations.form_name_repair import repair_form_menu_names


class FakeClient:
    """假 apaas client:query_menus 返预置菜单树;create_menu 记录调用,可被设成抛异常。"""

    def __init__(self, menus, fail_codes=None):
        self._menus = menus
        # 按 form_id 触发抛异常(create_menu 入参拿的是 form_id)
        self._fail_form_ids = set(fail_codes or [])
        self.create_menu_calls = []

    async def query_menus(self, app_id):
        return self._menus

    async def create_menu(self, app_id, menu_name, form_id, menu_order=0, menu_id="", **kw):
        self.create_menu_calls.append(
            {"app_id": app_id, "menu_name": menu_name, "form_id": form_id,
             "menu_id": menu_id, "menu_order": menu_order}
        )
        if form_id in self._fail_form_ids:
            raise Exception("模拟平台写菜单失败")
        return {"id": menu_id or "new"}


def _menus():
    # 一个占位待修(menuName=我的待办) + 一个已正确的
    return [
        {
            "id": "m1",
            "menuName": "我的待办",
            "menuType": "MODEL",
            "formId": "f1",
            "formCode": "efficacy_filing",
        },
        {
            "id": "m2",
            "menuName": "客户信息",
            "menuType": "MODEL",
            "formId": "f2",
            "formCode": "customer_info",
        },
    ]


def _spec_forms():
    return [
        {"formCode": "efficacy_filing", "name": "药效备案"},
        {"formCode": "customer_info", "name": "客户信息"},
    ]


def test_placeholder_menu_renamed_to_spec_name():
    client = FakeClient(_menus())
    res = asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))

    # 占位菜单被改名:create_menu 用对的 real name + form_id + menu_id 调用一次
    assert len(client.create_menu_calls) == 1
    call = client.create_menu_calls[0]
    assert call["menu_name"] == "药效备案"
    assert call["form_id"] == "f1"
    assert call["menu_id"] == "m1"
    assert call["app_id"] == "app1"

    assert res["fixed"] == [
        {"code": "efficacy_filing", "from": "我的待办", "to": "药效备案"}
    ]
    assert res["failed"] == []


def test_already_correct_menu_is_skipped():
    client = FakeClient(_menus())
    res = asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))

    # 已正确(menuName == spec name)的菜单跳过,不触发 create_menu
    assert "customer_info" in res["skipped"]
    assert all(c["form_id"] != "f2" for c in client.create_menu_calls)


def test_create_menu_exception_collected_not_raised():
    # 让待修菜单 f1 的 create_menu 抛异常 → failed 收集且函数不抛
    client = FakeClient(_menus(), fail_codes={"f1"})
    res = asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))

    assert res["fixed"] == []
    assert len(res["failed"]) == 1
    assert res["failed"][0]["code"] == "efficacy_filing"
    assert "error" in res["failed"][0]


def test_matched_by_form_code_not_name():
    # spec 用 formCode 匹配,name 取 spec 真值(证明走的是 formCode 关联,不是位置/名字)
    forms = [{"formCode": "efficacy_filing", "name": "药效备案_v2"}]
    client = FakeClient(_menus())
    res = asyncio.run(repair_form_menu_names(client, "app1", forms))

    # f1 按 formCode=efficacy_filing 命中 → 改名为 spec 的 name
    assert any(c["menu_name"] == "药效备案_v2" and c["form_id"] == "f1"
               for c in client.create_menu_calls)
    # customer_info 不在 spec name_by_code 里 → real 缺失 → skipped(不改名)
    assert "customer_info" in res["skipped"]
    assert all(c["form_id"] != "f2" for c in client.create_menu_calls)


def test_nested_children_are_walked():
    nested = [
        {
            "id": "g1",
            "menuName": "分组",
            "menuType": "GROUP",
            "children": [
                {
                    "id": "m1",
                    "menuName": "我的待办",
                    "menuType": "MODEL",
                    "formId": "f1",
                    "formCode": "efficacy_filing",
                }
            ],
        }
    ]
    client = FakeClient(nested)
    res = asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))
    assert {f["code"] for f in res["fixed"]} == {"efficacy_filing"}


def test_nested_subMenus_are_walked():
    # 平台另一种子节点键 subMenus(节点上只会有 children/subMenus 之一被填)
    nested = [
        {
            "id": "g1",
            "menuName": "分组",
            "menuType": "GROUP",
            "subMenus": [
                {
                    "id": "m2",
                    "menuName": "我的待办",
                    "menuType": "MODEL",
                    "formId": "f2",
                    "formCode": "customer_info",
                }
            ],
        }
    ]
    forms = [{"formCode": "customer_info", "name": "客户信息表"}]
    client = FakeClient(nested)
    res = asyncio.run(repair_form_menu_names(client, "app1", forms))
    assert {f["code"] for f in res["fixed"]} == {"customer_info"}


def test_custom_nonplaceholder_name_not_overwritten():
    # 用户在 apaas 把菜单名手改成非占位的合法名(≠spec 名)→ 不能被强行抹回 spec 名
    menus = [
        {
            "id": "m1",
            "menuName": "客户档案",  # 人为自定义,非占位、非空
            "menuType": "MODEL",
            "formId": "f1",
            "formCode": "customer_info",
        }
    ]
    forms = [{"formCode": "customer_info", "name": "客户信息"}]
    client = FakeClient(menus)
    res = asyncio.run(repair_form_menu_names(client, "app1", forms))

    assert client.create_menu_calls == []          # 不改名
    assert "customer_info" in res["skipped"]
    assert res["fixed"] == []


def test_empty_menu_name_renamed():
    # 空菜单名也属于「需修」(平台没给名)→ 回写 spec 名
    menus = [
        {"id": "m1", "menuName": "", "menuType": "MODEL",
         "formId": "f1", "formCode": "efficacy_filing"}
    ]
    client = FakeClient(menus)
    res = asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))

    assert {f["code"] for f in res["fixed"]} == {"efficacy_filing"}
    assert client.create_menu_calls[0]["menu_name"] == "药效备案"


def test_menu_order_preserved_on_rename():
    # 改名不应把菜单排序重置成 0:读回原 menuOrder 透传给 create_menu
    menus = [
        {"id": "m1", "menuName": "我的待办", "menuType": "MODEL",
         "formId": "f1", "formCode": "efficacy_filing", "menuOrder": 7}
    ]
    client = FakeClient(menus)
    asyncio.run(repair_form_menu_names(client, "app1", _spec_forms()))

    assert client.create_menu_calls[0]["menu_order"] == 7


def test_snake_case_casing_defensively_supported():
    # 防御性:raw 偶尔归一成 snake_case 也要能读
    menus = [
        {
            "id": "m1",
            "menu_name": "我的待办",
            "menu_type": "MODEL",
            "formId": "f1",
            "form_code": "efficacy_filing",
        }
    ]
    forms = [{"code": "efficacy_filing", "formName": "药效备案"}]
    client = FakeClient(menus)
    res = asyncio.run(repair_form_menu_names(client, "app1", forms))
    assert len(res["fixed"]) == 1
    assert client.create_menu_calls[0]["menu_name"] == "药效备案"
