import { useEffect } from "react";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { SceneView } from "@/components/SceneView";
import { LeftControls } from "@/components/LeftControls";
import { Panels } from "@/components/panels/Panels";
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
      <span className="muted" style={{ marginLeft: "auto" }}>
        {mode !== "idle" ? `${mode} · ${episodeId ?? ""}` : ""}
      </span>
    </>
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
    />
  );
}

function ConfigPage() {
  return (
    <Layout
      top={<TopNav />}
      center={
        <div className="placeholder" style={{ padding: 24 }}>
          场景配置上传 / 选择入口（Task 08 实现）
        </div>
      }
    />
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </BrowserRouter>
  );
}
