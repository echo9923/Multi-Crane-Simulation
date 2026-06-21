import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { ConnectionBadge } from "@/components/ConnectionBadge";
import { useStore } from "@/state/store";
import { useWorkbenchStore } from "@/state/workbench";

const navItems = [
  { to: "/", label: "场景", end: true },
  { to: "/config", label: "API Key" },
  { to: "/run", label: "运行" },
  { to: "/visualization", label: "3D 观察" },
  { to: "/data", label: "数据导出" },
  { to: "/settings", label: "设置" },
];

export function WorkbenchShell(props: { children: ReactNode }) {
  const summary = useWorkbenchStore((s) => s.summary);
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const runtimeMode = useStore((s) => s.mode);
  const runtimeEpisodeId = useStore((s) => s.episodeId);
  const runtimeLabel =
    currentEpisode?.episode_id ??
    (runtimeMode !== "idle" || runtimeEpisodeId
      ? `${runtimeMode}${runtimeEpisodeId ? ` · ${runtimeEpisodeId}` : ""}`
      : "未运行");

  return (
    <div className="workbench-shell">
      <aside className="workbench-sidebar">
        <div className="workbench-brand">
          <span className="brand-badge" aria-hidden>
            塔
          </span>
          <span>群塔仿真工作台</span>
        </div>
        <nav className="workbench-nav" aria-label="工作台导航">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `workbench-nav-link${isActive ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <section className="workbench-stage">
        <header className="workbench-statusbar">
          <div className="workbench-status-group" aria-label="实验摘要">
            <span className="chip">场景 {summary?.scenarioId ?? "未选择"}</span>
            <span className="chip">实验 {summary?.experimentId ?? "未创建"}</span>
            <span className="chip">Episode {runtimeLabel}</span>
          </div>
          <ConnectionBadge />
        </header>
        <main className="workbench-content">{props.children}</main>
      </section>
    </div>
  );
}
