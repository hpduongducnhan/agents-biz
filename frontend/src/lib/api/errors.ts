/** Envelope BE (`ApiResponse`) + lỗi chuẩn của FE. Lỗi luôn mang correlation id để tra log. */

export type ApiResponse<T = unknown> = {
  success: boolean;
  code: number;
  message: string | null;
  data: T;
  correlation_id?: string | null;
};

/** Danh sách phân trang (R14): `limit` mặc định 20, tối đa 100. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export class ApiError extends Error {
  readonly status: number;
  readonly code: number | null;
  readonly correlationId: string | null;
  readonly data: unknown;

  constructor(opts: { message: string; status: number; code?: number | null; correlationId?: string | null; data?: unknown }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code ?? null;
    this.correlationId = opts.correlationId ?? null;
    this.data = opts.data;
  }
}
