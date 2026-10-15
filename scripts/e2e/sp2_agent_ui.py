# ruff: noqa: E501
"""E2E Playwright cho SP2 (trợ lý theo tổ chức + stream + Cài đặt AI) trên stack thử.

Chạy:
    export PLAYWRIGHT_BROWSERS_PATH=<thư mục trình duyệt>
    <python có playwright> scripts/e2e/sp2_agent_ui.py [--only S1,S2] [--base http://127.0.0.1:8201]

Luồng (mỗi luồng chạy 1440x900 rồi 375x812):
  S1 /sa/ai-settings (2 thẻ), /sa/settings có link sang AI, ô flush = 10 báo lỗi + khoá Lưu
  S2 stream bật: chữ của live-run tăng dần qua >= 3 mức trung gian, data-stream=on
  S3 stream tắt: chữ nhảy thẳng rỗng -> đủ, data-stream=off (luôn bật lại stream)
  S4 tắt trợ lý theo tổ chức Acme: menu / nút nổi biến mất <= 10s không tải lại (luôn bật lại)
  S5 usage tab Tổ chức + lọc tenant_id, traces lọc tổ chức hiện "(Acme)"
  S6 ảnh giao diện + English không còn chuỗi Việt / khoá i18n thô

DoD mỗi luồng x kích thước: console error = 0 (4xx chủ ý khai báo bằng allow()), không HTTP >= 500,
không cuộn ngang, không khoá i18n thô, assertion đúng; ở 375 vùng chạm công tắc stream và mục menu
"Cài đặt" (AI) >= 44px.
Ảnh: .e2e/sp2/<luồng>-<bước>-<rộng>.png ; kết quả: .e2e/sp2/result.json.
Tự dọn: stream bật (flush 50), Acme bật trợ lý, locale vi.
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
OUT = ROOT / ".e2e" / "sp2"
PW = os.environ.get("SEED_PASSWORD") or "password123"
BASE = "http://127.0.0.1:8201"
API = BASE + "/bizwithagents/api"
SIZES = [(1440, 900), (375, 812)]
RAW_KEY = re.compile(
    r"^(auth|org|tenants|invite|nav|verify|sa|common|action|err|mail|profile|admin|lang|theme|menu|settings|notif|chat|usage|trace|traces|agent)"
    r"\.[A-Za-z][A-Za-z0-9_.]*$"
)
VI_CHARS = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)

SAMPLER = """() => {
  window.__samples = [];
  window.__t0 = performance.now();
  window.__iv = setInterval(() => {
    const el = document.querySelector('[data-testid=live-run]');
    window.__samples.push([Math.round(performance.now() - window.__t0),
      el ? el.innerText.trim().length : -1, el ? el.getAttribute('data-stream') : null]);
  }, 40);
}"""


def xff() -> str:
    return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def api(method: str, path: str, token: str | None = None, body: dict | None = None, query: dict | None = None):
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


def acme_id() -> str:
    st, env = api("GET", "tenants/list", token_of("superadmin@test.local"), query={"q": "acme"})
    assert st == 200, f"tenants/list {st} {env}"
    items = env["data"]["items"]
    return next(t["id"] for t in items if t["slug"] == "acme")


def acme_agent(enabled: bool):
    policies = {"agent_enabled": None if enabled else False}
    st, env = api(
        "POST", "tenants/update", token_of("superadmin@test.local"), {"tenant_id": acme_id(), "policies": policies}
    )
    assert st == 200, f"tenants/update {st} {env}"


class Flow:
    def __init__(self, browser, name: str, width: int, height: int):
        self.browser, self.name, self.width, self.height = browser, name, width, height
        self.ctxs, self.console, self.http = [], [], []
        self.allowed: list[tuple[str, tuple, str]] = []
        self.problems, self.notes, self.shots = [], [], []
        self.last_page = None

    def allow(self, sub: str, statuses: tuple, why: str):
        self.allowed.append((sub, statuses, why))

    async def ctx(self):
        c = await self.browser.new_context(viewport={"width": self.width, "height": self.height}, locale="vi-VN")
        ip = xff()

        async def add_ip(route):
            await route.continue_(headers={**route.request.headers, "x-forwarded-for": ip})

        await c.route(BASE + "/**", add_ip)
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
async def ui_login(page, email: str):
    await page.goto(BASE + "/login")
    await page.get_by_test_id("login-email").fill(email)
    await page.get_by_test_id("login-password").fill(PW)
    await page.get_by_test_id("login-submit").click()
    await page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    await page.wait_for_load_state("networkidle")


async def login_page(f: Flow, email: str):
    p = await f.page()
    await ui_login(p, email)
    return p


def mobile(f: Flow) -> bool:
    return f.width < 768


async def open_drawer(p):
    await p.get_by_test_id("nav-open").click()
    await p.get_by_test_id("nav-drawer").wait_for()


async def goto_ai_settings_via_menu(f: Flow, p):
    """Menu -> nhóm Trợ lý AI -> Cài đặt; trả về chiều cao mục menu."""
    if mobile(f):
        await open_drawer(p)
    root = p.get_by_test_id("nav-drawer" if mobile(f) else "sidebar")
    grp = root.get_by_test_id("nav-group-ai")
    await grp.wait_for()
    item = root.get_by_test_id("nav-ai-settings")
    if await item.count() == 0 or not await item.is_visible():
        await grp.click()
    await item.wait_for()
    box = await item.bounding_box()
    await item.click()
    await p.wait_for_url("**/sa/ai-settings")
    await p.get_by_test_id("ai-settings").wait_for()
    return box["height"]


async def send_chat(p, text: str):
    await p.get_by_test_id("chat-input").fill(text)
    await p.get_by_test_id("chat-send").click()


async def wait_chat_done(p, timeout=30000):
    await p.get_by_test_id("msg-pending").or_(p.get_by_test_id("live-run")).first.wait_for(timeout=timeout)
    await p.wait_for_function(
        "!document.querySelector('[data-testid=live-run]') || "
        "['succeeded','done','completed','failed','error','cancelled'].includes("
        "document.querySelector('[data-testid=live-run]').getAttribute('data-status'))",
        timeout=timeout,
    )
    await p.wait_for_timeout(1500)


async def stream_run(f: Flow, p, expect: str, step: str):
    await p.goto(BASE + "/assistant")
    await p.get_by_test_id("chat-input").wait_for()
    # lần đầu sau khi dựng stack, socket nối chậm → token đầu rơi trước khi vào phòng; chờ nối rồi mới gửi
    await p.locator("[data-testid=socket-dot][data-status=connected]").first.wait_for(state="attached", timeout=15000)
    await p.evaluate(SAMPLER)
    await send_chat(p, "slow xin chao")
    await wait_chat_done(p)
    samples = await p.evaluate("clearInterval(window.__iv) || window.__samples")
    # mở lại /assistant có thể chạy lại chữ của lượt cũ trong live-run (quan sát riêng) -> chỉ lấy đoạn sau lần live-run vắng cuối cùng
    gaps = [i for i, s_ in enumerate(samples) if s_[1] < 0 and any(x[1] >= 0 for x in samples[i:])]
    if gaps and any(x[1] >= 0 for x in samples[: gaps[-1]]):
        f.notes.append(
            f"{step}: live-run có chữ của lượt cũ ({max(x[1] for x in samples[: gaps[-1]])} ký tự) trước khi gửi tin mới"
        )
    samples = samples[gaps[-1] + 1 :] if gaps else samples
    attrs = {s[2] for s in samples if s[2]}
    lens = [s[1] for s in samples if s[1] >= 0]
    mx = max(lens) if lens else 0
    base = lens[0] if lens else 0  # live-run có sẵn nhãn / chấm trước khi có chữ
    inter = sorted({n for n in lens if base + 2 < n < 0.8 * mx})
    f.notes.append(
        f"{step}: data-stream={sorted(attrs)} max={mx} số mức trung gian={len(inter)} mẫu={len(samples)} chuỗi (ms,len)={[(a, b) for a, b, _ in samples if b >= 0][:60]}"
    )
    last = next(s[2] for s in reversed(samples) if s[2])
    early = [s for s in samples if s[2] and s[2] != expect and s[1] > base + 2]
    assert last == expect and not early, (
        f"data-stream mong {expect}, thực tế {attrs} (cuối={last}, lệch kèm chữ={early[:3]})"
    )
    await f.shot(p, step)
    scroll = await p.get_by_test_id("chat-scroll").inner_text()
    assert "slow xin chao" in scroll and len(scroll) > len("slow xin chao") + 40, (
        f"không có câu trả lời đủ: {scroll[:200]!r}"
    )
    return inter, mx


# ---------- S1 ----------
async def s1(f: Flow):
    sa = await login_page(f, "superadmin@test.local")
    h = await goto_ai_settings_via_menu(f, sa)
    f.notes.append(f"chiều cao mục menu Cài đặt (AI) = {h:.0f}px")
    if mobile(f) and h < 44:
        f.problems.append(f"mục menu Cài đặt cao {h:.0f}px < 44")
    await sa.wait_for_load_state("networkidle")
    await sa.get_by_test_id("settings-chat-stream").wait_for()
    form_text = await sa.get_by_test_id("ai-settings").inner_text()
    assert "Trợ lý chat" in form_text, "thiếu thẻ Trợ lý chat"
    assert "Trả lời dạng stream" in form_text, "thiếu thẻ Trả lời dạng stream"
    cards = await sa.get_by_test_id("ai-settings").locator("> div").count()
    assert cards >= 2, f"số thẻ = {cards}"
    assert await sa.get_by_test_id("settings-field-chat_session_idle_min").count() == 1, (
        "ô chat_session_idle_min phải ở /sa/ai-settings"
    )
    # vùng chạm công tắc
    ok = await sa.evaluate(
        """() => { const s = document.querySelector('[data-testid=settings-chat-stream]');
        s.scrollIntoView({block: 'center'}); const r = s.getBoundingClientRect();
        const cx = r.left + r.width/2, cy = r.top + r.height/2;
        const hit = (y) => { const e = document.elementFromPoint(cx, y); return !!e && (e === s || s.contains(e)); };
        let ext = 0; while (ext < 40 && hit(cy - ext - 1) && hit(cy + ext + 1)) ext++;
        return {box: r.height, hit: 2 * ext + 1, after: getComputedStyle(s, '::after').height}; }"""
    )
    f.notes.append(
        f"công tắc stream: box {ok['box']:.0f}px, vùng chạm đo bằng elementFromPoint ~{ok['hit']}px, ::after cao {ok['after']}"
    )
    if mobile(f) and ok["hit"] < 44:
        f.problems.append(
            f"vùng chạm công tắc stream ~{ok['hit']}px < 44px (box {ok['box']:.0f}px, ::after {ok['after']})"
        )
    await f.shot(sa, "ai-settings")
    # ô flush
    fld = sa.get_by_test_id("settings-field-chat_stream_flush_ms")
    orig = await fld.input_value()
    await fld.fill("10")
    await sa.get_by_text("Nhập số nguyên từ 20 đến 1000").wait_for()
    assert await sa.get_by_test_id("settings-save").is_disabled(), "Lưu phải khoá khi flush=10"
    await f.shot(sa, "flush-error")
    await fld.fill(orig)
    await sa.wait_for_timeout(300)
    assert await sa.get_by_text("Nhập số nguyên từ 20 đến 1000").count() == 0, "lỗi chưa biến mất"
    assert await sa.get_by_test_id("settings-save").is_disabled(), "Lưu phải khoá khi không có thay đổi"
    # /sa/settings
    await sa.goto(BASE + "/sa/settings")
    await sa.get_by_test_id("settings-ai-link").wait_for()
    assert await sa.get_by_test_id("settings-field-chat_session_idle_min").count() == 0, (
        "/sa/settings còn ô chat_session_idle_min"
    )
    await f.shot(sa, "settings-link")
    await sa.get_by_test_id("settings-ai-link").click()
    await sa.wait_for_url("**/sa/ai-settings")


# ---------- S2 ----------
async def s2(f: Flow):
    set_settings(chat_stream=True, chat_stream_flush_ms=50)
    p = await login_page(f, "user1@test.local")
    inter, mx = await stream_run(f, p, "on", "stream-on")
    assert len(inter) >= 3, f"chỉ {len(inter)} mức trung gian (max={mx}): {inter[:10]}"


# ---------- S3 ----------
async def s3(f: Flow):
    try:
        sa = await login_page(f, "superadmin@test.local")
        await sa.goto(BASE + "/sa/ai-settings")
        sw = sa.get_by_test_id("settings-chat-stream")
        await sw.wait_for()
        await sa.wait_for_timeout(500)
        if await sw.get_attribute("data-state") == "checked":
            await sw.click()
        await sa.get_by_test_id("settings-save").click()
        await sa.wait_for_timeout(1200)
        await sa.reload()
        await sa.get_by_test_id("settings-chat-stream").wait_for()
        await sa.wait_for_timeout(500)
        assert await sa.get_by_test_id("settings-chat-stream").get_attribute("data-state") == "unchecked", (
            "stream chưa tắt"
        )
        await f.shot(sa, "off-settings")
        p = await login_page(f, "user1@test.local")
        inter, mx = await stream_run(f, p, "off", "stream-off")
        assert mx > 0, "không thấy chữ trong live-run"
        assert len(inter) <= 1, f"stream tắt nhưng có {len(inter)} mức trung gian: {inter[:10]}"
    finally:
        set_settings(chat_stream=True, chat_stream_flush_ms=50)


# ---------- S4 ----------
async def s4(f: Flow):
    mob = mobile(f)
    f.allow("agent/", (403,), "tổ chức tắt trợ lý (err 6023)")
    f.allow("chat", (403,), "tổ chức tắt trợ lý (err 6023)")
    f.allow("session", (403,), "tổ chức tắt trợ lý (err 6023)")
    f.allow("assistant", (403,), "tổ chức tắt trợ lý (err 6023)")
    try:
        acme_agent(True)
        ac = await login_page(f, "acme1@test.local")
        await ac.goto(BASE + "/")
        await ac.wait_for_load_state("networkidle")
        target = (
            ac.get_by_test_id("dock-assistant") if mob else ac.get_by_test_id("sidebar").get_by_test_id("nav-assistant")
        )
        await target.wait_for()
        if mob:
            await open_drawer(ac)
            await ac.get_by_test_id("nav-drawer").get_by_test_id("nav-assistant").wait_for()
            await ac.keyboard.press("Escape")
        await f.shot(ac, "acme-before")
        sa = await login_page(f, "superadmin@test.local")
        await sa.goto(BASE + "/sa/tenants")
        await sa.get_by_test_id("tenant-edit-acme").click()
        sw = sa.get_by_test_id("tenant-agent-enabled")
        await sw.wait_for()
        assert await sw.get_attribute("data-state") == "checked", "Acme phải đang bật trợ lý"
        await f.shot(sa, "tenant-dialog")
        await sw.click()
        await sa.get_by_test_id("dialog-submit").click()
        t0 = time.time()
        await target.wait_for(state="detached", timeout=10000)
        took = time.time() - t0
        f.notes.append(f"nút/mục Trợ lý biến mất sau {took:.1f}s (không tải lại trang)")
        if mob:
            await open_drawer(ac)
            await ac.wait_for_timeout(300)
            assert await ac.get_by_test_id("nav-drawer").get_by_test_id("nav-assistant").count() == 0, (
                "mục Trợ lý còn trong ngăn kéo"
            )
            await f.shot(ac, "acme-drawer")
            await ac.keyboard.press("Escape")
        else:
            assert await ac.get_by_test_id("sidebar").get_by_test_id("nav-assistant").count() == 0, (
                "mục Trợ lý còn ở menu"
            )
        await f.shot(ac, "acme-after")
        await ac.goto(BASE + "/assistant")
        await ac.get_by_text("Trợ lý đang tắt cho tổ chức của bạn").first.wait_for()
        await f.shot(ac, "acme-assistant-off")
        u = await login_page(f, "user1@test.local")
        await u.goto(BASE + "/assistant")
        await u.get_by_test_id("chat-input").wait_for()
        await send_chat(u, "ping s4")
        await u.get_by_text("Bạn nói: ping s4").first.wait_for(timeout=30000)
        await f.shot(u, "user1-ok")
    finally:
        acme_agent(True)


# ---------- S5 ----------
async def s5(f: Flow):
    acme_agent(True)
    ad = await login_page(f, "acme-admin@test.local")
    await ad.goto(BASE + "/assistant")
    await ad.get_by_test_id("chat-input").wait_for()
    await send_chat(ad, f"hello acme {f.width}")
    await ad.get_by_text(f"Bạn nói: hello acme {f.width}").first.wait_for(timeout=30000)
    default_name = api("GET", "tenant/get", token_of("superadmin@test.local"))[1]["data"]["name"]
    sa = await login_page(f, "superadmin@test.local")
    await sa.goto(BASE + "/sa/usage")
    await sa.get_by_test_id("usage-tab-tenant").click()
    end = time.time() + 30
    body = ""
    while time.time() < end:
        await sa.wait_for_timeout(1500)
        body = await sa.get_by_test_id("usage-breakdown").inner_text()
        if "Acme" in body:
            break
        await sa.reload()
        await sa.get_by_test_id("usage-tab-tenant").click()
    assert "Acme" in body, f"không có dòng Acme: {body[:300]!r}"
    assert re.search(r"\bacme\b", body), "thiếu slug acme"
    assert default_name in body, f"thiếu tổ chức mặc định '{default_name}'"
    await f.shot(sa, "usage-tenant")
    sel = sa.get_by_test_id("usage-filter-tenant_id")
    await sel.select_option(label=re.compile("Acme")) if False else None
    opts = await sel.locator("option").all_inner_texts()
    label = next(o for o in opts if "Acme" in o)
    await sel.select_option(label=label)
    await sa.wait_for_url(re.compile(r"tenant_id="))
    await f.shot(sa, "usage-filtered")
    await sa.goto(BASE + "/sa/traces")
    tsel = sa.get_by_test_id("trace-tenant")
    await tsel.wait_for()
    opts = await tsel.locator("option").all_inner_texts()
    await tsel.select_option(label=next(o for o in opts if "Acme" in o))
    await sa.wait_for_url(re.compile(r"tenant_id="))
    await sa.wait_for_timeout(2000)
    li = sa.locator(
        "[data-testid^=trace-]:not([data-testid^=trace-open]):not([data-testid^=trace-by]):not([data-testid=trace-filters]):not([data-testid=trace-tenant])"
    )
    txt = await sa.locator("main").inner_text()
    assert "(Acme)" in txt, f"không thấy '(Acme)' trong danh sách trace: {txt[:300]!r} ({await li.count()} mục)"
    await f.shot(sa, "traces-acme")


# ---------- S6 ----------
async def s6(f: Flow):
    sa_tok = token_of("superadmin@test.local")
    try:
        acme_agent(False)
        ac = await login_page(f, "acme1@test.local")
        await ac.goto(BASE + "/assistant")
        await ac.get_by_text("Trợ lý đang tắt cho tổ chức của bạn").first.wait_for()
        await f.shot(ac, "assistant-off")
        acme_agent(True)
        s = await login_page(f, "superadmin@test.local")
        for path, step, tid in (
            ("/sa/ai-settings", "ai-settings", "ai-settings"),
            ("/sa/usage", "usage", "usage-breakdown"),
            ("/sa/traces", "traces", "trace-filters"),
        ):
            await s.goto(BASE + path)
            await s.get_by_test_id(tid).wait_for()
            if step == "usage":
                await s.get_by_test_id("usage-tab-tenant").click()
            await s.wait_for_timeout(1200)
            await f.shot(s, step)
        if not mobile(f):
            await s.goto(BASE + "/profile")
            await s.get_by_test_id("lang-en").click()
        else:
            await s.get_by_test_id("user-menu").click()
            await s.get_by_role("menuitem").filter(has_text=re.compile(r"^\s*EN")).click()
        await s.wait_for_timeout(1000)
        await s.goto(BASE + "/sa/ai-settings")
        await s.get_by_test_id("ai-settings").wait_for()
        await s.wait_for_timeout(800)
        await f.shot(s, "en-ai-settings")
        body = await s.get_by_test_id("ai-settings").inner_text()
        vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
        if vi:
            f.problems.append(f"[en-ai-settings] còn chuỗi tiếng Việt: {vi[:8]}")
        if mobile(f):
            await open_drawer(s)
            nav = await s.get_by_test_id("nav-drawer").inner_text()
            vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", nav, re.I)))
            if vi:
                f.problems.append(f"[en-drawer] còn chuỗi tiếng Việt: {vi[:8]}")
            await s.keyboard.press("Escape")
    finally:
        acme_agent(True)
        api("POST", "auth/update_me", sa_tok, {"locale": "vi"})


FLOWS = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6}


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
                                f.shots.append(f".e2e/sp2/{name}-FAIL-{width}.png (url={f.last_page.url})")
                            except Exception:  # noqa: BLE001
                                pass
                    res = f.finish()
                    await f.close()
                    results.append(res)
                    print(
                        f"{name} {width}: {'PASS' if res['pass'] else 'FAIL'}",
                        *res["problems"],
                        *[f"  note: {n}" for n in res["notes"]],
                        sep="\n   ",
                    )
        finally:
            await browser.close()
            for fn, kw in ((set_settings, {"chat_stream": True, "chat_stream_flush_ms": 50}), (acme_agent, None)):
                try:
                    fn(**kw) if kw else fn(True)
                except Exception as e:  # noqa: BLE001
                    print("dọn lỗi", fn.__name__, e)
            try:
                api("POST", "auth/update_me", token_of("superadmin@test.local"), {"locale": "vi"})
            except Exception as e:  # noqa: BLE001
                print("dọn locale lỗi", e)
    (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("tổng:", sum(r["pass"] for r in results), "/", len(results), "PASS")


if __name__ == "__main__":
    asyncio.run(main())
