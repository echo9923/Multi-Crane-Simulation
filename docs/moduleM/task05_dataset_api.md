# Task 05：Dataset 查询 API

## 任务目标

实现数据集列表与 summary 查询 API，读取 Module O 生成的数据集元数据或已有 `dataset_summary.json`，同时明确 M 不构建数据集。

## 范围：做什么 / 不做什么

做：

- 实现 `GET /datasets`。
- 实现 `GET /datasets/{dataset_id}/summary`。
- 定义本地 dataset root 发现策略。
- 读取 `metadata/dataset_summary.json` 或 O 暴露的 dataset catalog。
- 支持分页参数 `limit`、`offset`。
- 当 O 尚未实现时，返回明确的 `M_E_DATASET_NOT_IMPLEMENTED` 或基于文件系统的只读降级结果。

不做：

- 不运行 K 离线标签生成。
- 不运行 O dataset builder。
- 不切分 train/val/test。
- 不构造 STGNN window。
- 不修改 dataset_summary。

## 接口与数据结构（签名级别）

```python
@router.get("/datasets")
def list_datasets(limit: int = 50, offset: int = 0) -> ApiResponse: ...
```

返回 `DatasetListResponse`：

```json
{
  "items": [
    {
      "dataset_id": "tower_crane_llm_dataset_v1",
      "path": "runs/datasets/tower_crane_llm_dataset_v1",
      "created_at": "2026-06-13T12:00:00Z",
      "num_episodes": 12,
      "summary_available": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

```python
@router.get("/datasets/{dataset_id}/summary")
def get_dataset_summary(dataset_id: str) -> ApiResponse: ...
```

读取优先级：

1. O 的 dataset catalog/service，如果阶段三已存在。
2. 配置的 dataset root 下 `{dataset_id}/metadata/dataset_summary.json`。
3. run 目录聚合位置中的 `metadata/dataset_summary.json`，仅作为只读兼容。

## 前置依赖

- Task 01 的 dataset API schema。
- Task 02 的 app/error handler。
- Module A 的 `DatasetConfig` 字段语义。
- Module L 对 `metadata/dataset_summary.json` 的预留路径。
- Module O 的 dataset summary 合同；如果 O 未实现，本任务必须把降级行为写清楚并测试。

## 验收标准（具体、可测试）

- `GET /datasets` 返回统一成功结构。
- `limit`、`offset` 使用 Task 01 的分页约束。
- dataset root 为空时返回空列表，不报 500。
- 存在一个含 `metadata/dataset_summary.json` 的 dataset 目录时，列表项 `summary_available=true`。
- `GET /datasets/{dataset_id}/summary` 返回 summary dict。
- 不存在 dataset 返回 404 与 `M_E_DATASET_NOT_FOUND`。
- O 未实现且未配置文件系统降级时，返回 501 与 `M_E_DATASET_NOT_IMPLEMENTED`。
- dataset_id 不允许路径穿越。

## 测试要点（正常 + 边界 + 异常）

- 正常：tmp_path 下创建两个 dataset，分页返回第一个。
- 正常：summary JSON 可读取并原样放入 `summary` 字段。
- 边界：空 dataset root。
- 边界：summary 缺失时列表仍出现 item，但 `summary_available=false`。
- 异常：非法 dataset_id。
- 异常：summary JSON 非法，返回统一错误。
- 异常：未配置 dataset root 且 O service 不可用，返回 not implemented。

## 依赖关系

Task 05 依赖 Task 01 和 Task 02，可与 Task 03/04 并行实现。Task 08 需要覆盖 dataset API 的正常、空列表和未实现/不存在路径。
