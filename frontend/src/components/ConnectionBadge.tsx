// Connection status indicator for the realtime WebSocket link.

import { useStore } from "@/state/store";
import type { ConnectionStatus } from "@/state/store";

const COLOR: Record<ConnectionStatus, string> = {
  idle: "#6b7280",
  connecting: "#fbbf24",
  open: "#34d399",
  reconnecting: "#fb923c",
  error: "#ef4444",
};

const LABEL: Record<ConnectionStatus, string> = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  reconnecting: "重连中",
  error: "错误",
};

export function ConnectionBadge() {
  const conn = useStore((s) => s.connection);
  return (
    <span
      className="chip"
      data-testid="connection-badge"
      title={conn.error ?? LABEL[conn.status]}
      style={{ borderColor: COLOR[conn.status] }}
    >
      <span className="swatch" style={{ background: COLOR[conn.status] }} />
      {LABEL[conn.status]}
      {conn.attempts > 0 ? ` · #${conn.attempts}` : ""}
    </span>
  );
}
