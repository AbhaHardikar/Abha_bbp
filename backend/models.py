
from datetime import date, datetime, timezone
from typing import Literal

from sqlmodel import Field, SQLModel


class Equipment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)


class Batch(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    start_date: date
    end_date: date


class UnitOperation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    type: str
    color: str = "#4F83CC"
    status: str = "draft"
    start_date: date
    end_date: date
    batch_id: int = Field(foreign_key="batch.id")
    equipment_id: int = Field(foreign_key="equipment.id")


class UnitOperationDependency(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    from_unitop_id: int = Field(foreign_key="unitoperation.id")
    to_unitop_id: int = Field(foreign_key="unitoperation.id")


class Reading(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    time_h: float = Field(index=True)
    signal_name: str
    value: float
    unit: str
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Prediction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    made_at_time_h: float
    target_time_h: float = Field(index=True)
    horizon_minutes: int
    value: float
    model_name: str
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ControlCommand(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    setpoint_name: str
    value: float
    unit: str
    requested_apply_at_time_h: float
    issued_at_time_h: float
    apply_at_time_h: float
    source: str
    status: str = "pending"
    rejection_reason: str | None = None
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SimulatorState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    run_id: str | None = None
    next_index: int = 0
    process_time_h: float = 0.0
    process_minutes_per_second: float = 1.0
    current_feed_rate: float = 0.0
    feed_command_active: bool = False
    do_deviation: float = 0.0
    status: str = "stopped"
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ControlConfig(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    do_target_percent: float | None = None
    dwell_minutes: float | None = None
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


OperationType = Literal["Seed", "Bioreactor", "TFF", "Spray", "Sum"]
OperationStatus = Literal["draft", "confirmed", "completed"]
SignalName = Literal["DO", "pH", "temp", "feed_rate"]
