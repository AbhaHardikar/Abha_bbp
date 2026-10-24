import asyncio
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sklearn.pipeline import Pipeline
from sqlmodel import Field, Session, SQLModel, select

from forecaster import (
    HISTORY_MINUTES,
    MODEL_NAME,
    predict_next_minutes,
)
from models import (
    ControlCommand,
    ControlConfig,
    Prediction,
    Reading,
    SignalName,
    SimulatorState,
)

READING_UNITS = {"DO": "%", "pH": "-", "temp": "degC", "feed_rate": "mL/h"}
PROCESS_TIME_STEP_H = 1 / 60
ACTUATOR_LAG_MINUTES = 5
CONTROLLER_FORECAST_HORIZON_MINUTES = ACTUATOR_LAG_MINUTES
ACTUATOR_TIME_CONSTANT_MINUTES = 5.0
DO_FEED_GAIN = 2.0
DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data_kit"


class ReadingInput(SQLModel):
    time_h: float
    signal_name: SignalName
    value: float
    unit: str


class ReadingsIngest(SQLModel):
    readings: list[ReadingInput]


class CommandInput(SQLModel):
    setpoint_name: str
    value: float
    unit: str
    apply_at_time_h: float


class RelativeCommandInput(SQLModel):
    value: float
    unit: str
    apply_after_minutes: float


class SimulatorStart(SQLModel):
    run_id: Literal["run_A", "run_B", "run_C"] = "run_A"
    start_minute: int = Field(default=0, ge=0)
    process_minutes_per_second: float = Field(default=1.0, gt=0, le=60)


class ControllerConfigUpdate(SQLModel):
    do_target_percent: float = Field(ge=0, le=100)
    dwell_minutes: float = Field(gt=0)


class ControllerConfigRead(SQLModel):
    do_target_percent: float | None
    dwell_minutes: float | None
    configured: bool


@dataclass(slots=True)
class LoadedRun:
    samples: list[dict[str, float]]


def load_limits(path: Path = DATA_DIRECTORY / "limits.json") -> dict:
    with path.open(encoding="utf-8") as limits_file:
        limits = json.load(limits_file)
    feed = limits.get("feed_rate")
    if (
        not isinstance(feed, dict)
        or not isinstance(feed.get("unit"), str)
        or not isinstance(feed.get("min"), (int, float))
        or not isinstance(feed.get("max"), (int, float))
        or not math.isfinite(feed["min"])
        or not math.isfinite(feed["max"])
        or feed["min"] >= feed["max"]
    ):
        raise ValueError("limits.json must define feed_rate unit, min, and max")
    return limits


def load_simulation_runs(data_directory: Path = DATA_DIRECTORY) -> dict[str, LoadedRun]:
    runs: dict[str, LoadedRun] = {}
    for run_id in ("run_A", "run_B", "run_C"):
        samples_by_time: dict[float, dict[str, float]] = {}
        path = data_directory / f"{run_id}.csv"
        with path.open(newline="", encoding="utf-8") as run_file:
            reader = csv.DictReader(run_file)
            if reader.fieldnames != ["time_h", "signal_name", "value", "unit"]:
                raise ValueError(f"{path.name} has an unexpected header")
            for row in reader:
                name = row["signal_name"]
                if name not in READING_UNITS:
                    raise ValueError(f"{path.name} contains unsupported signal {name}")
                if row["unit"] != READING_UNITS[name]:
                    raise ValueError(f"{path.name} has an invalid unit for {name}")
                process_time = float(row["time_h"])
                value = float(row["value"])
                if not math.isfinite(process_time) or not math.isfinite(value):
                    raise ValueError(f"{path.name} contains a non-finite value")
                signals = samples_by_time.setdefault(process_time, {})
                if name in signals:
                    raise ValueError(f"{path.name} contains duplicate {name} at {process_time}")
                signals[name] = value

        source_samples = sorted(samples_by_time.items())
        if any(
            not math.isclose(
                source_samples[index][0] - source_samples[index - 1][0],
                PROCESS_TIME_STEP_H,
                abs_tol=0.0001,
            )
            for index in range(1, len(source_samples))
        ):
            raise ValueError(f"{path.name} is not sampled on a one-minute grid")
        samples = []
        for index, (_source_time_h, signals) in enumerate(source_samples):
            if set(signals) != set(READING_UNITS):
                raise ValueError(
                    f"{path.name} has incomplete readings at "
                    f"{_source_time_h}"
                )
            samples.append({"time_h": index / 60, **signals})
        if not samples:
            raise ValueError(f"{path.name} contains no readings")
        runs[run_id] = LoadedRun(samples)
    return runs


def _latest_complete_window(
    session: Session,
    run_id: str,
    run_instance_id: str | None,
) -> tuple[list[float], list[float], float] | None:
    latest_time = session.exec(
        select(func.max(Reading.time_h)).where(
            Reading.run_id == run_id,
            Reading.run_instance_id == run_instance_id,
        )
    ).one()
    if latest_time is None:
        return None
    earliest_time = latest_time - (HISTORY_MINUTES - 1) / 60 - 0.0001
    readings = session.exec(
        select(Reading)
        .where(
            Reading.run_id == run_id,
            Reading.run_instance_id == run_instance_id,
            Reading.time_h >= earliest_time,
        )
        .order_by(Reading.time_h, Reading.id)
    ).all()
    values_by_time: dict[float, dict[str, float]] = {}
    for reading in readings:
        values_by_time.setdefault(reading.time_h, {})[reading.signal_name] = reading.value
    complete_samples = [
        (time_h, values)
        for time_h, values in sorted(values_by_time.items())
        if "DO" in values and "feed_rate" in values
    ]
    if len(complete_samples) < HISTORY_MINUTES:
        return None
    complete_samples = complete_samples[-HISTORY_MINUTES:]
    times = [sample[0] for sample in complete_samples]
    if any(
        not math.isclose(right - left, PROCESS_TIME_STEP_H, abs_tol=0.0001)
        for left, right in zip(times, times[1:])
    ):
        return None
    return (
        [sample[1]["DO"] for sample in complete_samples],
        [sample[1]["feed_rate"] for sample in complete_samples],
        times[-1],
    )


def create_forecast(
    session: Session,
    run_id: str,
    model: Pipeline,
    run_instance_id: str | None = None,
) -> list[Prediction]:
    history = _latest_complete_window(session, run_id, run_instance_id)
    if history is None:
        return []
    do_history, feed_history, made_at_time_h = history
    values = predict_next_minutes(model, do_history, feed_history)
    predictions = [
        Prediction(
            run_id=run_id,
            run_instance_id=run_instance_id,
            made_at_time_h=made_at_time_h,
            target_time_h=made_at_time_h + horizon / 60,
            horizon_minutes=horizon,
            value=value,
            model_name=MODEL_NAME,
        )
        for horizon, value in enumerate(values, start=1)
    ]
    session.add_all(predictions)
    session.commit()
    return predictions


def store_readings(
    session: Session,
    readings: list[ReadingInput],
    run_id: str,
    model: Pipeline,
    run_instance_id: str | None = None,
) -> list[Prediction]:
    reading_keys: set[tuple[float, str]] = set()
    for reading in readings:
        key = (reading.time_h, reading.signal_name)
        if key in reading_keys:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate {reading.signal_name} reading at {reading.time_h}.",
            )
        reading_keys.add(key)
        expected_unit = READING_UNITS[reading.signal_name]
        if reading.unit != expected_unit:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{reading.signal_name} readings must use {expected_unit}, "
                    f"not {reading.unit}"
                ),
            )
        if not math.isfinite(reading.time_h) or reading.time_h < 0:
            raise HTTPException(status_code=422, detail="Reading time_h must be finite and non-negative")
        if not math.isfinite(reading.value):
            raise HTTPException(status_code=422, detail="Reading values must be finite")
    session.add_all(
        [
            Reading(
                run_id=run_id,
                run_instance_id=run_instance_id,
                time_h=reading.time_h,
                signal_name=reading.signal_name,
                value=reading.value,
                unit=reading.unit,
            )
            for reading in readings
        ]
    )
    session.commit()
    return create_forecast(session, run_id, model, run_instance_id)


def submit_command(
    session: Session,
    payload: CommandInput,
    source: Literal["manual", "controller"],
    limits: dict,
) -> tuple[ControlCommand, bool]:
    state = session.get(SimulatorState, 1)
    config = session.get(ControlConfig, 1)
    feed_limits = limits["feed_rate"]
    process_time = state.process_time_h if state else 0.0
    run_id = state.run_id if state else None
    run_instance_id = state.run_instance_id if state else None
    reason = None

    if payload.setpoint_name != "feed_rate":
        reason = "Only the feed_rate setpoint is supported."
    elif payload.unit != feed_limits["unit"]:
        reason = f"feed_rate commands must use {feed_limits['unit']}."
    elif not math.isfinite(payload.value) or not (
        feed_limits["min"] <= payload.value <= feed_limits["max"]
    ):
        reason = (
            f"feed_rate must be between {feed_limits['min']} and "
            f"{feed_limits['max']} {feed_limits['unit']}."
        )
    elif not math.isfinite(payload.apply_at_time_h):
        reason = "apply_at_time_h must be finite."
    elif state is None or state.status != "running":
        reason = "The simulator must be running to accept a command."
    elif payload.apply_at_time_h < process_time:
        reason = "apply_at_time_h cannot be earlier than the device process time."
    elif (
        payload.apply_at_time_h - process_time
        < ACTUATOR_LAG_MINUTES / 60 - 0.000001
    ):
        reason = (
            f"Commands must allow the {ACTUATOR_LAG_MINUTES:g}-minute actuator lag."
        )
    else:
        pending = session.exec(
            select(ControlCommand).where(
                ControlCommand.setpoint_name == payload.setpoint_name,
                ControlCommand.status == "pending",
                ControlCommand.run_instance_id == run_instance_id,
            )
        ).first()
        if pending is not None:
            reason = f"Command #{pending.id} for {payload.setpoint_name} is still pending."
        elif config and config.dwell_minutes is not None:
            last_command = session.exec(
                select(ControlCommand)
                .where(
                    ControlCommand.run_id == run_id,
                    ControlCommand.run_instance_id == run_instance_id,
                    ControlCommand.setpoint_name == payload.setpoint_name,
                    ControlCommand.status.in_(("pending", "applied")),
                )
                .order_by(ControlCommand.issued_at_time_h.desc())
            ).first()
            if (
                last_command
                and process_time - last_command.issued_at_time_h
                < config.dwell_minutes / 60 - 0.000001
            ):
                reason = (
                    f"Commands must be at least {config.dwell_minutes:g} process-minutes apart."
                )

    command = ControlCommand(
        run_id=run_id,
        run_instance_id=run_instance_id,
        setpoint_name=payload.setpoint_name,
        value=payload.value,
        unit=payload.unit,
        requested_apply_at_time_h=payload.apply_at_time_h,
        issued_at_time_h=process_time,
        apply_at_time_h=payload.apply_at_time_h,
        source=source,
        status="rejected" if reason else "pending",
        rejection_reason=reason,
    )
    session.add(command)
    session.commit()
    session.refresh(command)
    return command, reason is None


def maybe_issue_controller_command(
    session: Session,
    state: SimulatorState,
    limits: dict,
) -> ControlCommand | None:
    config = session.get(ControlConfig, 1)
    if (
        config is None
        or config.do_target_percent is None
        or config.dwell_minutes is None
        or state.run_id is None
    ):
        return None
    prediction = session.exec(
        select(Prediction)
        .where(
            Prediction.run_id == state.run_id,
            Prediction.run_instance_id == state.run_instance_id,
            Prediction.made_at_time_h == state.process_time_h,
            Prediction.horizon_minutes == CONTROLLER_FORECAST_HORIZON_MINUTES,
        )
        .order_by(Prediction.id.desc())
    ).first()
    if prediction is None:
        return None

    pending = session.exec(
        select(ControlCommand).where(
            ControlCommand.setpoint_name == "feed_rate",
            ControlCommand.status == "pending",
            ControlCommand.run_instance_id == state.run_instance_id,
        )
    ).first()
    if pending is not None:
        return None
    last_command = session.exec(
        select(ControlCommand)
        .where(
            ControlCommand.run_id == state.run_id,
            ControlCommand.run_instance_id == state.run_instance_id,
            ControlCommand.setpoint_name == "feed_rate",
            ControlCommand.status.in_(("pending", "applied")),
        )
        .order_by(ControlCommand.issued_at_time_h.desc())
    ).first()
    if (
        last_command
        and state.process_time_h - last_command.issued_at_time_h
        < config.dwell_minutes / 60 - 0.000001
    ):
        return None

    proposed = state.current_feed_rate + (
        prediction.value - config.do_target_percent
    ) / DO_FEED_GAIN
    feed_limits = limits["feed_rate"]
    proposed = min(max(proposed, feed_limits["min"]), feed_limits["max"])
    proposed = round(proposed, 3)
    if math.isclose(proposed, state.current_feed_rate, abs_tol=0.0005):
        return None
    payload = CommandInput(
        setpoint_name="feed_rate",
        value=proposed,
        unit=feed_limits["unit"],
        apply_at_time_h=state.process_time_h + ACTUATOR_LAG_MINUTES / 60,
    )
    command, accepted = submit_command(session, payload, "controller", limits)
    return command if accepted else None


def simulation_tick(
    engine: Engine,
    runs: dict[str, LoadedRun],
    model: Pipeline,
    limits: dict,
) -> tuple[bool, float]:
    with Session(engine) as session:
        state = session.get(SimulatorState, 1)
        if state is None or state.status != "running" or state.run_id is None:
            return False, 1.0
        run = runs[state.run_id]
        if state.next_index >= len(run.samples):
            state.status = "completed"
            state.wall_time = datetime.now(timezone.utc)
            session.add(state)
            session.commit()
            return False, state.process_minutes_per_second

        sample = run.samples[state.next_index]
        process_time = sample["time_h"]
        elapsed_minutes = max(0.0, (process_time - state.process_time_h) * 60)
        target_deviation = (
            -DO_FEED_GAIN * (state.current_feed_rate - sample["feed_rate"])
            if state.feed_command_active
            else 0.0
        )
        response_fraction = 1 - math.exp(
            -elapsed_minutes / ACTUATOR_TIME_CONSTANT_MINUTES
        )
        state.do_deviation += (
            target_deviation - state.do_deviation
        ) * response_fraction
        dissolved_oxygen = min(
            max(sample["DO"] + state.do_deviation, 0.0),
            100.0,
        )
        if not state.feed_command_active:
            state.current_feed_rate = sample["feed_rate"]

        due_commands = session.exec(
            select(ControlCommand)
            .where(
                ControlCommand.run_id == state.run_id,
                ControlCommand.run_instance_id == state.run_instance_id,
                ControlCommand.setpoint_name == "feed_rate",
                ControlCommand.status == "pending",
                ControlCommand.apply_at_time_h <= process_time,
            )
            .order_by(ControlCommand.apply_at_time_h, ControlCommand.id)
        ).all()
        for command in due_commands:
            state.current_feed_rate = command.value
            state.feed_command_active = True
            command.status = "applied"
            session.add(command)

        values = {
            "DO": dissolved_oxygen,
            "pH": sample["pH"],
            "temp": sample["temp"],
            "feed_rate": state.current_feed_rate,
        }
        session.add_all(
            [
                Reading(
                    run_id=state.run_id,
                    run_instance_id=state.run_instance_id,
                    time_h=process_time,
                    signal_name=signal_name,
                    value=value,
                    unit=READING_UNITS[signal_name],
                )
                for signal_name, value in values.items()
            ]
        )
        state.process_time_h = process_time
        state.next_index += 1
        state.wall_time = datetime.now(timezone.utc)
        session.add(state)
        session.commit()
        create_forecast(session, state.run_id, model, state.run_instance_id)
        refreshed_state = session.get(SimulatorState, 1)
        if refreshed_state is not None:
            maybe_issue_controller_command(session, refreshed_state, limits)
        return True, state.process_minutes_per_second


async def simulator_worker(app: FastAPI) -> None:
    while True:
        should_continue, speed = simulation_tick(
            app.state.engine,
            app.state.runs,
            app.state.forecaster,
            app.state.feed_limits,
        )
        if not should_continue:
            return
        await asyncio.sleep(1 / speed)
