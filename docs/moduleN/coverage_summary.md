# Module N Coverage Summary

## 测试分层

- **单元测试（Vitest + jsdom）**：`npm test`。覆盖纯逻辑与 Three.js 场景图（注入桩渲染器，无需 WebGL），共 119 条用例全绿。
- **端到端（Playwright + headless Chromium，软件 WebGL）**：`npm run e2e`（首次需 `npx playwright install chromium`）。覆盖浏览器真实渲染与交互冒烟。

## 覆盖范围（单元）

- **坐标与合同**：`worldToThree`/`threeToWorld` 互逆与右手性；`SimFrame`/`SimFrameCrane`/`SimFramePair`/`SimFrameWeather` 字段键集与后端 `recorder.py` 1:1；fixture 为 ≥3 塔合法 episode。
- **静态场景**：塔吊数量随配置变化（N=1/3/6，不硬编码）；塔身/起重臂/平衡臂/小车/吊钩几何与 `base/root/tip`、`mast/jib/counter` 尺寸一致；作业半径圆 = `trolley_r_max_m`（缺失回落 `jib_length_m`）；zones（box/polygon/overlap）按 kind 着色，未知类型跳过并计数；工地边界 AABB + 地面网格；glTF 替换接口（`registerCraneAsset`）注入与回落。
- **动态更新**：`applyFrame` 由 `base/root/tip/hook` 直驱姿态；吊物按 `shape`（box_long/flat_box/cylinder/beam）× `load_size_m` 渲染，未知 shape 回落包围盒；塔臂尾迹 FIFO 封顶；风向箭头随 `wind_direction_deg`；缺塔保形不崩；实时与离线同一 `applyFrame` 路径。
- **风险可视化**：6 级 `RiskLevel` 各有颜色/不透明度/线宽；`near_miss`/`collision` 脉冲；连线按 `pair` 增删；`showRisk` 开关；`risk_level_now=null` 弱化；重叠区渲染；`offline_labels` 非空的实时帧被拒。
- **面板**：塔吊/任务/风险面板字段正确；LLM 指令日志六段（observation/messages/raw_response/parsed_command/executed_command/validation_errors）展开/折叠、缺失段降级、密钥遮蔽；事件日志点击跳转 `time_s` 并高亮塔吊；`current_command` 降级路径。
- **离线回放**：`parseFramesJsonl`（跳过坏行 + 计数）、`loadEpisodeFromFiles`、`loadEpisodeFromZip`（fflate，缺 visual/metadata 各降级）；`seekIndexByTime` 二分边界；`PlaybackController.tick` 按 `speed×时间` 推进并在末帧停止。
- **WebSocket 实时**：`sim_frame`/`error`/`heartbeat` 分类；指数退避重连序列（可控时钟）；达 `maxAttempts` 停止；心跳超时触发重连；`stop()` 不再重连；`offline_labels` 非空拒绝。
- **交互与导出**：REST 成功解包 / `M_E_*` → `ApiClientError` / 网络错误 `N_E_TRANSPORT`；`downloadEpisode` ok 返回 Blob、!ok → `M_E_DOWNLOAD_FAILED`；`pickCrane` 命中塔吊、`followCrane` 移动相机；配置上传解析 JSON/YAML、`scrubSecrets` 遮蔽、combined/bare 拆分；ConfigPage 展示 valid/errors/M_E 错误。
- **跨任务验收**：离线完整链路（parse→load→applyFrame→seek）；实时链路（WS→store→controller→重连）；坐标一致（hook world↔three 精确互逆，且控制器摆放的 hook 世界坐标等于帧 ENU hook，5mm 容差，源于字段取整）；多塔 N=1/3/6。

## 覆盖范围（端到端）

- 自动加载 demo episode，渲染 `<canvas>` 与塔吊/任务/风险/事件面板（C1/C2/C3、`display-only`、`risk_snapshot`）。
- 时间轴播放推进（`▶`→时间/帧计数变化）。
- 塔吊列表点击选中 + 跟随切换（“跟随”徽标出现）。

> 说明：后端实时 WS 推送在 Module M 当前为 stub（adapter 抛 `NotImplementedError`），因此真实 `/live/:id` 连接会进入重连循环——这是 M 的待办，N 的客户端按既定合同消费并通过；e2e 以离线 demo 为主路径。后端无 CORS / 无 episode 列表端点 / 起始需 `config_path` 等缺口在前端通过 dev proxy、按 id/本地文件加载规避，不改后端。

## 未覆盖范围

- **真实后端联调**：单测/e2e 使用 fixture 与 mock WS / mock fetch；与运行中的 M 后端（真实 `validate`/`download`/WS 推送）的端到端联通需在集成环境验证，属 M 的可用性范畴。
- **真实 LLM 网络调用**：N 只展示已落盘/已推送的指令日志，不调用 provider（归 G）。
- **真实物理/风险计算**：N 只展示 `pairs` 已有字段（display-only），不计算距离/TTC/碰撞（归 H/K/J）。
- **生产部署 CORS**：dev proxy 解决开发期跨域；生产部署的反向代理/CORS 配置不在 N 范围。
- **大规模性能压测**：覆盖 N=6、30 帧；数十台塔吊 / 万级帧的帧率与内存应在真实数据规模下另做基准。
- **glTF 资产本身**：仅验证替换接口（注册即用、回落程序几何）；具体 GLB 文件的美术/材质不在范围。

## 运行命令

```bash
cd frontend
npm install            # 依赖
npm test               # Vitest 单元（119 条）
npm run typecheck      # tsc --noEmit
npm run build          # 生产构建
npx playwright install chromium   # 一次性
npm run e2e            # Playwright 端到端冒烟
```
