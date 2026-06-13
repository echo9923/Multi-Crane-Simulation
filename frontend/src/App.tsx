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
      <strong>群塔仿真 3D 展示</strong>
      <nav style={{ display: "flex", gap: 12 }}>
        <NavLink to="/" end>
          主视图
        </NavLink>
        <NavLink to="/config">配置</NavLink>
      </nav>
      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
        <GoLive />
        <ConnectionBadge />
        <span className="muted">{mode !== "idle" ? `${mode} · ${episodeId ?? ""}` : ""}</span>
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
      style={{ display: "flex", gap: 4 }}
    >
      <input
        data-testid="live-id-input"
        placeholder="episode id 实时"
        value={id}
        onChange={(e) => setId(e.target.value)}
        style={{ fontSize: 12, padding: "2px 6px", background: "#1c212b", color: "var(--text)", border: "1px solid var(--line)", borderRadius: 6 }}
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
