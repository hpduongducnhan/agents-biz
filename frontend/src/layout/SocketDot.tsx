import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";
import { useSocketStatus } from "@/lib/realtime/hooks";
import type { SocketStatus } from "@/lib/realtime/socket";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui";

const COLOR: Record<SocketStatus, string> = {
  connected: "bg-positive",
  connecting: "bg-warning animate-pulse",
  offline: "bg-muted-foreground",
};

/** Đèn kết nối realtime trên header. */
export function SocketDot() {
  const t = useT();
  const status = useSocketStatus();
  const label = t(`socket.${status}`);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span role="status" tabIndex={0} aria-label={label} data-testid="socket-dot" data-status={status} className="grid h-11 w-7 place-items-center md:h-9">
          <span className={cn("h-2.5 w-2.5 rounded-full", COLOR[status])} />
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
