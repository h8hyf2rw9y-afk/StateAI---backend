from fastapi import APIRouter, Depends

from app.api.routes import (
    activities,
    agent_executions,
    ai,
    appointments,
    audit_logs,
    buyer_requirements,
    calendar_connections,
    contacts,
    features,
    me,
    notifications,
    opportunities,
    organization,
    properties,
    property_interests,
    renova,
    renova_chat,
    tasks,
)
from app.core.renova_access import require_crm_access

# Health lives outside this router — mounted at the app root in main.py,
# unversioned, since uptime checks/load balancers shouldn't care about API versioning.
api_router = APIRouter()

# Everything except /me, /organization and the Renova module is the
# organization's shared CRM — a Renova-only advisor (role renova_agent) gets
# 403 there. Renova itself narrows what such an advisor sees per case
# (see app/core/renova_access.py).
_CRM_ONLY = [Depends(require_crm_access)]
api_router.include_router(me.router)
api_router.include_router(organization.router)
api_router.include_router(contacts.router, dependencies=_CRM_ONLY)
api_router.include_router(properties.router, dependencies=_CRM_ONLY)
api_router.include_router(buyer_requirements.router, dependencies=_CRM_ONLY)
api_router.include_router(opportunities.router, dependencies=_CRM_ONLY)
api_router.include_router(property_interests.router, dependencies=_CRM_ONLY)
api_router.include_router(activities.router, dependencies=_CRM_ONLY)
api_router.include_router(ai.router, dependencies=_CRM_ONLY)
api_router.include_router(agent_executions.router, dependencies=_CRM_ONLY)
api_router.include_router(features.router, dependencies=_CRM_ONLY)
api_router.include_router(audit_logs.router, dependencies=_CRM_ONLY)
api_router.include_router(tasks.router, dependencies=_CRM_ONLY)
api_router.include_router(appointments.router, dependencies=_CRM_ONLY)
api_router.include_router(calendar_connections.router, dependencies=_CRM_ONLY)
api_router.include_router(notifications.router, dependencies=_CRM_ONLY)
api_router.include_router(renova.router)
api_router.include_router(renova_chat.router)
api_router.include_router(renova.pipeline_router)
