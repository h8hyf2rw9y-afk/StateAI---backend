import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.common import ORMModel
from app.schemas.enums import RenovaOperationStage

OperationAction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class RenovaOperationCase(ORMModel):
    """A safe operational card: no protected identifiers, INE images or internal ciphertext."""

    id: uuid.UUID
    owner_name: str
    owner_phone: str
    status: str
    assigned_user_id: uuid.UUID | None
    street_address: str | None
    neighborhood: str | None
    municipality: str | None
    currency: str
    proposal_type: str | None
    debt_coverage_amount: Decimal | None
    owner_cash_offer: Decimal | None
    final_offer: Decimal | None
    operation_stage: str
    operation_next_action: str | None
    operation_due_at: datetime | None
    operation_stage_updated_at: datetime | None
    updated_at: datetime


class RenovaOperationStageGroup(BaseModel):
    stage: str
    cases: list[RenovaOperationCase]


class RenovaOperationsResponse(BaseModel):
    stages: list[RenovaOperationStageGroup]


class RenovaOperationUpdate(BaseModel):
    operation_stage: RenovaOperationStage | None = None
    operation_next_action: OperationAction | None = None
    operation_due_at: datetime | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "RenovaOperationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one operation field is required.")
        if "operation_stage" in self.model_fields_set and self.operation_stage is None:
            raise ValueError("operation_stage cannot be null.")
        return self
