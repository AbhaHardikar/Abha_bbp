from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

HISTORY_MINUTES = 60
FORECAST_MINUTES = 10
MODEL_NAME = "ridge_60min_10step"
SIGNALS = ("DO", "feed_rate")
RUN_FILES = {
    "run_A": "run_A.csv",
    "run_B": "run_B.csv",
    "run_C": "run_C.csv",
}


def load_run(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    required_columns = {"time_h", "signal_name", "value", "unit"}
    if set(raw.columns) != required_columns:
        raise ValueError(f"{path.name} must contain {sorted(required_columns)}")
    expected_units = {"DO": "%", "pH": "-", "temp": "degC", "feed_rate": "mL/h"}
    for signal, unit in expected_units.items():
        observed_units = raw.loc[raw["signal_name"] == signal, "unit"].unique()
        if len(observed_units) != 1 or observed_units[0] != unit:
            raise ValueError(f"{path.name} must use {unit} for {signal}")
    frame = raw.pivot(index="time_h", columns="signal_name", values="value").sort_index()
    if set(frame.columns) != {"DO", "feed_rate", "pH", "temp"}:
        raise ValueError(f"{path.name} must contain all four expected signals")
    if frame.isna().any().any() or not np.isfinite(frame.to_numpy()).all():
        raise ValueError(f"{path.name} contains missing or non-finite readings")
    if not np.allclose(np.diff(frame.index.to_numpy()), 1 / 60, atol=0.0001):
        raise ValueError(f"{path.name} must use a one-minute process-time grid")
    return frame


def make_windows(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = frame.loc[:, SIGNALS].to_numpy(dtype=float)
    dissolved_oxygen = frame["DO"].to_numpy(dtype=float)
    features = []
    targets = []
    persistence = []
    last_start = len(frame) - FORECAST_MINUTES
    for current_index in range(HISTORY_MINUTES - 1, last_start):
        history_start = current_index - HISTORY_MINUTES + 1
        features.append(values[history_start : current_index + 1].reshape(-1))
        targets.append(dissolved_oxygen[current_index + 1 : current_index + FORECAST_MINUTES + 1])
        persistence.append(
            np.repeat(dissolved_oxygen[current_index], FORECAST_MINUTES)
        )
    return (
        np.asarray(features),
        np.asarray(targets),
        np.asarray(persistence),
    )


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(mean_squared_error(actual, predicted)))


def train_forecaster(data_directory: Path) -> tuple[Pipeline, dict]:
    frames = {
        run_id: load_run(data_directory / filename)
        for run_id, filename in RUN_FILES.items()
    }
    train_x, train_y, _ = make_windows(frames["run_A"])
    validation_x, validation_y, validation_baseline = make_windows(frames["run_B"])
    test_x, test_y, test_baseline = make_windows(frames["run_C"])

    candidates = []
    for alpha in (0.01, 0.1, 1.0, 10.0, 100.0):
        model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        model.fit(train_x, train_y)
        validation_predictions = model.predict(validation_x)
        candidates.append(
            (rmse(validation_y, validation_predictions), alpha, model)
        )
    validation_rmse, selected_alpha, model = min(candidates, key=lambda item: item[0])

    test_predictions = model.predict(test_x)
    horizon_metrics = []
    for index in range(FORECAST_MINUTES):
        horizon_metrics.append(
            {
                "minutes_ahead": index + 1,
                "model_rmse": rmse(test_y[:, index], test_predictions[:, index]),
                "persistence_rmse": rmse(test_y[:, index], test_baseline[:, index]),
            }
        )

    metrics = {
        "model": MODEL_NAME,
        "features": "Last 60 minutes of DO and feed_rate",
        "target": "DO at each of the next 10 one-minute steps",
        "split": {
            "train": "run_A",
            "validation": "run_B",
            "test": "run_C",
            "windows_per_run": {
                "run_A": int(train_x.shape[0]),
                "run_B": int(validation_x.shape[0]),
                "run_C": int(test_x.shape[0]),
            },
        },
        "selection": {
            "method": "Lowest validation RMSE across Ridge alpha values",
            "selected_alpha": selected_alpha,
            "validation_rmse": validation_rmse,
        },
        "test": {
            "windows": int(test_x.shape[0]),
            "rmse": rmse(test_y, test_predictions),
            "persistence_rmse": rmse(test_y, test_baseline),
            "mae": float(mean_absolute_error(test_y, test_predictions)),
            "persistence_mae": float(mean_absolute_error(test_y, test_baseline)),
            "by_horizon": horizon_metrics,
        },
    }
    return model, metrics


def predict_next_minutes(
    model: Pipeline,
    do_history: list[float],
    feed_history: list[float],
) -> list[float]:
    if len(do_history) != HISTORY_MINUTES or len(feed_history) != HISTORY_MINUTES:
        raise ValueError(f"Forecast requires exactly {HISTORY_MINUTES} aligned readings")
    features = np.column_stack((do_history, feed_history)).reshape(1, -1)
    predictions = model.predict(features)[0]
    return [float(value) for value in predictions]
