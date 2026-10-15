/** API miền auth — tên operation khớp backend; kiểu lấy từ OpenAPI (R7). */
import { call, type OpInput } from "@/lib/api";

export const authApi = {
  register: (input: OpInput<"auth.register">) => call("auth.register", input),
  login: (input: OpInput<"auth.login">) => call("auth.login", input),
  logout: (refresh_token: string) => call("auth.logout", { refresh_token }),
  logoutAll: () => call("auth.logout_all"),
  me: () => call("auth.me"),
  updateMe: (input: OpInput<"auth.update_me">) => call("auth.update_me", input),
  changePassword: (input: OpInput<"auth.change_password">) => call("auth.change_password", input),
  requestVerify: (email: string) => call("auth.request_verify", { email }),
  verifyEmail: (token: string) => call("auth.verify_email", { token }),
  forgotPassword: (email: string) => call("auth.forgot_password", { email }),
  resetPassword: (token: string, new_password: string) => call("auth.reset_password", { token, new_password }),
};
