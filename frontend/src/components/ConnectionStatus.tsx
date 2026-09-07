import type { ConnectionState } from "@/collab/provider"

interface ConnectionStatusProps {
  state: ConnectionState
  reconnectAttempt: number
  onRetry: () => void
}

const LABELS: Record<ConnectionState, string> = {
  connecting: "Connecting…",
  syncing: "Syncing…",
  live: "Live",
  offline: "Disconnected",
  closed: "Connection closed",
}

const DOT_COLOR: Record<ConnectionState, string> = {
  connecting: "bg-yellow-500",
  syncing: "bg-yellow-500",
  live: "bg-green-500",
  offline: "bg-red-500",
  closed: "bg-red-500",
}


const RETRYABLE = new Set<ConnectionState>(["offline", "closed"])

export function ConnectionStatus({ state, reconnectAttempt, onRetry }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`h-2 w-2 rounded-full ${DOT_COLOR[state]}`} />
      <span className="font-mono text-muted-foreground">
        {LABELS[state]}
        {state === "offline" && reconnectAttempt > 0 && ` (attempt ${reconnectAttempt})`}
      </span>
      {RETRYABLE.has(state) && (
        <button
          type="button"
          onClick={onRetry}
          className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          Retry
        </button>
      )}
    </div>
  )
}
