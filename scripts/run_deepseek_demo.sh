#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_deepseek_demo.sh [options]

Options:
  --no-dashboard     Start in the background and print paths only.
  --package-latest   Package the latest deepseek-real-flow run for frontend import.
  --help            Show this help message.

Default behavior:
  Starts the real DeepSeek 4-crane demo, shows a live dashboard in this terminal,
  writes complete data under runs/, and automatically packages the run into
  deepseek-real-flow-import.zip after the episode exits successfully.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SHOW_DASHBOARD=true
PACKAGE_LATEST=false
DASHBOARD_SECONDS=""
for arg in "$@"; do
  case "$arg" in
    --no-dashboard)
      SHOW_DASHBOARD=false
      ;;
    --package-latest)
      PACKAGE_LATEST=true
      ;;
    --dashboard-seconds=*)
      DASHBOARD_SECONDS="${arg#*=}"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

find_latest_run_dir() {
  find runs -maxdepth 2 -type d -path 'runs/deepseek-real-flow-*/cli-episode' \
    2>/dev/null | sort -r | head -n 1
}

package_run() {
  local run_dir="$1"
  if [[ -z "$run_dir" || ! -d "$run_dir" ]]; then
    echo "Run directory not found: $run_dir" >&2
    exit 1
  fi
  if [[ ! -s "$run_dir/visual/frames.jsonl" ]]; then
    echo "Cannot package: $run_dir/visual/frames.jsonl is missing or empty." >&2
    exit 1
  fi
  if [[ ! -s "$run_dir/visual/episode_manifest.json" ]]; then
    echo "Cannot package: $run_dir/visual/episode_manifest.json is missing." >&2
    echo "The episode probably has not finished yet." >&2
    exit 1
  fi

  local zip_path="$run_dir/deepseek-real-flow-import.zip"
  (
    cd "$run_dir"
    rm -f deepseek-real-flow-import.zip
    zip -q -r deepseek-real-flow-import.zip \
      visual/frames.jsonl \
      visual/episode_manifest.json \
      logs/commands.jsonl \
      logs/events.jsonl \
      logs/llm_decisions.jsonl \
      logs/llm_observations.jsonl \
      metadata/episode_metadata.json \
      metadata/episode_summary.json \
      config/scenario.yaml \
      config/experiment.yaml \
      config/resolved_config.yaml
  )
  echo "ZIP_READY=$zip_path"
}

if [[ "$PACKAGE_LATEST" == true ]]; then
  latest_run_dir="$(find_latest_run_dir)"
  package_run "$latest_run_dir"
  exit 0
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Cannot find executable .venv/bin/python. Create the venv or run from the project root." >&2
  exit 1
fi

if [[ ! -f ".env.local" ]]; then
  echo "Cannot find .env.local. It must define DEEPSEEK_API_KEY." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env.local
set +a

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is not set after loading .env.local." >&2
  exit 1
fi

mkdir -p runs

RUN_TAG="deepseek-real-flow-$(date +%Y%m%d-%H%M%S)"
RUN_ROOT="runs/$RUN_TAG"
RUN_DIR="$RUN_ROOT/cli-episode"
LOG_FILE="runs/$RUN_TAG.log"
PID_FILE="runs/$RUN_TAG.pid"

run_episode_and_package() {
  .venv/bin/python scripts/run_episode.py \
    --config configs/deepseek_demo_4x2_manual.yaml \
    --runner production \
    --override experiment.output.run_root="$RUN_ROOT" \
    --output-json

  package_run "$RUN_DIR"
}

echo "RUN_ROOT=$RUN_ROOT"
echo "RUN_DIR=$RUN_DIR"
echo "LOG_FILE=$LOG_FILE"

nohup bash -c '
  set -euo pipefail
  cd "$1"
  RUN_ROOT="$2"
  RUN_DIR="$3"
  .venv/bin/python scripts/run_episode.py \
    --config configs/deepseek_demo_4x2_manual.yaml \
    --runner production \
    --override experiment.output.run_root="$RUN_ROOT" \
    --output-json

  if [[ ! -s "$RUN_DIR/visual/frames.jsonl" ]]; then
    echo "Cannot package: $RUN_DIR/visual/frames.jsonl is missing or empty." >&2
    exit 1
  fi
  if [[ ! -s "$RUN_DIR/visual/episode_manifest.json" ]]; then
    echo "Cannot package: $RUN_DIR/visual/episode_manifest.json is missing." >&2
    echo "The episode probably has not finished yet." >&2
    exit 1
  fi
  (
    cd "$RUN_DIR"
    rm -f deepseek-real-flow-import.zip
    zip -q -r deepseek-real-flow-import.zip \
      visual/frames.jsonl \
      visual/episode_manifest.json \
      logs/commands.jsonl \
      logs/events.jsonl \
      logs/llm_decisions.jsonl \
      logs/llm_observations.jsonl \
      metadata/episode_metadata.json \
      metadata/episode_summary.json \
      config/scenario.yaml \
      config/experiment.yaml \
      config/resolved_config.yaml
  )
  echo "ZIP_READY=$RUN_DIR/deepseek-real-flow-import.zip"
' bash "$REPO_ROOT" "$RUN_ROOT" "$RUN_DIR" > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
PID="$(cat "$PID_FILE")"
echo "PID=$PID"
echo
echo "Started. Keep this terminal open to watch the live dashboard."
echo "Data directory:"
echo "  $RUN_DIR"
echo "Auto package:"
echo "  $RUN_DIR/deepseek-real-flow-import.zip"
echo "Stop simulation:"
echo "  kill $PID"
echo

render_dashboard() {
  local status="running"
  if ! kill -0 "$PID" 2>/dev/null; then
    status="stopped"
  fi

  printf '\n===== DeepSeek multi-crane live dashboard %s =====\n' "$(date '+%H:%M:%S')"
  echo "status=$status pid=$PID"
  echo "run_dir=$RUN_DIR"
  echo "log_file=$LOG_FILE"
  echo

  if [[ -s "$RUN_DIR/visual/frames.jsonl" ]]; then
    tail -n 1 "$RUN_DIR/visual/frames.jsonl" | jq -r '
      "sim_time=\(.time_s) episode_status=\(.episode_status) frame=\(.frame)\n"
      + (["crane","task","stage","hook_h","theta_deg","trolley_r","load","slew","trolley","hoist","action"] | @tsv)
      + "\n"
      + ([.cranes[] | [
          .crane_id,
          (.task_id // "-"),
          (.task_stage // "-"),
          (.hook_h_m | tostring),
          ((.theta_rad * 180 / 3.141592653589793) | tostring),
          (.trolley_r_m | tostring),
          (.load_attached | tostring),
          (.current_command.left_joystick.slew.direction + ":" + (.current_command.left_joystick.slew.gear | tostring)),
          (.current_command.left_joystick.trolley.direction + ":" + (.current_command.left_joystick.trolley.gear | tostring)),
          (.current_command.right_joystick.hoist.direction + ":" + (.current_command.right_joystick.hoist.gear | tostring)),
          (.current_command.task_action // "none")
        ]] | .[] | @tsv)
    ' 2>/dev/null || echo "Frame exists but could not be rendered yet."
  else
    echo "Waiting for frames.jsonl ..."
  fi

  echo
  echo "Latest events:"
  if [[ -s "$RUN_DIR/logs/events.jsonl" ]]; then
    tail -n 6 "$RUN_DIR/logs/events.jsonl" | jq -r '"\(.time_s)\t\(.event_type)\t\(.details // {})"' 2>/dev/null || tail -n 6 "$RUN_DIR/logs/events.jsonl"
  else
    echo "  waiting for events ..."
  fi

  echo
  echo "Latest DeepSeek decisions:"
  if [[ -s "$RUN_DIR/logs/llm_decisions.jsonl" ]]; then
    tail -n 4 "$RUN_DIR/logs/llm_decisions.jsonl" | jq -r '
      "\(.time_s)\t\(.provider)/\(.model)\t\(.crane_id)\t"
      + (.call_record.parsed_command.reason // "-")
    ' 2>/dev/null || tail -n 4 "$RUN_DIR/logs/llm_decisions.jsonl"
  else
    echo "  waiting for llm_decisions ..."
  fi

  echo
  echo "Data is being written continuously under:"
  echo "  $RUN_DIR"
  echo
  echo "Auto package when finished:"
  echo "  $RUN_DIR/deepseek-real-flow-import.zip"
  echo
  echo "Press Ctrl+C here to stop watching only. To stop the simulation too:"
  echo "  kill $PID"
}

if [[ "$SHOW_DASHBOARD" != true ]]; then
  echo
  echo "Progress:"
  echo "  tail -f \"$LOG_FILE\""
  echo
  echo "The frontend zip will appear here after the episode finishes:"
  echo "  $RUN_DIR/deepseek-real-flow-import.zip"
  exit 0
fi

dashboard_started_at="$(date +%s)"
while kill -0 "$PID" 2>/dev/null; do
  render_dashboard
  if [[ -n "$DASHBOARD_SECONDS" ]]; then
    now="$(date +%s)"
    if (( now - dashboard_started_at >= DASHBOARD_SECONDS )); then
      echo
      echo "Dashboard preview ended after ${DASHBOARD_SECONDS}s. Simulation is still running:"
      echo "  pid=$PID"
      echo "Stop simulation:"
      echo "  kill $PID"
      exit 0
    fi
  fi
  sleep 1
done

render_dashboard
echo
echo "Simulation process exited. Final log tail:"
tail -n 40 "$LOG_FILE" 2>/dev/null || true
