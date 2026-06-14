from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
from pydantic import Field

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
    TrainingBaseModel,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeTables


class VariableNodePlan(TrainingBaseModel):
    strategy: str = "pad_and_mask"
    max_nodes: int = Field(gt=0)
    crane_order_by_episode: dict[str, list[str]]


class VariableNodeStrategy:
    def plan(
        self,
        *,
        windows: Sequence[DatasetWindowIndexRow],
        episode_cranes: Mapping[str, Sequence[str]],
        configured_max_nodes: int | None = None,
    ) -> VariableNodePlan:
        crane_order_by_episode: dict[str, list[str]] = {}
        max_observed = 0
        for window in windows:
            cranes = episode_cranes.get(window.episode_id)
            if cranes is None:
                raise TrainingConversionError(
                    TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                    "missing crane order for episode",
                    details={"episode_id": window.episode_id},
                )
            order = _stable_crane_order(cranes)
            if len(order) != window.num_cranes:
                raise TrainingConversionError(
                    TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                    "window num_cranes does not match episode crane list",
                    details={
                        "episode_id": window.episode_id,
                        "expected": window.num_cranes,
                        "actual": len(order),
                    },
                )
            previous = crane_order_by_episode.get(window.episode_id)
            if previous is not None and previous != order:
                raise TrainingConversionError(
                    TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                    "episode crane order is inconsistent across windows",
                    details={"episode_id": window.episode_id},
                )
            crane_order_by_episode[window.episode_id] = order
            max_observed = max(max_observed, len(order))

        max_nodes = configured_max_nodes or max_observed
        if max_nodes <= 0:
            raise TrainingConversionError(
                TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                "max_nodes must be positive",
                details={"max_observed_nodes": max_observed},
            )
        if max_observed > max_nodes:
            raise TrainingConversionError(
                TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                "configured max_nodes is smaller than observed crane count",
                details={
                    "max_observed_nodes": max_observed,
                    "configured_max_nodes": max_nodes,
                },
            )
        return VariableNodePlan(
            max_nodes=max_nodes,
            crane_order_by_episode=crane_order_by_episode,
        )

    def crane_order_for_window(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
    ) -> list[str]:
        cranes = _stable_crane_order(
            row["crane_id"] for row in tables.trajectories.to_pylist()
        )
        if len(cranes) != window.num_cranes:
            raise TrainingConversionError(
                TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
                "window num_cranes does not match trajectory crane count",
                details={
                    "episode_id": window.episode_id,
                    "expected": window.num_cranes,
                    "actual": len(cranes),
                },
            )
        return cranes

    def node_mask(self, *, crane_order: Sequence[str], max_nodes: int) -> np.ndarray:
        _validate_mask_bounds(crane_order=crane_order, max_nodes=max_nodes)
        mask = np.zeros((max_nodes,), dtype=bool)
        mask[: len(crane_order)] = True
        return mask

    def edge_mask(self, *, crane_order: Sequence[str], max_nodes: int) -> np.ndarray:
        _validate_mask_bounds(crane_order=crane_order, max_nodes=max_nodes)
        mask = np.zeros((max_nodes, max_nodes), dtype=bool)
        real_nodes = len(crane_order)
        for src in range(real_nodes):
            for dst in range(real_nodes):
                if src != dst:
                    mask[src, dst] = True
        return mask


def _validate_mask_bounds(*, crane_order: Sequence[str], max_nodes: int) -> None:
    if max_nodes <= 0 or len(crane_order) > max_nodes:
        raise TrainingConversionError(
            TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
            "crane_order does not fit max_nodes",
            details={"num_cranes": len(crane_order), "max_nodes": max_nodes},
        )


def _stable_crane_order(cranes: Sequence[str] | object) -> list[str]:
    return sorted({str(crane) for crane in cranes})


__all__ = ["VariableNodePlan", "VariableNodeStrategy"]
