// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TraceDetail from "@/pages/sa/TraceDetail";
import TracesPage from "@/pages/sa/TracesPage";

import { me } from "../fixtures";
import { renderPage, setDesktop, Where } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/admin/api", () => ({ adminApi: { listUsers: vi.fn() } }));
vi.mock("@/features/tenant/api", () => ({ tenantsApi: { list: vi.fn() } }));
vi.mock("@/features/agent/api", () => ({
  traceApi: { list: vi.fn(), get: vi.fn(), raw: vi.fn(), usage: vi.fn() },
  studioApi: { agents: vi.fn(), models: vi.fn() },
  agentApi: { sessions: vi.fn() },
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), call: vi.fn() }));
const { traceApi, studioApi, agentApi } = await import("@/features/agent/api");
const { adminApi } = await import("@/features/admin/api");
const { tenantsApi } = await import("@/features/tenant/api");
const { call } = await import("@/lib/api");

const SA = me({ is_superadmin: true, permissions: [] });
const base = { agent_id: "ag1", session_id: "s1", user_id: "u1", expire_at: "2026-11-01T00:00:00Z", run_id: "r1", cid: null, error: null };
const t0 = "2026-10-12T10:00:00Z";
const t1 = "2026-10-12T10:00:02Z";

const runSpan = { ...base, id: "sp-run", kind: "run", name: "Trợ lý", parent_id: null, seq: 1, start: t0, end: t1, status: "ok", input: { user: { name: "An" }, model: { name: "gpt-x" } }, output: {}, usage: { input: 100, output: 20 } };
const llmSpan = {
  ...base, id: "sp-llm", kind: "llm", name: "gpt-x", parent_id: "sp-run", seq: 2, start: t0, end: t1, status: "ok",
  input: { messages: [{ role: "user", content: "chào" }] }, output: { text: "xin chào" }, usage: { input: 100, output: 20 },
  credential_id: "c1", masked_hint: "sk-…abcd", ttft_ms: 250, raw_ids: ["raw1"],
}; // fmt: skip
const toolSpan = { ...base, id: "sp-tool", kind: "tool", name: "wallet_list", parent_id: "sp-llm", seq: 3, start: t0, end: t1, status: "ok", input: { limit: 5 }, output: { ok: true } };

const openList = (route = "/sa/traces") =>
  renderPage(
    <>
      <TracesPage />
      <Where />
    </>,
    { path: "/sa/traces", route, user: SA },
  );
const openDetail = () =>
  renderPage(<TraceDetail />, { path: "/sa/traces/:id", route: "/sa/traces/r1", user: SA });
const page = (items: unknown[], names: Record<string, string> = {}, total = items.length) => ({ enabled: true, items, total, limit: 20, offset: 0, names });
const lastList = () => vi.mocked(traceApi.list).mock.calls.at(-1)?.[0] as Record<string, unknown>;
const where = () => screen.getByTestId("where").textContent ?? "";
const dayIso = (d: string, plus = 0) => {
  const x = new Date(`${d}T00:00:00`);
  x.setDate(x.getDate() + plus);
  return x.toISOString();
};

const run2 = {
  ...runSpan, id: "r2", run_id: "r2", user_id: "u2", session_id: "s2", status: "error", error: "Lỗi 6011: hết key",
  agents: ["personal", "report"], models: ["gpt-x", "claude-y"], cost: 0.0123, llm_errors: 2,
}; // fmt: skip

beforeEach(() => {
  vi.clearAllMocks();
  setDesktop(false);
  vi.mocked(adminApi.listUsers).mockResolvedValue({ items: [{ id: "u1", name: "An", email: "an@x.io" }, { id: "u2", name: "Bình", email: "b@x.io" }], total: 2 } as never);
  vi.mocked(tenantsApi.list).mockResolvedValue({ items: [{ id: "t2", name: "Acme" }], total: 1, limit: 100, offset: 0 } as never);
  vi.mocked(studioApi.agents).mockResolvedValue([{ id: "ag1", name: "Trợ lý" }] as never);
  vi.mocked(studioApi.models).mockResolvedValue([{ id: "m1", name: "GPT", model_id: "gpt-x" }, { id: "m2", name: "GPT2", model_id: "gpt-x" }, { id: "m3", name: "Claude", model_id: "claude-y" }] as never);
  vi.mocked(call).mockResolvedValue({ items: [{ id: "g1", name: "Nhà mình" }, { id: "g2", name: "Bạn bè" }], total: 2 } as never);
  vi.mocked(agentApi.sessions).mockResolvedValue({ items: [{ id: "s1", title: "Chat chi tiêu" }, { id: "s9", title: null }], total: 2 } as never);
  vi.mocked(traceApi.list).mockResolvedValue(page([]) as never);
});

describe("TracesPage", () => {
  it("danh sách lượt: chuỗi chuyên gia, user, model, token, chi phí, badge lỗi LLM; Mongo tắt → banner", async () => {
    vi.mocked(traceApi.list).mockResolvedValue(
      page([run2, runSpan], { "user:u2": "Bình", "agent:ag1": "Trợ lý", "user:u1": "An" }) as never,
    );
    const first = openList();
    const item = await screen.findByTestId("trace-r2");
    expect(item.textContent).toContain("personal → report");
    expect(item.textContent).toContain("Bình");
    expect(item.textContent).toContain("gpt-x, claude-y");
    expect(item.textContent).toContain("120 tok");
    expect(item.textContent).toContain("$0.0123");
    expect(item.textContent).toContain("2 lỗi LLM");
    expect(item.textContent).toContain("Lỗi 6011: hết key");
    expect(screen.getByTestId("trace-open-r2").getAttribute("href")).toBe("/sa/traces/r2");
    const legacy = screen.getByTestId("trace-r1"); // lượt cũ: không có agents / models / cost
    expect(legacy.textContent).toContain("Trợ lý");
    expect(legacy.textContent).toContain("gpt-x");
    expect(legacy.textContent).not.toContain("$");
    expect(screen.getByTestId("trace-count").textContent).toContain("2");
    first.unmount();

    vi.mocked(traceApi.list).mockResolvedValue({ enabled: false, items: [], total: 0, limit: 20, offset: 0, names: {} } as never);
    openList();
    expect(await screen.findByTestId("log-disabled-banner")).toBeTruthy();
  });

  it("không có lượt nào → trạng thái rỗng", async () => {
    openList();
    await waitFor(() => expect(screen.getByText("Chưa có lượt nào")).toBeTruthy());
  });

  it("bộ lọc đọc từ URL → đúng query API (has_error / model / ngày → khoảng thời gian)", async () => {
    openList("/sa/traces?user_id=u1&session_id=s1&agent_id=ag1&status=error&has_error=1&model=gpt-x&since=2026-10-01&until=2026-10-02");
    await waitFor(() => expect(lastList()).toBeTruthy());
    expect(lastList()).toEqual({
      user_id: "u1", session_id: "s1", agent_id: "ag1", status: "error", has_error: true, model: "gpt-x",
      since: dayIso("2026-10-01"), until: dayIso("2026-10-02", 1), limit: 20, offset: 0,
    }); // fmt: skip
    expect((screen.getByTestId("trace-since") as HTMLInputElement).value).toBe("2026-10-01");
    expect(screen.getByTestId("trace-has-error").getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect((screen.getByTestId("trace-user") as HTMLSelectElement).value).toBe("u1"));
  });

  it("lọc theo tổ chức + lượt hiện tên tổ chức cạnh user (D22)", async () => {
    vi.mocked(traceApi.list).mockResolvedValue(page([{ ...run2, tenant_id: "t2" }], { "user:u2": "Bình", "tenant:t2": "Acme" }) as never);
    openList();
    expect((await screen.findByTestId("trace-r2")).textContent).toContain("Bình (Acme)");
    const u = userEvent.setup();
    await waitFor(() => expect(within(screen.getByTestId("trace-tenant")).getByRole("option", { name: "Acme" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("trace-tenant"), "t2");
    await waitFor(() => expect(lastList()).toMatchObject({ tenant_id: "t2" }));
    expect(where()).toContain("tenant_id=t2");
  });

  it("trạng thái lạ và tham số lạ trên URL bị bỏ", async () => {
    openList("/sa/traces?owner=personal&status=zzz");
    await waitFor(() => expect(lastList()).toEqual({ limit: 20, offset: 0 }));
  });

  it("chọn bộ lọc ghi vào URL và gọi lại API: user, agent, trạng thái, model, ngày, có lỗi", async () => {
    openList();
    const u = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("option", { name: "An" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("trace-user"), "u1");
    await waitFor(() => expect(lastList()).toMatchObject({ user_id: "u1" }));
    await u.selectOptions(screen.getByTestId("trace-agent"), "ag1");
    await u.selectOptions(screen.getByTestId("trace-status"), "error");
    await waitFor(() => expect(lastList()).toMatchObject({ user_id: "u1", agent_id: "ag1", status: "error", limit: 20, offset: 0 }));
    const codes = within(screen.getByTestId("trace-model")).getAllByRole("option").map((o) => o.textContent);
    expect(codes).toEqual(["Mọi model", "claude-y", "gpt-x"]); // mã model trùng gộp một, sắp xếp
    await u.selectOptions(screen.getByTestId("trace-model"), "claude-y");
    await u.click(screen.getByTestId("trace-has-error"));
    fireEvent.change(screen.getByTestId("trace-since"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByTestId("trace-until"), { target: { value: "2026-10-06" } });
    await waitFor(() => expect(lastList()).toMatchObject({ model: "claude-y", has_error: true, since: dayIso("2026-10-05"), until: dayIso("2026-10-06", 1) }));
    for (const k of ["user_id=u1", "agent_id=ag1", "status=error", "model=claude-y", "has_error=1", "since=2026-10-05", "until=2026-10-06"]) expect(where()).toContain(k);
  });

  it("phiên chỉ chọn được sau khi chọn user; đổi user thì bỏ phiên", async () => {
    openList();
    const u = userEvent.setup();
    const session = screen.getByTestId("trace-session") as HTMLSelectElement;
    expect(session.disabled).toBe(true);
    expect(agentApi.sessions).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("option", { name: "An" })).toBeTruthy());
    await u.selectOptions(screen.getByTestId("trace-user"), "u1");
    await waitFor(() => expect(session.disabled).toBe(false));
    expect(agentApi.sessions).toHaveBeenCalledWith({ user_id: "u1", limit: 100 });
    await waitFor(() => expect(screen.getByRole("option", { name: "Chat chi tiêu" })).toBeTruthy());
    await u.selectOptions(session, "s1");
    await waitFor(() => expect(lastList()).toMatchObject({ user_id: "u1", session_id: "s1" }));
    await u.selectOptions(screen.getByTestId("trace-user"), "u2");
    await waitFor(() => expect(where()).not.toContain("session_id"));
    expect(lastList()).not.toHaveProperty("session_id");
  });

  it("nút lọc nhanh trên một lượt: 'Lọc user này' và 'Lọc phiên này'; 'Bỏ lọc' xoá hết", async () => {
    vi.mocked(traceApi.list).mockResolvedValue(page([run2], { "user:u2": "Bình" }) as never);
    openList();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("trace-by-user-r2"));
    await waitFor(() => expect(where()).toBe("/sa/traces?user_id=u2"));
    await u.click(screen.getByTestId("trace-by-session-r2"));
    await waitFor(() => expect(where()).toContain("session_id=s2"));
    expect(where()).toContain("user_id=u2");
    await waitFor(() => expect(lastList()).toMatchObject({ user_id: "u2", session_id: "s2" }));
    await u.click(screen.getByTestId("trace-clear"));
    await waitFor(() => expect(where()).toBe("/sa/traces"));
    expect(screen.queryByTestId("trace-clear")).toBeNull();
    await waitFor(() => expect(lastList()).toEqual({ limit: 20, offset: 0 }));
  });

  it("từ trang Usage sang (?user_id=…) lọc đúng user", async () => {
    openList("/sa/traces?user_id=u1");
    await waitFor(() => expect(lastList()).toEqual({ user_id: "u1", limit: 20, offset: 0 }));
  });
});

describe("TraceDetail", () => {
  beforeEach(() => {
    vi.mocked(traceApi.get).mockResolvedValue({ enabled: true, spans: [toolSpan, llmSpan, runSpan] } as never);
    vi.mocked(traceApi.raw).mockResolvedValue({
      enabled: true,
      item: {
        id: "raw1", span_id: "sp-llm", run_id: "r1", expire_at: t1, method: "POST", url: "https://api.x/v1/chat", ms: 321, started_at: t0, error: null,
        request: { headers: { authorization: "***" }, body: { model: "gpt-x" } },
        response: { status: 200, body: { id: "resp-1" } },
      },
    } as never); // fmt: skip
  });

  it("cây span: mở / gập từng nút và mở / gập tất cả", async () => {
    openDetail();
    const tree = await screen.findByTestId("span-tree");
    expect(within(tree).getByTestId("span-run-sp-run")).toBeTruthy();
    expect(within(tree).getByTestId("span-llm-sp-llm")).toBeTruthy(); // mặc định mở gốc
    expect(within(tree).queryByTestId("span-tool-sp-tool")).toBeNull();
    const u = userEvent.setup();
    await u.click(within(tree).getByTestId("span-toggle-sp-llm"));
    expect(within(tree).getByTestId("span-tool-sp-tool")).toBeTruthy();
    await u.click(within(tree).getByTestId("span-toggle-sp-llm"));
    expect(within(tree).queryByTestId("span-tool-sp-tool")).toBeNull();
    await u.click(within(tree).getByTestId("span-toggle-sp-run"));
    expect(within(tree).queryByTestId("span-llm-sp-llm")).toBeNull();
    await u.click(screen.getByTestId("spans-expand"));
    expect(within(tree).getByTestId("span-tool-sp-tool")).toBeTruthy();
    await u.click(screen.getByTestId("spans-collapse"));
    expect(within(tree).queryByTestId("span-llm-sp-llm")).toBeNull();
  });

  it("span llm hiện token + masked_hint, không lộ key đầy đủ", async () => {
    openDetail();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("spans-expand"));
    await u.click(await screen.findByTestId("span-llm-sp-llm"));
    const detail = await screen.findByTestId("span-detail");
    expect(within(detail).getByTestId("span-key").textContent).toContain("sk-…abcd");
    expect(within(detail).getByTestId("span-usage").textContent).toContain("input 100");
    expect(within(detail).getByTestId("span-usage").textContent).toContain("output 20");
    expect(within(detail).getAllByTestId("json-view").length).toBeGreaterThanOrEqual(2); // input + output qua JsonView
  });

  it("raw HTTP qua JsonView, header bí mật đã che (***)", async () => {
    openDetail();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("spans-expand"));
    await u.click(await screen.findByTestId("span-llm-sp-llm"));
    await u.click(await screen.findByTestId("raw-open-raw1"));
    const raw = await screen.findByTestId("raw-raw1");
    expect(traceApi.raw).toHaveBeenCalledWith("r1", "raw1");
    expect(raw.textContent).toContain("POST https://api.x/v1/chat");
    expect(within(raw).getAllByTestId("json-view").length).toBe(2);
    expect(raw.textContent).toContain("***");
    expect(raw.textContent).not.toMatch(/Bearer|sk-[A-Za-z0-9]{8,}/);
  });

  it("Mongo tắt → banner như trang log", async () => {
    vi.mocked(traceApi.get).mockResolvedValue({ enabled: false, spans: [] } as never);
    openDetail();
    expect(await screen.findByTestId("log-disabled-banner")).toBeTruthy();
  });

  it("span router / agent: hiện trong cây đúng cha-con; router hiện decision, agent hiện task", async () => {
    const routerSpan = {
      ...base, id: "sp-router", kind: "router", name: "router", parent_id: "sp-run", seq: 2, start: t0, end: t1, status: "ok",
      input: { text: "ghi 45k rồi xem tổng", routes: ["personal", "report"] },
      output: { decision: { steps: [{ agent: "personal", task: "ghi 45k" }], clarify: null }, steps: [{ agent: "personal", task: "ghi 45k" }], fallback: "no_decision" },
    }; // fmt: skip
    const routerLlm = { ...llmSpan, id: "sp-llm-router", parent_id: "sp-router", seq: 3 };
    const agentSpan = {
      ...base, id: "sp-agent", kind: "agent", name: "personal", parent_id: "sp-run", seq: 4, start: t0, end: t1, status: "ok",
      input: { agent_id: "ag-p", slug: "personal", task: "ghi 45k tiền cà phê", via: "router" }, output: {},
    }; // fmt: skip
    const agentLlm = { ...llmSpan, id: "sp-llm-agent", parent_id: "sp-agent", seq: 5 };
    vi.mocked(traceApi.get).mockResolvedValue({ enabled: true, spans: [agentLlm, agentSpan, routerLlm, routerSpan, runSpan] } as never);
    openDetail();
    const tree = await screen.findByTestId("span-tree");
    const u = userEvent.setup();
    const routerNode = within(tree).getByTestId("span-router-sp-router");
    const agentNode = within(tree).getByTestId("span-agent-sp-agent");
    expect(routerNode.textContent).toContain("router");
    expect(agentNode.textContent).toContain("personal");
    expect(routerNode.compareDocumentPosition(agentNode) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // theo seq
    expect(within(tree).queryByTestId("span-llm-sp-llm-router")).toBeNull(); // con của router: gập mặc định
    await u.click(within(tree).getByTestId("span-toggle-sp-router"));
    expect(within(tree).getByTestId("span-llm-sp-llm-router")).toBeTruthy();
    await u.click(within(tree).getByTestId("span-toggle-sp-agent"));
    expect(within(tree).getByTestId("span-llm-sp-llm-agent")).toBeTruthy();

    await u.click(routerNode);
    let detail = await screen.findByTestId("span-detail");
    expect(within(detail).getAllByText("router").length).toBeGreaterThan(0);
    const out = within(detail).getAllByTestId("json-view").map((v) => v.textContent).join(" ");
    expect(out).toContain("decision");
    expect(out).toContain("ghi 45k");
    expect(out).toContain("no_decision");

    await u.click(agentNode);
    detail = await screen.findByTestId("span-detail");
    const agentInput = within(detail).getAllByTestId("json-view").map((v) => v.textContent).join(" ");
    expect(agentInput).toContain("ghi 45k tiền cà phê");
    expect(agentInput).toContain("personal");
  });

  it("span router: khối router-decision hiện steps / clarify / fallback / sticky; span khác không có khối", async () => {
    const routerSpan = {
      ...base, id: "sp-router", kind: "router", name: "router", parent_id: "sp-run", seq: 2, start: t0, end: t1, status: "ok",
      input: { text: "ghi rồi xem" },
      output: { steps: [{ agent: "personal", task: "ghi 45k" }, { agent: "report" }], clarify: "Ví nào?", fallback: "no_decision", sticky: "personal" },
    }; // fmt: skip
    vi.mocked(traceApi.get).mockResolvedValue({ enabled: true, spans: [routerSpan, runSpan] } as never);
    openDetail();
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("span-router-sp-router"));
    const box = await screen.findByTestId("router-decision");
    expect(box.textContent).toContain("personal (ghi 45k) → report");
    expect(box.textContent).toContain("? Ví nào?");
    expect(box.textContent).toContain("fallback: no_decision");
    expect(box.textContent).toContain("sticky: personal");
    await u.click(screen.getByTestId(/^span-run-/));
    await screen.findByTestId("span-detail");
    expect(screen.queryByTestId("router-decision")).toBeNull();
  });
});
