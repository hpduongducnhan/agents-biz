import { call, type OpInput, type OpOutput } from "@/lib/api";

export type Role = OpOutput<"rbac.list_roles">["items"][number];
export type Permission = OpOutput<"rbac.list_permissions">[number];

/** Role ít (vài chục) → lấy một trang 100 (R14 — tra cứu / dropdown). Catalog quyền là danh sách cố định, không phân trang. */
const ALL_ROLES = { limit: 100, offset: 0 } as const;

export const rbacApi = {
  listPermissions: () => call("rbac.list_permissions"),
  listRoles: () => call("rbac.list_roles", ALL_ROLES),
  createRole: (input: OpInput<"rbac.create_role">) => call("rbac.create_role", input),
  updateRole: (input: OpInput<"rbac.update_role">) => call("rbac.update_role", input),
  deleteRole: (role_id: string) => call("rbac.delete_role", { role_id }),
  setRolePolicies: (input: OpInput<"rbac.set_role_policies">) => call("rbac.set_role_policies", input),
};
