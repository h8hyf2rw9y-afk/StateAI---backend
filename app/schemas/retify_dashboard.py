import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

RetifyDashboardPeriod = Literal["7d", "30d", "90d", "all"]


class RetifyPerformanceMetrics(BaseModel):
    received: int = 0
    active: int = 0
    closed: int = 0
    archived: int = 0
    contacted: int = 0
    no_answer: int = 0
    follow_ups_overdue: int = 0
    proposals_sent: int = 0
    negotiating: int = 0
    accepted: int = 0
    operations_open: int = 0
    operations_closed: int = 0
    conversion_rate: float = 0


class RetifyAdvisorPerformance(BaseModel):
    user_id: uuid.UUID
    email: str | None
    role: str
    is_active: bool
    metrics: RetifyPerformanceMetrics


class RetifyAttentionItem(BaseModel):
    case_id: uuid.UUID
    owner_name: str
    assigned_user_id: uuid.UUID | None
    advisor_email: str | None
    status: str
    priority: Literal["urgent", "high"]
    reason: str
    next_follow_up_at: datetime | None = None


class RetifyDashboardResponse(BaseModel):
    period: RetifyDashboardPeriod
    assigned_user_id: uuid.UUID | None
    summary: RetifyPerformanceMetrics
    advisors: list[RetifyAdvisorPerformance]
    attention: list[RetifyAttentionItem]
