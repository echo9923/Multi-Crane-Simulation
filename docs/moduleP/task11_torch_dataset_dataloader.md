# Task 11：PyTorch Dataset / DataLoader 适配层

## 任务目标

在核心转换逻辑与 PyTorch 解耦的前提下，提供可直接用于训练脚本的 `StgnnTorchDataset`、`stgnn_collate_fn` 和轻量 DataLoader 工厂。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/torch_dataset.py`。
- 仅在该文件中导入 `torch`。
- 支持从内存 `StgnnTensorSample` 列表或 converter 输出目录加载样本。
- `__getitem__` 返回 tensors 和 metadata。
- `stgnn_collate_fn` 叠 batch 维度，保留 metadata list。
- 支持按 split 过滤。

不做：

- 不实现模型结构或训练循环。
- 不在 core converter 中强制依赖 torch。
- 不做分布式 sampler 或复杂 bucket sampler。
- 不改变 tensor 内容、label 或 split。

## 接口与数据结构（签名级别）

```python
class StgnnTorchDataset(torch.utils.data.Dataset):
    def __init__(
        self,
        samples_or_root: Sequence[StgnnTensorSample] | Path,
        *,
        split: str | None = None,
        load_tensors: bool = True,
    ) -> None: ...

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> dict[str, Any]: ...


def stgnn_collate_fn(batch: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


def build_stgnn_dataloader(
    samples_or_root: Sequence[StgnnTensorSample] | Path,
    *,
    split: str | None = None,
    batch_size: int = 32,
    shuffle: bool = False,
    num_workers: int = 0,
) -> torch.utils.data.DataLoader: ...
```

`__getitem__` 返回：

```python
{
    "X_node": torch.FloatTensor,
    "X_edge": torch.FloatTensor,
    "A_phy": torch.FloatTensor,
    "Y_traj": torch.FloatTensor,
    "Y_risk": torch.FloatTensor,
    "node_mask": torch.BoolTensor,
    "edge_mask": torch.BoolTensor,
    "risk_mask": torch.BoolTensor,
    "metadata": dict,
}
```

## 前置依赖

- Task 01 training schema。
- Task 08 variable node strategy。
- Task 09 metadata/index。
- Task 10 converter output.
- Optional PyTorch dependency in test environment.

## 验收标准（具体、可测试）

- 核心模块 `backend.app.training.converter` 可在未安装 torch 时 import。
- `backend.app.training.torch_dataset` 在未安装 torch 时给出明确错误。
- 内存样本 dataset 的 `len()` 正确。
- `__getitem__` 返回 torch tensor，dtype 符合约定。
- `stgnn_collate_fn` 生成 batch shape `[B, ...]`。
- metadata 作为 list 保留，不被 tensor 化。
- split filter 只返回指定 split。
- DataLoader 可迭代一个 batch。

## 测试要点（正常 + 边界 + 异常）

正常：

- 两个同 shape 样本 collate。
- train/val split filter。
- DataLoader batch_size=2。

边界：

- batch_size=1。
- 单塔吊样本 edge_mask 全 false。
- `shuffle=False` 保持 sample index 顺序。

异常：

- 样本 shape 不一致时 collate 报明确错误。
- 缺少 tensor 文件时 dataset construction 失败。
- torch 未安装时 core import 不受影响。

## 依赖关系

依赖 Task 01、Task 08、Task 09、Task 10。它是第一阶段实现链路的最后任务之一。
