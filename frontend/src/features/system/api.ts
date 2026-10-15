import { call, type OpInput, type OpOutput } from "@/lib/api";

export type PublicInfo = OpOutput<"system.public_info">;
export type SystemSettings = OpOutput<"system.get_settings">;
export type SettingsPatch = OpInput<"system.update_settings">;

export const systemApi = {
  publicInfo: () => call("system.public_info"),
  getSettings: () => call("system.get_settings"),
  updateSettings: (patch: SettingsPatch) => call("system.update_settings", patch),
  status: () => call("system.status"),
};
