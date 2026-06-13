# 测试风险与缺口清单 2026-06-13

## 当前结论

当前全量测试已经通过：

```text
895 passed, 1 warning
```

本清单记录的是自动化测试仍未完全证明的区域，用于后续模块推进和回归设计，不表示当前实现失败。

## 风险 1：真实外部 LLM provider 未默认集成测试

状态：有意不覆盖。

原因：

- 默认测试不能依赖外部网络、账号、API key 和第三方服务稳定性。
- 当前测试重点覆盖 provider wrapper、命令解析、fallback、重试和 secret 防泄漏。

后续建议：

- 增加 `pytest -m external` 或单独脚本。
- 只在显式提供测试 key 的环境运行。
- 所有请求/响应必须经过 secret scrub 和日志审查。

## 风险 2：生产级长 episode 性能未建基线

状态：弱覆盖。

当前覆盖：

- Module L 有 50 step 高频写入测试。
- Module J/L/M 有小 episode 集成测试。

缺口：

- 没有百万帧、多 episode、大 Parquet 文件的吞吐和文件大小基准。
- 没有 API 多客户端长时间 WebSocket 压测。

后续建议：

- 增加 `docs/testing/performance_baseline_*.md`。
- 固定场景、帧数、输出大小、耗时和机器配置。
- 性能测试不要默认进入普通单元测试。

## 风险 3：Module O/N/P 尚未进入完整链路

状态：后续模块职责。

当前覆盖：

- M 的 dataset API 有 filesystem fallback 和 O 未实现的明确错误。
- L 已产出训练主表和可视化帧。

缺口：

- O 的 dataset split/window/export 还没有端到端验收。
- N 的真实前端渲染没有纳入测试。
- P 的训练入口和模型评估没有纳入测试。

后续建议：

- O 完成后补 `run_dir -> dataset summary -> graph window` 验收。
- N 完成后补 Playwright/browser smoke test，验证 frames/WebSocket 能真实渲染。
- P 完成后补 tiny dataset 训练 smoke，不要求性能，只验证接口闭合。

## 风险 4：文件系统真实故障只用 monkeypatch 模拟

状态：部分覆盖。

当前覆盖：

- L 用 monkeypatch 模拟 Parquet 写失败。
- M 用 monkeypatch 模拟下载归档写入失败。

缺口：

- 未真实模拟磁盘满、权限变化、网络盘中断、跨平台路径异常。

后续建议：

- 在 CI 或本地专项测试中用临时只读目录和受限 quota 环境验证。
- 保留 monkeypatch 单元测试作为快速回归。

## 风险 5：依赖升级兼容性

状态：需持续关注。

当前情况：

- Python 3.13 下 `pyarrow>=18.1,<19` 已验证可安装并通过 L acceptance。
- FastAPI TestClient 当前有 Starlette/httpx deprecation warning。

后续建议：

- 升级 FastAPI/Starlette/httpx 前先跑 Module M 和全量测试。
- 将 warning 记录为依赖维护项，不在普通业务改动中顺手大升级。

## 风险 6：默认本地 runner 是 deterministic 短 episode

状态：有意降级。

当前覆盖：

- CLI 默认 runner 可以运行、输出 JSON、写 summary 和 `visual/frames.jsonl`。
- API 默认 runner autostart/cold stop 可产生 run_dir 和帧/summary。

缺口：

- 默认 runner 不调用真实外部 LLM。
- 默认 runner 不生成真实任务队列。
- 默认 runner 使用轻量 recorder，不替代 Module L 生产 Parquet recorder。

后续建议：

- 当任务生成、真实 operator provider、生产 recorder 的服务装配入口稳定后，再增加 production runner factory。
- 保留当前 deterministic runner 作为本地 smoke/CI 入口，避免测试依赖外部服务。
