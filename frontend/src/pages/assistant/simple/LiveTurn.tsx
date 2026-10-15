import { useEffect } from "react";

import type { LiveRun } from "@/features/agent/store";
import { useReducedMotion } from "@/lib/use-media";
import { useTypewriter } from "@/lib/use-typewriter";

import { ApprovalList, type DecideFn } from "../ApprovalGroup";
import { RunDots } from "./RunDots";
import { ReplyBubble } from "./Turns";

type Props = { live: LiveRun; deciding: boolean; onDecide: DecideFn; onGrow?: () => void };

/** Lượt đang chạy ở màn đơn giản: hàng chấm (nhấp nháy khi đang làm) → thẻ duyệt (≥ 2 thì gom) → chữ đang chạy.
 *  Chữ hiện đều tay khi lượt có stream; `onGrow` để khung chat cuộn theo chữ đang hiện. */
export function LiveTurn({ live, deciding, onDecide, onGrow }: Props) {
  const running = live.status === "running" || live.status === "waiting";
  const reduced = useReducedMotion(); // gọi hook mọi lần render — không đặt sau `&&` (rules of hooks)
  const smooth = live.stream !== false && !reduced;
  const texts = live.blocks.length ? live.blocks.map((b) => b.text).filter(Boolean) : live.text ? [live.text] : [];
  return (
    <div className="grid gap-1.5" data-testid="live-run" data-status={live.status} data-stream={live.stream === false ? "off" : "on"}>
      <RunDots dots={live.trail} running={running} />
      <ApprovalList approvals={live.approvals} simple busy={deciding} onDecide={onDecide} />
      {texts.map((text, i) => (
        <LiveReply key={i} text={text} running={running} smooth={smooth} onGrow={onGrow} />
      ))}
    </div>
  );
}

function LiveReply({ text, running, smooth, onGrow }: { text: string; running: boolean; smooth: boolean; onGrow?: () => void }) {
  const shown = useTypewriter(text, { running, enabled: smooth });
  useEffect(() => onGrow?.(), [shown, onGrow]);
  return <ReplyBubble text={shown} />;
}
