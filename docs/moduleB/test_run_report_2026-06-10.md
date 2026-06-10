# Module B 测试记录 2026-06-10

## 本轮新增测试目标

- 补充 `load_chart_points` 从场景配置到 resolved layout 的合同测试。
- 补充 reachability 对自定义载荷曲线的承载能力校验。
- 补充 resolved layout 输出结构、模型快照和 hash 变化测试。
- 补充 reachability 对 box / polygon 代表点、多吊机分区覆盖和小车最小半径的测试。
- 补充 auto layout diagnostics 的 reachability warning、pair id、quality score 和失败统计测试。

## 运行记录

- `python3 -m pytest backend/app/tests/test_moduleB_load_chart_extra.py backend/app/tests/test_moduleB_resolved_layout_extra.py backend/app/tests/test_moduleB_reachability_zone_extra.py backend/app/tests/test_moduleB_auto_layout_diagnostics_extra.py -q`
  - 第一轮：`3 failed, 13 passed`
  - 失败集中在 `crane_models[0].load_chart_points` 被 `ScenarioConfig` 拒绝。
- 修复后再次运行新增测试：
  - `17 passed in 0.27s`
- `python3 -m pytest backend/app/tests/test_config_schema.py backend/app/tests/test_crane_model.py backend/app/tests/test_crane_config_resolution.py backend/app/tests/test_auto_layout.py backend/app/tests/test_layout_reachability.py backend/app/tests/test_moduleB_acceptance.py backend/app/tests/test_moduleB_load_chart_extra.py backend/app/tests/test_moduleB_resolved_layout_extra.py backend/app/tests/test_moduleB_reachability_zone_extra.py backend/app/tests/test_moduleB_auto_layout_diagnostics_extra.py -q`
  - 第一轮：`3 failed, 56 passed`
  - 失败集中在 high-overlap auto layout 候选全部被 reachability precheck 拦截。
  - 修复后：`76 passed in 0.75s`

## 问题记录

- 发现问题 1：`CraneModelSpec` 和文档合同支持 `load_chart_points`，但 `ScenarioConfig.crane_models[]` 输入 schema 没有该字段，导致 YAML/原始 dict 配置无法传入自定义载荷曲线。
  - 修复：在 `backend/app/schemas/config.py` 增加 `CraneModelLoadChartPointInput`，并在 `CraneModelConfigInput` 暴露 `load_chart_points`。
- 发现问题 2：reachability precheck 使用 serialized model payload 计算容量时没有读取 `load_chart_points`，只走默认 `max_load_t/tip_load_t` 线性规则。
  - 修复：`backend/app/sim/layout_reachability.py` 增加 serialized payload 的点表插值能力。
- 发现问题 3：reachability 的载重判断原先把 material/work 可达半径混在一起取最大容量，可能出现“取料点近、落料点远但超载”仍误判通过。
  - 修复：按 material side 和 work side 分别计算可承载 crane ids，要求两侧都至少有可承载吊机。
- 发现问题 4：增强 reachability 严格度后，high-overlap auto layout 由于固定围绕 site center 采样，可能无法覆盖 fixture 中偏离中心的 material/work zone。
  - 修复：auto layout 的候选圆心改为 material/work zone 的二维几何锚点平均值，仍保留 deterministic seed 和原 overlap/coverage 策略。
