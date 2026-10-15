/** Danh sách module nghiệp vụ (D25) — module mới thêm MỘT dòng ở `MODULES`. Chỉ import manifest (nhẹ: icon, từ
 *  điển, trang lazy) — lọc theo quyền nằm ở `access.ts`. */
import { tasksModule } from "./tasks";
import type { ModuleManifest } from "./types";

export const MODULES: ModuleManifest[] = [tasksModule];
