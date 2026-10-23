# Data kit

Three fermentation runs and the setpoint limits for the closed-loop part of the assignment.

## Files

| File | Contents |
|---|---|
| `run_A.csv`, `run_B.csv`, `run_C.csv` | One fermentation run each, about 40 hours, one row per process-minute per signal |
| `limits.json` | Bounds for the feed setpoint: `{"feed_rate": {"unit": "mL/h", "min": 0.0, "max": 30.0}}` |

## Columns

```text
time_h,signal_name,value,unit
```

- `time_h`: process time in hours from inoculation, on a one-minute grid (0.0, 0.0167, 0.0333, ...).
- `signal_name`: one of `DO`, `pH`, `temp`, `feed_rate`.
- `value`: the reading.
- `unit`: `%` for DO, `-` for pH, `degC` for temperature, `mL/h` for feed rate.

## Notes

- Signal names are anonymized.
- The runs are complete: every minute has all four signals.
- Which runs you train on and which you hold out is your decision; say what you chose in your README.
- The device response to a feed command is defined in the assignment brief, section 3.
