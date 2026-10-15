/**
 * Một cửa transport (R6, R15): axios + interceptor — gắn Bearer / ngôn ngữ, mở envelope, ném ApiError, refresh
 * single-flight khi 401 (nhiều request cùng lúc chỉ refresh 1 lần — refresh token có phát hiện dùng lại). Giữa các
 * tab: xếp hàng bằng Web Locks; refresh token luôn đọc lại TRONG khoá (tab trước có thể vừa xoay).
 */
import axios, { type AxiosAdapter, type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from "axios";

import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/lib/auth-tokens";

import { endpoint, type OpArgs, type OpName, type OpOutput } from "./endpoints";
import { ApiError, type ApiResponse } from "./errors";
import { apiUrl } from "./url";

type HttpOptions = { baseURL?: string; onAuthFailure?: () => void; adapter?: AxiosAdapter };
type Retriable = AxiosRequestConfig & { _retry?: boolean };

let instance: AxiosInstance = axios.create();
let raw: AxiosInstance = axios.create();
let onAuthFailure: () => void = () => {};
let failureNotified = false;
let inflight: Promise<string> | null = null;

/** 401 của đăng nhập / đăng ký là sai thông tin, không phải hết phiên. */
const NO_REFRESH = new Set([endpoint("auth.login").path, endpoint("auth.register").path]);
const LOCK = "bw-auth-refresh";

function toApiError(status: number, body: unknown, headers?: Record<string, unknown>): ApiError {
  const env = (body && typeof body === "object" ? body : {}) as Partial<ApiResponse>;
  const headerCid = headers?.["x-correlation-id"];
  return new ApiError({
    message: env.message || `HTTP ${status}`,
    status,
    code: typeof env.code === "number" ? env.code : null,
    correlationId: env.correlation_id ?? (typeof headerCid === "string" ? headerCid : null),
    data: env.data,
  });
}

async function doRefresh(): Promise<string> {
  const refresh = getRefreshToken();
  if (!refresh) throw new ApiError({ message: "No refresh token", status: 401 });
  try {
    const res = await raw.post<ApiResponse<{ access_token: string; refresh_token: string }>>(endpoint("auth.refresh").path, {
      refresh_token: refresh,
    });
    if (!res.data.success) throw toApiError(res.status, res.data, res.headers);
    setTokens(res.data.data.access_token, res.data.data.refresh_token);
    failureNotified = false;
    return res.data.data.access_token;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const r = (err as { response?: AxiosResponse }).response;
    // Không có response = mất mạng / timeout: KHÔNG phải phiên hết hạn (PWA offline giữ đăng nhập).
    if (!r) throw new ApiError({ message: "Network error", status: 0 });
    throw toApiError(r.status, r.data, r.headers);
  }
}

/** Server thật sự từ chối refresh (4xx) → hết phiên; mất mạng (0) / server lỗi (5xx) → giữ token, thử lại sau. */
const sessionRejected = (err: unknown) => err instanceof ApiError && err.status >= 400 && err.status < 500;

/** Lượt thua khi hai tab cùng refresh mà không có Web Locks: BE trả 2104 nhưng phiên còn trong 10 s ân hạn —
 *  tab kia đã ghi refresh token mới vào storage → đọc lại và thử đúng một lần trước khi coi là hết phiên. */
async function refreshWithRetry(): Promise<string> {
  const sent = getRefreshToken();
  try {
    return await doRefresh();
  } catch (err) {
    const latest = getRefreshToken();
    if (err instanceof ApiError && err.code === 2104 && latest && latest !== sent) return doRefresh();
    throw err;
  }
}

/** Trong khoá: access token đã khác token bị 401 → lượt trước của tab này vừa xoay, dùng luôn. */
function refreshOnce(stale: string | null): Promise<string> {
  const run = () => {
    const current = getAccessToken();
    return current && current !== stale ? Promise.resolve(current) : refreshWithRetry();
  };
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  return locks ? locks.request(LOCK, run) : run();
}

/** Làm mới phiên (single-flight) — interceptor, socket (`auth:expired`, `core:rbac_updated`) dùng chung. */
export function refreshSession(stale: string | null = getAccessToken()): Promise<string> {
  inflight ??= refreshOnce(stale)
    .catch((err: unknown) => {
      if (sessionRejected(err)) {
        clearTokens();
        if (!failureNotified) {
          failureNotified = true;
          onAuthFailure();
        }
      }
      throw err;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function configureHttp(opts: HttpOptions = {}): void {
  const baseURL = opts.baseURL ?? apiUrl();
  onAuthFailure = opts.onAuthFailure ?? (() => {});
  failureNotified = false;
  inflight = null;
  raw = axios.create({ baseURL, timeout: 30_000, adapter: opts.adapter });
  instance = axios.create({
    baseURL,
    timeout: 30_000,
    headers: { "Content-Type": "application/json" },
    adapter: opts.adapter,
    paramsSerializer: { indexes: null }, // mảng → ids=a&ids=b (FastAPI), không ids[]=a
  });
  instance.interceptors.request.use(async (config) => {
    let token = getAccessToken();
    // Mở lại trang: access token (chỉ ở bộ nhớ) đã mất, còn refresh token → làm mới trước, không gửi để ăn 401.
    if (!token && getRefreshToken() && !NO_REFRESH.has(config.url ?? "")) token = await refreshSession(null);
    if (token) config.headers.Authorization = `Bearer ${token}`;
    config.headers["Accept-Language"] = document.documentElement.lang || "vi";
    return config;
  });
  instance.interceptors.response.use(
    (res: AxiosResponse<ApiResponse>) => {
      if (res.data && res.data.success === false) throw toApiError(res.status, res.data, res.headers);
      return res;
    },
    async (error: { config?: Retriable; response?: AxiosResponse }) => {
      if (error instanceof ApiError) throw error; // request interceptor đã ném (refresh trước khi gửi hỏng)
      const original = error.config;
      const status = error.response?.status ?? 0;
      if (status === 401 && original && !original._retry && getRefreshToken() && !NO_REFRESH.has(original.url ?? "")) {
        original._retry = true;
        const used = String(original.headers?.Authorization ?? "").replace(/^Bearer /, "") || null;
        const token = await refreshSession(used);
        original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
        return instance.request(original);
      }
      if (error.response) throw toApiError(status, error.response.data, error.response.headers);
      throw new ApiError({ message: "Network error", status: 0 });
    },
  );
}

async function unwrap<T>(p: Promise<AxiosResponse<ApiResponse<T>>>): Promise<T> {
  return (await p).data.data;
}

export const http = {
  get: <T>(path: string, cfg?: AxiosRequestConfig) => unwrap<T>(instance.get(path, cfg)),
  post: <T>(path: string, body?: unknown, cfg?: AxiosRequestConfig) => unwrap<T>(instance.post(path, body, cfg)),
  put: <T>(path: string, body?: unknown, cfg?: AxiosRequestConfig) => unwrap<T>(instance.put(path, body, cfg)),
  patch: <T>(path: string, body?: unknown, cfg?: AxiosRequestConfig) => unwrap<T>(instance.patch(path, body, cfg)),
  delete: <T>(path: string, cfg?: AxiosRequestConfig) => unwrap<T>(instance.delete(path, cfg)),
};

/** Cửa duy nhất để trang / feature gọi API: GET → query, còn lại → body JSON. */
export function call<O extends OpName>(op: O, ...args: OpArgs<O>): Promise<OpOutput<O>> {
  const { method, path } = endpoint(op);
  const input: unknown = args[0];
  return method === "GET" ? http.get<OpOutput<O>>(path, { params: input }) : http.post<OpOutput<O>>(path, input ?? {});
}
