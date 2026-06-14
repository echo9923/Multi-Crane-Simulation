from __future__ import annotations

from pathlib import Path

from backend.app.api.cli import EXIT_INPUT_ERROR, build_dataset_from_config
from backend.app.tests.test_moduleO_cli_api import _dataset_config_file


def test_build_dataset_rejects_non_positive_max_episodes_as_input_error(
    tmp_path: Path,
) -> None:
    result = build_dataset_from_config(
        _dataset_config_file(tmp_path),
        source_roots=[tmp_path / "runs"],
        output_root=tmp_path / "datasets",
        max_episodes=0,
        output_json=True,
    )

    assert result.exit_code == EXIT_INPUT_ERROR
    assert "--max-episodes must be positive" in result.stderr
