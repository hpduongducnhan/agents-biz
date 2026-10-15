/** Kiểm access JWT bằng PUBLIC key (realtime không ký, không giữ private key). */

import { readFileSync } from "node:fs";

import { type CryptoKey, type KeyObject, importSPKI, jwtVerify } from "jose";

export interface Claims {
  sub: string;
  tid?: string; // tenant của user (D10) — socket join phòng `tenant:<tid>`
  perms: string[];
  sup: boolean;
  exp: number;
  iat: number;
}

export class AuthError extends Error {}

export type PublicKey = CryptoKey | KeyObject;

export async function importPublicKey(pem: string, alg: string): Promise<PublicKey> {
  return importSPKI(pem, alg);
}

export async function loadPublicKey(path: string, alg: string): Promise<PublicKey> {
  return importPublicKey(readFileSync(path, "utf8"), alg);
}

export async function verifyAccess(token: string, key: PublicKey, alg: string): Promise<Claims> {
  let payload: Record<string, unknown>;
  try {
    ({ payload } = await jwtVerify(token, key, { algorithms: [alg], requiredClaims: ["sub", "exp", "iat"] }));
  } catch (err) {
    throw new AuthError(err instanceof Error ? err.message : "invalid token");
  }
  if (payload.typ !== "access") throw new AuthError("not an access token");
  return {
    sub: String(payload.sub),
    ...(typeof payload.tid === "string" && payload.tid ? { tid: payload.tid } : {}),
    perms: Array.isArray(payload.perms) ? payload.perms.map(String) : [],
    sup: payload.sup === true,
    exp: Number(payload.exp),
    iat: Number(payload.iat),
  };
}
