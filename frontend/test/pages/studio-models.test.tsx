// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Credential, Provider, RemoteModel } from "@/features/agent/api";
import { ApiError } from "@/lib/api/errors";
import { translate } from "@/lib/i18n";
import StudioPage from "@/pages/studio/StudioPage";

import { me } from "../fixtures";
import { renderPage, setDesktop } from "../render";

vi.mock("sonner", () => import("../sonner-mock"));
vi.mock("@/features/agent/api", () => {
  const fns = (...names: string[]) =>
    Object.fromEntries(names.map((n) => [n, vi.fn()]));
  return {
    studioApi: fns(
      "providers",
      "models",
      "agents",
      "providerModels",
      "addModels",
    ),
    credentialsApi: fns("list", "create", "update", "remove"),
    agentApi: fns("agents"),
    traceApi: fns("list"),
  };
});
const { studioApi, credentialsApi } = await import("@/features/agent/api");
const { toast } = await import("../sonner-mock");

const SA = me({ is_superadmin: true, permissions: [] });
const prov = (id: string, name: string): Provider => ({
  id,
  name,
  kind: "openai_compatible",
  base_url: null,
  extra_headers: {},
  default_params: {},
  status: "active",
  models_count: 1,
}); // fmt: skip
const cred = (over: Partial<Credential> = {}): Credential => ({
  id: "c1",
  name: "Key chính",
  kind: "api_key",
  provider_id: "p1",
  masked_hint: "sk-…7890",
  weight: 1,
  status: "active",
  disabled_reason: null,
  key_id: "k1",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  ...over,
}); // fmt: skip
const rm = (over: Partial<RemoteModel>): RemoteModel => ({
  model_id: "x",
  name: "X",
  description: "",
  context_window: null,
  chat: true,
  input_price_per_1m: null,
  output_price_per_1m: null,
  cache_read_price_per_1m: null,
  added: false,
  ...over,
}); // fmt: skip
const remote = (models: RemoteModel[]) => ({
  credential_id: "c1",
  latency_ms: 12,
  models,
});
const MODELS = [
  rm({ model_id: "fake-model", name: "Fake Model", added: true }),
  rm({
    model_id: "fake/large",
    name: "Fake Large",
    context_window: 128000,
    input_price_per_1m: "2",
    output_price_per_1m: "8",
  }),
  rm({ model_id: "fake-embed", name: "Fake Embed", chat: false }),
];
const t = (k: string, p?: Record<string, string | number>) => translate(k, p);
const firstArg = (fn: unknown) =>
  (fn as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];
const open = (route: string) =>
  renderPage(<StudioPage />, { path: "/studio", route, user: SA });

beforeEach(() => {
  setDesktop(false);
  vi.mocked(studioApi.providers).mockResolvedValue([
    prov("p1", "LLM giả"),
    prov("p2", "Khác"),
  ]);
  vi.mocked(studioApi.models).mockResolvedValue([]);
  vi.mocked(studioApi.agents).mockResolvedValue([]);
  vi.mocked(studioApi.providerModels).mockResolvedValue(remote(MODELS));
  vi.mocked(studioApi.addModels).mockResolvedValue({ added: 1, skipped: 0 });
  vi.mocked(credentialsApi.list).mockResolvedValue({
    items: [
      cred(),
      cred({ id: "c2", name: "Key lạ", provider_id: "p2" }),
      cred({ id: "c3", name: "Key chung", provider_id: null }),
    ],
    total: 3,
    limit: 100,
    offset: 0,
  }); // fmt: skip
});

const openFromProvider = async () => {
  const u = userEvent.setup();
  open("/studio?tab=providers");
  await u.click(await screen.findByTestId("provider-models-p1"));
  return { u, dialog: await screen.findByTestId("provider-models-dialog") };
};

describe("Studio — chọn model từ provider", () => {
  it("nút 'Chọn model' ở tab Provider mở hộp thoại cố định provider (không có ô chọn provider), key mặc định tự chọn", async () => {
    const { dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-fake/large");
    expect(studioApi.providerModels).toHaveBeenCalledWith("p1", undefined);
    expect(within(dialog).queryByLabelText(t("studio.provider"))).toBeNull();
    const key = within(dialog).getByTestId(
      "provider-models-key",
    ) as HTMLSelectElement;
    expect(key.value).toBe("");
    const labels = Array.from(key.options).map((o) => o.textContent);
    expect(labels[0]).toBe(t("studio.keyAuto"));
    expect(labels.join("|")).toContain("Key chính");
    expect(labels.join("|")).toContain("Key chung");
    expect(labels.join("|")).not.toContain("Key lạ"); // key gắn provider khác
  });

  it("danh sách: ẩn model không phải chat theo mặc định, hiện khi tắt công tắc; model đã thêm bị khoá + huy hiệu", async () => {
    const { u, dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-fake/large");
    expect(
      within(dialog).queryByTestId("provider-model-fake-embed"),
    ).toBeNull();
    const added = within(dialog).getByTestId("provider-model-fake-model");
    expect(within(added).getByText(t("studio.modelAdded"))).toBeTruthy();
    expect(
      within(added).getByRole("checkbox").hasAttribute("disabled") ||
        within(added).getByRole("checkbox").getAttribute("aria-disabled") ===
          "true",
    ).toBe(true);
    const large = within(dialog).getByTestId("provider-model-fake/large");
    expect(large.textContent).toContain(t("studio.ctxK", { n: 128 }));
    expect(large.textContent).toContain("$2 / $8");
    await u.click(within(dialog).getByRole("switch"));
    expect(
      within(dialog).getByTestId("provider-model-fake-embed"),
    ).toBeTruthy();
  });

  it("tìm kiếm lọc theo tên / mã; không khớp hiện thông báo rỗng", async () => {
    const { u, dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-fake/large");
    await u.type(within(dialog).getByTestId("provider-models-search"), "large");
    expect(
      within(dialog).queryByTestId("provider-model-fake-model"),
    ).toBeNull();
    expect(
      within(dialog).getByTestId("provider-model-fake/large"),
    ).toBeTruthy();
    await u.clear(within(dialog).getByTestId("provider-models-search"));
    await u.type(within(dialog).getByTestId("provider-models-search"), "zzz");
    expect(within(dialog).getByText(t("studio.noRemote"))).toBeTruthy();
  });

  it("chọn một model → nút 'Thêm 1 model' gọi add_models với giá, toast tổng kết, đóng hộp thoại", async () => {
    vi.mocked(studioApi.addModels).mockResolvedValue({ added: 1, skipped: 2 });
    const { u, dialog } = await openFromProvider();
    const add = within(dialog).getByTestId("provider-models-add");
    await within(dialog).findByTestId("provider-model-fake/large");
    expect((add as HTMLButtonElement).disabled).toBe(true);
    await u.click(
      within(within(dialog).getByTestId("provider-model-fake/large")).getByRole(
        "checkbox",
      ),
    );
    expect(add.textContent).toBe(t("studio.addN", { n: 1 }));
    await u.click(add);
    await waitFor(() => expect(studioApi.addModels).toHaveBeenCalled());
    expect(firstArg(studioApi.addModels)).toEqual({
      provider_id: "p1",
      models: [
        {
          model_id: "fake/large",
          name: "Fake Large",
          context_window: 128000,
          input_price_per_1m: "2",
          output_price_per_1m: "8",
          cache_read_price_per_1m: "0",
        },
      ],
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        t("studio.addedN", { added: 1, skipped: 2 }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("provider-models-dialog")).toBeNull(),
    );
  });

  it("'Chọn tất cả đang hiện' bỏ qua model đã thêm và model bị lọc; giá thiếu gửi '0', tên cắt 100 ký tự", async () => {
    vi.mocked(studioApi.providerModels).mockResolvedValue(
      remote([...MODELS, rm({ model_id: "long", name: "n".repeat(150) })]),
    );
    const { u, dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-long");
    await u.click(within(dialog).getByTestId("provider-models-all"));
    expect(within(dialog).getByTestId("provider-models-add").textContent).toBe(
      t("studio.addN", { n: 2 }),
    );
    await u.click(within(dialog).getByTestId("provider-models-add"));
    await waitFor(() => expect(studioApi.addModels).toHaveBeenCalled());
    const body = firstArg(studioApi.addModels) as {
      models: {
        model_id: string;
        name: string;
        context_window: number | null;
        input_price_per_1m: string;
      }[];
    };
    expect(body.models.map((m) => m.model_id)).toEqual(["fake/large", "long"]);
    const long = body.models[1];
    expect(long?.name).toHaveLength(100);
    expect(long?.input_price_per_1m).toBe("0");
    expect(long?.context_window).toBeNull();
  });

  it("chọn > 100 model thì gửi từng lô 100 và cộng dồn kết quả", async () => {
    const many = Array.from({ length: 130 }, (_, i) =>
      rm({ model_id: `m${i}`, name: `M${i}` }),
    );
    vi.mocked(studioApi.providerModels).mockResolvedValue(remote(many));
    vi.mocked(studioApi.addModels)
      .mockResolvedValueOnce({ added: 100, skipped: 0 })
      .mockResolvedValueOnce({ added: 28, skipped: 2 });
    const { u, dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-m0");
    await u.click(within(dialog).getByTestId("provider-models-all"));
    await u.click(within(dialog).getByTestId("provider-models-add"));
    await waitFor(() => expect(studioApi.addModels).toHaveBeenCalledTimes(2));
    const sizes = vi
      .mocked(studioApi.addModels)
      .mock.calls.map((c) => c[0].models.length);
    expect(sizes).toEqual([100, 30]);
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        t("studio.addedN", { added: 128, skipped: 2 }),
      ),
    );
  });

  it("chọn key cụ thể gọi lại provider_models với credential_id", async () => {
    const { u, dialog } = await openFromProvider();
    await within(dialog).findByTestId("provider-model-fake/large");
    await u.selectOptions(
      within(dialog).getByTestId("provider-models-key"),
      "c3",
    );
    await waitFor(() =>
      expect(studioApi.providerModels).toHaveBeenCalledWith("p1", "c3"),
    );
  });

  it("lỗi provider hiện inline kèm errorText + data.detail, không có danh sách", async () => {
    vi.mocked(studioApi.providerModels).mockRejectedValue(
      new ApiError({
        message: "Provider error",
        status: 502,
        code: 6011,
        data: { status: 401, detail: "Incorrect API key provided" },
      }),
    );
    const { dialog } = await openFromProvider();
    const err = await within(dialog).findByTestId("provider-models-error");
    expect(err.textContent).toContain("Incorrect API key provided");
    expect(within(dialog).queryByTestId("provider-models-list")).toBeNull();
  });

  it("tab Model: nút 'Thêm từ provider' mở hộp thoại có ô chọn provider; đổi provider tải lại danh sách", async () => {
    const u = userEvent.setup();
    open("/studio?tab=models");
    await u.click(await screen.findByTestId("model-import"));
    const dialog = await screen.findByTestId("provider-models-dialog");
    await within(dialog).findByTestId("provider-model-fake/large");
    expect(studioApi.providerModels).toHaveBeenCalledWith("p1", undefined);
    await u.selectOptions(
      within(dialog).getByLabelText(t("studio.provider")),
      "p2",
    );
    await waitFor(() =>
      expect(studioApi.providerModels).toHaveBeenCalledWith("p2", undefined),
    );
  });

  it("tab Model: 'Thêm từ provider' bị khoá khi chưa có provider", async () => {
    vi.mocked(studioApi.providers).mockResolvedValue([]);
    open("/studio?tab=models");
    await waitFor(() =>
      expect(
        (screen.getByTestId("model-import") as HTMLButtonElement).disabled,
      ).toBe(true),
    );
  });
});
