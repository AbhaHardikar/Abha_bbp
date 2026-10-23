
from datetime import date
from typing import Optional

from sqlmodel import SQLModel, Field


class Equipment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)


class Batch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    start_date: date
    end_date: date


class UnitOperation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    type: str
    color: str = "#4F83CC"
    status: str = "draft"
    start_date: date
    end_date: date
    batch_id: int = Field(foreign_key="batch.id")
    equipment_id: int = Field(foreign_key="equipment.id")


class UnitOperationDependency(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_unitop_id: int = Field(
        foreign_key="unitoperation.id"
    )
    to_unitop_id: int = Field(
        foreign_key="unitoperation.id"
    )
