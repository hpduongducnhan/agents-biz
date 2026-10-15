import { call, type OpInput, type OpOutput } from "@/lib/api";

export type EventQuery = OpInput<"observability.list_events">;
export type EventEntry = OpOutput<"observability.list_events">["items"][number];
export type IssueQuery = OpInput<"observability.list_issues">;
export type Issue = OpOutput<"observability.list_issues">["items"][number];
export type IssueDetail = NonNullable<OpOutput<"observability.get_issue">["item"]>;
export type IssueStatus = OpInput<"observability.set_issue_status">["status"];

/** Issue định danh bằng `fingerprint` (sha1 hex 40). */
export const obsApi = {
  listEvents: (q: EventQuery) => call("observability.list_events", q),
  listIssues: (q: IssueQuery) => call("observability.list_issues", q),
  getIssue: (fingerprint: string) => call("observability.get_issue", { fingerprint }),
  setIssueStatus: (fingerprint: string, status: IssueStatus) => call("observability.set_issue_status", { fingerprint, status }),
};
