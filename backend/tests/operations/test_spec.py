"""@operation: đăng ký spec + model, đường dẫn REST suy từ tên + effect, luật khai báo, ui_only, registry."""

from dataclasses import replace

import pytest
from pydantic import BaseModel

from app.core.operations import registry
from app.core.operations.registry import all_specs, get_spec, namespaces, specs_for
from app.core.operations.spec import operation, ui_only


class HelloIn(BaseModel):
    who: str


class HelloOut(BaseModel):
    text: str


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Registry riêng cho từng test — khai báo thử không lọt sang test khác."""
    monkeypatch.setattr(registry, "_SPECS", {})


def declare_demo():
    @operation("specdemo.hello", title="Chào", permission="specdemo.read", agent=True, toolset="lookup")
    async def hello(ctx, inp: HelloIn) -> HelloOut:
        return HelloOut(text=f"chào {inp.who}")

    @operation("specdemo.ping", title="Ping", effect="write", invalidates=("specdemo.x",))
    async def ping(ctx) -> dict:
        return {}

    @operation("specdemo.wipe", title="Xoá hết", effect="destructive", superadmin=True)
    async def wipe(ctx, inp: None) -> dict:  # không input: `(ctx)` hoặc `(ctx, inp: None)` đều được
        return {}

    return hello


def test_spec_registered_with_models():
    hello = declare_demo()
    spec = get_spec("specdemo.hello")
    assert spec is hello.__bw_operation__
    assert spec.input_model is HelloIn and spec.output_model is HelloOut and spec.takes_input is True
    assert (spec.effect, spec.permission, spec.agent, spec.toolset) == ("read", "specdemo.read", True, "lookup")
    assert (spec.read_from, spec.status_code, spec.public, spec.superadmin) == ("ro", 200, False, False)
    ping = get_spec("specdemo.ping")
    assert ping.input_model is None and ping.takes_input is False and ping.invalidates == ("specdemo.x",)
    wipe = get_spec("specdemo.wipe")
    assert wipe.input_model is None and wipe.takes_input is True  # runner gọi wipe(ctx, None)


def test_routes_are_derived_from_name_and_effect():
    declare_demo()
    assert get_spec("specdemo.hello").route == ("GET", "/specdemo/hello")
    assert get_spec("specdemo.ping").route == ("POST", "/specdemo/ping")
    assert get_spec("specdemo.wipe").route == ("POST", "/specdemo/wipe")

    @operation("specdemo.custom", title="Đường riêng", effect="write", http=("put", "/specdemo/khac"))
    async def custom(ctx) -> dict:
        return {}

    assert get_spec("specdemo.custom").route == ("PUT", "/specdemo/khac")


def test_namespace_and_package():
    declare_demo()
    spec = get_spec("specdemo.hello")
    assert spec.namespace == "specdemo" and spec.package == "specdemo"  # khai ngoài app.* → theo tên
    moved = replace(spec, name="admin.list_users", source="app.auth.ops")
    assert (moved.namespace, moved.package, moved.route) == ("admin", "auth", ("GET", "/admin/list_users"))


def test_input_schema():
    declare_demo()
    assert get_spec("specdemo.hello").input_schema()["properties"]["who"]["type"] == "string"
    assert get_spec("specdemo.ping").input_schema() == {"type": "object", "properties": {}}


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"name": "Bad Name"}, "tên operation"),
        ({"effect": "nuke"}, "effect"),
        ({"read_from": "primary"}, "read_from"),
        ({"title": "  "}, "title"),
        ({"public": True, "permission": "x.y"}, "public"),
        ({"public": True, "superadmin": True}, "public"),
        ({"agent": True}, "toolset"),
        ({"effect": "write", "http": ("GET", "/x/y")}, "GET"),
        ({"http": ("FETCH", "/x/y")}, "method"),
        ({"http": ("POST", "x/y")}, "bắt đầu"),
    ],
)
def test_declaration_rules(kwargs, match):
    args = {"name": "specdemo.bad", "title": "x"} | kwargs
    name = args.pop("name")
    with pytest.raises(ValueError, match=match):
        operation(name, **args)


def test_duplicate_sync_and_arity_are_rejected():
    declare_demo()
    with pytest.raises(ValueError, match="trùng"):

        @operation("specdemo.hello", title="x")
        async def again(ctx): ...

    with pytest.raises(TypeError, match="async"):

        @operation("specdemo.sync_fn", title="x")
        def sync_fn(ctx): ...

    with pytest.raises(TypeError, match="ctx"):

        @operation("specdemo.three", title="x")
        async def three(ctx, a, b): ...

    assert get_spec("specdemo.sync_fn") is None and get_spec("specdemo.three") is None


def test_ui_only_marks_function_and_needs_reason():
    @ui_only("redirect OAuth")
    async def callback(request): ...

    assert callback.__bw_ui_only__ == "redirect OAuth"
    with pytest.raises(ValueError, match="lý do"):
        ui_only(" ")


def test_registry_queries():
    declare_demo()

    @operation("otherdemo.read_one", title="x")
    async def other(ctx) -> dict:
        return {}

    assert [s.name for s in all_specs()] == ["otherdemo.read_one", "specdemo.hello", "specdemo.ping", "specdemo.wipe"]
    assert {s.name for s in specs_for("specdemo")} == {"specdemo.hello", "specdemo.ping", "specdemo.wipe"}
    assert namespaces() == ["otherdemo", "specdemo"]
    assert namespaces(app_only=True) == []  # khai trong test, không thuộc app.*
