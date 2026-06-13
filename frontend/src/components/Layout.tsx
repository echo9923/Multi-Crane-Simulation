// Base layout skeleton: five regions (top bar, left controls, center canvas,
// right panels, bottom timeline). Task 01 only renders placeholders; later
// tasks fill each region. Region ids are stable so integration tests can assert
// presence regardless of what is rendered inside.

import type { ReactNode } from "react";

export function Layout(props: {
  top?: ReactNode;
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
  bottom?: ReactNode;
}) {
  return (
    <div className="app-shell">
      <header className="app-top" data-region="top">
        {props.top ?? <TopPlaceholder />}
      </header>
      <main className="app-main">
        <aside className="app-left" data-region="left">
          {props.left ?? <Placeholder label="场景控制" />}
        </aside>
        <section className="app-center" data-region="center">
          {props.center ?? <Placeholder label="3D 画布" />}
        </section>
        <aside className="app-right" data-region="right">
          {props.right ?? <Placeholder label="状态面板 / 日志" />}
        </aside>
      </main>
      <footer className="app-bottom" data-region="bottom">
        {props.bottom ?? <Placeholder label="时间轴 / 播放控制" />}
      </footer>
    </div>
  );
}

function TopPlaceholder() {
  return (
    <div className="placeholder">
      <strong>群塔仿真 3D 展示</strong>
      <span className="muted">Module N · 前端展示层</span>
    </div>
  );
}

function Placeholder(props: { label: string }) {
  return (
    <div className="placeholder">
      <span className="muted">{props.label}（待实现）</span>
    </div>
  );
}
