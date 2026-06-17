import { useEffect, useState } from "react";

import {
  downloadEpisode,
  getEpisodeState,
  listDesktopRunFiles,
  listDesktopRuns,
} from "@/api/rest";
import { useWorkbenchStore } from "@/state/workbench";
import type { DesktopRunFile, DesktopRunItem } from "@/types/api";

function displayValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const code =
    error && typeof error === "object"
      ? (error as { code?: unknown }).code
      : null;
  return typeof code === "string" && code ? `${code}: ${message}` : message;
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

const researchModules = [
  { id: "K", title: "K 离线风险标签" },
  { id: "O", title: "O 数据集构建" },
  { id: "P", title: "P 训练样本转换" },
];

export function DataExportPage() {
  const currentEpisode = useWorkbenchStore((s) => s.currentEpisode);
  const episodeState = useWorkbenchStore((s) => s.episodeState);
  const setEpisodeState = useWorkbenchStore((s) => s.setEpisodeState);
  const [runs, setRuns] = useState<DesktopRunItem[]>([]);
  const [files, setFiles] = useState<DesktopRunFile[]>([]);
  const [status, setStatus] = useState<string>(
    currentEpisode ? "已选择当前 Episode，可刷新文件清单。" : "暂无当前 Episode，请先启动或选择一次运行。",
  );
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const episodeId = episodeState?.episode_id ?? currentEpisode?.episode_id ?? null;
  const currentStatus = episodeState?.status ?? currentEpisode?.status ?? null;
  const runDir = episodeState?.run_dir ?? currentEpisode?.run_dir ?? null;

  useEffect(() => {
    const id = currentEpisode?.episode_id;
    if (!id) return;
    let cancelled = false;
    getEpisodeState(id)
      .then((state) => {
        if (!cancelled) setEpisodeState(state);
      })
      .catch(() => {
        // User-triggered refresh actions surface errors; entry refresh stays quiet.
      });
    return () => {
      cancelled = true;
    };
  }, [currentEpisode?.episode_id, setEpisodeState]);

  const runAction = async (name: string, action: () => Promise<void>) => {
    if (busyAction) return;
    setBusyAction(name);
    try {
      await action();
    } catch (error) {
      setStatus(errorMessage(error));
    } finally {
      setBusyAction(null);
    }
  };

  const refreshRuns = () =>
    runAction("runs", async () => {
      const result = await listDesktopRuns();
      setRuns(result.items);
      setStatus(`已刷新运行列表：${result.items.length} 条。`);
    });

  const refreshFiles = () =>
    runAction("files", async () => {
      if (!episodeId) {
        setStatus("暂无当前 Episode，无法刷新文件清单。");
        return;
      }
      const result = await listDesktopRunFiles(episodeId);
      setFiles(result.files);
      setStatus(`已刷新 ${episodeId} 文件清单：${result.files.length} 个文件。`);
    });

  const downloadZip = () =>
    runAction("download", async () => {
      if (!episodeId) {
        setStatus("暂无当前 Episode，无法下载 zip。");
        return;
      }
      const blob = await downloadEpisode(episodeId, {
        include_logs: true,
        include_data: true,
        include_visual: true,
      });
      if (
        typeof URL === "undefined" ||
        typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function"
      ) {
        setStatus("当前环境无法创建下载链接，请在支持浏览器下载的环境中重试。");
        return;
      }
      const href = URL.createObjectURL(blob);
      try {
        const link = document.createElement("a");
        link.href = href;
        link.download = `${episodeId}.zip`;
        if (typeof link.click !== "function") {
          setStatus("当前环境无法触发浏览器下载，请手动使用导出接口。");
          return;
        }
        link.click();
        setStatus(`已准备下载 ${episodeId}.zip。`);
      } finally {
        URL.revokeObjectURL(href);
      }
    });

  const openRunDir = () =>
    runAction("open", async () => {
      if (!runDir) {
        setStatus("当前 Episode 没有 run_dir，无法打开 run 目录。");
        return;
      }
      if (!window.multiCraneDesktop?.openPath) {
        setStatus("浏览器模式无法打开本地目录，请在桌面端使用或手动打开 run_dir。");
        return;
      }
      const result = await window.multiCraneDesktop.openPath(runDir);
      setStatus(
        result.ok
          ? `已请求打开 run 目录：${runDir}`
          : `打开 run 目录失败：${result.error ?? "unknown error"}`,
      );
    });

  return (
    <section className="workbench-page">
      <header className="workbench-page-header">
        <h1>数据/导出</h1>
        <p className="muted">汇总 Episode 数据、日志和导出产物。</p>
      </header>

      <div className="workbench-config-toolbar">
        <button type="button" onClick={refreshRuns} disabled={busyAction !== null}>
          刷新运行列表
        </button>
        <button type="button" onClick={refreshFiles} disabled={busyAction !== null}>
          刷新文件清单
        </button>
        <button type="button" onClick={downloadZip} disabled={busyAction !== null}>
          下载 zip
        </button>
        <button type="button" onClick={openRunDir} disabled={busyAction !== null}>
          打开 run 目录
        </button>
        {busyAction ? <span className="chip">处理中</span> : null}
      </div>

      <div className="workbench-notice" role="status">
        {status}
      </div>

      <div className="workbench-panel">
        <h2>当前 Episode</h2>
        <dl className="workbench-summary-grid">
          <div>
            <dt>Episode</dt>
            <dd>{displayValue(episodeId)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{displayValue(currentStatus)}</dd>
          </div>
          <div>
            <dt>Run Dir</dt>
            <dd>{displayValue(runDir)}</dd>
          </div>
          <div>
            <dt>Config Hash</dt>
            <dd>{displayValue(currentEpisode?.resolved_config_hash)}</dd>
          </div>
        </dl>
      </div>

      <div className="workbench-panel">
        <h2>运行列表</h2>
        {runs.length > 0 ? (
          <table aria-label="运行列表">
            <thead>
              <tr>
                <th>Episode</th>
                <th>Status</th>
                <th>Path</th>
                <th>Created</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={`${run.episode_id}-${run.path}`}>
                  <td>{run.episode_id}</td>
                  <td>{displayValue(run.status)}</td>
                  <td>{run.path}</td>
                  <td>{displayValue(run.created_at)}</td>
                  <td>{run.summary_available ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">尚未加载运行列表。</p>
        )}
      </div>

      <div className="workbench-panel">
        <h2>文件清单</h2>
        {files.length > 0 ? (
          <table aria-label="文件清单">
            <thead>
              <tr>
                <th>Path</th>
                <th>Kind</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.path}>
                  <td>{file.relative_path}</td>
                  <td>{file.kind}</td>
                  <td>{formatBytes(file.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">尚未加载文件清单。</p>
        )}
      </div>

      <div className="workbench-panel">
        <h2>研究数据入口</h2>
        <div className="workbench-module-grid">
          {researchModules.map((module) => (
            <div className="workbench-module-card" key={module.id}>
              <span className="workbench-module-id">{module.title}</span>
              <span className="chip">预留入口</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
