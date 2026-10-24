import asyncio
import math
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from hmac import compare_digest
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import event, inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from control_service import (
    CommandInput,
    ControllerConfigRead,
    ControllerConfigUpdate,
    ReadingsIngest,
    RelativeCommandInput,
    SimulatorStart,
    load_limits,
    load_simulation_runs,
    simulator_worker,
    store_readings,
    submit_command,
)
from forecaster import train_forecaster
from models import (
    Batch,
    ControlCommand,
    ControlConfig,
    Equipment,
    OperationStatus,
    OperationType,
    Prediction,
    Reading,
    SimulatorState,
    UnitOperation,
    UnitOperationDependency,
)

DATABASE_PATH = Path(__file__).resolve().parent / "bioprocess.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATABASE_PATH}"
WRITE_API_TOKEN = os.environ.get("WRITE_API_TOKEN") or None
FRONTEND_PATH = Path(__file__).resolve().parent.parent / "frontend"
DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data_kit"
EQUIPMENT_NAMES = ("1.5L", "15L", "20L", "75L", "1500L")
OPERATION_ORDER = ("Seed", "Bioreactor", "TFF", "Spray", "Sum")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OperationCreate(SQLModel):
    name: str
    type: OperationType
    color: str = "#4F83CC"
    status: OperationStatus = "draft"
    start_date: date
    end_date: date
    batch_id: int
    equipment_id: int


class OperationUpdate(SQLModel):
    name: str | None = None
    type: OperationType | None = None
    color: str | None = None
    status: OperationStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    batch_id: int | None = None
    equipment_id: int | None = None


class OperationRead(SQLModel):
    id: int
    name: str
    type: OperationType
    color: str
    status: OperationStatus
    start_date: date
    end_date: date
    batch_id: int
    batch_name: str
    equipment_id: int
    equipment_name: str


class Violation(SQLModel):
    rule: str
    message: str
    operation_ids: list[int]


class OperationSaveResponse(SQLModel):
    operation: OperationRead
    violations: list[Violation]


class DependencyCreate(SQLModel):
    from_unitop_id: int
    to_unitop_id: int


class DependencyRead(SQLModel):
    id: int
    from_unitop_id: int
    to_unitop_id: int


class DependencySaveResponse(SQLModel):
    dependency: DependencyRead
    violations: list[Violation]


class ScheduleResponse(SQLModel):
    equipment: list[Equipment]
    batches: list[Batch]
    unit_operations: list[OperationRead]
    dependencies: list[DependencyRead]
    violations: list[Violation]


class CommandResponse(SQLModel):
    id: int
    accepted: bool
    status: str
    reason: str | None
    apply_at_time_h: float


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_options = {"connect_args": connect_args}
    if database_url.startswith("postgresql+psycopg://"):
        engine_options.update(pool_pre_ping=True, pool_recycle=300)
    if database_url in ("sqlite://", "sqlite:///:memory:"):
        engine_options["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_options)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def seed_database(engine: Engine) -> None:
    with Session(engine) as session:
        if session.exec(select(Equipment)).first() is not None:
            return

        equipment = [Equipment(name=name) for name in EQUIPMENT_NAMES]
        batches = [
            Batch(name="Batch Alpha", start_date=date(2026, 10, 20), end_date=date(2026, 11, 10)),
            Batch(name="Batch Beta", start_date=date(2026, 10, 20), end_date=date(2026, 11, 10)),
            Batch(name="Batch Gamma", start_date=date(2026, 10, 20), end_date=date(2026, 11, 10)),
        ]
        session.add_all(equipment + batches)
        session.commit()
        for item in equipment + batches:
            session.refresh(item)

        equipment_by_name = {item.name: item.id for item in equipment}
        batch_by_name = {item.name: item.id for item in batches}
        operations = [
            UnitOperation(
                name="Alpha Seed",
                type="Seed",
                start_date=date(2026, 10, 20),
                end_date=date(2026, 10, 23),
                batch_id=batch_by_name["Batch Alpha"],
                equipment_id=equipment_by_name["1.5L"],
            ),
            UnitOperation(
                name="Alpha Bioreactor",
                type="Bioreactor",
                start_date=date(2026, 10, 23),
                end_date=date(2026, 10, 28),
                batch_id=batch_by_name["Batch Alpha"],
                equipment_id=equipment_by_name["15L"],
            ),
            UnitOperation(
                name="Beta Seed",
                type="Seed",
                start_date=date(2026, 10, 22),
                end_date=date(2026, 10, 25),
                batch_id=batch_by_name["Batch Beta"],
                equipment_id=equipment_by_name["1.5L"],
            ),
            UnitOperation(
                name="Beta Bioreactor",
                type="Bioreactor",
                start_date=date(2026, 10, 25),
                end_date=date(2026, 10, 30),
                batch_id=batch_by_name["Batch Beta"],
                equipment_id=equipment_by_name["75L"],
            ),
            UnitOperation(
                name="Gamma Bioreactor",
                type="Bioreactor",
                start_date=date(2026, 10, 24),
                end_date=date(2026, 10, 27),
                batch_id=batch_by_name["Batch Gamma"],
                equipment_id=equipment_by_name["1500L"],
            ),
            UnitOperation(
                name="Gamma Seed",
                type="Seed",
                start_date=date(2026, 10, 27),
                end_date=date(2026, 10, 29),
                batch_id=batch_by_name["Batch Gamma"],
                equipment_id=equipment_by_name["20L"],
            ),
        ]
        session.add_all(operations)
        session.commit()


def initialize_control_state(
    engine: Engine,
    seed_demo_control_defaults: bool = False,
) -> None:
    with Session(engine) as session:
        simulator = session.get(SimulatorState, 1)
        if simulator is None:
            session.add(SimulatorState())
        else:
            if simulator.status == "running":
                simulator.status = "paused"
                simulator.wall_time = datetime.now(timezone.utc)
                session.add(simulator)
            if (
                simulator.run_id is not None
                and simulator.run_instance_id is None
                and simulator.status in {"running", "paused"}
            ):
                simulator.run_instance_id = uuid4().hex
                simulator.wall_time = datetime.now(timezone.utc)
                session.add(simulator)
                pending_commands = session.exec(
                    select(ControlCommand).where(
                        ControlCommand.run_id == simulator.run_id,
                        ControlCommand.run_instance_id.is_(None),
                        ControlCommand.status == "pending",
                    )
                ).all()
                for command in pending_commands:
                    command.run_instance_id = simulator.run_instance_id
                    session.add(command)
        if session.get(ControlConfig, 1) is None:
            session.add(
                ControlConfig(
                    do_target_percent=50.0 if seed_demo_control_defaults else None,
                    dwell_minutes=10.0 if seed_demo_control_defaults else None,
                )
            )
        session.commit()


def migrate_replay_instance_columns(engine: Engine) -> None:
    for table_name in ("reading", "prediction", "controlcommand", "simulatorstate"):
        columns = {
            column["name"]
            for column in inspect(engine).get_columns(table_name)
        }
        if "run_instance_id" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN run_instance_id VARCHAR")
                )


def command_response(command: ControlCommand, accepted: bool) -> CommandResponse:
    return CommandResponse(
        id=command.id,
        accepted=accepted,
        status=command.status,
        reason=command.rejection_reason,
        apply_at_time_h=command.apply_at_time_h,
    )


def control_state_payload(session: Session, limits: dict) -> dict:
    simulator = session.get(SimulatorState, 1)
    config = session.get(ControlConfig, 1)
    run_id = simulator.run_id if simulator and simulator.run_id else "external"
    run_instance_id = simulator.run_instance_id if simulator else None
    readings = session.exec(
        select(Reading)
        .where(
            Reading.run_id == run_id,
            Reading.run_instance_id == run_instance_id,
        )
        .order_by(Reading.time_h.desc(), Reading.id.desc())
        .limit(480)
    ).all()
    predictions = session.exec(
        select(Prediction)
        .where(
            Prediction.run_id == run_id,
            Prediction.run_instance_id == run_instance_id,
        )
        .order_by(Prediction.id.desc())
        .limit(10)
    ).all()
    command_query = select(ControlCommand)
    if simulator and simulator.run_id and run_instance_id:
        command_query = command_query.where(
            ControlCommand.run_id == run_id,
            ControlCommand.run_instance_id == run_instance_id,
        )
    commands = session.exec(
        command_query.order_by(ControlCommand.id.desc()).limit(50)
    ).all()
    return {
        "simulator": (
            {
                "status": simulator.status,
                "run_id": simulator.run_id,
                "process_time_h": simulator.process_time_h,
                "process_minutes_per_second": simulator.process_minutes_per_second,
                "current_feed_rate": simulator.current_feed_rate,
                "do_deviation": simulator.do_deviation,
            }
            if simulator
            else None
        ),
        "controller": {
            "configured": bool(
                config
                and config.do_target_percent is not None
                and config.dwell_minutes is not None
            ),
            "do_target_percent": config.do_target_percent if config else None,
            "dwell_minutes": config.dwell_minutes if config else None,
        },
        "limits": limits,
        "readings": [
            {
                "run_id": item.run_id,
                "time_h": item.time_h,
                "signal_name": item.signal_name,
                "value": item.value,
                "unit": item.unit,
                "wall_time": item.wall_time.isoformat(),
            }
            for item in reversed(readings)
        ],
        "predictions": [
            {
                "run_id": item.run_id,
                "made_at_time_h": item.made_at_time_h,
                "target_time_h": item.target_time_h,
                "horizon_minutes": item.horizon_minutes,
                "value": item.value,
                "model_name": item.model_name,
                "wall_time": item.wall_time.isoformat(),
            }
            for item in reversed(predictions)
        ],
        "commands": [
            {
                "id": item.id,
                "run_id": item.run_id,
                "setpoint_name": item.setpoint_name,
                "value": item.value,
                "unit": item.unit,
                "requested_apply_at_time_h": item.requested_apply_at_time_h,
                "issued_at_time_h": item.issued_at_time_h,
                "apply_at_time_h": item.apply_at_time_h,
                "source": item.source,
                "status": item.status,
                "rejection_reason": item.rejection_reason,
                "wall_time": item.wall_time.isoformat(),
            }
            for item in reversed(commands)
        ],
    }


def operation_read(
    operation: UnitOperation,
    batches: dict[int, Batch],
    equipment: dict[int, Equipment],
) -> OperationRead:
    return OperationRead(
        id=operation.id,
        name=operation.name,
        type=operation.type,
        color=operation.color,
        status=operation.status,
        start_date=operation.start_date,
        end_date=operation.end_date,
        batch_id=operation.batch_id,
        batch_name=batches[operation.batch_id].name,
        equipment_id=operation.equipment_id,
        equipment_name=equipment[operation.equipment_id].name,
    )


def find_violations(
    operations: list[UnitOperation],
    batches: dict[int, Batch],
    equipment: dict[int, Equipment],
    dependencies: list[UnitOperationDependency],
) -> list[Violation]:
    violations: list[Violation] = []
    order = {name: index for index, name in enumerate(OPERATION_ORDER)}

    for operation in operations:
        batch = batches[operation.batch_id]
        if operation.start_date < batch.start_date or operation.end_date > batch.end_date:
            violations.append(
                Violation(
                    rule="batch_bounds",
                    message=(
                        f"{operation.name} (#{operation.id}) must lie within "
                        f"{batch.name} ({batch.start_date} to {batch.end_date})."
                    ),
                    operation_ids=[operation.id],
                )
            )
        if operation.start_date >= operation.end_date:
            violations.append(
                Violation(
                    rule="operation_date_range",
                    message=f"{operation.name} (#{operation.id}) must end after it starts.",
                    operation_ids=[operation.id],
                )
            )

    equipment_pairs: set[tuple[int, int]] = set()
    sequence_pairs: set[tuple[int, int]] = set()
    operations_by_id = {operation.id: operation for operation in operations}
    for index, first in enumerate(operations):
        for second in operations[index + 1 :]:
            pair = tuple(sorted((first.id, second.id)))
            if (
                first.equipment_id == second.equipment_id
                and first.start_date < second.end_date
                and second.start_date < first.end_date
                and pair not in equipment_pairs
            ):
                equipment_pairs.add(pair)
                violations.append(
                    Violation(
                        rule="equipment_conflict",
                        message=(
                            f"{first.name} (#{first.id}) and {second.name} (#{second.id}) "
                            f"overlap on {equipment[first.equipment_id].name}."
                        ),
                        operation_ids=list(pair),
                    )
                )
            if first.batch_id != second.batch_id:
                continue
            first_precedes = order[first.type] < order[second.type]
            second_precedes = order[second.type] < order[first.type]
            earlier, later = (first, second) if first_precedes else (second, first)
            if (
                (first_precedes or second_precedes)
                and earlier.end_date > later.start_date
                and pair not in sequence_pairs
            ):
                sequence_pairs.add(pair)
                violations.append(
                    Violation(
                        rule="operation_sequence",
                        message=(
                            f"{earlier.name} (#{earlier.id}) must finish no later than "
                            f"{later.name} (#{later.id}) starts."
                        ),
                        operation_ids=[earlier.id, later.id],
                    )
                )

    dependency_pairs: set[tuple[int, int]] = set()
    for dependency in dependencies:
        pair = (dependency.from_unitop_id, dependency.to_unitop_id)
        if pair in dependency_pairs:
            continue
        dependency_pairs.add(pair)
        source = operations_by_id.get(dependency.from_unitop_id)
        target = operations_by_id.get(dependency.to_unitop_id)
        if source and target and target.start_date < source.end_date:
            violations.append(
                Violation(
                    rule="dependency",
                    message=(
                        f"{target.name} (#{target.id}) cannot start before "
                        f"{source.name} (#{source.id}) ends."
                    ),
                    operation_ids=[source.id, target.id],
                )
            )

    return violations


def create_app(
    database_url: str = DATABASE_URL,
    write_api_token: str | None = WRITE_API_TOKEN,
) -> FastAPI:
    write_api_token = write_api_token or None
    hosted = os.environ.get("RENDER", "").lower() == "true"
    if hosted and write_api_token is None:
        raise RuntimeError("WRITE_API_TOKEN must be configured on hosted deployments")
    if write_api_token is not None and (
        len(write_api_token) < 32 or not write_api_token.isascii()
    ):
        raise ValueError("WRITE_API_TOKEN must contain at least 32 ASCII characters")

    engine = make_engine(database_url)
    app = FastAPI(title="Boston Bioprocess API")
    app.state.engine = engine
    app.state.simulator_task = None

    @app.middleware("http")
    async def authorize_write_requests(request: Request, call_next):
        if request.method in WRITE_METHODS and write_api_token is not None:
            authorization = request.headers.get("authorization", "")
            scheme, separator, supplied_token = authorization.partition(" ")
            if (
                not separator
                or scheme.lower() != "bearer"
                or not compare_digest(
                    supplied_token.encode("utf-8"),
                    write_api_token.encode("utf-8"),
                )
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "A valid write access key is required."},
                )
        return await call_next(request)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        SQLModel.metadata.create_all(engine)
        migrate_replay_instance_columns(engine)
        seed_database(engine)
        initialize_control_state(
            engine,
            seed_demo_control_defaults=engine.dialect.name == "postgresql",
        )
        app.state.feed_limits = load_limits()
        app.state.runs = load_simulation_runs(DATA_DIRECTORY)
        app.state.forecaster, app.state.forecaster_metrics = train_forecaster(DATA_DIRECTORY)
        yield
        task = app.state.simulator_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        with Session(engine) as session:
            simulator = session.get(SimulatorState, 1)
            if simulator and simulator.status == "running":
                simulator.status = "paused"
                simulator.wall_time = datetime.now(timezone.utc)
                session.add(simulator)
                session.commit()

    app.router.lifespan_context = lifespan

    def get_session(request: Request) -> Iterator[Session]:
        with Session(request.app.state.engine) as session:
            yield session

    async def stop_simulator_task() -> None:
        task = app.state.simulator_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        app.state.simulator_task = None

    @app.get("/")
    def home():
        return FileResponse(FRONTEND_PATH / "index.html")

    @app.get("/health")
    def health_check():
        return {"status": "healthy"}

    @app.get("/api/schedule", response_model=ScheduleResponse)
    def get_schedule(
        start_date: date = Query(...),
        end_date: date = Query(...),
        session: Session = Depends(get_session),
    ):
        if start_date >= end_date:
            raise HTTPException(status_code=422, detail="end_date must be after start_date")

        operations = list(session.exec(select(UnitOperation)).all())
        batches_list = list(session.exec(select(Batch)).all())
        equipment_list = list(session.exec(select(Equipment)).all())
        dependencies = list(session.exec(select(UnitOperationDependency)).all())
        batches_by_id = {batch.id: batch for batch in batches_list}
        equipment_by_id = {item.id: item for item in equipment_list}
        visible_operations = [
            operation
            for operation in operations
            if (
                operation.start_date < end_date and operation.end_date > start_date
            )
            or start_date <= operation.start_date < end_date
        ]
        visible_ids = {operation.id for operation in visible_operations}
        violations = find_violations(
            operations,
            batches_by_id,
            equipment_by_id,
            dependencies,
        )
        visible_violations = [
            violation
            for violation in violations
            if visible_ids.intersection(violation.operation_ids)
        ]
        visible_batches = [
            batch
            for batch in batches_list
            if any(operation.batch_id == batch.id for operation in visible_operations)
        ]
        return ScheduleResponse(
            equipment=equipment_list,
            batches=visible_batches,
            unit_operations=[
                operation_read(operation, batches_by_id, equipment_by_id)
                for operation in visible_operations
            ],
            dependencies=[
                DependencyRead.model_validate(dependency)
                for dependency in dependencies
                if visible_ids.intersection(
                    (dependency.from_unitop_id, dependency.to_unitop_id)
                )
            ],
            violations=visible_violations,
        )

    @app.post("/api/unit_operations", response_model=OperationSaveResponse)
    def create_unit_operation(
        payload: OperationCreate,
        session: Session = Depends(get_session),
    ):
        batch = session.get(Batch, payload.batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail=f"Batch {payload.batch_id} was not found")
        equipment = session.get(Equipment, payload.equipment_id)
        if equipment is None:
            raise HTTPException(
                status_code=404,
                detail=f"Equipment {payload.equipment_id} was not found",
            )

        operation = UnitOperation(**payload.model_dump())
        session.add(operation)
        session.commit()
        session.refresh(operation)
        operations = list(session.exec(select(UnitOperation)).all())
        batches = {item.id: item for item in session.exec(select(Batch)).all()}
        dependencies = list(session.exec(select(UnitOperationDependency)).all())
        return OperationSaveResponse(
            operation=operation_read(
                operation,
                batches,
                {item.id: item for item in session.exec(select(Equipment)).all()},
            ),
            violations=[
                violation
                for violation in find_violations(
                    operations,
                    batches,
                    {item.id: item for item in session.exec(select(Equipment)).all()},
                    dependencies,
                )
                if operation.id in violation.operation_ids
            ],
        )

    @app.put("/api/unit_operations/{op_id}", response_model=OperationSaveResponse)
    def update_unit_operation(
        op_id: int,
        payload: OperationUpdate,
        session: Session = Depends(get_session),
    ):
        operation = session.get(UnitOperation, op_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Unit operation {op_id} was not found")
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="At least one field must be provided")
        if any(value is None for value in changes.values()):
            raise HTTPException(status_code=422, detail="Updated fields cannot be null")
        immutable_fields = {
            "start_date",
            "end_date",
            "equipment_id",
            "batch_id",
            "type",
            "status",
        }
        if operation.status == "completed" and any(
            field in changes and changes[field] != getattr(operation, field)
            for field in immutable_fields
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Completed unit operation {operation.name} (#{op_id}) "
                    "cannot be moved or have its status changed"
                ),
            )

        candidate = operation.model_copy(update=changes)
        if session.get(Batch, candidate.batch_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Batch {candidate.batch_id} was not found",
            )
        if session.get(Equipment, candidate.equipment_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Equipment {candidate.equipment_id} was not found",
            )

        for field, value in changes.items():
            setattr(operation, field, value)
        session.add(operation)
        session.commit()
        session.refresh(operation)
        operations = list(session.exec(select(UnitOperation)).all())
        batches = {item.id: item for item in session.exec(select(Batch)).all()}
        dependencies = list(session.exec(select(UnitOperationDependency)).all())
        equipment = {item.id: item for item in session.exec(select(Equipment)).all()}
        return OperationSaveResponse(
            operation=operation_read(operation, batches, equipment),
            violations=[
                violation
                for violation in find_violations(
                    operations,
                    batches,
                    equipment,
                    dependencies,
                )
                if operation.id in violation.operation_ids
            ],
        )

    @app.post(
        "/api/unit_operation_dependencies",
        response_model=DependencySaveResponse,
    )
    def create_dependency(
        payload: DependencyCreate,
        session: Session = Depends(get_session),
    ):
        source = session.get(UnitOperation, payload.from_unitop_id)
        target = session.get(UnitOperation, payload.to_unitop_id)
        if source is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source unit operation {payload.from_unitop_id} was not found",
            )
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Target unit operation {payload.to_unitop_id} was not found",
            )
        if source.id == target.id:
            raise HTTPException(status_code=422, detail="An operation cannot depend on itself")
        duplicate = session.exec(
            select(UnitOperationDependency).where(
                UnitOperationDependency.from_unitop_id == source.id,
                UnitOperationDependency.to_unitop_id == target.id,
            )
        ).first()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="That dependency already exists")

        dependency = UnitOperationDependency(
            from_unitop_id=source.id,
            to_unitop_id=target.id,
        )
        session.add(dependency)
        session.commit()
        session.refresh(dependency)
        operations = list(session.exec(select(UnitOperation)).all())
        batches = {item.id: item for item in session.exec(select(Batch)).all()}
        equipment = {item.id: item for item in session.exec(select(Equipment)).all()}
        dependencies = list(session.exec(select(UnitOperationDependency)).all())
        return DependencySaveResponse(
            dependency=DependencyRead.model_validate(dependency),
            violations=[
                violation
                for violation in find_violations(
                    operations,
                    batches,
                    equipment,
                    dependencies,
                )
                if violation.rule == "dependency"
                and set(violation.operation_ids) == {source.id, target.id}
            ],
        )

    @app.delete("/api/unit_operations/{op_id}")
    def delete_unit_operation(
        op_id: int,
        session: Session = Depends(get_session),
    ):
        operation = session.get(UnitOperation, op_id)
        if operation is None:
            raise HTTPException(status_code=404, detail=f"Unit operation {op_id} was not found")
        if operation.status == "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Completed unit operation {operation.name} (#{op_id}) cannot be deleted",
            )
        dependencies = session.exec(
            select(UnitOperationDependency).where(
                (UnitOperationDependency.from_unitop_id == op_id)
                | (UnitOperationDependency.to_unitop_id == op_id)
            )
        ).all()
        for dependency in dependencies:
            session.delete(dependency)
        session.delete(operation)
        session.commit()
        return {"deleted_id": op_id}

    @app.get("/api/forecaster/metrics")
    def get_forecaster_metrics():
        return app.state.forecaster_metrics

    @app.post("/ingest")
    def ingest_readings(
        payload: ReadingsIngest,
        session: Session = Depends(get_session),
    ):
        simulator = session.get(SimulatorState, 1)
        run_id = (
            simulator.run_id
            if simulator and simulator.status == "running" and simulator.run_id
            else "external"
        )
        predictions = store_readings(
            session,
            payload.readings,
            run_id,
            app.state.forecaster,
            simulator.run_instance_id if simulator and simulator.status == "running" else None,
        )
        return {
            "stored_readings": len(payload.readings),
            "predictions_created": len(predictions),
            "latest_forecast": [
                {
                    "made_at_time_h": item.made_at_time_h,
                    "target_time_h": item.target_time_h,
                    "horizon_minutes": item.horizon_minutes,
                    "value": item.value,
                }
                for item in predictions
            ],
        }

    @app.post("/command", response_model=CommandResponse)
    def create_control_command(
        payload: CommandInput,
        session: Session = Depends(get_session),
    ):
        command, accepted = submit_command(
            session,
            payload,
            "manual",
            app.state.feed_limits,
        )
        return command_response(command, accepted)

    @app.post("/api/control/commands", response_model=CommandResponse)
    def create_relative_control_command(
        payload: RelativeCommandInput,
        session: Session = Depends(get_session),
    ):
        if not math.isfinite(payload.apply_after_minutes):
            raise HTTPException(status_code=422, detail="apply_after_minutes must be finite")
        simulator = session.get(SimulatorState, 1)
        if simulator is None:
            raise HTTPException(status_code=503, detail="Simulator state is unavailable")
        command_payload = CommandInput(
            setpoint_name="feed_rate",
            value=payload.value,
            unit=payload.unit,
            apply_at_time_h=simulator.process_time_h + payload.apply_after_minutes / 60,
        )
        command, accepted = submit_command(
            session,
            command_payload,
            "manual",
            app.state.feed_limits,
        )
        return command_response(command, accepted)

    @app.get("/api/control/state")
    def get_control_state(session: Session = Depends(get_session)):
        return control_state_payload(session, app.state.feed_limits)

    @app.get("/api/control/config", response_model=ControllerConfigRead)
    def get_controller_config(session: Session = Depends(get_session)):
        config = session.get(ControlConfig, 1)
        configured = bool(
            config
            and config.do_target_percent is not None
            and config.dwell_minutes is not None
        )
        return ControllerConfigRead(
            do_target_percent=config.do_target_percent if config else None,
            dwell_minutes=config.dwell_minutes if config else None,
            configured=configured,
        )

    @app.put("/api/control/config", response_model=ControllerConfigRead)
    def update_controller_config(
        payload: ControllerConfigUpdate,
        session: Session = Depends(get_session),
    ):
        if not math.isfinite(payload.do_target_percent) or not math.isfinite(
            payload.dwell_minutes
        ):
            raise HTTPException(status_code=422, detail="Controller settings must be finite")
        config = session.get(ControlConfig, 1)
        if config is None:
            config = ControlConfig()
        config.do_target_percent = payload.do_target_percent
        config.dwell_minutes = payload.dwell_minutes
        config.wall_time = datetime.now(timezone.utc)
        session.add(config)
        session.commit()
        return ControllerConfigRead(
            do_target_percent=config.do_target_percent,
            dwell_minutes=config.dwell_minutes,
            configured=True,
        )

    @app.post("/api/simulator/start")
    async def start_simulator(
        payload: SimulatorStart,
        session: Session = Depends(get_session),
    ):
        if payload.start_minute >= len(app.state.runs[payload.run_id].samples):
            raise HTTPException(status_code=422, detail="start_minute is outside the selected run")
        state = session.get(SimulatorState, 1)
        if state is None:
            raise HTTPException(status_code=503, detail="Simulator state is unavailable")
        if state.status == "running":
            raise HTTPException(status_code=409, detail="The simulator is already running")

        pending_commands = session.exec(
            select(ControlCommand).where(ControlCommand.status == "pending")
        ).all()
        for command in pending_commands:
            command.status = "cancelled"
            command.rejection_reason = "The simulator was restarted before the command applied."
            session.add(command)

        sample = app.state.runs[payload.run_id].samples[payload.start_minute]
        state.run_id = payload.run_id
        state.run_instance_id = uuid4().hex
        state.next_index = payload.start_minute
        state.process_time_h = sample["time_h"]
        state.process_minutes_per_second = payload.process_minutes_per_second
        state.current_feed_rate = sample["feed_rate"]
        state.feed_command_active = False
        state.do_deviation = 0.0
        state.status = "running"
        state.wall_time = datetime.now(timezone.utc)
        session.add(state)
        session.commit()
        await stop_simulator_task()
        app.state.simulator_task = asyncio.create_task(simulator_worker(app))
        return {
            "status": state.status,
            "run_id": state.run_id,
            "process_time_h": state.process_time_h,
            "process_minutes_per_second": state.process_minutes_per_second,
        }

    @app.post("/api/simulator/pause")
    async def pause_simulator(session: Session = Depends(get_session)):
        state = session.get(SimulatorState, 1)
        if state is None:
            raise HTTPException(status_code=503, detail="Simulator state is unavailable")
        if state.status == "running":
            state.status = "paused"
            state.wall_time = datetime.now(timezone.utc)
            session.add(state)
            session.commit()
        await stop_simulator_task()
        return {"status": state.status, "process_time_h": state.process_time_h}

    @app.post("/api/simulator/resume")
    async def resume_simulator(session: Session = Depends(get_session)):
        state = session.get(SimulatorState, 1)
        if state is None or state.status != "paused" or state.run_id is None:
            raise HTTPException(status_code=409, detail="The simulator is not paused")
        state.status = "running"
        state.wall_time = datetime.now(timezone.utc)
        session.add(state)
        session.commit()
        await stop_simulator_task()
        app.state.simulator_task = asyncio.create_task(simulator_worker(app))
        return {
            "status": state.status,
            "run_id": state.run_id,
            "process_time_h": state.process_time_h,
        }

    app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")
    return app


app = create_app()
