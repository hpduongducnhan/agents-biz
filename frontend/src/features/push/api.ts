import { call, type OpInput } from "@/lib/api";

export const pushApi = {
  config: () => call("push.config"),
  subscribe: (input: OpInput<"push.subscribe">) => call("push.subscribe", input),
  unsubscribe: (endpoint: string) => call("push.unsubscribe", { endpoint }),
};
