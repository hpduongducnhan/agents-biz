# ruff: noqa: E501
"""E2E Playwright cho SP3 (module mẫu Tasks — quản lý công việc) trên stack thử.

Chạy:
    export PLAYWRIGHT_BROWSERS_PATH=<thư mục trình duyệt>
    <python có playwright> scripts/e2e/sp3_tasks_ui.py [--only K1,K2] [--base http://127.0.0.1:8201]

Luồng (mỗi luồng chạy 1440x900 rồi 375x812):
  K1 Web CRUD (user1): tạo việc (Cao, hạn mai, giao User 2) -> danh sách -> chi tiết -> Đang làm -> sửa tiêu đề
     -> bình luận -> đóng -> danh sách phản ánh; lọc Của tôi / Đã xong / tìm chữ / hạn — URL đổi theo
  K2 Realtime cùng tổ chức (user1 + user2): giao việc -> user2 thấy <= 5s + chuông tăng; user2 đánh dấu Xong -> user1 thấy <= 5s
  K3 Tách tổ chức: acme1 không thấy việc của default (danh sách + ?task=<id> -> "Không tìm thấy công việc"); việc của Acme user1 không thấy
  K4 Qua trợ lý: route:tasks call:tasks_create -> việc + nhãn "Tạo bởi trợ lý"; tasks_delete -> thẻ duyệt -> Duyệt -> biến <= 5s
  K5 Quyền: viewer (user3) không tạo / sửa / bình luận / xoá; admin xoá có hộp xác nhận
  K6 Tổng quan: widget "Việc của tôi" cập nhật khi có việc quá hạn; 375: "Việc mới" ở cụm nút nổi -> tạo -> toast
  K7 Ảnh giao diện + English (không còn chuỗi Việt / khoá i18n thô)

DoD mỗi luồng x kích thước: console error = 0 (4xx chủ ý khai báo bằng allow()), không HTTP >= 500, không cuộn ngang,
không khoá i18n thô, assertion đúng; ở 375 vùng chạm thẻ việc / "Việc mới" / công tắc "Của tôi" / nút gửi bình luận >= 44px.
Ảnh: .e2e/sp3/<luồng>-<bước>-<rộng>.png ; kết quả: .e2e/sp3/result.json.
Tự dọn: xoá việc đã tạo (admin từng tổ chức, quét theo hậu tố lượt chạy), locale vi.
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
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".e2e" / "sp3"
PW = os.environ.get("SEED_PASSWORD") or "password123"
BASE = "http://127.0.0.1:8201"
API = BASE + "/bizwithagents/api"
SIZES = [(1440, 900), (375, 812)]
RUN = f"{random.randint(0, 0xFFFFF):05x}"
RAW_KEY = re.compile(
    r"^(auth|org|tenants|invite|nav|sub|verify|sa|common|action|err|mail|profile|admin|lang|theme|menu|settings|notif|chat|usage|trace|traces|agent|tasks|task|approval)"
    r"\.[A-Za-z0-9][A-Za-z0-9_.]*$"
)
VI_CHARS = re.compile("[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
CREATED: list[tuple[str, str]] = []  # (admin email của tổ chức, task id)
ADMIN = {"default": "admin@test.local", "acme": "acme-admin@test.local"}


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


def api_create(email: str, tenant: str, **body) -> dict:
    st, env = api("POST", "tasks/create", token_of(email), body)
    assert st == 200, f"tasks/create {st} {env}"
    CREATED.append((ADMIN[tenant], env["data"]["id"]))
    return env["data"]


def person_id(email: str, name: str) -> str:
    st, env = api("GET", "tasks/people", token_of(email), query={"limit": 100})
    assert st == 200, f"tasks/people {st} {env}"
    return next(p["id"] for p in env["data"] if p["name"] == name)


def cleanup_tasks():
    toks = {}
    for email in ADMIN.values():
        try:
            toks[email] = token_of(email)
        except AssertionError as e:
            print("dọn: login lỗi", e)
    for email, tid in CREATED:
        if email in toks:
            api("POST", "tasks/delete", toks[email], {"task_id": tid})
    for tok in toks.values():  # quét sót (việc tạo qua UI / trợ lý)
        st, env = api("GET", "tasks/list", tok, query={"q": RUN, "limit": 100})
        if st == 200:
            for it in env["data"]["items"]:
                api("POST", "tasks/delete", tok, {"task_id": it["id"]})


class Flow:
    def __init__(self, browser, name: str, width: int, height: int):
        self.browser, self.name, self.width, self.height = browser, name, width, height
        self.ctxs, self.console, self.http = [], [], []
        self.allowed: list[tuple[str, tuple, str]] = []
        self.problems, self.notes, self.shots = [], [], []
        self.last_page = None

    def allow(self, sub: str, statuses: tuple, why: str):
        self.allowed.append((sub, statuses, why))

    async def ctx(self, locale="vi-VN"):
        c = await self.browser.new_context(viewport={"width": self.width, "height": self.height}, locale=locale)
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
async def login_page(f: Flow, email: str):
    p = await f.page()
    await p.goto(BASE + "/login")
    await p.get_by_test_id("login-email").fill(email)
    await p.get_by_test_id("login-password").fill(PW)
    await p.get_by_test_id("login-submit").click()
    await p.wait_for_url(lambda u: "/login" not in u, timeout=15000)
    await p.wait_for_load_state("networkidle")
    return p


def mobile(f: Flow) -> bool:
    return f.width < 768


def tid_from_url(p) -> str:
    m = re.search(r"[?&]task=([^&]+)", p.url)
    assert m, f"URL không có task=: {p.url}"
    return m.group(1)


def row(p, tid: str):
    return p.get_by_test_id(f"task-{tid}")


async def goto_tasks(p, qs: str = ""):
    await p.goto(BASE + "/tasks" + qs)
    await p.get_by_test_id("tasks-page").wait_for()
    await p.wait_for_load_state("networkidle")


async def bell(p) -> int:
    el = p.get_by_test_id("notification-count")
    if await el.count() == 0:
        return 0
    t = (await el.inner_text()).strip()
    return 10 if t.startswith("9+") else int(t)


async def close_sheet(p):
    await p.keyboard.press("Escape")
    await p.get_by_test_id("task-sheet").wait_for(state="detached")


def local_input(days: int, hour: int = 17) -> str:
    return (
        (datetime.now() + timedelta(days=days))
        .replace(hour=hour, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


async def hit_height(p, sel: str, closest: str | None = None) -> dict:
    """Chiều cao vùng chạm: box + khoảng elementFromPoint (nếu closest thì tính cả phần tử cha khớp selector)."""
    return await p.evaluate(
        """([sel, closest]) => { const s = document.querySelector(sel); s.scrollIntoView({block: 'center'});
        const r = s.getBoundingClientRect(); const cx = r.left + r.width/2, cy = r.top + r.height/2;
        const inside = (e) => !!e && (e === s || s.contains(e) || (closest && e.closest(closest) === s.closest(closest)));
        const hit = (y) => inside(document.elementFromPoint(cx, y));
        let ext = 0; while (ext < 60 && hit(cy - ext - 1) && hit(cy + ext + 1)) ext++;
        const c = closest ? s.closest(closest) : null;
        return {box: r.height, boxw: r.width, hit: 2 * ext + 1, closest: c ? c.getBoundingClientRect().height : null}; }""",
        [sel, closest],
    )


async def new_task_ui(f: Flow, p, title: str, priority="high", days=1, assignee="User 2", desc="") -> str:
    await p.get_by_test_id("tasks-new").click()
    await p.get_by_test_id("task-form-title").fill(title)
    if desc:
        await p.get_by_test_id("task-form-description").fill(desc)
    await p.get_by_test_id("task-form-priority").select_option(priority)
    await p.get_by_test_id("task-form-due").fill(local_input(days))
    if assignee:
        await p.get_by_test_id("task-form-assignee").select_option(label=assignee)
    f.t_submit = time.time()
    await p.get_by_test_id("dialog-submit").click()
    await p.get_by_test_id("task-sheet").wait_for()
    await p.wait_for_function("/[?&]task=/.test(location.search)")
    return tid_from_url(p)


# ---------- K1 ----------
async def k1(f: Flow):
    m = mobile(f)
    p = await login_page(f, "user1@test.local")
    await goto_tasks(p)
    title = f"K1 viec {RUN} {f.width}"
    await p.get_by_test_id("tasks-new").click()
    await p.get_by_test_id("task-form-title").wait_for()
    await f.shot(p, "form-empty")
    await p.get_by_test_id("task-form-title").fill(title)
    await p.get_by_test_id("task-form-priority").select_option("high")
    await p.get_by_test_id("task-form-due").fill(local_input(1))
    await p.get_by_test_id("task-form-assignee").select_option(label="User 2")
    await f.shot(p, "form-filled")
    await p.get_by_test_id("dialog-submit").click()
    await p.get_by_test_id("task-sheet").wait_for()
    await p.wait_for_function("/[?&]task=/.test(location.search)")
    tid = tid_from_url(p)
    CREATED.append((ADMIN["default"], tid))
    await p.get_by_test_id("task-editor").wait_for()
    assert await p.get_by_test_id("task-priority").input_value() == "high", "ưu tiên không phải Cao"
    assert (await p.get_by_test_id("task-assignee").evaluate("e => e.options[e.selectedIndex].text")) == "User 2", (
        "người làm không phải User 2"
    )
    await f.shot(p, "detail-new")
    await close_sheet(p)
    await row(p, tid).wait_for()
    txt = await row(p, tid).inner_text()
    assert title in txt and "Cao" in txt or m, f"dòng việc thiếu dữ liệu: {txt!r}"
    await f.shot(p, "list-after-create")
    if m:
        h = (await row(p, tid).bounding_box())["height"]
        f.notes.append(f"thẻ việc cao {h:.0f}px")
        if h < 44:
            f.problems.append(f"thẻ việc cao {h:.0f}px < 44")
    # mở chi tiết, đổi trạng thái, sửa tiêu đề, bình luận
    await row(p, tid).click()
    await p.get_by_test_id("task-editor").wait_for()
    await p.get_by_test_id("task-status").select_option("doing")
    await p.wait_for_timeout(1000)
    new_title = title + " sua"
    await p.get_by_test_id("task-title").fill(new_title)
    await p.get_by_test_id("task-title").press("Enter")
    await p.wait_for_function(
        "(t) => document.querySelector('[data-testid=task-sheet]').innerText.includes(t)", arg=new_title
    )
    await p.wait_for_timeout(800)
    cmt = f"binh luan {RUN}"
    await p.get_by_test_id("task-comment-input").fill(cmt)
    if m:
        d = await hit_height(p, "[data-testid=task-comment-send]")
        f.notes.append(f"nút gửi bình luận: {d}")
        if d["box"] < 44 or d["boxw"] < 44:
            f.problems.append(f"nút gửi bình luận {d['boxw']:.0f}x{d['box']:.0f}px < 44")
    await p.get_by_test_id("task-comment-send").click()
    await p.get_by_test_id("task-comments").get_by_text(cmt).wait_for()
    assert await p.get_by_test_id("task-status").input_value() == "doing", "trạng thái không còn Đang làm"
    await f.shot(p, "detail-edited")
    await close_sheet(p)
    await p.wait_for_timeout(500)
    txt = await row(p, tid).inner_text()
    assert new_title in txt and "Đang làm" in txt, f"danh sách chưa phản ánh: {txt!r}"
    assert "1" in txt, f"thiếu số bình luận: {txt!r}"
    await f.shot(p, "list-after-edit")
    # lọc Của tôi (user1 không phải người làm)
    if m:
        d = await hit_height(p, "[data-testid=tasks-mine]", "label")
        f.notes.append(f"công tắc Của tôi: {d}")
        if (d["closest"] or d["box"]) < 44:
            f.problems.append(f"công tắc Của tôi: vùng nhãn {d['closest']}px, box {d['box']}px < 44")
    await p.get_by_test_id("tasks-mine").click()
    await p.wait_for_url(re.compile(r"mine=1"))
    await row(p, tid).wait_for(state="detached")
    await f.shot(p, "filter-mine")
    await p.get_by_test_id("tasks-mine").click()
    await row(p, tid).wait_for()
    assert "mine=1" not in p.url
    # tab Đã xong
    await p.get_by_test_id("tasks-view-done").click()
    await p.wait_for_url(re.compile(r"view=done"))
    await row(p, tid).wait_for(state="detached")
    await f.shot(p, "view-done")
    await p.get_by_test_id("tasks-view-all").click()
    await p.wait_for_url(re.compile(r"view=all"))
    await row(p, tid).wait_for()
    await p.get_by_test_id("tasks-view-open").click()
    await p.wait_for_function("!/view=/.test(location.search)")
    # tìm chữ
    await p.get_by_test_id("tasks-search").fill(RUN + " " + str(f.width))
    await p.wait_for_url(re.compile(r"q="))
    await row(p, tid).wait_for()
    await p.get_by_test_id("tasks-search").fill("khong-co-viec-nay-" + RUN)
    await row(p, tid).wait_for(state="detached")
    await f.shot(p, "search-empty")
    await p.get_by_test_id("tasks-search").fill(RUN + " " + str(f.width))
    await row(p, tid).wait_for()
    # select hạn
    await p.get_by_test_id("tasks-due").select_option("week")
    await p.wait_for_url(re.compile(r"due=week"))
    await row(p, tid).wait_for()
    await p.get_by_test_id("tasks-due").select_option("none")
    await p.wait_for_url(re.compile(r"due=none"))
    await row(p, tid).wait_for(state="detached")
    await f.shot(p, "filter-due-none")


# ---------- K2 ----------
async def k2(f: Flow):
    st = api("POST", "notifications/mark_all_read", token_of("user2@test.local"))[0]
    u2 = await login_page(f, "user2@test.local")
    await goto_tasks(u2)
    u1 = await login_page(f, "user1@test.local")
    await goto_tasks(u1)
    b0 = await bell(u2)
    f.notes.append(f"mark_all_read user2 -> {st}; chuông user2 trước = {b0}")
    title = f"K2 realtime {RUN} {f.width}"
    tid = await new_task_ui(f, u1, title)
    CREATED.append((ADMIN["default"], tid))
    t0 = f.t_submit
    await row(u2, tid).wait_for(timeout=5000)
    t_row = time.time() - t0
    await u2.wait_for_function(
        "(b) => { const e = document.querySelector('[data-testid=notification-count]'); return !!e && parseInt(e.innerText) > b }",
        arg=b0,
        timeout=5000,
    )
    t_bell = time.time() - t0
    f.notes.append(
        f"(tính từ lúc bấm Tạo) việc hiện ở user2 sau {t_row:.1f}s, chuông tăng ({b0} -> {await bell(u2)}) sau {t_bell:.1f}s, không tải lại trang"
    )
    await f.shot(u2, "user2-sees-task")
    await close_sheet(u1)
    await row(u1, tid).wait_for()
    # user2 đánh dấu Xong
    await row(u2, tid).click()
    await u2.get_by_test_id("task-editor").wait_for()
    t1 = time.time()
    await u2.get_by_test_id("task-status").select_option("done")
    await row(u1, tid).wait_for(state="detached", timeout=5000)
    f.notes.append(f"việc biến khỏi tab Đang mở của user1 sau {time.time() - t1:.1f}s")
    await f.shot(u1, "user1-open-after-done")
    await u1.get_by_test_id("tasks-view-done").click()
    await row(u1, tid).wait_for()
    await f.shot(u1, "user1-done-tab")


# ---------- K3 ----------
async def k3(f: Flow):
    f.allow("tasks/get", (404, 403, 400, 422), "việc của tổ chức khác -> 'Không tìm thấy công việc' (err 10001)")
    d = api_create("user1@test.local", "default", title=f"K3 default {RUN} {f.width}")
    ac = await login_page(f, "acme1@test.local")
    await goto_tasks(ac)
    assert await row(ac, d["id"]).count() == 0, "acme1 thấy việc của default"
    assert f"K3 default {RUN}" not in await ac.get_by_test_id("tasks-page").inner_text(), (
        "tiêu đề việc default hiện ở acme"
    )
    await f.shot(ac, "acme-list")
    await ac.goto(BASE + f"/tasks?task={d['id']}")
    await ac.get_by_text("Không tìm thấy công việc").first.wait_for()
    await f.shot(ac, "acme-foreign-task")
    mine = f"K3 acme {RUN} {f.width}"
    a = api_create("acme1@test.local", "acme", title=mine)
    await ac.goto(BASE + "/tasks")
    await row(ac, a["id"]).wait_for()
    u1 = await login_page(f, "user1@test.local")
    await goto_tasks(u1, f"?q={RUN}")
    await row(u1, d["id"]).wait_for()
    assert await row(u1, a["id"]).count() == 0 and mine not in await u1.get_by_test_id("tasks-page").inner_text(), (
        "user1 thấy việc của Acme"
    )
    await f.shot(u1, "default-list")


# ---------- K4 ----------
async def chat(p, text: str):
    await p.get_by_test_id("chat-input").fill(text)
    await p.get_by_test_id("chat-send").click()


async def k4(f: Flow):
    title = f"Chat {RUN} {f.width}"
    ch = await login_page(f, "user1@test.local")
    await ch.goto(BASE + "/assistant")
    await ch.get_by_test_id("chat-input").wait_for()
    await chat(ch, 'route:tasks call:tasks_create {"title": "' + title + '", "priority": "urgent"}')
    await (
        ch.get_by_test_id("chat-scroll")
        .get_by_text(re.compile(r"Kết quả.*" + re.escape(title) + r".*overdue", re.S))
        .first.wait_for(timeout=40000)
    )
    await f.shot(ch, "chat-created")
    st, env = api("GET", "tasks/list", token_of("user1@test.local"), query={"q": RUN, "limit": 100})
    tid = next((i["id"] for i in env["data"]["items"] if i["title"] == title), None)
    assert tid, f"trợ lý chưa tạo việc '{title}'"
    CREATED.append((ADMIN["default"], tid))
    tp = await login_page(f, "user1@test.local")
    await goto_tasks(tp, f"?q={RUN}")
    await row(tp, tid).wait_for()
    await row(tp, tid).click()
    await tp.get_by_test_id("task-editor").wait_for()
    await tp.get_by_text("Tạo bởi trợ lý").first.wait_for()
    assert await tp.get_by_test_id("task-priority").input_value() == "urgent", "ưu tiên không phải Khẩn cấp"
    await f.shot(tp, "agent-detail")
    await close_sheet(tp)
    # tasks_delete chỉ có cho vai trò có quyền xoá (admin) — member nhận "Không có tool tasks_delete"
    ch = await login_page(f, "admin@test.local")
    await ch.goto(BASE + "/assistant")
    await ch.get_by_test_id("chat-input").wait_for()
    await chat(ch, 'route:tasks call:tasks_delete {"task_id": "' + tid + '"}')
    appr = ch.locator("[data-testid^=approve-]").first
    await appr.wait_for(timeout=40000)
    await f.shot(ch, "approval-card")
    t0 = time.time()
    await appr.click()
    await row(tp, tid).wait_for(state="detached", timeout=5000)
    f.notes.append(f"việc biến khỏi danh sách sau khi Duyệt {time.time() - t0:.1f}s (không tải lại)")
    await ch.wait_for_timeout(2500)
    await f.shot(ch, "approval-done")
    await f.shot(tp, "list-after-delete")


# ---------- K5 ----------
async def k5(f: Flow):
    t = api_create("user1@test.local", "default", title=f"K5 quyen {RUN} {f.width}")
    v = await login_page(f, "user3@test.local")
    await goto_tasks(v)
    assert await v.get_by_test_id("tasks-new").count() == 0, "viewer thấy nút Tạo việc"
    await row(v, t["id"]).wait_for()
    await f.shot(v, "viewer-list")
    if mobile(f):
        assert await v.get_by_test_id("dock-add-task").count() == 0, "viewer thấy 'Việc mới' ở cụm nút nổi"
    await row(v, t["id"]).click()
    await v.get_by_test_id("task-editor").wait_for()
    for sid in ("task-title", "task-status", "task-priority", "task-due", "task-assignee", "task-description"):
        assert await v.get_by_test_id(sid).is_disabled(), f"{sid} không bị khoá cho viewer"
    assert await v.get_by_test_id("task-comment-input").count() == 0, "viewer thấy ô bình luận"
    assert await v.get_by_test_id("task-delete").count() == 0, "viewer thấy nút xoá"
    await f.shot(v, "viewer-detail")
    # viewer vẫn mở chi tiết việc này: admin xoá → data:changed → viewer tải lại → 404 "Không tìm thấy công việc" (đúng)
    f.allow("tasks/get", (404,), "viewer đang mở việc bị admin xoá → realtime tải lại → 404")
    ad = await login_page(f, "admin@test.local")
    await goto_tasks(ad, f"?task={t['id']}")
    await ad.get_by_test_id("task-delete").wait_for()
    await f.shot(ad, "admin-detail")
    await ad.get_by_test_id("task-delete").click()
    dlg = ad.locator("[role=alertdialog]").or_(ad.get_by_role("dialog").filter(has_text="Không khôi phục được"))
    await dlg.first.wait_for()
    assert "Không khôi phục được" in await dlg.first.inner_text()
    await f.shot(ad, "admin-confirm")
    await dlg.first.get_by_role("button", name="Xoá việc").click()
    await ad.get_by_text("Đã xoá việc").first.wait_for()
    await ad.get_by_test_id("task-sheet").wait_for(state="detached")
    await row(ad, t["id"]).wait_for(state="detached")
    await f.shot(ad, "admin-after-delete")


# ---------- K6 ----------
async def counts(p) -> str:
    return (await p.get_by_test_id("widget-my-tasks-counts").inner_text()).strip()


async def k6(f: Flow):
    uid = person_id("user1@test.local", "User 1")
    p = await login_page(f, "user1@test.local")
    await p.goto(BASE + "/")
    await p.get_by_test_id("widget-my-tasks-counts").wait_for()
    c0 = await counts(p)
    await f.shot(p, "widget-before")
    due = (datetime.now() - timedelta(days=2)).astimezone().isoformat()
    t = api_create("user1@test.local", "default", title=f"K6 qua han {RUN} {f.width}", assignee_id=uid, due_at=due)
    t0 = time.time()
    rt = True
    try:
        await p.get_by_test_id(f"widget-task-{t['id']}").wait_for(timeout=6000)
    except Exception:  # noqa: BLE001
        rt = False
        await p.reload()
        await p.get_by_test_id(f"widget-task-{t['id']}").wait_for()
    c1 = await counts(p)
    f.notes.append(
        f"widget cập nhật {'realtime' if rt else 'CHỈ sau khi tải lại'} ({time.time() - t0:.1f}s): '{c0}' -> '{c1}'"
    )
    if not rt:
        f.problems.append("widget không cập nhật realtime khi có việc mới giao cho user1 (chỉ sau tải lại)")
    assert c0 != c1 and "quá hạn" in c1, f"số đếm không đổi: {c0!r} -> {c1!r}"
    await f.shot(p, "widget-after")
    if mobile(f):
        btn = p.get_by_test_id("dock-add-task")
        d = await hit_height(p, "[data-testid=dock-add-task]")
        f.notes.append(f"nút 'Việc mới' (dock): {d}")
        if d["box"] < 44 or d["boxw"] < 44:
            f.problems.append(f"nút Việc mới {d['boxw']:.0f}x{d['box']:.0f}px < 44")
        await btn.click()
        await p.get_by_test_id("task-form-title").fill(f"K6 nhanh {RUN}")
        await f.shot(p, "quick-add-dialog")
        await p.get_by_test_id("dialog-submit").click()
        await p.get_by_text("Đã tạo việc").first.wait_for()
        await f.shot(p, "quick-add-toast")
    else:
        f.notes.append("dock 'Việc mới' chỉ có ở điện thoại — bỏ qua ở desktop")
        assert await p.get_by_test_id("mobile-dock").is_hidden(), "cụm nút nổi lộ ở desktop"


# ---------- K7 ----------
async def set_lang(f: Flow, p, lang: str):
    if mobile(f):
        await p.get_by_test_id("user-menu").click()
        await p.get_by_role("menuitem").filter(has_text=re.compile(rf"^\s*{lang.upper()}")).click()
    else:
        await p.goto(BASE + "/profile")
        await p.get_by_test_id(f"lang-{lang}").click()
    await p.wait_for_timeout(1000)


async def k7(f: Flow):
    tok = token_of("user1@test.local")
    try:
        t = api_create(
            "user1@test.local",
            "default",
            title=f"K7 ui {RUN} {f.width}",
            description="mo ta test",
            priority="high",
            assignee_id=person_id("user1@test.local", "User 2"),
            due_at=(datetime.now() + timedelta(days=1)).astimezone().isoformat(),
        )
        p = await login_page(f, "user1@test.local")
        await goto_tasks(p)
        await row(p, t["id"]).wait_for()
        await f.shot(p, "list")
        await p.get_by_test_id("tasks-new").click()
        await p.get_by_test_id("task-form-title").wait_for()
        await f.shot(p, "create-dialog")
        await p.keyboard.press("Escape")
        await row(p, t["id"]).click()
        await p.get_by_test_id("task-editor").wait_for()
        await f.shot(p, "detail")
        await close_sheet(p)
        await p.goto(BASE + "/")
        await p.get_by_test_id("widget-my-tasks-counts").wait_for()
        await f.shot(p, "home-widget")
        await set_lang(f, p, "en")
        await goto_tasks(p)
        await row(p, t["id"]).wait_for()
        await f.shot(p, "en-list")
        body = await p.get_by_test_id("tasks-page").inner_text()
        vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
        if vi:
            f.problems.append(f"[en-list] còn chuỗi tiếng Việt: {vi[:8]}")
        await p.get_by_test_id("tasks-new").click()
        await p.get_by_test_id("task-form-title").wait_for()
        await f.shot(p, "en-create-dialog")
        body = await p.get_by_role("dialog").first.inner_text()
        vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
        if vi:
            f.problems.append(f"[en-create-dialog] còn chuỗi tiếng Việt: {vi[:8]}")
        await p.keyboard.press("Escape")
        await row(p, t["id"]).click()
        await p.get_by_test_id("task-editor").wait_for()
        await p.get_by_test_id("task-comment-input").fill("hello")
        await p.get_by_test_id("task-comment-send").click()
        await p.get_by_test_id("task-comments").wait_for()
        await p.wait_for_timeout(600)
        await f.shot(p, "en-detail")
        body = await p.get_by_test_id("task-sheet").inner_text()
        vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
        if vi:
            f.problems.append(f"[en-detail] còn chuỗi tiếng Việt: {vi[:8]}")
        await close_sheet(p)
        await p.goto(BASE + "/")
        await p.get_by_test_id("widget-my-tasks-counts").wait_for()
        await f.shot(p, "en-home-widget")
        body = await p.get_by_test_id("widget-my-tasks").inner_text()
        vi = sorted(set(re.findall(r"\S*" + VI_CHARS.pattern + r"\S*", body, re.I)))
        if vi:
            f.problems.append(f"[en-widget] còn chuỗi tiếng Việt: {vi[:8]}")
    finally:
        api("POST", "auth/update_me", tok, {"locale": "vi"})


FLOWS = {"K1": k1, "K2": k2, "K3": k3, "K4": k4, "K5": k5, "K6": k6, "K7": k7}


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
    print("RUN =", RUN)
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
                                f.shots.append(f".e2e/sp3/{name}-FAIL-{width}.png (url={f.last_page.url})")
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
            try:
                cleanup_tasks()
                api("POST", "auth/update_me", token_of("user1@test.local"), {"locale": "vi"})
            except Exception as e:  # noqa: BLE001
                print("dọn lỗi", e)
    (OUT / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("tổng:", sum(r["pass"] for r in results), "/", len(results), "PASS")


if __name__ == "__main__":
    asyncio.run(main())
