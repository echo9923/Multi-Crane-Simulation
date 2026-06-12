# Module L Coverage Summary

## 覆盖范围

本轮阶段四补充覆盖了 Module L 的跨任务集成、端到端链路、高频写入和错误路径。

- Schema 严格性：`SimFrame`、Parquet 行、JSONL 行、`EpisodeSummary` 和 `DataExportWarning` 均覆盖 `extra="forbid"` 与 NaN/Inf 拒绝或清洗路径。
- Run 目录：覆盖 `config/`、`metadata/`、`logs/`、`data/`、`replay/`、`visual/` 创建，`resolved_config.yaml`、`episode_metadata.json` 写入，以及 secret masking。
- Parquet：覆盖 `trajectories.parquet`、`pair_risks.parquet`、`graph_edges.parquet`、`tasks.parquet`、`weather.parquet` 的追加、flush、schema_version 列、NaN/Inf 转 null 和 schema mismatch。
- JSONL：覆盖 `llm_observations.jsonl`、`llm_decisions.jsonl`、`commands.jsonl`、`interventions.jsonl`、`events.jsonl` 的 UTF-8、schema_version、secret key 拒绝和 NaN/Inf 转 null。
- SimFrame：覆盖 crane/weather/pair/event 映射、`visual/frames.jsonl` 写入、`episode_manifest.json` 写入，以及实时帧禁止 offline labels。
- EpisodeSummary：覆盖任务完成率、风险等级比例、near miss、collision、LLM 调用数、latency、cache、operator profile、warning、has_nan/has_inf 和 replay availability。
- Recorder orchestrator：覆盖 `record_initial_frame()`、`record_step()`、`write_offline_labels()`、`finalize()` 的组合链路，并验证输入 `CraneState` 不被修改。
- J -> L 集成：使用 `EpisodeRunner` 与真实 `Recorder` 跑完整 episode，验证 J 调度帧进入 L 后生成 frames、manifest、trajectories、weather 和 summary。
- 全出口记录：覆盖 `record_step()` 同时接收 observations、LLM call records、executed commands、interventions、online risk 和 events 后写入所有 L 文件面。
- 高频/边界：覆盖 50 个 step 的快速帧写入，验证轨迹行数、frames 行数和 offline labels 隔离。
- 写入失败：通过 monkeypatch Parquet 写入模拟磁盘写失败，验证抛出 `DataExportError` 且不留下被误认为完成的权威 Parquet 文件。

## 未覆盖范围

以下内容没有在本阶段用自动化测试真实覆盖，原因是它们需要外部系统或属于后续模块职责。

- 真实磁盘满、文件系统权限变化和网络盘异常：当前用 monkeypatch `pyarrow.parquet.write_table` 模拟写失败，覆盖 L 的错误映射和权威文件保护策略。
- 真实前端渲染：本阶段只验证 `SimFrame` 与 `visual/frames.jsonl` schema；3D/Canvas/WebSocket 渲染属于 Module N。
- 真实 LLM 网络调用：L 只记录上游 G 产出的对象，不调用 provider；网络行为属于 Module G。
- 离线标签计算：L 只写入 K 生成的 `OfflineRiskLabel`；标签生成质量属于 Module K。
- dataset split 和 STGNN window 转换：L 只产出训练主表；数据集切分和图窗口转换属于 Module O/P。
- 大规模性能压测：本阶段覆盖高频小 episode 写入；百万级 episode/多 GB Parquet 性能应在数据集生成阶段另做基准。
