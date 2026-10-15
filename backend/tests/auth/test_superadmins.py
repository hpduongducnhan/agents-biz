"""SUPERADMIN_EMAILS là nguồn sự thật: migrate bật / gỡ cờ theo env, không phân biệt hoa thường / khoảng
trắng; env trống thì cảnh báo kèm DEFAULTS_APPLIED (R11)."""

import pytest
from sqlmodel import select

from app.auth.models import User
from app.auth.superadmins import apply_superadmin
from app.core.migrate import run_post_migrate
from tests.auth.factories import make_user


def test_apply_superadmin_follows_env(test_settings):
    root = User(email="root@test.local", timezone="UTC", is_superadmin=False)
    assert apply_superadmin(root, test_settings) is True and root.is_superadmin
    assert apply_superadmin(root, test_settings) is False
    gone = User(email="gone@x.io", timezone="UTC", is_superadmin=True)
    assert apply_superadmin(gone, test_settings) is True and not gone.is_superadmin


@pytest.mark.integration
async def test_migrate_promotes_and_demotes_by_env(pg, test_settings):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        await make_user(s, "root@test.local")
        await make_user(s, "Old.Boss@x.io", is_superadmin=True)
    result = await run_post_migrate(test_settings)
    assert result["auth.superadmins"] == {"promoted": ["root@test.local"], "demoted": ["old.boss@x.io"]}
    messy = test_settings.model_copy(update={"SUPERADMIN_EMAILS": " ROOT@test.local , old.boss@X.io ,"})
    result = await run_post_migrate(messy)
    assert result["auth.superadmins"] == {"promoted": ["old.boss@x.io"], "demoted": []}
    async with pg.ro() as s:
        flags = {u.email: u.is_superadmin for u in (await s.exec(select(User))).all()}
    assert flags == {"root@test.local": True, "old.boss@x.io": True}


@pytest.mark.integration
async def test_empty_env_demotes_everyone_and_warns(pg, test_settings, bw_log):
    await run_post_migrate(test_settings)
    async with pg.rw() as s:
        await make_user(s, "root@test.local", is_superadmin=True)
    result = await run_post_migrate(test_settings.model_copy(update={"SUPERADMIN_EMAILS": ""}))
    assert result["auth.superadmins"] == {"promoted": [], "demoted": ["root@test.local"]}
    warn = [line for line in bw_log() if line.get("loc") == "auth0403"]
    assert warn and "DEFAULTS_APPLIED=['SUPERADMIN_EMAILS']" in warn[0]["msg"]
