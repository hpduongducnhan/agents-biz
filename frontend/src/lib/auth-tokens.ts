/**
 * Token phiên: access token chỉ ở bộ nhớ (không persist); refresh token ở localStorage để mở lại trang /
 * tab khác vẫn còn phiên. Module thuần (không React) để interceptor + socket đọc trực tiếp.
 */
const REFRESH_KEY = "bw_refresh_token";

let access: string | null = null;

export function getAccessToken(): string | null {
  return access;
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(accessToken: string, refreshToken: string): void {
  access = accessToken;
  localStorage.setItem(REFRESH_KEY, refreshToken);
}

export function clearTokens(): void {
  access = null;
  try {
    localStorage.removeItem(REFRESH_KEY);
  } catch {
    // trình duyệt chặn storage: phiên trong bộ nhớ vẫn đã xoá
  }
}
