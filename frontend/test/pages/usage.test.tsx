// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UsagePage from "@/pages/sa/UsagePage";
import { compact, pct, usd } from "@/pages/sa/usage/filters";
import { buckets } from "@/pages/sa/usage/UsageChart";

import { me, tenant } from "../fixtures";
import { renderPage, setDesktop, Where } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/admin/api", () => ({ adminApi: { listUsers: vi.fn() } }));
vi.mock("@/features/tenant/api", () => ({ tenantsApi: { list: vi.fn() } }));
vi.mock("@/features/agent/api", () => ({
  traceApi: { list: vi.fn(), get: vi.fn(), raw: vi.fn(), usage: vi.fn(), usageErrors: vi.fn() },
  studioApi: { agents: vi.fn(), models: vi.fn(), providers: vi.fn() },
  credentialsApi: { list: vi.fn() },
  agentApi: { sessions: vi.fn() },
}));
const { traceApi, studioApi, credentialsApi } = await import("@/features/agent/api");
const { adminApi } = await import("@/features/admin/api");
const { tenantsApi } = await import("@/features/tenant/api");

const SA = me({ is_superadmin: true, permissions: [] });
type Row = Record<string, unknown>;
const row = (key: string, name: string | null, over: Row = {}): Row => ({
  key, name, sub: null, requests: 4, input_tokens: 1200, output_tokens: 300, cache_read_tokens: 600, cache_write_tokens: 200,
  cost: 0.0123, errors: 0, errors_rate: 0, errors_auth: 0, errors_server: 0, errors_other: 0, latency_avg_ms: 850, prices: null, ...over,
}); // fmt: skip
const TOTAL = row("total", null, { requests: 10, cost: 0.1234, errors: 2, latency_avg_ms: 1500 });
const FILTERED_TOTAL = row("total", null, { requests: 3, cost: 0.0042, errors: 0, latency_avg_ms: 300 });

const BY: Record<string, Row[]> = {
  provider: [row("p1", "OpenAI", { sub: "openai" })],
  model: [row("m1", "gpt-x", { sub: "gpt-x-2026", cost: 0.1, errors: 2, prices: { input: "3", output: "15", cache_read: "0.3", cache_write: "3.75" } }), row("m2", "claude-y", { cost: 0.02 })],
  agent: [row("a1", "Trợ lý", { sub: "assistant" })],
  purpose: [row("agent", null, { cost: 0.1 }), row("router", null, { cost: 0.0234 })],
  tenant: [row("t2", "Acme", { sub: "acme", cost: 0.09 }), row("none", null)],
  user: [row("u1", "An", { sub: "an@x.io" })],
  key: [row("c1", "key-chính", { sub: "sk-…1234" }), row("none", null)],
};

const summary = (group_by: string, rows: Row[], total: Row | null, enabled = true) => ({ enabled, since: "2026-09-13T00:00:00Z", until: "2026-10-12T00:00:00Z", group_by, tz: "Asia/Ho_Chi_Minh", rows, total });
const errorsPage = (items: Row[], total = items.length) => ({ enabled: true, items, total, limit: 10, offset: 0 });
const err = (id: string, over: Row = {}): Row => ({
  id, at: "2026-10-12T10:00:00Z", kind: "rate", error: "429 Rate limit reached", run_id: `run-${id}`, purpose: "router", agent: "Trợ lý", model: "gpt-x",
  model_code: "gpt-x-2026", provider_kind: "openai", user: "An", key: "key-chính", latency_ms: 120, ...over,
}); // fmt: skip

function mockUsage(opts: { enabled?: boolean } = {}) {
  vi.mocked(traceApi.usage).mockImplementation((async (q: Record<string, unknown>) => {
    const g = String(q?.group_by ?? "model");
    if (opts.enabled === false) return summary(g, [], null, false);
    const filtered = Object.keys(q).some((k) => k.endsWith("_id") || k === "purpose");
    const total = filtered ? FILTERED_TOTAL : TOTAL;
    if (g === "day") {
      const keys = buckets(String(q.since), 30);
      return summary(g, [row(keys[0] as string, null, { cost: 0.05, requests: 7, errors: 1 }), row(keys[keys.length - 1] as string, null, { cost: 0.1, requests: 3, errors: 0 })], total);
    }
    return summary(g, BY[g] ?? [], total);
  }) as never);
}

const mount = (route = "/sa/usage") =>
  renderPage(
    <>
      <UsagePage />
      <Where />
    </>,
    { path: "/sa/usage", route, user: SA },
  );
const lastUsage = (g: string) => vi.mocked(traceApi.usage).mock.calls.map((c) => c[0] as Record<string, unknown>).filter((q) => q.group_by === g).at(-1);
const where = () => screen.getByTestId("where").textContent ?? "";

beforeEach(() => {
  vi.clearAllMocks();
  setDesktop(true);
  mockUsage();
  vi.mocked(traceApi.usageErrors).mockResolvedValue(errorsPage([]) as never);
  vi.mocked(adminApi.listUsers).mockResolvedValue({ items: [{ id: "u1", name: "An", email: "an@x.io" }], total: 1 } as never);
  vi.mocked(tenantsApi.list).mockResolvedValue({ items: [tenant({ id: "t2", name: "Acme", slug: "acme" })], total: 1, limit: 100, offset: 0 } as never);
  vi.mocked(studioApi.agents).mockResolvedValue([{ id: "a1", name: "Trợ lý" }] as never);
  vi.mocked(studioApi.models).mockResolvedValue([{ id: "m1", name: "gpt-x", model_id: "gpt-x-2026" }] as never);
  vi.mocked(studioApi.providers).mockResolvedValue([{ id: "p1", name: "OpenAI" }] as never);
  vi.mocked(credentialsApi.list).mockResolvedValue({ items: [{ id: "c1", name: "key-chính", masked_hint: "sk-…1234" }], total: 1 } as never);
});

describe("helper của trang Usage", () => {
  it("buckets: ngày liên tục (có ngày trống), 'Hôm nay' theo giờ", () => {
    const days = buckets(new Date(2026, 9, 6, 0, 0).toISOString(), 7, new Date(2026, 9, 12, 15, 30));
    expect(days).toEqual(["2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12"]);
    const hours = buckets(new Date(2026, 9, 12, 0, 0).toISOString(), 1, new Date(2026, 9, 12, 3, 30));
    expect(hours).toEqual(["2026-10-12 00:00", "2026-10-12 01:00", "2026-10-12 02:00", "2026-10-12 03:00"]);
    expect(buckets(new Date(2026, 8, 29).toISOString(), 7, new Date(2026, 9, 2))).toEqual(["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]);
  });

  it("usd / compact / pct", () => {
    expect(usd(0.0123456)).toBe("$0.0123");
    expect(usd("1.5")).toBe("$1.5000");
    expect(usd(null)).toBe("$0.0000");
    expect(compact(null)).toBe("—");
    expect(compact(1234)).toMatch(/^1[.,\s ]?234$/);
    expect(compact(12_345)).toMatch(/12[.,]3\s?(N|k)|12[.,]3K/i);
    expect(pct(1, 4)).toMatch(/^25$/);
    expect(pct(0, 0)).toBe("0");
  });
});

describe("UsagePage — KPI, bộ lọc trên URL, bảng, biểu đồ, lỗi", () => {
  it("6 thẻ KPI lấy từ tổng của kết quả (gộp theo nơi gọi)", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("kpi-cost").textContent).toContain("$0.1234"));
    expect(screen.getByTestId("kpi-requests").textContent).toContain("10");
    expect(screen.getByTestId("kpi-tokens").textContent).toMatch(/2[.,\s ]?000 \/ 300/); // vào = input + cache read + cache write
    expect(screen.getByTestId("kpi-cache").textContent).toContain("600");
    expect(screen.getByTestId("kpi-cache").textContent).toContain("30%");
    expect(screen.getByTestId("kpi-errors").textContent).toContain("20%"); // 2 / 10
    expect(screen.getByTestId("kpi-latency").textContent).toMatch(/1[.,\s ]?500 ms/);
    expect(lastUsage("purpose")).toBeTruthy();
  });

  it("không có dữ liệu → KPI về 0 / —", async () => {
    vi.mocked(traceApi.usage).mockResolvedValue(summary("purpose", [], null) as never);
    mount();
    await waitFor(() => expect(traceApi.usage).toHaveBeenCalled());
    expect(screen.getByTestId("kpi-cost").textContent).toContain("$0.0000");
    expect(screen.getByTestId("kpi-latency").textContent).toContain("—");
  });

  it("bộ lọc đọc từ URL: gửi đúng query, ô chọn / tab / chỉ số phản ánh URL", async () => {
    mount("/sa/usage?range=7&by=agent&metric=requests&user_id=u1&purpose=router&session_id=sess-1234567890");
    await waitFor(() => expect(lastUsage("agent")).toBeTruthy());
    const q = lastUsage("agent") as Record<string, string>;
    expect(q.user_id).toBe("u1");
    expect(q.purpose).toBe("router");
    expect(q.session_id).toBe("sess-1234567890");
    const days = Math.round((Date.now() - new Date(q.since as string).getTime()) / 86_400_000);
    expect(days).toBeGreaterThanOrEqual(6);
    expect(days).toBeLessThanOrEqual(7);
    expect((screen.getByTestId("usage-range") as HTMLSelectElement).value).toBe("7");
    expect((screen.getByTestId("usage-metric") as HTMLSelectElement).value).toBe("requests");
    expect(screen.getByTestId("usage-tab-agent").getAttribute("aria-selected")).toBe("true");
    expect((screen.getByTestId("usage-filter-purpose") as HTMLSelectElement).value).toBe("router");
    await waitFor(() => expect((screen.getByTestId("usage-filter-user_id") as HTMLSelectElement).value).toBe("u1"));
    expect(screen.getByTestId("usage-chip-session").textContent).toContain("sess-123");
  });

  it("giá trị URL sai (range / by / metric) rơi về mặc định 30 ngày · model · chi phí", async () => {
    mount("/sa/usage?range=999&by=zzz&metric=nope");
    await waitFor(() => expect(lastUsage("model")).toBeTruthy());
    expect((screen.getByTestId("usage-range") as HTMLSelectElement).value).toBe("30");
    expect((screen.getByTestId("usage-metric") as HTMLSelectElement).value).toBe("cost");
    expect(screen.getByTestId("usage-tab-model").getAttribute("aria-selected")).toBe("true");
  });

  it("đổi bộ lọc ghi vào URL và gọi lại API; xoá lọc dọn URL, giữ range / by", async () => {
    mount("/sa/usage?by=agent");
    const u = userEvent.setup();
    await u.selectOptions(await screen.findByTestId("usage-range"), "7");
    await waitFor(() => expect(where()).toContain("range=7"));
    await waitFor(() => expect(screen.getByRole("option", { name: "An" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("usage-filter-user_id"), "u1");
    await u.selectOptions(screen.getByTestId("usage-filter-purpose"), "agent");
    await waitFor(() => expect(where()).toContain("user_id=u1"));
    expect(where()).toContain("purpose=agent");
    await waitFor(() => expect((lastUsage("agent") as Record<string, string>).user_id).toBe("u1"));
    await waitFor(() => expect(screen.getByTestId("kpi-cost").textContent).toContain("$0.0042")); // KPI đổi theo lọc
    await u.click(screen.getByTestId("usage-clear"));
    await waitFor(() => expect(where()).not.toContain("user_id"));
    expect(where()).not.toContain("purpose=");
    expect(where()).toContain("range=7");
    expect(where()).toContain("by=agent");
    await waitFor(() => expect(screen.getByTestId("kpi-cost").textContent).toContain("$0.1234"));
    expect(screen.queryByTestId("usage-clear")).toBeNull();
  });

  it("tab chiều: mỗi tab gọi group_by tương ứng và hiện dòng của nó", async () => {
    mount();
    const u = userEvent.setup();
    for (const [g, key, text] of [["provider", "p1", "OpenAI"], ["model", "m1", "gpt-x"], ["agent", "a1", "Trợ lý"], ["purpose", "router", "Router"], ["user", "u1", "An"], ["key", "c1", "key-chính"]] as const) {
      await u.click(screen.getByTestId(`usage-tab-${g}`));
      await waitFor(() => expect(where()).toContain(`by=${g}`));
      expect((await screen.findByTestId(`usage-row-${key}`)).textContent).toContain(text);
      expect(screen.getByTestId(`usage-tab-${g}`).getAttribute("aria-selected")).toBe("true");
    }
    expect(screen.getByTestId("usage-row-none").textContent).not.toBe(""); // dòng "(không có key)" ở tab key
    await u.click(screen.getByTestId("usage-tab-key"));
    expect(screen.getByTestId("usage-row-none").textContent).toContain("không có key");
  });

  it("tab model hiện giá / 1M token; dòng lỗi hiện số lỗi và %", async () => {
    mount("/sa/usage?by=model");
    const r = await screen.findByTestId("usage-row-m1");
    expect(r.textContent).toContain("$3 · $15 · $0.3");
    expect(r.textContent).toContain("2 (50%)");
    expect(r.textContent).toContain("gpt-x-2026");
    expect(r.textContent).toContain("$0.1000");
    expect(screen.getByTestId("usage-row-m2").textContent).toContain("—"); // chưa có giá
  });

  it("bấm dòng = lọc sâu theo chiều đó (URL + KPI đổi); bấm lại dòng đang lọc không làm gì; 'none' không lọc được", async () => {
    mount("/sa/usage?by=model");
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("usage-row-m1"));
    await waitFor(() => expect(where()).toContain("model_id=m1"));
    await waitFor(() => expect(screen.getByTestId("kpi-cost").textContent).toContain("$0.0042"));
    expect((lastUsage("model") as Record<string, string>).model_id).toBe("m1");
    await u.click(screen.getByTestId("usage-tab-agent"));
    await u.click(await screen.findByTestId("usage-row-a1"));
    await waitFor(() => expect(where()).toContain("agent_id=a1"));
    expect(where()).toContain("model_id=m1");
    await u.click(screen.getByTestId("usage-tab-key"));
    await u.click(await screen.findByTestId("usage-row-none"));
    expect(where()).not.toContain("credential_id");
    await u.click(screen.getByTestId("usage-tab-purpose"));
    await u.click(await screen.findByTestId("usage-row-router"));
    await waitFor(() => expect(where()).toContain("purpose=router"));
    await u.click(screen.getByTestId("usage-tab-user"));
    await u.click(await screen.findByTestId("usage-row-u1"));
    await waitFor(() => expect(where()).toContain("user_id=u1"));
  });

  it("điện thoại: dòng là thẻ, bấm thẻ cũng lọc sâu", async () => {
    setDesktop(false);
    mount("/sa/usage?by=agent");
    const card = await screen.findByTestId("usage-row-a1");
    expect(card.getAttribute("role")).toBe("button");
    expect(screen.queryByRole("table")).toBeNull();
    await userEvent.setup().click(card);
    await waitFor(() => expect(where()).toContain("agent_id=a1"));
  });

  it("dòng user có link 'Xem trace' sang /sa/traces?user_id=…, bấm link không lọc sâu", async () => {
    mount("/sa/usage?by=user");
    const link = await screen.findByTestId("usage-traces-u1");
    expect(link.getAttribute("href")).toBe("/sa/traces?user_id=u1");
    await userEvent.setup().click(link);
    await waitFor(() => expect(where()).toBe("/sa/traces?user_id=u1"));
  });

  it("biểu đồ: đủ cột cho từng ngày (cột trống = 0), đổi chỉ số đổi giá trị, bấm cột hiện giá trị", async () => {
    mount("/sa/usage?range=7");
    await waitFor(() => expect(lastUsage("day")).toBeTruthy());
    const n = buckets((lastUsage("day") as Record<string, string>).since as string, 7).length;
    await waitFor(() => expect(screen.getAllByTestId(/^usage-bars-bar-\d+$/)).toHaveLength(n));
    expect(n).toBeGreaterThanOrEqual(7);
    expect(screen.getByTestId("usage-bars-value").textContent).toContain("max $0.1000");
    const u = userEvent.setup();
    fireEvent.click(screen.getByTestId(`usage-bars-bar-${n - 1}`)); // chạm (không hover)
    expect(screen.getByTestId("usage-bars-value").textContent).toContain(": $0.1000");
    await u.hover(screen.getByTestId("usage-bars-bar-1"));
    expect(screen.getByTestId("usage-bars-value").textContent).toContain(": $0.0000");
    await u.selectOptions(screen.getByTestId("usage-metric"), "requests");
    await waitFor(() => expect(where()).toContain("metric=requests"));
    expect(screen.getByTestId("usage-bars-value").textContent).toBe("max 7");
    await u.selectOptions(screen.getByTestId("usage-metric"), "errors");
    expect(screen.getByTestId("usage-bars-value").textContent).toBe("max 1");
    await u.selectOptions(screen.getByTestId("usage-metric"), "tokens");
    expect(screen.getByTestId("usage-bars-value").textContent).toMatch(/^max 2[.,\s ]?300$/);
  });

  it("'Hôm nay' dùng group_by=hour", async () => {
    mount("/sa/usage?range=1");
    await waitFor(() => expect(lastUsage("hour")).toBeTruthy());
    expect(lastUsage("day")).toBeUndefined();
  });

  it("danh sách lỗi: loại, model · agent · nơi gọi, user · key, link tới trace; lọc loại gọi lại API", async () => {
    vi.mocked(traceApi.usageErrors).mockResolvedValue(errorsPage([err("e1"), err("e2", { kind: "auth", run_id: "", error: null })], 25) as never);
    mount("/sa/usage?user_id=u1");
    const first = await screen.findByTestId("llm-error-e1");
    expect(first.textContent).toContain("Quá hạn mức (429)");
    expect(first.textContent).toContain("gpt-x · Trợ lý · Router");
    expect(first.textContent).toContain("An · key-chính · 120 ms");
    expect(first.textContent).toContain("429 Rate limit reached");
    expect(within(first).getByRole("link").getAttribute("href")).toBe("/sa/traces/run-e1");
    expect(screen.getByTestId("llm-error-e2").textContent).toContain("Key bị từ chối");
    expect(within(screen.getByTestId("llm-error-e2")).queryByRole("link")).toBeNull();
    expect(vi.mocked(traceApi.usageErrors).mock.calls.at(-1)?.[0]).toMatchObject({ user_id: "u1", limit: 10, offset: 0 });
    await userEvent.setup().selectOptions(screen.getByTestId("llm-errors-kind"), "server");
    await waitFor(() => expect(vi.mocked(traceApi.usageErrors).mock.calls.at(-1)?.[0]).toMatchObject({ kind: "server", offset: 0 }));
    await userEvent.setup().click(screen.getByRole("button", { name: "Trang sau" }));
    await waitFor(() => expect(vi.mocked(traceApi.usageErrors).mock.calls.at(-1)?.[0]).toMatchObject({ offset: 10 }));
  });

  it("không có lỗi → trạng thái rỗng", async () => {
    mount();
    const box = await screen.findByTestId("llm-errors");
    await waitFor(() => expect(box.textContent).toContain("Không có lỗi gọi LLM"));
  });

  it("Mongo tắt (enabled=false) → banner usage-disabled, không có bảng / biểu đồ", async () => {
    mockUsage({ enabled: false });
    mount();
    expect(await screen.findByTestId("usage-disabled")).toBeTruthy();
    expect(screen.queryByTestId("usage-page")).toBeNull();
    expect(screen.queryByTestId("usage-chart")).toBeNull();
  });
});

describe("Usage theo tổ chức (D22)", () => {
  it("tab Tổ chức gộp theo tenant (tên + slug); chọn tổ chức → lọc tenant_id", async () => {
    mount("/sa/usage?by=tenant");
    await waitFor(() => expect(lastUsage("tenant")).toBeTruthy());
    expect(screen.getByTestId("usage-tab-tenant").getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("Acme")).toBeTruthy();
    const u = userEvent.setup();
    await waitFor(() => expect(within(screen.getByTestId("usage-filter-tenant_id")).getByRole("option", { name: "Acme" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("usage-filter-tenant_id"), "t2");
    await waitFor(() => expect(lastUsage("tenant")).toMatchObject({ tenant_id: "t2" }));
    expect(where()).toContain("tenant_id=t2");
  });
});
