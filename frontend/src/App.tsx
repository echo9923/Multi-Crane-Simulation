import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ConfigurationPage } from "@/components/workbench/ConfigurationPage";
import { DataExportPage } from "@/components/workbench/DataExportPage";
import { ExperimentPage } from "@/components/workbench/ExperimentPage";
import { RunPage } from "@/components/workbench/RunPage";
import { SettingsPage } from "@/components/workbench/SettingsPage";
import { VisualizationPage } from "@/components/workbench/VisualizationPage";
import { WorkbenchShell } from "@/components/workbench/WorkbenchShell";

export function AppRoutes() {
  return (
    <WorkbenchShell>
      <Routes>
        <Route path="/" element={<ExperimentPage />} />
        <Route path="/config" element={<ConfigurationPage />} />
        <Route path="/run" element={<RunPage />} />
        <Route path="/visualization" element={<VisualizationPage />} />
        <Route path="/live/:episodeId" element={<VisualizationPage />} />
        <Route path="/data" element={<DataExportPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<ExperimentPage />} />
      </Routes>
    </WorkbenchShell>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
