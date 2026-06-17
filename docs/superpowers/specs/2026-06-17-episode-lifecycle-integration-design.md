# Episode Lifecycle Integration Design

## Goal

Close the frontend/backend realtime episode loop described in `C:/Users/Administrator/Downloads/群塔前后端联调Bug审计报告.md` so a started crane simulation keeps advancing, can be controlled safely, streams usable realtime frames, and exposes generated run data clearly.

## Scope

This design covers the audit items B01 through B15. It focuses on the current desktop workbench path:

- React workbench Run, Visualization, and Data Export pages;
- REST endpoints under `/episodes/*` and `/desktop/*`;
- `EpisodeService`, production/local runners, recorder integration, and WebSocket streaming.

The design keeps the existing synchronous FastAPI route style and the existing thread-based `EpisodeService` worker. It does not migrate the API to a fully asyncio service, add a high-FPS queueing subsystem, or build a complete module observability platform. It does add enough real state to remove misleading placeholders and make the integration usable.

## Current Root Causes

The current implementation has a partial background-worker shape, but the lifecycle is still leaky:

- `start_episode()` runs one frame in the request path before the handle is registered, so slow first-frame work can block start and the realtime source is not reliably established.
- `stop_episode()` only accepts `running`, so repeated stop, terminal stop, and some paused stop paths surface as `M_E_INVALID_EPISODE_STATE`.
- handle state writes are not consistently protected; the worker and REST controls can race.
- `EpisodeHandle.last_frame` is defined but not updated from runner/recorder output.
- WebSocket connections wait for client messages and do not send a first frame or periodic heartbeat.
- WebSocket broadcast awaits clients sequentially, so a slow client can delay others.
- realtime frames update only `latestFrame`, not the shared `frames` buffer used by Timeline.
- desktop run discovery only scans `metadata/episode_summary.json`, so in-progress runs can be invisible.
- RunPage starts episodes with `buildValidateRequest()`, which scrubs secret-like fields before the start request.
- RunPage/DataExportPage rely on stale start response status in places where live `episodeState` should be authoritative.
- YAML edits do not invalidate or label the current episode, so controls can accidentally target an episode from old config.
- the module pipeline is a static placeholder, which makes debugging harder.

## Architecture

Keep the existing synchronous service boundaries and improve the lifecycle contract:

```text
POST /episodes/start
  -> resolve config
  -> create runner
  -> create and register EpisodeHandle
  -> if autostart: start worker thread
  -> return immediately

worker thread
  -> while running and not stop requested
  -> respect paused
  -> run one frame
  -> sync handle fields under lock
  -> terminal: finalize/sync/exit
  -> sleep based on runner dt
```

`EpisodeHandle` remains a dataclass but becomes the single state authority for REST state. Handle writes use a per-handle reentrant lock. The service also uses a service-level lock for `handles` registry operations.

The WebSocket manager remains the transport boundary. It sends current state on connect when available, sends periodic heartbeats, and broadcasts concurrently with a short timeout.

The frontend keeps one realtime rendering path: WebSocket frames enter `useStore.pushRealtimeFrame()`, which updates `latestFrame`, appends to a bounded `frames` buffer, and advances `currentIndex`.

## Backend Lifecycle Requirements

- `start_episode(autostart=true)` must not synchronously call `run_one_frame()` before returning.
- the handle must be present in `self.handles` before the worker can emit observable state.
- interactive server starts must keep advancing frames in the background until terminal, paused, stopped, or failed.
- `pause` should be accepted only for running, non-paused episodes.
- `resume` should be accepted only for paused running episodes.
- `stop` should be idempotent:
  - running or paused episodes request stop and return success;
  - terminal episodes return 200 with `accepted=false` and `reason="already_terminal"`;
  - missing episodes still return 404.
- worker exceptions should set `failed_invalid_state`, clear paused state, and expose a terminal reason.
- `get_state` should return the display status `paused` when appropriate and should include the most recent frame from the handle, runner, recorder, or file fallback.
- `run_mode` from `EpisodeStartRequest` should have a real effect by being merged into experiment runtime overrides before config resolution.

## Recorder And Runner Requirements

- `ProductionRecorderAdapter` should remember `last_frame` from `record_initial_frame()` and `record_step()`.
- `ProductionEpisodeRunner` should expose enough state for service helpers to retrieve run directory, last frame, and terminal reason if available.
- terminal finalization should remain idempotent.

## WebSocket Requirements

- connecting to a missing episode still sends the uniform `M_E_EPISODE_NOT_FOUND` error and closes.
- connecting to an existing episode accepts the socket and immediately sends the last frame if one exists.
- each connection receives periodic heartbeat messages while open.
- broadcast to multiple clients uses concurrent sends with a bounded timeout and disconnects failing clients.
- realtime frames must still reject `offline_labels`.

## Desktop Data Requirements

- `/desktop/runs` should list runs found by `metadata/episode_metadata.json` or `metadata/episode_summary.json`.
- runs without a summary should have `summary_available=false`.
- status should prefer summary status, then metadata status fields, then `None`.
- run files lookup should work for metadata-only runs under configured run roots.

## Frontend Requirements

- `buildValidateRequest()` stays scrubbed for validation.
- add `buildStartRequest()` for local start requests that parses YAML without secret scrubbing.
- RunPage uses `buildStartRequest()` for `/episodes/start`.
- RunPage polls `getEpisodeState()` about once per second while an episode is active.
- RunPage control buttons derive availability from live status:
  - pause only for `running`;
  - resume only for `paused`;
  - stop for non-terminal active episodes;
  - terminal episodes do not show a stop error.
- RunPage should offer a direct open-live-3D action or navigate after start; the existing live store state must continue to work.
- `pushRealtimeFrame()` appends monotonic new live frames into a bounded buffer and updates `currentIndex`.
- DataExportPage displays `episodeState.status` and `episodeState.run_dir` before falling back to `currentEpisode`.
- DataExportPage refreshes current episode state when opened if an episode exists.
- changing YAML should mark the current episode as stale or clear it so controls do not silently target old config.
- the module pipeline should stop saying every module is only a placeholder. It should show real available evidence such as episode status, frame count, run directory, and summary/run-file availability.

## Testing Requirements

Backend tests should prove:

- autostart interactive start returns before any fake runner frame is required and then advances in the background;
- pause stops advancement and resume restarts it;
- stop works from paused/running and is idempotent for terminal episodes;
- worker exceptions produce `failed_invalid_state` and terminal reason;
- state includes last frame after frames are recorded;
- WebSocket connect sends last frame or heartbeat and broadcasts concurrently;
- metadata-only runs appear in `/desktop/runs`.

Frontend tests should prove:

- start uses `buildStartRequest()` and does not replace real `api_key` with `***`;
- realtime frame push appends to `frames` and updates Timeline-related indexes;
- RunPage buttons are disabled/enabled from live status;
- RunPage polling refreshes active state;
- DataExportPage uses latest `episodeState`;
- YAML changes invalidate or label stale current episodes.

## Non-Goals

- Full asyncio migration.
- Full C/D/E/F/G/H/I/L module telemetry API.
- Real LLM latency optimization beyond avoiding request-path blocking.
- Production-grade per-client bounded WebSocket queues.
- Visual redesign of the workbench.

## Self-Review

- Scope coverage: B01-B15 are represented by backend lifecycle, WebSocket, desktop data, frontend state, secret handling, and module evidence requirements.
- Placeholder scan: no TBD/TODO placeholders remain.
- Internal consistency: the design consistently keeps synchronous routes and thread workers.
- Ambiguity check: the module pipeline is intentionally scoped to real evidence now, with a full telemetry API listed as a non-goal.
