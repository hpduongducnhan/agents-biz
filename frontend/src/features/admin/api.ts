import { call, type OpInput, type OpOutput } from "@/lib/api";

export type AdminUser = OpOutput<"admin.get_user">;
export type UserQuery = OpInput<"admin.list_users">;

export const adminApi = {
  listUsers: (q: UserQuery) => call("admin.list_users", q),
  getUser: (user_id: string) => call("admin.get_user", { user_id }),
  updateUser: (input: OpInput<"admin.update_user">) => call("admin.update_user", input),
  resetPassword: (input: OpInput<"admin.reset_password">) => call("admin.reset_password", input),
  userPolicies: (user_id: string) => call("admin.user_policies", { user_id }),
  setUserPolicies: (input: OpInput<"admin.set_user_policies">) => call("admin.set_user_policies", input),
};
