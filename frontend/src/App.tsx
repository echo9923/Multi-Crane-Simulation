import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, useParams, useNavigate } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { SceneView } from "@/components/SceneView";
import { LeftControls } from "@/components/LeftControls";
import { Panels } from "@/components/panels/Panels";
import { Timeline } from "@/components/Timeline";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { ConfigPage as ConfigPageView } from "@/components/ConfigPage";
import { useRealtimeEpisode } from "@/hooks/useRealtimeEpisode";
import { ensureDemoLoaded } from "@/bootstrap";
import { useStore } from "@/state/store";

function TopNav() {
  const mode = useStore((s) => s.mode);
  const episodeId = useStore((s) => s.episodeId);
  return (
    <>
      <span className="brand">
        <span className="brand-badge" aria-hidden>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 21h16" />
            <path d="M9 21V4" />
            <path d="M5 7h14" />
            <path d="M9 4l3 3M9 4l-3 3" />
            <path d="M15 7v3" />
          </svg>
        </span>
        群塔仿真
      </span>
      <nav style={{ display: "flex", gap: 4 }}>
        <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
          主视图
        </NavLink>
        <NavLink to="/config" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
          配置
        </NavLink>
      </nav>
      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
        <GoLive />
        <ConnectionBadge />
        {mode !== "idle" && (
          <span className="chip">
            {mode}
            {episodeId ? ` · ${episodeId}` : ""}
          </span>
        )}
      </span>
    </>
  );
}

function GoLive() {
  const [id, setId] = useState("");
  const navigate = useNavigate();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim()) navigate(`/live/${encodeURIComponent(id.trim())}`);
      }}
      style={{ display: "flex", gap: 6 }}
    >
      <input
        data-testid="live-id-input"
        placeholder="episode id 实时"
        value={id}
        onChange={(e) => setId(e.target.value)}
        style={{ width: 150 }}
      />
      <button type="submit">实时</button>
    </form>
  );
}

function HomePage() {
  useEffect(() => {
    ensureDemoLoaded();
  }, []);
  return (
    <Layout
      top={<TopNav />}
      left={<LeftControls />}
      center={<SceneView />}
      right={<Panels />}
      bottom={<Timeline />}
    />
  );
}

function LivePage() {
  const { episodeId } = useParams<{ episodeId: string }>();
  useRealtimeEpisode(episodeId);
  return (
    <Layout
      top={<TopNav />}
      left={<LeftControls />}
      center={<SceneView />}
      right={<Panels />}
      bottom={<Timeline />}
    />
  );
}

function ConfigPage() {
  return (
    <Layout
      top={<TopNav />}
      center={<ConfigPageView />}
    />
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/live/:episodeId" element={<LivePage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </BrowserRouter>
  );
}
