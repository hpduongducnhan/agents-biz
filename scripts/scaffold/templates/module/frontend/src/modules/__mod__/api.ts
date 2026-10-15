/** API module __title_vi__ — tên op khớp backend; kiểu lấy từ OpenAPI (R7). */
import { call, type OpInput, type OpOutput } from "@/lib/api";

export type __Mod__Item = OpOutput<"__mod__.create">;
export type __Mod__Query = OpInput<"__mod__.list">;

export const __mod__Api = {
  list: (q: __Mod__Query) => call("__mod__.list", q),
  get: (item_id: string) => call("__mod__.get", { item_id }),
  create: (input: OpInput<"__mod__.create">) => call("__mod__.create", input),
  update: (input: OpInput<"__mod__.update">) => call("__mod__.update", input),
  remove: (item_id: string) => call("__mod__.delete", { item_id }),
};
