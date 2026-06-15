# Desktop Workbench Design

## Goal

Build a cross-platform desktop workbench for the multi-crane simulation system so a user can double-click one program, configure a single experiment visually, run it, observe it in 3D, and download the resulting run artifacts without manually starting backend and frontend services.

The first release is a research-oriented single-experiment loop. It must organize the existing modules A-P instead of bypassing or replacing them. The desktop workbench is an orchestration and presentation layer over the current module contracts.

## Confirmed Direction

- Platforms: Windows and macOS.
- Desktop shell: Electron.
- Frontend: reuse and extend the existing React/Vite/Three application.
- Backend: keep FastAPI as the authoritative runtime/API layer.
- First release scope: single experiment loop.
- Configuration UX: templates plus core parameter forms plus an advanced YAML editor.
- Navigation: workbench tabs for experiment, configuration, run, 3D visualization, data/export, and settings.
- Packaging path: start with a development desktop launcher, then move toward self-contained Windows/macOS builds.

## Non-Goals For The First Release

- Do not rewrite module C-P core logic.
- Do not move physics, task state, risk, LLM calls, recording, dataset generation, or training conversion into Electron or the frontend.
- Do not make every YAML field a form control.
- Do not build a full experiment database.
- Do not build the complete batch dataset UI.
- Do not build the complete STGNN training UI.
- Do not require the first release to be a fully self-contained no-Python installer.
- Do not store raw API keys in repository files, YAML drafts, run summaries, logs, or downloadable run archives.

## Module Organization

The desktop workbench must expose the project as a coherent module pipeline:

```text
Desktop workbench / Electron
  |
  |-- Experiment configuration area
  |     |-- Module A: config parsing, validation, run directories, secret governance
  |     |-- Module B: crane model library, layout, coverage and overlap diagnostics
  |     |-- Module D: task generation, queues, attach/release state-machine parameters
  |     |-- Module E: weather, wind, visibility, environment disturbance parameters
  |
  |-- Simulation runtime area
  |     |-- Module J: episode main loop, frame scheduling, run modes
  |     |-- Module C: crane kinematics and physics stepping
  |     |-- Module F: observation construction
  |     |-- Module G: LLM operator, provider config, prompt, parsing, fallback
  |     |-- Module H: mechanical safety, forbidden-zone policy, online risk, intervention
  |     |-- Module I: low-level controller from safe command to continuous targets
  |
  |-- Recording and display area
  |     |-- Module L: authoritative recording, Parquet, JSONL, manifest, summary
  |     |-- Module M: REST API, WebSocket, CLI, episode management
  |     |-- Module N: 3D visualization, realtime view, offline replay, logs
  |
  |-- Data research area
        |-- Module K: offline risk labels
        |-- Module O: batch experiments, dataset build, quality gate, splits, windows
        |-- Module P: STGNN and trajectory-prediction sample conversion
```

The first release uses every runtime-facing module in the single-experiment path:

```text
User chooses template or edits YAML
  -> A validates and resolves config
  -> B resolves crane models and layout
  -> D prepares task queues
  -> E prepares weather timeline/state
  -> J starts the episode loop
  -> each frame calls C/D/E/F/G/H/I as required by the scheduler
  -> L records authoritative output
  -> M exposes state, controls, downloads, and WebSocket frames
  -> N renders 3D state, logs, tasks, risks, and events
  -> user downloads or opens L/M run artifacts
```

K/O/P are not implemented as full UI workflows in release one, but the data/export tab must reserve their entry points so the research workflow has an obvious next expansion path.

## Architecture

### Electron Main Process

Electron owns only desktop concerns:

- create and manage the application window;
- discover the project root in development mode;
- choose an available localhost port for FastAPI;
- start the backend child process;
- wait for `/health` before loading the app;
- inject backend URL/API base metadata into the frontend;
- collect backend stdout/stderr for diagnostics;
- terminate the backend child process on application exit;
- provide desktop-only actions such as opening run directories.

Electron must not implement simulation business logic or duplicate backend validation.

### React Workbench

The existing React/Vite/Three frontend becomes a tabbed workbench. Module N remains the owner of 3D rendering and presentation-only behavior. New workbench pages organize configuration, run control, export, and settings around existing backend APIs and a few thin desktop APIs.

The frontend may parse YAML for editor UX, but authoritative validation and resolution remain in Module A through Module M.

### FastAPI Backend

FastAPI remains the authority for:

- health and environment status;
- config validation;
- episode start, pause, resume, stop, state, summary, and download;
- WebSocket simulation frames;
- run artifact access.

New desktop-specific endpoints may be added, but they must remain thin orchestration/read APIs. They must not absorb core logic from A-P.

## Workbench Navigation

The desktop app uses a left navigation rail:

```text
Experiment
Configuration
Run
3D Visualization
Data / Export
Settings
```

The top bar shows the current experiment name, backend health, episode status, and primary actions when applicable.

## Tab Designs

### Experiment

Primary module: A. Future connections: O/P.

First release responsibilities:

- create an experiment from a template;
- import a `.yaml`, `.yml`, or `.json` config;
- display current experiment summary:
  - `scenario_id`;
  - `experiment_id`;
  - crane count;
  - task count;
  - simulation duration;
  - LLM provider;
  - `run_root`;
- display validation status:
  - unvalidated;
  - valid;
  - invalid;
- show recent runs for the current experiment when available;
- jump to 3D visualization or data/export for an existing run.

This tab does not start the simulation directly. It establishes which experiment the workbench is editing.

### Configuration

Primary modules: A/B/D/E/G/H/J/L.

The page uses a two-column layout.

Left column: core form controls:

- Basics:
  - experiment name;
  - seed;
  - simulation duration;
  - `dt`;
  - stop when all tasks complete.
- Cranes and layout:
  - crane count;
  - layout mode;
  - overlap level;
  - height strategy;
  - crane model.
- Tasks:
  - tasks per crane;
  - task generation mode;
  - priority settings;
  - attach/release thresholds where practical.
- Weather:
  - constant/schedule/random mode;
  - wind speed;
  - gust speed;
  - wind direction;
  - visibility.
- LLM:
  - enabled/disabled;
  - provider;
  - model;
  - base URL;
  - API key source;
  - temperature;
  - fallback policy.
- Safety:
  - risk prompt mode;
  - safety mode;
  - forbidden-zone policy;
  - risk thresholds.
- Output:
  - run root;
  - save visual frames;
  - save Parquet;
  - save replay.

Right column: advanced YAML editor:

- displays the complete YAML generated from template plus form state;
- allows direct YAML editing;
- supports "sync core fields to form" for fields that map cleanly;
- preserves advanced YAML fields that do not map to core form controls;
- validates by calling `/scenarios/validate`.

Principle: forms are convenience, YAML is the complete editable document, and backend validation is authoritative.

### Run

Primary modules: J/M. Runtime summary includes C/D/E/F/G/H/I/L.

First release responsibilities:

- buttons:
  - validate;
  - start;
  - pause;
  - resume;
  - stop;
- episode status:
  - `episode_id`;
  - status;
  - frame index;
  - simulation time;
  - `run_dir`;
  - terminal reason;
- module pipeline status:
  - C: physics step normal/error summary;
  - D: task queue, completed tasks, failed tasks;
  - E: current weather;
  - F: observation construction status;
  - G: LLM request status, failure count, fallback status;
  - H: risk level and intervention count;
  - I: controller output status;
  - L: recorder write status;
- realtime event stream:
  - errors;
  - risk events;
  - task events;
  - LLM calls;
  - safety interventions.

The run tab should make the module pipeline visible enough that a failure is understandable as "module X failed during stage Y", not just "the app failed".

### 3D Visualization

Primary module: N. Inputs come from L/M and resolved config from A.

First release responsibilities:

- central Three.js scene:
  - cranes;
  - hooks;
  - loads;
  - material/work/forbidden zones;
  - risk lines;
  - weather direction;
- controls:
  - camera modes;
  - follow crane;
  - show/hide risks;
  - show/hide zones;
- right panels:
  - crane status;
  - task status;
  - risk status;
  - LLM command log;
  - event log;
- bottom timeline:
  - realtime/replay mode;
  - speed;
  - seek;
  - step.
- offline loading:
  - downloaded episode zip;
  - local `frames.jsonl` plus manifest/log files.

Module N remains presentation-only. It must not compute authoritative physics, task transitions, risks, labels, or training truth.

### Data / Export

Primary modules in release one: L/M. Reserved expansion: K/O/P.

First release responsibilities:

- download the current episode zip;
- open the run directory from the desktop app;
- show episode summary:
  - duration;
  - task completion;
  - risk events;
  - LLM call statistics;
  - failure reason;
- show file inventory:
  - `trajectories.parquet`;
  - `pair_risks.parquet`;
  - `graph_edges.parquet`;
  - `tasks.parquet`;
  - `frames.jsonl`;
  - `commands.jsonl`;
  - manifests and summaries.

Reserved follow-up entry points:

- generate offline risk labels through K;
- build dataset through O;
- convert STGNN training samples through P.

### Settings

Primary desktop concerns plus A/G/M integration.

First release responsibilities:

- backend status:
  - host;
  - port;
  - health result;
  - launch logs;
- Python environment:
  - detected interpreter path;
  - version;
  - dependency status where available;
- output directory:
  - default `runs/`;
  - open output location;
- LLM providers:
  - DeepSeek;
  - OpenAI-compatible;
  - custom base URL;
  - disabled/rule baseline;
- API key handling:
  - choose environment variable source;
  - enter current-session key;
  - display only masked values;
- diagnostics:
  - copy logs;
  - restart backend;
  - open log directory.

## Desktop Launching

### Development Mode

Development mode is the first implementation target:

```text
start Electron
  -> find project root
  -> find Python:
       macOS/Linux: .venv/bin/python
       Windows: .venv/Scripts/python.exe
  -> choose available backend port
  -> launch:
       python -m uvicorn backend.app.main:app --host 127.0.0.1 --port <port>
  -> poll /health
  -> load React workbench:
       Vite dev server in dev
       frontend/dist in built mode
  -> inject API base URL into frontend
```

If backend launch fails, the app must show a diagnostic screen with:

- Python path;
- launch command;
- stderr/stdout excerpt;
- selected port;
- likely fixes for missing dependencies, missing `.venv`, or port conflicts.

### Release Mode

Release mode is a later stage:

```text
Electron app
  -> built frontend assets
  -> packaged backend launch resource
  -> local FastAPI or backend binary
  -> no manual terminal startup
```

The release path can be split:

- 2A: Electron includes frontend assets, backend still relies on local Python.
- 2B: backend is packaged with PyInstaller, Nuitka, or equivalent as a platform binary.

## Backend API Additions

Existing endpoints already support the core run loop:

- `GET /health`
- `POST /scenarios/validate`
- `POST /episodes/start`
- `POST /episodes/{episode_id}/pause`
- `POST /episodes/{episode_id}/resume`
- `POST /episodes/{episode_id}/stop`
- `GET /episodes/{episode_id}/state`
- `GET /episodes/{episode_id}/summary`
- `GET /episodes/{episode_id}/download`
- WebSocket realtime frames

First release should add thin desktop/workbench endpoints:

```text
GET  /desktop/templates
POST /desktop/config/render
POST /desktop/config/patch
POST /desktop/experiments/draft
GET  /desktop/experiments/recent
GET  /desktop/runs
GET  /desktop/runs/{episode_id}/files
GET  /desktop/environment
```

Responsibilities:

- `/desktop/templates`: list available config templates from approved template locations.
- `/desktop/config/render`: render full YAML from a template and core form values.
- `/desktop/config/patch`: patch mapped core fields into YAML while preserving advanced fields.
- `/desktop/experiments/draft`: save current experiment draft metadata and YAML.
- `/desktop/experiments/recent`: list recent drafts.
- `/desktop/runs`: scan known run roots for run summaries.
- `/desktop/runs/{episode_id}/files`: list known L-owned artifacts for a run.
- `/desktop/environment`: return app version, backend port, Python info, run root, and dependency status where practical.

These endpoints must not implement physics, task state, safety logic, LLM provider calls, recorder content generation, dataset building, or training conversion.

## Draft Storage

Drafts are stored outside authoritative run output:

```text
.desktop/experiments/<experiment_id>/
  draft.yaml
  draft.meta.json
```

`draft.yaml` stores the editable config document. `draft.meta.json` stores UI metadata:

- template name;
- last opened time;
- last validation result hash;
- dirty flag;
- display summary.

Raw API keys must not be written to draft files.

## LLM Provider And Secret Handling

LLM runtime belongs to Module G. Secret governance must respect Module A's existing rules.

First release strategy:

- YAML defaults to `api_key_env`, such as `DEEPSEEK_API_KEY`.
- The UI may accept an API key for the current session or a future secure storage integration.
- Runtime injection uses process environment variables or explicit backend runtime config that is not persisted into YAML or run artifacts.
- UI displays masked keys only.
- Supported provider presets:
  - DeepSeek;
  - OpenAI-compatible;
  - custom base URL and model;
  - disabled/rule baseline.

Secure OS keychain storage is a later enhancement unless it can be added without destabilizing the first release.

## Error Handling

Errors should be grouped by module and stage:

- A config errors: return user to the configuration tab and highlight mapped fields or YAML locations where possible.
- B layout errors: show crane distance, boundary, forbidden-zone, coverage, or overlap diagnostics.
- G LLM errors: show provider, model, base URL, failure count, and fallback status.
- H safety termination: show risk, collision, or forbidden-zone event details.
- J runtime failure: show episode terminal reason and frame/time.
- L recording failure: show run directory and file write error details.
- M connection failure: show backend health and child process logs.
- N display failure: show frame/WebSocket/offline loading errors without implying authoritative data corruption.

The app should make failures actionable and preserve module ownership in the message.

## Testing Strategy

Release-one tests:

- Electron main process:
  - port selection;
  - backend launch command construction;
  - Python path resolution;
  - backend child cleanup.
- Backend desktop APIs:
  - templates;
  - YAML render/patch;
  - draft save/list;
  - run listing;
  - environment report.
- Frontend:
  - tab navigation;
  - template selection;
  - core form to YAML;
  - YAML validation request;
  - episode start/pause/resume/stop actions;
  - error rendering.
- Existing backend:
  - full pytest suite remains passing.
- Existing/frontend checks:
  - TypeScript typecheck;
  - unit tests where present.
- Desktop smoke test:
  - start Electron;
  - wait for `/health`;
  - load workbench home;
  - verify backend status appears.

## Phased Delivery

### Phase 1: Development Desktop Single-Experiment Loop

Deliver:

- Electron desktop shell;
- automatic FastAPI launch;
- React workbench navigation;
- template plus core form plus YAML editor;
- provider selection;
- config validation;
- episode start/pause/resume/stop/state;
- realtime 3D;
- module pipeline status summary;
- episode zip download;
- open run directory;
- backend diagnostics.

Phase 1 may require local `.venv` and Node tooling.

### Phase 2: Packaged Desktop Distribution

Deliver:

- Windows executable or installer;
- macOS app bundle;
- bundled frontend assets;
- stable resource path handling;
- backend launch diagnostics in packaged mode;
- versioned log and user-data directories;
- optional packaged backend binary.

### Phase 3: Data Research Loop

Deliver:

- expanded data center;
- run index;
- episode summary comparison;
- offline risk label entry through K;
- dataset build workflow through O;
- quality gate, quarantine, split, and window index display;
- STGNN sample conversion entry through P;
- feature/label summary and leakage diagnostics.

### Phase 4: Experiment Management And Reproducibility

Deliver:

- experiment library;
- clone/version/comment workflows;
- config diff;
- run comparison;
- baseline comparison;
- batch queue;
- result charts;
- research package export.

## Release-One Acceptance Criteria

1. A user can open one desktop entry point without manually starting backend and frontend terminals.
2. The app starts FastAPI automatically and shows health status.
3. A user can create an experiment from a template.
4. A user can edit core parameters: crane count, layout, tasks, duration, weather, LLM provider, model, API key source, and safety mode.
5. A user can view and edit the complete YAML.
6. Config validation uses the existing backend A/resolver path through Module M.
7. A valid config can start one episode.
8. The run tab displays episode ID, status, frame, time, run directory, and terminal reason.
9. The run tab displays key module-pipeline summaries for C/D/E/F/G/H/I/L.
10. The 3D tab displays realtime cranes, tasks, risks, LLM commands, and events.
11. A user can pause, resume, and stop an episode.
12. A user can download the episode zip.
13. A user can open the run directory from the desktop app.
14. Closing the desktop app terminates its backend child process.
15. Raw API keys are not written to YAML drafts, logs, summaries, repository files, or downloaded run archives.
16. Backend launch failure shows a readable diagnostic screen.
17. Existing backend tests pass.
18. Frontend typecheck and relevant tests pass.
19. A desktop smoke test starts the app, waits for `/health`, and loads the workbench.

## Implementation Order

1. Create the desktop workbench implementation plan.
2. Add Electron shell and backend launch diagnostics.
3. Add API base injection and frontend runtime config.
4. Add workbench navigation.
5. Add configuration template/form/YAML/validation flow.
6. Add run controls and state polling.
7. Integrate the existing 3D view into the workbench structure.
8. Add data/export and settings pages.
9. Add tests, smoke checks, and developer documentation.
