# Episode Lifecycle Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the audited frontend/backend realtime episode bugs so an episode starts without blocking, advances in the background, streams live frames, handles controls safely, and exposes current run data.

**Architecture:** Keep the existing synchronous FastAPI routes and thread-based `EpisodeService` worker. Strengthen handle locking and lifecycle semantics, improve WebSocket connect/broadcast behavior, expose in-progress runs, and update the React workbench to use live state and un-scrubbed local start payloads.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic, pytest, React, Zustand, TypeScript, Vitest, Testing Library.

---

## File Structure

- Modify `backend/app/api/episode_service.py`: registry lock, handle lock helpers, no request-path first frame, idempotent stop, run_mode overrides, state sync helpers.
- Modify `backend/app/api/routes_episodes.py`: display paused state and read synchronized last frame.
- Modify `backend/app/api/production_runner.py`: store recorder last frame and expose terminal reason where possible.
- Modify `backend/app/api/websocket.py`: first-frame send, heartbeat loop, concurrent broadcast timeout.
- Modify `backend/app/api/desktop_service.py`: discover metadata-only runs.
- Modify `frontend/src/api/config.ts`: add `toStartRequest()` and `buildStartRequest()`.
- Modify `frontend/src/state/store.ts`: append bounded realtime frames.
- Modify `frontend/src/state/workbench.ts`: track config revision/stale episode.
- Modify `frontend/src/components/workbench/RunPage.tsx`: use start request, status polling, status-derived controls, live 3D link, evidence-based module cards.
- Modify `frontend/src/components/workbench/DataExportPage.tsx`: use live episode state and refresh on entry.
- Update tests in `backend/app/tests/test_moduleM_episode_lifecycle.py`, `backend/app/tests/test_moduleM_websocket.py`, `backend/app/tests/test_desktop_routes.py`, `frontend/tests/store.test.ts`, `frontend/tests/workbench/run.test.tsx`, `frontend/tests/workbench/export-settings.test.tsx`, and add focused config tests if needed.

## Task 1: Backend Lifecycle Tests

**Files:**
- Modify: `backend/app/tests/test_moduleM_episode_lifecycle.py`

- [ ] **Step 1: Write failing tests for non-blocking interactive start and idempotent stop**

Add or update tests so they assert:

```python
def test_interactive_autostart_returns_before_first_frame_then_advances() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)

    response = client.post(
        "/episodes/start",
        json={**_start_payload(autostart=True), "run_mode": "interactive_server"},
    )

    assert response.status_code == 200
    runner = factory.created[0]["runner"]
    assert runner.run_one_frame_calls == 0
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and runner.run_one_frame_calls < 2:
        time.sleep(0.02)
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.worker_stop.set()
    assert runner.run_one_frame_calls >= 2
```

```python
def test_stop_is_idempotent_for_terminal_episode() -> None:
    factory = FakeRunnerFactory()
    client = _client_with_factory(factory)
    client.post("/episodes/start", json=_start_payload())
    handle = client.app.state.episode_service.get_handle("E-life")
    handle.status = EpisodeStatus.COMPLETED

    stop = client.post("/episodes/E-life/stop")

    assert stop.status_code == 200
    assert stop.json()["data"]["accepted"] is False
    assert stop.json()["data"]["reason"] == "already_terminal"
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `python -m pytest backend/app/tests/test_moduleM_episode_lifecycle.py -q`

Expected before implementation: failures showing autostart already advanced once and terminal stop returns 409.

## Task 2: Backend Lifecycle Implementation

**Files:**
- Modify: `backend/app/api/episode_service.py`
- Modify: `backend/app/api/routes_episodes.py`
- Modify: `backend/app/api/production_runner.py`

- [ ] **Step 1: Implement registry and handle locking**

Use a service-level `threading.RLock` for `self.handles` and keep each `EpisodeHandle.advance_lock` as the handle state lock. Register the handle before starting a worker.

- [ ] **Step 2: Remove request-path first frame from interactive start**

For `request.autostart` with `run_mode == "interactive_server"`, start the worker without calling `_advance_handle_once()` in `start_episode()`.

- [ ] **Step 3: Make stop idempotent**

Terminal statuses return `EpisodeControlResponse(... accepted=False, reason="already_terminal")`. Running or paused episodes call `runner.stop("stopped_by_user")`, clear paused, advance or let worker observe the stop, and return success.

- [ ] **Step 4: Sync last frame and terminal reason**

Add helper lookups for runner/recorder `last_frame` and `terminal_reason`. Update `_advance_handle_once()` and exception paths to write these fields under the handle lock.

- [ ] **Step 5: Apply run_mode overrides**

Merge `request.run_mode` into `experiment.runtime.mode` before inline/config-path resolution so API `run_mode` has real semantic effect.

- [ ] **Step 6: Run lifecycle tests and verify GREEN**

Run: `python -m pytest backend/app/tests/test_moduleM_episode_lifecycle.py -q`

Expected: all lifecycle tests pass.

## Task 3: WebSocket Tests And Implementation

**Files:**
- Modify: `backend/app/tests/test_moduleM_websocket.py`
- Modify: `backend/app/api/websocket.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:

```python
def test_manager_broadcast_disconnects_slow_or_failing_client() -> None:
    manager = WebSocketConnectionManager(send_timeout_s=0.01)
    good = FakeWebSocket()
    bad = FakeWebSocket()
    bad.fail_send = True
    ...
```

and endpoint/client-level coverage that an existing episode receives a heartbeat or last frame after connection.

- [ ] **Step 2: Run WebSocket tests and verify RED**

Run: `python -m pytest backend/app/tests/test_moduleM_websocket.py -q`

- [ ] **Step 3: Implement concurrent broadcast with timeout**

In `_broadcast()`, copy clients, send with `asyncio.wait_for()`, gather with `return_exceptions=True`, and disconnect failed clients.

- [ ] **Step 4: Implement connect first-frame and heartbeat loop**

After `manager.connect()`, send `handle.last_frame` or file-derived frame if available. Start a task that sends a heartbeat every 5 seconds and cancel it when the socket disconnects.

- [ ] **Step 5: Run WebSocket tests and verify GREEN**

Run: `python -m pytest backend/app/tests/test_moduleM_websocket.py -q`

## Task 4: Desktop Run Discovery

**Files:**
- Modify: `backend/app/tests/test_desktop_routes.py`
- Modify: `backend/app/api/desktop_service.py`

- [ ] **Step 1: Write failing metadata-only run test**

Add a run with `metadata/episode_metadata.json` and no summary. Assert `/desktop/runs` returns it with `summary_available=false`.

- [ ] **Step 2: Run desktop route tests and verify RED**

Run: `python -m pytest backend/app/tests/test_desktop_routes.py -q`

- [ ] **Step 3: Implement metadata-first run discovery**

Collect run directories from both `metadata/episode_metadata.json` and `metadata/episode_summary.json`, merge duplicates, prefer summary fields, and preserve project-root safety.

- [ ] **Step 4: Run desktop route tests and verify GREEN**

Run: `python -m pytest backend/app/tests/test_desktop_routes.py -q`

## Task 5: Frontend Store And Config Request Tests

**Files:**
- Modify: `frontend/tests/store.test.ts`
- Modify: `frontend/tests/workbench/run.test.tsx`
- Modify: `frontend/src/api/config.ts`
- Modify: `frontend/src/state/store.ts`

- [ ] **Step 1: Write failing realtime frame buffer test**

Update `pushRealtimeFrame` test to expect `frames.length === 1`, `currentIndex === 0`, and duplicate/older frames not appended.

- [ ] **Step 2: Write failing start-request secret test**

In RunPage tests, include `api_key: sk-real-secret` in YAML and assert `/episodes/start` body preserves it while `/scenarios/validate` remains scrubbed.

- [ ] **Step 3: Run frontend tests and verify RED**

Run: `npm test -- --run frontend/tests/store.test.ts frontend/tests/workbench/run.test.tsx`

- [ ] **Step 4: Add `buildStartRequest()`**

Parse YAML and build an `EpisodeStartRequest` without `scrubSecrets()`. Keep `buildValidateRequest()` unchanged.

- [ ] **Step 5: Append bounded realtime frames**

Update `pushRealtimeFrame()` to append monotonic frames, cap at 5000, update `latestFrame`, `currentIndex`, and `episodeId`.

- [ ] **Step 6: Run frontend tests and verify GREEN**

Run: `npm test -- --run frontend/tests/store.test.ts frontend/tests/workbench/run.test.tsx`

## Task 6: Frontend Workbench State And Pages

**Files:**
- Modify: `frontend/src/state/workbench.ts`
- Modify: `frontend/src/components/workbench/RunPage.tsx`
- Modify: `frontend/src/components/workbench/DataExportPage.tsx`
- Modify: `frontend/tests/workbench/run.test.tsx`
- Modify: `frontend/tests/workbench/export-settings.test.tsx`

- [ ] **Step 1: Write failing tests for live status controls and data export live state**

Assert paused status enables resume but disables pause; terminal status disables stop; DataExportPage displays `episodeState.status` over `currentEpisode.status`.

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run frontend/tests/workbench/run.test.tsx frontend/tests/workbench/export-settings.test.tsx`

- [ ] **Step 3: Track config revision/stale episode**

Increment revision on `setYamlText()`. When YAML changes after a current episode exists, mark `currentEpisodeStale=true` or clear the current episode. Keep the UX minimally invasive by displaying stale state and disabling controls until a new start.

- [ ] **Step 4: Update RunPage controls and polling**

Use live status for `canPause`, `canResume`, `canStop`. Poll active episode state every 1000 ms. Use `buildStartRequest()` for start.

- [ ] **Step 5: Update module cards with real evidence**

Show status/frame/run-dir evidence instead of static "pending integration" for every module.

- [ ] **Step 6: Update DataExportPage**

Read `episodeState` and refresh current state on mount when an episode id exists.

- [ ] **Step 7: Run tests and verify GREEN**

Run: `npm test -- --run frontend/tests/workbench/run.test.tsx frontend/tests/workbench/export-settings.test.tsx`

## Task 7: Full Verification

**Files:**
- No new files required.

- [ ] **Step 1: Run targeted backend tests**

Run: `python -m pytest backend/app/tests/test_moduleM_episode_lifecycle.py backend/app/tests/test_moduleM_websocket.py backend/app/tests/test_desktop_routes.py -q`

- [ ] **Step 2: Run targeted frontend tests**

Run: `npm test -- --run frontend/tests/store.test.ts frontend/tests/workbench/run.test.tsx frontend/tests/workbench/export-settings.test.tsx`

- [ ] **Step 3: Run broader safety checks if targeted tests pass**

Run: `python -m pytest backend/app/tests/test_moduleM_acceptance.py backend/app/tests/test_moduleM_production_api.py -q`

Run: `npm test -- --run frontend/tests/ws.test.ts frontend/tests/integration.test.ts`

- [ ] **Step 4: Completion audit**

Map B01-B15 to changed files and tests. If any audit item lacks direct evidence, add targeted verification before claiming completion.

## Plan Self-Review

- Spec coverage: Tasks cover lifecycle, WebSocket, desktop runs, frontend realtime store, start secret handling, status controls, data export, and module evidence.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: `EpisodeStartRequest`, `EpisodeStateResponse`, and existing store method names match current source.
