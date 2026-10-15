/** Kiểu phiên lấy từ hợp đồng OpenAPI (R7). */
import type { OpOutput } from "@/lib/api/endpoints";

export type Me = OpOutput<"auth.me">;
export type LoginResult = OpOutput<"auth.login">;
export type SessionTokens = { access_token: string; refresh_token: string };
