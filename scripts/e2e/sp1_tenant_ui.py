"""E2E Playwright cho SP1 (tenant + mail) trên stack thử.

Chạy:
    export PLAYWRIGHT_BROWSERS_PATH=<thư mục trình duyệt>
    <python có playwright> scripts/e2e/sp1_tenant_ui.py [--only T1,T2] [--base http://127.0.0.1:8201]

Luồng (mỗi luồng chạy 1440x900 rồi 375x812, dữ liệu ghi dùng email / tên riêng từng kích thước):
  T1 đăng ký theo signup_mode (default_tenant / new_tenant / invite_only)
  T2 xác thực email (required -> thư -> link; soft -> banner + gửi lại)
  T3 mời bằng link dùng chung (viewer), đếm lượt dùng, thu hồi
  T4 tách dữ liệu giữa tenant (UI + API get_user chéo tenant -> 404)
  T5 quên mật khẩu -> thư -> đặt lại; mật khẩu cũ bị từ chối; link dùng lại bị từ chối
  T6 khoá tenant (realtime đăng xuất <= 10s) rồi mở khoá
  T7 ảnh giao diện + kiểm tra English không còn chuỗi Việt / khoá i18n thô

DoD mỗi luồng x kích thước: console error = 0 (lỗi "Failed to load resource" do 4xx được
theo dõi riêng ở mục http), không HTTP >= 500, 4xx chỉ ở chỗ khai báo bằng allow(), không cuộn
ngang, không khoá i18n thô, assertion đúng.
Ảnh: .e2e/sp1/<luồng>-<bước>-<rộng>.png ; kết quả: .e2e/sp1/result.json.
Tự dọn: signup_mode=default_tenant, email_verification=soft, mở khoá tenant, locale vi.
"""

import argparse
import asyncio
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".e2e" / "sp1"
PW = os.environ.get("SEED_PASSWORD") or "password123"  # mật khẩu tài khoản seed của stack thử
RUN = f"{int(time.time()) % 1000000:x}"
BASE = "http://127.0.0.1:8201"
API = BASE + "/bizwithagents/api"
SIZES = [(1440, 900), (375, 812)]
RAW_KEY = re.compile(
    r"^(auth|org|tenants|invite|nav|verify|sa|common|action|err|mail|profile|admin|lang|theme|menu|settings|notif)"
    r"\.[A-Za-z][A-Za-z0-9_.]*$"
)
VI_CHARS = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def xff() -> str:
    return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def api(method: str, path: str, token: str | None = None, body: dict | None = None, query: dict | None = None):
    """Gọi API, trả (http_status, envelope)."""
    url = f"{API}/{path}"
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    headers = {"X-Forwarded-For": xff(), "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200].decode(errors="replace")}


def token_of(email: str) -> str:
    st, env = api("POST", "auth/login", body={"email": email, "password": PW})
    assert st == 200, f"API login {email}: {st} {env}"
    return env["data"]["tokens"]["access_token"]


def set_settings(**kw):
    st, env = api("POST", "system/update_settings", token_of("superadmin@test.local"), kw)
    assert st == 200, f"update_settings {kw}: {st} {env}"


def outbox() -> list[dict]:
    st, env = api("GET", "mail/outbox", token_of("superadmin@test.local"), query={"limit": 50})
    assert st == 200, f"outbox {st} {env}"
    return env["data"]["items"]


def mail_link(to: str, pattern: str, timeout: float = 15) -> str:
    """Link (theo regex) trong thư MỚI NHẤT gửi tới `to`."""
    end = time.time() + timeout
    while time.time() < end:
        hits = [
            m for m in outbox() if to.lower() in str(m.get("to")).lower() and re.search(pattern, m.get("text") or "")
        ]
        if hits:
            hits.sort(key=lambda m: str(m.get("sent_at")))
            return re.search(r"https?://\S*" + pattern + r"\S*", hits[-1]["text"]).group(0).rstrip(".,)")
        time.sleep(1)
    raise AssertionError(f"không thấy thư tới {to} chứa {pattern}")


class Flow:
    def __init__(self, browser, name: str, width: int, height: int):
        self.browser, self.name, self.width, self.height = browser, name, width, height
        self.ctxs, self.pages = [], []
        self.console: list[str] = []
        self.http: list[tuple[int, str]] = []
        self.allowed: list[tuple[str, tuple, str]] = []
        self.problems: list[str] = []
        self.notes: list[str] = []
        self.shots: list[str] = []
        self.last_page = None
        self.n = 0

    def allow(self, sub: str, statuses: tuple, why: str):
        self.allowed.append((sub, statuses, why))

    async def ctx(self):
        c = await self.browser.new_context(viewport={"width": self.width, "height": self.height}, locale="vi-VN")
        ip = xff()

        async def add_ip(route):
            await route.continue_(headers={**route.request.headers, "x-forwarded-for": ip})

        await c.route(BASE + "/**", add_ip)  # chỉ gắn cho request tới app, không gắn cho font Google (CORS)
        c.on("console", lambda m: self.console.append(m.text) if m.type == "error" else None)
        c.on(
            "response",
            lambda r: (
                self.http.append((r.status, r.request.method + " " + r.url.replace(BASE, "")))
                if r.status >= 400
                else None
            ),
        )
        self.ctxs.append(c)
        return c

    async def page(self):
        p = await (await self.ctx()).new_page()
        p.set_default_timeout(15000)
        self.pages.append(p)
        self.last_page = p
        return p

    async def shot(self, page, step: str, check: bool = True):
        self.last_page = page
        path = OUT / f"{self.name}-{step}-{self.width}.png"
        await page.screenshot(path=str(path), full_page=True)
        self.shots.append(str(path.relative_to(ROOT)))
        if check:
            await self.check_page(page, step)

    async def check_page(self, page, step: str):
        sw, iw = await page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        if sw > iw:
            self.problems.append(f"[{step}] cuộn ngang: scrollWidth={sw} > innerWidth={iw}")
        text = await page.evaluate("document.body.innerText")
        raw = {w for w in re.split(r"\s+", text) if RAW_KEY.match(w) and not w.endswith(".local")}
        if raw:
            self.problems.append(f"[{step}] khoá i18n thô: {sorted(raw)[:6]}")

    def finish(self) -> dict:
        for st, what in self.http:
            if st >= 500:
                self.problems.append(f"HTTP {st} {what}")
                continue
            ok = [w for sub, sts, w in self.allowed if sub in what and st in sts]
            if ok:
                self.notes.append(f"4xx chủ ý: {st} {what} ({ok[0]})")
            else:
                self.problems.append(f"HTTP {st} ngoài dự kiến {what}")
        errs = [c for c in self.console if not c.startswith("Failed to load resource")]
        skipped = len(self.console) - len(errs)
        if skipped:
            self.notes.append(f"{skipped} console 'Failed to load resource' (ứng với 4xx đã liệt kê ở HTTP)")
        for c in errs:
            self.problems.append(f"console error: {c[:300]}")
        return {
            "flow": self.name,
            "width": self.width,
            "pass": not self.problems,
            "problems": self.problems,
            "notes": self.notes,
            "shots": self.shots,
        }

    async def close(self):
        for c in self.ctxs:
            await c.close()


# ---------- helper UI ----------
async def ui_login(page, email: str, pw: str = PW, expect_ok: bool = True):
    await page.goto(BASE + "/login")
    await page.get_by_test_id("login-email").fill(email)
    await page.get_by_test_id("login-password").fill(pw)
    await page.get_by_test_id("login-submit").click()
    if expect_ok:
        await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        await page.wait_for_load_state("networkidle")


async def ui_register(page, name: str, email: str, pw: str = PW, tenant: str | None = None):
    await page.get_by_test_id("register-name").fill(name)
    await page.get_by_test_id("register-email").fill(email)
    await page.get_by_test_id("register-password").fill(pw)
    if tenant is not None:
        await page.get_by_test_id("register-tenant").fill(tenant)
    await page.get_by_test_id("register-submit").click()


async def in_app(page):
    await page.wait_for_url(lambda u: not re.search(r"/(register|login|invite)", u), timeout=15000)
    await page.wait_for_load_state("networkidle")


async def open_user_menu(page):
    await page.get_by_test_id("user-menu").click()
    await page.get_by_test_id("user-menu-tenant").wait_for()


async def logout(page):
    await page.get_by_test_id("user-menu").click()
    await page.get_by_test_id("logout").click()
    await page.wait_for_url(lambda u: "/login" in u)


async def sa_page(flow: Flow):
    p = await flow.page()
    await ui_login(p, "superadmin@test.local")
    return p


async def see_mail(flow: Flow, sa, email: str, step: str):
    await sa.goto(BASE + "/sa/mail")
    await sa.get_by_test_id("mail-outbox").wait_for()
    await sa.get_by_text(email).first.wait_for()
    await flow.shot(sa, step)


def uid(w: int, tag: str) -> str:
    return f"e2e-{RUN}-{tag}{w}"


# ---------- T1 ----------
async def t1(f: Flow):
    w = f.width
    f.allow("auth/register", (400, 403, 422), "đăng ký bị đóng (invite_only)")
    default_name = api("GET", "tenant/get", token_of("superadmin@test.local"))[1]["data"]["name"]
    sa = await sa_page(f)
    await sa.goto(BASE + "/sa/settings")

    async def mode(v: str):
        await sa.goto(BASE + "/sa/settings")
        await sa.get_by_test_id("settings-signup-mode").wait_for()
        await sa.wait_for_timeout(500)
        if await sa.get_by_test_id("settings-signup-mode").input_value() != v:
            await sa.get_by_test_id("settings-signup-mode").select_option(v)
            await sa.get_by_test_id("settings-save").click()
            await sa.wait_for_timeout(1000)
        assert api("GET", "system/public_info")[1]["data"]["signup_mode"] == v, f"signup_mode chưa đổi sang {v}"

    try:
        await mode("default_tenant")
        await f.shot(sa, "a-settings")
        p = await f.page()
        await p.goto(BASE + "/register")
        await p.get_by_test_id("register-name").wait_for()
        assert await p.get_by_test_id("register-tenant").count() == 0, "default_tenant: không được có ô tên tổ chức"
        await f.shot(p, "a-register")
        await ui_register(p, "E2E Default", f"{uid(w, 't1a')}@e2e.test")
        await in_app(p)
        await open_user_menu(p)
        txt = await p.get_by_test_id("user-menu-tenant").inner_text()
        assert default_name in txt, f"tenant menu '{txt}' != '{default_name}'"
        await f.shot(p, "a-menu")

        await mode("new_tenant")
        p = await f.page()
        await p.goto(BASE + "/register")
        await p.get_by_test_id("register-tenant").wait_for()
        await f.shot(p, "b-register")
        org = f"E2E Org {RUN} {w}"
        await ui_register(p, "E2E NewTenant", f"{uid(w, 't1b')}@e2e.test", tenant=org)
        await in_app(p)
        await p.goto(BASE + "/org")
        await p.get_by_test_id("org-name").wait_for()
        await p.wait_for_function("document.querySelector('[data-testid=org-name]').value !== ''")
        assert await p.get_by_test_id("org-name").input_value() == org, "tên tổ chức sai ở /org"
        await p.get_by_test_id("org-invites").wait_for()
        await f.shot(p, "b-org")

        await mode("invite_only")
        p = await f.page()
        await p.goto(BASE + "/register")
        await p.get_by_text("Đăng ký đang đóng").wait_for()
        await f.shot(p, "c-closed")
        await ui_register(p, "E2E Closed", f"{uid(w, 't1c')}@e2e.test")
        await p.get_by_role("alert").wait_for()
        assert "/register" in p.url
        await f.shot(p, "c-error")
    finally:
        set_settings(signup_mode="default_tenant")


# ---------- T2 ----------
async def t2(f: Flow):
    w = f.width
    f.allow("auth/login", (401, 403), "đăng nhập chưa xác thực email")
    sa = await sa_page(f)
    try:
        set_settings(email_verification="required")
        p = await f.page()
        em = f"{uid(w, 't2r')}@e2e.test"
        await p.goto(BASE + "/register")
        await ui_register(p, "E2E Verify", em)
        await p.get_by_test_id("register-check-email").wait_for()
        assert "/register" in p.url
        await f.shot(p, "check-email")
        await ui_login(p, em, expect_ok=False)
        await p.get_by_role("alert").get_by_text("chưa được xác thực").wait_for()
        assert "/login" in p.url
        await f.shot(p, "login-blocked")
        await see_mail(f, sa, em, "mail")
        link = mail_link(em, r"/verify-email\?token=")
        v = await f.page()
        await v.goto(link)
        await v.get_by_test_id("verify-done").wait_for()
        assert "Email đã được xác thực" in await v.get_by_test_id("verify-done").inner_text()
        await f.shot(v, "verified")
        await ui_login(v, em)
        await f.shot(v, "login-ok")

        set_settings(email_verification="soft")
        s = await f.page()
        await s.goto(BASE + "/register")
        await ui_register(s, "E2E Soft", f"{uid(w, 't2s')}@e2e.test")
        await in_app(s)
        await s.get_by_test_id("verify-banner").wait_for()
        await f.shot(s, "soft-banner")
        await s.get_by_test_id("verify-banner-send").click()
        await s.wait_for_function("document.querySelector('[data-testid=verify-banner-send]').disabled")
        await f.shot(s, "soft-sent")
    finally:
        set_settings(email_verification="soft")


# ---------- T3 ----------
async def t3(f: Flow):
    w = f.width
    f.allow("invites/preview", (404, 400, 410, 422), "link mời đã thu hồi / không hợp lệ")
    admin_tok = token_of("acme-admin@test.local")
    before = {i["id"] for i in api("GET", "tenant/list_invites", admin_tok)[1]["data"]}
    a = await f.page()
    await ui_login(a, "acme-admin@test.local")
    await a.goto(BASE + "/org")
    await a.get_by_test_id("invite-new").click()
    await a.get_by_test_id("invite-mode-link").click()
    opt = await a.get_by_test_id("invite-role").evaluate("s => [...s.options].map(o => [o.value, o.textContent])")
    vid = next(v for v, t in opt if t.strip().lower().startswith("viewer"))
    await a.get_by_test_id("invite-role").select_option(vid)
    await f.shot(a, "dialog")
    await a.get_by_test_id("dialog-submit").click()
    link = await a.get_by_test_id("invite-link").input_value()
    assert "/invite/" in link, link
    await f.shot(a, "link")
    await a.get_by_test_id("dialog-submit").click()  # nút Đóng
    token_path = link[link.index("/invite/") :]

    b = await f.page()
    await b.goto(BASE + token_path)
    pv = b.get_by_test_id("invite-preview")
    await pv.wait_for()
    txt = await pv.inner_text()
    assert "Bạn được mời vào Acme với vai trò viewer" in txt, txt
    await f.shot(b, "preview")
    await ui_register(b, "E2E Invitee", f"{uid(w, 't3')}@e2e.test")
    await in_app(b)
    await open_user_menu(b)
    assert "Acme" in await b.get_by_test_id("user-menu-tenant").inner_text()
    await f.shot(b, "invitee-in")

    await a.reload()
    await a.get_by_test_id("org-invites").wait_for()
    new = {i["id"] for i in api("GET", "tenant/list_invites", admin_tok)[1]["data"]} - before
    assert len(new) == 1, f"lời mời mới: {new}"
    iid = new.pop()
    row = a.get_by_test_id(f"invite-{iid}")
    await row.wait_for()
    assert re.search(r"Đã dùng 1 / \d+", await row.inner_text()), await row.inner_text()
    await f.shot(a, "used")
    await a.get_by_test_id(f"invite-revoke-{iid}").click()
    await row.wait_for(state="detached")
    c = await f.page()
    await c.goto(BASE + token_path)
    await c.get_by_text("không hợp lệ").first.wait_for()
    await f.shot(c, "revoked")


# ---------- T4 ----------
async def t4(f: Flow):
    f.allow("admin/get_user", (404,), "get_user chéo tenant phải 404")
    acme_tok = token_of("acme-admin@test.local")
    items = api("GET", "admin/list_users", acme_tok, query={"limit": 100})[1]["data"]["items"]
    acme1 = next(u["id"] for u in items if u["email"] == "acme1@test.local")

    a = await f.page()
    await ui_login(a, "acme-admin@test.local")
    await a.goto(BASE + "/admin/users")
    await a.get_by_text("acme1@test.local").first.wait_for()
    body = await a.evaluate("document.body.innerText")
    assert "user1@test.local" not in body and "admin@test.local" not in body.replace("acme-admin@test.local", ""), (
        "acme-admin thấy user tenant khác"
    )
    await f.shot(a, "acme-users")

    d = await f.page()
    await ui_login(d, "admin@test.local")
    await d.goto(BASE + "/admin/users")
    await d.get_by_text("user1@test.local").first.wait_for()
    body = await d.evaluate("document.body.innerText")
    assert "acme1@test.local" not in body, "admin default thấy user Acme"
    await f.shot(d, "default-users")
    st, env = api("GET", "admin/get_user", token_of("admin@test.local"), query={"user_id": acme1})
    assert st == 404, f"get_user chéo tenant trả {st}: {env}"
    f.notes.append(f"API get_user chéo tenant -> {st} code={env.get('code')}")


# ---------- T5 ----------
async def t5(f: Flow):
    w = f.width
    f.allow("auth/login", (401, 403, 400), "mật khẩu cũ bị từ chối")
    f.allow("auth/reset_password", (400, 401, 403, 404, 410, 422), "link đặt lại đã dùng")
    set_settings(email_verification="soft")
    em, new_pw = f"{uid(w, 't5')}@e2e.test", "newpass456"
    sa = await sa_page(f)
    p = await f.page()
    await p.goto(BASE + "/register")
    await ui_register(p, "E2E Forgot", em)
    await in_app(p)
    await logout(p)
    await p.get_by_test_id("login-forgot").click()
    await p.get_by_test_id("forgot-email").fill(em)
    await f.shot(p, "forgot-form")
    await p.get_by_test_id("forgot-submit").click()
    await p.get_by_test_id("forgot-sent").wait_for()
    assert "Nếu email có tài khoản" in await p.get_by_test_id("forgot-sent").inner_text()
    await f.shot(p, "forgot-sent")
    await see_mail(f, sa, em, "mail")
    link = mail_link(em, r"/reset-password\?token=")
    r = await f.page()
    await r.goto(link)
    await r.get_by_test_id("reset-password").fill(new_pw)
    await f.shot(r, "reset-form")
    await r.get_by_test_id("reset-submit").click()
    await r.get_by_test_id("reset-done").wait_for()
    await f.shot(r, "reset-done")
    await ui_login(r, em, PW, expect_ok=False)
    await r.get_by_role("alert").wait_for()
    assert "/login" in r.url
    await f.shot(r, "old-pw-rejected")
    await ui_login(r, em, new_pw)
    await open_user_menu(r)
    await f.shot(r, "new-pw-ok")
    r2 = await f.page()
    await r2.goto(link)
    await r2.get_by_test_id("reset-password").fill("another789")
    await r2.get_by_test_id("reset-submit").click()
    await r2.get_by_role("alert").wait_for()
    assert (
        "không hợp lệ" in await r2.get_by_role("alert").inner_text()
        or "hết hạn" in await r2.get_by_role("alert").inner_text()
    )
    await f.shot(r2, "link-reused")


# ---------- T6 ----------
async def t6(f: Flow):
    w = f.width
    f.allow("auth/login", (401, 403), "đăng nhập tổ chức bị khoá")
    for sub in ("/",):
        f.allow(sub, (401, 403), "request của user sau khi tổ chức bị khoá (chỉ tính khi đã khoá)")
    name, em = f"E2E Lock {RUN} {w}", f"{uid(w, 't6')}@e2e.test"
    sa_tok = token_of("superadmin@test.local")
    tid = None
    s = await sa_page(f)
    try:
        await s.goto(BASE + "/sa/tenants")
        await s.get_by_test_id("tenant-create").click()
        await s.get_by_test_id("tenant-name").fill(name)
        await s.get_by_test_id("tenant-admin-email").fill(em)
        await f.shot(s, "create-dialog")
        await s.get_by_test_id("dialog-submit").click()
        await s.get_by_test_id("tenant-name").wait_for(state="detached")
        items = api("GET", "tenants/list", sa_tok, query={"limit": 100, "q": name.replace(" ", "%20")})[1]["data"][
            "items"
        ]
        t = next(x for x in items if x["name"] == name)
        slug, tid = t["slug"], t["id"]
        await s.get_by_test_id("tenants-search").fill(name)
        await s.get_by_test_id(f"tenant-{slug}").wait_for()
        await f.shot(s, "tenants")
        link = mail_link(em, r"/invite/")
        u = await f.page()
        await u.goto(link)
        await u.get_by_test_id("invite-preview").wait_for()
        await ui_register(u, "E2E Lock Admin", em)
        await in_app(u)
        await u.goto(BASE + "/org")
        await u.get_by_test_id("org-info").wait_for()
        await u.wait_for_timeout(1500)  # socket nối xong
        await f.shot(u, "org-before")

        await s.get_by_test_id(f"tenant-toggle-{slug}").click()
        await f.shot(s, "confirm")
        await s.get_by_role("dialog").get_by_role("button", name="Khoá", exact=True).click()
        t0 = time.time()
        await u.wait_for_url(lambda x: "/login" in x, timeout=10000)
        f.notes.append(f"đăng xuất realtime sau {time.time() - t0:.1f}s")
        await f.shot(u, "kicked")
        await ui_login(u, em, expect_ok=False)
        await u.get_by_role("alert").get_by_text("bị khoá").wait_for()
        await f.shot(u, "login-suspended")
        await s.get_by_test_id(f"tenant-toggle-{slug}").click()  # Mở khoá
        await s.wait_for_timeout(1500)
        await f.shot(s, "resumed")
        await ui_login(u, em)
        await f.shot(u, "login-after-resume")
    finally:
        if tid:
            api("POST", "tenants/resume", sa_tok, {"tenant_id": tid})


# ---------- T7 ----------
async def t7(f: Flow):
    admin_tok = token_of("acme-admin@test.local")
    st, env = api("POST", "tenant/invite", admin_tok, {"email": None, "role_id": None, "days": 1, "max_uses": 3})
    assert st == 200 and env["data"].get("link"), f"tạo mời: {st} {env}"
    tok_path = env["data"]["link"][env["data"]["link"].index("/invite/") :]
    sa_tok = token_of("superadmin@test.local")
    try:
        g = await f.page()
        await g.goto(BASE + "/forgot-password")
        await g.get_by_test_id("forgot-email").wait_for()
        await f.shot(g, "forgot")
        await g.goto(BASE + tok_path)
        await g.get_by_test_id("invite-preview").wait_for()
        await f.shot(g, "invite")
        s = await sa_page(f)
        for path, step in (("/org", "org"), ("/sa/tenants", "tenants"), ("/sa/mail", "mail")):
            await s.goto(BASE + path)
            await s.wait_for_load_state("networkidle")
            await f.shot(s, step)
        # English
        if f.width >= 768:
            await s.goto(BASE + "/profile")
            await s.get_by_test_id("lang-en").click()
        else:
            await s.get_by_test_id("user-menu").click()
            await s.get_by_role("menuitem").filter(has_text=re.compile(r"^\s*EN")).click()
        await s.wait_for_timeout(1000)
        for path, step in (("/org", "en-org"), ("/sa/tenants", "en-tenants")):
            await s.goto(BASE + path)
            await s.wait_for_load_state("networkidle")
            await s.wait_for_timeout(500)
            await f.shot(s, step)
            # bỏ hàng tenant (tên tenant là dữ liệu của smoke, vd "Smoke xxx đổi tên"), chỉ xét chữ giao diện
            body = await s.evaluate(
                "(() => { const c = document.body.cloneNode(true);"
                ' c.querySelectorAll(\'[data-testid^="tenant-"]:not([data-testid="tenant-create"])\')'
                ".forEach(e => e.remove());"
                " document.body.appendChild(c); c.style.cssText='position:fixed;left:-9999px';"
                " const t = c.innerText; c.remove(); return t; })()"
            )
            vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
            if vi:
                f.problems.append(f"[{step}] còn chuỗi tiếng Việt: {vi[:8]}")
    finally:
        api("POST", "auth/update_me", sa_tok, {"locale": "vi"})


FLOWS = {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6, "T7": t7}


async def main():
    global BASE, API
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE, API = args.base, args.base + "/bizwithagents/api"
    OUT.mkdir(parents=True, exist_ok=True)
    only = [x.strip().upper() for x in args.only.split(",") if x.strip()] or list(FLOWS)
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for name in only:
                for width, height in SIZES:
                    f = Flow(browser, name, width, height)
                    try:
                        await FLOWS[name](f)
                    except Exception as e:  # noqa: BLE001
                        f.problems.append(f"ASSERT/EXC: {type(e).__name__}: {str(e)[:400]}")
                        if f.last_page:
                            try:
                                await f.last_page.screenshot(path=str(OUT / f"{name}-FAIL-{width}.png"), full_page=True)
                                f.shots.append(f".e2e/sp1/{name}-FAIL-{width}.png (url={f.last_page.url})")
                            except Exception:  # noqa: BLE001
                                pass
                    res = f.finish()
                    await f.close()
                    results.append(res)
                    print(f"{name} {width}: {'PASS' if res['pass'] else 'FAIL'}", *res["problems"], sep="\n   ")
        finally:
            await browser.close()
            for kw in ({"signup_mode": "default_tenant"}, {"email_verification": "soft"}):
                try:
                    set_settings(**kw)
                except Exception as e:  # noqa: BLE001
                    print("dọn lỗi", kw, e)
    (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("tổng:", sum(r["pass"] for r in results), "/", len(results), "PASS")


if __name__ == "__main__":
    asyncio.run(main())
