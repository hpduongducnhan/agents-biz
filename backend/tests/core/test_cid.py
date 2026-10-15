import asyncio
import contextvars
import re

from app.core.cid import get_cid, is_valid_cid, new_cid, set_cid

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_new_cid_is_32_hex():
    assert HEX32.match(new_cid())


def test_set_cid_keeps_valid_value():
    def run():
        assert set_cid("abc-123_X") == "abc-123_X"
        assert get_cid() == "abc-123_X"

    contextvars.Context().run(run)


def test_set_cid_rejects_bad_values():
    for bad in (None, "", "x" * 65, "có dấu", "a b", "a;b", "<script>"):
        got = contextvars.Context().run(set_cid, bad)
        assert HEX32.match(got), bad
        assert not is_valid_cid(bad)


def test_fresh_context_has_no_cid():
    assert contextvars.Context().run(get_cid) is None


async def test_child_task_does_not_leak_cid_to_parent():
    set_cid("parent")

    async def child():
        set_cid("child")

    await asyncio.create_task(child())
    assert get_cid() == "parent"
