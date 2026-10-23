# Boston Bioprocess

This project is a local proof of concept for batch scheduling and simulated bioreactor control. I built the browser interface with plain HTML, CSS, and JavaScript and serve it from the FastAPI backend. The backend stores schedules, readings, forecasts, simulator state, and commands in SQLite.

**Hosted application:** Not deployed. I have not found and verified a setup that keeps the full application at $0.  
**Demo video:** Not recorded.

## Run the application

Python 3.12 is recommended.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
```

Then open <http://127.0.0.1:8000>. On first start, the application creates `backend/bioprocess.db` and adds sample equipment, batches, and operations. The database is local and ignored by Git.

To run the tests:

```bash
cd backend
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest -v test_main
```

## Scheduling

The schedule page loads data from the API and displays operations on equipment lanes in a Gantt chart. The date range end is exclusive. I can select an operation to edit its dates, equipment, or status.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/schedule` | Get equipment, batches, operations, and violations |
| POST | `/api/unit_operations` | Create an operation |
| PUT | `/api/unit_operations/{op_id}` | Update an operation |
| DELETE | `/api/unit_operations/{op_id}` | Delete a non-completed operation |
| POST | `/api/unit_operation_dependencies` | Add an explicit dependency |

The API saves an operation even when it creates a schedule violation, then returns a readable explanation. The UI highlights the conflict so it can be corrected. Validation covers batch date bounds, operation sequence, equipment overlap, explicit dependencies, and invalid date ranges. End dates are exclusive; completed operations cannot be moved, have their status changed, or be deleted.

The initial schedule includes five equipment lanes, three batches, and six operations. Two seeded issues make the validation visible when the application first opens:

- `Alpha Seed` and `Beta Seed` overlap on the `1.5L` equipment.
- `Gamma Seed` is scheduled after `Gamma Bioreactor` has started.

The sample schedule is seeded only when the equipment table is empty.

## Forecasting

I trained a multi-output Ridge regression model to forecast DO for the next ten one-minute steps from the previous 60 minutes of DO and feed-rate readings. The scaler is fit on training data only. I split by run rather than randomly by time window to reduce leakage between highly overlapping windows.

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

The simulator records DO, pH, temperature, and feed rate. Once it has 60 consecutive one-minute DO/feed observations, it creates ten one-minute DO predictions. Each prediction records when it was made and its target process time.

I implemented the actuator behavior described in the assignment: commands have a five-process-minute delay, feed changes at the scheduled time, and DO responds with a five-minute first-order lag toward `-2.0 * (feed_rate - feed_run)`. DO is kept within `[0, 100]`; feed bounds and units are loaded from `data_kit/limits.json`. Rejected commands are retained with their reasons. The UI labels observations, forecasts, pending commands, and applied commands separately.

The `/command` API accepts an absolute apply time. The manual control form uses `/api/control/commands` and sends a delay instead; the backend anchors that delay to the latest persisted process time. This avoids stale client timestamps during fast replay.

The automatic controller is implemented but **not configured or active by default**. I have not chosen a DO target or dwell time, so the controller does not send automatic commands unless an operator supplies those settings. I did not want to assume a process target that was not provided.

## Implementation decisions

- I save schedule violations and return them to the UI instead of rejecting the operation, so conflicts remain visible and editable.
- I used SQLite and a static frontend to keep local setup simple and avoid an extra frontend build toolchain.
- I used a run-level train/validation/test split because adjacent time windows overlap.
- Manual commands follow the same five-minute delay rule as controller commands.

## Not completed

- **Hosting:** The app has not been deployed. I will only consider hosting after verifying it can be kept at $0; I have not enabled billing or published the supplied data.
- **Demo video:** Not recorded.
- **Automatic control settings:** Waiting for a DO target and dwell time.

The assignment brief is available locally at `data_kit/Take_Home_SWE_ML_Brief.pdf` and is not included in the repository.
