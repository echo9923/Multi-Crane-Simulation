from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

from backend.app.tests.test_config_schema import FIXTURE_DIR

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_full_pipeline_script_generates_episode_dataset_and_stgnn_index(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "full-pipeline"
    result = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            str(REPO_ROOT / "scripts" / "run_full_pipeline.py"),
            "--config",
            str(FIXTURE_DIR / "demo_valid.yaml"),
            "--episodes",
            "1",
            "--output-root",
            str(output_root),
            "--runner",
            "production",
            "--output-json",
            "--override",
            'scenario.layout={"mode":"manual","num_cranes":2,"overlap_level":"medium","height_strategy":"mixed","coverage_target":"balanced","slew_mode_default":"continuous","max_sampling_attempts":500}',
            "--override",
            'scenario.cranes=[{"crane_id":"C1","model_id":"generic_flat_top_55m","base":[-22,0,0],"mast_height_m":50,"theta_init_deg":30,"slew":{"mode":"continuous"}},{"crane_id":"C2","model_id":"generic_flat_top_55m","base":[-34,0,0],"mast_height_m":54,"theta_init_deg":30,"slew":{"mode":"continuous"}}]',
            "--override",
            'scenario.site.material_zones=[{"zone_id":"mat","type":"box","center":[-35,-10,1],"size":[10,10,2],"z_range_m":[0.5,1.5],"load_types":["rebar_bundle"]}]',
            "--override",
            'scenario.site.work_zones=[{"zone_id":"work","type":"box","center":[5,10,20],"size":[10,10,4],"z_range_m":[18,22],"accepted_load_types":["rebar_bundle"]}]',
            "--override",
            "scenario.tasks.num_tasks_per_crane=1",
            "--override",
            "scenario.tasks.fallback_dropoff_z_range_m=[18,22]",
            "--override",
            'scenario.tasks.queue_policy={"start_mode":"simultaneous","initial_start_jitter_s":[0,0],"inter_task_delay_s":[0,0]}',
            "--override",
            'scenario.tasks.task_type_distribution={"easy_task":1.0,"overlap_task":0.0,"stress_task":0.0}',
            "--override",
            'experiment.sim={"dt":0.1,"duration_s":8.0,"min_duration_s":0.0,"stop_when_all_tasks_done":false,"completion_cooldown_s":0.0,"physics_hz":20,"controller_hz":20,"llm_decision_interval_s":0.5}',
            "--override",
            'experiment.llm={"enabled":true,"provider":"mock","model":"mock-full-pipeline","base_url":"https://api.deepseek.com/v1","api_key_env":null,"api_key":null,"temperature":0.4,"timeout_s":1,"max_retries":0,"max_consecutive_failures":3,"fallback_policy":"neutral_stop","command_duration":{"default_s":1.0,"min_s":0.5,"max_s":3.0},"scheduling":{"mode":"offline_wait","stale_command_max_hold_s":0.5},"structured_output":{"mode":"json_object"},"context":{"history_mode":"none","recent_decisions_full":0,"include_task_history_summary":true,"include_completed_task_summary":true,"include_failed_request_history":true,"include_risk_event_history":true,"summarizer":{"mode":"none","provider":"same_as_operator","fallback":"rule","trigger":{"every_n_decisions":20,"context_over_tokens":12000}}}}',
            "--override",
            'dataset.windows={"input_steps":2,"pred_steps":2,"stride_steps":2,"risk_label_horizons_s":[5,10],"negative_positive_sampling":{"enabled":false,"max_negative_to_positive_ratio":5}}',
            "--override",
            'dataset.split.holdout={"unseen_layout":false,"unseen_num_cranes":false}',
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["run_dirs"]) == 1
    run_dir = Path(payload["run_dirs"][0])
    assert (run_dir / "visual" / "frames.jsonl").is_file()
    assert Path(payload["dataset_dir"]).is_dir()
    assert Path(payload["stgnn_output_root"]).is_dir()
    assert payload["frontend_replay_files"]["frames_jsonl"].endswith(
        "visual/frames.jsonl"
    )

    samples_path = Path(payload["stgnn_output_root"]) / "index" / "samples.parquet"
    rows = pq.read_table(samples_path).to_pylist()
    assert rows
