# Boston Bioprocess

This project is a proof of concept for batch scheduling and simulated bioreactor control. I built the browser interface with plain HTML, CSS, and JavaScript and serve it from the FastAPI backend. The backend stores schedules, readings, forecasts, simulator state, and commands with SQLModel. It uses SQLite locally and can use PostgreSQL through `DATABASE_URL` when hosted.

**Hosted URL:** <https://boston-bioprocess-demo.onrender.com>

## Architecture

- `backend/main.py` defines the FastAPI routes, database lifecycle, schedule validation, and static-file serving.
- `backend/models.py` contains the SQLModel persistence types for schedules and control data.
- `backend/control_service.py` validates run data and commands and implements ingestion and simulated actuator behavior.
- `backend/forecaster.py` loads the supplied runs, trains/selects/evaluates the model, and produces inference outputs.
- `frontend/` contains the same-origin static interface, which fetches schedule and control state from the API.

## Run the application

Python 3.12 is recommended.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

Then open <http://127.0.0.1:8000>. On first start, the application creates `backend/bioprocess.db` and adds sample equipment, batches, and operations if the schedule is empty. The database is local and ignored by Git. To use a temporary in-memory database instead, run:

```bash
DATABASE_URL=sqlite:// .venv/bin/uvicorn main:app --reload
```

The in-memory database resets when the server stops and does not modify `backend/bioprocess.db`.

To run the tests:

```bash
cd backend
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest -v test_main
```

## Scheduling

The schedule page loads data from the API and displays operations on equipment lanes in a Gantt chart. The date range end is exclusive. I can select an operation to edit its dates, equipment, or status, or drag it to another date or equipment lane.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/schedule` | Get equipment, batches, operations, and violations |
| POST | `/api/unit_operations` | Create an operation |
| PUT | `/api/unit_operations/{op_id}` | Update an operation |
| DELETE | `/api/unit_operations/{op_id}` | Delete a non-completed operation |
| POST | `/api/unit_operation_dependencies` | Add an explicit dependency |

The API saves an operation even when it creates a schedule violation, then returns a readable explanation. The UI highlights the conflict so it can be corrected. Validation covers batch date bounds, operation sequence, equipment overlap, explicit dependencies, and invalid date ranges. End dates are exclusive; completed operations cannot be moved, have their status changed, or be deleted.

### Optional extension E3 — Drag to reschedule

I can drag a non-completed operation across dates or equipment lanes. The browser shows a distinct, unsaved preview while leaving the saved operation, Gantt conflict markers, and violation list untouched. On drop it sends the proposed dates and equipment to the existing `PUT /api/unit_operations/{op_id}` endpoint. The backend remains the source of truth: after success, the browser applies the returned operation and its violations to the in-memory schedule and redraws the Gantt and violation list without reloading the page. If the request fails, the preview is discarded and the last saved schedule and violations remain visible. Completed operations cannot be dragged.

The initial schedule includes five equipment lanes, three batches, and six operations. Two seeded issues make the validation visible when the application first opens:

- `Alpha Seed` and `Beta Seed` overlap on the `1.5L` equipment.
- `Gamma Seed` is scheduled after `Gamma Bioreactor` has started.

The sample schedule is seeded only when the equipment table is empty.

## How I split and evaluated the forecaster

I used the three supplied CSV runs as provided; I did not synthesize training data. Each run contains 2,400 process minutes with DO, pH, temperature, and feed-rate values. I trained a multi-output Ridge regression model to forecast DO for the next ten one-minute steps from the previous 60 minutes of DO and feed-rate readings. The scaler is fit on training data only. I split by run rather than randomly by time window to reduce leakage between highly overlapping windows.

| Run | Use | Windows |
|---|---|---:|
| `run_A` | Training | 2,331 |
| `run_B` | Validation and Ridge alpha selection | 2,331 |
| `run_C` | Final test | 2,331 |

I selected the Ridge alpha with the lowest validation RMSE from `{0.01, 0.1, 1, 10, 100}`. As a baseline, I repeated the last observed DO value across all forecast steps.

| Held-out `run_C` metric | Ridge model | Persistence baseline |
|---|---:|---:|
| RMSE (%DO) | 0.895 | 1.062 |
| MAE (%DO) | 0.503 | 0.576 |

The metrics endpoint also reports errors by forecast horizon. These results are a small proof of concept: the test windows overlap and come from only one held-out run, so they are not independent biological replicates and do not establish performance on a production process.

## Simulator and control room

The control room replays one of the supplied fermentation runs and displays readings, DO forecasts, and command status. Replay starts paused; the default speed is one process-minute per second. Before a manual command is applied, feed rate follows the selected run.

Each replay has its own instance identifier while retaining the source dataset's `run_id`. This keeps a replay restarted at an earlier process minute from mixing its live readings and forecasts with history from an earlier replay. Startup adds the new nullable instance columns to existing databases without deleting existing rows.

The simulator records DO, pH, temperature, and feed rate. Once it has 60 consecutive one-minute DO/feed observations, it creates ten one-minute DO predictions. Each prediction records when it was made and its target process time.

I implemented the actuator behavior described in the assignment: commands have a five-process-minute delay, feed changes at the scheduled time, and DO responds with a five-minute first-order lag toward `-2.0 * (feed_rate - feed_run)`. DO is kept within `[0, 100]`; feed bounds and units are loaded from `data_kit/limits.json`. Rejected commands are retained with their reasons. The UI labels observations, forecasts, pending commands, and applied commands separately.

The `/command` API accepts an absolute apply time. The manual control form uses `/api/control/commands` and sends a delay instead; the backend anchors that delay to the latest persisted process time. This avoids stale client timestamps during fast replay.

For the demo, I configured a **50% DO target** and a **10-process-minute minimum dwell**. These are illustrative values, not scientifically validated operating targets. The controller and its simplified feed/DO response have not been validated for a real bioprocess; these settings must not be treated as process guidance. The settings are stored in the database. A fresh local SQLite database starts without controller settings. A fresh PostgreSQL database is initialized with these illustrative settings, but existing settings are never overwritten during startup.

### Optional extension E2 — Forecast-aware controller

The automatic controller reads the prediction made from the current process observation at **+5 minutes**, matching the simulator's **5-minute actuator command delay**. Although the model returns a ten-minute trajectory, the controller does not use the +10-minute value for this decision. It adjusts the current feed by `(5-minute predicted DO - DO target) / 2`, then clamps the proposal to the feed-rate minimum and maximum in `data_kit/limits.json`. The API validates the command again before recording it. A pending command blocks another proposal; after a command, the configured minimum dwell must also elapse before another change can be proposed.

The forecast must match the current run and replay instance and have been made at the current process time. If that fresh +5-minute forecast is missing, the controller holds the current setpoint and emits no command; it does not fall back to an older forecast or the current DO reading.

Example from the supplied **Run B** using the trained forecaster and 50% demo target: at process minute 1,010 the observed DO was **50.306%**, while the model's +5-minute forecast was **49.809%**. A reactive threshold rule would not act at that observation because it is still above 50%; the forecast-aware policy instead proposed reducing feed from **8.885 to 8.789 mL/h**, scheduled for minute 1,015. Under the simulator's assumed five-minute first-order response, this feed offset produces about **+0.121 percentage points** of DO deviation from the source trace five minutes after actuation (minute 1,020; source-trace DO was 50.758%, simulated DO about 50.879%). This is a policy illustration, not evidence of improved real-world control: the source trace actually remained above 50%, so the forecast crossing was a false alarm. It demonstrates why the forecast policy and actuator model need validation before any real process use.

## Decisions and trade-offs

- I save schedule violations and return them to the UI instead of rejecting the operation, so conflicts remain visible and editable.
- I used SQLite and a static frontend to keep local setup simple and avoid an extra frontend build toolchain.
- I used a run-level train/validation/test split because adjacent time windows overlap.
- Manual commands follow the same five-minute delay rule as controller commands.
- For E3, a drag is only a preview until the existing update API accepts it; returned violations replace the moved operation's old violation entries in the current UI state.

## How I would deploy, retrain and monitor this

I have prepared the application to use PostgreSQL from the `DATABASE_URL` environment variable while retaining SQLite as the local default. The hosted database URL should be stored as a secret, not committed. PostgreSQL connections use the `psycopg` driver and connection health checks. Startup creates missing tables, applies the additive replay-isolation migration, seeds the schedule only when the equipment table is empty, and creates the illustrative control settings only when no configuration row exists. Startup does not import or overwrite the local SQLite database.

The live demo uses a Render Free Web Service and a Neon Free PostgreSQL database. The service uses the repository root, `pip install -r backend/requirements.txt`, and `uvicorn main:app --app-dir backend --host 0.0.0.0 --port $PORT` with Python `3.12.9`. `DATABASE_URL` and the write key are configured as environment secrets and are not stored in this repository.

This is a demonstration setup, not a production availability guarantee. The Render Free service can spin down after inactivity, causing a cold-start delay; the Neon Free database has usage quotas. The simulator is in-process, so it pauses while Render sleeps and must be started again after service restarts. The hosted API allows public reads but requires the evaluator write key for changes. Keep that key private and out of source control. The repository remains private; the app needs the supplied `data_kit` files for training and simulation but does not serve the raw CSVs as static assets.

On Render, set `WRITE_API_TOKEN` as a secret environment variable to a high-entropy value of at least 32 ASCII characters. The server requires it when running on Render and rejects every `POST`, `PUT`, `PATCH`, or `DELETE` request without a valid `Authorization: Bearer` header; public `GET` routes remain readable. The page has an “Unlock demo edits” control for the evaluator. The key is entered at runtime, kept in the current browser tab's session storage, and sent only with write requests; it is not included in the frontend source. The evaluator must receive the key through a private channel separate from the public URL and repository. The shared key grants write access to whoever possesses it and does not identify individual users. Local SQLite development remains writable without a key.

**Retraining and monitoring**

I would retrain from versioned input data using the same run-level split strategy, select settings on validation data only, and compare each candidate with the persistence baseline before evaluating it once on a held-out run. I would retain the model version, input-data identifiers, and evaluation metrics for each candidate.

Monitoring should cover reading freshness and unit validity, prediction error by horizon, run-to-run drift, feed bounds, command rejection reasons, pending-to-applied delay, simulator health, and API/database errors. Any move from this simulated controller to real equipment would require process-owner review, validated control limits, and appropriate safety engineering; this proof of concept is not validated for equipment use.

## Known limitations and submission status

- The free hosted demo is live at <https://boston-bioprocess-demo.onrender.com>; free-tier availability and quotas are not guaranteed.
- **Demo video:** Not recorded.
- **Automatic control:** Uses the current 5-minute forecast and configured minimum dwell; demo settings are illustrative and not validated for real process use.
- The ML metrics are based on overlapping windows from a single held-out run and do not establish biological generalization.
- The current simulator supports one vessel and uses an assumed simplified response model.

The assignment brief is included at `data_kit/Take_Home_SWE_ML_Brief.pdf`.
